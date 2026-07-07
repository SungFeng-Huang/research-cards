#!/usr/bin/env python3
"""Mirror Heptabase whiteboards into Obsidian JSON Canvas files (one-way).

Data sources (freshest available wins):
  live (default)  the desktop app's own SQLite store (`hepta.db` under
                  ~/Library/Application Support/project-meta — override via
                  config heptabase.app_data_dir or --live-db). A consistent
                  snapshot is taken with SQLite's backup API; the app can
                  stay open. UNDOCUMENTED schema — guarded by an explicit
                  table/column check that fails loudly and points at the
                  backup source instead.
  backup          a Heptabase「Export all data」backup (All-Data.json, the
                  officially re-importable format). config
                  heptabase.backup_dir (newest is picked) or --all-data.
--all-data / --live-db force their source; otherwise live is tried first,
then backup.

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
import sqlite3
import sys
import urllib.parse
import tempfile
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


DEFAULT_APP_DATA = "~/Library/Application Support/project-meta"
# live hepta.db table -> (All-Data key, snake_case -> camelCase columns)
LIVE_TABLES = {
    "whiteboard": ("whiteBoardList", {"id": "id", "name": "name",
                                      "is_trashed": "isTrashed"}),
    "card": ("cardList", {"id": "id", "title": "title",
                          "is_trashed": "isTrashed"}),
    "card_instance": ("cardInstances", {
        "id": "id", "whiteboard_id": "whiteboardId", "card_id": "cardId",
        "x": "x", "y": "y", "width": "width", "height": "height",
        "color": "color", "is_folded": "isFolded",
        "folded_height": "foldedHeight"}),
    "text_element": ("textElements", {
        "id": "id", "whiteboard_id": "whiteboardId", "content": "content",
        "x": "x", "y": "y", "width": "width", "height": "height"}),
    "section": ("sections", {
        "id": "id", "whiteboard_id": "whiteboardId", "title": "title",
        "color": "color", "x": "x", "y": "y",
        "width": "width", "height": "height"}),
    "connection": ("connections", {
        "id": "id", "whiteboard_id": "whiteboardId", "begin_id": "beginId",
        "end_id": "endId", "begin_pos": "beginPos", "end_pos": "endPos",
        "begin_style": "beginStyle", "end_style": "endStyle",
        "color": "color", "description": "description"}),
}


def find_live_db(explicit):
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    root = (hbconfig.load_config().get("heptabase") or {}).get("app_data_dir")         or DEFAULT_APP_DATA
    p = os.path.join(os.path.expanduser(root), "hepta.db")
    return p if os.path.isfile(p) else None


class LiveSchemaError(RuntimeError):
    """The live DB opened fine but its schema is not what we expect —
    NEVER silently fall back to a (possibly stale) backup on this."""


def load_live(db_path, wb_ids=None):
    """Consistent snapshot of the app's SQLite store -> All-Data-shaped dict.

    The schema is UNDOCUMENTED (observed at DB level); every table/column we
    rely on is checked first so an app update changes this into a clear
    error, never silently wrong output."""
    with tempfile.TemporaryDirectory(prefix="hb-live-") as td:
        snap = os.path.join(td, "snap.db")
        try:
            quoted = urllib.parse.quote(os.path.abspath(db_path))
            src = sqlite3.connect(f"file:{quoted}?mode=ro", uri=True)
            dst = sqlite3.connect(snap)
            src.backup(dst)
            src.close()
        except sqlite3.Error as e:
            raise RuntimeError(f"live DB 快照失敗（{db_path}）：{e}")
        dst.row_factory = sqlite3.Row
        have = {r[0] for r in dst.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in LIVE_TABLES if t not in have]
        if missing:
            raise LiveSchemaError(f"live DB 缺表 {missing}——app 版本的 "
                                  "schema 可能變了；確認後改用備份來源（--all-data）")
        data = {}
        for table, (key, colmap) in LIVE_TABLES.items():
            cols = {r[1] for r in dst.execute(f"PRAGMA table_info({table})")}
            lack = [c for c in colmap if c not in cols]
            if lack:
                raise LiveSchemaError(f"live DB 表 {table} 缺欄位 {lack}——"
                                      "schema 可能變了；確認後改用備份來源（--all-data）")
            sel = ", ".join(colmap)
            data[key] = [
                {camel: row[snake] for snake, camel in colmap.items()}
                for row in dst.execute(f"SELECT {sel} FROM {table}")]
        # card content is only needed for mention-line derivation on the
        # mirrored boards — fetch just those cards, not the whole workspace
        need = {i["cardId"] for i in data["cardInstances"]
                if wb_ids is None or i["whiteboardId"] in wb_ids}
        contents = {}
        need_list = sorted(c for c in need if c)
        for i in range(0, len(need_list), 500):
            chunk = need_list[i:i + 500]
            q = ",".join("?" * len(chunk))
            for row in dst.execute(
                    f"SELECT id, content FROM card WHERE id IN ({q})", chunk):
                contents[row["id"]] = row["content"]
        for c in data["cardList"]:
            if c["id"] in contents:
                c["content"] = contents[c["id"]]
        # census-only tables (unsupported object types) — best effort so the
        # skipped_unsupported report matches the backup source
        census = {"media_element": "mediaElements",
                  "pdf_card_instance": "pdfCardInstances",
                  "mind_map_instance": "mindMapInstances",
                  "web_element": "webElements",
                  "chat_instance": "chatInstances",
                  "journal_instance": "journalInstances",
                  "whiteboard_instance": "whiteboardInstances",
                  "insight_instance": "insightInstances",
                  "highlight_element_instance": "highlightElementInstances",
                  "media_card_instance": "mediaCardInstances"}
        for table, key in census.items():
            if table not in have:
                continue
            cols = {r[1] for r in dst.execute(f"PRAGMA table_info({table})")}
            if "whiteboard_id" not in cols:
                continue
            data[key] = [{"whiteboardId": row["whiteboard_id"]}
                         for row in dst.execute(
                             f"SELECT whiteboard_id FROM {table}")]
        dst.close()
    for c in data["cardList"]:
        c["isTrashed"] = bool(c["isTrashed"])
    for i in data["cardInstances"]:
        i["isFolded"] = bool(i["isFolded"])
    # trashed whiteboards behave like the export (absent from whiteBoardList)
    data["whiteBoardList"] = [w for w in data["whiteBoardList"]
                              if not w.pop("isTrashed", False)]
    return data


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


def mention_ids(content_json):
    """Card ids mentioned in a card's ProseMirror content (mention nodes:
    {"type": "card", "attrs": {"cardId": ...}} — what Heptabase draws its
    automatic mention lines from)."""
    try:
        doc = json.loads(content_json or "{}")
    except Exception:
        return set()
    out = set()
    stack = [doc]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            if n.get("type") == "card" and (n.get("attrs") or {}).get("cardId"):
                out.add(n["attrs"]["cardId"])
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)
    return out


def mention_edges(instances, contents, connected_pairs):
    """Canvas edges for card-mention links between instances on the board.
    Mutual mentions collapse into one double-arrow edge; pairs already tied
    by an explicit connection are skipped."""
    directed = set()
    for a_card, a_insts in instances.items():
        for target in mention_ids(contents.get(a_card)) & set(instances):
            if target != a_card:
                directed.add((a_card, target))
    edges = []
    for a_card, b_card in sorted(directed):
        mutual = (b_card, a_card) in directed
        if mutual and a_card > b_card:
            continue  # 由 id 小的那一方代表雙向邊
        for a in instances[a_card]:
            for b in instances[b_card]:
                if frozenset((a, b)) in connected_pairs:
                    continue
                e = {"id": f"mention:{a}:{b}", "fromNode": a, "toNode": b}
                if mutual:
                    e["fromEnd"] = "arrow"
                edges.append(e)
    return edges


def build_canvas(wb_id, data, sync_cards, folders, workspace, report,
                 want_mentions=True):
    titles = {c["id"]: c.get("title") or "(untitled)" for c in data.get("cardList", [])}
    trashed = {c["id"] for c in data.get("cardList", []) if c.get("isTrashed")}
    nodes, node_ids, inst_card = [], set(), {}

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
        inst_card[i["id"]] = i.get("cardId")
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
    if want_mentions:
        instances = {}
        for n in nodes:
            cid = inst_card.get(n["id"])
            if cid:
                instances.setdefault(cid, []).append(n["id"])
        contents = {c["id"]: c.get("content") for c in data.get("cardList", [])
                    if c["id"] in instances}
        connected_pairs = {frozenset((e["fromNode"], e["toNode"]))
                           for e in edges}
        m = mention_edges(instances, contents, connected_pairs)
        report["mention_edges"] += len(m)
        edges.extend(m)

    nodes.sort(key=lambda n: (0 if n["type"] == "group" else 1, n["id"]))
    edges.sort(key=lambda e: e["id"])
    return {"nodes": nodes, "edges": edges}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-data", help="強制用備份來源：All-Data.json 路徑"
                    "（不給路徑時的順位：live hepta.db → config "
                    "heptabase.backup_dir 最新備份）")
    ap.add_argument("--live-db", help="強制用 live 來源：hepta.db 路徑"
                    "（預設 config heptabase.app_data_dir 或 "
                    f"{DEFAULT_APP_DATA}）")
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

    if args.all_data and args.live_db:
        sys.exit("--all-data 與 --live-db 只能擇一")
    src = data = None
    if not args.all_data:
        live = find_live_db(args.live_db)
        if live:
            try:
                data = load_live(live, wb_ids=set(mirrors))
                src = f"live:{live}"
            except LiveSchemaError as e:
                sys.exit(str(e))  # 漂移必須大聲，退回舊備份會靜默出爛資料
            except RuntimeError as e:
                if args.live_db:
                    sys.exit(str(e))
                print(f"# live 來源不可用（{e}）——退回備份", file=sys.stderr)
        elif args.live_db:
            sys.exit(f"--live-db 檔案不存在：{args.live_db}")
    if data is None:
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

    want_mentions = bool(((obs.get("graph") or {})
                          .get("mirror_mention_edges", True)))
    report = {"source": src, "written": [], "not_in_backup": [],
              "unsynced_cards": [], "skipped_trashed": 0,
              "skipped_unsupported": 0, "skipped_dangling_edges": 0,
              "mention_edges": 0,
              "text_convert_errors": 0, "text_placeholders_stripped": 0}
    staged = []  # build EVERYTHING first — a crash mid-way must not leave a partial mirror set
    for wb_id, rel in mirrors.items():
        if wb_id not in known:
            report["not_in_backup"].append(wb_id)
            continue
        canvas = build_canvas(wb_id, data, sync_cards, folders, workspace,
                              report, want_mentions=want_mentions)
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
