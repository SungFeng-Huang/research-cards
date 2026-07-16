"""setup/check_config.py: upgrade-hint diff and load branches on fixtures."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
CHECK = os.path.join(REPO, "skills", "setup", "check_config.py")
sys.path.insert(0, os.path.join(REPO, "skills", "setup"))
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))


def run_check(cfg_path, *flags):
    env = {**os.environ, "RESEARCH_CARDS_CONFIG": str(cfg_path)}
    env.pop("HEPTABASE_CARDS_CONFIG", None)
    r = subprocess.run([sys.executable, CHECK, "--json", *flags],
                       capture_output=True, text=True, env=env)
    return r.returncode, json.loads(r.stdout)


class TestCheckConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc-test-setup-"))

    def test_missing_config_is_guidance_not_error(self):
        rc, out = run_check(self.tmp / "nope.json")
        self.assertEqual(rc, 0)
        self.assertFalse(out["exists"])
        self.assertTrue(any("setup" in w for w in out["warnings"]))

    def test_minimal_obsidian_config_loads(self):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"obsidian": {"vault": str(self.tmp)}}))
        rc, out = run_check(cfg)
        self.assertEqual(rc, 0)
        self.assertTrue(out["loads"])
        self.assertEqual(out["backend"], "obsidian")  # unset → default
        vault_check = next(c for c in out["checks"]
                           if c["name"] == "vault directory")
        self.assertTrue(vault_check["ok"])
        # a minimal config has plenty of documented opt-ins
        self.assertIn("profile", out["upgrade_hints"])

    def test_invalid_backend_reports_error(self):
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({"backend": "notion",
                                   "obsidian": {"vault": str(self.tmp)}}))
        rc, out = run_check(cfg)
        self.assertEqual(rc, 1)
        self.assertIn("backend", out["error"])

    def test_placeholder_ids_count_as_missing(self):
        # a config copied straight from the example still carries <...>
        # placeholders — the health check must not green-light them
        cfg = self.tmp / "config.json"
        cfg.write_text(json.dumps({
            "backend": "heptabase",
            "heptabase": {"workspace_id": "<your-heptabase-workspace-uuid>",
                          "collections": {"papers": {"tag_id": "<tag-uuid>"}}}}))
        rc, out = run_check(cfg)
        ws = next(c for c in out["checks"] if c["name"] == "heptabase.workspace_id")
        self.assertFalse(ws["ok"])
        cols = next(c for c in out["checks"] if c["name"] == "collections with tag_id")
        self.assertFalse(cols["ok"])

    def test_upgrade_hints_nested(self):
        import importlib
        import check_config as CC
        importlib.reload(CC)
        cfg = {"backend": "obsidian",
               "obsidian": {"vault": "/x"},
               "profile": {"reader": "r"}}
        example = {"$comment": "doc", "backend": "obsidian",
                   "profile": {"$comment": "doc", "reader": "", "language": ""},
                   "features": {"study": True}}
        hints = CC.upgrade_hints(cfg, example)
        self.assertIn("profile.language", hints)
        self.assertIn("features", hints)
        self.assertNotIn("backend", hints)
        self.assertNotIn("profile.$comment", hints)


if __name__ == "__main__":
    unittest.main()
