"""backends list model (0.30.0): normalization of the new list syntax and
the legacy single-value "backend" key, alias handling, and the guard
rails. No network, temp configs only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))


import hbconfig


def load_cfg(payload, vault=None):
    tmp = Path(tempfile.mkdtemp(prefix="rc-test-backends-"))
    if vault is None:
        vault = tmp / "vault"
        vault.mkdir()
    payload.setdefault("obsidian", {"vault": str(vault)})
    p = tmp / "config.json"
    p.write_text(json.dumps(payload, ensure_ascii=False))
    # patch the module-level path instead of reloading: a reload would mint
    # a NEW ConfigError class and break assertRaises identity
    old_path = hbconfig.CONFIG_PATH
    hbconfig.CONFIG_PATH = str(p)
    try:
        return hbconfig.load_config(), hbconfig
    finally:
        hbconfig.CONFIG_PATH = old_path


HEPTA = {"workspace_id": "w", "collections": {"papers": {"tag_id": "t"}}}


class TestBackendsList(unittest.TestCase):
    def test_legacy_values_map_to_lists(self):
        cfg, _ = load_cfg({"backend": "obsidian"})
        self.assertEqual(cfg["backends"], ["local"])
        self.assertEqual(cfg["backend"], "obsidian")
        cfg, _ = load_cfg({"backend": "heptabase", "heptabase": HEPTA})
        self.assertEqual(cfg["backends"], ["heptabase"])
        cfg, _ = load_cfg({"backend": "both", "heptabase": HEPTA})
        self.assertEqual(cfg["backends"], ["heptabase", "local"])
        self.assertEqual(cfg["backend"], "both")

    def test_unset_defaults_to_local(self):
        cfg, _ = load_cfg({})
        self.assertEqual(cfg["backends"], ["local"])
        self.assertEqual(cfg["backend"], "obsidian")

    def test_explicit_list_and_alias_and_dedupe(self):
        cfg, _ = load_cfg({"backends": ["obsidian"]})
        self.assertEqual(cfg["backends"], ["local"])
        cfg, _ = load_cfg({"backends": ["local", "obsidian"]})
        self.assertEqual(cfg["backends"], ["local"])
        cfg, _ = load_cfg({"backends": ["heptabase", "local", "hackmd"],
                           "heptabase": HEPTA})
        self.assertEqual(cfg["backend"], "both")

    def test_legacy_infers_hackmd_from_collections(self):
        cfg, _ = load_cfg({"backend": "obsidian",
                           "hackmd": {"collections": {"overviews": {}}}})
        self.assertIn("hackmd", cfg["backends"])

    def test_explicit_list_is_taken_at_face_value(self):
        cfg, _ = load_cfg({"backends": ["local"],
                           "hackmd": {"collections": {"overviews": {}}}})
        self.assertNotIn("hackmd", cfg["backends"])

    def test_guard_rails(self):
        _, hb = load_cfg({})
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backends": ["hackmd", "local"]})     # hackmd canonical
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backends": ["local", "heptabase"],   # unsupported order
                      "heptabase": HEPTA})
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backends": ["notion"]})              # unknown value
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backends": []})                      # empty list
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backends": "local"})                 # not a list
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backend": "vault"})                  # bad legacy value

    def test_heptabase_requirements_still_enforced(self):
        _, hb = load_cfg({})
        with self.assertRaises(hb.ConfigError):
            load_cfg({"backends": ["heptabase", "local"]})  # no workspace_id


if __name__ == "__main__":
    unittest.main()
