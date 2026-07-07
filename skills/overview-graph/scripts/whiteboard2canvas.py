#!/usr/bin/env python3
"""Mirror Heptabase whiteboards into Obsidian JSON Canvas files (one-way).

v1 data source: a Heptabase「Export all data」backup (All-Data.json) — the
officially re-importable format (ships its own README + schema version).
Point config `heptabase.backup_dir` at the folder holding your backups (the
newest `*/All-Data.json` is picked automatically), or pass --all-data.

Which whiteboards: config `obsidian.graph.mirror_whiteboards` maps
`{"<whiteboard-id>": "<vault-relative>.canvas"}`. Each target .canvas is
REWRITTEN wholesale every run — the layout's source of truth is the
Heptabase whiteboard; don't hand-arrange the mirrored canvas.

Object mapping (JSON Canvas 1.0):
  cardInstance -> "file" node when the card is in the obsidian-sync state
                  (folder rule mirrors sync.py: folders.get(key,
                  key.capitalize())); unsynced cards degrade to a "text"
                  node carrying the title + Heptabase URL
  textElement  -> "text" node (ProseMirror -> markdown via shared pmmd)
  section      -> "group" node (label = title)
  connection   -> edge; begin/endPos map to from/toSide unless "auto";
                  beginStyle/endStyle map to from/toEnd

Prints one JSON report line per run. Exit code 0 even with skipped objects
(they are reported); config/backup errors exit non-zero.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "..", "_shared"))
import hbconfig  # noqa: E402
from pmmd import Converter  # noqa: E402

# Heptabase palette -> JSON Canvas preset colors ("1" red … "6" purple).
COLOR = {"red": "1", "orange": "2", "yellow": "3", "green": "4",
         "blue": "5", "purple": "6"}  # white/default -> omit
SIDES = {"top": "top", "bottom": "bottom", "left": "left", "right": "right"}
STALE_AFTER_DAYS = 7


def find_all_data(explicit):
    if explicit:
        if not os.path.isfile(explicit):
            sys.exit(f"--all-data 檔案不存在：{explicit}")
        return explicit
    root = (hbconfig.load_config().get("heptabase") or {}).get("backup_dir")
    if not root:
        sys.exit("找不到資料來源：傳 --all-data，或在 config 設 "
                 "heptabase.backup_dir（放 Heptabase 備份的資料夾）")
    root = os.path.expanduser(root)
    cands = glob.glob(os.path.join(root, "*", "All-Data.json")) \
        + glob.glob(os.path.join(root, "All-Data.json"))
    if not cands:
        sys.exit(f"backup_dir 裡找不到 All-Data.json：{root}")
    newest = max(cands, key=os.path.getmtime)
    age_days = (time.time() - os.path.getmtime(newest)) / 86400
    if age_days > STALE_AFTER_DAYS:
        print(f"# 注意：最新備份已 {age_days:.0f} 天前（{newest}）——鏡像出的"
              f" canvas 只到備份當下；要即時請重新 Export all data",
              file=sys.stderr)
    return newest


def load_sync_state(vault):
    p = os.path.join(vault, ".hepta-sync", "state.json")
    if not os.path.isfile(p):
        return {}
    try:
        return json.load(open(p)).get("cards") or {}
    except Exception:
        return {}


def card_file(card_id, sync_cards, folders):
    """Vault-relative .md path for a synced card (sync.py's folder rule)."""
    st = sync_cards.get(card_id)
    if not st or not st.get("file"):
        return None
    folder = folders.get(st.get("collection"),
                         str(st.get("collection", "")).capitalize())
    return f"{folder}/{st['file']}.md"


def pm_to_text(content_json, report):
    """textElement ProseMirror -> markdown; placeholders degrade to plain."""
    try:
        doc = json.loads(content_json)
        md = Converter({"id": "textElement", "title": ""}).convert(doc).strip()
    except Exception:
        report["text_convert_errors"] += 1
        return ""
    if "%%HEPTA" in md:  # embeds/files inside a floating text — keep the rest
        report["text_placeholders_stripped"] += 1
        md = re.sub(r"%%HEPTA[^%]*%%", "", md)
        md = "\n".join(l.rstrip() for l in md.splitlines() if l.strip()).strip()
    return md


def build_canvas(wb_id, data, sync_cards, folders, workspace, report):
    titles = {c["id"]: c.get("title") or "(untitled)" for c in data.get("cardList", [])}
    trashed = {c["id"] for c in data.get("cardList", []) if c.get("isTrashed")}
    nodes, node_ids = [], set()

    for s in data.get("sections", []):
        if s.get("whiteboardId") != wb_id:
            continue
        n = {"id": s["id"], "type": "group",
             "x": round(s["x"]), "y": round(s["y"]),
             "width": round(s["width"]), "height": round(s["height"]),
             "label": s.get("title") or ""}
        if COLOR.get(s.get("color")):
            n["color"] = COLOR[s["color"]]
        nodes.append(n)

    for i in data.get("cardInstances", []):
        if i.get("whiteboardId") != wb_id:
            continue
        if i.get("cardId") in trashed:
            report["skipped_trashed"] += 1
            continue
        height = i.get("foldedHeight") if i.get("isFolded") \
            and (i.get("foldedHeight") or 0) > 0 else i.get("height")
        n = {"id": i["id"],
             "x": round(i["x"]), "y": round(i["y"]),
             "width": round(i["width"]), "height": round(height)}
        if COLOR.get(i.get("color")):
            n["color"] = COLOR[i["color"]]
        f = card_file(i.get("cardId"), sync_cards, folders)
        if f:
            n["type"] = "file"
            n["file"] = f
        else:
            title = titles.get(i.get("cardId"), "(unknown card)")
            n["type"] = "text"
            n["text"] = (f"**{title}**\n\n[在 Heptabase 開啟]"
                         f"(https://app.heptabase.com/{workspace}/card/{i.get('cardId')})")
            report["unsynced_cards"].append(title)
        nodes.append(n)

    for t in data.get("textElements", []):
        if t.get("whiteboardId") != wb_id:
            continue
        nodes.append({"id": t["id"], "type": "text",
                      "x": round(t["x"]), "y": round(t["y"]),
                      "width": round(t["width"]), "height": round(t["height"]),
                      "text": pm_to_text(t.get("content") or "{}", report)})

    node_ids = {n["id"] for n in nodes}
    other = [x for o in ("mediaElements", "pdfCardInstances", "mindMapInstances",
                         "webElements", "chatInstances", "journalInstances",
                         "whiteboardInstances", "insightInstances",
                         "highlightElementInstances", "mediaCardInstances")
             for x in data.get(o, []) if x.get("whiteboardId") == wb_id]
    report["skipped_unsupported"] += len(other)

    edges = []
    for c in data.get("connections", []):
        if c.get("whiteboardId") != wb_id:
            continue
        if c["beginId"] not in node_ids or c["endId"] not in node_ids:
            report["skipped_dangling_edges"] += 1
            continue
        e = {"id": c["id"], "fromNode": c["beginId"], "toNode": c["endId"]}
        if SIDES.get(c.get("beginPos")):
            e["fromSide"] = SIDES[c["beginPos"]]
        if SIDES.get(c.get("endPos")):
            e["toSide"] = SIDES[c["endPos"]]
        # Heptabase default: no tail, arrow head. Canvas default is the same,
        # so only deviations are emitted.
        if c.get("beginStyle") == "default":
            e["fromEnd"] = "arrow"
        if c.get("endStyle") == "none":
            e["toEnd"] = "none"
        if COLOR.get(c.get("color")):
            e["color"] = COLOR[c["color"]]
        desc = c.get("description") or ""
        if desc.lstrip().startswith("{"):  # PM doc, not plain text
            desc = pm_to_text(desc, report)
        if desc:
            e["label"] = desc
        edges.append(e)

    # JSON Canvas array order IS z-order (earlier = below): groups first so
    # sections never cover their cards; deterministic id order within layers.
    nodes.sort(key=lambda n: (0 if n["type"] == "group" else 1, n["id"]))
    edges.sort(key=lambda e: e["id"])
    return {"nodes": nodes, "edges": edges}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-data", help="Heptabase 備份的 All-Data.json 路徑"
                    "（預設：config heptabase.backup_dir 裡最新一份）")
    ap.add_argument("--whiteboard", help="只鏡像這個 whiteboard id"
                    "（預設：config 裡登記的全部）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = hbconfig.load_config()
    obs = cfg.get("obsidian") or {}
    vault = os.path.expanduser(obs.get("vault") or "")
    if not vault or not os.path.isdir(vault):
        sys.exit("config obsidian.vault 未設定或不存在")
    mirrors = ((obs.get("graph") or {}).get("mirror_whiteboards")) or {}
    if args.whiteboard:
        if args.whiteboard not in mirrors:
            sys.exit(f"config obsidian.graph.mirror_whiteboards 沒有 "
                     f"{args.whiteboard} 的條目（值=輸出 .canvas 的 vault 相對路徑）")
        mirrors = {args.whiteboard: mirrors[args.whiteboard]}
    if not mirrors:
        sys.exit("config obsidian.graph.mirror_whiteboards 是空的——"
                 '加 {"<whiteboard-id>": "Maps/我的地圖.canvas"} 後再跑')

    src = find_all_data(args.all_data)
    try:
        data = json.load(open(src))
        if not isinstance(data.get("whiteBoardList"), list):
            raise ValueError("缺 whiteBoardList——不是 All-Data.json？")
    except Exception as e:
        sys.exit(f"備份檔無法解析（{src}）：{e}")
    known = {w["id"]: w.get("name") for w in data.get("whiteBoardList", [])}
    sync_cards = load_sync_state(vault)
    folders = obs.get("folders") or {}
    workspace = (cfg.get("heptabase") or {}).get("workspace_id") or "app"

    report = {"source": src, "written": [], "not_in_backup": [],
              "unsynced_cards": [], "skipped_trashed": 0,
              "skipped_unsupported": 0, "skipped_dangling_edges": 0,
              "text_convert_errors": 0, "text_placeholders_stripped": 0}
    staged = []  # build EVERYTHING first — a crash mid-way must not leave a partial mirror set
    for wb_id, rel in mirrors.items():
        if wb_id not in known:
            report["not_in_backup"].append(wb_id)
            continue
        canvas = build_canvas(wb_id, data, sync_cards, folders, workspace, report)
        out = os.path.join(vault, rel)
        if not os.path.realpath(out).startswith(os.path.realpath(vault) + os.sep):
            sys.exit(f"輸出路徑逸出 vault：{rel!r}")
        staged.append((wb_id, rel, out, canvas))
    for wb_id, rel, out, canvas in staged:
        if not args.dry_run:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w") as f:
                json.dump(canvas, f, ensure_ascii=False, indent=1)
                f.write("\n")
        report["written"].append({"whiteboard": known[wb_id], "canvas": rel,
                                  "nodes": len(canvas["nodes"]),
                                  "edges": len(canvas["edges"]),
                                  "dry_run": args.dry_run})
    print(json.dumps({k: v for k, v in report.items() if v},
                     ensure_ascii=False))
    if not report["written"]:  # every requested whiteboard was missing — not a success
        sys.exit(f"備份裡找不到任何要鏡像的 whiteboard：{report['not_in_backup']}"
                 "（備份太舊？重新 Export all data）")


if __name__ == "__main__":
    main()
