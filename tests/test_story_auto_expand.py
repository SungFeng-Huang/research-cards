"""Safety regressions for the isolated story expansion runner."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / "skills" / "project-card-canvas"
spec = importlib.util.spec_from_file_location("story_auto_expand_under_test",
                                              HERE / "story_auto_expand.py")
SA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SA)


class TestStoryAgentSafety(unittest.TestCase):
    def test_explicit_off_wins_even_when_codex_is_installed(self):
        with mock.patch.dict(os.environ,
                             {"RESEARCH_CARDS_STORY_AGENT": "off"}):
            with self.assertRaisesRegex(RuntimeError, "已停用"):
                SA._run_codex(Path("/tmp"), mock.Mock(), 1)

    def test_compare_and_swap_rejects_concurrent_graph_edit(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "graph.json"
            before = {"nodes": [{"id": "a"}], "edges": []}
            path.write_text(json.dumps(before), encoding="utf-8")
            SA._assert_graph_unchanged(path, before)
            path.write_text(json.dumps({
                "nodes": [{"id": "a"}, {"id": "manual"}], "edges": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "拒絕覆蓋"):
                SA._assert_graph_unchanged(path, before)

    def test_material_uses_full_ids_when_eight_char_prefix_collides(self):
        l1 = "12345678-0000-4000-8000-000000000001"
        l2 = "12345678-0000-4000-8000-000000000002"
        report = {"coverage": {"uncovered_logs": [
            {"log": "12345678", "log_id": l1},
            {"log": "12345678", "log_id": l2},
        ], "uncovered_sections": []}}
        fake_doc = lambda cid: (None, {"content": [  # noqa: E731
            {"type": "paragraph", "content": [
                {"type": "text", "text": cid}]}]})
        with mock.patch.object(SA.M, "scan", return_value={
                "done_logs": [{"log": l1}, {"log": l2}],
                "pending_logs": [], "chain": []}), \
             mock.patch.object(SA.M.L, "read_card", side_effect=fake_doc):
            material = SA._coverage_material("entry", report)
        self.assertIn(f"## LOG {l1}", material)
        self.assertIn(f"## LOG {l2}", material)


if __name__ == "__main__":
    unittest.main()
