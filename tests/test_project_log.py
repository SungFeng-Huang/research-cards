"""project-card-log resolve_card precedence on a temp layout."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      "..", "skills", "project-card-log", "resolve_card.py")


def run_resolver(cwd, env_extra):
    env = dict(os.environ)
    env.pop("HB_PROJECT_CARD", None)
    env.update(env_extra)
    out = subprocess.run([sys.executable, SCRIPT], cwd=cwd, env=env,
                         capture_output=True, text=True)
    return json.loads(out.stdout)


class TestResolveCard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hbcards-projlog-"))
        cfg_dir = self.tmp / "cfg"
        cfg_dir.mkdir()
        self.cfg = cfg_dir / "config.json"
        self.cfg.write_text(json.dumps({"backend": "heptabase"}))
        (cfg_dir / "projects.json").write_text(json.dumps({
            "projects": [{"card": "REG-CARD", "title": "P",
                          "match_any": ["myproj_dir"]}]}))
        self.repo = self.tmp / "myproj_dir"
        self.repo.mkdir()
        self.env = {"HEPTABASE_CARDS_CONFIG": str(self.cfg)}

    def test_env_wins(self):
        r = run_resolver(self.repo, dict(self.env, HB_PROJECT_CARD="ENV-CARD"))
        self.assertEqual((r["card"], r["source"]), ("ENV-CARD", "env"))

    def test_marker_beats_registry(self):
        (self.repo / ".heptabase-card").write_text("card: MARK-CARD\n")
        r = run_resolver(self.repo, self.env)
        self.assertEqual((r["card"], r["source"]), ("MARK-CARD", "marker"))

    def test_registry_from_config_dir(self):
        r = run_resolver(self.repo, self.env)
        self.assertEqual((r["card"], r["source"]), ("REG-CARD", "registry"))

    def test_marker_search_stops_at_git_root(self):
        # parent dir has a marker, but the nested git repo must NOT see it
        (self.tmp / ".heptabase-card").write_text("card: PARENT-CARD\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        r = run_resolver(self.repo, self.env)
        self.assertNotEqual(r.get("card"), "PARENT-CARD")
        self.assertEqual((r["card"], r["source"]), ("REG-CARD", "registry"))

    def test_feature_toggle_disables(self):
        self.cfg.write_text(json.dumps({"backend": "heptabase",
                                        "features": {"project": False}}))
        r = run_resolver(self.repo, self.env)
        self.assertEqual(r["source"], "disabled")


if __name__ == "__main__":
    unittest.main()
