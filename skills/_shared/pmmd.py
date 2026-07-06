#!/usr/bin/env python3
"""Shared ProseMirror <-> markdown conversion for the research-cards plugin.

Converter renders ProseMirror JSON to markdown with %%HEPTA-*%% placeholders
for card links/embeds/local files (callers resolve them per backend). The
reverse direction lives in md2pm.py.
"""
import re

# Heptabase text-color names -> readable CSS colors (Obsidian light & dark).
# Keep in sync with md2pm.CSS_TO_HEPTA (the reverse map).
HEPTA_TO_CSS = {"red": "#e5484d", "yellow": "#c8860d", "green": "#2f9e68",
                "blue": "#3b82f6", "purple": "#8b5cf6", "orange": "#f76b15"}


def assemble(block_mds):
    parts = [md for md in block_mds if md.strip()]
    return "\n\n".join(parts) + "\n" if parts else ""


def split_blocks(text):
    """Split markdown into blank-line-separated blocks (code-fence aware)."""
    blocks, cur, fence = [], [], False
    for ln in text.rstrip("\n").split("\n"):
        if ln.startswith("```"):
            fence = not fence
        if not ln.strip() and not fence:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def safe_filename(title):
    name = re.sub(r"^\[alphaXiv\]\s*", "", title).strip()
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return name[:180] or "untitled"


def norm_md(s):
    return "\n".join(l.rstrip() for l in s.strip().split("\n"))



class Converter:
    """ProseMirror JSON -> markdown with link placeholders."""

    def __init__(self, ctx, anchor_ids=None):
        self.ctx = ctx
        self.mentions = []      # {kind, targetId}
        self.local_files = []   # fileIds
        self.embeds = []        # highlightElement ids
        self.unknown = {}       # unhandled node/mark types -> example card id
        # Heptabase block ids that are targets of same-card anchor links;
        # emit an Obsidian block id (^xxxxxxxx) on those blocks.
        self.anchor_ids = anchor_ids or set()

    def marks(self, text, marks):
        for m in marks or []:
            t, a = m.get("type"), m.get("attrs") or {}
            if t == "strong":
                text = f"**{text}**"
            elif t in ("em", "italic"):
                text = f"*{text}*"
            elif t == "code":
                text = f"`{text}`"
            elif t in ("strikethrough", "strike"):
                text = f"~~{text}~~"
            elif t == "underline":
                text = f"<u>{text}</u>"
            elif t == "color" and a.get("type") == "text" and a.get("color"):
                # Heptabase text-color mark <-> HTML span (renders in Obsidian)
                css = HEPTA_TO_CSS.get(a["color"], a["color"])
                text = f'<span style="color:{css}">{text}</span>'
            elif t in ("highlight", "textColor", "backgroundColor", "color"):
                if t == "highlight" or a.get("backgroundColor") or a.get("color"):
                    text = f"=={text}=="
            elif t == "link":
                href = a.get("href") or ""
                text = f"[{text}]({href})" if href else text
            else:
                self.unknown[f"mark:{t}"] = self.ctx["id"]
        return text

    def inline(self, nodes):
        out = []
        for n in nodes or []:
            t = n.get("type")
            if t == "text":
                out.append(self.marks(n.get("text", ""), n.get("marks")))
            elif t == "hard_break":
                out.append("\n")
            elif t == "math_inline":
                out.append("$" + "".join(x.get("text", "") for x in n.get("content") or []) + "$")
            elif t in ("card", "whiteboard", "section", "pdf_card", "chat"):
                a = n.get("attrs") or {}
                oid = (a.get("cardId") or a.get("whiteboardId")
                       or a.get("sectionId") or a.get("pdfCardId")
                       or a.get("chatId"))
                self.mentions.append({"kind": t, "targetId": oid})
                out.append(f"%%HEPTA-{t.upper()}:{oid}%%")
            else:
                self.unknown[f"inline:{t}"] = self.ctx["id"]
                if n.get("content"):
                    out.append(self.inline(n["content"]))
        return "".join(out)

    def block(self, node, depth=0, ordered_index=None):
        t = node.get("type")
        a = node.get("attrs") or {}
        c = node.get("content") or []
        ind = "    " * depth
        if a.get("id") in self.anchor_ids:
            md = self._block_inner(node, t, a, c, ind, depth, ordered_index)
            if md.strip():
                return md.rstrip("\n") + f" ^{a['id'][:8]}\n"
            return md
        return self._block_inner(node, t, a, c, ind, depth, ordered_index)

    def _block_inner(self, node, t, a, c, ind, depth, ordered_index):
        if t == "heading":
            return f"{'#' * a.get('level', 1)} {self.inline(c)}\n"
        if t == "paragraph":
            txt = self.inline(c)
            return f"{txt}\n" if txt.strip() else ""
        if t == "horizontal_rule":
            return "---\n"
        if t == "text":
            return self.inline([node]) + "\n"
        if t == "math_display":
            return "$$\n" + "".join(x.get("text", "") for x in c) + "\n$$\n"
        if t == "embed":
            oid = a.get("objectId")
            if a.get("objectType") == "highlightElement":
                self.embeds.append(oid)
                return f"%%HEPTA-EMBED:{oid}%%\n"
            self.mentions.append({"kind": "embed", "targetId": oid})
            return f"%%HEPTA-CARD:{oid}%%\n"
        if t in ("bullet_list_item", "ordered_list_item", "numbered_list_item",
                 "todo_list_item", "check_list_item", "toggle_list_item"):
            marker = "- "
            if t in ("ordered_list_item", "numbered_list_item"):
                marker = f"{(ordered_index or 1)}. "
            if t in ("todo_list_item", "check_list_item"):
                marker = "- [x] " if a.get("checked") else "- [ ] "
            if t == "toggle_list_item":
                marker = "- ⏵ "  # plugin dialect: toggle = bullet + ⏵ prefix
                # (plain bullet on purpose — a checkbox syntax like `- [>]`
                # renders as a clickable box in Obsidian; clicking it would
                # rewrite the marker and change the node type on write-back)
            parts, first, child_ord = [], True, 0
            child_ind = "    " * (depth + 1)
            for ch in c:
                if ch.get("type") == "paragraph" and first:
                    parts.append(f"{ind}{marker}{self.inline(ch.get('content'))}\n")
                    first = False
                else:
                    if ch.get("type") in ("ordered_list_item", "numbered_list_item"):
                        child_ord += 1
                    else:
                        child_ord = 0
                    child_md = self.block(ch, depth + 1, child_ord or None)
                    if ch.get("type") == "paragraph" and child_md.strip():
                        # continuation paragraphs must be indented under the item
                        child_md = "".join(f"{child_ind}{l}\n" for l in
                                           child_md.rstrip("\n").split("\n"))
                    parts.append(child_md)
            if first:
                parts.insert(0, f"{ind}{marker}\n")
            return "".join(parts)
        if t == "blockquote":
            inner = "".join(self.block(ch) for ch in c)
            return "".join(f"> {ln}\n" for ln in inner.rstrip("\n").split("\n"))
        if t == "code_block":
            body = "".join(n.get("text", "") for n in c)
            return f"```{a.get('language') or ''}\n{body}\n```\n"
        if t in ("image", "file", "media"):
            if a.get("obsidianFile"):
                return f"![[{a['obsidianFile']}]]\n"
            if a.get("fileId"):
                self.local_files.append(a["fileId"])
                return f"%%HEPTA-LOCALFILE:{a['fileId']}%%\n"
            if a.get("src"):
                return f"![]({a['src']})\n"
            return ""
        if t == "table":
            rows = []
            for ri, row in enumerate(c):
                cells = []
                for cell in row.get("content") or []:
                    txt = " ".join(self.inline(p.get("content"))
                                   for p in (cell.get("content") or [])
                                   if p.get("type") == "paragraph").strip()
                    cells.append(txt.replace("|", "\\|").replace("\n", " "))
                rows.append("| " + " | ".join(cells) + " |")
                if ri == 0:
                    rows.append("|" + "|".join([" --- "] * len(cells)) + "|")
            return "\n".join(rows) + "\n"
        self.unknown[f"block:{t}"] = self.ctx["id"]
        return "".join(self.block(ch, depth) for ch in c)

    def convert_blocks(self, doc):
        """Top-level nodes -> [(node, block_md)], title H1 split off as prefix."""
        blocks, ord_idx = [], 0
        for node in doc.get("content") or []:
            if node.get("type") in ("ordered_list_item", "numbered_list_item"):
                ord_idx += 1
            else:
                ord_idx = 0
            md = self.block(node, 0, ord_idx or None)
            md = re.sub(r"\n{3,}", "\n\n", md).strip("\n")
            blocks.append((node, md))
        prefix = []
        if blocks and blocks[0][1].strip() == f"# {self.ctx['title']}":
            prefix = [blocks[0][0]]
            blocks = blocks[1:]
        return prefix, blocks

    def convert(self, doc):
        _, blocks = self.convert_blocks(doc)
        return assemble(md for _, md in blocks)


