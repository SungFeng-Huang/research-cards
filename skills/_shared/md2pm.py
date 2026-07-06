#!/usr/bin/env python3
"""Markdown -> ProseMirror for the Level-2 write-back (safe subset only).

Only constructs that our forward converter (sync.Converter) can reproduce
byte-identically are supported. Anything else must be caught EITHER by
lossy_reason() on the original nodes OR by the caller's round-trip check
(re-render parsed nodes and compare with the input markdown).
"""
import re, uuid

# reverse of pmmd.HEPTA_TO_CSS: CSS color -> Heptabase color name
CSS_TO_HEPTA = {"#e5484d": "red", "#c8860d": "yellow", "#2f9e68": "green",
                "#3b82f6": "blue", "#8b5cf6": "purple", "#f76b15": "orange"}

# ---------------------------------------------------------------- lossy scan

def lossy_reason(node):
    """Why writing back over this node would lose information (None = safe)."""
    t = node.get("type")
    a = node.get("attrs") or {}
    # toggle_list_item / text-color / underline are NOT lossy: the plugin
    # markdown dialect round-trips them (`- [>] `, <span style=color>, <u>).
    if t == "embed":
        return "highlight/物件嵌入（會脫鉤成純文字）"
    if t in ("whiteboard", "section", "pdf_card", "chat"):
        return f"{t} 提及（無法從 markdown 重建）"
    if t == "image" and (a.get("width") or (a.get("alignment") not in (None, "center"))):
        return "圖片自訂寬度/對齊（markdown 無法表達）"
    if t == "table":
        for row in node.get("content") or []:
            for cell in row.get("content") or []:
                ca = cell.get("attrs") or {}
                if (ca.get("colspan") or 1) != 1 or (ca.get("rowspan") or 1) != 1:
                    return "表格合併儲存格"
                kids = cell.get("content") or []
                if len(kids) != 1 or kids[0].get("type") != "paragraph":
                    return "表格儲存格含多段落/巢狀內容"
    for m in node.get("marks") or []:
        mt, ma = m.get("type"), m.get("attrs") or {}
        if mt == "color" and ma.get("type") == "text" and ma.get("color"):
            continue  # round-trips as <span style="color:...">
        if mt in ("highlight", "textColor", "backgroundColor", "color") and \
                (ma.get("color") or ma.get("backgroundColor")):
            return "背景色/highlight 顏色（markdown dialect 尚未支援）"
    for ch in node.get("content") or []:
        r = lossy_reason(ch)
        if r:
            return r
    return None


# ------------------------------------------------------------------- helpers

def nid():
    return str(uuid.uuid4())


def text_node(text, marks=None):
    n = {"type": "text", "text": text}
    if marks:
        n["marks"] = marks
    return n


def link_mark(href):
    return {"type": "link", "attrs": {"href": href, "title": None,
                                      "data-internal-href": None, "edited": False}}


# ------------------------------------------------------------- inline parser
# token priority: inline code > math > links/wikilinks > bold > highlight >
# strike > italic. Recursion applies remaining levels inside each match.

class InlineParser:
    def __init__(self, ctx):
        # ctx: self_id, workspace, name_to_card {filename: cardId},
        #      anchor_short_to_full {8char: full block uuid}
        self.ctx = ctx

    def parse(self, text):
        return self._level(text, 0)

    LEVELS = ["code", "math", "span", "underline", "link", "bold", "highlight",
              "strike", "italic"]
    PATTERNS = {
        "code": re.compile(r"`([^`]+)`"),
        "math": re.compile(r"\$([^$\n]+)\$"),
        "span": re.compile(r'<span style="color:([#\w-]+)">(.*?)</span>', re.S),
        "underline": re.compile(r"<u>(.*?)</u>", re.S),
        "link": re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]|\[([^\]]*)\]\(([^)\s]+)\)"),
        "bold": re.compile(r"\*\*(.+?)\*\*", re.S),
        "highlight": re.compile(r"==(.+?)==", re.S),
        "strike": re.compile(r"~~(.+?)~~", re.S),
        "italic": re.compile(r"\*([^*\n]+)\*"),
    }

    def _level(self, text, li):
        if li >= len(self.LEVELS):
            return [text_node(text)] if text else []
        kind = self.LEVELS[li]
        pat = self.PATTERNS[kind]
        out, pos = [], 0
        for m in pat.finditer(text):
            if m.start() > pos:
                out += self._level(text[pos:m.start()], li + 1)
            out += self._token(kind, m, li)
            pos = m.end()
        if pos < len(text):
            out += self._level(text[pos:], li + 1)
        return out

    def _mark_wrap(self, inner_nodes, mark):
        for n in inner_nodes:
            if n.get("type") == "text":
                n.setdefault("marks", []).append(mark)
        return inner_nodes

    def _token(self, kind, m, li):
        if kind == "code":
            return [text_node(m.group(1), [{"type": "code"}])]
        if kind == "math":
            return [{"type": "math_inline", "content": [text_node(m.group(1))]}]
        if kind == "link":
            return self._link(m, li)
        if kind == "span":
            color = CSS_TO_HEPTA.get(m.group(1).lower(), m.group(1))
            mark = {"type": "color", "attrs": {"type": "text", "color": color}}
            return self._mark_wrap(self._level(m.group(2), li + 1), mark)
        if kind == "underline":
            return self._mark_wrap(self._level(m.group(1), li + 1),
                                   {"type": "underline"})
        mark = {"bold": {"type": "strong"}, "highlight": {"type": "highlight"},
                "strike": {"type": "strikethrough"}, "italic": {"type": "em"}}[kind]
        return self._mark_wrap(self._level(m.group(1), li + 1), mark)

    def _link(self, m, li):
        if m.group(4) is not None:                      # [label](url)
            label, href = m.group(3), m.group(4)
            return self._mark_wrap(self._level(label, li + 1), link_mark(href))
        if self.ctx.get("mode") == "obsidian":
            # vault-native: keep [[wikilinks]] as literal text (round-trips)
            return [text_node(m.group(0))]
        ws, self_id = self.ctx["workspace"], self.ctx["self_id"]
        target, alias = m.group(1), m.group(2)
        if target.startswith("#^"):                     # [[#^id|label]]
            full = self.ctx["anchor_short_to_full"].get(target[2:])
            if not full:
                raise ValueError(f"unknown block anchor {target}")
            href = f"https://app.heptabase.com/{ws}/card/{self_id}#{full}"
            return self._mark_wrap(self._level(alias or target, li + 1),
                                   link_mark(href))
        cid = self.ctx["name_to_card"].get(target)
        if not cid:
            raise ValueError(f"wikilink target not a synced card: {target}")
        if alias is None:
            # plain [[Name]] -> native card MENTION (what Heptabase renders as
            # a card link; feeds the mention graph: whiteboard lines, topology,
            # coverage). Aliased links need custom text -> link mark instead.
            return [{"type": "card", "attrs": {"cardId": cid}}]
        href = f"https://app.heptabase.com/{ws}/card/{cid}"
        return self._mark_wrap(self._level(alias, li + 1), link_mark(href))


# -------------------------------------------------------------- block parser

LIST_RE = re.compile(r"^(\s*)(- \[[ x]\] |- |(\d+)\. )(.*)$")
HEADING_RE = re.compile(r"^(#{1,6}) (.*)$")
ANCHOR_RE = re.compile(r" \^([0-9a-f]{8})$")


class BlockParser:
    def __init__(self, ctx):
        self.ctx = ctx
        self.inline = InlineParser(ctx)

    def _strip_anchor(self, line):
        m = ANCHOR_RE.search(line)
        if m:
            full = self.ctx["anchor_short_to_full"].get(m.group(1))
            if not full:
                raise ValueError(f"unknown block anchor ^{m.group(1)}")
            return line[:m.start()], full
        return line, None

    def _para(self, lines, node_id=None):
        content = []
        for i, ln in enumerate(lines):
            if i:
                content.append({"type": "hard_break"})
            content += self.inline.parse(ln)
        return {"type": "paragraph", "attrs": {"id": node_id or nid()},
                "content": content}

    def parse(self, md):
        lines = md.splitlines()
        nodes, i = [], 0
        while i < len(lines):
            ln = lines[i]
            if not ln.strip():
                i += 1
                continue
            if ln.strip() == "---":
                nodes.append({"type": "horizontal_rule", "attrs": {"id": nid()}})
                i += 1
            elif ln.startswith("```"):
                lang = ln[3:].strip()
                j = i + 1
                while j < len(lines) and not lines[j].startswith("```"):
                    j += 1
                body = "\n".join(lines[i + 1:j])
                nodes.append({"type": "code_block",
                              "attrs": {"id": nid(), "language": lang or None},
                              "content": [text_node(body)] if body else []})
                i = j + 1
            elif ln.strip() == "$$":
                j = i + 1
                while j < len(lines) and lines[j].strip() != "$$":
                    j += 1
                nodes.append({"type": "math_display", "attrs": {"id": nid()},
                              "content": [text_node("\n".join(lines[i + 1:j]))]})
                i = j + 1
            elif HEADING_RE.match(ln):
                stripped, anchor = self._strip_anchor(ln)
                m = HEADING_RE.match(stripped)
                nodes.append({"type": "heading",
                              "attrs": {"id": anchor or nid(), "level": len(m.group(1))},
                              "content": self.inline.parse(m.group(2))})
                i += 1
            elif ln.startswith("> "):
                j = i
                while j < len(lines) and lines[j].startswith(">"):
                    j += 1
                qlines = [l[2:] if l.startswith("> ") else l[1:] for l in lines[i:j]]
                nodes.append({"type": "blockquote", "attrs": {"id": nid()},
                              "content": [self._para([q]) for q in qlines]})
                i = j
            elif ln.startswith("![[") or ln.startswith("!["):
                stripped, anchor = self._strip_anchor(ln)
                nodes.append(self._image(stripped.strip(), anchor))
                i += 1
            elif ln.startswith("| "):
                j = i
                while j < len(lines) and lines[j].startswith("|"):
                    j += 1
                nodes.append(self._table(lines[i:j]))
                i = j
            elif LIST_RE.match(ln):
                item, i = self._list_item(lines, i, 0)
                nodes.append(item)
            else:
                j = i
                while j < len(lines) and lines[j].strip() and \
                        not any(lines[j].startswith(p) for p in ("#", "- ", "> ", "```", "![", "|")) \
                        and lines[j].strip() != "---" and not LIST_RE.match(lines[j]) \
                        and lines[j].strip() != "$$":
                    j += 1
                plines, anchor = [], None
                for k, l in enumerate(lines[i:j]):
                    s, a = self._strip_anchor(l)
                    plines.append(s)
                    anchor = anchor or a
                nodes.append(self._para(plines, anchor))
                i = j
        return nodes

    def _image(self, line, anchor):
        m = re.match(r"^!\[\[([^\]]+)\]\]$", line)
        if m:
            fid = self.ctx["attach_to_fileid"].get(m.group(1))
            if not fid and self.ctx.get("mode") == "obsidian":
                return {"type": "image",
                        "attrs": {"id": anchor or nid(), "src": None,
                                  "fileId": None, "obsidianFile": m.group(1),
                                  "alt": None, "title": None, "width": None,
                                  "originalHeight": None, "originalWidth": None,
                                  "alignment": "center", "reference": None}}
            if not fid:
                raise ValueError(f"unknown attachment: {m.group(1)}")
            return {"type": "image",
                    "attrs": {"id": anchor or nid(), "src": None, "fileId": fid,
                              "alt": None, "title": None, "width": None,
                              "originalHeight": None, "originalWidth": None,
                              "alignment": "center", "reference": None}}
        m = re.match(r"^!\[\]\(([^)]+)\)$", line)
        if m:
            return {"type": "image",
                    "attrs": {"id": anchor or nid(), "src": m.group(1), "fileId": None,
                              "alt": None, "title": None, "width": None,
                              "originalHeight": None, "originalWidth": None,
                              "alignment": "center", "reference": None}}
        raise ValueError(f"unsupported image line: {line[:60]}")

    def _table(self, tlines):
        def cells(row):
            parts = [c.strip() for c in row.strip().strip("|").split("|")]
            return [c.replace("\\|", "|") for c in parts]
        header = cells(tlines[0])
        body_rows = [cells(r) for r in tlines[2:]]  # skip separator
        rows = [{"type": "table_row", "attrs": {"id": nid()}, "content": [
            {"type": "table_header", "attrs": {"id": nid()},
             "content": [self._para([h])]} for h in header]}]
        for r in body_rows:
            rows.append({"type": "table_row", "attrs": {"id": nid()}, "content": [
                {"type": "table_cell", "attrs": {"id": nid()},
                 "content": [self._para([c])]} for c in r]})
        return {"type": "table", "attrs": {"id": nid()}, "content": rows}

    def _list_item(self, lines, i, depth):
        m = LIST_RE.match(lines[i])
        indent, marker, num, rest = m.group(1), m.group(2), m.group(3), m.group(4)
        if len(indent) != depth * 4:
            raise ValueError(f"unexpected list indent: {lines[i][:40]}")
        rest, anchor = self._strip_anchor(rest)
        if marker == "- " and rest.startswith("⏵ "):
            ntype, attrs = "toggle_list_item", {}
            rest = rest[2:]
        elif marker.startswith("- ["):
            ntype, attrs = "todo_list_item", {"checked": "x" in marker}
        elif num is not None:
            ntype, attrs = "numbered_list_item", {}
        else:
            ntype, attrs = "bullet_list_item", {}
        base_attrs = {"id": anchor or nid(), "folded": False}
        if ntype != "toggle_list_item":
            base_attrs["format"] = None
        node = {"type": ntype, "attrs": {**base_attrs, **attrs},
                "content": [self._para([rest])]}
        i += 1
        child_ind = " " * ((depth + 1) * 4)
        while i < len(lines):
            ln = lines[i]
            if not ln.strip():
                break
            m2 = LIST_RE.match(ln)
            if m2 and len(m2.group(1)) >= (depth + 1) * 4:
                child, i = self._list_item(lines, i, depth + 1)
                node["content"].append(child)
            elif ln.startswith(child_ind) and ln[len(child_ind)] != " ":
                # indented continuation paragraph(s) belonging to this item
                plines = []
                while i < len(lines) and lines[i].startswith(child_ind) \
                        and not LIST_RE.match(lines[i]):
                    s, _ = self._strip_anchor(lines[i][len(child_ind):])
                    plines.append(s)
                    i += 1
                node["content"].append(self._para(plines))
            else:
                break
        return node, i
