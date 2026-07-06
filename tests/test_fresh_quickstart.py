"""D14: the README Obsidian-only quickstart, replayed on a fresh $HOME.

Simulates a brand-new machine (fresh HOME isolates config/state; the test
interpreter's site-packages are passed through — a real user installs deps
per the README). Covers: filled example config -> first card with Tasks ->
hub/topic creation -> topology refresh -> topic discovery -> placeholder
ids error out with the exact config key.
"""
import json
import os
import site
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def sh(code, home, extra_env=None):
    env = dict(os.environ, HOME=str(home),
               PYTHONPATH=site.getusersitepackages())
    env.pop("HEPTABASE_CARDS_CONFIG", None)
    env.pop("RESEARCH_CARDS_CONFIG", None)
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, "-c", code], env=env,
                       capture_output=True, text=True)
    return r


class TestFreshQuickstart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp(prefix="hbcards-fresh-"))
        (cls.home / "MyVault").mkdir()
        cfg = json.load(open(REPO / "config.example.json"))
        cfg["backend"] = "obsidian"
        cfg["plugin_root"] = str(REPO)
        cfg["profile"] = {"reader": "測試讀者", "field": "測試領域"}
        cfg["obsidian"]["vault"] = str(cls.home / "MyVault")
        cfg_dir = cls.home / ".config" / "research-cards"
        cfg_dir.mkdir(parents=True)
        json.dump(cfg, open(cfg_dir / "config.json", "w"), ensure_ascii=False)

    def run_step(self, code):
        r = sh(code, self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return r.stdout

    def test_1_first_card_with_tasks(self):
        out = self.run_step(f"""
import sys; sys.path.insert(0, r"{REPO}/skills/scholar-inbox-clip")
import run
cid = run.create_card("# [alphaXiv] Fresh QS Paper\\n\\n## 1. 背景\\n\\n內文。\\n")
run.set_arxiv_property(cid, "2599.00001"); run.set_source_type(cid)
run.set_tasks(cid, ["MyTask"])
assert run.current_tasks(cid) == ["MyTask"], run.current_tasks(cid)
assert "/.config/research-cards/" in run.STATE_FILE
print(cid)
""")
        self.assertIn("Papers/Fresh QS Paper", out)

    def test_2_topic_flow(self):
        # user copies the template, fills it, creates hub+comparison cards
        tdir = self.home / ".config/research-cards/topics/my-topic"
        tdir.mkdir(parents=True, exist_ok=True)
        tpl = open(REPO / "skills/overview/topics/_example/config.py").read()
        tpl = tpl.replace('"<comparison-card-id>"', '"Overviews/QS 比較"') \
                 .replace('"<card title>"', '"QS 比較"') \
                 .replace('"<one-paragraph intro>"', '"intro"')
        open(tdir / "config.py", "w").write(tpl)
        self.run_step(f"""
import sys; sys.path.insert(0, r"{REPO}/skills/_shared")
from backend import get_backend
be = get_backend()
be.create_card("overviews", "QS 比較",
               "## 各論文簡介\\n\\n### Fresh QS Paper（2599.00001）\\n\\n[[Fresh QS Paper]]\\n",
               {{"Level": "3"}})
be.create_card("overviews", "QS 總覽",
               "## 子卡與閱讀順序\\n\\n- [[QS 比較]]　比較卡\\n",
               {{"Tasks": ["MyTask"], "Level": "2"}})
""")
        cfgp = self.home / ".config/research-cards/config.json"
        cfg = json.load(open(cfgp))
        cfg["obsidian"]["graph"]["hubs"] = {"my-topic": "Overviews/QS 總覽"}
        json.dump(cfg, open(cfgp, "w"), ensure_ascii=False)

        r = sh(f"import runpy, sys; sys.argv=['t','refresh','my-topic']; "
               f"runpy.run_path(r'{REPO}/skills/_shared/topology.py', run_name='__main__')",
               self.home)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertIn("my-topic: own=1", r.stdout)
        snap = json.load(open(self.home / ".config/research-cards/topics/my-topic/topic_snapshot.json"))
        self.assertEqual(snap["task_values"], ["MyTask"])

        out = self.run_step(f"""
import sys, os
sys.path.insert(0, r"{REPO}/skills/overview"); sys.path.insert(0, r"{REPO}/skills/_shared")
import sync_overview as SO
print(SO.TOPIC_KEYS)
""")
        self.assertIn("my-topic", out)

    def test_3_placeholder_ids_error_clearly(self):
        cfgp = self.home / ".config/research-cards/hb.json"
        cfg = json.load(open(self.home / ".config/research-cards/config.json"))
        cfg["backend"] = "heptabase"
        json.dump(cfg, open(cfgp, "w"), ensure_ascii=False)
        r = sh(f"""
import sys; sys.path.insert(0, r"{REPO}/skills/scholar-inbox-clip")
import run
run.tag_card('x')
""", self.home, {"HEPTABASE_CARDS_CONFIG": str(cfgp)})
        self.assertNotEqual(r.returncode, 0)
        combined = r.stderr + r.stdout
        self.assertIn("heptabase.collections.papers.tag_id", combined)


if __name__ == "__main__":
    unittest.main()
