#!/usr/bin/env python3
"""Mechanical re-split executor: backup cards, create new skeleton cards, move
L3 paper sections + dimension-table rows between cards, retitle cards.

Usage: python3 resplit.py <plan.json> [--dry-run]
Plan:
{
  "dim_cols": ["論文", …],                      # dim-table header for NEW cards
  "new_cards": [{"key":"T2","title":"…","intro":"…"}],
  "retitle": {"<card-id>": "new title", …},
  "moves": [{"key":"<heading substring>","from":"<id>","to":"<id or new-card key>"}]
}
Sections live between the 各論文核心貢獻與設計差異 and 關鍵設計維度對比 headings.
"""
import json, subprocess, tempfile, os, sys, datetime

# backend routing: obsidian mode moves sections between vault cards (new cards
# also get a knowledge-map canvas node); heptabase/both keep the legacy path.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.realpath(__file__)),
                                  "..", "..", "_shared"))
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None

SEC_A, SEC_B = "各論文核心貢獻與設計差異", "關鍵設計維度對比"
BK_DIR = os.path.expanduser("~/.cache/overview-resplit")

def run(a): return subprocess.run(a, capture_output=True, text=True)
def tx(n):
    if n.get("type") == "text": return n.get("text", "")
    return "".join(tx(c) for c in n.get("content", []) if isinstance(c, dict))

def read_card(cid):
    if OBS:
        return OBS.read_doc(cid)
    r = run(["heptabase", "note", "read", cid]); d = json.loads(r.stdout)
    return d["contentMd5"], json.loads(d["content"])

def save_card(cid, md5, doc):
    if OBS:
        return OBS.save_doc(cid, md5, doc)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False); tmp = f.name
    try:
        r = run(["heptabase", "note", "save", cid, "--content-md5", md5, "--content-file", tmp])
        if r.returncode != 0: raise RuntimeError(f"save {cid}: {r.stderr[:200]}")
    finally: os.unlink(tmp)

def H(l, t): return {"type":"heading","attrs":{"id":None,"level":l},"content":[{"type":"text","text":t}]}
def P(t): return {"type":"paragraph","attrs":{"id":None},"content":[{"type":"text","text":t}] if t else []}
def hidx(C, title):
    for i, n in enumerate(C):
        if n.get("type") == "heading" and tx(n).strip() == title: return i
    raise KeyError(title)

def blocks_of(C):
    """[(heading_text, start, end)] of L3 blocks between SEC_A and SEC_B."""
    a, b = hidx(C, SEC_A) + 1, hidx(C, SEC_B)
    out, cur_start, cur_head = [], None, None
    for i in range(a, b):
        n = C[i]
        if n.get("type") == "heading" and n["attrs"].get("level") == 3:
            if cur_start is not None: out.append((cur_head, cur_start, i))
            cur_start, cur_head = i, tx(n).strip()
    if cur_start is not None: out.append((cur_head, cur_start, b))
    return out

def dim_table(C):
    hi = hidx(C, SEC_B)
    for i in range(hi, len(C)):
        if C[i].get("type") == "table": return i
    raise KeyError("dim table")

def cell_cols(dim_cols):
    def cell(t, hdr=False):
        return {"type": "table_header" if hdr else "table_cell",
                "attrs": {"id":None,"colspan":1,"rowspan":1,"colwidth":None,
                          "backgroundColor":None,"textColor":None},
                "content":[P(t)] if False else [{"type":"paragraph","attrs":{"id":None},
                          "content":([{"type":"text","text":t}] if t else [])}]}
    return {"type":"table","attrs":{"id":None},
            "content":[{"type":"table_row","attrs":{"id":None},
                        "content":[cell(c, True) for c in dim_cols]}]}

def skeleton(title, intro, dim_cols):
    return [H(1,title), P(intro),
            H(2,"架構典範分類"), P("（由敘事整理階段補上）"),
            H(2,SEC_A),
            H(2,SEC_B), cell_cols(dim_cols),
            H(2,"主要研究方向歸納"), P("（由敘事整理階段補上）")]

def main():
    plan = json.load(open(sys.argv[1], encoding="utf-8"))
    dry = "--dry-run" in sys.argv
    ids = {m["from"] for m in plan["moves"]} | set(plan.get("retitle", {}))
    ids |= {m["to"] for m in plan["moves"] if "-" in m["to"]}

    docs = {}
    for cid in ids:
        md5, doc = read_card(cid); docs[cid] = [md5, doc, False]

    # dry-run resolution check
    problems = []
    valid_dsts = {nc["key"] for nc in plan.get("new_cards", [])} | ids
    for m in plan["moves"]:
        if m["to"] not in valid_dsts:
            problems.append(f"destination {m['to']!r} is neither a new-card key nor a read card id")
    for m in plan["moves"]:
        C = docs[m["from"]][1]["content"]
        hits = [h for h, s, e in blocks_of(C) if m["key"] in h]
        if len(hits) != 1:
            problems.append(f"{m['key']!r} in {m['from'][:8]}: {len(hits)} matches {hits}")
    print(f"moves: {len(plan['moves'])}; resolution problems: {len(problems)}")
    for p in problems: print("  !!", p)
    if dry:
        for m in plan["moves"]:
            C = docs[m["from"]][1]["content"]
            h = next((h for h, s, e in blocks_of(C) if m["key"] in h), None)
            if h is None:
                print(f"  !! {m['from'][:8]} -> {m['to'][:12]:12} | {m['key']!r} UNRESOLVED — skipped")
                continue
            # row present?
            ti = dim_table(C)
            row = any(m["key"].split("（")[0].lower() in tx(r["content"][0]).lower()
                      for r in C[ti]["content"][1:])
            print(f"  OK {m['from'][:8]} -> {m['to'][:12]:12} | {h[:46]:48} row={row}")
        return 0 if not problems else 1
    if problems:
        print("ABORT: unresolved keys"); return 1

    # backups
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    bdir = os.path.join(BK_DIR, ts); os.makedirs(bdir, exist_ok=True)
    for cid, (md5, doc, _) in docs.items():
        with open(os.path.join(bdir, cid.replace("/", "__") + ".json"), "w", encoding="utf-8") as f:
            json.dump({"contentMd5": md5, "content": doc}, f, ensure_ascii=False)
    print("backups:", bdir)

    # create new cards
    keymap = {}
    for nc in plan.get("new_cards", []):
        if OBS:
            cid = OBS.create_card("overviews", nc["title"], "")
        else:
            r = run(["heptabase", "note", "create", "--content", "# " + nc["title"]])
            if r.returncode != 0: raise RuntimeError("create failed: " + r.stderr[:200])
            cid = json.loads(r.stdout)["id"]
        keymap[nc["key"]] = cid
        md5, doc = read_card(cid)
        doc["content"] = skeleton(nc["title"], nc["intro"], plan["dim_cols"])
        docs[cid] = [md5, doc, True]
        if OBS:
            g = (OBS.cfg["obsidian"].get("graph") or {})
            if g.get("canvas"):
                from obsidian_canvas import Canvas
                cv = Canvas(os.path.join(OBS.vault, g["canvas"]))
                cv.add_file(cid + ".md"); cv.save()
        else:
            run(["heptabase", "tag", "add", "--card-id", cid, "--tag-name", "study/overview"])
        print(f"created {nc['key']} = {cid}")

    # moves (collect cuts per source first to avoid index invalidation)
    for m in plan["moves"]:
        src = m["from"]; dst = keymap.get(m["to"], m["to"])
        C = docs[src][1]["content"]
        h, s, e = next((h, s, e) for h, s, e in blocks_of(C) if m["key"] in h)
        block = C[s:e]
        # trailing hr of the previous section stays; ensure block ends with hr
        if block[-1].get("type") != "horizontal_rule":
            block = block + [{"type":"horizontal_rule","attrs":{"id":None}}]
        del C[s:e]
        # cut dim row if present
        ti = dim_table(C)
        row = None
        base = m["key"].split("（")[0].lower()
        for j, r0 in enumerate(C[ti]["content"][1:], start=1):
            if base in tx(r0["content"][0]).lower(): row = j; break
        rownode = C[ti]["content"].pop(row) if row else None
        # insert into dest
        D = docs[dst][1]["content"]
        di = hidx(D, SEC_B)
        D[di:di] = block
        if rownode is not None:
            tj = dim_table(D)
            docs[dst][1]["content"][tj]["content"].append(rownode)
        docs[src][2] = docs[dst][2] = True
        print(f"moved {h[:40]:42} {src[:8]} -> {dst[:8]} row={'yes' if rownode else 'no'}")

    # retitles
    for cid, title in plan.get("retitle", {}).items():
        C = docs[cid][1]["content"]
        if C and C[0].get("type") == "heading" and C[0]["attrs"]["level"] == 1:
            C[0]["content"] = [{"type": "text", "text": title}]
        else:
            C.insert(0, H(1, title))
        docs[cid][2] = True
        print(f"retitled {cid[:8]} -> {title[:50]}")

    for cid, (md5, doc, dirty) in docs.items():
        if dirty: save_card(cid, md5, doc)
    print("saved.")
    # final inventory
    for cid in docs:
        _, doc = read_card(cid)
        n = len(blocks_of(doc["content"]))
        print(f"  {cid[:8]}: {n} sections | title: {tx(doc['content'][0])[:60]}")
    if keymap: print("new card ids:", json.dumps(keymap))
    return 0

try:
    import hbconfig as _hbc_gate
    if not _hbc_gate.feature_enabled("study"):
        sys.exit("study 方向已在 config features.study 停用")
except ImportError:
    pass
sys.exit(main())
