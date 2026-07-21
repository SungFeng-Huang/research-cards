#!/usr/bin/env python3
"""project_canvas — a git-graph style JSON Canvas per project card chain.

One canvas per project: the entry card (the chain "README"/HEAD) sits on
top, log cards (the "commits") hang below it newest-first along a vertical
trunk, edges point in the direction of time (old → new → entry). Colors
carry the distillation state straight from the timeline marks:

    📎 not yet distilled  → orange ("2")
    📗 distilled by merge → green  ("4")
    entry (README)        → purple ("6")
    continuation children → gray side row next to the entry

The canvas is a GENERATED VIEW (rebuilt from scan() every run — do not
hand-arrange it; that's what the knowledge-map canvas is for). Node ids
are deterministic (derived from card ids) so Obsidian doesn't flicker on
regeneration. Log cards mirrored into the vault become clickable file
nodes; unmirrored ones (bridge-created, not yet synced) degrade to text
nodes carrying the summary and a Heptabase link.

Mac-only for now: scan() reads the chain via the local heptabase CLI.

Usage:
    python3 project_canvas.py --card <ENTRY_ID>      # one project
    python3 project_canvas.py --all                  # every hub-listed project
    python3 project_canvas.py --card <ENTRY_ID> --dry-run
"""
import argparse
import hashlib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "_shared"))
sys.path.insert(0, os.path.join(_HERE, "..", "project-card-merge"))
sys.path.insert(0, os.path.join(_HERE, "..", "card-rewrite"))

import hbconfig  # noqa: E402

NODE_W, NODE_H, ENTRY_H, GAP = 520, 120, 150, 44
CHILD_W, CHILD_H = 260, 90
COLOR_PENDING, COLOR_DONE, COLOR_ENTRY = "2", "4", "6"


def _nid(card_id, salt=""):
    return hashlib.md5(f"{salt}{card_id}".encode()).hexdigest()[:16]


def safe_filename(title):
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip() or "project"


def build_canvas(entry_id, entry_title, chain_ids, entries, vault_file_of):
    """Pure layout: timeline entries (each {log, date, summary, done}) →
    JSON Canvas dict. newest-first below the entry; edges old→new→entry.
    vault_file_of(card_id) -> vault-relative .md path or None."""
    nodes, edges = [], []
    entry_file = vault_file_of(entry_id)
    entry_node = {"id": _nid(entry_id), "x": 0, "y": 0,
                  "width": NODE_W, "height": ENTRY_H, "color": COLOR_ENTRY}
    if entry_file:
        entry_node.update({"type": "file", "file": entry_file})
    else:
        entry_node.update({"type": "text",
                           "text": f"# {entry_title}\n（entry 卡未鏡像）"})
    nodes.append(entry_node)

    # continuation children: a gray side row next to the entry (they are
    # pages of the README, not commits)
    for i, cid in enumerate(c for c in chain_ids if c != entry_id):
        f = vault_file_of(cid)
        n = {"id": _nid(cid, "chain"), "x": NODE_W + 80 + i * (CHILD_W + 30),
             "y": 0, "width": CHILD_W, "height": CHILD_H}
        if f:
            n.update({"type": "file", "file": f})
        else:
            n.update({"type": "text", "text": f"續卡 {cid[:8]}（未鏡像）"})
        nodes.append(n)

    ordered = sorted(entries, key=lambda e: (e.get("date") or "", e["log"]),
                     reverse=True)                      # newest first
    prev_node_id = _nid(entry_id)
    for i, e in enumerate(ordered):
        y = ENTRY_H + GAP + i * (NODE_H + GAP)
        f = vault_file_of(e["log"])
        n = {"id": _nid(e["log"]), "x": 0, "y": y,
             "width": NODE_W, "height": NODE_H,
             "color": COLOR_DONE if e.get("done") else COLOR_PENDING}
        if f:
            n.update({"type": "file", "file": f})
        else:
            mark = "📗" if e.get("done") else "📎"
            n.update({"type": "text",
                      "text": (f"{mark} {e.get('date', '')}　"
                               f"{e.get('summary', '')}\n"
                               f"（未鏡像；Heptabase card {e['log'][:8]}）")})
        nodes.append(n)
        # time flows upward: this (older) node points at the newer one above
        edges.append({"id": _nid(e["log"], "edge"),
                      "fromNode": n["id"], "fromSide": "top",
                      "toNode": prev_node_id, "toSide": "bottom"})
        prev_node_id = n["id"]
    return {"nodes": nodes, "edges": edges}


def vault_mapper(cfg):
    """card id -> vault-relative path. Pure-local backend: the card id IS
    the vault-relative id (Folder/Name). Dual-store: resolve through
    heptabase-sync's ledger (folder fallback mirrors backend._folder —
    the raw collection key — matching whoever wrote the file)."""
    if cfg.get("backend") == "obsidian":
        return lambda cid: f"{cid}.md" if "/" in cid else None
    vault = cfg["obsidian"]["vault"]
    folders = cfg["obsidian"].get("folders") or {}
    try:
        state = json.load(open(os.path.join(vault, ".hepta-sync",
                                            "state.json")))
    except Exception:                                        # noqa: BLE001
        state = {"cards": {}}

    def lookup(cid):
        rec = (state.get("cards") or {}).get(cid)
        if not rec:
            return None
        folder = folders.get(rec.get("collection"), rec.get("collection"))
        return f"{folder}/{rec['file']}.md"
    return lookup


def render(entry_id, dry=False):
    import merge_lib as M
    cfg = hbconfig.load_config()
    s = M.scan(entry_id)
    entries = s["done_logs"] + s["pending_logs"]
    title = next((h for h in s.get("headings", [])), "")
    # scan headings are H2s; get the real title from the entry read
    _, doc = M.L.read_card(entry_id)
    title = next((M.L._txt(n).strip() for n in doc["content"]
                  if n.get("type") == "heading"
                  and (n.get("attrs") or {}).get("level") == 1), entry_id[:8])
    canvas = build_canvas(entry_id, title, s["chain"], entries,
                          vault_mapper(cfg))
    folders = cfg["obsidian"].get("folders") or {}
    out_dir = os.path.join(cfg["obsidian"]["vault"],
                           folders.get("projects", "Projects"))
    path = os.path.join(out_dir, f"{safe_filename(title)}.canvas")
    if dry:
        return {"entry": entry_id, "title": title, "canvas": path,
                "nodes": len(canvas["nodes"]), "edges": len(canvas["edges"]),
                "pending": len(s["pending_logs"]), "done": len(s["done_logs"]),
                "dry_run": True}
    os.makedirs(out_dir, exist_ok=True)
    json.dump(canvas, open(path, "w"), ensure_ascii=False, indent=1)
    return {"entry": entry_id, "title": title, "canvas": path,
            "nodes": len(canvas["nodes"]), "edges": len(canvas["edges"]),
            "pending": len(s["pending_logs"]), "done": len(s["done_logs"])}


def all_entries(cfg):
    """Entry card ids from the Research-Projects hub's card mentions."""
    import merge_lib as M
    hub = ((cfg.get("heptabase") or {}).get("collections") or {}) \
        .get("projects", {}).get("hub_card")
    if not hub:
        sys.exit("config heptabase.collections.projects.hub_card 未設定"
                 "——--all 需要 hub 卡列出各專案 entry")
    _, doc = M.L.read_card(hub)
    return M._cardlink_ids(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", help="ENTRY card id")
    ap.add_argument("--all", action="store_true",
                    help="rebuild the canvas of every hub-listed project")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.card and not args.all:
        ap.error("give --card <ENTRY_ID> or --all")
    cfg = hbconfig.load_config()
    if cfg.get("backend") not in ("both", "obsidian"):
        sys.exit("project canvas 需要 local 資料底座（backends 含 local）"
                 "——canvas 檔住在 vault 裡")
    targets = [args.card] if args.card else all_entries(cfg)
    out = [render(cid, dry=args.dry_run) for cid in targets]
    print(json.dumps(out if args.all else out[0], ensure_ascii=False,
                     indent=1))


if __name__ == "__main__":
    main()
