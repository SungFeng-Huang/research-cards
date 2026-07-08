"""research-campaign progress dashboard: log parsing, payload, rendering."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPTS = os.path.join(HERE, "..", "skills", "research-campaign", "scripts")
CAMPAIGN = os.path.join(SCRIPTS, "campaign.py")

spec = importlib.util.spec_from_file_location(
    "progress_page", os.path.join(SCRIPTS, "progress_page.py"))
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)


def run(args, ok=True):
    env = dict(os.environ)
    env.pop("RESEARCH_CARDS_CONFIG", None)
    env.pop("HEPTABASE_CARDS_CONFIG", None)
    r = subprocess.run([sys.executable, CAMPAIGN, *args], env=env,
                       capture_output=True, text=True)
    if ok:
        assert r.returncode == 0, r.stderr[-500:]
    return r


def payload_of(html_path):
    html = Path(html_path).read_text()
    m = re.search(r"^const D = (.*);$", html, re.M)
    assert m, "payload line not found"
    return json.loads(m.group(1))    # < 是合法 JSON escape，直接可解


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="hbcards-progress-"))
        self.root = self.repo / "runs" / "auto_research"
        run(["init", "--repo", str(self.repo), "--rungs", "E0", "E1"])

    def write_cfg(self, **over):
        cfg = {"title": "測試戰役", "log_glob": "slurm_logs/*.out",
               "step_re": "^step=(?P<step>\\d+)\\b",
               "kv_re": "(\\w+)=(-?\\d+\\.?\\d*(?:[eE][+-]?\\d+)?)",
               "max_x": 200, "scheduler": "none", "table_every": 50,
               "charts": [
                   {"title": "訓練損失",
                    "series": [{"key": "loss", "label": "total loss"},
                               {"key": "recon", "label": "recon"}],
                    "nd": 3},
                   {"title": "usage", "series": [{"key": "usage"}],
                    "zero": True, "refs": [{"y": 30.0, "label": "上限 30%"}]},
               ]}
        cfg.update(over)
        (self.root / "progress.json").write_text(
            json.dumps(cfg, ensure_ascii=False))
        return cfg

    def write_logs(self):
        d = self.repo / "slurm_logs"
        d.mkdir(exist_ok=True)
        # job 101: steps 0..100；job 102 重疊 80..100（搶佔重跑）再續到 200
        with open(d / "run-101.out", "w") as f:
            f.write("some preamble line\n")
            for s in range(0, 101, 10):
                f.write(f"step={s} loss={1.0 + s * 0.001:.3f} "
                        f"recon=0.5 usage={s * 0.1:.1f}\n")
        with open(d / "run-102.out", "w") as f:
            for s in range(80, 201, 10):
                f.write(f"step={s} loss={0.5 + s * 0.001:.3f} "
                        f"recon=0.4 usage={s * 0.1:.1f}\n")
        return d


class TestConfig(Base):
    def test_init_scaffolds_and_refuses_overwrite(self):
        out = json.loads(run(["progress-init", "--dir", str(self.root)]).stdout)
        cfg = json.loads((self.root / "progress.json").read_text())
        self.assertIn("log_glob", cfg)
        self.assertIn("charts", cfg)
        self.assertIn("_doc", cfg)                    # 模板自帶逐項說明
        r = run(["progress-init", "--dir", str(self.root)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("不覆蓋", r.stderr)

    def test_progress_without_config_points_to_init(self):
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("progress-init", r.stderr)

    def test_config_validation(self):
        self.write_cfg(step_re="^step=(\\d+)")        # 缺 named group
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertIn("(?P<step>", r.stderr)
        self.write_cfg(kv_re="(\\w+)")                # group 數不對
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertIn("兩個 capture group", r.stderr)
        self.write_cfg(charts=[{"title": "x", "series": [
            {"key": f"k{i}"} for i in range(5)]}])    # >4 series
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertIn("上限", r.stderr)
        self.write_cfg(charts=[])                     # 沒圖
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertNotEqual(r.returncode, 0)


class TestParsing(Base):
    def test_overlap_later_job_wins_and_jobs_summary(self):
        self.write_logs()
        self.write_cfg()
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg)
        self.assertEqual(sorted(train)[0], 0)
        self.assertEqual(sorted(train)[-1], 200)
        # step 90 在兩個 log 都有——後面的 job（102）覆寫
        self.assertAlmostEqual(train[90]["loss"], 0.59, places=3)
        self.assertAlmostEqual(train[90]["recon"], 0.4)
        self.assertEqual([j["job_id"] for j in jobs], ["101", "102"])
        self.assertEqual(jobs[0]["first_step"], 0)
        self.assertEqual(jobs[1]["last_step"], 200)

    def test_nonfinite_and_junk_values_dropped(self):
        d = self.repo / "slurm_logs"
        d.mkdir(exist_ok=True)
        (d / "run-1.out").write_text(
            "step=10 loss=1e999 recon=0.5\nstep=20 loss=0.9 recon=0.4\n")
        self.write_cfg()
        cfg = pp.load_progress_config(str(self.root))
        train, _ = pp.parse_logs(str(self.repo), cfg)
        self.assertNotIn("loss", train[10])           # inf → 丟棄該值
        self.assertEqual(train[10]["recon"], 0.5)     # 同行其他值保留

    def test_downsample_keeps_last(self):
        steps = list(range(0, 5000))
        kept = pp.downsample(steps, 700)
        self.assertLessEqual(len(kept), 701)
        self.assertEqual(kept[-1], 4999)
        self.assertEqual(kept[0], 0)


class TestRender(Base):
    def test_end_to_end_deterministic_and_escaped(self):
        self.write_logs()
        self.write_cfg(title="測試 </script> 戰役",
                       footnote="註 <!--<script 腳")
        (self.root / "ledger.jsonl").write_text(json.dumps(
            {"experiment": "E0", "config_hash": "h", "metrics": {},
             "significant": True, "decision": "advance"}) + "\n")
        out = self.repo / "docs" / "campaign-progress.html"
        rep = json.loads(run(["progress", "--dir", str(self.root),
                              "--out", str(out)]).stdout)
        self.assertEqual(rep["last_step"], 200)
        self.assertEqual(rep["charts"], 2)
        html = out.read_text()
        payload_line = re.search(r"^const D = .*$", html, re.M).group(0)
        self.assertNotIn("<", payload_line[len("const D = "):])  # 全 < 已跳脫
        self.assertIn("\\u003c/script>", payload_line)
        self.assertIn("\\u003c!--", payload_line)     # <!-- 也進不了 script data
        self.assertIn("&lt;/script&gt;", html)        # <title> 走 html escape
        d = payload_of(out)
        self.assertEqual(d["title"], "測試 </script> 戰役")
        self.assertEqual(d["x"][-1], 200)
        self.assertEqual(d["cols"]["loss"][-1], 0.7)
        self.assertEqual(d["charts"][0]["series"][0]["color"], "#2a78d6")
        self.assertEqual(d["charts"][0]["series"][1]["color"], "#1baf7a")
        self.assertIsNone(d["squeue"])                # scheduler none
        # tiles：進度（200/200=100%）＋兩張圖最新值
        self.assertIn("100.0%", json.dumps(d["tiles"]))
        self.assertEqual(d["tiles"][0]["val"], "200 / 200")
        # 資料表每 50 步 + 最後一步
        self.assertEqual([r[0] for r in d["table"]], [0, 50, 100, 150, 200])
        first = out.read_bytes()
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        self.assertEqual(first, out.read_bytes())     # 確定性
        # report 有 progress.json 時互連進度頁
        run(["report", "--dir", str(self.root),
             "--out", str(self.repo / "docs" / "campaign-report.html")])
        self.assertIn("campaign-progress.html",
                      (self.repo / "docs" / "campaign-report.html").read_text())

    def test_small_magnitude_metrics_survive(self):
        # lr=5e-06 不可被小數位捨入壓成 0——存 6 位有效數字
        d = self.repo / "slurm_logs"
        d.mkdir(exist_ok=True)
        (d / "run-1.out").write_text(
            "step=10 loss=0.9 lr=5e-06\nstep=20 loss=0.8 lr=1.23456789e-05\n")
        self.write_cfg(charts=[{"title": "lr",
                                "series": [{"key": "lr"}], "nd": 8}])
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        dd = payload_of(out)
        self.assertEqual(dd["cols"]["lr"], [5e-06, 1.23457e-05])

    def test_same_step_lines_merge_not_replace(self):
        # 同 step 的 train 行＋eval 行＋雜訊行——逐 key 合併不清空
        d = self.repo / "slurm_logs"
        d.mkdir(exist_ok=True)
        (d / "run-1.out").write_text(
            "step=10 loss=0.9\n"
            "step=10 val_loss=0.7\n"
            "step=20 loss=0.8\n"
            "step=20 checkpoint saved to ckpt-20.pt\n")
        self.write_cfg()
        cfg = pp.load_progress_config(str(self.root))
        train, _ = pp.parse_logs(str(self.repo), cfg)
        self.assertEqual(train[10], {"loss": 0.9, "val_loss": 0.7})
        self.assertEqual(train[20], {"loss": 0.8})    # 雜訊行不清空

    def test_ledger_append_rejects_nan(self):
        bad = ('{"experiment":"E0","config_hash":"h","metrics":{"loss":NaN},'
               '"significant":true,"decision":"x"}')
        r = run(["ledger-append", "--dir", str(self.root), "--json", bad],
                ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("有限數", r.stderr)

    def test_nan_in_queue_sanitized_not_crash(self):
        self.write_logs()
        self.write_cfg()
        (self.root / "queue.json").write_text(
            '{"experiments": [{"id": "E0", "status": "pending", "w": NaN}]}')
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        d = payload_of(out)
        self.assertIsNone(d["queue"]["experiments"][0]["w"])  # NaN → null

    def test_placeholder_literals_in_title_safe(self):
        self.write_logs()
        self.write_cfg(title="奇怪標題 __PAYLOAD__ 與 __TITLE__")
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        d = payload_of(out)                            # payload 仍可解析
        self.assertIn("__PAYLOAD__", d["title"])
        html = out.read_text()
        self.assertEqual(html.count("const D = "), 1)  # blob 沒被二次替換

    def test_log_glob_cannot_escape_project_root(self):
        outside = Path(tempfile.mkdtemp(prefix="hbcards-outside-"))
        (outside / "secret.out").write_text("step=1 loss=1.0\n")
        rel = os.path.relpath(outside, self.repo)
        self.write_cfg(log_glob=f"{rel}/*.out")
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("之外", r.stderr)
        self.write_cfg(log_glob=str(outside / "*.out"))  # 絕對路徑也擋
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertIn("相對 project root", r.stderr)

    def test_recursive_glob_supported(self):
        (self.repo / "logs" / "exp1").mkdir(parents=True)
        (self.repo / "logs" / "a.out").write_text("step=1 loss=1.0\n")
        (self.repo / "logs" / "exp1" / "b.out").write_text("step=2 loss=0.9\n")
        self.write_cfg(log_glob="logs/**/*.out")
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg)
        self.assertEqual(sorted(train), [1, 2])        # ** 含零層

    def test_slurm_scheduler_line_and_eta(self):
        self.write_logs()
        self.write_cfg(scheduler="slurm", job_name="demo", max_x=400)
        bindir = self.repo / "bin"
        bindir.mkdir()
        (bindir / "squeue").write_text(
            "#!/bin/sh\necho '12345 RUNNING 1:40:00 node01'\n")
        os.chmod(bindir / "squeue", 0o755)
        out = self.repo / "docs" / "p.html"
        env = dict(os.environ,
                   PATH=f"{bindir}:{os.environ['PATH']}")
        env.pop("RESEARCH_CARDS_CONFIG", None)
        env.pop("HEPTABASE_CARDS_CONFIG", None)
        r = subprocess.run([sys.executable, CAMPAIGN, "progress",
                            "--dir", str(self.root), "--out", str(out)],
                           env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        d = payload_of(out)
        self.assertIn("RUNNING", d["squeue"])
        tiles = json.dumps(d["tiles"], ensure_ascii=False)
        self.assertIn("step/min", tiles)               # rate/ETA tile 有出現
        # job 102 跨 80→200 步、牆鐘 100 分 → 1.2 step/min
        self.assertIn("1.2 step/min", tiles)

    def test_nd_zero_honored_and_invalid_rejected(self):
        self.write_logs()
        self.write_cfg(charts=[{"title": "x", "series": [{"key": "loss"}],
                                "nd": 0}])
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        self.assertEqual(payload_of(out)["charts"][0]["nd"], 0)
        self.write_cfg(charts=[{"title": "x", "series": [{"key": "loss"}],
                                "nd": -1}])
        r = run(["progress", "--dir", str(self.root)], ok=False)
        self.assertIn("nd", r.stderr)

    def test_title_falls_back_to_mission_h1(self):
        self.write_logs()
        self.write_cfg(title="")
        (self.root / "MISSION.md").write_text("# MISSION: 任務書標題\n")
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        self.assertEqual(payload_of(out)["title"], "任務書標題")

    def test_warnings_for_unknown_field_and_unseen_key(self):
        self.write_logs()
        cfg = {"title": "t", "log_glob": "slurm_logs/*.out",
               "step_re": "^step=(?P<step>\\d+)\\b",
               "kv_re": "(\\w+)=(-?\\d+\\.?\\d*(?:[eE][+-]?\\d+)?)",
               "scheduler": "none", "tabel_every": 100,   # 拼錯的欄位
               "charts": [{"title": "x", "series": [{"key": "lossss"}]}]}
        (self.root / "progress.json").write_text(json.dumps(cfg))
        r = run(["progress", "--dir", str(self.root),
                 "--out", str(self.repo / "docs" / "p.html")])
        self.assertIn("tabel_every", r.stderr)         # 未知欄位警告
        self.assertIn("lossss", r.stderr)              # 空圖 key 警告

    def test_no_logs_still_renders(self):
        self.write_cfg()
        out = self.repo / "docs" / "campaign-progress.html"
        rep = json.loads(run(["progress", "--dir", str(self.root),
                              "--out", str(out)]).stdout)
        self.assertIsNone(rep["last_step"])
        self.assertEqual(rep["jobs"], 0)
        d = payload_of(out)
        self.assertEqual(d["x"], [])
        self.assertEqual(d["table"], [])

    def test_default_out_honors_pages_json(self):
        self.write_logs()
        self.write_cfg()
        (self.root / "pages.json").write_text(json.dumps(
            {"host": "gitlab", "output_dir": "public", "ci_ready": True}))
        run(["progress", "--dir", str(self.root)])
        self.assertTrue(
            (self.repo / "public" / "campaign-progress.html").is_file())
        self.assertFalse((self.repo / "docs").exists())


if __name__ == "__main__":
    unittest.main()
