#!/usr/bin/env python3
"""Mac-side consumer for cluster project-card-log events.

The bridge drainer copies the cluster's durable JSONL event queue into a local
inbox, then invokes this script.  A batch is processed in the only safe order:

    optional chain repair → pinpoint repair → one note-sync
    → timeline + existing-mode mind map

The inbox is claimed atomically, drained until empty, and re-queued on any
failure.  Every operation is idempotent, so retrying a partially completed
batch is safe.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent
DEFAULT_INBOX = Path(os.path.expanduser(
    os.environ.get("HB_PROJECT_LOG_INBOX",
                   "~/.heptabase-bridge/project-log-events.inbox.jsonl")))
# The hook must keep using the interpreter that successfully imported its own
# dependencies.  PATH may put Apple's dependency-free /usr/bin/python3 ahead
# of the Homebrew/venv interpreter that launched us.
PYTHON = os.environ.get("RESEARCH_CARDS_PYTHON") or sys.executable


def runtime_capabilities():
    """Return (sync_enabled, canvas_enabled) from normalized config."""
    sys.path.insert(0, str(SKILLS / "_shared"))
    import hbconfig
    cfg = hbconfig.load_config()
    backends = set(cfg.get("backends") or [])
    has_local = "local" in backends
    return (("hackmd" in backends
             or {"local", "heptabase"} <= backends),
            has_local)


def valid_event(rec):
    if not isinstance(rec, dict) or rec.get("kind") != "project-card-log":
        return False
    if rec.get("schema") != 1:
        return False
    return (all(isinstance(rec.get(k), str) and 0 < len(rec[k]) <= 256
                for k in ("entry_card", "log_card", "timeline_card"))
            and isinstance(rec.get("repair_chain", False), bool))


def parse_lines(lines):
    events, invalid = [], []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            invalid.append(line)
            continue
        (events if valid_event(rec) else invalid).append(rec)
    return events, invalid


def command_plan(events, capabilities=(True, True)):
    """Coalesce a batch: repair every affected card once, sync once, refresh
    each project once.  Stable order makes reports/tests deterministic."""
    repair_cards = sorted({
        c for e in events for c in (e["timeline_card"], e["log_card"])
    })
    entries = sorted({e["entry_card"] for e in events})
    chain_entries = sorted({e["entry_card"] for e in events
                            if e.get("repair_chain")})
    repair = [PYTHON, str(SKILLS / "project-card-repair" / "repair.py")]
    for cid in repair_cards:
        repair.extend(["--card", cid])
    commands = [
        ("chain-repair", entry,
         [PYTHON, str(HERE / "repair_chain.py"),
          "--card", entry, "--seal"])
        for entry in chain_entries
    ]
    commands.append(("repair", None, repair))
    sync_enabled, canvas_enabled = capabilities
    if sync_enabled:
        commands.append(
            ("note-sync", None,
             [PYTHON, str(SKILLS / "note-sync" / "sync.py")]))
    if canvas_enabled:
        for entry in entries:
            commands.extend([
                ("timeline", entry,
                 [PYTHON,
                  str(SKILLS / "project-card-canvas" / "project_canvas.py"),
                  "--card", entry]),
                ("mindmap", entry,
                 [PYTHON,
                  str(SKILLS / "project-card-canvas" / "context_mindmap.py"),
                  "--card", entry]),
            ])
    return commands


def _json_stdout(run):
    try:
        return json.loads(run.stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def run_pipeline(events, runner=subprocess.run, capabilities=(True, True)):
    reports = []
    for step, entry, cmd in command_plan(events, capabilities=capabilities):
        try:
            run = runner(cmd, capture_output=True, text=True, timeout=3600)
        except Exception as e:                                   # noqa: BLE001
            reports.append({"step": step, "entry": entry,
                            "error": f"{type(e).__name__}: {str(e)[:400]}"})
            return False, reports
        parsed = _json_stdout(run)
        rep = {"step": step, "entry": entry, "rc": run.returncode,
               "report": parsed}
        if run.returncode != 0:
            rep["stderr"] = (run.stderr or "")[-500:]
            reports.append(rep)
            return False, reports
        if not isinstance(parsed, dict):
            rep["error"] = "command returned no JSON object"
            reports.append(rep)
            return False, reports
        # repair.py intentionally continues after a per-card error; automation
        # must not publish a canvas from a batch whose targeted repair failed.
        if step == "repair" and any("error" in r
                                    for r in (parsed or {}).get("results", [])):
            rep["error"] = "targeted repair reported a per-card error"
            reports.append(rep)
            return False, reports
        # A note-sync conflict requires human resolution.  Keep the event
        # pending instead of rendering a knowingly divergent mirror.
        if step == "note-sync" and (parsed or {}).get("total_conflicts", 0):
            rep["error"] = "note-sync reported conflicts"
            reports.append(rep)
            return False, reports
        reports.append(rep)
    return True, reports


def _append_lines(path, lines):
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            if isinstance(line, str):
                f.write(line.rstrip("\n") + "\n")
            else:
                f.write(json.dumps(line, ensure_ascii=False,
                                   separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def consume(inbox, runner=subprocess.run, dry_run=False,
            capabilities=(True, True)):
    inbox = Path(inbox).expanduser()
    lock_path = Path(str(inbox) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a+") as lock:
        # Serialize hook invocations instead of returning "already-running".
        # The waiter must acquire and re-check the inbox after its predecessor
        # exits, otherwise the final arrival can lose its only wake-up.
        fcntl.flock(lock, fcntl.LOCK_EX)
        processing = Path(f"{inbox}.processing")
        total_events = total_invalid = batches = 0
        projects, reports = set(), []
        while True:
            # A prior process may have died after the atomic claim. Resume that
            # older batch first, then claim any inbox that landed meanwhile.
            if not processing.exists():
                if not inbox.exists() or inbox.stat().st_size == 0:
                    break
                os.replace(inbox, processing)
            lines = processing.read_text(encoding="utf-8").splitlines()
            events, invalid = parse_lines(lines)
            if dry_run:
                _append_lines(inbox, lines)
                processing.unlink(missing_ok=True)
                return {"status": "dry-run", "events": len(events),
                        "invalid": len(invalid),
                        "plan": [{"step": s, "entry": e, "command": c}
                                 for s, e, c in command_plan(
                                     events, capabilities=capabilities)]}
            batches += 1
            total_events += len(events)
            total_invalid += len(invalid)
            projects.update(e["entry_card"] for e in events)
            if invalid:
                _append_lines(Path(str(inbox) + ".invalid.jsonl"), invalid)
            if events:
                ok, batch_reports = run_pipeline(
                    events, runner=runner, capabilities=capabilities)
                reports.extend(batch_reports)
                if not ok:
                    _append_lines(inbox, events)
                    processing.unlink(missing_ok=True)
                    return {"status": "retry", "events": total_events,
                            "invalid": total_invalid,
                            "projects": sorted(projects),
                            "reports": reports, "batches": batches}
            processing.unlink(missing_ok=True)

        if not batches:
            return {"status": "empty", "inbox": str(inbox)}
        return {"status": "ok" if total_events else "invalid-only",
                "events": total_events, "invalid": total_invalid,
                "projects": sorted(projects), "reports": reports,
                "batches": batches}


def main():
    ap = argparse.ArgumentParser(
        description="Consume cluster project-log events on the Mac.")
    ap.add_argument("--inbox", default=str(DEFAULT_INBOX))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    report = consume(args.inbox, dry_run=args.dry_run,
                     capabilities=runtime_capabilities())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report.get("status") == "retry" else 0


if __name__ == "__main__":
    raise SystemExit(main())
