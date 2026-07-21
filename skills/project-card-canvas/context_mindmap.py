#!/usr/bin/env python3
"""context_mindmap — EXPERIMENTAL: a project's context mind map, grown
log card by log card.

Weekly-report log cards are self-contained (0.42.0 spec): 前情提要 states
what this round builds on WITH card-link sources, and the body carries
做了什麼/結果/這代表什麼/待裁決. That makes each card decomposable into a
small subtree, and the 前情提要 citations tell us WHERE to hang it — so
the whole project context becomes one mind map that EXPANDS as new log
cards arrive:

    root（軸卡, purple）
      └─ log hub（cyan; date＋主題＋開卡 link）
           ├─ ❓ 這次要回答（orange）
           ├─ 🔬 做了什麼
           ├─ 📊 結果
           ├─ 💡 這代表什麼（green）
           ├─ ⚖️ 待裁決／下一步（red）
           └─ child log hubs（the rounds that built on this one）…

Build order is the citation-topological order (parents before children,
(date, seq) tiebreak) — NOT the timeline's display order — so `--limit 1`
starts from the project's EARLIEST root log and regeneration with a
higher limit only APPENDS subtrees: node ids are deterministic, existing
nodes keep their identity across runs (Obsidian doesn't flicker).

Attachment rule: a log's parent is the LATEST (topologically deepest) log
its 前情提要 cites; remaining citations become gray "也承接" edges. No
in-set citation → the log hangs off the root. Citations are read from the
前情提要 section ONLY (that's the section whose contract says "附出處").

Two sibling modes share the canvas file:
- --mode chain — decompose the CHAIN BODY's H2/H3 sections (projects whose
  history was distilled into the chain by merges); structural view.
- --mode story — the research narrative (因為想法→實驗→結果→轉向/分岔)
  as a layered DAG. Prose reasoning is not machine-extractable, so an
  AGENT reads the chain and authors a graph JSON; kinds: idea/question/
  experiment/result/finding/decision/pivot/open. Full schema of record:
  the comment block above load_story_graph() in this file.

The canvas is a GENERATED VIEW — rebuilt each run, never hand-arranged.
Written next to the timeline canvas as `<title>·脈絡心智圖.canvas`
(story graph JSON lives beside it as `<title>·脈絡心智圖.graph.json`).

Mac-only (reads the chain via the local heptabase CLI).

Usage:
    python3 context_mindmap.py --card <ENTRY_ID>            # full map
    python3 context_mindmap.py --card <ENTRY_ID> --limit 1  # earliest only
    python3 context_mindmap.py --card <ENTRY_ID> --mode chain
    python3 context_mindmap.py --card <ENTRY_ID> --mode story --graph g.json
    python3 context_mindmap.py --card <ENTRY_ID> --dry-run
"""
import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "_shared"))
sys.path.insert(0, os.path.join(_HERE, "..", "project-card-merge"))
sys.path.insert(0, os.path.join(_HERE, "..", "card-rewrite"))

import hbconfig  # noqa: E402
import project_canvas as PCV  # noqa: E402  (_nid / safe_filename / vault_mapper)

HUB_W, HUB_H = 380, 110
LEAF_W, LEAF_H = 400, 190
HGAP, VGAP = 80, 28
COLOR_ROOT, COLOR_HUB = "6", "5"
LEAF_CHARS = 220
_UUID_RE = re.compile(r"\[\[card:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\]\]")

# section name (fuzzy contains-match on the H2 text) → leaf spec
LEAF_SPECS = [
    ("這次要回答", "❓ 這次要回答", "2"),      # synthesized from 前情提要
    ("做了什麼", "🔬 做了什麼", None),
    ("結果", "📊 結果", None),
    ("這代表什麼", "💡 這代表什麼", "4"),
    ("待裁決", "⚖️ 待裁決／下一步", "1"),
    ("下一步", "⚖️ 待裁決／下一步", "1"),
]

LEGEND_W = 300
LEGENDS = {   # mode → legend lines (色塊 emoji ≈ canvas palette 1–6)
    "logs": ["🟪 軸卡（root）", "🟦 log 卡（hub）", "🟧 ❓ 這次要回答",
             "🟩 💡 這代表什麼", "🟥 ⚖️ 待裁決／下一步",
             "⬜ 🔬 做了什麼／📊 結果"],
    "chain": ["🟪 軸卡（root）", "🟩 定位／現狀／進展／Findings",
              "🟨 實驗統整", "🟦 方法／評估",
              "🟥 開放項（🔍／下一步／發想／待補）", "⬜ 其他／H3 細節"],
    "story": ["🟪 軸卡（root）", "🟧 💡 想法／❓ 提問", "🟨 🧪 實驗",
              "⬜ 📊 結果", "🟩 ✅ 發現／⚖️ 定案",
              "🟥 🔀 轉向／⏳ 進行中",
              "（向下弧線＝跨幕接續或跨層長邊）"],
}


AUDIT_W = 380


def audit_node(entry_id, coverage, x):
    """Red 「⚠️ 待補」 banner — rendered ONLY when the coverage audit is
    dirty. Canvas-only, never written into the graph JSON (a stub node in
    the graph would get mistaken for an authored one); it regenerates from
    the audit each render and vanishes once the gaps are filled. None when
    the audit is clean."""
    logs = coverage.get("uncovered_logs") or []
    secs = coverage.get("uncovered_sections") or []
    if not logs and not secs:
        return None
    lines = []
    if logs:
        lines.append(f"未入圖 log（{len(logs)}）：")
        lines += [(f"・{(u.get('date') or '')[5:]} "
                   f"{u.get('summary', '')}")[:46] for u in logs[:8]]
        if len(logs) > 8:
            lines.append(f"…等共 {len(logs)} 張")
    if secs:
        lines.append(f"未入圖 section（{len(secs)}）：")
        lines += [f"・〔{u['card']}〕{u['section']}"[:46] for u in secs[:6]]
        if len(secs) > 6:
            lines.append(f"…等共 {len(secs)} 段")
    lines.append("（讀缺的→graph 加節點→重渲染即消失）")
    h = 72 + 26 * len(lines)
    return {"id": PCV._nid(entry_id, "mm-audit"), "x": x, "y": -(h + 48),
            "width": AUDIT_W, "height": h, "type": "text", "color": "1",
            "text": "**⚠️ 待補（coverage 稽核）**\n" + "\n".join(lines)}


GLOSSARY_W = 360


def glossary_node(entry_id, terms, x):
    """名詞 node beside the legend — the canvas counterpart of a weekly
    report's mini-glossary: recurring codes get ONE home viewers can
    glance at (one-off abbreviations must be expanded in place in node
    texts — the authoring hard rule). None when no terms."""
    if not terms:
        return None
    h = 64 + 30 * len(terms)
    return {"id": PCV._nid(entry_id, "mm-glossary"), "x": x, "y": -(h + 48),
            "width": GLOSSARY_W, "height": h, "type": "text",
            "text": "**名詞**\n" + "\n".join(terms)}


def legend_node(entry_id, mode, x):
    """A fixed legend text node ABOVE the graph (content starts at y=0 in
    every mode, so negative y never collides). Deterministic id; uncolored
    so it doesn't compete with the palette it explains."""
    lines = LEGENDS[mode]
    h = 64 + 30 * len(lines)
    return {"id": PCV._nid(entry_id, "mm-legend"), "x": x, "y": -(h + 48),
            "width": LEGEND_W, "height": h, "type": "text",
            "text": "**圖例**\n" + "\n".join(lines)}


def split_sections(content, txt_of):
    """{'_header': [nodes…], '<H2 text>': [nodes…]} in document order."""
    secs, cur = {"_header": []}, "_header"
    for n in content or []:
        if n.get("type") == "heading" and (n.get("attrs") or {}).get("level") == 2:
            cur = txt_of(n).strip()
            secs.setdefault(cur, [])
        else:
            secs.setdefault(cur, []).append(n)
    return secs


_NUM_PREFIX = (r"[（(][一二三四五六七八九十\d]+[)）]\s*"  # "（一）實驗統整"
               r"|\d+[.、)）]\s*|\d+\s+")               # "1. 現狀" / "01 方法"


def _norm_heading(name):
    """Strip emoji/symbol/numbering prefixes so '⚖️ 待裁決／下一步' matches
    '待裁決' and '1. 現狀' matches '現狀' — but anchored ('附錄：前情提要範例'
    never matches '前情提要') and digit-safe ('3D 視覺化' keeps its 3: bare
    digits only strip when followed by punctuation or whitespace). The
    bracket-numeral alternative must come FIRST — the generic symbol class
    would otherwise eat the opening bracket alone."""
    return re.sub(r"^(?:" + _NUM_PREFIX + r"|[^\w一-鿿]+)+",
                  "", name or "").strip()


def section_named(secs, key):
    """The nodes of the first section whose NORMALIZED H2 STARTS WITH `key`
    (None if absent). Anchored match — a heading merely mentioning the key
    ('非前情提要', '附錄：前情提要範例') is not that section."""
    for name, nodes in secs.items():
        if name != "_header" and _norm_heading(name).startswith(key):
            return nodes
    return None


TABLE_MARK = "（表格：開卡看）"


def leaf_text(nodes, txt_of, limit=LEAF_CHARS):
    """Readable excerpt of a section: paragraphs/list items joined, tables
    collapsed to a marker, hard-trimmed with an ellipsis. The marker is
    RESERVED before trimming — a long section can never crowd it out."""
    saw_table = any(n.get("type") == "table" for n in nodes or [])
    out = []
    for n in nodes or []:
        if n.get("type") == "table":
            continue
        t = txt_of(n).strip()
        if t:
            out.append(t)
        if sum(len(x) for x in out) > limit * 2:
            break
    cap = limit - (len(TABLE_MARK) + 1) if saw_table else limit
    s = "\n".join(out)
    s = s[:cap] + ("…" if len(s) > cap else "")
    if saw_table:
        s = (s + "\n" if s else s) + TABLE_MARK
    return s


def question_of(pre_nodes, txt_of, limit=LEAF_CHARS):
    """The 這次要回答 beat inside 前情提要 (empty string if absent)."""
    for n in pre_nodes or []:
        t = txt_of(n).strip()
        i = t.find("這次要回答")
        if i >= 0:
            s = t[i:]
            return s[:limit] + ("…" if len(s) > limit else "")
    return ""


def _card_ids_of(node):
    """cardIds of REAL card-mention nodes, in document order (recursive) —
    the id-shape-agnostic primary source (works for local Folder/Name ids
    the [[card:uuid]] regex can never see)."""
    out = []
    if not isinstance(node, dict):
        return out
    if node.get("type") == "card":
        cid = (node.get("attrs") or {}).get("cardId")
        if cid:
            out.append(cid)
    for c in node.get("content") or []:
        out.extend(_card_ids_of(c))
    return out


def citations_of(pre_nodes, txt_of, in_set, self_id):
    """Ordered unique in-set citations from the 前情提要 section only.
    Real card nodes first (any id shape), then text-form [[card:uuid]]
    literals (bridge-written lines the CLI left as plain text)."""
    seen, out = set(), []

    def _add(cid):
        if cid in in_set and cid != self_id and cid not in seen:
            seen.add(cid)
            out.append(cid)

    for n in pre_nodes or []:
        for cid in _card_ids_of(n):
            _add(cid)
        for cid in _UUID_RE.findall(txt_of(n)):
            _add(cid)
    return out


def topo_order(logs, cites):
    """Citation-topological order (cited before citer), ties broken by
    (date, seq, id). Back-edges in a cycle are dropped (deterministic)."""
    key = {e["log"]: (e.get("date") or "", e.get("seq", 0), e["log"])
           for e in logs}
    ids = set(key)
    deps = {i: set(c for c in cites.get(i, []) if c in ids) for i in ids}
    order, placed = [], set()
    while len(order) < len(ids):
        ready = sorted((i for i in ids if i not in placed
                        and deps[i] <= placed), key=lambda i: key[i])
        if not ready:                      # cycle: place the oldest, drop edge
            ready = [min((i for i in ids if i not in placed),
                         key=lambda i: key[i])]
        for i in ready:
            placed.add(i)
            order.append(i)
    return order




def build_mindmap(entry_id, entry_title, logs, decomp, vault_file_of,
                  limit=None):
    """Pure assembly, logs mode — v2 layout: log hubs run HORIZONTALLY
    (citation-topological order — the project timeline reads left→right)
    and each hub's section leaves hang in a vertical thread BELOW it.
    Parent→child hub edges are lateral when adjacent and fly over the
    lane (top→top arcs) when the child sits further right — same for
    「也承接」 secondary citations. Returns (canvas, order)."""
    cites = {cid: d.get("cites", []) for cid, d in decomp.items()}
    order = topo_order(logs, cites)
    if limit:
        order = order[:limit]
    rank = {cid: i for i, cid in enumerate(order)}
    date_of = {e["log"]: e.get("date") or "" for e in logs}

    parent_of, secondary = {}, {}
    for cid in order:
        back = [c for c in cites.get(cid, [])
                if c in rank and rank[c] < rank[cid]]
        p = max(back, key=lambda c: rank[c]) if back else None
        parent_of[cid] = p
        secondary[cid] = [c for c in back if c != p]

    col_step = max(HUB_W, LEAF_W) + 60
    nodes, edges = [], []

    def hub_id(cid):
        return PCV._nid(cid, "mm-hub")

    def leaves_of(cid):
        d = decomp[cid]
        out = []
        if d.get("question"):
            out.append(("❓ 這次要回答", "2", d["question"]))
        out.extend(d.get("sections", []))
        return out

    for i, cid in enumerate(order):
        x = i * col_step
        f = vault_file_of(cid)
        link = (f"[[{f[:-3] if f and f.endswith('.md') else f}|→ 開卡]]"
                if f else f"（Heptabase card {cid[:8]}）")
        nodes.append({"id": hub_id(cid), "x": x, "y": 0,
                      "width": HUB_W, "height": HUB_H, "color": COLOR_HUB,
                      "type": "text",
                      "text": f"**{date_of.get(cid, '')[5:]}｜"
                              f"{decomp[cid].get('title', cid[:8])}**\n{link}"})
        y = HUB_H + 40
        prev = None
        for j, (label, color, text) in enumerate(leaves_of(cid)):
            n = {"id": PCV._nid(cid, f"mm-leaf{j}"),
                 "x": x + (HUB_W - LEAF_W) // 2, "y": y,
                 "width": LEAF_W, "height": LEAF_H, "type": "text",
                 "text": f"**{label}**\n{text}"}
            if color:
                n["color"] = color
            nodes.append(n)
            edges.append({"id": PCV._nid(cid, f"mm-eleaf{j}"),
                          "fromNode": prev or hub_id(cid),
                          "fromSide": "bottom",
                          "toNode": n["id"], "toSide": "top"})
            prev = n["id"]
            y += LEAF_H + VGAP
    for cid in order:
        p = parent_of[cid]
        if p is not None:
            adjacent = rank[cid] == rank[p] + 1
            edges.append({"id": PCV._nid(cid, "mm-edge"),
                          "fromNode": hub_id(p),
                          "fromSide": "right" if adjacent else "top",
                          "toNode": hub_id(cid),
                          "toSide": "left" if adjacent else "top"})
        for c in secondary.get(cid, []):
            edges.append({"id": PCV._nid(cid, f"mm-esec-{len(c)}:{c}:"),
                          "fromNode": hub_id(c), "fromSide": "top",
                          "toNode": hub_id(cid), "toSide": "top",
                          "label": "也承接"})
    ef = vault_file_of(entry_id)
    root = {"id": PCV._nid(entry_id, "mm-root"), "x": -(HUB_W + HGAP + 80),
            "y": (HUB_H - PCV.ENTRY_H) // 2, "width": HUB_W,
            "height": PCV.ENTRY_H, "color": COLOR_ROOT}
    if ef:
        root.update({"type": "file", "file": ef})
    else:
        root.update({"type": "text", "text": f"# {entry_title}"})
    nodes.append(root)
    nodes.append(legend_node(entry_id, "logs", -(HUB_W + HGAP + 80)))
    first = True                       # roots of the citation forest
    for cid in order:
        if parent_of[cid] is None:
            # only the FIRST root gets the lateral edge — a later root's
            # lateral edge would plow through every hub before it; those
            # fly over the lane like non-adjacent parents do
            edges.append({"id": PCV._nid(cid, "mm-edge"),
                          "fromNode": root["id"],
                          "fromSide": "right" if first else "top",
                          "toNode": hub_id(cid),
                          "toSide": "left" if first else "top"})
            first = False
    return ({"nodes": nodes, "edges": edges}, order)


# ── chain mode: decompose the CHAIN BODY (distilled knowledge) ─────────────
# Older projects predate log-as-card: their history was distilled into the
# chain body by merges. There the mind map's unit is the SECTION — H2 hubs
# with H3 leaves — colored by section role.
SEC_HUB_W, SEC_HUB_H = 380, 140
_SEC_COLORS = [                     # normalized-startswith → canvas color
    (("定位", "現狀", "進展", "Findings", "findings"), "4"),   # 狀態/結論 → 綠
    (("實驗",), "3"),                                          # 實驗紀錄 → 黃
    (("方法", "Method", "method", "評估"), "5"),               # 方法/協定 → cyan
    (("研究漏洞", "下一步", "發想", "待補", "待裁決"), "1"),   # 開放項 → 紅
]
_SEC_SKIP = ("log 時間線",)         # chain plumbing, already its own canvas


def section_color(title):
    t = _norm_heading(title)
    for keys, color in _SEC_COLORS:
        if any(t.startswith(k) for k in keys):
            return color
    return None


def chain_sections(content, txt_of):
    """[(h2_title, lead_nodes, [(h3_title, h3_nodes)…])…] in document
    order. Content before the first H2 (card header/back-ref) is dropped;
    plumbing sections (📜 log 時間線) are skipped."""
    out, cur = [], None
    for n in content or []:
        lvl = ((n.get("attrs") or {}).get("level")
               if n.get("type") == "heading" else None)
        if lvl == 2:
            t = txt_of(n).strip()
            cur = None
            if not any(_norm_heading(t).startswith(s) for s in _SEC_SKIP):
                cur = (t, [], [])
                out.append(cur)
        elif cur is not None and lvl == 3:
            cur[2].append((txt_of(n).strip(), []))
        elif cur is not None:
            (cur[2][-1][1] if cur[2] else cur[1]).append(n)
    return out


def build_chainmap(entry_id, entry_title, per_card, vault_file_of,
                   txt_of=None):
    """Pure assembly, chain mode. per_card: [(card_id, marker, sections)]
    where marker is "" for the entry / 「續N」 for continuations and
    sections comes from chain_sections(). Two-level tree: root → H2 hubs
    (chain order) → H3 leaves. Node ids key on (card, title, occurrence),
    NOT position — inserting/renaming a DIFFERENTLY-titled section never
    renames the others (same-titled sections shift occurrence numbers, so
    renaming the first 「實驗」 does re-id the second — acceptable for a
    generated view)."""
    txt_of = txt_of or PCV_txt
    nodes, edges = [], []
    hubs = []                             # (hub_id, height, leaves…)
    for cid, marker, sections in per_card:
        occ = {}
        for h2, lead, subs in sections:
            occ[h2] = occ.get(h2, 0) + 1
            sid = PCV._nid(cid, f"mm-sec:{occ[h2]}:{len(h2)}:{h2}:")
            leaves = []
            for h3, h3_nodes in subs:
                occ_key = (h2, h3)
                occ[occ_key] = occ.get(occ_key, 0) + 1
                lid = PCV._nid(cid, f"mm-sub:{occ[h2]}:{occ[occ_key]}:"
                                    f"{len(h2)}:{h2}:{len(h3)}:{h3}:")
                leaves.append((lid, h3, leaf_text(h3_nodes, txt_of)))
            hubs.append((sid, cid, marker, h2, lead, leaves))
    # layout: hubs at x=0, leaves at x=HUB+GAP; root spans on the left.
    # A leafless hub RENDERS taller (LEAF_H — it carries the excerpt), so
    # its slot must budget that rendered height, not SEC_HUB_H.
    height, rendered = {}, {}
    for sid, cid, marker, h2, lead, leaves in hubs:
        rendered[sid] = SEC_HUB_H if leaves else LEAF_H
        kids = [LEAF_H] * len(leaves)
        height[sid] = (max(rendered[sid], sum(kids) + VGAP * (len(kids) - 1))
                       if kids else rendered[sid])
    total_h = (sum(height[h[0]] for h in hubs)
               + VGAP * max(0, len(hubs) - 1)) or SEC_HUB_H
    ef = vault_file_of(entry_id)
    root = {"id": PCV._nid(entry_id, "mm-root"), "x": -(SEC_HUB_W + HGAP),
            "y": (total_h - PCV.ENTRY_H) // 2, "width": SEC_HUB_W,
            "height": PCV.ENTRY_H, "color": COLOR_ROOT}
    if ef:
        root.update({"type": "file", "file": ef})
    else:
        root.update({"type": "text", "text": f"# {entry_title}"})
    nodes.append(root)
    nodes.append(legend_node(entry_id, "chain", -(SEC_HUB_W + HGAP)))
    y = 0
    for sid, cid, marker, h2, lead, leaves in hubs:
        hub_y = y + (height[sid] - rendered[sid]) // 2
        head = f"**{'〔' + marker + '〕' if marker else ''}{h2}**"
        excerpt = leaf_text(lead, txt_of, limit=100 if leaves else LEAF_CHARS)
        n = {"id": sid, "x": 0, "y": hub_y,
             "width": SEC_HUB_W, "height": rendered[sid],
             "type": "text",
             "text": head + (f"\n{excerpt}" if excerpt else "")}
        color = section_color(h2)
        if color:
            n["color"] = color
        nodes.append(n)
        edges.append({"id": PCV._nid(cid, f"mm-esec-hub:{sid}"),
                      "fromNode": root["id"], "fromSide": "right",
                      "toNode": sid, "toSide": "left"})
        ly = y
        for lid, h3, text in leaves:
            nodes.append({"id": lid, "x": SEC_HUB_W + HGAP, "y": ly,
                          "width": LEAF_W, "height": LEAF_H, "type": "text",
                          "text": f"**{h3}**\n{text}"})
            edges.append({"id": PCV._nid(cid, f"mm-eleaf:{lid}"),
                          "fromNode": sid, "fromSide": "right",
                          "toNode": lid, "toSide": "left"})
            ly += LEAF_H + VGAP
        y += height[sid] + VGAP
    return {"nodes": nodes, "edges": edges}


# ── story mode: the RESEARCH NARRATIVE as a layered DAG ─────────────────────
# The reasoning chain (因為想法→做了實驗→結果→轉向/分岔/回頭) lives in
# prose — no regex can extract it. Contract: an AGENT reads the chain and
# authors a graph JSON (schema below); this script only does deterministic
# validation + layout, so regeneration / id stability stay code-guaranteed.
#
#   {"nodes": [{"id": "slug", "kind": "idea|question|experiment|result|
#               finding|decision|pivot|open", "label": "短標題",
#               "text": "一兩句",
#               "anchor": "出處 section（選填；・分隔可列多個）",
#               "date": "MM-DD（選填）",
#               "sources": ["<log 卡 id 或 ≥8 碼前綴>…（選填——此節點蓋掉
#                           的 log 卡；coverage 稽核的鍵）"],
#               "stage": "幕標題（選填）——只標每幕的第一個節點；後續節點
#                         沿輸入（敘事）序繼承，直到下一個 stage 標記"}],
#    "edges": [{"from": "slug", "to": "slug", "label": "所以/但是（選填）"}],
#    "coverage_ignore": ["方法", "評估協定", "…（選填——刻意不入圖的
#                        section，稽核豁免；比對規則同 anchor）"],
#    "glossary": ["st1＝…", "…（選填——整圖反覆使用的代號，一行一個；
#                 渲染成 legend 旁的名詞節點。一次性縮寫請在節點 text
#                 就地展開——無縮寫是撰寫硬規則）"]}
# (This block is the schema of record — the module docstring points here.)
#
# Coverage audit: every story render reports which timeline LOG CARDS no
# node claims (via `sources`) and which chain H2 SECTIONS no node anchors
# — log ids are stable across distillation (log cards are never trashed),
# so the audit tells the refreshing agent exactly what to read and where
# to extend the graph.
#
# Stages = rows: each stage renders as its own ROW (x restarts at 0 —
# a "line wrap" for long narratives), with the stage title on the row's
# top-left and cross-stage edges flowing bottom→top to the later row.
# No stage fields → one unlabeled row (single-line layout).
#
# Node input order = narrative order (drives --limit replay and layer
# stacking); ids are author-chosen stable slugs, so growing the graph
# only ADDS canvas nodes.
STORY_W, STORY_H = 360, 200
# story columns need room for EDGE LABELS (rendered mid-edge): a 6-CJK
# connective is ~120px wide — the shared HGAP (80) buries it under nodes
STORY_HGAP = 240
# soft label budget (CJK≈2 units, latin≈1): longer connectives belong in
# the node text; the report lists offenders instead of truncating them
LABEL_UNITS = 12
STORY_KINDS = {                      # kind → (icon, canvas color)
    "idea": ("💡", "2"), "question": ("❓", "2"),
    "experiment": ("🧪", "3"),
    "result": ("📊", None),
    "finding": ("✅", "4"), "decision": ("⚖️", "4"),
    "pivot": ("🔀", "1"), "open": ("⏳", "1"),
}


def _disp_units(s):
    """Approximate display width: CJK/fullwidth ≈ 2 units, else 1."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s or "")


def load_story_graph(path):
    """(nodes, edges, warnings, meta). Warnings are soft: an over-budget
    edge label (> LABEL_UNITS display units) renders clipped/buried
    mid-edge in Obsidian — move the nuance into the node text and keep a
    short connective. Never truncated here (the author owns the words).
    meta carries top-level extras (coverage_ignore)."""
    g = json.load(open(path, encoding="utf-8"))
    nodes, edges = g.get("nodes") or [], g.get("edges") or []
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)) or not all(ids):
        raise ValueError("story graph: node ids must be unique and non-empty")
    idset = set(ids)
    warnings = []
    for e in edges:
        if e.get("from") not in idset or e.get("to") not in idset:
            raise ValueError(f"story graph: edge {e.get('from')}→{e.get('to')} "
                             f"references an unknown node")
        if _disp_units(e.get("label")) > LABEL_UNITS:
            warnings.append(f"label 過長（{e.get('label')}）@ "
                            f"{e['from']}→{e['to']}——縮成短連接詞、"
                            f"語義放節點內文")
    meta = {"coverage_ignore": g.get("coverage_ignore") or [],
            "glossary": g.get("glossary") or []}
    return nodes, edges, warnings, meta


def _anchor_parts(s):
    """Split an anchor/ignore string into normalized match parts."""
    return [p for p in
            (_norm_heading(x) for x in re.split(r"[・/／、＋+]", s or ""))
            if len(p) >= 2]


def story_coverage(graph_nodes, logs, sections_by_card, ignore=None):
    """What the graph has NOT covered yet — the refresh agent's to-read
    list. logs: scan timeline entries ({log,date,summary}); sections_by_card:
    [(card_id, [H2 titles…])]. A log is covered when some node's `sources`
    lists its id (or a ≥8-char prefix); a section is covered when its
    normalized head (title before ：/:) containment-matches any node's
    anchor part (either direction) or an ignore part."""
    src = set()
    anchor_parts = []
    for n in graph_nodes:
        for s in n.get("sources") or []:
            if isinstance(s, str) and len(s) >= 8:
                src.add(s)
        anchor_parts.extend(_anchor_parts(n.get("anchor")))
    ignore_parts = []
    for s in ignore or []:
        ignore_parts.extend(_anchor_parts(s))

    def log_covered(lid):
        return any(lid == s or lid.startswith(s) for s in src)

    uncovered_logs = [
        {"log": e["log"][:8], "date": e.get("date", ""),
         "summary": (e.get("summary") or "")[:60]}
        for e in logs if not log_covered(e["log"])]

    def sec_covered(title):
        head = _norm_heading(re.split(r"[：:]", title, maxsplit=1)[0])
        if len(head) < 2:
            return True
        for part in anchor_parts + ignore_parts:
            if part in head or head in part:
                return True
        return False

    uncovered_sections = [
        {"card": cid[:8], "section": t}
        for cid, titles in sections_by_card
        for t in titles if not sec_covered(t)]
    # sources sanity: an ambiguous prefix silently claims several logs and
    # a zero-hit source is usually a typo — both deserve a loud line
    warns = []
    for s in sorted(src):
        hits = [e["log"] for e in logs
                if e["log"] == s or e["log"].startswith(s)]
        if len(hits) > 1:
            warns.append(f"source 前綴 {s} 命中 {len(hits)} 張 log"
                         f"（歧義——全部視為已覆蓋；請改用完整 id）")
        elif not hits:
            warns.append(f"source {s[:16]}… 沒命中任何時間線 log（typo？）")
    out = {"uncovered_logs": uncovered_logs,
           "uncovered_sections": uncovered_sections}
    if warns:
        out["source_warnings"] = warns
    return out


def story_layers(nodes, edges):
    """node id → layer (longest path from sources). Deterministic cycle
    tolerance: nodes are seated in Kahn waves ordered by input position;
    on a stall the earliest-input stalled node is force-placed (its unmet
    back-edges simply don't lengthen the path)."""
    order_ix = {n["id"]: i for i, n in enumerate(nodes)}
    preds = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["to"] != e["from"]:
            preds[e["to"]].append(e["from"])
    layer, placed = {}, set()
    while len(placed) < len(preds):
        ready = sorted((i for i in preds if i not in placed
                        and all(p in placed for p in preds[i])),
                       key=lambda i: order_ix[i])
        if not ready:
            ready = [min((i for i in preds if i not in placed),
                         key=lambda i: order_ix[i])]
        for i in ready:
            layer[i] = max((layer[p] + 1 for p in preds[i] if p in placed),
                           default=0)
            placed.add(i)
    return layer


def story_y_positions(graph_nodes, graph_edges, layer):
    """node id → TOP y. Flow-tracking coordinate assignment: a node wants
    to sit at its predecessors' mean height (edges become near-horizontal
    and stop piling into one central band); collisions within a column
    push down, keeping (desired-y, input-order) order — branches fan out,
    a straight chain stays a straight lane. Deterministic; the whole
    layout is normalized so the top-most node sits at y=0."""
    order_ix = {n["id"]: i for i, n in enumerate(graph_nodes)}
    preds = {n["id"]: [] for n in graph_nodes}
    for e in graph_edges:
        # dedupe: a parallel edge must not double-weight its predecessor
        # in the desired-y mean
        if e["from"] != e["to"] and e["from"] not in preds[e["to"]]:
            preds[e["to"]].append(e["from"])
    cols = {}
    for n in graph_nodes:
        cols.setdefault(layer[n["id"]], []).append(n["id"])
    ycen, ytop = {}, {}
    for c in sorted(cols):
        ranked = sorted(
            ((sum(ycen[p] for p in preds[i] if p in ycen)
              / max(1, len([p for p in preds[i] if p in ycen]))
              if any(p in ycen for p in preds[i]) else None,
              order_ix[i], i) for i in cols[c]),
            key=lambda t: (t[0] if t[0] is not None else float("inf"), t[1]))
        bottom = None
        for desired, _, i in ranked:
            top = 0 if desired is None else int(desired - STORY_H / 2)
            if bottom is not None:
                top = max(top, bottom + VGAP)
            elif desired is None:
                top = 0
            ytop[i] = top
            ycen[i] = top + STORY_H / 2
            bottom = top + STORY_H
    shift = min(ytop.values(), default=0)
    return {i: t - shift for i, t in ytop.items()}


ROW_GAP, STAGE_HEADER_H = 180, 80


def story_stages(graph_nodes):
    """node id → stage label; unstaged nodes inherit the previous node's
    stage in input (narrative) order — annotate only stage BOUNDARIES.
    Returns (stage_of, ordered unique stage labels)."""
    stage_of, order, cur = {}, [], ""
    for n in graph_nodes:
        if n.get("stage"):
            cur = n["stage"]
        stage_of[n["id"]] = cur
        if cur not in order:
            order.append(cur)
    return stage_of, order


def build_storymap(entry_id, entry_title, graph_nodes, graph_edges,
                   vault_file_of, limit=None):
    """Pure assembly, story mode. Stages render as ROWS (x restarts per
    row; each row is its own layered DAG with flow-tracking lanes); the
    stage title sits at the row's top-left, cross-stage edges flow
    bottom→top into the later row, and long INTRA-row edges (≥2 local
    layers) take the bottom bypass arc. Without stage fields everything
    is one unlabeled row. Returns (canvas, [node ids in input order])."""
    if limit:
        graph_nodes = graph_nodes[:limit]
        kept = {n["id"] for n in graph_nodes}
        graph_edges = [e for e in graph_edges
                       if e["from"] in kept and e["to"] in kept]
    stage_of, stage_order = story_stages(graph_nodes)
    row_ix = {s: i for i, s in enumerate(stage_order)}
    nodes, edges = [], []
    nid, layer, ytop = {}, {}, {}
    row_base = 0
    left_x = -(STORY_W + STORY_HGAP)
    for s in stage_order:
        row_nodes = [n for n in graph_nodes if stage_of[n["id"]] == s]
        row_edges = [e for e in graph_edges
                     if stage_of.get(e["from"]) == s
                     and stage_of.get(e["to"]) == s]
        rlayer = story_layers(row_nodes, row_edges)   # LOCAL layers: x from 0
        rytop = story_y_positions(row_nodes, row_edges, rlayer)
        if s:                                          # stage header band
            nodes.append({"id": PCV._nid(entry_id, f"mm-stage:{s}"),
                          "x": left_x, "y": row_base,
                          "width": STORY_W, "height": STAGE_HEADER_H,
                          "type": "text", "text": f"**{s}**"})
            row_base += STAGE_HEADER_H + 30
        for i, t in rytop.items():
            ytop[i] = row_base + t
        layer.update(rlayer)
        row_base += (max(rytop.values()) + STORY_H if rytop else STORY_H) \
            + ROW_GAP
    for n in graph_nodes:
        icon, color = STORY_KINDS.get(n.get("kind"), ("", None))
        head = f"**{icon} {n.get('label', n['id'])}**".replace("** ", "**")
        body = (n.get("text") or "").strip()
        tail = f"\n〔{n['anchor']}〕" if n.get("anchor") else ""
        date = f"{n['date']}　" if n.get("date") else ""
        node = {"id": PCV._nid(entry_id, f"mm-story:{n['id']}"),
                "x": layer[n["id"]] * (STORY_W + STORY_HGAP),
                "y": ytop[n["id"]],
                "width": STORY_W, "height": STORY_H, "type": "text",
                "text": f"{head}\n{date}{body}{tail}"}
        if color:
            node["color"] = color
        nodes.append(node)
        nid[n["id"]] = node["id"]
    first_row = [ytop[n["id"]] for n in graph_nodes
                 if row_ix[stage_of[n["id"]]] == 0 and layer[n["id"]] == 0]
    root_yc = (min(first_row) + max(first_row) + STORY_H) / 2 if first_row \
        else STORY_H / 2
    ef = vault_file_of(entry_id)
    root = {"id": PCV._nid(entry_id, "mm-root"), "x": left_x,
            "y": int(root_yc - PCV.ENTRY_H / 2), "width": STORY_W,
            "height": PCV.ENTRY_H, "color": COLOR_ROOT}
    if ef:
        root.update({"type": "file", "file": ef})
    else:
        root.update({"type": "text", "text": f"# {entry_title}"})
    nodes.append(root)
    nodes.append(legend_node(entry_id, "story", -(STORY_W + STORY_HGAP)))
    # first-row layer-0 nodes hang off the root — NOT raw in-degree: a
    # pure cycle (a↔b) or a self-loop has no in-degree-0 node and would
    # detach from the root entirely; layering already force-seats those.
    # (Later rows' layer-0 nodes are narrative continuations, not roots.)
    for n in graph_nodes:
        if layer[n["id"]] == 0 and row_ix[stage_of[n["id"]]] == 0:
            edges.append({"id": PCV._nid(entry_id, f"mm-sroot:{n['id']}"),
                          "fromNode": root["id"], "fromSide": "right",
                          "toNode": nid[n["id"]], "toSide": "left"})
    pair_occ = {}                              # parallel edges (same from→to,
    for e in graph_edges:                      # different連接詞) stay distinct
        k = (e["from"], e["to"])
        pair_occ[k] = pair_occ.get(k, 0) + 1
        edge = {"id": PCV._nid(entry_id,
                               f"mm-sedge:{len(e['from'])}:{e['from']}:"
                               f"{e['to']}:{pair_occ[k]}"),
                "fromNode": nid[e["from"]], "fromSide": "right",
                "toNode": nid[e["to"]], "toSide": "left"}
        drow = row_ix[stage_of[e["to"]]] - row_ix[stage_of[e["from"]]]
        if drow > 0:                # line-wrap: flow DOWN into the later row
            edge.update({"fromSide": "bottom", "toSide": "top"})
        elif drow < 0:              # rare backward link: climb back up
            edge.update({"fromSide": "top", "toSide": "bottom"})
        elif abs(layer[e["to"]] - layer[e["from"]]) >= 2:
            # long intra-row edge would plow through the columns between —
            # bypass arc below the row (label lands in the row gap)
            edge.update({"fromSide": "bottom", "toSide": "bottom"})
        if e.get("label"):
            edge["label"] = e["label"]
        edges.append(edge)
    return ({"nodes": nodes, "edges": edges},
            [n["id"] for n in graph_nodes])


def PCV_txt(n):
    """merge_lib's L._txt when importable; a minimal fallback keeps the
    pure helpers testable without the full stack."""
    try:
        import merge_lib as M
        return M.L._txt(n)
    except Exception:                                        # noqa: BLE001
        out = []
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text", ""))
            for c in n.get("content") or []:
                out.append(PCV_txt(c))
        return "".join(out)


def decompose(cid, in_set, M):
    """Read ONE log card → its mind-map ingredients."""
    _, doc = M.L.read_card(cid)
    secs = split_sections(doc.get("content"), M.L._txt)
    title = next((M.L._txt(n).strip() for n in doc.get("content", [])
                  if n.get("type") == "heading"
                  and (n.get("attrs") or {}).get("level") == 1), cid[:8])
    # strip the leading "<project>｜" and trailing "（date）" for the hub label
    m = re.match(r"^[^｜]{1,40}｜(.+?)(?:（\d{4}-\d{2}-\d{2}）)?$", title)
    topic = m.group(1) if m else title
    pre = section_named(secs, "前情提要")
    sections = []
    for key, label, color in LEAF_SPECS:
        if key == "這次要回答":
            continue                      # synthesized below, not an H2
        nodes = section_named(secs, key)
        if nodes:
            t = leaf_text(nodes, M.L._txt)
            if t and not any(lbl == label for lbl, _, _ in sections):
                sections.append((label, color, t))
    return {"title": topic,
            "question": question_of(pre, M.L._txt),
            "sections": sections,
            "cites": citations_of(pre, M.L._txt, in_set, cid)}


def render(entry_id, limit=None, dry=False, mode="logs", graph=None):
    import merge_lib as M
    cfg = hbconfig.load_config()
    s = M.scan(entry_id)
    _, doc = M.L.read_card(entry_id)
    title = next((M.L._txt(n).strip() for n in doc["content"]
                  if n.get("type") == "heading"
                  and (n.get("attrs") or {}).get("level") == 1), entry_id[:8])
    if mode == "story":
        gnodes, gedges, gwarns, gmeta = load_story_graph(graph)
        canvas, order = build_storymap(entry_id, title, gnodes, gedges,
                                       PCV.vault_mapper(cfg), limit=limit)
        secs_by_card = []
        for cid in s["chain"]:
            _, d = (None, doc) if cid == entry_id else M.L.read_card(cid)
            secs_by_card.append(
                (cid, [h2 for h2, _, _ in
                       chain_sections(d.get("content"), M.L._txt)]))
        gcov = story_coverage(gnodes, s["done_logs"] + s["pending_logs"],
                              secs_by_card, gmeta.get("coverage_ignore"))
        an = audit_node(entry_id, gcov,
                        -(STORY_W + STORY_HGAP) + LEGEND_W + 40)
        if an:                       # dirty audit → red banner beside legend
            canvas["nodes"].append(an)
        gn = glossary_node(entry_id, gmeta.get("glossary"),
                           -(STORY_W + STORY_HGAP) + LEGEND_W + AUDIT_W + 80)
        if gn:
            canvas["nodes"].append(gn)
    elif mode == "chain":
        # distilled knowledge lives in the chain BODY (pre-log-as-card
        # history): decompose H2/H3 sections card by card, chain order
        per_card = []
        for i, cid in enumerate(s["chain"]):
            _, d = (None, doc) if cid == entry_id else M.L.read_card(cid)
            per_card.append((cid, f"續{i}" if i else "",
                             chain_sections(d.get("content"), M.L._txt)))
        canvas = build_chainmap(entry_id, title, per_card,
                                PCV.vault_mapper(cfg), txt_of=M.L._txt)
        order = [c for c, _, _ in per_card]
    else:
        logs = s["done_logs"] + s["pending_logs"]
        in_set = {e["log"] for e in logs}
        decomp = {e["log"]: decompose(e["log"], in_set, M) for e in logs}
        canvas, order = build_mindmap(entry_id, title, logs, decomp,
                                      PCV.vault_mapper(cfg), limit=limit)
    folders = cfg["obsidian"].get("folders") or {}
    # same home as the timeline canvas (0.43.1): generated views live in
    # <projects folder>/Canvas, overridable via local.folders.project_canvas
    canvas_folder = folders.get("project_canvas") or os.path.join(
        folders.get("projects", "Projects"), "Canvas")
    out_dir = os.path.join(cfg["obsidian"]["vault"], canvas_folder)
    path = os.path.join(out_dir, f"{PCV.safe_filename(title)}·脈絡心智圖.canvas")
    rep = {"entry": entry_id, "title": title, "canvas": path}
    if mode == "story":
        rep.update({"story_nodes": len(order), "limit": limit})
        stages = [x for x in story_stages(gnodes)[1] if x]
        if stages:
            rep["stages"] = stages
        if gwarns:
            rep["label_warnings"] = gwarns
        rep["coverage"] = gcov
    elif mode == "chain":
        rep.update({"chain_cards": len(order),
                    "sections": sum(1 for n in canvas["nodes"]
                                    if n["x"] == 0)})
    else:                       # keep the 0.44.0 logs-mode field order
        rep.update({"logs_total": len(logs), "logs_mapped": len(order),
                    "limit": limit})
    rep.update({"nodes": len(canvas["nodes"]), "edges": len(canvas["edges"]),
                "build_order": [c[:8] for c in order], "mode": mode})
    if dry:
        rep["dry_run"] = True
        return rep
    os.makedirs(out_dir, exist_ok=True)
    json.dump(canvas, open(path, "w"), ensure_ascii=False, indent=1)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True, help="ENTRY card id")
    ap.add_argument("--mode", choices=("logs", "chain", "story"),
                    default="logs",
                    help="拆解單位：logs＝週報 log 卡（預設；引用圖掛枝）"
                         "／chain＝卡鏈正文 H2/H3（結構目錄）"
                         "／story＝研究敘事 DAG（agent 讀鏈產 --graph JSON）")
    ap.add_argument("--graph",
                    help="story 模式必填：敘事 graph JSON 路徑"
                         "（schema 見檔頭；由讀鏈的 agent 撰寫/更新）")
    ap.add_argument("--limit", type=int,
                    help="only the first N logs (citation order) / story "
                         "nodes (narrative order); chain mode 不適用")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be >= 1")
    if args.limit is not None and args.mode == "chain":
        ap.error("--limit 只適用 logs／story 模式（chain 一律整鏈拆解）")
    if args.mode == "story" and not args.graph:
        ap.error("--mode story 需要 --graph <path>")
    if args.graph and args.mode != "story":
        ap.error("--graph 只適用 story 模式")
    cfg = hbconfig.load_config()
    if cfg.get("backend") != "both":
        sys.exit("context mindmap 需要 heptabase＋local 雙底座（backend=both）"
                 "——卡片經 heptabase CLI 讀、canvas 檔住 vault")
    print(json.dumps(render(args.card, limit=args.limit, dry=args.dry_run,
                            mode=args.mode, graph=args.graph),
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
