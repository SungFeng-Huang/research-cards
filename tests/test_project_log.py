"""project-card-log resolve_card precedence + create_project_card pinning."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      "..", "skills", "project-card-log", "resolve_card.py")
CREATE = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      "..", "skills", "project-card-log", "create_project_card.py")


def run_resolver(cwd, env_extra):
    env = dict(os.environ)
    env.pop("HB_PROJECT_CARD", None)
    env.pop("RESEARCH_CARDS_CONFIG", None)
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


class TestCreateProjectCard(unittest.TestCase):
    """Pin-location decision: git repo -> marker; plain project root whose
    git repos live one level down -> registry entry (a marker above a nested
    repo's git root would be invisible to the marker search)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hbcards-projcreate-"))
        cfg_dir = self.tmp / "cfg"
        cfg_dir.mkdir()
        (self.tmp / "Vault").mkdir()
        self.cfg = cfg_dir / "config.json"
        self.cfg.write_text(json.dumps({
            "backend": "obsidian",
            "obsidian": {"vault": str(self.tmp / "Vault")}}))
        self.env = {"HEPTABASE_CARDS_CONFIG": str(self.cfg)}
        self.reg = cfg_dir / "projects.json"
        self.proj = self.tmp / "my_proj_root"
        self.nested = self.proj / "some_repo"
        self.nested.mkdir(parents=True)

    def run_create(self, cwd, check=True):
        env = dict(os.environ)
        env.pop("HB_PROJECT_CARD", None)
        env.pop("RESEARCH_CARDS_CONFIG", None)
        env.update(self.env)
        r = subprocess.run([sys.executable, CREATE], cwd=cwd, env=env,
                           capture_output=True, text=True)
        if check:
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            return json.loads(r.stdout.splitlines()[-1])
        return r

    def test_registry_fallback_outside_git(self):
        out = self.run_create(self.proj)
        self.assertEqual(out["record"], "registry")
        reg = json.loads(self.reg.read_text())
        self.assertEqual(reg["projects"][0]["match_any"], ["my_proj_root"])
        self.assertEqual(reg["projects"][0]["card"], out["card"])
        self.assertFalse((self.proj / ".heptabase-card").exists())
        # a nested git repo then resolves via the registry path match
        subprocess.run(["git", "init", "-q", str(self.nested)], check=True)
        r = run_resolver(self.nested, self.env)
        self.assertEqual((r["card"], r["source"]), (out["card"], "registry"))

    def test_marker_inside_git(self):
        subprocess.run(["git", "init", "-q", str(self.nested)], check=True)
        out = self.run_create(self.nested)
        self.assertEqual(out["record"], "marker")
        self.assertTrue((self.nested / ".heptabase-card").is_file())
        self.assertFalse(self.reg.exists())

    def test_dry_run_reports_registry_without_writing(self):
        env = dict(os.environ)
        env.pop("RESEARCH_CARDS_CONFIG", None)
        env.update(self.env)
        r = subprocess.run([sys.executable, CREATE, "--dry-run"],
                           cwd=self.proj, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = json.loads(r.stdout.splitlines()[-1])
        self.assertEqual((out["dry_run"], out["record"]), (True, "registry"))
        self.assertFalse(self.reg.exists())
        self.assertEqual(list((self.tmp / "Vault").glob("**/*.md")), [])

    def test_registry_collision_fails_before_creating(self):
        self.reg.write_text(json.dumps({"projects": [
            {"card": "X", "title": "T", "match_any": ["my_proj_root"]}]}))
        r = self.run_create(self.proj, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("互撞", r.stderr + r.stdout)
        self.assertEqual(list((self.tmp / "Vault").glob("**/*.md")), [])


if __name__ == "__main__":
    unittest.main()
