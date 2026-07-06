#!/usr/bin/env python3
"""Structural research-gap candidates for a project card (Operation 5 stage 1).

Reads a Research-Projects card, extracts its concepts with the hung-yi-lee
skill's OWN extractor (same patterns + alignment canonicalization + slug, so
ids line up with the mixed graph exactly), then mines graph.local.json for
two candidate classes the pilot run validated:

  (c)  UNCITED NEIGHBOR PAPERS — external paper cards whose concept sets
       overlap the project's, log-damped rarity weighting (1/log2(2+df):
       god nodes contribute little, mid-frequency signal concepts still
       count — plain 1/df buried the pilot's targets under coincidental
       rare-term matches), minus papers the card already mentions.
  (c2) TOP-MATCHING OVERVIEW SHELVES — the overview cards whose concept
       sets best match the project, each listing its links_to papers the
       project does NOT cite. This is the curated-layer channel: papers
       whose relevance is topical rather than lexical (the pilot's
       TS3-Codec / MOSS / X-Codec / Kanade all surface here via the
       tokenizer shelves) can't be found by raw concept overlap, because
       the card's core vocabulary (causal/streaming) barely exists as
       graph concepts. Kept as its OWN section instead of folding into one
       score — a single scalar tuned to recover one card's targets would
       just overfit.
  (a)  DISTANCE-2 UNTOUCHED CONCEPTS — concepts that documents mentioning
       the project's concepts keep mentioning, but the project card never
       does ("everyone doing X also handles Y; your card has no Y").
       God-node cap; still needs model judgment (pilot: real signal ~1:10).

  Class (b) cross-community bridges is deliberately NOT here — the pilot
  found it drowned by god nodes; needs a redesign (document-level bridges or
  links_to endpoints) before it earns a slot.

These are STRUCTURAL CANDIDATES, not conclusions: stage 2 is a model reading
the card + this output and writing the hung-yi-lee-style gap analysis (see
overview-graph SKILL.md Operation 5).

  python3 research_gaps.py <project-card-id> [--top 15]
"""
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, "..", "..", "_shared"))
HUNGYI_ROOT = os.environ.get(
    "HUNGYI_ROOT", os.path.expanduser("~/.claude/skills/hung-yi-lee"))
sys.path.insert(0, os.path.join(HUNGYI_ROOT, "scripts"))

try:
    from hungyi_graph import extract_concepts_from_text, slug  # noqa: E402
except ImportError as e:
    sys.exit(f"ERROR: cannot import the hung-yi-lee extractor from "
             f"{HUNGYI_ROOT}/scripts (set HUNGYI_ROOT?): {e}")

try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None


def read_card(card_id):
    """Return (title, ProseMirror doc). Backend-routed like the exporter:
    obsidian reads the vault; heptabase/both go through the CLI (project
    cards are not a synced vault collection, so obsidian mode only works if
    the card actually lives there)."""
    if OBS:
        _, doc = OBS.read_doc(card_id)
        return card_id.rsplit("/", 1)[-1], doc
    r = subprocess.run(["heptabase", "note", "read", card_id],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit(f"ERROR: note read {card_id} failed: "
                 f"{(r.stderr or r.stdout).strip()[:160]}")
    data = json.loads(r.stdout)
    return data.get("title", card_id), json.loads(data["content"])


def _plain_text(n):
    if not isinstance(n, dict):
        return ""
    if n.get("type") == "text":
        return n.get("text", "")
    return "".join(_plain_text(c) for c in (n.get("content") or []))


def walk_text_and_mentions(doc):
    text_parts, mentioned = [], set()
    def walk(n):
        if not isinstance(n, dict):
            return
        if n.get("type") == "text":
            text_parts.append(n.get("text", ""))
        # any reference node carrying a cardId (card / embed / section refs)
        # counts as "already cited" — matching on type=="card" alone let
        # embedded references slip back into the candidate lists.
        cid = (n.get("attrs") or {}).get("cardId")
        if cid:
            mentioned.add(cid)
        for c in (n.get("content") or []):
            walk(c)
    # Skip 🔍-headed H2 sections: those are THIS workflow's own appended
    # gap-analysis output — feeding them back into concept extraction (and
    # into "already cited") inflates the project's concept set on every run
    # (observed on the pilot card: 70 -> 91 concepts after one append).
    skipping = False
    for n in doc.get("content", []):
        if isinstance(n, dict) and n.get("type") == "heading":
            level = (n.get("attrs") or {}).get("level")
            # any H1/H2 ends the skipped section; only a 🔍 H2 starts one
            if level is not None and level <= 2:
                skipping = level == 2 and _plain_text(n).strip().startswith("🔍")
        if not skipping:
            walk(n)
    return "\n".join(text_parts), mentioned


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card_id")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--max-doc-degree", type=int, default=80,
                    help="(a): skip candidate concepts mentioned by more "
                         "documents than this (god nodes)")
    args = ap.parse_args()
    if args.top <= 0 or args.max_doc_degree <= 0:
        ap.error("--top and --max-doc-degree must be positive")

    graph_path = os.path.join(HUNGYI_ROOT, "wiki", "graph", "graph.local.json")
    if not os.path.exists(graph_path):
        sys.exit("ERROR: graph.local.json missing — run the freshness one-liner "
                 "first (hungyi_query.py --refresh-only)")
    g = json.loads(open(graph_path, encoding="utf-8").read())

    title, doc = read_card(args.card_id)
    text, mentioned = walk_text_and_mentions(doc)
    concepts = {c["raw"] for c in extract_concepts_from_text(title + "\n" + text)}
    proj_ids = {f"concept_{slug(c)}" for c in concepts}

    labels, node_type, source_type = {}, {}, {}
    papers = []  # (node_id, label, origin_id)
    for n in g["nodes"]:
        labels[n["id"]] = n.get("label") or n["id"]
        node_type[n["id"]] = n.get("type")
        source_type[n["id"]] = n.get("source_type")
        if (n.get("type") == "external"
                and n.get("source_type") == "heptabase_paper_card"):
            papers.append((n["id"], n.get("label", ""), n.get("origin_id")))
    paper_origin = {pid: origin for pid, _, origin in papers}

    # Reverse vocabulary match: the extractor's patterns miss lowercase /
    # single-word / unwhitelisted-acronym domain terms the card DOES use
    # (pilot: "flow matching", "DAC", "chunk-aware"). Scan the card text with
    # the GRAPH's own concept vocabulary (display + merged alt labels) —
    # ASCII labels match on word boundaries, CJK by substring.
    import re as _re
    text_cf = (title + "\n" + text).casefold()
    def _display(lab):
        return _re.sub(r"\s*[（(]=.*?[）)]\s*$", "", lab).strip()
    def _alts(lab):
        m = _re.search(r"[（(]=(.*?)[）)]\s*$", lab)
        return m.group(1).split("/") if m else []
    vocab_hits = set()
    for nid, lab in labels.items():
        if node_type.get(nid) != "concept" or nid in proj_ids:
            continue
        for cand in [_display(lab)] + _alts(lab):
            cand = cand.strip()
            if len(cand) < 3:
                continue
            c_cf = cand.casefold()
            if c_cf not in text_cf:
                continue
            if _re.search(r"[㐀-鿿]", cand) or \
               _re.search(rf"(?<![\w-]){_re.escape(c_cf)}(?![\w-])", text_cf):
                vocab_hits.add(nid)
                break
    proj_ids |= vocab_hits

    # concept <-> document incidence (mentions) + overview shelves (links_to)
    docs_of = defaultdict(set)      # concept id -> doc ids
    concepts_of = defaultdict(set)  # doc id -> concept ids
    shelf_of = defaultdict(set)     # overview node id -> paper node ids
    for e in g["links"]:
        rel = e.get("relation")
        s, t = e["source"], e["target"]
        if rel == "mentions":
            c, d = (t, s) if node_type.get(t) == "concept" else (s, t)
            if node_type.get(c) != "concept" or node_type.get(d) not in ("video", "external"):
                continue
            docs_of[c].add(d)
            concepts_of[d].add(c)
        elif rel == "links_to":
            for a, b in ((s, t), (t, s)):
                if (source_type.get(a) == "heptabase_overview_card"
                        and b in paper_origin):
                    shelf_of[a].add(b)

    proj_in_graph = {c for c in proj_ids if c in docs_of}
    import math
    def rarity(c):
        # log damping: god nodes ~0.1, mid-frequency signal ~0.2-0.4 — plain
        # 1/df buried topical matches under coincidental rare-term overlaps.
        return 1.0 / math.log2(2 + len(docs_of[c]))

    print(f"[suggest-gaps] {title}")
    print(f"  card concepts: {len(concepts)} extracted + {len(vocab_hits)} "
          f"vocabulary-matched, {len(proj_in_graph)} in graph; "
          f"{len(mentioned)} cards already mentioned\n")
    if not proj_in_graph:
        sys.exit("ERROR: no card concept matches a graph node — is the graph "
                 "stale, or is the card outside the speech/audio domain?")

    # ── (c) uncited neighbor papers ────────────────────────────────────────
    scored = []
    for pid, plabel, origin in papers:
        if origin and (origin in mentioned or origin == args.card_id):
            continue
        shared = concepts_of[pid] & proj_in_graph
        if len(shared) < 2:
            continue
        score = sum(rarity(c) for c in shared)
        top_shared = sorted(shared, key=rarity, reverse=True)[:5]
        scored.append((score, plabel, origin, [labels[c] for c in top_shared]))
    scored.sort(reverse=True)
    print(f"(c) 未引用近鄰論文 — top {args.top}（log-damped 概念重疊；已排除卡上 mention）")
    for score, plabel, origin, shared in scored[: args.top]:
        print(f"  {score:6.3f}  {plabel[:64]}")
        print(f"          共享概念：{'、'.join(shared)}   [{(origin or '')[:8]}]")

    # ── (c2) top-matching overview shelves ─────────────────────────────────
    ovscore = sorted(((sum(rarity(c) for c in concepts_of[o] & proj_in_graph), o)
                      for o in shelf_of), reverse=True)
    print(f"\n(c2) 高匹配 overview 卡的書架 — top 5 書架上未引用的論文"
          f"（主題通道：詞彙對不上但同主題的論文從這裡浮出）")
    for oscore, o in ovscore[:5]:
        if oscore <= 0:
            continue  # no shared concept — an arbitrary shelf would be noise
        uncited = [p for p in shelf_of[o]
                   if paper_origin.get(p) not in mentioned
                   and paper_origin.get(p) != args.card_id]
        if not uncited:
            continue
        uncited.sort(key=lambda p: sum(rarity(c) for c in concepts_of[p] & proj_in_graph),
                     reverse=True)
        shown = uncited[: args.top]
        print(f"  [{oscore:.2f}] {labels[o][:60]}"
              + (f"（書架 {len(uncited)} 本，顯示 {len(shown)}）" if len(uncited) > len(shown) else ""))
        for p in shown:
            print(f"         • {labels[p][:66]}  [{(paper_origin.get(p) or '')[:8]}]")

    # ── (a) distance-2 untouched concepts ──────────────────────────────────
    agg = defaultdict(float)
    via_docs = defaultdict(set)
    for d, cset in concepts_of.items():
        overlap = len(cset & proj_in_graph)
        if overlap == 0:
            continue
        for c in cset - proj_in_graph:
            if len(docs_of[c]) > args.max_doc_degree:
                continue
            agg[c] += overlap * rarity(c)
            via_docs[c].add(d)
    ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
    print(f"\n(a) 距離 2 未連概念 — top {args.top}（經文件鄰居共同提及；god-node cap "
          f"{args.max_doc_degree}）")
    for c, score in ranked[: args.top]:
        print(f"  {score:6.2f}  {labels[c]}  （經 {len(via_docs[c])} 份文件）")

    print("\n⚠ 以上是結構候選，非結論——下一步：model 讀 project 卡＋本輸出，"
          "以 hung-yi-lee「問題→撞牆→怎麼辦呢」語氣寫 gap 分析並 append 回卡"
          "（overview-graph SKILL.md Operation 5）。")


if __name__ == "__main__":
    main()
