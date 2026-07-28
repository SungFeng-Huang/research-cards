#!/usr/bin/env python3
"""Run the canonical Mac post-mutation pipeline for project-card entries.

project-card-merge and project-card-cleanup mutate an existing project chain
directly on the Mac, so they do not pass through the cluster event inbox.
This direct-entry wrapper deliberately reuses post_log_sync's pipeline rather
than maintaining a second orchestration path:

    chain seal → pinpoint repair → note-sync
    → timeline + existing-mode mind map → guarded story expansion

Every step is idempotent. A failed step returns a non-zero exit status and the
JSON report names the last completed operation; the caller can fix the cause
and rerun the same command.
"""
import argparse
import json
import subprocess

import post_log_sync as PLS


def events_for_entries(entries):
    """Translate direct mutations into the canonical pipeline event shape.

    All pinpoint targets intentionally use the entry: repair_chain --seal
    walks every live continuation and seals timeline/back-reference links
    before project-card-repair checks the entry itself.
    """
    unique = sorted(set(entries))
    if not unique:
        raise ValueError("at least one --card ENTRY_ID is required")
    for entry in unique:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError("card ids must be non-empty strings")
        if len(entry) > 256:
            raise ValueError("card ids must be at most 256 characters")
    return [{
        "schema": 1,
        "kind": "project-card-log",
        "entry_card": entry,
        "log_card": entry,
        "timeline_card": entry,
        "repair_chain": True,
        "repair_inline_links": False,
    } for entry in unique]


def process(entries, runner=subprocess.run, capabilities=(True, True),
            dry_run=False):
    events = events_for_entries(entries)
    if dry_run:
        return {
            "status": "dry-run",
            "projects": [e["entry_card"] for e in events],
            "plan": [
                {"step": step, "entry": entry, "command": command}
                for step, entry, command in PLS.command_plan(
                    events, capabilities=capabilities)
            ],
        }
    ok, reports = PLS.run_pipeline(
        events, runner=runner, capabilities=capabilities)
    return {
        "status": "ok" if ok else "failed",
        "projects": [e["entry_card"] for e in events],
        "reports": reports,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Converge project-card mutations on the Mac.")
    ap.add_argument("--card", action="append", required=True, metavar="ENTRY_ID",
                    help="project ENTRY card id (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    report = process(args.card, dry_run=args.dry_run,
                     capabilities=PLS.runtime_capabilities())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
