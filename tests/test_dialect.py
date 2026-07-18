"""Markdown dialect round-trip guarantees (pmmd.Converter <-> md2pm).

These are the invariants the heptabase-sync write-back's round-trip check
relies on: for every supported construct, PM -> md -> PM -> md must be
byte-stable, and node types/marks must survive.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "_shared"))
import md2pm  # noqa: E402
from pmmd import Converter, assemble, split_blocks  # noqa: E402

CTX = {"self_id": "x", "workspace": "w", "name_to_card": {},
       "attach_to_fileid": {}, "anchor_short_to_full": {}, "mode": "obsidian"}


def pm_to_md(doc):
    return Converter({"id": "x", "title": "t"}).convert(doc)


def md_to_pm(md, ctx=None):
    nodes = md2pm.BlockParser(dict(ctx or CTX)).parse(md)
    return {"type": "doc", "content": nodes}


def roundtrip(md, ctx=None):
    return pm_to_md(md_to_pm(md, ctx))


class TestDialectRoundTrip(unittest.TestCase):
    def assert_stable(self, md, ctx=None):
        self.assertEqual(md, roundtrip(md, ctx))

    def test_headings_paragraphs_hr(self):
        self.assert_stable("## 標題\n\n段落一。\n\n---\n\n段落二。\n")

    def test_toggle_dialect(self):
        md = ("- ⏵ **AI 摘要**\n"
              "    內文段落。\n"
              "    - ⏵ 巢狀 toggle\n"
              "    - [x] 已完成項\n"
              "    - [ ] 未完成項\n")
        self.assert_stable(md)
        doc = md_to_pm(md)
        top = doc["content"][0]
        self.assertEqual(top["type"], "toggle_list_item")
        kinds = [c["type"] for c in top["content"]]
        self.assertEqual(kinds, ["paragraph", "paragraph", "toggle_list_item",
                                 "todo_list_item", "todo_list_item"])

    def test_color_span_palette(self):
        md = ('<span style="color:#c8860d">τ-Voice</span> 超越 '
              '<span style="color:#2f9e68">SOTA</span> 但 '
              '<span style="color:#e5484d">有侷限</span>。\n')
        self.assert_stable(md)
        node = md_to_pm(md)["content"][0]["content"][0]
        self.assertEqual(node["marks"][0],
                         {"type": "color", "attrs": {"type": "text", "color": "yellow"}})

    def test_underline_and_inline_marks(self):
        self.assert_stable("**粗** *斜* `code` ~~刪~~ ==螢光== <u>底線</u> $x^2$\n")

    def test_nested_lists_numbered(self):
        # canonical form: blank line between TOP-LEVEL items (each is its own
        # PM node); nested children stay adjacent
        self.assert_stable("1. 第一\n\n2. 第二\n\n- 甲\n    - 乙\n        - 丙\n")

    def test_tight_list_normalizes_then_converges(self):
        # adjacent top-level items are non-canonical: one round-trip
        # normalizes them (blank lines inserted), after which it's stable
        once = roundtrip("1. 第一\n2. 第二\n")
        self.assertEqual(once, "1. 第一\n\n2. 第二\n")
        self.assertEqual(roundtrip(once), once)

    def test_table(self):
        self.assert_stable("| a | b |\n| --- | --- |\n| 1 | 2 |\n")

    def test_math_display_and_code_block(self):
        self.assert_stable("$$\nE = mc^2\n$$\n\n```python\nprint(1)\n```\n")

    def test_blockquote(self):
        self.assert_stable("> 引用一\n> 引用二\n")

    def test_obsidian_mode_keeps_wikilinks_literal(self):
        md = "見 [[某張卡]] 與 [[卡|別名]]。\n"
        self.assert_stable(md)

    def test_obsidian_mode_image_embed(self):
        self.assert_stable("![[圖檔.png]]\n\n![](https://example.com/x.png)\n")

    def test_heptabase_mode_plain_wikilink_becomes_mention(self):
        ctx = dict(CTX, mode=None, name_to_card={"某張卡": "aaaa-bbbb"})
        doc = md_to_pm("見 [[某張卡]]。\n", ctx)
        kinds = [n.get("type") for n in doc["content"][0]["content"]]
        self.assertIn("card", kinds)

    def test_heptabase_mode_aliased_wikilink_becomes_link_mark(self):
        ctx = dict(CTX, mode=None, name_to_card={"某張卡": "aaaa-bbbb"})
        doc = md_to_pm("見 [[某張卡|別名]]。\n", ctx)
        marks = doc["content"][0]["content"][1]["marks"]
        self.assertEqual(marks[0]["type"], "link")
        self.assertIn("aaaa-bbbb", marks[0]["attrs"]["href"])

    def test_block_anchor(self):
        full = "39cf9854-d27a-4132-a90a-3bf2053171fb"
        ctx = dict(CTX, anchor_short_to_full={full[:8]: full})
        md = f"目標段落 ^{full[:8]}\n\n跳到 [[#^{full[:8]}|那段]]。\n"
        doc = md_to_pm(md, ctx)
        self.assertEqual(doc["content"][0]["attrs"]["id"], full)


class TestLossyReason(unittest.TestCase):
    def test_dialect_constructs_not_lossy(self):
        for node in (
            {"type": "toggle_list_item", "attrs": {"id": "x", "folded": True},
             "content": []},
            {"type": "paragraph", "attrs": {"id": "x"}, "content": [
                {"type": "text", "marks": [{"type": "color",
                 "attrs": {"type": "text", "color": "red"}}], "text": "t"}]},
            {"type": "paragraph", "attrs": {"id": "x"}, "content": [
                {"type": "text", "marks": [{"type": "underline"}], "text": "t"}]},
        ):
            self.assertIsNone(md2pm.lossy_reason(node), node)

    def test_truly_lossy_constructs(self):
        for node in (
            {"type": "embed", "attrs": {"objectType": "highlightElement",
                                        "objectId": "x"}},
            {"type": "whiteboard", "attrs": {"whiteboardId": "x"}},
            {"type": "image", "attrs": {"width": 300, "alignment": "center"}},
            {"type": "paragraph", "attrs": {"id": "x"}, "content": [
                {"type": "text", "marks": [{"type": "highlight",
                 "attrs": {"color": "yellow"}}], "text": "t"}]},
        ):
            self.assertIsNotNone(md2pm.lossy_reason(node), node)


class TestBlockHelpers(unittest.TestCase):
    def test_split_blocks_fence_aware(self):
        text = "a\n\n```py\n\nx = 1\n\n```\n\nb\n"
        blocks = split_blocks(text)
        self.assertEqual(len(blocks), 3)
        self.assertIn("x = 1", blocks[1])

    def test_assemble_inverse_of_split(self):
        blocks = ["# h", "- a\n    - b", "尾段。"]
        self.assertEqual(split_blocks(assemble(blocks)), blocks)


if __name__ == "__main__":
    unittest.main()
