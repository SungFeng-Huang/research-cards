#!/usr/bin/env python3
"""note-sync — one entry point for the whole note-surface sync chain.

The chain is a sequence of adjacent two-way segments, derived from the
config `backends` list (first = canonical):

    Heptabase ◀──(obsidian-sync)──▶ vault/local ◀──(hackmd-sync)──▶ HackMD

Modes (each an existing engine, unchanged in place):
  obsidian — Heptabase ↔ vault, block-level level 2 (needs both stores in
             `backends`: ["heptabase", "local"])
  hackmd   — local backend ↔ HackMD, paragraph-level write-back (needs
             "hackmd" in `backends`)
  (a reverse "heptabase" mode — vault-canonical mirrored INTO Heptabase —
  is roadmap; `backends: ["local", "heptabase"]` is rejected until then)

Without --mode, every applicable segment runs canonical-outward, then a
convergence pass: if hackmd-sync wrote HackMD edits back into the vault,
obsidian-sync runs once more so they reach Heptabase in the same
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
    "obsidian": os.path.join(HERE, "..", "obsidian-sync", "sync.py"),
    "hackmd": os.path.join(HERE, "..", "hackmd-sync", "sync.py"),
}


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
    bk = cfg.get("backends") or []
    plan = []
    if {"heptabase", "local"} <= set(bk):
        plan.append("obsidian")
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
    ap.add_argument("--mode", choices=sorted(ENGINES),
                    help="run a single segment instead of the whole chain")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = hbconfig.load_config()
    plan = [args.mode] if args.mode else plan_from_config(cfg)
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
    # vault still need obsidian-sync to carry them on to Heptabase
    if not args.dry_run and not skipped and "hackmd" in plan \
            and "obsidian" in plan:
        wb = (segments[-1].get("report") or {}).get("written_back")
        if wb:
            segments.append(run_engine("obsidian"))

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
