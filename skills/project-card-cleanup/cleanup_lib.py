#!/usr/bin/env python3
"""cleanup_lib — helpers for project-card-cleanup (thin layer over merge_lib).

Distilled from the 2026-07-19 axis-card / A-card cleanup sessions. Reuses
project-card-merge's merge_lib (M) + rewrite_lib (M.L); adds:
  - dump_chain(cid, outdir)      : one read pass → dump files + md5 json + image count
  - section(dump, prefix)        : H2 section extractor, fullwidth-paren tolerant
  - emit(C, text, repl=())       : dump text → builder nodes (tables/cardlinks/H3/bullets)
  - verify_content(C)            : card-link / table / H2 inventory before write
  - finalize_with_room(...)      : finalize_chain with a lowered greedy threshold
                                   (dense bullet/table rebuilds inflate ~40B/node on save;
                                   the default 80K threshold can overshoot the 100K cap)

Import pattern (from any cwd — use this skill's directory, e.g. the base
dir the skill system hands you):
    import sys
    sys.path.insert(0, "<this skill's directory>")
    import cleanup_lib as CL          # CL.M is merge_lib, CL.M.L is rewrite_lib
"""
import json
import os
import re
import sys

# realpath: symlinked entry points (~/.claude/skills/…) resolve back into
# the live plugin tree, so the sibling engine imports work from anywhere
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "project-card-merge"))
import merge_lib as M  # noqa: E402

_FW = str.maketrans({"(": "（", ")": "）", ":": "：", ",": "，"})


def dump_chain(cid, outdir):
    """One read pass over the chain: write per-card dumps + md5 baseline json.

    Returns (chain_ids, md5s, image_counts). Dumps go to
    {outdir}/cc_{cid8}.dump.md; md5 baseline to {outdir}/cc_md5s_{entry8}.json.
    The md5 baseline MUST be the one used for finalize/cleanup (optimistic lock).
    """
    reads = M.chain_dumps(cid)
    md5s, imgs = {}, {}
    os.makedirs(outdir, exist_ok=True)
    for c, md5, dump in reads:
        md5s[c] = md5
        with open(f"{outdir}/cc_{c[:8]}.dump.md", "w") as f:
            f.write(dump)
        _, doc = M.L.read_card(c)
        imgs[c[:8]] = len(M.L.extract_images(doc))
    with open(f"{outdir}/cc_md5s_{cid[:8]}.json", "w") as f:
        json.dump(md5s, f, indent=1)
    return [c for c, _, _ in reads], md5s, imgs


def section(dump, prefix, level=2):
    """Extract one `## prefix…` section body (heading excluded).

    Tolerant to fullwidth punctuation: if the halfwidth prefix misses, retry
    with （）：， translated — dump headings use fullwidth parens/colons.
    """
    hashes = "#" * level
    for p in (prefix, prefix.translate(_FW)):
        # consume to end of the HEADING LINE — a prefix match must not leak
        # the heading's tail (e.g. section(dump, "現狀") on 「## 現狀（最新）」
        # would otherwise start the body with 「（最新）」)
        m = re.search(rf"^{hashes} {re.escape(p)}[^\n]*\n?", dump, re.M)
        if m:
            rest = dump[m.end():]
            nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
            return rest[: nxt.start()] if nxt else rest
    raise AssertionError(f"section not found: {prefix}")


def emit(C, text, repl=()):
    """Convert dump lines back into builder nodes.

    Handles: `| … |` table runs → M.table, `[[card:id]]` lines → M.cardlink,
    ###/#### → M.L.h, •/-/・ bullets → M.L.bp, everything else → M.L.pp.
    `repl` applies plain str.replace pairs first (in-place corrections).
    Tables and card-links are exactly what a naive rebuild drops — this is the
    carrier that keeps them.
    """
    for old, new in repl:
        text = text.replace(old, new)
    # HARD FILTER (2026-07-19 lesson): never carry chain plumbing into a rebuild.
    # - sentinel lines (▶ 續卡…[[card:…]]) point at cards the merge is about to
    #   trash; carrying them corrupts append_card's chain walk (it appended to a
    #   trashed card). finalize_chain re-creates the real sentinel itself.
    # - merge-spill auto-headers (…的續卡 N／…；母卡：…) are re-created too.
    lines = [ln for ln in text.splitlines()
             if not (M.AC.LINK_MARK in ln and "[[card:" in ln)
             and not re.match(r"^（.*的續卡\s*\d.*母卡[:：]", ln.strip())]
    i, table = 0, []

    def flush():
        nonlocal table
        if table:
            M.L.add(C, M.table(table))
            table = []

    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.startswith("|") and ln.endswith("|") and len(ln) > 2:
            table.append([c.strip() for c in ln.strip().strip("|").split("|")])
            i += 1
            continue
        flush()
        if not ln or ln in ("----", "---"):
            i += 1
            continue
        m = re.match(r"^(#{3,4}) (.*)$", ln)
        if m:
            M.L.add(C, M.L.h(len(m.group(1)), m.group(2)))
            i += 1
            continue
        lm = re.match(
            rf"^({re.escape(M.AC.LOG_MARK)}|{re.escape(M.AC.LOG_DONE_MARK)})"
            rf"\s*(\d{{4}}-\d{{2}}-\d{{2}})?[　\s]*"
            rf"\[\[card:([0-9a-f-]+)\]\][　\s]*(.*)$", ln.strip())
        if lm:      # timeline lines rebuild WITH a real card node — the log
            M.L.add(C, M.loglink_node(   # link record must never degrade
                lm.group(3), lm.group(2) or "", lm.group(4).strip(),
                done=lm.group(1) == M.AC.LOG_DONE_MARK))
            i += 1
            continue
        cm = re.fullmatch(r"\[\[card:([0-9a-f-]+)\]\]", ln.strip())
        if cm:
            M.L.add(C, M.cardlink(cm.group(1)))
            i += 1
            continue
        if ln.startswith(("• ", "- ", "・")):
            M.L.add(C, M.L.bp(ln.lstrip("•-・ ").strip()))
            i += 1
            continue
        M.L.add(C, M.L.pp(ln))
        i += 1
    flush()


def verify_content(C):
    """Inventory the rebuilt node list BEFORE writing: card-links, tables, H2s.

    Compare card-link count against the old chain (sentinels/back-refs excluded)
    — a drop means emit() missed something. Returns dict for the caller to print.
    """
    def count(nodes, pred, n=0):
        for x in nodes:
            if isinstance(x, dict):
                if pred(x):
                    n += 1
                n = count(x.get("content", []) or [], pred, n)
        return n

    h2s = [(x.get("content") or [{}])[0].get("text", "?") for x in C
           if isinstance(x, dict) and x.get("type") == "heading"
           and (x.get("attrs") or {}).get("level") == 2]
    return {
        "card_links": count(C, lambda x: x.get("type") == "card"),
        "tables": count(C, lambda x: x.get("type") == "table"),
        "h2": h2s,
    }


def seg_sizes(C):
    """Per-H2 segment as-built sizes — run when finalize complains, to see
    which section is oversized before touching the threshold."""
    segs, cur, title = [], [], "(前段)"
    for x in C:
        if (isinstance(x, dict) and x.get("type") == "heading"
                and (x.get("attrs") or {}).get("level") == 2):
            segs.append((title, len(json.dumps(cur, ensure_ascii=False))))
            cur, title = [], (x.get("content") or [{}])[0].get("text", "?")
        cur.append(x)
    segs.append((title, len(json.dumps(cur, ensure_ascii=False))))
    return segs


def finalize_with_room(entry_id, md5, C, color_rules, threshold=62000,
                       dry_run=True):
    """finalize_chain with a lowered greedy split threshold.

    Rationale: rebuilds dominated by small bullets / table cells inflate by
    ~40B per node when Heptabase assigns UUIDs on save. The stock threshold
    (80K) lets the greedy packer fill a segment to ~79K as-built, which can
    exceed the 100K stored cap after inflation. 62K keeps every planned card
    comfortably under the cap. Restores the original config hook afterwards.
    """
    orig = M.AC.cap_threshold
    M.AC.cap_threshold = lambda cfg: (orig(cfg)[0], threshold)
    try:
        return M.finalize_chain(entry_id, md5, C, color_rules, dry_run=dry_run)
    finally:
        M.AC.cap_threshold = orig
