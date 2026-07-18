"""repair_chain.py pure logic: sentinel detection + stranded-markdown
normalization. No card I/O."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))
sys.path.insert(0, os.path.join(REPO, "skills", "card-rewrite"))
sys.path.insert(0, os.path.join(REPO, "skills", "project-card-log"))

UUID = "12345678-1234-1234-1234-123456789abc"


def _para(*content):
    return {"type": "paragraph", "attrs": {"id": None}, "content": list(content)}


def _t(s, **marks):
    n = {"type": "text", "text": s}
    if marks:
        n["marks"] = [{"type": k} for k in marks]
    return n


def _card(cid):
    return {"type": "card", "attrs": {"cardId": cid}}


class TestSentinelDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rc-test-repair-"))
        cfg = cls.tmp / "config.json"
        cfg.write_text(json.dumps({"backend": "obsidian",
                                   "obsidian": {"vault": str(cls.tmp)}}))
        cls._env = os.environ.get("RESEARCH_CARDS_CONFIG")
        os.environ["RESEARCH_CARDS_CONFIG"] = str(cfg)
        for m in ("repair_chain", "append_card", "rewrite_lib", "hbconfig"):
            sys.modules.pop(m, None)
        global RC, AC
        import repair_chain as RC
        import append_card as AC

    @classmethod
    def tearDownClass(cls):
        if cls._env is None:
            os.environ.pop("RESEARCH_CARDS_CONFIG", None)
        else:
            os.environ["RESEARCH_CARDS_CONFIG"] = cls._env

    def _sentinel(self, cid=UUID):
        return _para(_t("▶ "), _t(AC.LINK_MARK, strong=True), _t("："), _card(cid))

    def test_no_sentinel(self):
        nodes = [_para(_t("hello")), _para(_t("world"))]
        self.assertIsNone(RC.last_sentinel_idx(nodes))

    def test_sentinel_last_is_clean(self):
        nodes = [_para(_t("body")), self._sentinel()]
        self.assertEqual(RC.last_sentinel_idx(nodes), 1)

    def test_mention_without_card_link_not_sentinel(self):
        # prose that merely quotes the sentinel wording must not count
        nodes = [_para(_t(f"關於{AC.LINK_MARK}的說明")), _para(_t("tail content"))]
        self.assertIsNone(RC.last_sentinel_idx(nodes))

    def test_card_link_before_marker_not_sentinel(self):
        # a card link that PRECEDES the marker text is prose, not a sentinel
        # (review P2: the link must come after the marker, like merge_lib)
        nodes = [self._sentinel(),
                 _para(_card(UUID), _t(f"這卡談到{AC.LINK_MARK}的機制"))]
        self.assertEqual(RC.last_sentinel_idx(nodes), 0)

    def test_multiple_sentinels_take_last(self):
        nodes = [self._sentinel("11111111-1111-1111-1111-111111111111"),
                 _para(_t("mid")),
                 self._sentinel(UUID),
                 _para(_t("stranded"))]
        self.assertEqual(RC.last_sentinel_idx(nodes), 2)

    def test_seal_converts_text_sentinel(self):
        # a bridge/CLI spill writes the sentinel as plain text — seal must
        # rebuild it into the canonical form with a REAL card node
        n = _para(_t("▶ "), _t(AC.LINK_MARK, strong=True),
                  _t(f"：[[card:{UUID}]]"))
        nodes = [_para(_t("body")), n]
        self.assertIsNone(RC.last_sentinel_idx(nodes))  # invisible before seal
        self.assertEqual(AC.seal_sentinel_paragraphs(nodes), 1)
        self.assertEqual(RC.last_sentinel_idx(nodes), 1)  # visible after
        self.assertEqual(RC._sentinel_child(nodes[1]), UUID)

    def test_seal_ignores_prose_and_real_sentinels(self):
        real = self._sentinel()
        prose = _para(_t(f"內文提到 [[card:{UUID}]] 但不是 sentinel"))
        nodes = [real, prose]
        self.assertEqual(AC.seal_sentinel_paragraphs(nodes), 0)

    def test_seal_ignores_card_literal_before_marker(self):
        # review P2: "[[card:x]] … LINK_MARK" prose must NOT be sealed —
        # the literal has to come AFTER the marker to count
        n = _para(_t(f"[[card:{UUID}]] 這段 prose 提到{AC.LINK_MARK}的機制"))
        self.assertEqual(AC.seal_sentinel_paragraphs([n]), 0)

    def test_seal_child_id_filter(self):
        other = "99999999-9999-4999-8999-999999999999"
        n = _para(_t(AC.LINK_MARK + f"：[[card:{UUID}]]"))
        self.assertEqual(AC.seal_sentinel_paragraphs([n], child_id=other), 0)
        self.assertEqual(AC.seal_sentinel_paragraphs([n], child_id=UUID), 1)

    def test_seal_backref_splits_text_keeping_prose(self):
        # child_header writes 「（<title> 的續卡 N…；母卡：[[card:entry]]。…）」
        # as ONE text node — seal must split it into text + card + text,
        # keeping the surrounding prose intact
        n = _para(_t(f"（軸卡 的續卡 2／append 溢位；母卡：[[card:{UUID}]]。"
                     "整併請用 project-card-merge。）"))
        self.assertEqual(AC.seal_backref_paragraphs([n], UUID), 1)
        kids = n["content"]
        self.assertEqual([k["type"] for k in kids], ["text", "card", "text"])
        self.assertEqual(kids[1]["attrs"]["cardId"], UUID)
        self.assertTrue(kids[0]["text"].endswith("母卡："))
        self.assertTrue(kids[2]["text"].startswith("。整併請用"))
        # idempotent: a card node is present now
        self.assertEqual(AC.seal_backref_paragraphs([n], UUID), 0)

    def test_seal_backref_never_touches_prose(self):
        # review P2: user prose merely QUOTING [[card:id]] must not be
        # rewritten — the BACKREF_MARK must precede the literal
        p1 = _para(_t(f"筆記正文引用了 [[card:{UUID}]] 這個寫法"))
        self.assertEqual(AC.seal_backref_paragraphs([p1], UUID), 0)
        p2 = _para(_t(f"[[card:{UUID}]] 之後才提到母卡：如何如何"))
        self.assertEqual(AC.seal_backref_paragraphs([p2], UUID), 0)
        # and only the FIRST back-ref paragraph seals (a card has one)
        a = _para(_t(f"母卡：[[card:{UUID}]]。"))
        b = _para(_t(f"母卡：[[card:{UUID}]]。"))
        self.assertEqual(AC.seal_backref_paragraphs([a, b], UUID), 1)
        self.assertEqual([k["type"] for k in b["content"]], ["text"])

    def test_seal_backref_filters_and_boundaries(self):
        other = "99999999-9999-4999-8999-999999999999"
        n = _para(_t(f"母卡：[[card:{UUID}]]。"))
        self.assertEqual(AC.seal_backref_paragraphs([n], other), 0)  # id filter
        # sentinel paragraphs belong to seal_sentinel_paragraphs, not here
        s = _para(_t(AC.LINK_MARK + f"：[[card:{UUID}]]"))
        self.assertEqual(AC.seal_backref_paragraphs([s], UUID), 0)
        # marks on the original text survive on both split halves
        m = _para(_t(f"母卡：[[card:{UUID}]] 完", strong=True))
        self.assertEqual(AC.seal_backref_paragraphs([m], UUID), 1)
        self.assertEqual(m["content"][0].get("marks"),
                         [{"type": "strong"}])
        self.assertEqual(m["content"][2].get("marks"),
                         [{"type": "strong"}])

    def test_stranded_markdown_normalizes_card_links(self):
        stranded = [_para(_t("見："), _card(UUID))]
        md = RC.stranded_to_markdown(stranded, "entry-id")
        self.assertIn(f"[[card:{UUID}]]", md)
        self.assertNotIn("%%HEPTA-CARD", md)


if __name__ == "__main__":
    unittest.main()
