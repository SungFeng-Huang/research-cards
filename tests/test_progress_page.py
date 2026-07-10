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

    def test_gstep_tracked_flag_follows_config(self):
        # 沒設 gstep_re/resume_re＝沒在追蹤存檔——頁面 job 表不得把 gstep=null
        # 全判 failed（預設勾選的隱藏會把所有正常 job 藏光）
        self.write_logs()
        self.write_cfg()
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        self.assertFalse(payload_of(out)["gstep_tracked"])
        self.write_cfg(resume_re="Restored step=(?P<gstep>\\d+)-last")
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        self.assertTrue(payload_of(out)["gstep_tracked"])

    def test_rank_suffix_ordering_and_job_grouping(self):
        # slurm-<job>-<rank>.log：尾碼是 rank 不是 job id——需照 raw job id
        # 排序（較新 job 覆寫重疊步數）與分組（不得全掛到 job「0」）
        d = self.repo / "slurm_logs"
        d.mkdir(exist_ok=True)
        (d / "slurm-101-0.log").write_text("step=10 loss=1.0\nstep=20 loss=0.9\n")
        (d / "slurm-102-0.log").write_text("step=20 loss=0.5\nstep=30 loss=0.4\n")
        self.write_cfg(log_glob="slurm_logs/slurm-*.log")
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
        self.assertAlmostEqual(train[20]["loss"], 0.5)    # 102 覆寫 101
        self.assertEqual([j["job_id"] for j in jobs], ["101", "102"])

    def test_same_basename_across_dirs_are_separate_attempts(self):
        # <job>_<task>/train.out：不同目錄的同名檔不得合成一個 attempt
        for job, (s0, s1) in [("11111_0", (0, 101)), ("22222_0", (100, 201))]:
            d = self.repo / "logs" / job
            d.mkdir(parents=True)
            (d / "train.out").write_text(
                "".join(f"step={s} loss=1.0\n" for s in range(s0, s1, 10)))
        self.write_cfg(log_glob="logs/**/train.out")
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
        self.assertEqual([j["job_id"] for j in jobs], ["11111", "22222"])
        self.assertEqual([j["attempts"] for j in jobs], [1, 1])
        self.assertEqual(jobs[0]["last_step"], 100)       # 各自的區間沒被互蓋
        self.assertEqual(jobs[1]["first_step"], 100)

    def test_array_dir_beats_rank_digit_in_basename(self):
        # <job>_<task>/train-0.out：basename 的「0」是 rank——array 目錄
        # 必須優先，否則兩個任務的 rank-0 檔塌成同一 attempt
        for job, (s0, s1) in [("11111_0", (0, 101)), ("22222_0", (100, 201))]:
            d = self.repo / "logs" / job
            d.mkdir(parents=True)
            (d / "train-0.out").write_text(
                "".join(f"step={s} loss=1.0\n" for s in range(s0, s1, 10)))
        self.write_cfg(log_glob="logs/**/train-*.out")
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
        self.assertEqual([j["job_id"] for j in jobs], ["11111", "22222"])
        self.assertEqual([j["attempts"] for j in jobs], [1, 1])

    def test_teardown_inference_requires_resume_within_span(self):
        d = self.repo / "slurm_logs"
        d.mkdir(exist_ok=True)
        # 101 跑 0..100（無 ckpt 訊息）；102 從 100 恢復 → 回推 101 有存檔
        (d / "run-101.out").write_text(
            "".join(f"step={s} loss=1.0\n" for s in range(0, 101, 10)))
        (d / "run-102.out").write_text(
            "Restored step=100-last.ckpt\nstep=0 loss=0.5\nstep=10 loss=0.5\n")
        # 103 只跑到 step 10；104 從 300 恢復——300 不在 103 區間，不得捏造
        (d / "run-103.out").write_text("step=0 loss=0.5\nstep=10 loss=0.5\n")
        (d / "run-104.out").write_text(
            "Restored step=300-last.ckpt\nstep=0 loss=0.4\n")
        self.write_cfg(resume_re="Restored step=(?P<gstep>\\d+)-last")
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
        by = {j["job_id"]: j for j in jobs}
        self.assertEqual(by["101"]["gstep"], 100)         # 上下界內 → 回推
        self.assertTrue(by["101"].get("gstep_inferred"))
        self.assertIsNone(by["103"]["gstep"])             # 300 > last=10 → 不捏造

    def test_unknown_field_warning_skips_injected_keys(self):
        # 注入的內部鍵（_gstep_re 等）不得被當成未知欄位；真正的錯字要警告
        self.write_logs()
        self.write_cfg(gstep_re="global step (?P<gstep>\\d+)", gstep_scale=2)
        r = run(["progress", "--dir", str(self.root)])
        self.assertNotIn("未知欄位", r.stderr)
        self.write_cfg(log_globb="slurm_logs/*.out")  # 錯字仍要警告
        r = run(["progress", "--dir", str(self.root)])
        self.assertIn("log_globb", r.stderr)


class TestParsing(Base):
    def test_overlap_later_job_wins_and_jobs_summary(self):
        self.write_logs()
        self.write_cfg()
        cfg = pp.load_progress_config(str(self.root))
        train, jobs = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
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
        train, _ = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
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
        train, _ = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
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
        train, jobs = pp.parse_logs(str(self.repo), cfg, cfg["log_glob"])
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


class TestTzOffset(Base):
    """P2-2: tz_offset_hours 邊界驗證＋跨 cfg 不汙染。"""

    def _make_cfg_with_tz(self, tz):
        cfg = {"title": "t", "log_glob": "slurm_logs/*.out",
               "step_re": "^step=(?P<step>\\d+)\\b",
               "kv_re": "(\\w+)=(-?\\d+\\.?\\d*)",
               "charts": [{"title": "c", "series": [{"key": "loss"}]}],
               "tz_offset_hours": tz}
        (self.root / "progress.json").write_text(json.dumps(cfg))

    def test_valid_tz_offset_accepted(self):
        self._make_cfg_with_tz(9)
        out = self.repo / "docs" / "p.html"
        run(["progress", "--dir", str(self.root), "--out", str(out)])

    def test_tz_offset_out_of_range_rejected(self):
        for bad in (24, -24, 100):
            self._make_cfg_with_tz(bad)
            r = run(["progress", "--dir", str(self.root)], ok=False)
            self.assertNotEqual(r.returncode, 0, f"tz={bad} should be rejected")
            self.assertIn("合法範圍", r.stderr)

    def test_tz_global_resets_to_default_between_cfgs(self):
        """cfg A 設 tz=5 生成頁面含 UTC+5；cfg B 不設，生成頁面應含 UTC+8。"""
        self.write_logs()   # 提供有 mtime 的 log，讓時區標籤出現在頁面

        def make_cfg(tz=None):
            c = {"title": "t", "log_glob": "slurm_logs/*.out",
                 "step_re": "^step=(?P<step>\\d+)\\b",
                 "kv_re": "(\\w+)=(-?\\d+\\.?\\d*)",
                 "charts": [{"title": "c", "series": [{"key": "loss"}]}]}
            if tz is not None:
                c["tz_offset_hours"] = tz
            return c

        out = self.repo / "docs" / "p.html"
        # campaign A: tz=5 → UTC+5 出現在頁面
        (self.root / "progress.json").write_text(json.dumps(make_cfg(tz=5)))
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        self.assertIn("UTC+5", out.read_text())

        # campaign B: 無 tz → 應重設回 UTC+8，不殘留 +5
        (self.root / "progress.json").write_text(json.dumps(make_cfg()))
        run(["progress", "--dir", str(self.root), "--out", str(out)])
        html = out.read_text()
        self.assertIn("UTC+8", html)
        self.assertNotIn("UTC+5", html)


class TestEvalBarChart(unittest.TestCase):
    """P2-3: eval 柱狀圖 zero / negative 值不得產生 NaN 座標——JS 模板驗證。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "pp_bar", os.path.join(SCRIPTS, "progress_page.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        cls.TEMPLATE = m.TEMPLATE

    def test_bar_chart_js_uses_safe_ymin(self):
        """修正後模板 eval 柱狀圖的 ymin 以 Math.min(0,...) 計算，相容零值。"""
        self.assertIn("Math.min(0, ...vals)", self.TEMPLATE)

    def test_bar_chart_js_degenerate_guard_present(self):
        """當 ymax <= ymin 時（全零），JS 應有 ymax = ymin + 1 的退化守衛。"""
        self.assertIn("if (ymax <= ymin) ymax = ymin + 1", self.TEMPLATE)


if __name__ == "__main__":
    unittest.main()
