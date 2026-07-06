#!/usr/bin/env python3
"""One-shot consistency audit of the study/overview knowledge graph.

Checks, against the LIVE Heptabase state:
  1. every study/overview card has a Level value
  2. the root index mentions every study/overview card except itself (tree
     completeness) and mentions nothing outside the tag
  3. every study/overview card is on the knowledge-map whiteboard
  4. lateral-edge sections: every ↔ edge has its mirror on the target card

Exit 0 = consistent, 1 = findings (listed), 2 = read failure.
"""
import json, os, subprocess, sys

# backend routing: obsidian mode audits the vault (Level frontmatter, root
# index coverage, knowledge-map CANVAS membership, ↔ mirrors); heptabase/both
# keep the legacy CLI path. topology-snapshot check is heptabase-only.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.realpath(__file__)),
                                  "..", "..", "_shared"))
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None

TAG_ID = LEVEL_ID = ROOT_ID = WB_ID = None
WB_OPTIONAL = set()
SEC      = "相關主題（橫向連結）"
try:  # all ids from config: heptabase.graph.* + collections.overviews
    import hbconfig as _hbc0
    _g = (_hbc0.load_config().get("heptabase") or {}).get("graph") or {}
    TAG_ID = _hbc0.hb_id("collections", "overviews", "tag_id")
    LEVEL_ID = _g.get("level_prop")
    ROOT_ID = _g.get("root_card")
    WB_ID = _g.get("whiteboard")
    WB_OPTIONAL = set(_g.get("whiteboard_optional") or [])
except Exception:
    pass

def run(a): return subprocess.run(a, capture_output=True, text=True)
def tx(n):
    if n.get("type") == "text": return n.get("text", "")
    return "".join(tx(c) for c in n.get("content", []) if isinstance(c, dict))

def mentions(doc):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "card": out.append(n["attrs"]["cardId"])
            for c in n.get("content", []): walk(c)
    for n in doc["content"]: walk(n)
    return out

def edge_targets(doc):
    """card ids mentioned inside the lateral-edge section, with ↔/→ marker."""
    C = doc["content"]; out = []
    idx = next((i for i, n in enumerate(C)
                if n.get("type") == "heading" and tx(n).strip() == SEC), None)
    if idx is None: return out
    for n in C[idx+1:]:
        if n.get("type") == "heading": break
        ids = mentions({"content": [n]})
        label = tx(n)
        for cid in ids:
            out.append((cid, "↔" if "↔" in label else ("→" if "→" in label else "?")))
    return out

def main_obsidian():
    g = (OBS.cfg["obsidian"].get("graph") or {})
    cards = OBS.list_cards("overviews")
    members = {c["id"]: c["title"] for c in cards}
    findings = []

    # 1. Level present (frontmatter `level`)
    for c in cards:
        if not c["props"].get("level"):
            findings.append(f"[level] {c['id']} has no Level")

    # 2. root index coverage
    root = g.get("root_card")
    if root:
        try:
            _, root_doc = OBS.read_doc(root)
        except Exception as e:
            print(f"ERROR: root card unreadable: {e}"); return 2
        root_list = mentions(root_doc)
        root_m = set(root_list)
        for cid, title in members.items():
            if cid != root and cid not in root_m:
                findings.append(f"[root] index missing {cid}")
        for cid in root_m:
            if cid not in members:
                findings.append(f"[root] index links non-member {cid}")
        if root in root_m:
            findings.append("[root] index mentions ITSELF")
        from collections import Counter
        for cid, n in Counter(root_list).items():
            if n > 1:
                findings.append(f"[root] duplicate mention x{n}: {cid}")
    else:
        print("(root_card 未設定於 config obsidian.graph — 跳過根目錄檢查)")

    # 3. knowledge-map canvas membership
    rel = g.get("canvas")
    if rel:
        from obsidian_canvas import Canvas
        cv = Canvas(os.path.join(OBS.vault, rel))
        on_map = {p[:-3] for p in cv.file_paths() if p and p.endswith(".md")}
        optional = set(g.get("canvas_optional") or [])
        for cid, title in members.items():
            if cid not in on_map and cid not in optional:
                findings.append(f"[canvas] missing {cid}")
    else:
        print("(canvas 未設定於 config obsidian.graph — 跳過知識地圖檢查)")

    # 4. ↔ edges have mirrors
    docs = {}
    for cid in members:
        try:
            docs[cid] = OBS.read_doc(cid)[1]
        except Exception:
            findings.append(f"[read] {cid} unreadable")
    for cid, doc in docs.items():
        for tgt, kind in edge_targets(doc):
            if kind == "↔" and tgt in docs:
                back = {t: k for t, k in edge_targets(docs[tgt])}
                if back.get(cid) != "↔":
                    what = "no mirror" if cid not in back else f"mirror is {back[cid]!r}, not ↔"
                    findings.append(f"[edge] ↔ {cid}→{tgt}: {what}")

    # 5. topology snapshots current (needs obsidian.graph.hubs configured)
    if (g.get("hubs") or {}):
        topo = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            "..", "..", "_shared", "topology.py")
        r = run(["python3", topo, "check"])
        if r.returncode != 0:
            for line in (r.stdout + r.stderr).splitlines():
                if line.startswith("!!") or line.startswith("ERROR"):
                    findings.append(f"[topology] {line.lstrip('! ')}")
            if not any(f.startswith("[topology]") for f in findings):
                findings.append(f"[topology] check failed (rc={r.returncode})")
    else:
        print("(obsidian.graph.hubs 未設定 — 跳過 topology snapshot 檢查)")
    print(f"members: {len(members)}; findings: {len(findings)}")
    for f in findings: print("  !!", f)
    print("[OK] graph consistent." if not findings else "[FAIL] see findings.")
    return 0 if not findings else 1


def main():
    if OBS:
        return main_obsidian()
    missing = [k for k, v in (("collections.overviews.tag_id", TAG_ID),
                              ("graph.level_prop", LEVEL_ID),
                              ("graph.root_card", ROOT_ID),
                              ("graph.whiteboard", WB_ID)) if not v]
    if missing:
        print("ERROR: config 缺少 heptabase." + ", heptabase.".join(missing))
        return 2
    r = run(["heptabase", "tag", "cards", TAG_ID, "--include-properties"])
    try:
        cards = json.loads(r.stdout)["cards"]
    except Exception as e:
        print("ERROR: tag read failed:", e); return 2
    members = {c["id"]: c.get("title", "") for c in cards}
    findings = []

    # 1. Level present
    for c in cards:
        lvl = next((p.get("value") for p in c.get("properties", []) if p["id"] == LEVEL_ID), None)
        if not lvl:
            findings.append(f"[level] {c['id'][:8]} {c.get('title','')[:50]} has no Level")

    # 2. root index coverage
    r = run(["heptabase", "note", "read", ROOT_ID])
    root_doc = json.loads(json.loads(r.stdout)["content"])
    root_list = mentions(root_doc)
    root_m = set(root_list)
    for cid, title in members.items():
        if cid != ROOT_ID and cid not in root_m:
            findings.append(f"[root] index missing {cid[:8]} {title[:50]}")
    for cid in root_m:
        if cid not in members:
            findings.append(f"[root] index links non-member {cid[:8]}")
    if ROOT_ID in root_m:
        findings.append("[root] index mentions ITSELF")
    from collections import Counter
    for cid, n in Counter(root_list).items():
        if n > 1:
            findings.append(f"[root] duplicate mention x{n}: {cid[:8]} {members.get(cid,'?')[:40]}")

    # 3. whiteboard membership
    r = run(["heptabase", "whiteboard", "cards", WB_ID])
    try:
        on_wb = {c["cardId"] for c in json.loads(r.stdout).get("cards", [])}
        for cid, title in members.items():
            if cid not in on_wb and cid not in WB_OPTIONAL:
                findings.append(f"[whiteboard] missing {cid[:8]} {title[:50]}")
    except Exception:
        findings.append("[whiteboard] read failed (whiteboard renamed/removed?)")

    # 4. ↔ edges have mirrors
    docs = {}
    for cid in members:
        r = run(["heptabase", "note", "read", cid])
        try: docs[cid] = json.loads(json.loads(r.stdout)["content"])
        except Exception: findings.append(f"[read] {cid[:8]} unreadable")
    for cid, doc in docs.items():
        for tgt, kind in edge_targets(doc):
            if kind == "↔" and tgt in docs:
                back = {t: k for t, k in edge_targets(docs[tgt])}
                if back.get(cid) != "↔":
                    what = "no mirror" if cid not in back else f"mirror is {back[cid]!r}, not ↔"
                    findings.append(f"[edge] ↔ {cid[:8]}→{tgt[:8]}: {what} on {tgt[:8]}")

    # 5. topology snapshots current (phase 2: graph-derived configs)
    topo = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "..", "..", "_shared", "topology.py")
    r = run(["python3", topo, "check"])
    if r.returncode != 0:
        for line in (r.stdout + r.stderr).splitlines():
            if line.startswith("!!") or line.startswith("ERROR"):
                findings.append(f"[topology] {line.lstrip('! ')}")
        if not any(f.startswith("[topology]") for f in findings):
            findings.append(f"[topology] check failed (rc={r.returncode})")

    print(f"members: {len(members)}; findings: {len(findings)}")
    for f in findings: print("  !!", f)
    print("[OK] graph consistent." if not findings else "[FAIL] see findings.")
    return 0 if not findings else 1

if __name__ == "__main__":
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    sys.exit(main())
