#!/usr/bin/env python3
"""project-card-repair — seal TEXT-form card links (bridge/CLI spills) in
project + progress cards back into real card-mention nodes.

WHY this exists: a `hb` bridge append (remote cluster) or a bare CLI append
writes a card link as the plain-text literal `[[card:<uuid>]]` — the heptabase
CLI does NOT auto-render it, so the link shows as dead text in the UI and is
invisible to PM-level chain parsers. Three header/timeline shapes hit this:

  * log/progress card header  「專案：[[card:<project>]]　環境：…」   (log → project)
  * project card timeline line 「📎 <date>　[[card:<log>]]　<summary>」 (project → log)
  * continuation child header  「…母卡：[[card:<entry>]]。…」          (chain child → entry)

Invocation (mirrors the ask — id given ⇒ pinpoint, none ⇒ sweep all):
  python3 repair.py --card <id> [--card <id> …]   # repair only these cards
  python3 repair.py                               # scan EVERY project + progress card
  python3 repair.py --dry-run                      # preview; save nothing
  python3 repair.py --include-sentinel             # also seal ▶續卡 sentinels (see NOTE)

NOTE on sentinels: the ▶續卡（本卡已達容量上限）：[[card:…]] chain edge is ALSO a
text-form spill, but sealing it has chain semantics — the canonical fix is
`project-card-log/repair_chain.py --seal <entry>`, which WALKS the chain and
guards against re-linking a deliberately folded+trashed continuation. This
skill leaves sentinels alone unless --include-sentinel is passed (single-card
seal, no walk); use it only when you know the continuation is live.

Design: the split-in-place seal logic lives ONCE in project-card-log/
append_card.py (seal_loglink / seal_backref / seal_sentinel). This skill only
routes cards to those helpers — it does not reimplement them. Heptabase-only:
obsidian .md stores links as [[wikilink]] and never has this gap. Read/save go
through rewrite_lib (md5-guarded — a concurrent edit aborts the save)."""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "_shared"))
sys.path.insert(0, os.path.join(_HERE, "..", "card-rewrite"))
sys.path.insert(0, os.path.join(_HERE, "..", "project-card-log"))

import append_card as AC      # noqa: E402  seal_{loglink,backref,sentinel}_paragraphs
import rewrite_lib as L       # noqa: E402  read_card / save_card (md5-guarded, backend-aware)
import hbconfig               # noqa: E402  collection tag ids from config

# both header back-ref shapes seal with the same split: chain 母卡 + log 專案
SEAL_MARKS = (AC.BACKREF_MARK, AC.PROJECTREF_MARK)


def _cli(*args):
    r = subprocess.run(["heptabase", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"heptabase {' '.join(args)}: {(r.stderr or '').strip()[:160]}")
    return json.loads(r.stdout)


# collection key -> default tag name. progress is OPTIONAL in config.example,
# so its tag_id is often unset — resolving by NAME instead of silently skipping
# is essential: the log cards under project/progress are exactly the ones whose
# 專案：[[card:…]] back-refs this skill most needs to repair.
_DEFAULT_TAG_NAMES = {"projects": "project", "progress": "project/progress"}


def _resolve_tag_id(key):
    """Tag id for a collection: config tag_id first, else resolve the tag NAME
    (config tag_name, else the default) via `heptabase tag list`. Returns
    (tag_id, warning); warning is set (tag_id None) only when neither path
    resolves, so the caller can surface it instead of silently dropping a whole
    collection — a dropped collection means unrepaired cards reported as clean."""
    tid = hbconfig.hb_id("collections", key, "tag_id")
    if tid:
        return tid, None
    name = hbconfig.hb_id("collections", key, "tag_name") or _DEFAULT_TAG_NAMES.get(key)
    if not name:
        return None, f"collection '{key}': no tag_id and no tag name to resolve"
    try:
        for t in _cli("tag", "list").get("tags", []):
            if t.get("name") == name:
                return t["id"], None
    except Exception as e:
        return None, f"collection '{key}': tag list failed ({str(e)[:80]})"
    return None, f"collection '{key}': tag '{name}' not found"


def scan_target_ids():
    """((id, title) list, warnings): every card under the project + progress
    collections, plus a warning for any collection that could NOT be resolved.
    Never silently skips a collection — an unresolved progress tag would drop
    every log card while still reporting success."""
    out, warnings = [], []
    for key in ("projects", "progress"):
        tid, warn = _resolve_tag_id(key)
        if warn:
            warnings.append(warn)
            continue
        for c in _cli("tag", "cards", tid).get("cards", []):
            out.append((c["id"], c.get("title", "")))
    return out, warnings


def repair_card(cid, include_sentinel=False, dry_run=False):
    """Seal one card in place; return a report dict. No-op (sealed=0) on cards
    that carry no text-form link — safe to run on any card id."""
    md5, doc = L.read_card(cid)
    nodes = doc["content"]
    by_kind = {
        "loglink": AC.seal_loglink_paragraphs(nodes),                 # 📎 timeline
        "backref": AC.seal_backref_paragraphs(nodes, marks=SEAL_MARKS),  # 母卡:/專案:
    }
    if include_sentinel:
        by_kind["sentinel"] = AC.seal_sentinel_paragraphs(nodes)      # ▶ 續卡
    total = sum(by_kind.values())
    if total and not dry_run:
        L.save_card(cid, md5, doc)
    return {"card": cid, "sealed": total,
            "by_kind": {k: v for k, v in by_kind.items() if v},
            "dry_run": dry_run}


def main():
    ap = argparse.ArgumentParser(
        description="Seal text-form card links in project/progress cards.")
    ap.add_argument("--card", action="append", default=[], metavar="ID",
                    help="card id to repair (repeatable); omit to sweep every "
                         "project + progress card")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview what would seal; save nothing")
    ap.add_argument("--include-sentinel", action="store_true",
                    help="also seal ▶續卡 sentinels on the target card (no "
                         "chain walk — prefer repair_chain.py --seal)")
    args = ap.parse_args()

    scan_warnings = []
    if args.card:
        targets = [(c, "") for c in args.card]
    else:
        targets, scan_warnings = scan_target_ids()

    results, changed = [], 0
    for cid, title in targets:
        try:
            r = repair_card(cid, include_sentinel=args.include_sentinel,
                            dry_run=args.dry_run)
        except Exception as e:  # one bad card must not abort the sweep
            r = {"card": cid, "error": str(e)[:160]}
        r["title"] = title
        if r.get("sealed"):
            changed += 1
        results.append(r)

    print(json.dumps({
        "mode": "card" if args.card else "scan-all",
        "dry_run": args.dry_run,
        "include_sentinel": args.include_sentinel,
        "scanned": len(targets),
        "cards_changed": changed,
        # surface unresolved collections loudly — a missing progress tag would
        # otherwise drop every log card and still look like a clean sweep
        "warnings": scan_warnings,
        # keep the report lean: only cards that changed or errored
        "results": [r for r in results if r.get("sealed") or r.get("error")],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
