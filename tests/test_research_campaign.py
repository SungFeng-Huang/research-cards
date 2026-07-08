"""research-campaign: scaffold, ledger schema, status math."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..",
                      "skills", "research-campaign", "scripts", "campaign.py")


def run(args, cwd=None, ok=True):
    env = dict(os.environ)
    env.pop("RESEARCH_CARDS_CONFIG", None)
    env.pop("HEPTABASE_CARDS_CONFIG", None)
    r = subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd, env=env,
                       capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stderr[-400:]
    return r


class TestCampaign(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="hbcards-campaign-"))
        self.root = self.repo / "runs" / "auto_research"

    def test_init_scaffolds_and_refuses_overwrite(self):
        out = json.loads(run(["init", "--repo", str(self.repo),
                              "--rungs", "E0", "E1"]).stdout)
        self.assertTrue((self.root / "MISSION.md").is_file())
        self.assertIn("FIXED GOAL", (self.root / "MISSION.md").read_text())
        q = json.loads((self.root / "queue.json").read_text())
        self.assertEqual([e["id"] for e in q["experiments"]], ["E0", "E1"])
        self.assertTrue((self.root / "ledger.jsonl").exists())
        self.assertEqual(out["rungs"], ["E0", "E1"])
        r = run(["init", "--repo", str(self.repo)], ok=False)
        self.assertNotEqual(r.returncode, 0)          # 不覆蓋既有任務書
        self.assertIn("不覆蓋", r.stderr)

    def test_ledger_schema_enforced(self):
        run(["init", "--repo", str(self.repo)])
        good = {"experiment": "E1", "config_hash": "abc", "metrics": {"wer": 0.3},
                "significant": True, "decision": "advance",
                "playbook_rules_cited": ["speech.whisper.lr"]}
        run(["ledger-append", "--dir", str(self.root), "--json", json.dumps(good)])
        rows = [json.loads(l) for l in (self.root / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(rows[0]["experiment"], "E1")
        # 缺必要欄位 → 拒收
        bad = {"experiment": "E2", "metrics": {}, "significant": False}
        r = run(["ledger-append", "--dir", str(self.root),
                 "--json", json.dumps(bad)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("config_hash", r.stderr)
        # significant 非布林 → 拒收
        bad2 = dict(good, significant="yes")
        r = run(["ledger-append", "--dir", str(self.root),
                 "--json", json.dumps(bad2)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        # 無 playbook 引用 → 收但警告
        nowarn = {k: v for k, v in good.items() if k != "playbook_rules_cited"}
        r = run(["ledger-append", "--dir", str(self.root),
                 "--json", json.dumps(nowarn)])
        self.assertIn("playbook_rules_cited", r.stderr)

    def test_status_summary(self):
        run(["init", "--repo", str(self.repo), "--rungs", "E0", "E1", "E2"])
        q = json.loads((self.root / "queue.json").read_text())
        q["experiments"][0]["status"] = "done"
        q["experiments"][1]["status"] = "running"
        (self.root / "queue.json").write_text(json.dumps(q))
        (self.root / "BLOCKED.md").write_text("等 GPU 配額")
        row = {"experiment": "E0", "config_hash": "x", "metrics": {},
               "significant": False, "decision": "baseline recorded",
               "playbook_rules_cited": ["-"]}
        run(["ledger-append", "--dir", str(self.root), "--json", json.dumps(row)])
        out = json.loads(run(["status", "--dir", str(self.root)]).stdout)
        self.assertEqual(out["queue"], {"pending": 1, "running": 1,
                                        "done": 1, "failed": 0})
        self.assertEqual(out["running"], ["E1"])
        self.assertEqual(out["next_pending"], "E2")
        self.assertEqual(out["ledger_rows"], 1)
        self.assertIn("GPU", out["BLOCKED"])


if __name__ == "__main__":
    unittest.main()
