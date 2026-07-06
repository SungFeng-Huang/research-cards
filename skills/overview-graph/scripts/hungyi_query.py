#!/usr/bin/env python3
"""One-command freshness + query for the hung-yi-lee mixed knowledge graph.

Two modes, by design (lecture sync is network-heavy and dirties the fork
tree, so it belongs to the ROUTINE, not to interactive queries):

  QUERY mode  —  python3 hungyi_query.py "全雙工 語音語言模型"
      card-side freshness (export_hungyi_corpus.py --if-stale --build,
      incremental, <2s when fresh) then `graph query`. Lecture data is NOT
      synced (fast + no surprise dirty tree); `--sync-lectures` opts in.

  REFRESH mode —  python3 hungyi_query.py --refresh-only
      For the scholar-inbox desktop routine's closing step: lecture-side
      refresh (sync-metadata + sync-transcripts + tracked `graph build`,
      throttled to once per --lecture-ttl hours, default 24, age measured on
      raw/youtube/channel_videos.json) then card-side freshness. A lecture
      refresh regenerates tracked fork files (raw/, wiki/) — this wrapper
      never commits; the ROUTINE session (model in the loop) commits the
      fork + bumps the submodule pointer right after, per push rules.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
_DIR = os.path.dirname(os.path.realpath(__file__))
SKILL_ROOT = os.environ.get(
    "HUNGYI_ROOT", os.path.expanduser("~/.claude/skills/hung-yi-lee"))


def _py(args, **kw):
    """Run hungyi_kb.py through the skill's conda env when available."""
    kb = os.path.join(SKILL_ROOT, "scripts", "hungyi_kb.py")
    cmd = (["conda", "run", "-n", "hung-yi-lee"] if shutil.which("conda") else []) + \
          ["python3", kb] + args
    return subprocess.run(cmd, cwd=SKILL_ROOT, **kw)


def lectures_age_hours():
    meta = os.path.join(SKILL_ROOT, "raw", "youtube", "channel_videos.json")
    if not os.path.exists(meta):
        return float("inf")
    return (time.time() - os.path.getmtime(meta)) / 3600


def refresh_lectures(limit):
    for step in (["sync-metadata"], ["sync-transcripts", "--limit", str(limit)],
                 ["graph", "build"]):
        r = _py(step)
        if r.returncode != 0:
            # Lecture refresh is best-effort: a YouTube hiccup must not block
            # the query itself. Report and move on.
            print(f"[hungyi-query] WARNING: {' '.join(step)} failed "
                  f"(rc={r.returncode}) — continuing with existing data",
                  file=sys.stderr)
            return
    print("[hungyi-query] lecture data refreshed — the fork tree now has "
          "uncommitted regenerated files (raw/, wiki/); commit it when convenient")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*", help="graph query text")
    ap.add_argument("--refresh-only", action="store_true",
                    help="refresh lecture data + card corpus, skip the query")
    ap.add_argument("--sync-lectures", action="store_true",
                    help="force the lecture-side refresh (any mode)")
    ap.add_argument("--lecture-ttl", type=float, default=24.0,
                    help="hours between automatic lecture refreshes in "
                         "--refresh-only mode (default 24)")
    ap.add_argument("--transcript-limit", type=int, default=50)
    args = ap.parse_args()
    if not args.refresh_only and not args.query:
        ap.error("give a query, or use --refresh-only")
    if args.refresh_only and args.query:
        ap.error("--refresh-only does not accept query text")
    import math
    if not math.isfinite(args.lecture_ttl) or args.lecture_ttl < 0:
        ap.error("--lecture-ttl must be a finite non-negative number")
    if args.transcript_limit <= 0:
        ap.error("--transcript-limit must be positive")

    # Lecture sync: routine's --refresh-only mode (TTL-throttled) or explicit
    # --sync-lectures. Plain query mode never touches it.
    if args.sync_lectures:
        refresh_lectures(args.transcript_limit)
    elif args.refresh_only:
        age = lectures_age_hours()
        if age >= args.lecture_ttl:
            print(f"[hungyi-query] lecture data is {age:.1f}h old — refreshing "
                  f"(ttl {args.lecture_ttl}h)")
            refresh_lectures(args.transcript_limit)
        else:
            print(f"[hungyi-query] lecture data fresh ({age:.1f}h < "
                  f"{args.lecture_ttl}h ttl) — sync skipped")

    r = subprocess.run(
        [sys.executable, os.path.join(_DIR, "export_hungyi_corpus.py"),
         "--if-stale", "--build"])
    if r.returncode != 0:
        print(f"ERROR: card-corpus freshness failed (rc={r.returncode})",
              file=sys.stderr)
        sys.exit(r.returncode)

    if args.refresh_only:
        print("[hungyi-query] refresh complete")
        return
    r = _py(["graph", "query", " ".join(args.query)])
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
