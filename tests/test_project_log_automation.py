"""Cluster project-log event handoff + Mac post-log orchestrator."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_DIR = REPO / "skills" / "project-card-log"
sys.path.insert(0, str(LOG_DIR))
sys.path.insert(0, str(REPO / "skills" / "_shared"))

import append_card as AC  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "post_log_sync_under_test", LOG_DIR / "post_log_sync.py")
PLS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PLS)


def event(entry="entry-1", log="log-1", timeline="tail-1", eid="ev-1"):
    return {"schema": 1, "kind": "project-card-log", "event_id": eid,
            "created_at": "2026-07-23T00:00:00+00:00",
            "entry_card": entry, "log_card": log,
            "timeline_card": timeline}


class TestClusterEventQueue(unittest.TestCase):
    def test_enqueue_is_jsonl_and_durable_shape(self):
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "nested" / "events.jsonl"
            got = AC.enqueue_project_log_event({
                "entry": "entry", "log_card": "log",
                "appended_to": "tail"}, path=str(queue))
            rec = json.loads(queue.read_text())
            self.assertEqual(rec["kind"], "project-card-log")
            self.assertEqual((rec["entry_card"], rec["log_card"],
                              rec["timeline_card"]),
                             ("entry", "log", "tail"))
            self.assertEqual(got["event_id"], rec["event_id"])
            self.assertFalse(rec["repair_chain"])
            self.assertEqual(queue.stat().st_mode & 0o777, 0o600)

    def test_failed_spill_seal_requests_chain_repair(self):
        with tempfile.TemporaryDirectory() as td:
            queue = Path(td) / "events.jsonl"
            AC.enqueue_project_log_event({
                "entry": "entry", "log_card": "log", "appended_to": "child",
                "overflowed": True, "sealed": False}, path=str(queue))
            self.assertTrue(json.loads(queue.read_text())["repair_chain"])


class TestPostLogPlan(unittest.TestCase):
    def test_coalesces_cards_and_projects_in_safe_order(self):
        plan = PLS.command_plan([
            event(), event(log="log-2", timeline="tail-1", eid="ev-2"),
            event(entry="entry-2", log="log-3", timeline="tail-2", eid="ev-3"),
        ])
        self.assertEqual([p[0] for p in plan],
                         ["repair", "note-sync",
                          "timeline", "mindmap", "timeline", "mindmap"])
        repair = plan[0][2]
        cards = [repair[i + 1] for i, arg in enumerate(repair[:-1])
                 if arg == "--card"]
        self.assertEqual(cards, ["log-1", "log-2", "log-3",
                                 "tail-1", "tail-2"])
        self.assertEqual([p[1] for p in plan[2:]],
                         ["entry-1", "entry-1", "entry-2", "entry-2"])

    def test_failed_spill_seal_runs_chain_walk_before_pinpoint_repair(self):
        e = event()
        e["repair_chain"] = True
        plan = PLS.command_plan([e])
        self.assertEqual([p[0] for p in plan],
                         ["chain-repair", "repair", "note-sync",
                          "timeline", "mindmap"])
        self.assertEqual(plan[0][2][-3:], ["--card", "entry-1", "--seal"])

    def test_heptabase_only_still_consumes_repair(self):
        plan = PLS.command_plan([event()], capabilities=(False, False))
        self.assertEqual([p[0] for p in plan], ["repair"])


class TestPostLogConsume(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc-post-log-"))
        self.inbox = self.tmp / "events.jsonl"

    @staticmethod
    def ok_runner(cmd, **kwargs):
        if "repair.py" in cmd[1]:
            out = {"results": []}
        elif "note-sync" in cmd[1]:
            out = {"total_conflicts": 0}
        elif "context_mindmap.py" in cmd[1]:
            out = {"mode": "logs", "logs_total": 1, "logs_mapped": 1}
        else:
            out = {"ok": True}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

    def write(self, *records):
        self.inbox.write_text("".join(
            json.dumps(r) + "\n" if not isinstance(r, str) else r + "\n"
            for r in records))

    def test_success_consumes_inbox(self):
        self.write(event())
        rep = PLS.consume(self.inbox, runner=self.ok_runner)
        self.assertEqual(rep["status"], "ok")
        self.assertFalse(self.inbox.exists())
        self.assertEqual([r["step"] for r in rep["reports"]],
                         ["repair", "note-sync", "timeline", "mindmap"])

    def test_conflict_requeues_for_retry(self):
        self.write(event())

        def runner(cmd, **kwargs):
            if "repair.py" in cmd[1]:
                out = {"results": []}
            else:
                out = {"total_conflicts": 2}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

        rep = PLS.consume(self.inbox, runner=runner)
        self.assertEqual(rep["status"], "retry")
        self.assertEqual(json.loads(self.inbox.read_text())["event_id"], "ev-1")
        self.assertEqual([r["step"] for r in rep["reports"]],
                         ["repair", "note-sync"])

    def test_failed_canvas_requeues_whole_idempotent_batch(self):
        self.write(event())

        def runner(cmd, **kwargs):
            if "project_canvas.py" in cmd[1]:
                return subprocess.CompletedProcess(cmd, 1, "", "boom")
            return self.ok_runner(cmd, **kwargs)

        rep = PLS.consume(self.inbox, runner=runner)
        self.assertEqual(rep["status"], "retry")
        self.assertTrue(self.inbox.exists())
        self.assertEqual(rep["reports"][-1]["step"], "timeline")

    def test_story_gap_runs_guarded_semantic_expansion(self):
        self.write(event())

        def runner(cmd, **kwargs):
            if "repair.py" in cmd[1]:
                out = {"results": []}
            elif "note-sync" in cmd[1]:
                out = {"total_conflicts": 0}
            elif "context_mindmap.py" in cmd[1]:
                out = {"mode": "story", "coverage": {
                    "uncovered_logs": [{"log": "log-1"}],
                    "uncovered_sections": []}}
            elif "story_auto_expand.py" in cmd[1]:
                out = {"status": "expanded"}
            else:
                out = {"ok": True}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

        rep = PLS.consume(self.inbox, runner=runner)
        self.assertEqual(rep["status"], "ok")
        self.assertEqual([r["step"] for r in rep["reports"]][-2:],
                         ["mindmap", "story-expand"])

    def test_story_agent_failure_requeues_batch(self):
        self.write(event())

        def runner(cmd, **kwargs):
            if "repair.py" in cmd[1]:
                out = {"results": []}
            elif "note-sync" in cmd[1]:
                out = {"total_conflicts": 0}
            elif "context_mindmap.py" in cmd[1]:
                out = {"mode": "story", "coverage": {
                    "uncovered_logs": [{"log": "log-1"}],
                    "uncovered_sections": []}}
            elif "story_auto_expand.py" in cmd[1]:
                return subprocess.CompletedProcess(cmd, 1, "{}", "agent down")
            else:
                out = {"ok": True}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")

        rep = PLS.consume(self.inbox, runner=runner)
        self.assertEqual(rep["status"], "retry")
        self.assertEqual(rep["reports"][-1]["step"], "story-expand")

    def test_invalid_lines_are_quarantined_not_retried(self):
        self.write("not-json", {"kind": "wrong"}, event())
        rep = PLS.consume(self.inbox, runner=self.ok_runner)
        self.assertEqual((rep["status"], rep["invalid"]), ("ok", 2))
        invalid = Path(str(self.inbox) + ".invalid.jsonl")
        self.assertEqual(len(invalid.read_text().splitlines()), 2)

    def test_dry_run_restores_inbox(self):
        self.write(event())
        rep = PLS.consume(self.inbox, dry_run=True)
        self.assertEqual(rep["status"], "dry-run")
        self.assertTrue(self.inbox.exists())
        self.assertEqual(len(rep["plan"]), 4)

    def test_resumes_processing_file_after_crash(self):
        processing = Path(str(self.inbox) + ".processing")
        processing.write_text(json.dumps(event(eid="old")) + "\n")
        self.write(event(eid="new"))
        rep = PLS.consume(self.inbox, runner=self.ok_runner)
        self.assertEqual(rep["status"], "ok")
        self.assertFalse(processing.exists())
        self.assertFalse(self.inbox.exists())
        self.assertEqual((rep["events"], rep["batches"]), (2, 2))

    def test_child_commands_keep_hook_interpreter(self):
        self.assertEqual(PLS.PYTHON, sys.executable)
        self.assertTrue(all(cmd[0] == sys.executable
                            for _, _, cmd in PLS.command_plan([event()])))

    def test_resumes_processing_without_any_new_inbox(self):
        processing = Path(str(self.inbox) + ".processing")
        processing.write_text(json.dumps(event(eid="old")) + "\n")
        rep = PLS.consume(self.inbox, runner=self.ok_runner)
        self.assertEqual(rep["status"], "ok")
        self.assertFalse(processing.exists())

    def test_runner_exception_requeues_instead_of_stranding_processing(self):
        self.write(event())

        def explode(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 3600)

        rep = PLS.consume(self.inbox, runner=explode)
        self.assertEqual(rep["status"], "retry")
        self.assertTrue(self.inbox.exists())
        self.assertFalse(Path(str(self.inbox) + ".processing").exists())


if __name__ == "__main__":
    unittest.main()
