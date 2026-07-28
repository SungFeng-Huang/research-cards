#!/usr/bin/env python3
"""project-card-repair — seal TEXT-form card links (bridge/CLI spills) in
project + progress cards back into real card-mention nodes.

WHY this exists: a `hb` bridge append (remote cluster) or a bare CLI append
writes a card link as the plain-text literal `[[card:<uuid>]]` — the heptabase
CLI does NOT auto-render it, so the link shows as dead text in the UI and is
invisible to PM-level chain parsers. Three header/timeline shapes always hit this:

  * log/progress card header  「專案：[[card:<project>]]　環境：…」   (log → project)
  * project card timeline line 「📎 <date>　[[card:<log>]]　<summary>」 (project → log)
  * continuation child header  「…母卡：[[card:<entry>]]。…」          (chain child → entry)

Progress/log card prose can also contain citations such as
「見 [[card:<previous-log>]]」. Use --inline-card for those cards: live
(non-trashed) targets are sealed recursively, while inline-code and code blocks
stay literal.

Invocation (mirrors the ask — id given ⇒ pinpoint, none ⇒ sweep all):
  python3 repair.py --card <id> [--card <id> …]   # repair only these cards
  python3 repair.py --inline-card <id>             # also seal safe prose links
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
append_card.py (seal_loglink / seal_backref / seal_sentinel / seal_inline).
This skill only routes cards to those helpers — it does not reimplement them.
Heptabase-only:
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
    targets, warnings = scan_targets()
    return [(cid, title) for cid, title, _ in targets], warnings


def scan_targets():
    """((id, title, inline) list, warnings) for the automatic full sweep.

    Project cards get only structural header/timeline repair. Progress cards
    additionally get safe inline citation repair. A card in both collections
    is deduplicated and takes the inline-enabled mode.
    """
    out, order, warnings = {}, [], []
    for key in ("projects", "progress"):
        tid, warn = _resolve_tag_id(key)
        if warn:
            warnings.append(warn)
            continue
        for c in _cli("tag", "cards", tid).get("cards", []):
            cid = c["id"]
            if cid not in out:
                order.append(cid)
                out[cid] = [c.get("title", ""), False]
            out[cid][1] = out[cid][1] or key == "progress"
    return [(cid, out[cid][0], out[cid][1]) for cid in order], warnings


_LIVE_CARD_IDS = None


def _live_card_ids():
    """Snapshot every non-trashed Card Library id, once per invocation.

    `note read` is unsuitable here: Heptabase deliberately lets it read cards
    in trash. `card list` excludes trashed cards, is read-only, and covers all
    card types that a card mention may target. Fail closed if pagination is
    malformed or incomplete; the post-log hook will retain the event for retry.
    """
    global _LIVE_CARD_IDS
    if _LIVE_CARD_IDS is not None:
        return _LIVE_CARD_IDS
    ids, offset, limit = set(), 0, 100
    while True:
        page = _cli("card", "list", "--offset", str(offset),
                    "--limit", str(limit))
        results = page.get("results")
        total = page.get("total")
        if not isinstance(results, list) or not isinstance(total, int):
            raise RuntimeError("card list returned malformed pagination")
        ids.update(c["id"] for c in results if isinstance(c.get("id"), str))
        offset += len(results)
        if offset >= total:
            break
        if not results:
            raise RuntimeError(
                f"card list pagination stopped at {offset}/{total}")
    _LIVE_CARD_IDS = ids
    return ids


def _card_exists(cid):
    """Safety gate for prose conversion: target must be live, not just readable."""
    return cid in _live_card_ids()


def repair_card(cid, include_sentinel=False, include_inline=False,
                dry_run=False):
    """Seal one card in place; return a report dict. No-op (sealed=0) on cards
    that carry no text-form link — safe to run on any card id."""
    md5, doc = L.read_card(cid)
    nodes = doc["content"]
    by_kind = {
        "loglink": AC.seal_loglink_paragraphs(nodes),                 # 📎 timeline
        "backref": AC.seal_backref_paragraphs(nodes, marks=SEAL_MARKS),  # 母卡:/專案:
    }
    missing = set()
    if include_inline:
        by_kind["inline"] = AC.seal_inline_card_literals(
            nodes, card_exists=_card_exists, missing=missing)
    if include_sentinel:
        by_kind["sentinel"] = AC.seal_sentinel_paragraphs(nodes)      # ▶ 續卡
    total = sum(by_kind.values())
    if total and not dry_run:
        L.save_card(cid, md5, doc)
    return {"card": cid, "sealed": total, "inline": include_inline,
            "by_kind": {k: v for k, v in by_kind.items() if v},
            "missing_inline_targets": sorted(missing),
            "dry_run": dry_run}


def main():
    ap = argparse.ArgumentParser(
        description="Seal text-form card links in project/progress cards.")
    ap.add_argument("--card", action="append", default=[], metavar="ID",
                    help="card id to repair (repeatable); omit to sweep every "
                         "project + progress card")
    ap.add_argument("--inline-card", action="append", default=[], metavar="ID",
                    help="progress/log card to repair, including safe inline "
                         "prose citations (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview what would seal; save nothing")
    ap.add_argument("--include-sentinel", action="store_true",
                    help="also seal ▶續卡 sentinels on the target card (no "
                         "chain walk — prefer repair_chain.py --seal)")
    args = ap.parse_args()

    scan_warnings = []
    if args.card or args.inline_card:
        explicit, order = {}, []
        for cid, inline in ([(c, False) for c in args.card]
                            + [(c, True) for c in args.inline_card]):
            if cid not in explicit:
                explicit[cid] = inline
                order.append(cid)
            else:
                explicit[cid] = explicit[cid] or inline
        targets = [(cid, "", explicit[cid]) for cid in order]
    else:
        targets, scan_warnings = scan_targets()

    results, changed = [], 0
    for cid, title, inline in targets:
        try:
            r = repair_card(cid, include_sentinel=args.include_sentinel,
                            include_inline=inline,
                            dry_run=args.dry_run)
        except Exception as e:  # one bad card must not abort the sweep
            r = {"card": cid, "error": str(e)[:160]}
        r["title"] = title
        if r.get("sealed"):
            changed += 1
        results.append(r)

    print(json.dumps({
        "mode": "card" if args.card or args.inline_card else "scan-all",
        "dry_run": args.dry_run,
        "include_sentinel": args.include_sentinel,
        "scanned": len(targets),
        "cards_changed": changed,
        # surface unresolved collections loudly — a missing progress tag would
        # otherwise drop every log card and still look like a clean sweep
        "warnings": scan_warnings,
        # keep the report lean, but never hide an unreadable inline target
        "results": [r for r in results
                    if r.get("sealed") or r.get("error")
                    or r.get("missing_inline_targets")],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
