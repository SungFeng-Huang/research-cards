#!/usr/bin/env python3
"""
Mechanics for rewriting a Heptabase paper card into the teaching-style format.
Claude AUTHORS the content (by reading the paper card + the alphaXiv original via
MCP); this module provides the reusable, easy-to-get-wrong machinery:
  - read / save a card (via --content-file, so data-URL images survive)
  - extract the existing figure nodes so the rewrite PRESERVES them
  - ProseMirror builders (heading / paragraph / bullet / toggle / image / hr)
  - colorize(): re-apply 🟡/🟢/🔴 marks (lost when content is rebuilt)
  - finalize(): colorize → size-check (100k limit) → save

Typical use (in a per-card rewrite script, or a retrofit subagent):

    import rewrite_lib as L
    md5, doc = L.read_card(CID)
    imgs = L.extract_images(doc)              # [{"src","caption"}, ...] in order
    C = []
    C.append(L.h(1, "[alphaXiv] …"))
    C.append(L.pp([("一句話：", True), "…"]))
    C.append(L.hr())
    C.append(L.h(2, "快速摘要"))
    C.append(L.toggle("AI 摘要", [L.p("…")]))
    C.append(L.toggle("問題", [L.bp("…"), L.bp("…")]))
    …
    C.append(L.h(3, "3.1 …")); C += L.img(imgs[0]["src"], "圖：…")
    C.append(L.bul("架構", "…"))
    …
    C.append(L.source("https://www.alphaxiv.org/zh/overview/{id}"))
    L.finalize(CID, md5, C, COLOR_RULES)
"""
import os, sys, json, subprocess, tempfile, re, copy
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

STUDY_PAPER_TAG = SOURCE_TYPE_PROP = ARXIV_PROP = None  # from config below
# A card counts as "already upgraded" if it carries the teaching-style structural
# marker — the 先備知識 section (every rewrite adds one). No property/tag needed.
UPGRADE_MARKER = "先備知識"

# ── read / save (backend-routed: obsidian vault when config says so) ─────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "_shared"))
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None
try:
    import hbconfig as _hbc0
    STUDY_PAPER_TAG = _hbc0.hb_id("collections", "papers", "tag_id")
    SOURCE_TYPE_PROP = _hbc0.hb_id("props", "source_type")
    ARXIV_PROP = _hbc0.hb_id("props", "arxiv")
except Exception:
    pass

def read_card(cid):
    if OBS:
        return OBS.read_doc(cid)
    r = subprocess.run(["heptabase", "note", "read", cid], capture_output=True, text=True)
    data = json.loads(r.stdout)
    return data["contentMd5"], json.loads(data["content"])

def save_card(cid, md5, doc):
    if OBS:
        return OBS.save_doc(cid, md5, doc)
    s = json.dumps(doc, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(s); tmp = f.name
    try:
        subprocess.run(["heptabase", "note", "save", cid, "--content-md5", md5,
                        "--content-file", tmp], check=True, capture_output=True)
    finally:
        os.unlink(tmp)

def _txt(n):
    t = n.get("type")
    if t == "text":
        return n.get("text", "")
    if t == "card":                       # card-link node carries no text — surface it
        return "[[card:%s]]" % (n.get("attrs", {}).get("cardId", ""))
    return "".join(_txt(c) for c in n.get("content", []) if isinstance(c, dict))

def card_dump(cid):
    """Readable plain-text dump of a card (RECURSIVE — sees nested bullets/toggles,
    unlike a naive non-recursive extractor). Use to read the OLD card before rewriting."""
    _, doc = read_card(cid)
    out = []
    for n in doc["content"]:
        t = n.get("type")
        if t == "heading":
            out.append("#" * n["attrs"]["level"] + " " + _txt(n))
        elif t == "paragraph":
            s = _txt(n)
            if s.strip(): out.append(s)
        elif t == "toggle_list_item":
            out.append("▸ " + _txt(n["content"][0]))
            for c in n["content"][1:]:
                out.append("    - " + _txt(c))
        elif t == "bullet_list_item":
            out.append("• " + _txt(n))
        elif t == "horizontal_rule":
            out.append("----")
        elif t == "image":
            a = n.get("attrs", {})
            ref = a.get("src") or a.get("fileId") or ""
            out.append("[IMAGE] " + ref[:60])
        elif t == "table":                # render rows so tables aren't invisible on read
            for row in n.get("content", []):
                cells = [" ".join(_txt(c) for c in cell.get("content", [])).strip()
                         for cell in row.get("content", [])]
                out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)

def extract_images(doc):
    """Return the card's figures in order as [{"src","caption"}] so a rewrite can
    re-insert them. caption = the italic paragraph immediately following the image."""
    out, content = [], doc["content"]
    for i, n in enumerate(content):
        if n.get("type") == "image":
            cap = ""
            if i + 1 < len(content):
                nxt = content[i + 1]
                if nxt.get("type") == "paragraph" and any(
                        m.get("type") == "em" for c in nxt.get("content", []) for m in c.get("marks", [])):
                    cap = _txt(nxt)
            out.append({"src": n["attrs"].get("src", ""), "caption": cap})
    return out

# ── retrofit-status detection ─────────────────────────────────────────────────
def is_upgraded(doc):
    """True if the card already has the teaching-style 先備知識 section marker."""
    return any(n.get("type") == "heading" and UPGRADE_MARKER in _txt(n)
               for n in doc["content"])

def list_todo(source_type="alphaXiv"):
    """List study/paper cards that still need a teaching-style retrofit (no 先備知識
    marker). Pass source_type=None to scan every study/paper card; default limits to
    cron-generated alphaXiv cards. Overview cards are skipped. Returns
    {"todo":[...], "done":[...]} of {card_id,title,arxiv}. Reads each card's content
    (one note read per card) — a manual maintenance command, not a hot path."""
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            raise SystemExit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    if OBS:
        todo, done, excluded = [], [], 0
        for c in OBS.list_cards("papers"):
            if source_type is not None and c["props"].get("source_type") != source_type:
                excluded += 1
                continue
            try:
                _, doc = read_card(c["id"])
            except Exception:
                continue
            rec = {"card_id": c["id"], "title": c["title"],
                   "arxiv": c["props"].get("arxiv_id")}
            (done if is_upgraded(doc) else todo).append(rec)
        return _with_exclusion_note({"todo": todo, "done": done}, excluded, source_type)
    if not (STUDY_PAPER_TAG and SOURCE_TYPE_PROP and ARXIV_PROP):
        raise SystemExit("config 缺少 heptabase.collections.papers.tag_id / props.*（heptabase 模式必填）")
    r = subprocess.run(["heptabase", "tag", "cards", STUDY_PAPER_TAG,
                        "--include-properties"], capture_output=True, text=True)
    cards = json.loads(r.stdout).get("cards", [])
    todo, done, excluded = [], [], 0
    for c in cards:
        src = aid = None
        for p in c.get("properties", []):
            if p["id"] == SOURCE_TYPE_PROP: src = p.get("value")
            if p["id"] == ARXIV_PROP: aid = p.get("value")
        if src == "Overview":
            continue
        if source_type is not None and src != source_type:
            excluded += 1
            continue
        try:
            _, doc = read_card(c["id"])
        except Exception:
            continue
        rec = {"card_id": c["id"], "title": c.get("title", ""), "arxiv": aid}
        (done if is_upgraded(doc) else todo).append(rec)
    return _with_exclusion_note({"todo": todo, "done": done}, excluded, source_type)


def _with_exclusion_note(result, excluded, source_type):
    """The silent blind spot that hid 11 legacy cards for years: cards without
    (or with a different) Source Type never even ENTER the todo list. Keep the
    filter, but make the exclusion a visible number."""
    result["excluded_by_filter"] = excluded
    if excluded:
        print(f"[list_todo] 注意：另有 {excluded} 張 study/paper 卡因 "
              f"Source Type != {source_type!r} 未列入本清單"
              f"（list_todo(source_type=None) 可全掃）", file=sys.stderr)
    return result

# ── ProseMirror builders ──────────────────────────────────────────────────────
def h(level, text):
    return {"type": "heading", "attrs": {"id": None, "level": level},
            "content": [{"type": "text", "text": text}]}
def p(text):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": ([{"type": "text", "text": text}] if text else [])}
def pp(parts):
    """Paragraph with mixed bold/plain spans: parts = [(text, bold_bool) | text]."""
    c = []
    for seg in parts:
        if isinstance(seg, tuple):
            t, bold = seg
            node = {"type": "text", "text": t}
            if bold: node["marks"] = [{"type": "strong"}]
            c.append(node)
        else:
            c.append({"type": "text", "text": seg})
    return {"type": "paragraph", "attrs": {"id": None}, "content": c}
def hr():
    return {"type": "horizontal_rule", "attrs": {"id": None}}
def bul(label, text):
    """Bold-labelled bullet:  **label**：text"""
    return {"type": "bullet_list_item", "attrs": {"id": None, "folded": False, "format": None},
            "content": [{"type": "paragraph", "attrs": {"id": None},
                "content": [{"type": "text", "marks": [{"type": "strong"}], "text": label},
                            {"type": "text", "text": "：" + text}]}]}
def bp(text):
    """Plain bullet."""
    return {"type": "bullet_list_item", "attrs": {"id": None, "folded": False, "format": None},
            "content": [p(text)]}
def img(src, caption):
    """Image node + italic caption paragraph. Returns a LIST (use C += L.img(...))."""
    out = [{"type": "image", "attrs": {"id": None, "src": src, "alignment": "center"}}]
    if caption:
        out.append({"type": "paragraph", "attrs": {"id": None},
                    "content": [{"type": "text", "marks": [{"type": "em"}], "text": caption}]})
    return out
def toggle(label, nodes, folded=False):
    lab = {"type": "paragraph", "attrs": {"id": None},
           "content": [{"type": "text", "marks": [{"type": "strong"}], "text": label}]}
    return {"type": "toggle_list_item", "attrs": {"id": None, "folded": folded},
            "content": [lab] + nodes}
def source(url):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": [{"type": "text", "text": "Source: " + url}]}

def add(C, *nodes):
    """Append builder output to the content list, ergonomically. Single-node
    builders (h/p/pp/bul/bp/toggle/hr/source) return a dict; `img` returns a LIST
    (image + caption). `add` handles both, so you never hit the `C += L.h(...)`
    footgun (a dict spread into a list yields its keys). Use:
        C = []
        L.add(C, L.h(1, "…"), L.pp([...]), L.hr())
        L.add(C, *L.img(src, "圖：…"))      # or just: L.add(C, L.img(src, cap))
    Returns C for chaining."""
    for n in nodes:
        if isinstance(n, list):
            C.extend(n)
        else:
            C.append(n)
    return C

# ── colorization ──────────────────────────────────────────────────────────────
def _color_mark(c): return {"type": "color", "attrs": {"type": "text", "color": c}}
def _colorize_text(node, rules):
    text = node.get("text", ""); marks = node.get("marks", [])
    hits = []
    for pat, col in rules:
        for m in re.finditer(re.escape(pat), text):
            hits.append((m.start(), m.end(), col))
    if not hits:
        return [node]
    hits.sort(key=lambda x: x[0])
    clean, last = [], 0
    for s, e, c in hits:
        if s >= last:
            clean.append((s, e, c)); last = e
    out, pos = [], 0
    for s, e, c in clean:
        if pos < s:
            n = {"type": "text", "text": text[pos:s]}
            if marks: n["marks"] = list(marks)
            out.append(n)
        out.append({"type": "text", "text": text[s:e], "marks": list(marks) + [_color_mark(c)]})
        pos = e
    if pos < len(text):
        n = {"type": "text", "text": text[pos:]}
        if marks: n["marks"] = list(marks)
        out.append(n)
    return out
def colorize(nodes, rules):
    """Apply (substring, 'yellow'|'green'|'red') rules to every text node, preserving
    existing marks (strong/em). First match wins per overlap. 🟡 names / 🟢 gains / 🔴 limits."""
    res = []
    for n in nodes:
        if n.get("type") == "text":
            res.extend(_colorize_text(n, rules))
        else:
            nn = copy.deepcopy(n)
            if "content" in nn:
                nn["content"] = colorize(nn["content"], rules)
            res.append(nn)
    return res

# ── figure size control ───────────────────────────────────────────────────────
def shrink_data_url(src, target_w=720, q=60):
    """Downscale a data-URL image (via PyMuPDF) so big PDF-rendered figures don't
    blow the 100k card limit. Returns a smaller JPEG data-URL, or the original on
    any failure / if it isn't a data-URL. Figures are PRESERVED, just lower-res."""
    if not src.startswith("data:"):
        return src
    try:
        import fitz, base64
        pix = fitz.Pixmap(base64.b64decode(src.split(",", 1)[1]))
        while pix.width > target_w:
            pix.shrink(1)                 # in-place halve
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)     # drop alpha (JPEG can't have it)
        jpg = pix.tobytes("jpg", jpg_quality=q)
        out = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
        return out if len(out) < len(src) else src
    except Exception:
        return src

def _shrink_card_figures(content, steps=((720, 60), (560, 52), (440, 46))):
    """Progressively downscale every data-URL image in `content` (mutates src in
    place) — used by finalize when a card is too big because of large figures."""
    imgs = [n for n in content if n.get("type") == "image"
            and n["attrs"].get("src", "").startswith("data:")]
    for tw, q in steps:
        if not imgs:
            break
        for n in imgs:
            n["attrs"]["src"] = shrink_data_url(n["attrs"]["src"], target_w=tw, q=q)
        if len(json.dumps({"content": content}, ensure_ascii=False)) < 90000:
            break

# ── finalize ──────────────────────────────────────────────────────────────────
LIMIT = 100000
def finalize(cid, md5, content, color_rules, dry_run=False):
    """Colorize → size-check (Heptabase 100k limit; with-UUID inflation ~+20%, so
    warn above ~80k as-built) → save. Returns the as-built size."""
    # Defensive flatten: tolerate nested lists (e.g. an img() list appended whole),
    # so a stray nesting never produces an invalid document.
    flat = []
    for n in content:
        flat.extend(n) if isinstance(n, list) else flat.append(n)
    content = colorize(flat, color_rules)
    size = len(json.dumps({"content": content}, ensure_ascii=False))
    # Auto-shrink large data-URL figures (the usual cause of oversize) — figures
    # are kept, just lower-res — so the card never lands over the 100k limit.
    if size > 88000:
        _shrink_card_figures(content)
        size = len(json.dumps({"content": content}, ensure_ascii=False))
    doc = {"content": content}
    if size > LIMIT:
        raise ValueError(f"as-built size {size} exceeds 100000 even after figure shrink — trim text")
    if size > 88000:
        print(f"  [WARN] as-built {size} — close to 100k; consider trimming text")
    if not dry_run:
        full_md5, full_doc = read_card(cid)
        full_doc["content"] = content
        save_card(cid, full_md5, full_doc)
    return size

# ── CLI: retrofit-status report ───────────────────────────────────────────────
if __name__ == "__main__":
    st = None if "all" in sys.argv else "alphaXiv"
    res = list_todo(source_type=st)
    scope = "all sources" if st is None else st
    print(f"retrofit status ({scope}): {len(res['done'])} upgraded, {len(res['todo'])} TODO\n")
    print("TODO (no 先備知識 marker — needs teaching-style retrofit):")
    for x in res["todo"]:
        print(f"  {x['card_id']}  {(x['arxiv'] or '-'):16} {x['title'][:60]}")
