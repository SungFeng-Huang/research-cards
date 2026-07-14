#!/usr/bin/env python3
"""Heptabase -> Obsidian Level-1 sync (research-cards plugin, obsidian-sync skill).

- Body: one-way Heptabase -> Obsidian (Heptabase is source of truth).
- Properties: bidirectional 3-way sync (Status/Tasks/Topics/Note/...); conflicts
  are reported, never auto-merged.
- Card links: targets synced to the vault become [[wikilinks]]; other targets
  keep a Heptabase app URL; self-anchors degrade to plain text.
- Local images are exported to <folder>/attachments/.
- Highlight embeds are resolved from highlights.json (agent-maintained; new
  ones are reported for the agent to fetch via MCP and add).

Usage: python3 sync.py [--dry-run] [--bootstrap-report-only]
State: <vault>/.hepta-sync/state.json
"""
import argparse, copy, datetime, difflib, hashlib, json, os, re, subprocess, sys, tempfile

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "_shared"))
import md2pm
import hbconfig
from pmmd import Converter, assemble, split_blocks, safe_filename, norm_md

SKILL_DIR = os.path.dirname(os.path.realpath(__file__))
_cfg = hbconfig.load_config()
if _cfg["backend"] != "both":
    sys.exit("obsidian-sync 只在 backend='both' 模式下有意義"
             f"（目前 config 是 {_cfg['backend']!r}）。單一 backend 不需要同步。")
VAULT = _cfg["obsidian"]["vault"]
WORKSPACE = _cfg["heptabase"]["workspace_id"]
# A collection syncs only when its tag_id is filled in — entries without one
# (or with a <placeholder>) are metadata for other skills (e.g. projects'
# hub_card for project-card-merge) and must not crash the sync.
COLLECTIONS = [
    {"key": key,
     "tag_id": col["tag_id"],
     "tag_name": col.get("tag_name"),
     "folder": _cfg["obsidian"]["folders"].get(key, key.capitalize()),
     "filter": col.get("filter"),
     "new_card_props": col.get("new_card_props") or {}}
    for key, col in _cfg["heptabase"]["collections"].items()
    if isinstance(col.get("tag_id"), str) and col["tag_id"]
    and not col["tag_id"].startswith("<")]
STATE_PATH = os.path.join(VAULT, ".hepta-sync", "state.json")
CACHE_DIR = os.path.join(VAULT, ".hepta-sync", "pm-cache")
CONFLICT_NOTE = os.path.join(VAULT, "Sync Conflicts.md")
# highlight-embed contents are USER data (personal note excerpts)
HIGHLIGHTS_PATH = os.path.join(hbconfig.user_data_dir(), "highlights.json")






def body_hash(body):
    return hashlib.sha1(body.encode()).hexdigest()

FM_ORDER = ["title", "arxiv_id", "tasks", "topics", "status", "note",
            "source_type", "level"]
SYSTEM_KEYS = ["heptabase_id", "created", "modified"]

REBUILD = False
report = {"created": [], "body_updated": [], "fm_updated": [], "renamed": [],
          "journals": [],
          "prop_writeback": [], "conflicts": [], "removed_from_tag": [],
          "missing_files_recreated": [], "unknown_nodes": {},
          "unresolved_highlights": [], "bootstrap_fm_diffs": [],
          "writeback_errors": [], "errors": []}


def cli(*args, timeout=120):
    r = subprocess.run(["heptabase", *args], capture_output=True, text=True,
                       timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"heptabase {' '.join(args[:3])}: {r.stderr[:300]}")
    return json.loads(r.stdout)





# ------------------------------------------------------------- link resolve
class LinkResolver:
    def __init__(self, state, in_set, tag_titles=None):
        self.state = state
        self.in_set = in_set          # cardId -> filename (no .md)
        self.tag_titles = tag_titles or {}  # all tag cards incl. non-synced
        self.titles = state.setdefault("titles", {})
        self.highlights = (json.load(open(HIGHLIGHTS_PATH))
                           if os.path.exists(HIGHLIGHTS_PATH) else {})
        self._wb_names = None

    def title_of(self, tid, kind="card"):
        if tid in self.tag_titles:
            return self.tag_titles[tid]
        if tid in self.titles:
            return self.titles[tid]
        title = None
        if kind == "chat":
            return "Heptabase chat"
        if kind == "whiteboard":
            if self._wb_names is None:
                try:
                    self._wb_names = {w["id"]: w.get("name") or "whiteboard"
                                      for w in cli("whiteboard", "list")["whiteboards"]}
                except Exception:
                    self._wb_names = {}
            title = self._wb_names.get(tid, "Heptabase whiteboard")
        elif kind == "section":
            title = "Heptabase section"
        else:
            try:
                title = cli("note", "read", tid).get("title")
            except Exception:
                title = None
        title = title or "Heptabase card"
        self.titles[tid] = title
        return title

    def url(self, tid, kind="card"):
        seg = "whiteboard" if kind == "whiteboard" else "card"
        return f"https://app.heptabase.com/{WORKSPACE}/{seg}/{tid}"

    def resolve(self, text, self_id, fileid_to_name, valid_anchors=None):
        valid_anchors = valid_anchors or set()
        # link marks baked as markdown URLs
        link_re = re.compile(
            r"\[([^\]]*)\]\(https://app\.heptabase\.com/" + WORKSPACE +
            r"/card/([0-9a-f-]{36})(#[0-9a-f-]+)?\)")

        def repl_link(m):
            label, tid, anchor = m.group(1), m.group(2), m.group(3)
            if tid == self_id:
                if anchor and anchor[1:] in valid_anchors:
                    # same-card block anchor -> Obsidian block reference
                    bold = label.startswith("**") and label.endswith("**")
                    core = label[2:-2] if bold else label
                    link = f"[[#^{anchor[1:][:8]}|{core}]]"
                    return f"**{link}**" if bold else link
                return label  # anchor target gone (dangling) -> plain text
            if tid in self.in_set:
                target = self.in_set[tid]
                return (f"[[{target}]]" if label.strip("*") == target
                        else f"[[{target}|{label}]]")
            return f"[{label}]({self.url(tid)})"

        def repl_mention(m):
            kind, tid = m.group(1).lower(), m.group(2)
            if tid in self.in_set:
                return f"[[{self.in_set[tid]}]]"
            return f"[{self.title_of(tid, kind)}]({self.url(tid, kind)})"

        def repl_embed(m):
            hid = m.group(1)
            h = self.highlights.get(hid)
            if not h:
                report["unresolved_highlights"].append({"card": self_id, "highlight": hid})
                return f"> [Heptabase highlight 尚未解析: {hid}]"
            lines = [f"> {ln}" for ln in h.get("highlight", "").split("\n") if ln]
            if h.get("note"):
                lines.append(f"> — *{h['note']}*")
            return "\n".join(lines) + "\n"

        def repl_localfile(m):
            name = fileid_to_name.get(m.group(1))
            return f"![[{name}]]" if name else ""

        text = link_re.sub(repl_link, text)
        text = re.sub(r"%%HEPTA-(CARD|WHITEBOARD|SECTION|PDF_CARD|CHAT):([0-9a-f-]{36})%%",
                      repl_mention, text)
        text = re.sub(r"%%HEPTA-EMBED:([0-9a-f-]{36})%%", repl_embed, text)
        text = re.sub(r"%%HEPTA-LOCALFILE:([0-9a-f-]{36})%%", repl_localfile, text)
        return text


# ------------------------------------------------------------- frontmatter
def fm_key(prop_name):
    return re.sub(r"[ /]+", "_", prop_name.strip().lower())


def parse_file(path):
    text = open(path).read()
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[m.end():].lstrip("\n")


def dump_fm(fm):
    keys = [k for k in FM_ORDER if k in fm]
    keys += [k for k in fm if k not in FM_ORDER and k not in SYSTEM_KEYS]
    keys += [k for k in SYSTEM_KEYS if k in fm]
    lines = ["---"]
    for k in keys:
        v = fm[k]
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines += [f"  - {json.dumps(x, ensure_ascii=False)}" for x in v]
        else:
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def norm(v, multi):
    if multi:
        if v is None:
            return frozenset()
        if isinstance(v, (list, tuple)):
            return frozenset(str(x) for x in v)
        return frozenset([str(v)])
    if isinstance(v, list):
        v = v[0] if len(v) == 1 else json.dumps(v, ensure_ascii=False)
    return None if v in (None, "") else str(v)


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rebuild-cache", action="store_true",
                    help="re-read every card and rebuild the PM block cache")
    args = ap.parse_args()
    dry = args.dry_run
    global REBUILD
    REBUILD = args.rebuild_cache

    if not os.path.isdir(VAULT):
        sys.exit(f"vault not accessible: {VAULT}")

    state = {"cards": {}, "files": {}, "titles": {}}
    if os.path.exists(STATE_PATH):
        state = json.load(open(STATE_PATH))
    bootstrap = not state["cards"]

    # property schemas (also needed by adoption below)
    tag_props = {}   # key -> {fm_key: {id, name, type}}
    for col in COLLECTIONS:
        props = cli("tag", "properties", col["tag_id"])["properties"]
        tag_props[col["key"]] = {fm_key(p["name"]): p for p in props
                                 if p["type"] != "relation"}

    # Level-3 adoption BEFORE fetching, so new cards join this run normally
    state_in_set = {cid: st["file"] for cid, st in state["cards"].items()}
    for col in COLLECTIONS:
        try:
            adopt_new_files(col, col["folder"], tag_props[col["key"]],
                            state, state_in_set, dry)
        except Exception as e:
            report["errors"].append({"card": f"adopt:{col['key']}",
                                     "err": repr(e)[:300]})

    # fetch collections
    col_cards = {}   # key -> [card]
    tag_titles = {}  # every card in both tags (even non-synced), for link text
    for col in COLLECTIONS:
        data = cli("tag", "cards", col["tag_id"], "--include-properties")
        cards = data["cards"]
        tag_titles.update({c["id"]: c["title"] for c in cards})
        if col["filter"]:
            (pname, pval), = col["filter"].items()
            cards = [c for c in cards
                     if any(p["name"] == pname and p.get("value") == pval
                            for p in c.get("properties") or [])]
        col_cards[col["key"]] = cards

    # adopt existing files on bootstrap (match by heptabase_id)
    existing_by_id = {}
    for col in COLLECTIONS:
        folder = os.path.join(VAULT, col["folder"])
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if fn.endswith(".md"):
                fm, _ = parse_file(os.path.join(folder, fn))
                if fm.get("heptabase_id"):
                    existing_by_id[fm["heptabase_id"]] = (col["key"], fn[:-3])

    # build in-set filename map (stable names from state, then existing, then new)
    in_set, used = {}, {}
    for col in COLLECTIONS:
        used[col["key"]] = set()
        for c in col_cards[col["key"]]:
            st = state["cards"].get(c["id"])
            if st:
                in_set[c["id"]] = st["file"]
            elif c["id"] in existing_by_id:
                in_set[c["id"]] = existing_by_id[c["id"]][1]
            if c["id"] in in_set:
                used[col["key"]].add(in_set[c["id"]])
    for col in COLLECTIONS:
        for c in col_cards[col["key"]]:
            if c["id"] in in_set:
                continue
            base = safe_filename(c["title"])
            name, i = base, 1
            while name in used[col["key"]]:
                i += 1
                name = f"{base} ({i})"
            used[col["key"]].add(name)
            in_set[c["id"]] = name

    resolver = LinkResolver(state, in_set, tag_titles)

    for col in COLLECTIONS:
        folder = os.path.join(VAULT, col["folder"])
        att_dir = os.path.join(folder, "attachments")
        os.makedirs(att_dir, exist_ok=True)
        props_by_key = tag_props[col["key"]]

        for c in col_cards[col["key"]]:
            cid = c["id"]
            try:
                sync_card(c, col, folder, att_dir, props_by_key, state,
                          resolver, in_set, bootstrap, dry)
            except Exception as e:
                report["errors"].append({"card": cid, "err": repr(e)[:300]})

        # cards gone from tag
        for cid, st in list(state["cards"].items()):
            if st.get("collection") == col["key"] and \
               cid not in {c["id"] for c in col_cards[col["key"]]}:
                report["removed_from_tag"].append({"card": cid, "file": st["file"]})

    try:
        sync_journals(state, resolver, dry)
    except Exception as e:
        report["errors"].append({"card": "journal", "err": repr(e)[:300]})

    if not dry:
        update_conflict_log(state)
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        json.dump(state, open(STATE_PATH, "w"), ensure_ascii=False, indent=1)

    print(json.dumps({k: v for k, v in report.items() if v},
                     ensure_ascii=False, indent=1))


def hepta_props_fm(card, props_by_key):
    """Heptabase property values -> frontmatter dict (only known non-relation)."""
    out = {}
    vals = {p["name"]: p.get("value") for p in card.get("properties") or []}
    for key, pdef in props_by_key.items():
        v = vals.get(pdef["name"])
        if v in (None, "", []):
            continue
        out[key] = v
    return out


def cache_path(cid):
    return os.path.join(CACHE_DIR, cid + ".json")


def update_conflict_log(state):
    """Maintain the "Sync Conflicts" note in the vault root.

    Live conflicts re-report on every run until resolved (their state stays
    frozen), so: in this run's report = unresolved; previously logged but
    absent now = resolved. The note is regenerated from state each run.
    """
    today = datetime.date.today().isoformat()
    log = state.setdefault("conflict_log", {})

    def ckey(c):
        raw = json.dumps([c.get("file"), c.get("prop"),
                          c.get("reason") or c.get("hint") or "",
                          (c.get("block") or "")[:80]], ensure_ascii=False)
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    live = {ckey(c): c for c in report["conflicts"]}
    for k, c in live.items():
        if k not in log or log[k].get("resolved"):
            log[k] = {"first": today, "resolved": None, "entry": c}
    window = set(state.get("journal_window") or [])
    for k, rec in log.items():
        if not rec.get("resolved") and k not in live:
            entry = rec.get("entry") or {}
            if str(entry.get("card", "")).startswith("journal:") and \
               entry.get("file") not in window:
                continue  # journal day out of the rolling window: unverified
            rec["resolved"] = today

    def fmt(rec, done):
        c = rec["entry"]
        box = "x" if done else " "
        reason = (c.get("reason") or c.get("hint")
                  or f"Heptabase={json.dumps(c.get('heptabase'), ensure_ascii=False)}"
                     f" / Obsidian={json.dumps(c.get('obsidian'), ensure_ascii=False)}")
        when = rec["first"] + (f" → {rec['resolved']} 解決" if done else "")
        lines = [f"- [{box}] {when} [[{c['file']}]] — `{c.get('prop', '')}` {reason}"]
        if c.get("block"):
            lines.append(f"    - 區塊：`{c['block'][:80].replace(chr(10), ' ')}`")
        return lines

    unresolved = sorted((r for r in log.values() if not r["resolved"]),
                        key=lambda r: r["first"], reverse=True)
    resolved = sorted((r for r in log.values() if r["resolved"]),
                      key=lambda r: r["resolved"], reverse=True)
    out = ["---", 'tags: [sync-conflicts]', "---", "",
           "Heptabase ↔ Obsidian 同步衝突紀錄（obsidian-sync 自動維護，手動編輯會被覆蓋）。",
           "",
           "解法二選一：到 **Heptabase** 改該區塊（下次 sync 前向覆蓋 Obsidian），"
           "或把 **Obsidian** 檔案的該區塊改回與 Heptabase 一致。改完重跑 sync 即自動歸檔。",
           "", f"## 未解決（{len(unresolved)}）", ""]
    for r in unresolved:
        out += fmt(r, False)
    out += ["", f"## 已解決（{len(resolved)}）", ""]
    for r in resolved:
        out += fmt(r, True)
    with open(CONFLICT_NOTE, "w") as f:
        f.write("\n".join(out).rstrip() + "\n")




def render_forward(note, cid, card, resolver, state, att_dir, dry):
    """Heptabase note -> (body, md5); writes the per-block PM cache."""
    anchor_ids = {bid for bid in re.findall(
        r"card/" + re.escape(cid) + r"#([0-9a-f-]{36})", note["content"])
        if f'"id":"{bid}"' in note["content"]}  # drop dangling anchors
    conv = Converter({"id": cid, "title": note.get("title") or card["title"]},
                     anchor_ids)
    prefix, blocks = conv.convert_blocks(json.loads(note["content"]))
    report["unknown_nodes"].update(conv.unknown)
    fileid_to_name, _ = export_local_files(conv, att_dir, state, cid, dry)
    out_blocks = [(node, resolver.resolve(md, cid, fileid_to_name, anchor_ids))
                  for node, md in blocks]
    body = assemble(md for _, md in out_blocks)
    if not dry:
        os.makedirs(CACHE_DIR, exist_ok=True)
        json.dump({"contentMd5": note.get("contentMd5"),
                   "title": note.get("title") or card["title"],
                   "prefix": prefix, "anchorIds": sorted(anchor_ids),
                   "blocks": [{"node": n, "md": m} for n, m in out_blocks]},
                  open(cache_path(cid), "w"), ensure_ascii=False)
    return body, note.get("contentMd5")




def export_local_files(conv, att_dir, state, err_key, dry):
    """Export a Converter's referenced Heptabase files into att_dir once,
    remembering names in state["files"]. Shared by card body sync and the
    journal bridge. Returns (fileid_to_name, failed): callers that checkpoint
    on success must refuse to when failed > 0, or a missing mapping renders
    as a silently-empty embed forever. Under --dry-run nothing touches the
    vault (no mkdir / export / rename): unmapped ids stay unmapped."""
    fileid_to_name = {}
    failed = 0
    for fid in conv.local_files:
        if fid in state["files"]:
            fileid_to_name[fid] = state["files"][fid]
            continue
        if dry:
            continue
        try:
            os.makedirs(att_dir, exist_ok=True)
            info = cli("file", "export", fid, "--output-dir", att_dir)
            name = info["filename"]
            # Heptabase pasted images may have no real extension
            # (e.g. "Pasted ...09:54:04.653Z" -> ".653z"); Obsidian won't
            # render unknown extensions, so fix from mimeType.
            mime_ext = {"image/png": ".png", "image/jpeg": ".jpg",
                        "image/gif": ".gif", "image/webp": ".webp",
                        "image/svg+xml": ".svg"}.get(info.get("mimeType"))
            known = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                     ".bmp", ".pdf", ".mp4", ".mp3", ".m4a", ".wav"}
            if mime_ext and os.path.splitext(name)[1].lower() not in known:
                os.rename(os.path.join(att_dir, name),
                          os.path.join(att_dir, name + mime_ext))
                name += mime_ext
            fileid_to_name[fid] = name
            state["files"][fid] = name
        except Exception as e:
            failed += 1
            report["errors"].append({"card": err_key, "err": f"file export {fid}: {e}"})
    return fileid_to_name, failed


# ---- journal bridge: Heptabase journal -> Obsidian daily notes (one-way) ----
J_START = "<!-- hepta-journal:start -->"
J_END = "<!-- hepta-journal:end -->"


def _doc_is_empty(doc):
    """True when the PM doc carries no visible content (Heptabase returns a
    single empty paragraph for days with no journal)."""
    for node in doc.get("content") or []:
        if node.get("type") != "paragraph":
            return False
        if node.get("content"):
            return False
    return True


def render_journal(note, date, resolver, att_dir, state, dry):
    """Heptabase journal PM doc -> (markdown body, failed_exports). A non-zero
    failure count means the body has silently-empty embeds — the caller must
    NOT checkpoint that day (retry next run)."""
    conv = Converter({"id": f"journal-{date}", "title": note.get("title") or date},
                     set())
    _, blocks = conv.convert_blocks(json.loads(note["content"]))
    report["unknown_nodes"].update(conv.unknown)
    fileid_to_name, failed = export_local_files(conv, att_dir, state,
                                                f"journal:{date}", dry)
    body = assemble(resolver.resolve(md, f"journal-{date}", fileid_to_name, set())
                    for _, md in blocks)
    return body, failed


def _journal_run_digest(resolver):
    """Digest of the render inputs BEYOND the source doc — the synced-card
    set (wikilink targets), cached link titles, and highlights.json. Part of
    each day's skip key, so a card rename or a newly-resolved highlight
    re-renders journal days whose source md5 did not change. Computed once
    per run; titles cached during this run's own renders converge on the
    following run."""
    h = hashlib.sha1()
    h.update(json.dumps(sorted(getattr(resolver, "in_set", {}).items()),
                        ensure_ascii=False).encode())
    h.update(json.dumps(sorted(getattr(resolver, "titles", {}).items()),
                        ensure_ascii=False).encode())
    if os.path.exists(HIGHLIGHTS_PATH):
        h.update(open(HIGHLIGHTS_PATH, "rb").read())
    return h.hexdigest()[:16]


def _split_frontmatter(text):
    """(frontmatter_bytes, rest) — frontmatter kept byte-exact, empty when
    the file does not start with a YAML properties block."""
    m = re.match(r"^---\n.*?\n---\n?", text, re.S)
    return (text[:m.end()], text[m.end():]) if m else ("", text)


def _marker_lines(text):
    """Line indices where a marker is a STANDALONE line (whitespace-trimmed
    exact match). Inline occurrences (`prefix <marker> suffix`) are counted
    separately so callers can treat them as corruption, not as a valid pair."""
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines) if l.strip() == J_START]
    ends = [i for i, l in enumerate(lines) if l.strip() == J_END]
    inline = (text.count(J_START) > len(starts)) or (text.count(J_END) > len(ends))
    return lines, starts, ends, inline


def _markers_intact(text):
    _, starts, ends, inline = _marker_lines(text)
    return len(starts) == 1 and len(ends) == 1 and starts[0] < ends[0] and not inline


def _atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=".hepta-journal-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_managed_block(path, body, dry, claim_ok=True):
    """Write `body` into the managed marker block of a daily note, preserving
    every byte outside the markers (the user's own notes). Returns the action
    taken: created / updated / unchanged / conflict.

    Guarantees (review 41068ad follow-ups): exactly ONE standalone marker
    pair is required — duplicates, reordering, or a marker literal inside the
    rendered body are conflicts, never guesses. A markerless file is claimed
    only when `claim_ok` (i.e. this day was never managed before), inserting
    AFTER any YAML frontmatter so Obsidian keeps recognising Properties, and
    without stripping the user's leading blank lines. Writes go through a
    tempfile + os.replace with an optimistic recheck, so an Obsidian/iCloud
    save racing the sync surfaces as a conflict instead of being clobbered."""
    if J_START in body or J_END in body:
        return "conflict"  # rendered body must never smuggle marker literals
    block = J_START + "\n" + (body.rstrip() + "\n" if body.strip() else "") + J_END
    if not os.path.exists(path):
        if dry:
            return "created"
        try:
            # O_EXCL closes the exists()->write race: a note Obsidian creates
            # in between surfaces as a conflict instead of being clobbered.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return "conflict"
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(block + "\n")
        return "created"
    st0 = os.stat(path)
    text = open(path, encoding="utf-8").read()
    lines, starts, ends, inline = _marker_lines(text)
    if inline:
        return "conflict"  # marker text embedded inside a line — never guess
    if (len(starts), len(ends)) == (0, 0):
        if not claim_ok:
            # we managed this note before and the markers are gone — the user
            # removed them; re-claiming would duplicate old content as stale
            # text outside a fresh block. Report, never guess.
            return "conflict"
        fm, rest = _split_frontmatter(text)
        new_text = fm + block + "\n\n" + rest
    elif (len(starts), len(ends)) != (1, 1) or starts[0] > ends[0]:
        return "conflict"  # half-deleted / duplicated / reordered markers
    else:
        pre = "\n".join(lines[:starts[0]])
        post = "\n".join(lines[ends[0] + 1:])
        new_text = (pre + ("\n" if pre else "")) + block + ("\n" + post if post else "")
    if new_text == text:
        return "unchanged"
    if not dry:
        # Best-effort race guard: recheck as late as possible before the
        # atomic replace. A save landing inside the remaining microseconds
        # can still lose (no file locking on iCloud vaults) — the recheck
        # narrows the window, it cannot close it.
        st1 = os.stat(path)
        if (st1.st_mtime_ns, st1.st_size) != (st0.st_mtime_ns, st0.st_size):
            return "conflict"  # note changed under us — retry next run
        _atomic_write(path, new_text)
    return "updated"


def sync_journals(state, resolver, dry):
    """One-way journal leg: mirror the last N days of the Heptabase journal
    into the managed block of daily notes. Config
    obsidian.journal.{enabled, days, folder} — `folder` is the vault-relative
    daily-note directory (empty/absent = vault root, backward compatible;
    values escaping the vault are rejected); incremental via per-day
    contentMd5.
    The user's content OUTSIDE the markers is never touched; edits INSIDE
    the markers are overwritten on the next source change (documented
    one-way semantics). Reverse flow (daily note -> Heptabase) is a
    deliberate non-goal of v1."""
    jcfg = _cfg["obsidian"].get("journal") or {}
    days = int(jcfg.get("days", 30))  # an explicit 0 means OFF, not 30
    if not jcfg.get("enabled") or days <= 0:
        # A disabled leg must not leave last run's window in state: days that
        # were in-window then would look in-window-but-unreported now, and
        # update_conflict_log() would wrongly mark their conflicts resolved.
        state["journal_window"] = []
        return
    jstate = state.setdefault("journals", {})
    jdir = hbconfig.journal_dir(_cfg)
    if not dry:
        os.makedirs(jdir, exist_ok=True)
    att_dir = os.path.join(VAULT, "attachments")
    run_digest = _journal_run_digest(resolver)
    today = datetime.date.today()
    window = []
    for i in range(days):
        date = (today - datetime.timedelta(days=i)).isoformat()
        window.append(date)
        try:
            note = cli("journal", "read", date)
            md5 = note.get("contentMd5")
            path = os.path.join(jdir, f"{date}.md")
            prev = jstate.get(date) or {}
            managed = bool(prev.get("managed"))
            if (not REBUILD and prev.get("md5") == md5
                    and prev.get("rd") == run_digest):
                # source + render inputs unchanged; still verify the target —
                # the fast path must not paper over deleted/duplicated markers
                if managed:
                    if os.path.exists(path) and \
                       _markers_intact(open(path, encoding="utf-8").read()):
                        continue
                elif not managed and (not os.path.exists(path)
                                      or prev.get("skipped")):
                    continue
            empty = _doc_is_empty(json.loads(note["content"]))
            checkpoint = {"md5": md5, "rd": run_digest, "managed": managed}
            if empty and not os.path.exists(path):
                # nothing to say and no note to claim: don't create empty files
                checkpoint["managed"] = False
            elif empty and not managed and \
                    J_START not in open(path, encoding="utf-8").read():
                # an empty source day must not claim a pre-existing note the
                # bridge never managed (review P1-1)
                checkpoint["managed"] = False
                checkpoint["skipped"] = True
            else:
                body, failed = ("", 0) if empty else render_journal(
                    note, date, resolver, att_dir, state, dry)
                if failed:
                    # do NOT checkpoint: the day retries next run (review P1-3)
                    continue
                action = write_managed_block(path, body, dry,
                                             claim_ok=not managed)
                if action == "conflict":
                    report["conflicts"].append(
                        {"card": f"journal:{date}", "file": date,
                         "reason": "managed markers malformed/removed, or "
                                   "the note changed during the write"})
                    continue
                if action != "unchanged":
                    report["journals"].append({"date": date, "action": action})
                checkpoint["managed"] = True
            if not dry:
                jstate[date] = checkpoint
        except Exception as e:
            # single-day isolation: one bad day never aborts the window
            report["errors"].append({"card": f"journal:{date}",
                                     "err": repr(e)[:200]})
            continue
    if not dry:
        state["journal_window"] = window


def adopt_new_files(col, folder, props_by_key, state, in_set, dry):
    """Level-3 adoption: an untracked .md (no heptabase_id) in a managed
    folder becomes a real Heptabase card — note create + full-doc save,
    tag add, properties from frontmatter — and joins the sync state.
    Unparseable dialect -> conflict, file untouched."""
    fdir = os.path.join(VAULT, col["folder"])
    if not os.path.isdir(fdir):
        return
    tracked = {st["file"] for st in state["cards"].values()
               if st.get("collection") == col["key"]}
    name_to_uuid = {v: k for k, v in in_set.items()}
    for fn in sorted(os.listdir(fdir)):
        if not fn.endswith(".md") or fn[:-3] in tracked:
            continue
        fname = fn[:-3]
        path = os.path.join(fdir, fn)
        fm, body = parse_file(path)
        if fm.get("heptabase_id"):
            continue  # tracked by another collection pass / manual
        title = fm.get("title") or fname
        try:
            parser = md2pm.BlockParser({
                "self_id": "", "workspace": WORKSPACE,
                "name_to_card": name_to_uuid,
                "attach_to_fileid": {v: k for k, v in state.get("files", {}).items()},
                "anchor_short_to_full": {}})
            nodes = parser.parse(body)
        except ValueError as e:
            report["conflicts"].append({"file": fname, "prop": "(adopt)",
                                        "reason": f"新卡無法解析：{e}"})
            continue
        if dry:
            report["created"].append(f"{fname}（dry-run：待收養進 Heptabase）")
            continue
        created = cli("note", "create", "--content", f"# {title}")
        cid = created["id"]
        note = cli("note", "read", cid)
        h1 = {"type": "heading", "attrs": {"id": None, "level": 1},
              "content": [{"type": "text", "text": title}]}
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        tmp.write(json.dumps({"type": "doc", "content": [h1] + nodes},
                             ensure_ascii=False))
        tmp.close()
        try:
            cli("note", "save", cid, "--content-md5", note["contentMd5"],
                "--content-file", tmp.name)
        finally:
            os.unlink(tmp.name)
        if col.get("tag_name"):
            cli("tag", "add", "--card-id", cid, "--tag-name", col["tag_name"])
        # properties from frontmatter (known, non-relation columns only);
        # collection defaults (e.g. Source Type=alphaXiv) fill the gaps so the
        # adopted card passes the collection filter on the fetch that follows
        wanted = {}
        for name, dv in (col.get("new_card_props") or {}).items():
            key = fm_key(name)
            if key in props_by_key and fm.get(key) in (None, "", []):
                wanted[key] = (props_by_key[key], dv)
        for key, pdef in props_by_key.items():
            v = fm.get(key)
            if v in (None, "", []):
                continue
            wanted[key] = (pdef, v)
        for key, (pdef, v) in wanted.items():
            try:
                if pdef["type"] == "multiSelect":
                    vv = v if isinstance(v, list) else [v]
                    cli("card", "set-property", cid, "--property-id", pdef["id"],
                        "--json-value", json.dumps([str(x) for x in vv],
                                                   ensure_ascii=False))
                else:
                    vv = v[0] if isinstance(v, list) and len(v) == 1 else v
                    cli("card", "set-property", cid, "--property-id", pdef["id"],
                        "--value", str(vv))
            except Exception as e:
                report["writeback_errors"].append(
                    {"file": fname, "prop": key, "err": f"adopt: {str(e)[:200]}"})
        note2 = cli("note", "read", cid)
        state["cards"][cid] = {"file": fname, "collection": col["key"],
                               "md5": note2.get("contentMd5"),
                               "lastEditedTime": None,  # refresh on this run
                               "props": dict(fm),
                               "body_hash": body_hash(body)}
        in_set[cid] = fname
        report["created"].append(f"{fname}（已收養進 Heptabase：{cid}）")


def write_back(cid, fname, obs_body, note, resolver, in_set, state, att_dir, dry):
    """Block-level Obsidian -> Heptabase write-back.

    Unchanged blocks keep their original ProseMirror nodes (colors, toggles,
    block ids all intact). Edited/deleted blocks whose original contains a
    lossy construct - or whose new markdown fails the round-trip check - turn
    the whole card into a conflict: NOTHING is written (all-or-nothing).
    Returns (new_body, new_md5) on success, None on conflict.
    """
    def conflict(reason, block_md=""):
        report["conflicts"].append({"file": fname, "prop": "(body)",
                                    "block": block_md[:80], "reason": reason})

    cp = cache_path(cid)
    if not os.path.exists(cp):
        conflict("無 PM 快取，無法區塊級寫回（先跑一次 --rebuild-cache）")
        return None
    cache = json.load(open(cp))
    if note.get("contentMd5") != cache.get("contentMd5"):
        conflict("Heptabase 內容與快取不一致（兩邊都改了或快取過期）")
        return None

    entries = cache["blocks"]
    anchor_ids = set(cache.get("anchorIds") or [])
    id_map = {}
    def collect(n):
        i = (n.get("attrs") or {}).get("id")
        if i:
            id_map.setdefault(i[:8], i)
        for ch in n.get("content") or []:
            collect(ch)
    for e in entries:
        collect(e["node"])

    parser = md2pm.BlockParser({
        "self_id": cid, "workspace": WORKSPACE,
        "name_to_card": {v: k for k, v in in_set.items()},
        "attach_to_fileid": {v: k for k, v in state.get("files", {}).items()},
        "anchor_short_to_full": id_map})

    obs_blocks = split_blocks(obs_body)
    nonempty = [i for i, e in enumerate(entries) if e["md"].strip()]
    canon = [entries[i]["md"] for i in nonempty]
    sm = difflib.SequenceMatcher(None, canon, obs_blocks, autojunk=False)

    def trailing_empties(k):
        start = nonempty[k] + 1
        end = nonempty[k + 1] if k + 1 < len(nonempty) else len(entries)
        return [entries[i]["node"] for i in range(start, end)
                if not entries[i]["md"].strip()]

    new_nodes = [entries[i]["node"]
                 for i in range(nonempty[0] if nonempty else len(entries))]
    ok, wrote_groups = True, 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i1, i2):
                new_nodes.append(entries[nonempty[k]]["node"])
                new_nodes += trailing_empties(k)
            continue
        for k in range(i1, i2):
            r = md2pm.lossy_reason(entries[nonempty[k]]["node"])
            if r:
                conflict(r, entries[nonempty[k]]["md"])
                ok = False
        region = "\n\n".join(obs_blocks[j1:j2])
        if not ok or not region.strip():
            wrote_groups += bool(region.strip()) or (i2 > i1)
            continue
        try:
            nodes = parser.parse(region)
        except ValueError as e:
            conflict(f"無法解析 markdown：{e}", region)
            ok = False
            continue

        # Guard: a toggle (`- ⏵ `) rewritten as a todo checkbox is a node-type
        # change (usually a hand edit gone wrong). Never write that back
        # silently.
        def _types(ns, acc):
            for n in ns:
                acc.add(n.get("type"))
                _types(n.get("content") or [], acc)
            return acc
        orig_types = _types([entries[nonempty[k]]["node"]
                             for k in range(i1, i2)], set())
        new_types = _types(nodes, set())
        if "toggle_list_item" in orig_types and "todo_list_item" in new_types:
            conflict("toggle（- ⏵）被改成 checkbox（- [ ]/- [x]）——"
                     "如非刻意，請把該行改回「- ⏵ 」再同步", region)
            ok = False
            continue

        conv = Converter({"id": cid, "title": cache.get("title") or ""}, anchor_ids)
        mds, ord_idx = [], 0
        for n in nodes:
            if n["type"] in ("ordered_list_item", "numbered_list_item"):
                ord_idx += 1
            else:
                ord_idx = 0
            mds.append(re.sub(r"\n{3,}", "\n\n",
                              conv.block(n, 0, ord_idx or None)).strip("\n"))
        rendered = assemble(resolver.resolve(m, cid, state.get("files", {}),
                                             anchor_ids) for m in mds)
        if norm_md(rendered) != norm_md(region):
            conflict("round-trip 不一致（含寫回後會變形的語法）", region)
            ok = False
            continue
        new_nodes += nodes
        wrote_groups += 1
    if not ok:
        return None

    doc = {"type": "doc", "content": (cache.get("prefix") or []) + new_nodes}
    if dry:
        report["prop_writeback"].append(
            {"file": fname, "prop": "(body)",
             "value": f"dry-run：{wrote_groups} 個區塊群將寫回"})
        return obs_body, cache.get("contentMd5")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    tmp.write(json.dumps(doc, ensure_ascii=False))
    tmp.close()
    try:
        cli("note", "save", cid, "--content-md5", cache["contentMd5"],
            "--content-file", tmp.name)
    finally:
        os.unlink(tmp.name)
    note2 = cli("note", "read", cid)
    body2, md5_2 = render_forward(note2, cid, {"title": note2.get("title")},
                                  resolver, state, att_dir, dry)
    report["prop_writeback"].append(
        {"file": fname, "prop": "(body)",
         "value": f"{wrote_groups} 個區塊群已寫回 Heptabase"})
    return body2, md5_2


def sync_card(card, col, folder, att_dir, props_by_key, state, resolver,
              in_set, bootstrap, dry):
    cid = card["id"]
    fname = in_set[cid]
    path = os.path.join(folder, fname + ".md")
    st = state["cards"].get(cid)
    hepta_fm = hepta_props_fm(card, props_by_key)

    # rename if title changed
    if st and st["file"] != fname:
        st = None  # shouldn't happen (we keep state name); safety
    if st:
        new_base = safe_filename(card["title"])
        if new_base != st["file"] and not st["file"].startswith(new_base + " ("):
            old_path = os.path.join(folder, st["file"] + ".md")
            new_name, i = new_base, 1
            while os.path.exists(os.path.join(folder, new_name + ".md")):
                i += 1
                new_name = f"{new_base} ({i})"
            if not dry and os.path.exists(old_path):
                os.rename(old_path, os.path.join(folder, new_name + ".md"))
                rewrite_wikilinks(st["file"], new_name)
            report["renamed"].append({"from": st["file"], "to": new_name})
            st["file"] = new_name
            in_set[cid] = new_name
            fname = new_name
            path = os.path.join(folder, fname + ".md")

    file_exists = os.path.exists(path)
    need_body = (st is None or st.get("lastEditedTime") != card.get("lastEditedTime")
                 or not file_exists or REBUILD)

    obs_fm, obs_body = (parse_file(path) if file_exists else ({}, ""))

    # ---------- 3-way property sync
    snap = (st or {}).get("props", {})
    merged_fm, writebacks, conflicts = {}, [], []
    for key, pdef in props_by_key.items():
        multi = pdef["type"] == "multiSelect"
        h, s, o = (norm(hepta_fm.get(key), multi), norm(snap.get(key), multi),
                   norm(obs_fm.get(key), multi))
        if st is None:  # bootstrap / new card: Heptabase wins, report diffs
            if file_exists and o != h:
                report["bootstrap_fm_diffs"].append(
                    {"file": fname, "prop": key, "obsidian": obs_fm.get(key),
                     "heptabase": hepta_fm.get(key)})
            raw = hepta_fm.get(key)
        elif h == s and o == s:
            raw = snap.get(key)
        elif h != s and (o == s or o == h):
            raw = hepta_fm.get(key)
        elif o != s and h == s:
            raw = obs_fm.get(key)
            writebacks.append((key, pdef, obs_fm.get(key)))
        else:
            conflicts.append({"file": fname, "prop": key,
                              "heptabase": hepta_fm.get(key),
                              "obsidian": obs_fm.get(key)})
            # keep the USER'S file value; the snapshot stays old (below) so
            # the conflict re-reports every run until resolved — never
            # clobber the file or silently write either side back
            raw = obs_fm.get(key)
        if raw not in (None, "", []):
            merged_fm[key] = raw
    report["conflicts"].extend(conflicts)

    # ---------- body (3-way: hepta changed / obsidian changed / both)
    body = obs_body
    content_md5 = (st or {}).get("md5")
    new_last_edited = card.get("lastEditedTime")
    obs_changed = bool(st and file_exists and st.get("body_hash")
                       and body_hash(obs_body) != st["body_hash"])

    new_body_hash = None  # None -> hash(body) at state-update time
    if obs_changed:
        # decide by actual content md5, not lastEditedTime (property edits
        # and our own saves bump the timestamp without changing content)
        note = cli("note", "read", cid)
        if note.get("contentMd5") == st.get("md5"):
            wb = write_back(cid, fname, obs_body, note, resolver, in_set,
                            state, att_dir, dry)
            if wb is None:  # conflicts reported; keep everything pending
                new_last_edited = st.get("lastEditedTime")
                new_body_hash = st.get("body_hash")
            else:
                body, content_md5 = wb
                new_last_edited = None  # save bumped it; refresh next run
        else:
            report["conflicts"].append(
                {"file": fname, "prop": "(body)",
                 "heptabase": "content changed", "obsidian": "content changed",
                 "hint": "兩邊內文都改了；先手動處理其中一邊再重跑 sync"})
            new_last_edited = st.get("lastEditedTime")
            new_body_hash = st.get("body_hash")
    elif need_body:
        note = cli("note", "read", cid)
        if (not REBUILD and st and note.get("contentMd5") == st.get("md5")
                and file_exists):
            content_md5 = st.get("md5")
            if not os.path.exists(cache_path(cid)):  # backfill cache
                render_forward(note, cid, card, resolver, state, att_dir, dry)
        else:
            body, content_md5 = render_forward(note, cid, card, resolver,
                                               state, att_dir, dry)

    # ---------- assemble + write
    fm = dict(merged_fm)
    fm["title"] = card["title"]
    fm["heptabase_id"] = cid
    fm["created"] = card.get("createdTime", "")
    fm["modified"] = card.get("lastEditedTime", "")
    new_text = dump_fm(fm) + "\n\n" + body
    old_text = (open(path).read() if file_exists else None)
    if new_text != old_text:
        if not dry:
            with open(path, "w") as f:
                f.write(new_text)
        if not file_exists:
            report["created"].append(fname)
        elif need_body:
            report["body_updated"].append(fname)
        else:
            report["fm_updated"].append(fname)

    # ---------- property write-back
    snap_new = dict(hepta_fm)
    # conflicted keys keep the OLD snapshot: both sides still differ from it,
    # so the conflict re-detects next run instead of one side silently winning
    for c in conflicts:
        k = c["prop"]
        if k in snap:
            snap_new[k] = snap[k]
        else:
            snap_new.pop(k, None)
    for key, pdef, value in writebacks:
        try:
            if not dry:
                if value in (None, "", []):
                    # clearing wins over type dispatch: a cleared multiSelect
                    # must become null, never [str(None)]
                    cli("card", "set-property", cid, "--property-id", pdef["id"],
                        "--json-value", "null")
                elif pdef["type"] == "multiSelect":
                    v = value if isinstance(value, list) else [value]
                    cli("card", "set-property", cid, "--property-id", pdef["id"],
                        "--json-value", json.dumps([str(x) for x in v], ensure_ascii=False))
                else:
                    v = value[0] if isinstance(value, list) and len(value) == 1 else value
                    cli("card", "set-property", cid, "--property-id", pdef["id"],
                        "--value", str(v))
            snap_new[key] = value
            report["prop_writeback"].append({"file": fname, "prop": key, "value": value})
        except Exception as e:
            report["writeback_errors"].append({"file": fname, "prop": key,
                                               "err": str(e)[:300]})

    if not dry:
        state["cards"][cid] = {"file": fname, "collection": col["key"],
                               "md5": content_md5,
                               "lastEditedTime": new_last_edited,
                               "props": snap_new,
                               "body_hash": new_body_hash or body_hash(body)}


def rewrite_wikilinks(old, new):
    for col in COLLECTIONS:
        folder = os.path.join(VAULT, col["folder"])
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(folder, fn)
            text = open(p).read()
            t2 = text.replace(f"[[{old}]]", f"[[{new}]]").replace(f"[[{old}|", f"[[{new}|")
            if t2 != text:
                open(p, "w").write(t2)


if __name__ == "__main__":
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    main()
