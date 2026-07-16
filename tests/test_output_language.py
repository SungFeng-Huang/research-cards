"""Output-language resolution (config profile.language → Claude Code
settings.json `language` → 繁體中文) and prompt-template formatting smoke.
No network, no vault — pure config plumbing."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))
sys.path.insert(0, os.path.join(REPO, "skills", "scholar-inbox-clip"))


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False))


class TestOutputLanguage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc-test-lang-"))
        self.cfg = self.tmp / "config.json"
        self.claude = self.tmp / "claude-settings.json"
        self._env = {k: os.environ.get(k) for k in
                     ("RESEARCH_CARDS_CONFIG", "HEPTABASE_CARDS_CONFIG",
                      "CLAUDE_SETTINGS_PATH")}
        os.environ["RESEARCH_CARDS_CONFIG"] = str(self.cfg)
        os.environ.pop("HEPTABASE_CARDS_CONFIG", None)
        # point at a guaranteed-missing file so the real ~/.claude/settings.json
        # never leaks into tests
        os.environ["CLAUDE_SETTINGS_PATH"] = str(self.tmp / "nope.json")
        for m in ("hbconfig",):
            sys.modules.pop(m, None)
        import hbconfig
        self.hb = hbconfig

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sys.modules.pop("hbconfig", None)

    def _cfg(self, language=None):
        prof = {"reader": "研究者", "field": "語音"}
        if language is not None:
            prof["language"] = language
        _write(self.cfg, {"backend": "obsidian",
                          "obsidian": {"vault": str(self.tmp)},
                          "profile": prof})

    def test_config_language_wins(self):
        self._cfg(language="日本語")
        _write(self.claude, {"language": "korean"})
        os.environ["CLAUDE_SETTINGS_PATH"] = str(self.claude)
        self.assertEqual(self.hb.output_language(), "日本語")

    def test_claude_settings_mapped(self):
        self._cfg()
        for raw, expect in [("chinese", "繁體中文"), ("japanese", "日本語"),
                            ("korean", "한국어"), ("english", "English"),
                            ("french", "french")]:
            _write(self.claude, {"language": raw})
            os.environ["CLAUDE_SETTINGS_PATH"] = str(self.claude)
            self.assertEqual(self.hb.output_language(), expect, raw)

    def test_default_traditional_chinese(self):
        self._cfg()  # no language key, no claude settings file
        self.assertEqual(self.hb.output_language(), "繁體中文")

    def test_missing_config_still_defaults(self):
        # config file absent entirely — resolution must not raise
        os.environ["RESEARCH_CARDS_CONFIG"] = str(self.tmp / "missing.json")
        self.assertEqual(self.hb.output_language(), "繁體中文")

    def test_struct_labels_follow_language(self):
        self._cfg(language="日本語")
        self.assertEqual(self.hb.struct_labels()["summary"], "クイックサマリー")
        self._cfg(language="简体中文")  # documented in config.example
        self.assertEqual(self.hb.struct_labels()["prereq_marker"], "先备知识")
        self._cfg(language="Deutsch")  # unknown language → English labels
        self.assertEqual(self.hb.struct_labels()["summary"], "Quick Summary")

    def test_marker_variants_cover_all_languages(self):
        self._cfg()
        ms = self.hb.marker_variants("prereq_marker")
        for m in ("先備知識", "Prerequisites", "前提知識", "선행 지식"):
            self.assertIn(m, ms)


class TestPromptTemplatesCarryLang(unittest.TestCase):
    """Every generation prompt template must format cleanly with lang= and
    must actually interpolate it (a template that silently dropped {lang}
    would regress to hardcoded Chinese)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rc-test-lang-run-"))
        cfg = cls.tmp / "config.json"
        _write(cfg, {"backend": "obsidian",
                     "obsidian": {"vault": str(cls.tmp)},
                     "profile": {"reader": "研究者", "field": "語音",
                                 "language": "日本語"}})
        cls._env = {k: os.environ.get(k) for k in
                    ("RESEARCH_CARDS_CONFIG", "HEPTABASE_CARDS_CONFIG",
                     "CLAUDE_SETTINGS_PATH")}
        os.environ["RESEARCH_CARDS_CONFIG"] = str(cfg)
        os.environ.pop("HEPTABASE_CARDS_CONFIG", None)
        os.environ["CLAUDE_SETTINGS_PATH"] = str(cls.tmp / "nope.json")
        for m in ("run", "hbconfig"):
            sys.modules.pop(m, None)
        global run
        import run  # noqa: F401

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in ("run", "hbconfig"):
            sys.modules.pop(m, None)

    def test_lang_helper_reads_config(self):
        self.assertEqual(run._lang(), "日本語")

    def test_summary_nodes_localized(self):
        nodes = run.build_summary_nodes(
            {"ai_summary": "a", "problems": [], "methods": [],
             "results": [], "takeaways": []})
        text = json.dumps(nodes, ensure_ascii=False)
        self.assertIn("クイックサマリー", text)
        self.assertNotIn("快速摘要", text)

    def test_all_templates_format_with_lang(self):
        lang = run._lang()
        prereq = run._hbconfig.struct_labels()["prereq_heading"]
        cases = [
            (run.TRANSLATE_PROMPT, dict(arxiv_id="2607.00001", content="x")),
            (run.TRANSLATE_PROMPT_WITH_IMAGES,
             dict(arxiv_id="2607.00001", content="x", max_images=4,
                  image_list="1. a")),
            (run.GENERATE_PROMPT, dict(content="x")),
            (run.COLORIZE_PROMPT, dict(content="x")),
            (run.TEACHING_TRANSLATE_PROMPT,
             dict(spec="s", reader="研究者", field="語音",
                  arxiv_id="2607.00001", content="x")),
            (run.TEACHING_TRANSLATE_PROMPT_WITH_IMAGES,
             dict(spec="s", reader="研究者", field="語音",
                  arxiv_id="2607.00001", content="x", max_images=4,
                  image_list="1. a")),
            (run.FIGURE_PLACE_PROMPT,
             dict(headings="- H", images="1. a")),
        ]
        for tpl, kw in cases:
            out = tpl.format(lang=lang, prereq_heading=prereq, **kw)
            self.assertIn(lang, out, "template dropped {lang}")
            self.assertNotIn("繁體中文", out,
                             "hardcoded Chinese survived in a template")


if __name__ == "__main__":
    unittest.main()
