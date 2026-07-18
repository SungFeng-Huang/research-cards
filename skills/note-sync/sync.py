#!/usr/bin/env python3
"""note-sync — one entry point for the whole note-surface sync chain.

The topology is a STAR: local (the plain-.md data floor) is always the
hub, and every enabled surface syncs over its own local ↔ surface
segment. When `backends` names other surfaces but not "local", the hub is
injected implicitly (store defaults to ~/.local/share/research-cards/store).

    Heptabase ◀─(heptabase segment)─▶ local ◀─(hackmd segment)─▶ HackMD

Segments (each an engine skill, runnable standalone):
  heptabase — local ↔ Heptabase, block-level level 2 (engine:
              skills/heptabase-sync/; "obsidian" is the pre-star alias)
  hackmd    — local ↔ HackMD, paragraph-level write-back (engine:
              skills/hackmd-sync/)
  Reverse mode: backends: ["local", "heptabase"] makes the store the
  canonical and Heptabase a rebuildable VIEW — deleting an .md trashes
  the card; a card removed on Heptabase is rebuilt by adoption.

Without --mode, every applicable segment runs canonical-outward, then a
convergence pass: if hackmd-sync wrote HackMD edits back into the vault,
heptabase-sync runs once more so they reach Heptabase in the same
invocation. One aggregated JSON report; conflicts from all segments are
surfaced together.

Usage:
    python3 sync.py                  # full chain per config backends
    python3 sync.py --mode hackmd    # just one segment
    python3 sync.py --dry-run
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_shared"))

import hbconfig  # noqa: E402

ENGINES = {
    "heptabase": os.path.join(HERE, "..", "heptabase-sync", "sync.py"),
    "hackmd": os.path.join(HERE, "..", "hackmd-sync", "sync.py"),
}
MODE_ALIASES = {"obsidian": "heptabase"}   # pre-star-topology segment name


def run_engine(mode, dry=False):
    args = [sys.executable, ENGINES[mode]] + (["--dry-run"] if dry else [])
    r = subprocess.run(args, capture_output=True, text=True, timeout=3600)
    try:
        report = json.loads(r.stdout)
    except Exception:                                        # noqa: BLE001
        report = {"unparsed_output": (r.stdout or "")[-400:]}
    out = {"mode": mode, "rc": r.returncode, "report": report}
    if r.returncode != 0:
        out["stderr"] = (r.stderr or "")[-400:]
    return out


def plan_from_config(cfg):
    """Star topology: local is always the hub; one segment per OTHER
    enabled surface, canonical's segment first."""
    bk = cfg.get("backends") or []
    plan = []
    if {"heptabase", "local"} <= set(bk):
        plan.append("heptabase")
    if "hackmd" in bk:
        plan.append("hackmd")
    return plan


def is_fatal(segment):
    """A segment is fatal when its process failed or it aborted early
    (quota exhaustion) — downstream segments would then publish from a
    stale vault. Per-card `errors` are NOT fatal: the engines are
    incremental and self-healing by design."""
    return segment["rc"] != 0 or bool((segment.get("report") or {}).get("aborted"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode",
                    choices=sorted(ENGINES) + sorted(MODE_ALIASES),
                    help="run a single segment instead of the whole chain")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = hbconfig.load_config()
    mode = MODE_ALIASES.get(args.mode, args.mode)
    plan = [mode] if mode else plan_from_config(cfg)
    if not plan:
        sys.exit("backends 沒有可同步的段——單一庫且無 hackmd 時沒有東西要收斂"
                 f"（目前 backends={cfg.get('backends')}）")

    # run segment by segment: a fatal upstream (dead process / quota abort)
    # must not let a downstream segment publish from a stale vault
    segments, skipped = [], []
    for i, m in enumerate(plan):
        seg = run_engine(m, dry=args.dry_run)
        segments.append(seg)
        if is_fatal(seg):
            skipped = [{"mode": rest, "skipped_because":
                        f"上游段 {m} 失敗（rc={seg['rc']}"
                        f"{'，aborted' if (seg.get('report') or {}).get('aborted') else ''}）"
                        "——避免用過期狀態發佈"}
                       for rest in plan[i + 1:]]
            break

    # convergence: HackMD-side edits that hackmd-sync wrote back into the
    # vault still need heptabase-sync to carry them on to Heptabase
    if not args.dry_run and not skipped and "hackmd" in plan \
            and "heptabase" in plan:
        wb = (segments[-1].get("report") or {}).get("written_back")
        if wb:
            segments.append(run_engine("heptabase"))

    conflicts = []
    for s in segments:
        for c in (s.get("report") or {}).get("conflicts") or []:
            conflicts.append({"mode": s["mode"],
                              **(c if isinstance(c, dict) else {"item": c})})
    print(json.dumps({"plan": plan,
                      "segments": segments,
                      "skipped": skipped,
                      "total_conflicts": len(conflicts),
                      "conflicts": conflicts},
                     ensure_ascii=False, indent=1))
    if skipped or any(is_fatal(s) for s in segments):
        sys.exit(1)


if __name__ == "__main__":
    main()
