"""note-sync dispatcher pure logic: plan derivation and the fatal gate.
Engines are exercised by their own suites; the dispatcher's subprocess
plumbing was verified live (dry-run)."""
import importlib.util
import os
import sys
import unittest

REPO = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
sys.path.insert(0, os.path.join(REPO, "skills", "_shared"))

spec = importlib.util.spec_from_file_location(
    "note_sync_under_test",
    os.path.join(REPO, "skills", "note-sync", "sync.py"))
NS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(NS)


class TestNoteSync(unittest.TestCase):
    def test_plan_from_backends(self):
        self.assertEqual(
            NS.plan_from_config({"backends": ["heptabase", "local", "hackmd"]}),
            ["obsidian", "hackmd"])
        self.assertEqual(NS.plan_from_config({"backends": ["local", "hackmd"]}),
                         ["hackmd"])
        self.assertEqual(
            NS.plan_from_config({"backends": ["heptabase", "local"]}),
            ["obsidian"])
        self.assertEqual(NS.plan_from_config({"backends": ["local"]}), [])

    def test_fatal_gate(self):
        self.assertTrue(NS.is_fatal({"rc": 1, "report": {}}))
        self.assertTrue(NS.is_fatal({"rc": 0, "report": {"aborted": "429"}}))
        # per-card errors are self-healing — NOT fatal
        self.assertFalse(NS.is_fatal({"rc": 0, "report":
                                      {"errors": [{"card": "x"}]}}))
        self.assertFalse(NS.is_fatal({"rc": 0, "report": {"aborted": None}}))


if __name__ == "__main__":
    unittest.main()
