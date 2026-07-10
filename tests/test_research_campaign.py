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

    def test_init_git_upgrades_existing_campaign(self):
        run(["init", "--repo", str(self.repo)])
        (self.root / "MISSION.md").write_text("# MISSION: 手寫任務書\n")
        r = run(["init", "--repo", str(self.repo), "--git"])   # 升級不被擋
        out = json.loads(r.stdout)
        self.assertTrue(out["git_tracked"])
        self.assertTrue((self.repo / ".git").is_dir())
        self.assertEqual((self.root / "MISSION.md").read_text(),
                         "# MISSION: 手寫任務書\n")             # 任務書未被覆寫

    def test_nested_gitfile_worktree_detected(self):
        # submodule/linked worktree 的 .git 是「檔案」不是目錄——也要排除
        nested = self.repo / "sub_repo"
        nested.mkdir()
        (nested / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
        r = run(["init", "--repo", str(self.repo), "--git"])
        out = json.loads(r.stdout)
        self.assertEqual(out["nested_repos_ignored"], ["sub_repo/"])

    def test_ancestor_repo_ignoring_campaign_dir(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".gitignore").write_text("runs/\n")
        r = run(["init", "--repo", str(self.repo)])
        out = json.loads(r.stdout)
        self.assertFalse(out["git_tracked"])          # 被 ignore ≠ 有版控
        self.assertIn("忽略", r.stderr)

    def test_load_dir_rejects_non_campaign_dir(self):
        stray = self.repo / "not_campaign"
        stray.mkdir()
        r = run(["status", "--dir", str(stray)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不像 campaign 目錄", r.stderr)

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
        self.assertIn("chip pending", html)               # ladder 徽章
        self.assertIn("chip sig", html)                   # 顯著性徽章
        self.assertIn('class="tiles"', html)              # 狀態磚
        self.assertIn('meta name="description"', html)    # index 卡片描述來源
        self.assertIn("advance &lt;ok&gt;", html)         # 內容 escape
        self.assertIn("BLOCKED", html)
        self.assertIn("speech.lr", html)
        first = out.read_bytes()
        run(["report", "--dir", str(root), "--out", str(out)])
        self.assertEqual(first, out.read_bytes())         # 無時間戳＝確定性

    def test_pages_setup_deploy_branch_scaffold(self):
        repo = Path(tempfile.mkdtemp(prefix="hbcards-campaign-ab-"))
        root = repo / "runs" / "auto_research"
        run(["init", "--repo", str(repo)])
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "git@gitlab.example.com:g/p.git"], check=True)
        (repo / "public").mkdir()
        (repo / "public" / "index.html").write_text("<html>old</html>")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"],
                       check=True)
        out = json.loads(run(["pages-setup", "--repo", str(repo),
                              "--deploy-branch", "pages"]).stdout)
        ab = out["artifact_branch"]
        self.assertEqual(ab["branch"], "created")
        self.assertEqual(ab["worktree"], "created")
        self.assertTrue(ab["untracking_staged"])      # main 曾追蹤 public/
        # orphan：單 commit、無 parent、tree 含 CI 檔＋public 子樹
        parents = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--parents", "-1", "pages"],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(len(parents), 1)             # 只有自身 sha＝無 parent
        tree = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "--name-only", "pages"],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(tree), [".gitlab-ci.yml", "public"])
        gi = (repo / ".gitignore").read_text()
        self.assertIn("public/", gi)
        self.assertIn(".pages-worktree/", gi)
        self.assertIn('$CI_COMMIT_BRANCH == "pages"',
                      (repo / ".gitlab-ci.yml").read_text())
        self.assertNotIn("changes:", (repo / ".gitlab-ci.yml").read_text())
        pj = json.loads((root / "pages.json").read_text())
        self.assertEqual(pj["deploy_branch"], "pages")
        script = repo / "scripts" / "campaign" / "update_pages.sh"
        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn("flock", script.read_text())
        # 冪等重跑：不重建、不重複 append
        out2 = json.loads(run(["pages-setup", "--repo", str(repo),
                               "--deploy-branch", "pages"]).stdout)
        ab2 = out2["artifact_branch"]
        self.assertEqual((ab2["branch"], ab2["worktree"],
                          ab2["gitignore_added"], ab2["update_script"]),
                         ("existing", "existing", [], "existing"))
        # 無 flag 重跑不得洗掉 deploy_branch（read-modify-write）
        run(["pages-setup", "--repo", str(repo)])
        pj = json.loads((root / "pages.json").read_text())
        self.assertEqual(pj.get("deploy_branch"), "pages")
        # artifact-branch 模式下 main 側 ignore 生成頁是設計——不誤警
        r = run(["report", "--dir", str(root)])
        self.assertNotIn("被 .gitignore 忽略", r.stderr)
        # 目前所在分支不可當部署分支
        r = run(["pages-setup", "--repo", str(repo),
                 "--deploy-branch",
                 subprocess.run(["git", "-C", str(repo), "rev-parse",
                                 "--abbrev-ref", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()],
                ok=False)
        self.assertIn("目前所在分支", r.stderr)

    def test_pages_setup_deploy_branch_guards(self):
        repo = Path(tempfile.mkdtemp(prefix="hbcards-campaign-abg-"))
        run(["init", "--repo", str(repo)])
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(repo), "config", k, v], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "git@gitlab.example.com:g/p.git"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init",
                        "--allow-empty"], check=True)
        # 非法分支名（git 規則，非自訂 regex）在建任何東西之前就擋
        r = run(["pages-setup", "--repo", str(repo),
                 "--deploy-branch", "pages.lock"], ok=False)
        self.assertIn("check-ref-format", r.stderr)
        self.assertFalse((repo / ".gitlab-ci.yml").exists())
        # 既有同名分支不是單-commit artifact 分支 → 擋（防 amend 掉正常分支）
        subprocess.run(["git", "-C", str(repo), "branch", "dev"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x",
                        "--allow-empty"], check=True)   # main 2 commits
        subprocess.run(["git", "-C", str(repo), "branch", "-f", "dev"],
                       check=True)
        r = run(["pages-setup", "--repo", str(repo),
                 "--deploy-branch", "dev"], ok=False)
        self.assertIn("orphan artifact", r.stderr)
        # 正常 scaffold 後：worktree 掛錯分支要擋
        run(["pages-setup", "--repo", str(repo), "--deploy-branch", "pages"])
        pj_path = repo / "runs" / "auto_research" / "pages.json"
        r = run(["pages-setup", "--repo", str(repo),
                 "--deploy-branch", "pages2"], ok=False)
        self.assertIn("checkout 在", r.stderr)
        # artifact 模式（gitlab）不能直接 --host github（殘留 deploy_branch
        # 會讓 runtime 誤判契約）
        r = run(["pages-setup", "--repo", str(repo), "--host", "github"],
                ok=False)
        self.assertIn("artifact-branch", r.stderr)
        # 壞 pages.json 不靜默重建（自訂欄位會無聲遺失）
        pj_path.write_text("{broken")
        r = run(["pages-setup", "--repo", str(repo)], ok=False)
        self.assertIn("pages.json 壞了", r.stderr)

    def test_report_chart_payload_escaped_and_overflow_safe(self):
        import re
        repo = Path(tempfile.mkdtemp(prefix="hbcards-campaign-xss-"))
        root = repo / "runs" / "auto_research"
        run(["init", "--repo", str(repo), "--rungs", "E0", "E1"])
        (root / "glossary.json").write_text(json.dumps(
            {"mos": "品質 </script><script>x</script>"}, ensure_ascii=False))
        evil = "</script><script>alert(1)//"
        rows = [{"experiment": "E0", "config_hash": "h",
                 "metrics": {"mos": 3.4, evil: 1, "tiny": 5e-6},
                 "significant": False, "decision": "calibrate"},
                {"experiment": "E1", "config_hash": "h",
                 "metrics": {"mos": 3.1, evil: 2, "big": 10 ** 400},
                 "significant": True, "decision": "advance"}]
        for row in rows:
            run(["ledger-append", "--dir", str(root), "--json",
                 json.dumps(row)])
        out = repo / "docs" / "campaign-report.html"
        rep = json.loads(run(["report", "--dir", str(root),
                              "--out", str(out)]).stdout)
        # 10**400 不可 float——跳過該值即可，report 不得崩（OverflowError）
        self.assertEqual(rep["ledger_rows"], 2)
        html = out.read_text()
        payload_line = re.search(r"^const D = .*$", html, re.M).group(0)
        # 全 < 已跳脫：metric key/glossary 帶 </script> 也逃不出 script data
        self.assertNotIn("<", payload_line[len("const D = "):])
        self.assertIn("\\u003c/script>", payload_line)
        d = json.loads(re.search(r"^const D = (.*);$", html, re.M).group(1))
        self.assertIn("mos", d["metric_keys"])            # ≥2 次 → 入圖
        self.assertNotIn("big", d["metric_keys"])         # overflow 值被跳過
        self.assertEqual(d["metrics"]["mos"], [3.4, 3.1])




def _load_campaign():
    import importlib.util
    spec = importlib.util.spec_from_file_location("campaign_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestShowcaseMacMergePass(unittest.TestCase):
    """Known-opens the cluster branch left for the Mac merge pass."""

    def test_index_casefold_variant_hard_rejects(self):
        campaign = _load_campaign()
        pub = tempfile.mkdtemp(prefix="rc-camp-idx-")
        with open(os.path.join(pub, "Index.html"), "w") as f:
            f.write("<title>user page</title>")
        with open(os.path.join(pub, "report.html"), "w") as f:
            f.write("<title>r</title>")
        with self.assertRaises(SystemExit):
            campaign._write_index(pub, "t")
        # user file untouched
        self.assertIn("Index.html", os.listdir(pub))

    def test_ignored_generated_page_warns(self):
        campaign = _load_campaign()
        import io, contextlib
        repo = tempfile.mkdtemp(prefix="rc-camp-ign-")
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        with open(os.path.join(repo, ".gitignore"), "w") as f:
            f.write("*.html\n")
        page = os.path.join(repo, "docs", "x.html")
        os.makedirs(os.path.dirname(page))
        with open(page, "w") as f:
            f.write("<title>x</title>")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            campaign._warn_if_page_ignored(page)
        self.assertIn("被 .gitignore 忽略", err.getvalue())
        # non-ignored page stays silent
        with open(os.path.join(repo, "docs", "keep.css"), "w") as f:
            f.write("x")
        err2 = io.StringIO()
        with contextlib.redirect_stderr(err2):
            campaign._warn_if_page_ignored(os.path.join(repo, "docs", "keep.css"))
        self.assertEqual(err2.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
