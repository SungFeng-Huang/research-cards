#!/usr/bin/env python3
"""project_canvas — a git-graph style JSON Canvas per project card chain.

One canvas per project, laid out like a real git graph: log cards (the
"commits") run newest-on-top along a vertical trunk, edges pointing in
the direction of time (old → new). The entry card is the HEAD pointer —
it sits BESIDE the newest distilled (📗) log and points at it laterally,
so everything ABOVE the entry is exactly the not-yet-distilled (📎)
backlog. Distillation state is thus carried by TOPOLOGY (where HEAD
attaches), which frees the color axis for origin — the default:

    Mac session      → cyan   ("5")
    cluster session  → yellow ("3")
    undeterminable   → gray   (uncolored)
    entry (HEAD)     → purple ("6")
    continuation children → gray row riding beside the entry

--color-by state recolors the LOG cards by their timeline mark instead
(the pre-0.51 axis, now redundant with the topology):

    📎 not yet distilled  → orange ("2")
    📗 distilled by merge → green  ("4")

Origin is read from the log card itself: the weekly-report header's
`**環境**：<host>` field (0.42.0 spec), falling back to the retro-split
provenance line `原段：📥 Mac 補充…`/`📥 cluster 補充…` (cards split out
of legacy 📥 append blocks). Unmirrored text nodes keep their 📎/📗 mark
in both modes. Default mode comes from config
heptabase.collections.projects.canvas_color_by (origin|state).

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
COLOR_MAC, COLOR_CLUSTER = "5", "3"

# origin signals live in the log card's OPENING lines (title + header /
# retro-split provenance); cap the scan so prose QUOTING one of these
# patterns deeper in the body can never flip a card's origin
ORIGIN_SCAN_CHARS = 800
# the 環境 FIELD, not the word in prose: must start a segment (line start,
# whitespace, 　, or an opening bracket) — "執行環境：Mac" never matches.
# Value stops at * so a following **代碼** field can't bleed in.
_ENV_RE = re.compile(r"(?:^|[\s　（(])\*{0,2}環境\*{0,2}\s*[:：]\s*([^\n　*｜]*)")
# the retro-split provenance line requires its 原段 anchor on the same
# line — prose merely quoting "📥 cluster 補充" carries no origin
_RETRO_RE = re.compile(r"原段\s*[:：][^\n]*?📥\s*([^\s　]{1,24})\s*(?:補充|進度)")
# whole-word mac (machine-01 must NOT match) or the Mac-ish CJK names
_MAC_RE = re.compile(r"\bmac\b|\bmacbook\b|\bmacos\b|本機", re.I)


def log_origin(text):
    """'mac' | 'cluster' | None from a log card's opening text. Precedence:
    the weekly-report 環境 field (explicit, 0.42.0 spec), then the
    retro-split 原段 line's 📥 <origin> marker. A 環境 value naming the
    Mac wins as mac; any other non-empty value is a remote host →
    cluster."""
    head = (text or "")[:ORIGIN_SCAN_CHARS]
    m = _ENV_RE.search(head)
    if m:
        v = m.group(1).strip()
        if v:
            return "mac" if _MAC_RE.search(v) else "cluster"
    m = _RETRO_RE.search(head)
    if m:
        v = m.group(1)
        if _MAC_RE.search(v):
            return "mac"
        if re.search(r"cluster", v, re.I):
            return "cluster"
    return None


def origin_color(origin):
    return {"mac": COLOR_MAC, "cluster": COLOR_CLUSTER}.get(origin)


def _nid(card_id, salt=""):
    return hashlib.md5(f"{salt}{card_id}".encode()).hexdigest()[:16]


def safe_filename(title):
    return re.sub(r'[\\/:*?"<>|]', "-", title).strip() or "project"


def build_canvas(entry_id, entry_title, chain_ids, entries, vault_file_of,
                 color_by="origin"):
    """Pure layout: timeline entries (each {log, date, summary, done}
    [+ origin when color_by="origin"]) → JSON Canvas dict.

    git-graph semantics: the commit column (log cards) runs newest-on-top
    at x=0 — ordered by (date, append position), so same-day logs keep
    their real chronological sequence — edges pointing in the direction
    of time (old → new). The entry card is the HEAD pointer: it sits
    beside the newest distilled (📗) log and points at it laterally, so
    the nodes above the entry are exactly the un-distilled (📎) backlog.
    Nothing distilled yet → the entry sinks below the column (HEAD has
    merged nothing); no logs at all → the entry stands alone at (0,0).
    vault_file_of(card_id) -> vault-relative .md path or None."""
    nodes, edges = [], []

    # true chronological order: timeline lines are APPENDED in time order,
    # so an entry's position in the scan (chain walk) is its timestamp —
    # date alone can't order same-day logs (the old log-uuid tiebreak was
    # effectively random). seq defaults to input position so callers passing
    # plain scan order (done_logs + pending_logs) are already correct.
    entries = [dict(e, seq=e.get("seq", i)) for i, e in enumerate(entries)]
    ordered = sorted(entries,
                     key=lambda e: (e.get("date") or "", e["seq"]),
                     reverse=True)                      # newest on top

    # HEAD anchor: the newest distilled log's row (vertically centered on
    # it); sunk one row below the column when nothing is distilled yet.
    head_row = next((i for i, e in enumerate(ordered) if e.get("done")),
                    None)
    if not ordered:
        entry_x = entry_y = 0
    else:
        entry_x = NODE_W + 80
        entry_y = (len(ordered) * (NODE_H + GAP) if head_row is None
                   else head_row * (NODE_H + GAP) + (NODE_H - ENTRY_H) // 2)

    entry_file = vault_file_of(entry_id)
    entry_node = {"id": _nid(entry_id), "x": entry_x, "y": entry_y,
                  "width": NODE_W, "height": ENTRY_H, "color": COLOR_ENTRY}
    if entry_file:
        entry_node.update({"type": "file", "file": entry_file})
    else:
        entry_node.update({"type": "text",
                           "text": f"# {entry_title}\n（entry 卡未鏡像）"})
    nodes.append(entry_node)

    # continuation children: a gray row riding beside the entry (they are
    # pages of the README, not commits — they travel with HEAD)
    for i, cid in enumerate(c for c in chain_ids if c != entry_id):
        f = vault_file_of(cid)
        n = {"id": _nid(cid, "chain"),
             "x": entry_x + NODE_W + 30 + i * (CHILD_W + 30),
             "y": entry_y, "width": CHILD_W, "height": CHILD_H}
        if f:
            n.update({"type": "file", "file": f})
        else:
            n.update({"type": "text", "text": f"續卡 {cid[:8]}（未鏡像）"})
        nodes.append(n)

    prev_node_id = None
    for i, e in enumerate(ordered):
        y = i * (NODE_H + GAP)
        f = vault_file_of(e["log"])
        if color_by == "origin":
            color = origin_color(e.get("origin"))       # None → gray
        else:
            color = COLOR_DONE if e.get("done") else COLOR_PENDING
        n = {"id": _nid(e["log"]), "x": 0, "y": y,
             "width": NODE_W, "height": NODE_H}
        if color:
            n["color"] = color
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
        if prev_node_id:
            edges.append({"id": _nid(e["log"], "edge"),
                          "fromNode": n["id"], "fromSide": "top",
                          "toNode": prev_node_id, "toSide": "bottom"})
        prev_node_id = n["id"]
        if i == head_row:                    # HEAD → its distilled tip
            edges.append({"id": _nid(entry_id, "head"),
                          "fromNode": _nid(entry_id), "fromSide": "left",
                          "toNode": n["id"], "toSide": "right"})
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


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*\n?", re.S)


def _strip_frontmatter(md):
    """Drop a leading YAML frontmatter block — it would eat the origin
    scan budget before the report header is even reached."""
    return _FRONTMATTER_RE.sub("", md or "")


def head_text(cid, cfg, vault_file_of):
    """Opening text of a card for origin sniffing — the mirrored vault file
    when available (local, no CLI round-trip); a mirror that turns out
    unreadable/empty falls THROUGH to a CLI read (pure-local backend has
    no CLI to fall back to). Best-effort: nothing readable → "" (origin
    None → gray)."""
    budget = ORIGIN_SCAN_CHARS * 2
    try:
        rel = vault_file_of(cid)
    except Exception:                                        # noqa: BLE001
        rel = None
    if rel:
        try:
            if cfg.get("backend") == "obsidian":
                import backend
                md = backend.get_backend(cfg).read_card(cid).md or ""
            else:
                p = os.path.join(cfg["obsidian"]["vault"], rel)
                md = open(p, encoding="utf-8").read(budget * 4)
            md = _strip_frontmatter(md)
            if md.strip():
                return md[:budget]
        except Exception:                                    # noqa: BLE001
            pass                    # mirror unreadable → try the CLI below
    if cfg.get("backend") == "obsidian":
        return ""
    try:
        import merge_lib as M
        _, doc = M.L.read_card(cid)
        return "\n".join(M.L._txt(n)
                         for n in doc.get("content", [])[:10])[:budget]
    except Exception:                                        # noqa: BLE001
        return ""


def scan_entries(s):
    """scan() buckets loglinks by a done flag that scan_loglinks_ordered
    yields OUT-OF-BAND — the entry dicts themselves never carry it. Put it
    back when concatenating: the HEAD anchor, state colors, and the 📎/📗
    mark on unmirrored text nodes all read e["done"]. (Before 0.51 the
    canvas concatenated the bare buckets — state mode silently colored
    every log as pending.)"""
    return ([dict(e, done=True) for e in s["done_logs"]]
            + [dict(e, done=False) for e in s["pending_logs"]])


def resolve_color_by(cfg, cli_value=None):
    """CLI flag > config projects.canvas_color_by > "origin". Placeholder
    ("<…>") and unknown values fall through to the default. (origin became
    the default in 0.51.0 — distillation state now reads off the topology:
    HEAD attaches to the newest distilled log, 📎 backlog stacks above.)"""
    v = cli_value or (((cfg.get("heptabase") or {}).get("collections") or {})
                      .get("projects") or {}).get("canvas_color_by")
    return v if v in ("state", "origin") else "origin"


def render(entry_id, dry=False, color_by="origin"):
    import merge_lib as M
    cfg = hbconfig.load_config()
    s = M.scan(entry_id)
    entries = scan_entries(s)
    title = next((h for h in s.get("headings", [])), "")
    # scan headings are H2s; get the real title from the entry read
    _, doc = M.L.read_card(entry_id)
    title = next((M.L._txt(n).strip() for n in doc["content"]
                  if n.get("type") == "heading"
                  and (n.get("attrs") or {}).get("level") == 1), entry_id[:8])
    mapper = vault_mapper(cfg)
    origins = None
    if color_by == "origin":
        for e in entries:
            e["origin"] = log_origin(head_text(e["log"], cfg, mapper))
        origins = {k: sum(1 for e in entries if e.get("origin") == k)
                   for k in ("mac", "cluster", None)}
        origins = {("unknown" if k is None else k): v
                   for k, v in origins.items() if v}
    canvas = build_canvas(entry_id, title, s["chain"], entries, mapper,
                          color_by=color_by)
    folders = cfg["obsidian"].get("folders") or {}
    # canvases live in their own subfolder (they're generated views, not
    # cards) — default <projects folder>/Canvas, overridable via
    # local.folders.project_canvas
    canvas_folder = folders.get("project_canvas") or os.path.join(
        folders.get("projects", "Projects"), "Canvas")
    out_dir = os.path.join(cfg["obsidian"]["vault"], canvas_folder)
    path = os.path.join(out_dir, f"{safe_filename(title)}.canvas")
    rep = {"entry": entry_id, "title": title, "canvas": path,
           "nodes": len(canvas["nodes"]), "edges": len(canvas["edges"]),
           "pending": len(s["pending_logs"]), "done": len(s["done_logs"]),
           "color_by": color_by}
    if origins is not None:
        rep["origins"] = origins
    if dry:
        rep["dry_run"] = True
        return rep
    os.makedirs(out_dir, exist_ok=True)
    json.dump(canvas, open(path, "w"), ensure_ascii=False, indent=1)
    return rep


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
    ap.add_argument("--color-by", choices=("state", "origin"),
                    help="log-card color axis: origin（Mac=cyan／cluster="
                         "yellow，預設——蒸餾狀態改由拓撲表達：HEAD 側貼"
                         "最新 📗）or state（📎橙/📗綠，舊軸）; default "
                         "from config projects.canvas_color_by")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.card and not args.all:
        ap.error("give --card <ENTRY_ID> or --all")
    cfg = hbconfig.load_config()
    if cfg.get("backend") not in ("both", "obsidian"):
        sys.exit("project canvas 需要 local 資料底座（backends 含 local）"
                 "——canvas 檔住在 vault 裡")
    color_by = resolve_color_by(cfg, args.color_by)
    targets = [args.card] if args.card else all_entries(cfg)
    out = [render(cid, dry=args.dry_run, color_by=color_by)
           for cid in targets]
    print(json.dumps(out if args.all else out[0], ensure_ascii=False,
                     indent=1))


if __name__ == "__main__":
    main()
