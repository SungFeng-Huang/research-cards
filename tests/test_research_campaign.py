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

    def test_init_outside_git_notes_split_layout(self):
        r = run(["init", "--repo", str(self.repo)])
        out = json.loads(r.stdout)
        self.assertFalse(out["git_tracked"])
        self.assertIn("不在 git 版控內", r.stderr)

    def test_init_git_bootstraps_project_root(self):
        # 拆分式佈局：project root 非 repo、底下有巢狀 core repo
        nested = self.repo / "core_code"
        nested.mkdir()
        subprocess.run(["git", "init", "-q", str(nested)], check=True)
        r = run(["init", "--repo", str(self.repo), "--git"])
        out = json.loads(r.stdout)
        self.assertTrue(out["git_tracked"])
        self.assertTrue(out["git_initialized"])
        self.assertEqual(out["nested_repos_ignored"], ["core_code/"])
        self.assertTrue((self.repo / ".git").is_dir())
        gi = (self.repo / ".gitignore").read_text()
        self.assertIn("checkpoints/", gi)
        self.assertIn("core_code/", gi)
        self.assertIn("首 commit", r.stderr)  # 不自動 commit，留給使用者

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


class TestPagesSetup(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="hbcards-campaign-pg-"))
        self.root = self.repo / "runs" / "auto_research"
        run(["init", "--repo", str(self.repo)])
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def _remote(self, url):
        subprocess.run(["git", "-C", str(self.repo), "remote", "add",
                        "origin", url], check=True)

    def test_github_remote_installs_workflow(self):
        self._remote("git@github.com:user/proj.git")
        out = json.loads(run(["pages-setup", "--repo", str(self.repo)]).stdout)
        self.assertEqual(out["host"], "github")
        self.assertEqual(out["output_dir"], "docs")
        self.assertTrue(out["ci_installed"])
        wf = self.repo / ".github" / "workflows" / "pages.yml"
        self.assertIn("actions/deploy-pages", wf.read_text())
        pj = json.loads((self.root / "pages.json").read_text())
        self.assertEqual(pj, {"host": "github", "output_dir": "docs",
                              "ci_ready": True})
        # report 未指定 --out → 依 pages.json 落 docs/
        run(["report", "--dir", str(self.root)])
        self.assertTrue((self.repo / "docs" / "campaign-report.html").is_file())

    def test_gitlab_remote_installs_ci_and_report_targets_public(self):
        self._remote("https://gitlab-master.example.com/team/proj.git")
        out = json.loads(run(["pages-setup", "--repo", str(self.repo)]).stdout)
        self.assertEqual(out["host"], "gitlab")
        self.assertEqual(out["output_dir"], "public")
        ci = (self.repo / ".gitlab-ci.yml").read_text()
        self.assertIn("pages:", ci)
        self.assertIn("- public", ci)
        run(["report", "--dir", str(self.root)])
        self.assertTrue((self.repo / "public" / "campaign-report.html").is_file())
        self.assertFalse((self.repo / "docs").exists())

    def test_existing_ci_file_not_overwritten(self):
        self._remote("https://gitlab.com/team/proj.git")
        (self.repo / ".gitlab-ci.yml").write_text("stages: [test]\n")
        r = run(["pages-setup", "--repo", str(self.repo)])
        out = json.loads(r.stdout)
        self.assertFalse(out["ci_installed"])
        self.assertIn("手動合併", r.stderr)
        self.assertEqual((self.repo / ".gitlab-ci.yml").read_text(),
                         "stages: [test]\n")          # 原檔不動
        # pages.json 照寫但 ci_ready=false——「跑過 setup ≠ 部署就緒」可判別
        pj = json.loads((self.root / "pages.json").read_text())
        self.assertEqual(pj["output_dir"], "public")
        self.assertFalse(pj["ci_ready"])

    def test_ci_ready_survives_rerun_after_manual_merge(self):
        self._remote("https://gitlab.com/team/proj.git")
        (self.repo / ".gitlab-ci.yml").write_text("stages: [test]\n")
        run(["pages-setup", "--repo", str(self.repo)])
        pj = self.root / "pages.json"
        d = json.loads(pj.read_text())
        d["ci_ready"] = True                       # 使用者手動合併完標好
        pj.write_text(json.dumps(d))
        r = run(["pages-setup", "--repo", str(self.repo)])   # 重跑
        self.assertTrue(json.loads(pj.read_text())["ci_ready"])  # 不降級
        self.assertNotIn("手動合併", r.stderr)     # 也不再嘮叨

    def test_host_detection_uses_url_host_not_path(self):
        # repo 名含 "github" 的 gitlab remote 不可誤判成 GitHub
        self._remote("https://gitlab.com/team/github-mirror.git")
        out = json.loads(run(["pages-setup", "--repo", str(self.repo)]).stdout)
        self.assertEqual(out["host"], "gitlab")
        # scp-like 形式同樣只看 host
        subprocess.run(["git", "-C", str(self.repo), "remote", "set-url",
                        "origin", "git@github.com:team/gitlab-tools.git"],
                       check=True)
        (self.root / "pages.json").unlink()
        out = json.loads(run(["pages-setup", "--repo", str(self.repo)]).stdout)
        self.assertEqual(out["host"], "github")

    def test_host_detection_follows_push_url(self):
        # 部署跟著 push 走：fetch=github、pushurl=gitlab → gitlab
        self._remote("https://github.com/team/proj.git")
        subprocess.run(["git", "-C", str(self.repo), "remote", "set-url",
                        "--push", "origin",
                        "https://gitlab-master.example.com/team/proj.git"],
                       check=True)
        out = json.loads(run(["pages-setup", "--repo", str(self.repo)]).stdout)
        self.assertEqual(out["host"], "gitlab")

    def test_github_workflow_branch_rewritten_to_current(self):
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q",
                        "-b", "trunk"], check=True)
        self._remote("https://github.com/team/proj.git")
        run(["pages-setup", "--repo", str(self.repo)])
        wf = (self.repo / ".github" / "workflows" / "pages.yml").read_text()
        self.assertIn('branches: ["trunk"]', wf)
        self.assertNotIn('branches: ["main"]', wf)

    def test_report_rejects_invalid_output_dir(self):
        self._remote("https://github.com/team/proj.git")
        run(["pages-setup", "--repo", str(self.repo)])
        pj = self.root / "pages.json"
        pj.write_text(json.dumps({"host": "github",
                                  "output_dir": "../outside"}))
        r = run(["report", "--dir", str(self.root)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不合法", r.stderr)
        pj.write_text("{broken")
        r = run(["report", "--dir", str(self.root)], ok=False)
        self.assertNotEqual(r.returncode, 0)          # 壞檔明確失敗，不靜默回退
        # 明給 --out 不受 pages.json 影響
        out = self.repo / "x.html"
        run(["report", "--dir", str(self.root), "--out", str(out)])
        self.assertTrue(out.is_file())

    def test_unknown_remote_requires_host_flag(self):
        self._remote("https://git.example.com/team/proj.git")
        r = run(["pages-setup", "--repo", str(self.repo)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--host", r.stderr)
        out = json.loads(run(["pages-setup", "--repo", str(self.repo),
                              "--host", "github"]).stdout)
        self.assertEqual(out["host"], "github")


class TestReport(unittest.TestCase):
    def test_report_renders_and_is_deterministic(self):
        repo = Path(tempfile.mkdtemp(prefix="hbcards-campaign-rep-"))
        root = repo / "runs" / "auto_research"
        run(["init", "--repo", str(repo), "--rungs", "E0", "E1"])
        (root / "MISSION.md").write_text("# MISSION: 測試戰役 <x&y>\n")
        row = {"experiment": "E0", "config_hash": "h", "metrics": {"wer": 0.31},
               "significant": True, "decision": "advance <ok>",
               "playbook_rules_cited": ["speech.lr"]}
        run(["ledger-append", "--dir", str(root), "--json", json.dumps(row)])
        (root / "BLOCKED.md").write_text("等資料")
        out = repo / "docs" / "campaign-report.html"
        rep = json.loads(run(["report", "--dir", str(root),
                              "--out", str(out)]).stdout)
        self.assertEqual(rep["ledger_rows"], 1)
        html = out.read_text()
        self.assertIn("測試戰役 &lt;x&amp;y&gt;", html)   # 標題有 escape
        self.assertIn("b-pending", html)                  # ladder 徽章
        self.assertIn("b-sig", html)                      # 顯著性徽章
        self.assertIn("advance &lt;ok&gt;", html)         # 內容 escape
        self.assertIn("BLOCKED", html)
        self.assertIn("speech.lr", html)
        first = out.read_bytes()
        run(["report", "--dir", str(root), "--out", str(out)])
        self.assertEqual(first, out.read_bytes())         # 無時間戳＝確定性


if __name__ == "__main__":
    unittest.main()
