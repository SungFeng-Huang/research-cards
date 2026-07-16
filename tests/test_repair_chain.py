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

    def test_stranded_markdown_normalizes_card_links(self):
        stranded = [_para(_t("見："), _card(UUID))]
        md = RC.stranded_to_markdown(stranded, "entry-id")
        self.assertIn(f"[[card:{UUID}]]", md)
        self.assertNotIn("%%HEPTA-CARD", md)


if __name__ == "__main__":
    unittest.main()
