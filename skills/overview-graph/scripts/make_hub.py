#!/usr/bin/env python3
"""Create a topic-hub overview card from a JSON spec.

Spec (JSON file passed as argv[1]):
{
  "title": "…",                       # H1 + card title
  "blocks": [
    ["md",  "paragraph text with **bold** spans"],
    ["h2",  "section heading"],
    ["card", "<card-id>", "one-line description (rendered after the mention)"],
    ["hr"]
  ]
}
Creates the card, fills content (real card mentions), tags it study/overview,
prints the new card id.
"""
import json, subprocess, tempfile, os, sys

# backend routing: obsidian mode creates the hub in the vault (and drops a
# node on the knowledge-map canvas); heptabase/both keep the legacy CLI path.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.realpath(__file__)),
                                  "..", "..", "_shared"))
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None


def canvas_add(card_id):
    """obsidian mode: ensure the new card has a node on the knowledge-map
    canvas (additive; never touches user layout). Returns a status string."""
    g = (OBS.cfg["obsidian"].get("graph") or {})
    rel = g.get("canvas")
    if not rel:
        return "no canvas configured"
    from obsidian_canvas import Canvas
    cv = Canvas(_os.path.join(OBS.vault, rel))
    added = cv.add_file(card_id + ".md")
    cv.save()
    return "added to canvas" if added else "already on canvas"

def run(args):
    return subprocess.run(args, capture_output=True, text=True)

def inline(text):
    parts = text.split("**")
    if len(parts) % 2 == 0:
        parts = [text]
    out = []
    for i, seg in enumerate(parts):
        if seg == "":
            continue
        n = {"type": "text", "text": seg}
        if i % 2 == 1:
            n["marks"] = [{"type": "strong"}]
        out.append(n)
    return out or [{"type": "text", "text": ""}]

def H(l, t): return {"type":"heading","attrs":{"id":None,"level":l},"content":inline(t)}
def P(nodes): return {"type":"paragraph","attrs":{"id":None},"content":nodes}
def hr(): return {"type":"horizontal_rule","attrs":{"id":None}}
def card_bullet(cid, desc):
    return {"type":"bullet_list_item","attrs":{"id":None,"folded":False,"format":None},
            "content":[P([{"type":"card","attrs":{"cardId":cid}},
                          {"type":"text","text":"　"+desc}])]}

def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    title = spec["title"]

    if OBS:
        cid = OBS.create_card("overviews", title, "")
        md5, doc = OBS.read_doc(cid)
    else:
        r = run(["heptabase", "note", "create", "--content", f"# {title}"])
        if r.returncode != 0:
            print("create failed:", r.stderr[:300]); return 1
        cid = json.loads(r.stdout)["id"]

        r = run(["heptabase", "note", "read", cid])
        data = json.loads(r.stdout)
        md5 = data["contentMd5"]; doc = json.loads(data["content"])

    nodes = [H(1, title)]
    for blk in spec["blocks"]:
        kind = blk[0]
        if kind == "md":   nodes.append(P(inline(blk[1])))
        elif kind == "h2": nodes.append(H(2, blk[1]))
        elif kind == "card": nodes.append(card_bullet(blk[1], blk[2]))
        elif kind == "hr": nodes.append(hr())
        else: print("unknown block kind:", kind); return 1
    doc["content"] = nodes

    if OBS:
        try:
            OBS.save_doc(cid, md5, doc)
        except Exception as e:
            print("save failed:", str(e)[:300]); return 1
        print(f"OK created hub card: {cid}  ({canvas_add(cid)})")
        return 0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False); tmp = f.name
    try:
        r = run(["heptabase", "note", "save", cid, "--content-md5", md5, "--content-file", tmp])
    finally:
        os.unlink(tmp)
    if r.returncode != 0:
        print("save failed:", r.stderr[:300]); return 1

    r = run(["heptabase", "tag", "add", "--card-id", cid, "--tag-name", "study/overview"])
    tag_ok = (r.returncode == 0)
    print(f"OK created hub card: {cid}  (tagged study/overview: {tag_ok})")
    return 0

try:
    import hbconfig as _hbc_gate
    if not _hbc_gate.feature_enabled("study"):
        sys.exit("study 方向已在 config features.study 停用")
except ImportError:
    pass
sys.exit(main())
