#!/usr/bin/env python3
"""Repair a project-card chain whose ENTRY card has content stranded AFTER the
continuation sentinel.

How content gets stranded: the sentinel (`▶ 續卡（本卡已達容量上限）：[[card:…]]`)
must stay the LAST thing on every non-tail card, but a bare `hb append <entry>`
or `hb log-exp --to <entry>` writes straight to the entry card without the
tail-walk that append_card.py does — the new section lands after the sentinel.

What this tool does (Mac only — needs the local `heptabase` CLI with
overwrite capability; the hb bridge is append-only):

  1. read the ENTRY card; find the LAST sentinel paragraph
  2. everything after it = the stranded nodes; convert them back to markdown
  3. re-append that markdown via append_card.py (which walks to the real tail
     and keeps all capacity/spill guarantees)
  4. only after that append SUCCEEDS, truncate the entry back to the sentinel
     (md5-guarded save — concurrent edits abort the truncation)

Move-then-truncate order means a crash between steps duplicates content on
two cards instead of losing it; if step 4 fails, DO NOT blindly re-run —
the stranded copy is already on the tail. Inspect, truncate by hand (or
re-run with --truncate-only).

Usage:
    python3 repair_chain.py --card <ENTRY_ID> [--dry-run]
    python3 repair_chain.py --card <ENTRY_ID> --truncate-only   # after a
        previous run moved content but failed to truncate

Prints one JSON line:
  {entry, stranded_nodes, moved_to, entry_truncated, dry_run}
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "_shared"))
sys.path.insert(0, os.path.join(_HERE, "..", "card-rewrite"))

import append_card as AC          # noqa: E402  (LINK_MARK — sentinel contract)
import rewrite_lib as L           # noqa: E402  (read_card / save_card, md5-guarded)


def _txt(n):
    if n.get("type") == "text":
        return n.get("text", "")
    return "".join(_txt(c) for c in n.get("content", []) or [])


def _sentinel_child(n):
    """The continuation card id IF this paragraph is a sentinel. The card
    node must come AFTER the LINK_MARK text within the paragraph — same rule
    as merge_lib's chain parser: prose that merely quotes the wording, or a
    card link that precedes the marker, does not count."""
    if n.get("type") != "paragraph":
        return None
    acc = ""
    for c in n.get("content", []) or []:
        if c.get("type") == "card":
            if AC.LINK_MARK in acc:
                return (c.get("attrs") or {}).get("cardId")
        else:
            acc += _txt(c)
    return None


def last_sentinel_idx(nodes):
    """Index of the LAST sentinel paragraph, or None when the card has no
    chain."""
    idx = None
    for i, n in enumerate(nodes):
        if _sentinel_child(n):
            idx = i
    return idx


def stranded_to_markdown(nodes, entry_id):
    """PM nodes → markdown, in the plugin dialect; card links re-normalized to
    the `[[card:<id>]]` input form (pmmd emits %%HEPTA-CARD:%% placeholders,
    which are a READ-side rendering, not valid append input)."""
    import re
    from pmmd import Converter
    conv = Converter({"id": entry_id, "title": ""}, set())
    md = conv.convert({"type": "doc", "content": nodes})
    return re.sub(r"%%HEPTA-CARD:([0-9a-f-]{36})%%", r"[[card:\1]]", md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True, help="ENTRY card id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--truncate-only", action="store_true",
                    help="skip the move (content already on the tail from a "
                         "previous partial run); just truncate after the sentinel")
    args = ap.parse_args()

    md5, doc = L.read_card(args.card)
    nodes = doc["content"]
    si = last_sentinel_idx(nodes)
    if si is None:
        print(json.dumps({"entry": args.card, "stranded_nodes": 0,
                          "moved_to": None, "entry_truncated": False,
                          "note": "no continuation sentinel — nothing to repair"},
                         ensure_ascii=False))
        return
    stranded = nodes[si + 1:]
    if not stranded:
        print(json.dumps({"entry": args.card, "stranded_nodes": 0,
                          "moved_to": None, "entry_truncated": False,
                          "note": "clean — sentinel is already the last node"},
                         ensure_ascii=False))
        return

    moved_to = None
    if not args.truncate_only:
        md = stranded_to_markdown(stranded, args.card)
        if args.dry_run:
            print(json.dumps({"entry": args.card, "stranded_nodes": len(stranded),
                              "moved_to": "(dry-run)", "entry_truncated": False,
                              "dry_run": True,
                              "preview": md[:400]}, ensure_ascii=False))
            return
        r = subprocess.run(
            [sys.executable, os.path.join(_HERE, "append_card.py"),
             "--card", args.card, "--content", "-"],
            input=md, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"append_card.py failed — entry untouched:\n{r.stderr[:400]}")
        out = json.loads(r.stdout.strip().splitlines()[-1])
        moved_to = out.get("appended_to")
        if not moved_to:
            raise SystemExit(f"append reported no target — entry untouched: {out}")

    # truncate only after the move landed (or explicitly --truncate-only)
    if args.dry_run:
        print(json.dumps({"entry": args.card, "stranded_nodes": len(stranded),
                          "moved_to": None, "entry_truncated": False,
                          "dry_run": True}, ensure_ascii=False))
        return
    doc["content"] = nodes[:si + 1]
    L.save_card(args.card, md5, doc)
    print(json.dumps({"entry": args.card, "stranded_nodes": len(stranded),
                      "moved_to": moved_to, "entry_truncated": True},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
