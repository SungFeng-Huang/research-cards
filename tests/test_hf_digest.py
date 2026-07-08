"""HuggingFace Daily Papers source: detection, extraction, selection."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "skills", "scholar-inbox-clip"))

BODY = """Daily Papers
by AK and the AI research community
Here is the selection of papers for today (6 Jul):
Speech Foo: A Speech Model (140 ▲)
Vision Bar: An Image Model (35 ▲)
Audio Baz: An Audio Codec (2 ▲)
To view more checkout today's Daily Paper page.
"""

# quoted-printable 風格：連結被軟斷行切開、submit 連結必須被忽略
SOURCE = (
    'x <a href="https://huggingface.co/papers/2607.0=\n0001?utm">A</a> '
    'y <a href="https://huggingface.co/papers/2607.00002">B</a> '
    'dup <a href="https://huggingface.co/papers/2607.00001">A again</a> '
    'z <a href="https://huggingface.co/papers/2607.00003">C</a> '
    '<a href="https://huggingface.co/papers/submit?utm">submit</a>'
)


class TestHFDigest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="hbcards-hf-"))
        cls.cfg = cls.tmp / "config.json"
        cls._write_cfg({})
        os.environ["HEPTABASE_CARDS_CONFIG"] = str(cls.cfg)
        os.environ.pop("RESEARCH_CARDS_CONFIG", None)
        global run
        import run  # noqa: F401

    @classmethod
    def _write_cfg(cls, extra):
        cfg = {"backend": "obsidian",
               "obsidian": {"vault": str(cls.tmp)}}
        cfg.update(extra)
        cls.cfg.write_text(json.dumps(cfg, ensure_ascii=False))

    def setUp(self):
        self._write_cfg({})
        run._hbconfig.CONFIG_PATH = str(self.cfg)
        self._orig_call = run.call_claude

    def tearDown(self):
        run.call_claude = self._orig_call

    def test_is_hf_daily(self):
        self.assertTrue(run.is_hf_daily("Daily papers of 6 Jul 2026", SOURCE))
        self.assertFalse(run.is_hf_daily("Daily papers of 6 Jul 2026", "no links"))
        self.assertFalse(run.is_hf_daily("📣 Scholar Alert Digest 03/07", SOURCE))
        self.assertFalse(
            run.is_hf_daily("[Hugging Face] Click this link to confirm", SOURCE))

    def test_extract_pairs_ids_with_titles(self):
        papers = run.extract_hf_papers(BODY, SOURCE)
        self.assertEqual([p["id"] for p in papers],
                         ["2607.00001", "2607.00002", "2607.00003"])
        self.assertEqual(papers[0],
                         {"id": "2607.00001", "title": "Speech Foo: A Speech Model",
                          "upvotes": 140})
        self.assertEqual(papers[2]["upvotes"], 2)

    def test_upvote_threshold(self):
        self._write_cfg({"email": {"hf_min_upvotes": 10}})
        run.call_claude = lambda *a, **k: self.fail("不該呼叫 agent（無 field）")
        papers = run.extract_hf_papers(BODY, SOURCE)
        sel = run.select_hf_papers(papers)
        self.assertEqual([p["id"] for p in sel], ["2607.00001", "2607.00002"])

    def test_field_selection_subset(self):
        self._write_cfg({"profile": {"field": "語音"}})
        run.call_claude = lambda *a, **k: "2607.00001\n2607.00003\n"
        sel = run.select_hf_papers(run.extract_hf_papers(BODY, SOURCE))
        self.assertEqual([p["id"] for p in sel], ["2607.00001", "2607.00003"])

    def test_field_selection_none(self):
        self._write_cfg({"profile": {"field": "語音"}})
        run.call_claude = lambda *a, **k: "NONE"
        self.assertEqual(run.select_hf_papers(
            run.extract_hf_papers(BODY, SOURCE)), [])

    def test_interests_only_selection(self):
        self._write_cfg({"email": {"topics_of_interest":
                                   ["LLM / Foundation Model", "Agentic AI"]}})
        seen = {}
        def fake(prompt, **k):
            seen["prompt"] = prompt
            return "2607.00002"
        run.call_claude = fake
        sel = run.select_hf_papers(run.extract_hf_papers(BODY, SOURCE))
        self.assertEqual([p["id"] for p in sel], ["2607.00002"])
        self.assertIn("LLM / Foundation Model", seen["prompt"])
        self.assertNotIn("領域直接相關", seen["prompt"])  # 無 field 就不出現該條件

    def test_field_plus_interests_both_in_prompt(self):
        self._write_cfg({"profile": {"field": "語音"},
                         "email": {"topics_of_interest": ["Agentic AI"]}})
        seen = {}
        def fake(prompt, **k):
            seen["prompt"] = prompt
            return "NONE"
        run.call_claude = fake
        self.assertEqual(run.select_hf_papers(
            run.extract_hf_papers(BODY, SOURCE)), [])
        self.assertIn("語音", seen["prompt"])
        self.assertIn("Agentic AI", seen["prompt"])

    def test_field_selection_failure_keeps_all(self):
        self._write_cfg({"profile": {"field": "語音"}})
        run.call_claude = lambda *a, **k: None
        sel = run.select_hf_papers(run.extract_hf_papers(BODY, SOURCE))
        self.assertEqual(len(sel), 3)

    def test_subject_only_detection_split(self):
        # 主旨符合但 source 空（讀取失敗）→ is_hf_daily False、
        # is_hf_daily_subject True——呼叫端據此跳過不標記，不走通用路徑
        self.assertTrue(run.is_hf_daily_subject("Daily papers of 6 Jul 2026"))
        self.assertFalse(run.is_hf_daily("Daily papers of 6 Jul 2026", ""))
        self.assertFalse(run.is_hf_daily_subject("Scholar Alert Digest"))

    def test_count_mismatch_uses_anchor_text_not_positional(self):
        # 標題行少一行（缺 Vision Bar）——位置配對會整條鏈錯位；
        # 改抓 anchor text 後各 id 拿到自己的標題、缺讚數標 None
        body = ("Speech Foo: A Speech Model (140 ▲)\n"
                "Audio Baz: An Audio Codec (2 ▲)\n")
        src = ('<a href="https://huggingface.co/papers/2607.00001">'
               'Speech Foo: A Speech Model</a> '
               '<a href="https://huggingface.co/papers/2607.00002">'
               'Vision Bar: An Image Model</a> '
               '<a href="https://huggingface.co/papers/2607.00003">'
               'Audio Baz: An Audio Codec</a>')
        papers = run.extract_hf_papers(body, src)
        by_id = {p["id"]: p for p in papers}
        self.assertEqual(by_id["2607.00003"]["title"],
                         "Audio Baz: An Audio Codec")
        self.assertEqual(by_id["2607.00003"]["upvotes"], 2)   # 標題對回讚數
        self.assertEqual(by_id["2607.00002"]["upvotes"], None)  # body 沒這行
        # 絕不把 Vision Bar 的 metadata 錯配給 Audio Baz（舊行為）
        self.assertNotEqual(by_id["2607.00002"]["title"],
                            by_id["2607.00003"]["title"])

    def test_unknown_upvotes_pass_threshold(self):
        self._write_cfg({"email": {"hf_min_upvotes": 100}})
        run.call_claude = lambda *a, **k: self.fail("不該呼叫 agent")
        papers = [{"id": "2607.00001", "title": "A", "upvotes": 140},
                  {"id": "2607.00002", "title": "B", "upvotes": None},
                  {"id": "2607.00003", "title": "C", "upvotes": 2}]
        sel = run.select_hf_papers(papers)
        self.assertEqual([p["id"] for p in sel],
                         ["2607.00001", "2607.00002"])       # unknown 放行

    def test_garbage_reply_keeps_all_not_zero(self):
        # 非空但無候選 ID 也無 NONE 的壞回覆 ≠「零篇相關」——保守全收，
        # 否則整封信被誤標已處理而永久漏收
        self._write_cfg({"profile": {"field": "語音"}})
        run.call_claude = lambda *a, **k: "Agent unavailable, try again later"
        sel = run.select_hf_papers(run.extract_hf_papers(BODY, SOURCE))
        self.assertEqual(len(sel), 3)
        # 回覆只含榜外 ID → 同樣當壞回覆
        run.call_claude = lambda *a, **k: "9999.99999"
        sel = run.select_hf_papers(run.extract_hf_papers(BODY, SOURCE))
        self.assertEqual(len(sel), 3)

    def test_call_exception_keeps_all(self):
        self._write_cfg({"profile": {"field": "語音"}})
        def boom(*a, **k):
            raise TimeoutError("CLI timeout")
        run.call_claude = boom
        sel = run.select_hf_papers(run.extract_hf_papers(BODY, SOURCE))
        self.assertEqual(len(sel), 3)                         # 不中止整批

    def test_norm_title_strips_h1_and_prefix(self):
        # 呼叫端餵的是 H1 行——「# [alphaXiv] Title」必須與既有卡標題
        # 「[alphaXiv] Title」/「Title」正規化相等，否則標題去重永遠失效
        want = run._norm_title("Foo: A Bar — Baz")
        self.assertEqual(run._norm_title("# [alphaXiv] Foo: A Bar — Baz"), want)
        self.assertEqual(run._norm_title("[alphaXiv] Foo, a bar? Baz"), want)
        self.assertNotEqual(run._norm_title("# [alphaXiv] Other"), want)

    def test_title_duplicate_obsidian_punctuation_immune(self):
        # Obsidian 走全量標題掃描——標點差異不再擋在 substring 搜尋階段
        vault = Path(tempfile.mkdtemp(prefix="hbcards-dedup-"))
        (vault / "Papers").mkdir()
        # Obsidian 標題＝檔名（無 冒號 等非法字元）——正是兩邊標點會不同的
        # 現實來源；正規化等值必須跨得過去
        (vault / "Papers" / "[alphaXiv] Foo — A Bar Baz.md").write_text(
            "body\n")
        self._write_cfg({"backend": "obsidian",
                         "obsidian": {"vault": str(vault),
                                      "folders": {"papers": "Papers"}}})
        import importlib
        importlib.reload(run)
        try:
            self.assertTrue(run.title_duplicate("# [alphaXiv] Foo: a bar Baz"))
            self.assertFalse(run.title_duplicate("# [alphaXiv] Different"))
        finally:
            self._write_cfg({})
            importlib.reload(run)

    def test_untitled_papers_bypass_agent_filter(self):
        self._write_cfg({"profile": {"field": "語音"}})
        run.call_claude = lambda *a, **k: "2607.00001"
        papers = [{"id": "2607.00001", "title": "Speech Foo", "upvotes": 140},
                  {"id": "2607.00002", "title": "", "upvotes": None}]
        sel = run.select_hf_papers(papers)
        self.assertEqual([p["id"] for p in sel],
                         ["2607.00001", "2607.00002"])       # 無標題不由 agent 淘汰


if __name__ == "__main__":
    unittest.main()
