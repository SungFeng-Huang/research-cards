"""project-card-cleanup pure logic: section extraction (fullwidth-tolerant),
emit()'s dump→builder conversion incl. the chain-plumbing HARD FILTER, and
verify_content inventory. merge_lib is imported for real (pure builders);
no card I/O."""
import os
import sys
import unittest

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))
sys.path.insert(0, os.path.join(REPO, "skills", "card-rewrite"))
sys.path.insert(0, os.path.join(REPO, "skills", "project-card-cleanup"))

import cleanup_lib as CL  # noqa: E402

UUID = "12345678-1234-1234-1234-123456789abc"


def flat_text(nodes):
    out = []
    for n in nodes:
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text", ""))
            out.append(flat_text(n.get("content") or []))
    return "".join(out)


class TestSection(unittest.TestCase):
    DUMP = ("## 現狀（最新）\n\nA 段。\n\n## 實驗統整\n\n數字表。\n\n"
            "### 子節\n\n內文。\n\n## 待補\n\n尾。\n")

    def test_extracts_body_until_next_same_level(self):
        body = CL.section(self.DUMP, "實驗統整")
        self.assertIn("數字表", body)
        self.assertIn("子節", body)          # deeper headings stay inside
        self.assertNotIn("待補", body)

    def test_fullwidth_tolerance(self):
        # halfwidth prefix finds the fullwidth heading
        body = CL.section(self.DUMP, "現狀(最新)")
        self.assertIn("A 段", body)
        with self.assertRaises(AssertionError):
            CL.section(self.DUMP, "不存在的段")


class TestEmit(unittest.TestCase):
    def test_tables_cardlinks_bullets_headings(self):
        C = []
        CL.emit(C, ("### 小節\n\n| a | b |\n| 1 | 2 |\n\n"
                    f"[[card:{UUID}]]\n\n• 點一\n一般段。\n"))
        types = [n.get("type") for n in C]
        self.assertIn("heading", types)
        self.assertIn("table", types)
        self.assertIn("paragraph", types)
        inv = CL.verify_content(C)
        self.assertEqual(inv["card_links"], 1)
        self.assertEqual(inv["tables"], 1)

    def test_hard_filter_drops_chain_plumbing(self):
        C = []
        CL.emit(C, (f"▶ 續卡（本卡已達容量上限）：[[card:{UUID}]]\n"
                    f"（軸卡 的續卡 2／merge 溢位；母卡：[[card:{UUID}]]。）\n"
                    "真內容留下。\n"))
        inv = CL.verify_content(C)
        self.assertEqual(inv["card_links"], 0)   # plumbing never carried
        text = flat_text(C)
        self.assertIn("真內容留下", text)
        self.assertNotIn("續卡", text)

    def test_section_heading_tail_not_leaked(self):
        body = CL.section(self.DUMP if hasattr(self, "DUMP") else
                          "## 現狀（最新）\n\nA 段。\n", "現狀")
        self.assertTrue(body.lstrip().startswith("A 段"))
        self.assertNotIn("（最新）", body)

    def test_hard_filter_spares_prose_mentioning_sentinel_words(self):
        C = []
        CL.emit(C, "• 若失敗，▶ 續卡實驗流程照舊。\n")
        self.assertIn("續卡實驗流程", flat_text(C))   # prose survives

    def test_repl_applies_before_parsing(self):
        C = []
        CL.emit(C, "舊數字 0.71。\n", repl=(("0.71", "0.87"),))
        self.assertIn("0.87", flat_text(C))
        self.assertNotIn("0.71", flat_text(C))


if __name__ == "__main__":
    unittest.main()
