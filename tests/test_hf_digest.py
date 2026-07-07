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


if __name__ == "__main__":
    unittest.main()
