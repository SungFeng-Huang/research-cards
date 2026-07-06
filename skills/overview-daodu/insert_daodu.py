#!/usr/bin/env python3
"""Insert or refresh a teaching 導讀 at the top of a Heptabase overview card.

The 導讀 *prose* is written by the model (grounded in the card); this script only
does the mechanical part: read the card, back it up, convert the 導讀 markdown to
Heptabase doc nodes, insert it just before the first level-2 heading — or, if a
導讀 section already exists, replace it in place (idempotent) — and save.

Usage:
    python3 insert_daodu.py --card <CARD_ID> --md-file <PATH>
    python3 insert_daodu.py --card <CARD_ID>            # reads 導讀 markdown from stdin
    python3 insert_daodu.py --card <CARD_ID> --dry-run  # show plan, don't save

Markdown subset understood: `##`/`###`/`####` headings, `---` horizontal rule,
blank-line-separated paragraphs, and `**bold**` inline. The 導讀 markdown should
start with its own `## 導讀…` heading (that heading is how re-runs find and
replace it) and normally end with a `---` separator.

Requires the `heptabase` CLI (Mac, local Heptabase). No third-party deps.
"""
import argparse, json, os, re, subprocess, sys, tempfile, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "_shared"))
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None


def read_card(card_id):
    if OBS:
        return OBS.read_doc(card_id)
    r = subprocess.run(["heptabase", "note", "read", card_id],
                       capture_output=True, text=True, check=True)
    data = json.loads(r.stdout)
    return data["contentMd5"], json.loads(data["content"])


def save_card(card_id, md5, doc):
    if OBS:
        return OBS.save_doc(card_id, md5, doc)
    s = json.dumps(doc, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        f.write(s); tmp = f.name
    try:
        subprocess.run(["heptabase", "note", "save", card_id,
                        "--content-md5", md5, "--content-file", tmp],
                       check=True, capture_output=True)
    finally:
        os.unlink(tmp)


def node_text(n):
    if n.get("type") == "text":
        return n.get("text", "")
    return "".join(node_text(c) for c in n.get("content", []) if isinstance(c, dict))


# ── markdown → Heptabase doc nodes ──────────────────────────────────────────────
def inline(text):
    """Split on **bold**; alternate segments get a strong mark. Unbalanced ** →
    treat the whole string as plain text (never corrupt the doc)."""
    parts = text.split("**")
    if len(parts) % 2 == 0:          # odd number of "**" → unbalanced
        parts = [text]
    nodes = []
    for i, seg in enumerate(parts):
        if seg == "":
            continue
        node = {"type": "text", "text": seg}
        if i % 2 == 1:
            node["marks"] = [{"type": "strong"}]
        nodes.append(node)
    return nodes or [{"type": "text", "text": ""}]


def md_to_nodes(md):
    nodes = []
    for block in re.split(r"\n\s*\n", md.strip()):
        block = block.strip()
        if not block:
            continue
        if re.fullmatch(r"-{3,}", block):
            nodes.append({"type": "horizontal_rule", "attrs": {"id": None}})
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", block)
        if m:
            level = len(m.group(1))
            nodes.append({"type": "heading", "attrs": {"id": None, "level": level},
                          "content": inline(m.group(2).strip())})
            continue
        text = " ".join(line.strip() for line in block.splitlines())
        nodes.append({"type": "paragraph", "attrs": {"id": None},
                      "content": inline(text)})
    return nodes


def is_heading(n, level=None):
    if n.get("type") != "heading":
        return False
    return level is None or n.get("attrs", {}).get("level") == level


def daodu_bounds(content):
    """Return (start, end) slice to replace for an existing 導讀 section, or None.
    The section runs from the 導讀 heading up to the next heading of level <= it."""
    for i, n in enumerate(content):
        if is_heading(n) and node_text(n).strip().startswith("導讀"):
            lvl = n["attrs"]["level"]
            j = i + 1
            while j < len(content):
                if is_heading(content[j]) and content[j]["attrs"]["level"] <= lvl:
                    break
                j += 1
            return (i, j)
    return None


def first_h2(content):
    for i, n in enumerate(content):
        if is_heading(n, 2):
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True, help="Heptabase card id")
    ap.add_argument("--md-file", help="path to 導讀 markdown (default: stdin)")
    ap.add_argument("--restore", help="restore the card from a backup JSON written by a prior run")
    ap.add_argument("--backup-dir", default=os.path.expanduser("~/.cache/overview-daodu"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Restore mode: reinstate a backed-up doc, using the CURRENT md5 (Heptabase
    # save is optimistic-concurrency: the stale md5 in the backup won't work).
    if args.restore:
        with open(args.restore, encoding="utf-8") as f:
            backup = json.load(f)
        doc = backup["content"] if isinstance(backup, dict) and "content" in backup else backup
        cur_md5, _ = read_card(args.card)
        if args.dry_run:
            print(f"DRY-RUN: would restore card {args.card} from {args.restore}")
            return 0
        save_card(args.card, cur_md5, doc)
        print(f"OK: restored card {args.card} from {args.restore}")
        return 0

    md = open(args.md_file, encoding="utf-8").read() if args.md_file else sys.stdin.read()
    if not md.strip():
        print("ERROR: empty 導讀 markdown", file=sys.stderr); return 2
    nodes = md_to_nodes(md)
    # Must be an H2 heading: daodu_bounds() uses the heading's level to find the
    # replace range, so an H1 導讀 would swallow every following section on re-run.
    if not (is_heading(nodes[0], 2) and node_text(nodes[0]).strip().startswith("導讀")):
        print("ERROR: 導讀 markdown must start with a level-2 '## 導讀…' heading", file=sys.stderr)
        return 2

    md5, doc = read_card(args.card)
    content = doc["content"]

    bounds = daodu_bounds(content)
    if bounds:
        start, end = bounds
        action = f"REPLACE existing 導讀 (nodes {start}..{end})"
        new_content = content[:start] + nodes + content[end:]
    else:
        idx = first_h2(content)
        if idx is None:
            print("ERROR: no level-2 heading found to anchor before; aborting",
                  file=sys.stderr)
            return 3
        action = f"INSERT before first H2 (node {idx}: '{node_text(content[idx]).strip()}')"
        new_content = content[:idx] + nodes + content[idx:]

    print(f"{action}; 導讀 = {len(nodes)} nodes")
    if args.dry_run:
        print("DRY-RUN: not saving.")
        return 0

    os.makedirs(args.backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    backup = os.path.join(args.backup_dir, f"{args.card.replace(chr(47), chr(95)*2)}.{ts}.json")
    with open(backup, "w", encoding="utf-8") as f:
        json.dump({"contentMd5": md5, "content": doc}, f, ensure_ascii=False, indent=2)

    doc["content"] = new_content
    save_card(args.card, md5, doc)
    print(f"OK: saved. Backup: {backup}")
    return 0


if __name__ == "__main__":
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    sys.exit(main())
