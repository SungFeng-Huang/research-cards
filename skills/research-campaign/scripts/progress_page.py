#!/usr/bin/env python3
"""Training-progress dashboard for a research campaign (stdlib only).

Generic port of vocodec's gen_progress_page.py: parse training logs into
step-indexed metric rows, render one self-contained HTML page (inline
CSS/JS/SVG, no CDN) with stat tiles, SVG line charts, a sampled data table,
the campaign ladder, recent ledger rows, and the training-job chain.

Everything domain-specific lives in runs/auto_research/progress.json
(created by `campaign.py progress-init`): the log glob, the step/metric
regexes, and the chart declarations. This module owns only the mechanical
parts — parsing, downsampling, payload sanitising, and the chart layer.

Chart design follows the dataviz skill: categorical slots #2a78d6/#1baf7a/
#eda100/#008300 (validated on the white panel surface — aqua/yellow sit
below 3:1 so the sampled data table is the required relief), 2px lines,
hairline solid grid, crosshair + all-series tooltip, legend only for >=2
series, one y-axis per chart (more measures = more charts, never dual axes).

Deterministic given identical inputs: no wall-clock timestamp is embedded —
"freshness" is the max log mtime (input-derived) and git history. The
optional scheduler line (squeue) is live state; tests run with
scheduler=none.
"""
import glob
import json
import math
import os
import re
import sys

MAX_SERIES_PER_CHART = 4          # categorical slots — fold more into charts
SERIES_COLORS = ("#2a78d6", "#1baf7a", "#eda100", "#008300")

PROGRESS_TEMPLATE = {
    "_doc": ("campaign.py progress 的設定。log_glob 相對 project root、"
             "支援 **（遞迴）、對到的檔案必須在 project 內（本檔會進版控"
             "共享，不允許把 repo 外資料發佈到 Pages）；step_re 必須含 "
             "named group (?P<step>...)；kv_re 必須恰有兩個 group（key、"
             "數值），名為 step 的指標保留給 x 軸、要畫請改名；regex 來自"
             "本檔（自己的機器自己的 log，災難性回溯只會慢到自己）。"
             "charts[].series[].key 對應 kv_re 抓到的指標名。"
             "_doc 開頭的 key 一律忽略、其他未知欄位會出警告。"),
    "title": "",
    "_doc_title": "頁面標題；留空則取 MISSION.md 的 H1",
    "log_glob": "slurm_logs/*.out",
    "runs": [],
    "_doc_runs": ("多個訓練 run 疊在同一張曲線圖（勾選顯示子集）：[{\"name\": "
                  "\"E1 …\", \"log_glob\": \"exp/run_a/*.log\", \"desc\": \"設定差異\","
                  " \"purpose\": \"實驗目的\"}, …]。留空＝單一 log_glob 當一個 run。"
                  "desc/purpose 會渲染成曲線區上方的 run 總覽表。"),
    "gstep_re": None,
    "_doc_gstep_re": ("選配：全域 step（optimizer step，跨重啟單調）的 regex，"
                      "需 named group (?P<gstep>\\d+)，如 PTL 的 checkpoint 訊息 "
                      "\"global step (?P<gstep>\\d+)\"——job 鏈表會多一欄「全域 "
                      "step(ckpt)」。log_glob 可為 list（把含這些訊息的 stderr log "
                      "一併掃進來；不含訓練 step 行的檔案不影響曲線）。"),
    "job_group_re": None,
    "_doc_job_group_re": ("訓練 job 鏈的聚合鍵 regex（對 log 相對路徑 search，"
                          "取 named group job 或整個 match）。預設：路徑裡最後一個 "
                          "\"<數字>_<數字>\" 目錄視為 Slurm array 任務取 master id、"
                          "否則取檔名數字尾碼——同任務的搶佔/重啟合成一列。"),
    "step_re": "^step=(?P<step>\\d+)\\b",
    "kv_re": "(\\w+)=(-?\\d+\\.?\\d*(?:[eE][+-]?\\d+)?)",
    "max_x": None,
    "_doc_max_x": "訓練總步數（進度百分比/ETA 的分母）；不知道就留 null",
    "x_label": "step",
    "table_every": 500,
    "max_points": 700,
    "scheduler": "none",
    "_doc_scheduler": "\"slurm\" 會 best-effort 跑 squeue 顯示佇列狀態與 "
                      "ETA（需 job_name）；\"none\" 完全離線（輸出確定性）",
    "job_name": None,
    "footnote": "",
    "charts": [
        {"title": "訓練損失", "note": "",
         "series": [{"key": "loss", "label": "total loss"}],
         "zero": False, "nd": 3, "refs": []},
    ],
    "_doc_table_every": "資料表取 step 為 table_every 倍數的列＋最後一列"
                        "（是 modulo 不是等距抽樣——log 週期不整除時列數會少）",
    "_doc_charts": ("每張圖一個 y 軸；series ≤4（超過請拆圖）；zero=true 讓 "
                    "y 軸含 0；refs=[{y,label}] 畫參考水平線；nd=顯示小數位"
                    "（0-10；資料本身存 6 位有效數字）"),
}


def _fail(msg):
    sys.exit(f"[progress] {msg}")


def load_progress_config(root):
    path = os.path.join(root, "progress.json")
    if not os.path.exists(path):
        _fail(f"找不到 {path}——先跑 campaign.py progress-init 生成模板再填")
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (ValueError, OSError) as e:
        _fail(f"progress.json 壞了（{e}）")
    if not isinstance(cfg, dict):
        _fail("progress.json 必須是 JSON object")
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_doc")}
    user_keys = set(cfg)   # 未知欄位檢查用——之後會注入 _gstep_re 等內部鍵
    runs = cfg.get("runs")
    if runs:
        if not isinstance(runs, list):
            _fail("runs 必須是 list")
        for i, r in enumerate(runs):
            if not isinstance(r, dict) or not r.get("log_glob"):
                _fail(f"runs[{i}] 缺 log_glob")
            r.setdefault("name", f"run{i+1}")
    elif not cfg.get("log_glob"):
        _fail("progress.json 缺 log_glob（或改用 runs）")
    if cfg.get("gstep_re"):
        try:
            g = re.compile(cfg["gstep_re"])
        except re.error as e:
            _fail(f"gstep_re 不是合法 regex：{e}")
        if "gstep" not in g.groupindex:
            _fail("gstep_re 必須含 named group (?P<gstep>\\d+)")
        cfg["_gstep_re"] = g
    else:
        cfg["_gstep_re"] = None
    if cfg.get("gstep_scale") is not None:
        try:
            assert int(cfg["gstep_scale"]) > 0
        except (TypeError, ValueError, AssertionError):
            _fail(f"gstep_scale={cfg.get('gstep_scale')!r} 必須是正整數"
                  "（= accumulate_grad_batches，micro-batch/optimizer-step 比）")
    if cfg.get("resume_re"):
        try:
            rr = re.compile(cfg["resume_re"])
        except re.error as e:
            _fail(f"resume_re 不是合法 regex：{e}")
        if "gstep" not in rr.groupindex:
            _fail("resume_re 必須含 named group (?P<gstep>\\d+)")
        cfg["_resume_re"] = rr
    else:
        cfg["_resume_re"] = None
    if cfg.get("job_group_re"):
        try:
            cfg["_job_group_re"] = re.compile(cfg["job_group_re"])
        except re.error as e:
            _fail(f"job_group_re 不是合法 regex：{e}")
    else:
        cfg["_job_group_re"] = None
    try:
        step_re = re.compile(cfg.get("step_re") or "")
    except re.error as e:
        _fail(f"step_re 不是合法 regex：{e}")
    if "step" not in step_re.groupindex:
        _fail("step_re 必須含 named group (?P<step>\\d+)")
    try:
        kv_re = re.compile(cfg.get("kv_re") or "")
    except re.error as e:
        _fail(f"kv_re 不是合法 regex：{e}")
    if kv_re.groups != 2:
        _fail("kv_re 必須恰有兩個 capture group：(key, value)")
    charts = cfg.get("charts")
    if not isinstance(charts, list) or not charts:
        _fail("progress.json 缺 charts（至少一張圖）")
    for i, c in enumerate(charts):
        series = c.get("series")
        if not isinstance(series, list) or not series:
            _fail(f"charts[{i}] 缺 series")
        if len(series) > MAX_SERIES_PER_CHART:
            _fail(f"charts[{i}] 有 {len(series)} 條 series——上限 "
                  f"{MAX_SERIES_PER_CHART}（多的請拆成另一張圖，不要共用 y 軸）")
        for s in series:
            if not s.get("key"):
                _fail(f"charts[{i}] 有 series 缺 key")
        nd = c.get("nd")
        if nd is not None and (not isinstance(nd, int) or not 0 <= nd <= 10):
            _fail(f"charts[{i}] 的 nd={nd!r} 不合法（0-10 的整數）")
    global TZ_OFFSET_HOURS, TZ_LABEL
    if cfg.get("tz_offset_hours") is not None:
        try:
            h = int(cfg["tz_offset_hours"])
        except (TypeError, ValueError):
            _fail(f"tz_offset_hours={cfg['tz_offset_hours']!r} 不是整數")
        if not -23 <= h <= 23:
            _fail(f"tz_offset_hours={h} 超出合法範圍（-23 ~ +23）")
        TZ_OFFSET_HOURS = h
        TZ_LABEL = f"UTC{h:+d}"
    else:
        # 每次載入設定重設預設值，避免跨 campaign 使用上一份設定的時區
        TZ_OFFSET_HOURS = 8
        TZ_LABEL = "UTC+8"
    known = {"title", "log_glob", "step_re", "kv_re", "max_x", "x_label",
             "table_every", "max_points", "scheduler", "job_name",
             "footnote", "charts", "runs", "job_group_re", "tz_offset_hours",
             "gstep_re", "gstep_scale", "resume_re"}
    unknown = sorted(user_keys - known)
    if unknown:
        print(f"[progress] 警告：progress.json 有未知欄位 {unknown}——"
              "會被忽略（拼字錯誤？）", file=sys.stderr)
    cfg["_step_re"] = step_re
    cfg["_kv_re"] = kv_re
    return cfg


def _num(value):
    """6 位有效數字（不是小數位）——lr=5e-06 這類小量級指標要存活。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return float(f"{v:.6g}") if math.isfinite(v) else None


def sanitize(obj):
    """遞迴把非有限 float 換成 None——queue.json/ledger.jsonl 可能被手編出
    NaN/Infinity（json.loads 預設收），別讓 allow_nan=False 的 dumps 炸。"""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return obj


def _digit_id(name):
    """name 裡最長的數字串（同長取最後一個）＝raw job id。尾碼 regex 會抓到
    rank/task 編號——slurm-10778323-0.log 的尾碼是 rank「0」不是 job id，
    照它排序/分組會讓所有 rank-0 檔混在一起且新舊顛倒。無數字回 None。
    已知邊界：檔名嵌日期（run-20260709-job-101.out）會誤取日期為 id——
    這種自訂命名請用 job_group_re 指定；與 _attempt_key 同一套規則比
    「各處各一套」重要（同 attempt 的檔案必須相鄰）。"""
    nums = re.findall(r"\d+", name)
    if not nums:
        return None
    best = max(len(n) for n in nums)
    return [n for n in nums if len(n) == best][-1]


def _log_order(relpath):
    """Chronological-ish ordering: raw job id（slurm job id 單調遞增）優先
    ——檔名沒有數字（如 <job>_<task>/train.out）就找上層目錄的 id，
    再退 lexicographic。Later files overwrite earlier steps — pre-emption
    reruns resolve to the newest attempt."""
    d = _digit_id(os.path.basename(relpath))
    if d is None:
        for comp in reversed(relpath.split(os.sep)[:-1]):
            d = _digit_id(comp)
            if d is not None:
                break
    if d is not None:
        return (0, int(d), relpath)
    return (1, 0, relpath)


def _job_group(relpath, group_re):
    """訓練 job 鏈的聚合鍵：同一「任務」的多次嘗試（搶佔/重啟/requeue）
    合成一列。預設規則：路徑中最後一個 <數字>_<數字> 目錄視為 Slurm array
    任務、取 master id；否則退回檔名的 raw job id（= 原本一檔一列的行為）。

    設計限制：若 log 目錄結構以 <array_master>_<task_idx>（不同任務）命名，
    不同 task（e.g. 11111_0 / 11111_1）會被合入同一列。這符合「搶佔→重跑」
    的命名慣例，但與標準 Slurm array 索引語義衝突。有此情境請改用
    progress.json 的 job_group_re（named group "job"）覆寫聚合鍵。"""
    if group_re is not None:
        m = group_re.search(relpath)
        if m:
            return m.group("job") if "job" in m.re.groupindex else m.group(0)
    comps = relpath.split(os.sep)
    for comp in reversed(comps[:-1]):
        m = re.fullmatch(r"(\d+)_\d+", comp)
        if m:
            return m.group(1)
    d = _digit_id(os.path.basename(relpath))
    return d if d is not None else os.path.basename(relpath)


def parse_logs(project_root, cfg, log_glob, gstep_scale=None, gstep_native=False,
               gstep_base=0):
    """Return (train rows by step, per-任務 aggregated job summaries)。
    log_glob 可為 str 或 list（多個 glob 合併掃描——例如把含 checkpoint
    「global step」訊息的 stderr log 一起掃進 gstep 欄）。

    全域軸模式（gstep_re 且該 run 給了 gstep_scale 或 gstep_native）：
    x 軸統一成 optimizer step——log 的訓練計數器每次重啟歸零，因此逐檔
    推 offset（檔內 ckpt 訊息的 gstep 對 位置 的中位差；沒有訊息的檔用
    前一檔的最大全域值＝resume 點），global = offset + micro/scale。
    gstep_native=True 表示該檔的 step 已是全域（如評測點 log），不轉換。"""
    train, jobs = {}, []
    step_re, kv_re = cfg["_step_re"], cfg["_kv_re"]
    gstep_re = cfg.get("_gstep_re")
    resume_re = cfg.get("_resume_re")
    global_mode = gstep_native or (gstep_re is not None and gstep_scale)
    scale = int(gstep_scale) if gstep_scale else 1
    chain_base = int(gstep_base or 0)   # fine-tune/warm-start run 的全域起點
    globs = log_glob if isinstance(log_glob, list) else [log_glob]
    proot = os.path.realpath(project_root)
    paths = []
    for one in globs:
        if os.path.isabs(one):
            _fail("log_glob 必須是相對 project root 的路徑（progress.json 會進"
                  "版控共享，絕對路徑/逸出會把 repo 外的資料發佈到 Pages）")
        for path in glob.glob(os.path.join(project_root, one), recursive=True):
            if not os.path.isfile(path):
                continue
            if not os.path.realpath(path).startswith(proot + os.sep):
                _fail(f"log_glob 對到 project root 之外的檔案：{path}——拒絕"
                      "（防止把 repo 外資料發佈到 Pages）")
            paths.append(path)
    # 全序：raw job id（slurm job id）→ 相對路徑——跨機器/檔案系統穩定，
    # 「較新 job 覆寫較舊」的語義不能靠 glob 的回傳順序
    paths.sort(key=lambda p: _log_order(os.path.relpath(p, proot)))
    # 以「attempt」（同 raw job id 的 slurm+error 等多檔）為掃描單位——
    # ckpt「global step」訊息常在 stderr、訓練行在 stdout，必須同 attempt 關聯
    def _attempt_key(path):
        # attempt＝同一次 job 執行的所有檔案（stdout/stderr/rank 檔）。
        # <master>_<task>/ 這種 slurm array 任務目錄優先：目錄即 attempt——
        # 底下 train-0.out 的「0」是 rank，按 basename 數字會把不同目錄
        # 合成一個 attempt。無 array 目錄才用檔名的 raw job id（最長數字串，
        # slurm-10778323-0.log 取 10778323 不是尾端 rank）；連數字都沒有
        # 就以所在目錄聚合，再不然一檔一 attempt。
        rel = os.path.relpath(path, proot)
        for comp in reversed(rel.split(os.sep)[:-1]):
            if re.fullmatch(r"\d+_\d+", comp):
                return os.path.dirname(rel)
        d = _digit_id(os.path.basename(rel))
        if d is not None:
            return d
        return os.path.dirname(rel) or rel

    attempts, aorder = {}, []
    for path in paths:
        k = _attempt_key(path)
        if k not in attempts:
            attempts[k] = []
            aorder.append(k)
        attempts[k].append(path)

    for akey in aorder:
        first = last = None
        gmax = None
        rstart = None           # resume 行的精確 gstep（「Restored … step=N-last.ckpt」）
        file_rows = {}
        amtime, ats = "—", None
        for path in attempts[akey]:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    for line in f:                  # 串流——多 GB log 不整檔進記憶體
                        if resume_re is not None and rstart is None:
                            rm = resume_re.search(line)
                            if rm:
                                try:
                                    rstart = int(rm.group("gstep"))
                                except ValueError:
                                    pass
                        if gstep_re is not None:
                            gm = gstep_re.search(line)
                            if gm:
                                try:
                                    gv = int(gm.group("gstep"))
                                    gmax = gv if gmax is None else max(gmax, gv)
                                except ValueError:
                                    pass
                        m = step_re.search(line)
                        if not m:
                            continue
                        try:
                            step = int(m.group("step"))
                        except ValueError:
                            continue
                        row = {}
                        for k2, v in kv_re.findall(line):
                            if k2 == "step":
                                continue
                            val = _num(v)
                            if val is not None:
                                row[k2] = val
                        # 逐 key 合併：同 step 多行各留各的指標；雜訊行不清資料
                        (file_rows if global_mode else train).setdefault(step, {}).update(row)
                        first = step if first is None else first
                        last = step
            except OSError:
                continue
            ts = _mtime_ts(path)
            if ts is not None and (ats is None or ts > ats):
                ats = ts
                amtime = _fmt_mtime(ts)
        if global_mode and (file_rows or gstep_native):
            if gstep_native:
                offset = 0.0
            elif rstart is not None:
                # resume 行給出精確起點：計數器從 0 起算 → offset = resume gstep
                offset = float(rstart)
            elif resume_re is not None:
                # 有設 resume_re 卻沒有 resume 行 = 真 fresh start（PTL 只在
                # resume 時印 Restored 行）→ 從 gstep_base（from-scratch=0、
                # warm-start run=其起點）起算，不用鏈估計
                offset = float(gstep_base or 0)
            elif gmax is not None and last is not None:
                # 沒 resume_re 可用時退回：最後一則 ckpt 訊息 ≈ 末段 val 點
                offset = gmax - last / scale
            else:
                offset = float(chain_base)          # 無任何錨：從上次進度接續（估計）
            def to_g(micro):
                return micro if gstep_native else int(round(offset + micro / scale))
            for micro in sorted(file_rows):
                train.setdefault(to_g(micro), {}).update(file_rows[micro])
            if first is not None:
                first, last = to_g(first), to_g(last)
            if last is not None:
                chain_base = max(chain_base, last)
        rel = os.path.relpath(attempts[akey][0], proot)
        jobs.append({"job_id": _job_group(rel, cfg.get("_job_group_re")),
                     "first_step": first, "last_step": last, "gstep": gmax,
                     "resume": rstart, "log_mtime": amtime,
                     "log_mtime_ts": ats})

    # 回推 teardown 存檔：attempt i 無存檔「訊息」但有訓練列，而下一個有
    # resume 行的 attempt 從 R 恢復、且 R 落在 i 的區間內 → 那顆 ckpt 只能是
    # i 存的（resume_if_exists 下 fresh start 代表當時沒有更早的 ckpt）
    for i, j in enumerate(jobs):
        if j["gstep"] is not None or j["first_step"] is None:
            continue
        for k in range(i + 1, len(jobs)):
            nxt = jobs[k]
            if nxt.get("resume") is not None:
                lo = j["first_step"] if j["first_step"] is not None else 0
                # 上下界都要：resume 點超過 i 的最後進度＝那顆 ckpt 不可能是
                # i 存的（只跑到 step 10 的 job 不該被標成 step 100 有存檔）。
                # 非 global mode 時此比較假設 step 軸與 ckpt 步數同域——log
                # 計數器每次重啟歸零的訓練請設 gstep_scale 進 global mode，
                # 否則曲線本身就已錯位，回推寧可保守漏推不捏造
                if lo <= nxt["resume"] and (j["last_step"] is not None
                                            and nxt["resume"] <= j["last_step"]):
                    j["gstep"] = nxt["resume"]
                    j["gstep_inferred"] = True
                break
            if nxt["first_step"] is not None:
                break   # 中間有跑過訓練的 attempt，歸屬不明——不回推

    # 同任務多次嘗試（搶佔/重啟）聚合成一列：step 以最新嘗試為準（paths 已
    # 依「較新覆寫較舊」全序排序）、起始取歷次最早、mtime 取最大
    grouped, order = {}, []
    for j in jobs:
        g = grouped.get(j["job_id"])
        if g is None:
            # cur_first/cur_last＝「最新一次 attempt」自己的 step 區間——ETA 的
            # 速度計算只能用它（group 聚合的 first/last 橫跨多次重啟，除以目前
            # 單一 job 的 elapsed 會高估速度、低估 ETA）
            grouped[j["job_id"]] = {**j, "attempts": 1,
                                    "cur_first": j["first_step"],
                                    "cur_last": j["last_step"]}
            order.append(j["job_id"])
        else:
            g["attempts"] += 1
            if j["first_step"] is not None and (g["first_step"] is None
                                                or j["first_step"] < g["first_step"]):
                g["first_step"] = j["first_step"]
            if j.get("gstep") is not None and (g.get("gstep") is None
                                               or j["gstep"] > g["gstep"]):
                g["gstep"] = j["gstep"]
                g["gstep_inferred"] = j.get("gstep_inferred", False)
            if j["last_step"] is not None and (g["last_step"] is None
                                               or j["last_step"] > g["last_step"]):
                g["last_step"] = j["last_step"]     # 歷次嘗試的最大進度（暖機被砍的
                                                    # 新 attempt 只印 step=0，不該蓋掉）
            newer = (j["log_mtime_ts"] is not None
                     and (g["log_mtime_ts"] is None
                          or j["log_mtime_ts"] > g["log_mtime_ts"]))
            if newer:
                g["log_mtime"] = j["log_mtime"]
                g["log_mtime_ts"] = j["log_mtime_ts"]
            # cur_*＝「最新 attempt」的區間，判準與 log_mtime 一致（mtime 優先、
            # 全缺 mtime 才退列序）——列序與 mtime 不一致時 ETA 才不會用錯 span
            if newer or g["log_mtime_ts"] is None:
                g["cur_first"], g["cur_last"] = j["first_step"], j["last_step"]
    return train, [grouped[k] for k in order]


TZ_OFFSET_HOURS = 8      # 頁面時間戳時區（預設台灣 UTC+8；progress.json tz_offset_hours 可覆寫）
TZ_LABEL = "UTC+8"


def _mtime_ts(path):
    """epoch 秒（float）或 None——「哪個較新」一律用它比；顯示字串截到分鐘，
    同分鐘的兩個 run 用字串比會平手、誤選較舊者。"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _fmt_mtime(ts):
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=TZ_OFFSET_HOURS))
    return datetime.fromtimestamp(ts, tz=tz).strftime(
        f"%Y-%m-%d %H:%M {TZ_LABEL}")


def _mtime_utc(path):
    ts = _mtime_ts(path)
    return "—" if ts is None else _fmt_mtime(ts)


def downsample(steps, target):
    if len(steps) <= target:
        return steps
    stride = math.ceil(len(steps) / target)
    kept = steps[::stride]
    if kept[-1] != steps[-1]:
        kept.append(steps[-1])
    return kept


def scheduler_state(cfg):
    """Best-effort live queue line. Only 'slurm' is supported — the command
    is fixed (never taken from config) so a shared progress.json can't be
    used to run arbitrary commands."""
    if cfg.get("scheduler") != "slurm":
        return None
    import subprocess
    job = cfg.get("job_name")
    if not job:
        return "（scheduler=slurm 但未設 job_name——略過 squeue）"
    try:
        out = subprocess.run(["squeue", "-h", "-n", job, "-o", "%i %T %M %R"],
                             capture_output=True, text=True,
                             timeout=30).stdout.strip()
        return out.splitlines()[0] if out else \
            "佇列中目前沒有訓練 job（續投間隙或鏈已結束）"
    except Exception:
        return "（無法查詢 squeue——頁面由非叢集環境產生）"


def _elapsed_minutes(squeue_line):
    m = re.search(r"\s((?:\d+-)?\d{1,2}:\d{2}(?::\d{2})?)\s",
                  " " + squeue_line + " ")
    if not m:
        return None
    text = m.group(1)
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        days = int(d)
    parts = [int(p) for p in text.split(":")]
    h, mi, s = parts if len(parts) == 3 else (0, parts[0], parts[1])
    return days * 1440 + h * 60 + mi + s / 60


def _fmt(v, nd=3):
    return "—" if v is None else f"{v:.{nd}f}"


def build_payload(root, cfg):
    project_root = os.path.normpath(os.path.join(root, "..", ".."))
    max_pts = int(cfg.get("max_points") or 700)
    every = max(1, int(cfg.get("table_every") or 500))

    keys, seen = [], set()
    for c in cfg["charts"]:
        for s in c["series"]:
            if s["key"] not in seen:
                seen.add(s["key"])
                keys.append(s["key"])
    charts = []
    for c in cfg["charts"]:
        charts.append({
            "title": str(c.get("title") or ""),
            "note": str(c.get("note") or ""),
            "zero": bool(c.get("zero")),
            "nd": 3 if c.get("nd") is None else int(c.get("nd")),
            "refs": [{"y": _num(r.get("y")), "label": str(r.get("label") or "")}
                     for r in (c.get("refs") or []) if _num(r.get("y")) is not None],
            "series": [{"key": s["key"],
                        "label": str(s.get("label") or s["key"]),
                        "color": SERIES_COLORS[i]}
                       for i, s in enumerate(c["series"])]})

    # ---- 每個 run 各自解析（單一 log_glob = 一個匿名 run，向後相容）----
    runs_cfg = cfg.get("runs") or [{"name": "", "log_glob": cfg["log_glob"]}]
    runs, any_seen_keys = [], set()
    for rc in runs_cfg:
        train, jobs = parse_logs(
            project_root, cfg, rc["log_glob"],
            gstep_scale=rc.get("gstep_scale", cfg.get("gstep_scale")),
            gstep_native=bool(rc.get("gstep_native")),
            gstep_base=rc.get("gstep_base", 0))
        steps = sorted(train)
        kept = downsample(steps, max_pts)
        cols = {k: [_num(train[s].get(k)) for s in kept] for k in keys}
        table = ([[s] + [_num(train[s].get(k)) for k in keys]
                  for s in steps if s % every == 0 or s == steps[-1]]
                 if steps else [])
        for r in train.values():
            any_seen_keys.update(r)
        runs.append({"name": str(rc.get("name") or ""),
                     "short": str(rc.get("short") or ""),
                     "attach": str(rc.get("attach") or ""),
                     "desc": str(rc.get("desc") or ""),
                     "purpose": str(rc.get("purpose") or ""),
                     "aux": bool(rc.get("aux")),
                     "job_notes": {str(k): str(v) for k, v in
                                   (rc.get("job_notes") or {}).items()},
                     "x": kept, "cols": cols, "table": table, "jobs": jobs,
                     "last_step": steps[-1] if steps else None,
                     "last_row": train[steps[-1]] if steps else {},
                     "last_mtime": max([j["log_mtime"] for j in jobs
                                        if j["log_mtime"] != "—"] or ["—"]),
                     "last_mtime_ts": max([j["log_mtime_ts"] for j in jobs
                                           if j["log_mtime_ts"] is not None]
                                          or [None])})
    never = [k for k in keys if k not in any_seen_keys]
    if never and any(r["x"] for r in runs):
        print(f"[progress] 警告：charts 引用的指標 {never} 從未出現在 "
              "log 裡（kv_re 抓不到或 key 拼錯？）——該圖會是空的",
              file=sys.stderr)
    # active run = log 最新者（頁面預設顯示、tiles/ETA 依它算）
    for i, r in enumerate(runs):
        host = None
        if r["attach"]:
            for j, h in enumerate(runs):
                if j != i and r["attach"] in h["name"]:
                    host = j
                    break
            if host is None:
                print(f"[progress] 警告：runs[{i}] 的 attach={r['attach']!r} "
                      "對不到任何 run 名稱——當作獨立 run", file=sys.stderr)
        r["attach_to"] = host
    cand = [i for i, r in enumerate(runs) if not r["aux"]] or list(range(len(runs)))
    act = cand[0]
    for i in cand:
        r = runs[i]
        if r["last_mtime_ts"] is not None \
                and (runs[act]["last_mtime_ts"] is None
                     or r["last_mtime_ts"] > runs[act]["last_mtime_ts"]):
            act = i
    A = runs[act]
    steps_last = A["last_step"]
    jobs = A["jobs"]

    squeue = scheduler_state(cfg)
    max_x = cfg.get("max_x")
    rate = eta_h = None
    if squeue and "RUNNING" in squeue and jobs and steps_last is not None and max_x:
        mins = _elapsed_minutes(squeue)
        # 「目前在跑的」＝log 最新的 group；速度用它最新一次 attempt 的
        # cur_first/cur_last（group 聚合的 first/last 橫跨多次重啟，除以單一
        # squeue job 的 elapsed 會高估速度、把 ETA 算得過度樂觀）
        cur = max(enumerate(jobs),
                  key=lambda t: (t[1]["log_mtime_ts"] is not None,
                                 t[1]["log_mtime_ts"] or 0, t[0]))[1]
        # ts 平手（同秒/粗粒度檔案系統）取列序較後者——jobs 依 raw job id
        # 時序排列，後者才是現役 job
        if mins and mins > 5 and cur["cur_first"] is not None \
                and cur["cur_last"] is not None:
            span = cur["cur_last"] - cur["cur_first"]
            if span > 0:
                rate = round(span / mins, 1)
                eta_h = round((max_x - steps_last) / (span / mins) / 60, 1)

    last = A["last_row"]
    tiles = []
    if len(runs) > 1:
        tiles.append({"lab": "最新活動 run", "val": A["name"] or f"run{act+1}",
                      "det": f"log 更新 {A['last_mtime']}"})
    if steps_last is not None and max_x:
        tiles.append({"lab": f"訓練進度（{cfg.get('x_label') or 'step'}）",
                      "val": f"{steps_last:,} / {int(max_x):,}",
                      "det": f"{100 * steps_last / max_x:.1f}%"})
    elif steps_last is not None:
        tiles.append({"lab": f"最新 {cfg.get('x_label') or 'step'}",
                      "val": f"{steps_last:,}", "det": ""})
    for c in charts[:4]:
        s0 = c["series"][0]
        tiles.append({"lab": c["title"] or s0["label"],
                      "val": _fmt(last.get(s0["key"]), c["nd"]),
                      "det": s0["label"] + "（最新）"})
    if rate is not None:
        tiles.append({"lab": "速度 / 預估", "val": f"{rate} step/min",
                      "det": f"剩 ~{eta_h} 純訓練小時" if eta_h else ""})

    queue = None
    try:
        with open(os.path.join(root, "queue.json")) as f:
            queue = json.load(f)
    except (OSError, ValueError):
        pass
    ledger = []
    try:
        with open(os.path.join(root, "ledger.jsonl")) as f:
            ledger = [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        ledger = []
    glossary = {}
    try:
        with open(os.path.join(root, "glossary.json")) as f:
            g = json.load(f)
        if isinstance(g, dict):
            glossary = {str(k): str(v) for k, v in g.items()}
    except (OSError, ValueError):
        pass
    evals = None
    try:
        with open(os.path.join(root, "evals.json")) as f:
            ev = json.load(f)
        # 通用表格 spec：{"title": str, "note": str, "columns": [...], "rows": [[...]]}
        if isinstance(ev, dict) and isinstance(ev.get("columns"), list) \
                and isinstance(ev.get("rows"), list):
            evals = {"title": str(ev.get("title") or "驗證評測"),
                     "note": str(ev.get("note") or ""),
                     "columns": [str(c) for c in ev["columns"]],
                     "rows": [[c for c in r] for r in ev["rows"]
                              if isinstance(r, list)]}
            # 選配：groups=[[名稱,說明],…] 渲染「評測集設定說明」摺疊表；
            # chart={x_col,series_col,value_cols} 為每個 value col 畫分組柱狀圖
            if isinstance(ev.get("groups"), list):
                evals["groups"] = [[str(a), str(b)] for a, b in
                                   (g for g in ev["groups"]
                                    if isinstance(g, list) and len(g) == 2)]
            ch = ev.get("chart")
            if isinstance(ch, dict) and isinstance(ch.get("value_cols"), list):
                evals["chart"] = {"x_col": int(ch.get("x_col", 0)),
                                  "series_col": int(ch.get("series_col", 1)),
                                  "value_cols": [int(v) for v in ch["value_cols"]],
                                  "x_order": [str(x) for x in ch.get("x_order") or []]}
    except (OSError, ValueError):
        pass

    title = str(cfg.get("title") or "").strip()
    if not title:
        mp = os.path.join(root, "MISSION.md")
        if os.path.exists(mp):
            for line in open(mp):
                if line.startswith("# "):
                    title = line[2:].strip().replace("MISSION:", "").strip()
                    break
    return {
        "title": title or "Research Campaign",
        "x_label": str(cfg.get("x_label") or "step"),
        "max_points": max_pts,
        "table_every": every,
        # 頂層 x/cols/table/jobs = active run（單 run 時與舊版完全相同）
        "x": A["x"],
        "cols": A["cols"],
        "keys": keys,
        "charts": charts,
        "tiles": tiles,
        "squeue": squeue,
        "last_mtime": A["last_mtime"],
        "queue": queue,
        "ledger": ledger[-8:],
        "table": A["table"],
        "jobs": jobs,
        "runs": [{"name": r["name"], "short": r["short"], "desc": r["desc"],
                  "purpose": r["purpose"], "attach_to": r["attach_to"],
                  "aux": r["aux"], "job_notes": r["job_notes"],
                  "x": r["x"], "cols": r["cols"],
                  "table": r["table"], "jobs": r["jobs"],
                  "last_step": r["last_step"], "last_mtime": r["last_mtime"],
                  "last_mtime_ts": r["last_mtime_ts"]}
                 for r in runs],
        # 沒設 gstep_re/resume_re＝根本沒在追蹤存檔——job 表不能把 gstep=null
        # 全判成 failed（預設勾選的 hideFailed 會把所有正常 job 藏光）
        "gstep_tracked": bool(cfg.get("_gstep_re") or cfg.get("_resume_re")),
        "active": act,
        "glossary": glossary,
        "evals": evals,
        "footnote": str(cfg.get("footnote") or ""),
    }


TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    color-scheme: light;
    --bg:#f7f7f4; --ink:#1d2528; --muted:#586368; --line:#d9dedb;
    --accent:#126c73; --panel:#ffffff;
    --grid:#e1e0d9; --axis:#c3c2b7; --faint:#898781;
    --good:#0ca30c; --crit:#d03b3b; --run:#2a78d6;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }
  main { width:min(1080px,calc(100% - 32px)); margin:0 auto; padding:40px 0 72px; }
  h1 { font-size:26px; margin:0 0 4px; }
  h2 { font-size:18px; margin:36px 0 12px; }
  .sub { color:var(--muted); margin:0 0 20px; }
  a { color:var(--accent); }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
  .tile { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
  .tile .lab { font-size:12.5px; color:var(--muted); }
  .tile .val { font-size:24px; font-weight:600; margin-top:2px; }
  .tile .det { font-size:12px; color:var(--faint); margin-top:2px; }
  .charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(420px,1fr)); gap:14px; }
  @media (max-width:520px){ .charts{grid-template-columns:1fr;} }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 14px 8px; position:relative; }
  .card h3 { font-size:14.5px; margin:0 0 2px; }
  .card .note { font-size:12px; color:var(--faint); margin:0 0 6px; }
  .legend { display:flex; flex-wrap:wrap; gap:6px 14px; font-size:12.5px; color:var(--muted); margin:4px 0 2px; }
  .evsel-ck { text-align:center; }
  .evsel-ck input { accent-color:#2a78d6; cursor:pointer; }
  .swk { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:7px; vertical-align:-1px; }
  .evsel-bar { display:flex; gap:8px; align-items:center; }
  .evsel-bar button { font:inherit; font-size:12px; padding:2px 10px; border:1px solid var(--line);
           border-radius:8px; background:var(--bg); color:var(--ink); cursor:pointer; }
  .evsel-n { color:var(--muted); font-size:12px; }
  .legend .key { display:inline-block; width:14px; height:2px; vertical-align:middle; margin-right:5px; border-radius:1px; }
  svg text { font:11.5px system-ui,sans-serif; fill:var(--faint); }
  .tt { position:absolute; pointer-events:none; background:var(--panel); border:1px solid var(--line);
        border-radius:8px; padding:8px 10px; font-size:12.5px; box-shadow:0 2px 10px rgba(29,37,40,.12);
        display:none; z-index:5; min-width:130px; }
  .tt .t { color:var(--muted); margin-bottom:4px; }
  .tt .r { display:flex; align-items:center; gap:6px; }
  .tt .r b { font-variant-numeric:tabular-nums; }
  .tt .r span { color:var(--muted); }
  table { border-collapse:collapse; width:100%; background:var(--panel);
          border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:13.5px; }
  th, td { text-align:left; padding:7px 10px; border-top:1px solid var(--line); }
  thead th { border-top:none; background:var(--bg); color:var(--muted); font-weight:600; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .chip { display:inline-block; font-size:12.5px; padding:1px 9px; border-radius:99px; border:1px solid var(--line); white-space:nowrap; }
  .chip.done { color:var(--good); border-color:var(--good); }
  .chip.running { color:var(--run); border-color:var(--run); }
  .chip.pending { color:var(--muted); }
  .chip.failed { color:var(--crit); border-color:var(--crit); }
  details { margin-top:14px; }
  summary { cursor:pointer; color:var(--accent); }
  .runtabs { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 12px; }
  .runtabs button { font:inherit; font-size:13px; padding:5px 12px; border-radius:16px;
    border:1px solid var(--line); background:var(--panel); color:var(--ink); cursor:pointer; }
  .runtabs button.on { background:var(--accent); border-color:var(--accent); color:#fff; }
  .runtabs .live { font-size:11px; opacity:.85; margin-left:4px; }
  [data-tip] { text-decoration:underline dotted; cursor:help; }
  .runtabs button[data-tip] { text-decoration:none; }
  details.fold { margin:0; display:inline; }
  details.fold > summary { color:inherit; }
  details.fold .foldbody { white-space:pre-wrap; margin-top:6px; padding-top:6px;
                           border-top:1px dashed var(--line); color:var(--muted); }
  #mtip { position:fixed; pointer-events:none; background:var(--panel);
          border:1px solid var(--line); border-radius:8px; padding:8px 10px;
          font-size:12.5px; display:none; box-shadow:0 2px 10px rgba(0,0,0,.14);
          max-width:360px; z-index:9; white-space:pre-line; color:var(--muted); }
  .footnote { font-size:12.5px; color:var(--muted); margin-top:28px; border-top:1px solid var(--line); padding-top:14px; }
  .wrap { overflow-x:auto; }
</style>
</head>
<body>
<main>
  <h1 id="pgTitle"></h1>
  <p class="sub"><span id="pgSub"></span> <a href="campaign-report.html">← campaign report</a></p>
  <div class="tiles" id="tiles"></div>
  <h2>訓練曲線</h2>
  <details id="runsInfoWrap" hidden><summary id="runsInfoSummary">run 總覽</summary>
    <div class="wrap" style="margin-top:10px"><table id="runsInfo"></table></div>
  </details>
  <p class="sub" id="runTabsHint" hidden style="margin:14px 0 12px">勾選要疊在曲線上的 run（可多選；滑過按鈕看說明）：</p>
  <div id="runTabs" class="runtabs" hidden></div>
  <details id="moreRunsWrap" hidden><summary id="moreRunsSummary">更早的 run</summary>
    <div id="moreRuns" class="runtabs" style="margin-top:10px"></div>
  </details>
  <div class="charts" id="charts" style="margin-top:12px"></div>
  <details><summary id="tblSummary"></summary>
    <div class="wrap" style="margin-top:10px"><table id="dataTable"></table></div>
  </details>
  <h2 id="evalsH2" hidden></h2>
  <p class="sub" id="evalsNote" hidden></p>
  <details id="evalsGroups" hidden><summary id="evalsGroupsSummary">評測集設定說明</summary>
    <div class="wrap" style="margin-top:10px"><table id="evalsGroupsTable"></table></div>
  </details>
  <div class="charts" id="evalsCharts" style="margin-top:12px"></div>
  <details id="evalsTblWrap" hidden style="margin-top:10px"><summary>驗證評測數據表</summary>
    <div class="wrap" style="margin-top:10px"><table id="evalsTable"></table></div>
  </details>
  <h2>Campaign 實驗階梯</h2>
  <p class="sub">running 平鋪、其餘收合；各 rung 的結論敘事與 gate 判定見
    <a href="campaign-report.html">campaign report</a>。</p>
  <div class="wrap"><table id="ladder"></table></div>
  <details id="ladderRestWrap" hidden><summary id="ladderRestSummary">其他 rung</summary>
    <div class="wrap" style="margin-top:10px"><table id="ladderRest"></table></div>
  </details>
  <h2>Ledger（最近完成的評測決策）</h2>
  <div class="wrap"><table id="ledger"></table></div>
  <details id="glossWrap" hidden><summary>指標說明（表頭/欄名滑過也會顯示）</summary>
    <div class="wrap" style="margin-top:10px"><table id="glossTable"></table></div>
  </details>
  <h2>訓練 job 鏈</h2>
  <details id="jobsWrap"><summary id="jobsSummary">job 鏈明細</summary>
    <p class="sub" id="hideFailedWrap" style="margin-top:10px"><label><input type="checkbox" id="hideFailed" checked>
      隱藏無存檔進度的嘗試（<span id="hiddenN">0</span> 筆——全域 step 空＝沒撐到第一次 checkpoint 的失敗/中斷；運行中的不隱藏）</label></p>
    <div class="wrap"><table id="jobsTable"></table></div>
  </details>
  <p class="footnote" id="foot"></p>
</main>
<div id="mtip"></div>
<script>
const D = __PAYLOAD__;
const fmtK = v => v >= 1000 ? (v/1000).toFixed(v % 1000 === 0 ? 0 : 1) + 'k' : String(v);
const fmt = (v, nd=3) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : (+v).toFixed(nd);
/* 多 run：selected = 勾選要疊圖的 run 集合（預設只有最新活動 run）；
   primary = 資料表顯示哪個 run（最後一個被勾起的） */
const RUNS = (D.runs && D.runs.length) ? D.runs : [{name:'', desc:'', purpose:'', x:D.x, cols:D.cols, table:D.table, jobs:D.jobs, last_mtime:D.last_mtime}];
const PAL = ['#2a78d6','#1baf7a','#eda100','#8073ac','#d6604d','#35978f','#de77ae','#008300'];
let selected = new Set([D.active || 0]);
let primary = D.active || 0;
const runName = i => RUNS[i].name || ('run' + (i+1));
const renderers = [];   // 每張圖的 render()，勾選變動時全部重畫

document.title = D.title + ' — 訓練進度';
document.getElementById('pgTitle').textContent = D.title + ' — 訓練進度';
document.getElementById('pgSub').textContent =
  '由 campaign.py progress 產生 · 曲線／表格皆出自訓練 log 與 ledger ·';
document.getElementById('tblSummary').textContent =
  '資料表（' + D.x_label + ' 為 ' + D.table_every +
  ' 倍數的列＋最後一列 — 無需滑鼠懸停即可讀值）';

/* ---- stat tiles ---- */
document.getElementById('tiles').innerHTML = D.tiles.map(() =>
  '<div class="tile"><div class="lab"></div><div class="val"></div><div class="det"></div></div>').join('');
document.querySelectorAll('#tiles .tile').forEach((el, i) => {
  el.querySelector('.lab').textContent = D.tiles[i].lab;
  el.querySelector('.val').textContent = D.tiles[i].val;
  el.querySelector('.det').textContent = D.tiles[i].det;
});

/* ---- line chart (2px lines, hairline solid grid, crosshair + all-series tooltip) ---- */
function chart(host, cfg){
  const card = document.createElement('div'); card.className = 'card';
  const h3 = document.createElement('h3'); h3.textContent = cfg.title; card.appendChild(h3);
  if (cfg.note){ const p = document.createElement('p'); p.className='note'; p.textContent = cfg.note; card.appendChild(p); }
  const lg = document.createElement('div'); lg.className = 'legend'; card.appendChild(lg);
  const box = document.createElement('div'); card.appendChild(box);
  const tt = document.createElement('div'); tt.className = 'tt'; card.appendChild(tt);
  host.appendChild(card);

  function seriesList(){
    // 疊圖：勾選的每個 run × chart 的每個指標 = 一條線。
    // 沒有任何資料的組合直接略過（不畫線、不佔 legend——例如訓練 run 在
    // 評測圖上、或評測 run 在 loss 圖上），legend 才不會四倍爆長。
    const base = [...selected];
    const sel = [...selected];
    RUNS.forEach((r, i) => {
      if (r.attach_to !== null && r.attach_to !== undefined
          && base.includes(r.attach_to) && !sel.includes(i)) sel.push(i);
    });
    sel.sort((a,b)=>a-b);
    const S = [];
    sel.forEach(ri => cfg.series.forEach(sk => {
      const ys = RUNS[ri].cols[sk.key] || [];
      if (!ys.some(v => typeof v === 'number' && Number.isFinite(v))) return;
      const multiRun = RUNS.length > 1, multiKey = cfg.series.length > 1;
      const tag = RUNS[ri].short || runName(ri);
      let label = sk.label;
      if (multiRun) label = multiKey ? (tag + '·' + sk.label) : tag;
      S.push({run: RUNS[ri], key: sk.key, label,
              color: PAL[S.length % PAL.length]});
    }));
    return S;
  }

  function render(){
    box.textContent = '';
    const S = seriesList();
    lg.textContent = '';
    if (S.length >= 2){
      S.forEach(s => { const it = document.createElement('span');
        const k = document.createElement('i'); k.className = 'key'; k.style.background = s.color;
        it.appendChild(k); it.appendChild(document.createTextNode(s.label)); lg.appendChild(it); });
    }
    const W = Math.max(320, box.clientWidth || card.clientWidth - 28), H = 210;
    const m = {t:12, r:14, b:26, l:52};
    let xmin = Infinity, xmax = -Infinity, vals = [];
    S.forEach(s => {
      const xs = s.run.x;
      if (xs.length){ xmin = Math.min(xmin, xs[0]); xmax = Math.max(xmax, xs[xs.length-1]); }
      vals = vals.concat((s.run.cols[s.key] || []).filter(v => typeof v === 'number' && Number.isFinite(v)));
    });
    (cfg.refs || []).forEach(r => vals.push(r.y));
    if (!Number.isFinite(xmin) || !vals.length){ box.textContent = '（尚無資料）'; return; }
    if (xmax === xmin) xmax = xmin + 1;
    let ymin = Math.min(...vals), ymax = Math.max(...vals);
    if (cfg.zero) ymin = Math.min(0, ymin);
    if (ymax === ymin) ymax = ymin + 1;
    const pad = (ymax - ymin) * 0.08; ymin -= pad; ymax += pad;
    const X = v => m.l + (v - xmin) / (xmax - xmin) * (W - m.l - m.r);
    const Y = v => H - m.b - (v - ymin) / (ymax - ymin) * (H - m.t - m.b);
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    const add = (tag, at) => { const e = document.createElementNS(NS, tag);
      for (const k in at) e.setAttribute(k, at[k]); svg.appendChild(e); return e; };
    const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    for (let i = 0; i <= 4; i++){
      const v = ymin + (ymax - ymin) * i / 4, y = Y(v);
      add('line', {x1:m.l, x2:W-m.r, y1:y, y2:y, stroke:css('--grid'), 'stroke-width':1});
      const tx = add('text', {x:m.l-6, y:y+4, 'text-anchor':'end'});
      tx.textContent = Math.abs(v) >= 1000 ? fmtK(Math.round(v)) : (+v.toFixed(2)).toString();
    }
    for (let i = 0; i <= 4; i++){
      const v = xmin + (xmax - xmin) * i / 4;
      const tx = add('text', {x:X(v), y:H-8, 'text-anchor':'middle'});
      tx.textContent = fmtK(Math.round(v));
    }
    add('line', {x1:m.l, x2:W-m.r, y1:H-m.b, y2:H-m.b, stroke:css('--axis'), 'stroke-width':1});
    (cfg.refs || []).forEach(r => {
      const y = Y(r.y);
      add('line', {x1:m.l, x2:W-m.r, y1:y, y2:y, stroke:css('--faint'), 'stroke-width':1, opacity:.55});
      const tx = add('text', {x:W-m.r, y:y-4, 'text-anchor':'end'}); tx.textContent = r.label;
    });
    S.forEach(s => {
      const xs = s.run.x, ys = s.run.cols[s.key] || [];
      let d = '';
      for (let i = 0; i < xs.length; i++){
        const v = ys[i]; if (v === null || v === undefined || Number.isNaN(v)) continue;
        d += (d ? 'L' : 'M') + X(xs[i]).toFixed(1) + ' ' + Y(v).toFixed(1);
      }
      if (d) add('path', {d, fill:'none', stroke:s.color, 'stroke-width':2,
                          'stroke-linejoin':'round', 'stroke-linecap':'round'});
      for (let i = xs.length - 1; i >= 0; i--){
        const v = ys[i];
        if (v !== null && v !== undefined && !Number.isNaN(v)){
          add('circle', {cx:X(xs[i]), cy:Y(v), r:4, fill:s.color, stroke:'#fff', 'stroke-width':2});
          break;
        }
      }
    });
    const cross = add('line', {x1:0, x2:0, y1:m.t, y2:H-m.b, stroke:css('--axis'),
                               'stroke-width':1, visibility:'hidden'});
    // hover 綁整個 svg（不靠透明 rect 的 hit-test）；每條線各自貼齊最近的點
    svg.style.touchAction = 'none';
    svg.addEventListener('pointermove', ev => {
      const r = svg.getBoundingClientRect();
      const px = Math.min(Math.max(ev.clientX - r.left, m.l), W - m.r);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px);
      cross.setAttribute('visibility', 'visible');
      const xv = xmin + (px - m.l) / (W - m.l - m.r) * (xmax - xmin);
      tt.textContent = '';
      const tl = document.createElement('div'); tl.className = 't';
      tl.textContent = D.x_label + ' ≈ ' + Math.round(xv).toLocaleString('en-US'); tt.appendChild(tl);
      S.forEach(s => {
        const xs = s.run.x; if (!xs.length) return;
        let lo = 0, hi = xs.length - 1;
        while (hi - lo > 1){ const mid = (lo + hi) >> 1; (xs[mid] < xv) ? lo = mid : hi = mid; }
        const i = (Math.abs(xs[lo] - xv) < Math.abs(xs[hi] - xv)) ? lo : hi;
        const row = document.createElement('div'); row.className = 'r';
        const k = document.createElement('i');
        k.style.cssText = 'width:12px;height:2px;background:' + s.color + ';display:inline-block;border-radius:1px;';
        const b = document.createElement('b');
        b.textContent = fmt((s.run.cols[s.key]||[])[i], cfg.nd) + '＠' + fmtK(xs[i]);
        const nm = document.createElement('span'); nm.textContent = s.label;
        row.appendChild(k); row.appendChild(b); row.appendChild(nm); tt.appendChild(row);
      });
      tt.style.display = 'block';
      const cr = card.getBoundingClientRect();
      let tx = ev.clientX - cr.left + 14;
      if (tx + 190 > cr.width) tx = Math.max(4, ev.clientX - cr.left - 200);
      tt.style.left = tx + 'px';
      tt.style.top = (ev.clientY - cr.top - 10) + 'px';
    });
    svg.addEventListener('pointerleave', () => {
      cross.setAttribute('visibility', 'hidden'); tt.style.display = 'none';
    });
    box.appendChild(svg);
  }
  // 首繪延到 rAF：同輪 script 同步塞多張卡片，立刻量 clientWidth 會拿到
  // 「當下只有一張卡」的全行寬 → 首卡溢出破圖（vocodec 同款根因）
  requestAnimationFrame(render);
  renderers.push(render);
  let raf = null;
  window.addEventListener('resize', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(render); });
}
const chartHost = document.getElementById('charts');
D.charts.forEach(c => chart(chartHost, c));

/* ---- tables ---- */
function fillTable(id, header, rows){
  const tb = document.getElementById(id); tb.textContent = '';
  const thead = document.createElement('thead'); const trh = document.createElement('tr');
  header.forEach(h => { const th = document.createElement('th');
    if (typeof h === 'object'){ th.textContent = h.t; if (h.num) th.className = 'num';
      if (h.tip){ th.dataset.tip = h.tip; } }
    else th.textContent = h;
    trh.appendChild(th); });
  thead.appendChild(trh); tb.appendChild(thead);
  const tbody = document.createElement('tbody');
  rows.forEach(r => { const tr = document.createElement('tr');
    r.forEach(c => { const td = document.createElement('td');
      if (c && typeof c === 'object' && c.el){ td.appendChild(c.el); }
      else { const bad = c === null || c === undefined || (typeof c === 'number' && !Number.isFinite(c));
             td.textContent = bad ? '—' : String(c);
             if (typeof c === 'number') td.className = 'num'; }
      tr.appendChild(td); });
    tbody.appendChild(tr); });
  tb.appendChild(tbody);
}
function chipEl(status){
  const icon = {done:'✓', running:'▶', pending:'○', failed:'✗'}[status] || '○';
  const s = document.createElement('span'); s.className = 'chip ' + status;
  s.textContent = icon + ' ' + status; return {el:s};
}
function foldCell(text, head, foldAt){
  // 長文塞 cell 會把整列撐爆（ladder note 實測破萬字）——超過 foldAt 收成
  // details 摺疊：summary 顯前段、點開看全文
  head = head || 110; foldAt = foldAt || 200;
  const t = String(text || '').trim();
  if (!t) return '—';
  if (t.length <= foldAt) return t;
  const d = document.createElement('details'); d.className = 'fold';
  const s = document.createElement('summary');
  s.textContent = t.replace(/\s+/g, ' ').slice(0, head) + '…'; d.appendChild(s);
  const b = document.createElement('div'); b.className = 'foldbody';
  b.textContent = t; d.appendChild(b);
  return {el: d};
}
function fillDataTable(){
  const P = RUNS[primary];
  document.getElementById('tblSummary').textContent =
    '資料表（' + (RUNS.length > 1 ? ('run：' + runName(primary) + '；') : '') +
    D.x_label + ' 為 ' + D.table_every + ' 倍數的列＋最後一列 — 無需滑鼠懸停即可讀值）';
  fillTable('dataTable',
    [D.x_label, ...D.keys.map(k => ({t:k, num:1, tip:(D.glossary||{})[k] || ''}))],
    P.table.map(r => [r[0].toLocaleString('en-US'),
      ...r.slice(1).map(v => (v === null || v === undefined) ? '—' : (+v).toFixed(3))]));
}
function fillJobsTable(){
  // 全部 run 的 job 合併列出，「實驗」欄標明歸屬。
  // 狀態：▶ 運行中（squeue RUNNING 且 log 最新）/ ✓ 有存檔（gstep 有值）/
  //      ✗ 無存檔（沒撐到第一次 checkpoint 的失敗或早期中斷）
  // 未追蹤存檔（無 gstep_re/resume_re）時整個「隱藏失敗」控制與其文案都
  // 不適用——藏起來，別讓使用者以為空 gstep＝失敗
  document.getElementById('hideFailedWrap').style.display = D.gstep_tracked ? '' : 'none';
  const hide = D.gstep_tracked && document.getElementById('hideFailed').checked;
  const allJobs = [];
  RUNS.forEach((r, i) => (r.jobs || []).forEach(j => allJobs.push([r, i, j])));
  let newestMt = -1;   // 數值 ts 比較——顯示字串截到分鐘，同分鐘會平手
  allJobs.forEach(([r, i, j]) => {
    if (j.log_mtime_ts !== null && j.log_mtime_ts !== undefined && j.log_mtime_ts > newestMt)
      newestMt = j.log_mtime_ts;
  });
  const isRunning = j => !!(D.squeue && D.squeue.indexOf('RUNNING') >= 0
                            && j.log_mtime_ts !== null && j.log_mtime_ts !== undefined
                            && j.log_mtime_ts === newestMt);
  const statusOf = j => isRunning(j) ? 'running'
    : !D.gstep_tracked ? 'plain'   // 沒追蹤存檔（無 gstep_re/resume_re）≠ failed
    : ((j.gstep === null || j.gstep === undefined) ? 'failed' : 'done');
  const runCell = i => {
    const sp = document.createElement('span'); sp.textContent = runName(i);
    const tip = [RUNS[i].desc, RUNS[i].purpose].filter(Boolean).join('\n');
    if (tip) sp.dataset.tip = tip;
    return {el: sp};
  };
  const chip = st => {
    const lab = {running:'▶ 運行中', done:'✓ 有存檔', failed:'✗ 無存檔', plain:'—'}[st];
    const sp = document.createElement('span'); sp.className = 'chip ' + (st === 'done' ? 'done' : st);
    sp.textContent = lab; return {el: sp};
  };
  const rows = []; let hidden = 0;
  allJobs.forEach(([r, i, j]) => {
    const st = statusOf(j);
    if (hide && st === 'failed'){ hidden++; return; }
    rows.push([
      runCell(i), j.job_id, chip(st), j.attempts || 1,
      // 起點：resume 行給的是精確 gstep；first_step 是首筆訓練列換算的估計
      (j.resume !== null && j.resume !== undefined) ? j.resume.toLocaleString('en-US')
        : (j.first_step === null ? '—' : j.first_step.toLocaleString('en-US')),
      (j.gstep === null || j.gstep === undefined) ? '—'
        : ((j.gstep_inferred ? '~' : '') + j.gstep.toLocaleString('en-US')),
      j.log_mtime,
      (r.job_notes || {})[j.job_id] ||
        ((r.jobs || []).length > 1 ? '（重啟批次——同實驗多列＝多次 sbatch，由 ckpt 續跑）' : '—')]);
  });
  document.getElementById('hiddenN').textContent = hidden;
  document.getElementById('jobsSummary').textContent =
    'job 鏈明細（' + rows.length + ' 列'
    + (hidden ? '；另 ' + hidden + ' 筆無存檔已隱藏' : '')
    + '——每次 sbatch/重啟的存檔進度稽核，平時免展開）';
  fillTable('jobsTable',
    ['實驗', '任務', '狀態', {t:'嘗試',num:1},
     {t:'起始',num:1, tip:'該任務的起點：log 裡「Restored … step=N-last.ckpt」resume 行的精確值；沒有 resume 行的（真 from-scratch=0，或缺訊息時由前段進度鏈估計）'},
     {t:'最大 step(ckpt)',num:1, tip: D.gstep_tracked
        ? 'checkpoint 存檔的 optimizer step（跨重啟單調的真實進度）。~ 前綴＝由下一個 attempt 的 resume 行回推（scancel/SIGTERM 的 teardown 存檔不印訊息）。空＝該任務真的沒留下任何 ckpt'
        : '未設定 gstep_re/resume_re——本頁沒在追蹤 checkpoint，空值不代表失敗'},
     'log 最後更新', '備註'],
    rows.length ? rows : [['（全部被隱藏或無資料）', '', '', '', '', '', '', '']]);
}
document.getElementById('hideFailed').addEventListener('change', fillJobsTable);
fillDataTable();
/* run 總覽表：每個 exp 的設定差異與實驗目的（收合——21 個 run 的長文表
   擋在曲線前面沒人捲得動；點開備查） */
if (RUNS.length > 1 || RUNS.some(r => r.desc || r.purpose)){
  document.getElementById('runsInfoWrap').hidden = false;
  document.getElementById('runsInfoSummary').textContent =
    'run 總覽（' + RUNS.length + ' 個 run 的設定差異與實驗目的）';
  fillTable('runsInfo', ['實驗', '設定差異', '實驗目的', {t:'最新 step',num:1}, 'log 更新'],
    RUNS.map((r, i) => [runName(i)
      + (i === (D.active||0) ? '（最新活動）' : '')
      + ((r.attach_to !== null && r.attach_to !== undefined)
         ? '（附掛於 ' + (RUNS[r.attach_to].short || runName(r.attach_to)) + '，隨其勾選顯示）' : ''),
      r.desc || '—', r.purpose || '—',
      r.last_step === null ? '—' : r.last_step.toLocaleString('en-US'), r.last_mtime]));
}
/* 多 run 勾選 chips：勾選集合疊在同一張圖；最後點亮的 run = 資料表顯示對象。
   依 log 更新時間新→舊排；前 MAX_TABS 個平鋪，其餘（多半已停/已砍的歷史
   run）收進「更早的 run」折疊區——按鈕文字用 short，全名/設定進 tooltip */
if (RUNS.length > 1){
  const bar = document.getElementById('runTabs'); bar.hidden = false;
  document.getElementById('runTabsHint').hidden = false;
  const MAX_TABS = 6;
  const order = RUNS.map((r, i) => i)
    .filter(i => RUNS[i].attach_to === null || RUNS[i].attach_to === undefined)  // 附掛 run 隨宿主，不單獨列
    .sort((a, b) => (RUNS[b].last_mtime_ts || 0) - (RUNS[a].last_mtime_ts || 0));
  const mkBtn = i => {
    const r = RUNS[i];
    const b = document.createElement('button');
    b.textContent = r.short || runName(i);
    const tip = [r.name, r.desc, r.purpose].filter(Boolean).join('\n');
    if (tip && tip !== b.textContent) b.dataset.tip = tip;
    if (i === (D.active || 0)){
      const s = document.createElement('span'); s.className = 'live';
      s.textContent = '（最新活動）'; b.appendChild(s);
    }
    if (selected.has(i)) b.classList.add('on');
    b.addEventListener('click', () => {
      if (selected.has(i)){
        if (selected.size <= 1) return;         // 至少留一個
        selected.delete(i); b.classList.remove('on');
        if (primary === i) primary = [...selected][0];
      } else {
        selected.add(i); b.classList.add('on'); primary = i;
      }
      renderers.forEach(fn => fn());
      fillDataTable();
    });
    return b;
  };
  order.slice(0, MAX_TABS).forEach(i => bar.appendChild(mkBtn(i)));
  const rest = order.slice(MAX_TABS);
  if (rest.length){
    document.getElementById('moreRunsWrap').hidden = false;
    document.getElementById('moreRunsSummary').textContent =
      '更早的 run（' + rest.length + '——已停/已砍/歷史對照，點開可勾選疊圖）';
    const more = document.getElementById('moreRuns');
    rest.forEach(i => more.appendChild(mkBtn(i)));
  }
}
function barChart(host, title, cats, serNames, matrix, tipOf, colors, autoResize){
  // 分組柱狀圖：cats × series；每根柱 hover 立即顯示（組合, series, 精確值）。
  // colors（選配）＝逐 series 指定色——evals 勾選過濾時各組顏色才不會跳動。
  // autoResize=false：呼叫端自行統一處理 resize（如 evals 每次勾選整批重建，
  // 若每個 instance 都掛 window listener 會隨互動線性累積——review P2）。
  const colorOf = i => (colors && colors[i]) || PAL[i % PAL.length];
  const card = document.createElement('div'); card.className = 'card';
  const h3 = document.createElement('h3'); h3.textContent = title; card.appendChild(h3);
  const lg = document.createElement('div'); lg.className = 'legend';
  serNames.forEach((nm, i) => { const it = document.createElement('span');
    const k = document.createElement('i'); k.className = 'key'; k.style.background = colorOf(i);
    it.appendChild(k); it.appendChild(document.createTextNode(nm)); lg.appendChild(it); });
  if (serNames.length >= 2) card.appendChild(lg);
  const box = document.createElement('div'); card.appendChild(box);
  const tt = document.createElement('div'); tt.className = 'tt'; card.appendChild(tt);
  host.appendChild(card);
  function render(){
    box.textContent = '';
    const W = Math.max(320, box.clientWidth || card.clientWidth - 28), H = 210;
    const m = {t:12, r:12, b:48, l:44};
    let vals = [];
    matrix.forEach(row => row.forEach(v => { if (typeof v === 'number' && Number.isFinite(v)) vals.push(v); }));
    if (!vals.length){ box.textContent = '（無資料）'; return; }
    let ymin = Math.min(0, ...vals);
    let ymax = Math.max(...vals);
    if (ymax <= ymin) ymax = ymin + 1; else ymax *= 1.1;
    const Y = v => H - m.b - (v - ymin) / (ymax - ymin) * (H - m.t - m.b);
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    const add = (tag, at) => { const e = document.createElementNS(NS, tag);
      for (const k in at) e.setAttribute(k, at[k]); svg.appendChild(e); return e; };
    for (let i = 0; i <= 4; i++){
      const v = ymin + (ymax - ymin) * i / 4, y = Y(v);
      add('line', {x1:m.l, x2:W-m.r, y1:y, y2:y, stroke:'#e3e7e3', 'stroke-width':1});
      const tx = add('text', {x:m.l-6, y:y+4, 'text-anchor':'end'});
      tx.textContent = (+v.toFixed(2)).toString();
    }
    const gw = (W - m.l - m.r) / cats.length;
    const bw = Math.min(26, gw * 0.8 / Math.max(1, serNames.length));
    cats.forEach((c, ci) => {
      const gx = m.l + gw * ci + gw / 2;
      serNames.forEach((nm, si) => {
        const v = matrix[si][ci];
        if (v === null || v === undefined || Number.isNaN(v)) return;
        const x = gx - (serNames.length * bw) / 2 + si * bw;
        const rect = add('rect', {x: x, y: Y(v), width: bw - 2,
          height: Math.max(1, H - m.b - Y(v)), fill: colorOf(si), rx: 2});
        rect.addEventListener('pointerenter', ev => {
          tt.textContent = '';
          const tl = document.createElement('div'); tl.className = 't'; tl.textContent = c;
          const row = document.createElement('div'); row.className = 'r';
          const b = document.createElement('b'); b.textContent = (+v.toFixed(4)).toString();
          const s2 = document.createElement('span'); s2.textContent = nm + (tipOf ? '（' + tipOf + '）' : '');
          row.appendChild(b); row.appendChild(s2); tt.appendChild(tl); tt.appendChild(row);
          tt.style.display = 'block';
          const cr = card.getBoundingClientRect();
          let tx2 = ev.clientX - cr.left + 12;
          if (tx2 + 180 > cr.width) tx2 = Math.max(4, ev.clientX - cr.left - 190);
          tt.style.left = tx2 + 'px'; tt.style.top = (ev.clientY - cr.top - 8) + 'px';
        });
        rect.addEventListener('pointerleave', () => { tt.style.display = 'none'; });
      });
      const short = c.length > 20 ? c.slice(0, 19) + '…' : c;
      const rot = cats.length > 4 || cats.some(x => String(x).length > 10);
      const tx = rot
        ? add('text', {x: gx, y: H-26, 'text-anchor':'end',
                       transform: 'rotate(-18 ' + gx + ' ' + (H-26) + ')'})
        : add('text', {x: gx, y: H-22, 'text-anchor':'middle'});
      tx.textContent = short;
    });
    add('line', {x1:m.l, x2:W-m.r, y1:H-m.b, y2:H-m.b, stroke:'#9aa4a0', 'stroke-width':1});
    box.appendChild(svg);
  }
  requestAnimationFrame(render);   // 同上：延後首繪防首卡全寬破圖
  if (autoResize !== false){
    let raf = null;
    window.addEventListener('resize', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(render); });
  }
}
if (D.evals){
  document.getElementById('evalsH2').hidden = false;
  document.getElementById('evalsH2').textContent = D.evals.title;
  if (D.evals.note){ const en = document.getElementById('evalsNote');
    en.hidden = false; en.textContent = D.evals.note; }
  document.getElementById('evalsTblWrap').hidden = false;
  fillTable('evalsTable',
    D.evals.columns.map(c => (D.glossary||{})[c] ? {t:c, tip:D.glossary[c]} : c),
    D.evals.rows);
  if (D.evals.groups && D.evals.groups.length){
    document.getElementById('evalsGroups').hidden = false;
    // 有 chart 時，表格由下方 chart 區塊建（含勾選欄＋色塊），summary 由
    // renderEvals 動態帶勾選計數；無 chart 退回純說明表——別對無圖的設定
    // 宣稱「勾選＝顯示於圖表」
    if (!D.evals.chart){
      fillTable('evalsGroupsTable', ['評測集', '設定'], D.evals.groups);
    }
  }
  if (D.evals.chart){
    const ch = D.evals.chart;
    let cats = [], sers = [];
    D.evals.rows.forEach(r => {
      // 只收「在任一 value 欄有有限值」的列——不同 schema 的評測（如 spk_sim
      // 只有自己的欄位）不會把 '?' 之類的空類別擠進 x 軸
      const hasVal = ch.value_cols.some(vc => typeof r[vc] === 'number' && Number.isFinite(r[vc]));
      if (!hasVal) return;
      if (!cats.includes(String(r[ch.x_col]))) cats.push(String(r[ch.x_col]));
      if (!sers.includes(String(r[ch.series_col]))) sers.push(String(r[ch.series_col]));
    });
    if (ch.x_order && ch.x_order.length){
      const pos = c => { const i = ch.x_order.indexOf(c); return i < 0 ? 999 : i; };
      cats = cats.slice().sort((a, b) => pos(a) - pos(b));
    }
    const evHost = document.getElementById('evalsCharts');
    // ---- 評測集選擇表：設定說明表升級為選擇器（位於圖表上方）----
    // 勾選＝第一欄；色塊併入「評測集」欄（＝該組在圖中的顏色）；25+ 組時靠
    // 勾選過濾，避免全畫擠爆。
    // Object.create(null)：series 名是任意字串——"__proto__" 之類的合法名稱
    // 在普通 object 上會踩到原型 setter（review P3）
    const serColor = Object.create(null); sers.forEach((sn, i) => { serColor[sn] = PAL[i % PAL.length]; });
    // 預設勾選：組少全勾；組多只勾最後 MAX_ON 組（rows 出現序的尾端≈最近
    // 加入的評測集）——幾十組全畫時每根柱寬 <1px，等於白畫
    const MAX_ON = 8;
    const defOn = new Set(sers.length > MAX_ON ? sers.slice(-MAX_ON) : sers);
    const checked = Object.create(null); sers.forEach(sn => { checked[sn] = defOn.has(sn); });
    const descOf = Object.create(null); (D.evals.groups || []).forEach(g => { descOf[String(g[0])] = g[1]; });
    document.getElementById('evalsGroups').hidden = false;
    const gt = document.getElementById('evalsGroupsTable');
    gt.textContent = '';
    const thr = document.createElement('tr');
    [['顯示', '勾選＝畫進下方圖表'], ['評測集', '色塊＝該組在圖中的顏色'], ['設定', '']].forEach(p => {
      const th = document.createElement('th'); th.textContent = p[0];
      if (p[1]) th.dataset.tip = p[1]; thr.appendChild(th); });
    gt.appendChild(thr);
    // 全選/全不選＋計數（跨欄工具列）
    const bar = document.createElement('tr');
    const btd = document.createElement('td'); btd.colSpan = 3;
    const bwrap = document.createElement('div'); bwrap.className = 'evsel-bar';
    const boxes = [];
    const setAll = on => { sers.forEach(sn => { checked[sn] = on; });
      boxes.forEach(b => { b.checked = on; }); renderEvals(); };
    const mkBtn = (txt, fn) => { const b = document.createElement('button');
      b.type = 'button'; b.textContent = txt; b.addEventListener('click', fn); return b; };
    bwrap.appendChild(mkBtn('全選', () => setAll(true)));
    bwrap.appendChild(mkBtn('全不選', () => setAll(false)));
    const pcount = document.createElement('span'); pcount.className = 'evsel-n';
    bwrap.appendChild(pcount); btd.appendChild(bwrap); bar.appendChild(btd); gt.appendChild(bar);
    sers.forEach(sn => {
      const tr = document.createElement('tr');
      const td0 = document.createElement('td'); td0.className = 'evsel-ck';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = checked[sn];
      cb.addEventListener('change', () => { checked[sn] = cb.checked; renderEvals(); });
      boxes.push(cb); td0.appendChild(cb);
      const td1 = document.createElement('td');
      const k = document.createElement('i'); k.className = 'swk';
      k.style.background = serColor[sn];
      td1.appendChild(k); td1.appendChild(document.createTextNode(sn));
      const td2 = document.createElement('td'); td2.textContent = descOf[sn] || '—';
      tr.appendChild(td0); tr.appendChild(td1); tr.appendChild(td2); gt.appendChild(tr);
    });
    // groups 有登記、但圖上沒有任何有限值的組——列出說明但不給勾選
    (D.evals.groups || []).forEach(g => {
      const n = String(g[0]); if (sers.includes(n)) return;
      const tr = document.createElement('tr');
      const td0 = document.createElement('td'); td0.className = 'evsel-ck'; td0.textContent = '—';
      td0.dataset.tip = '此組在圖表指標上沒有數值（不同 schema 或全缺值），僅列說明';
      const td1 = document.createElement('td'); td1.textContent = n;
      const td2 = document.createElement('td'); td2.textContent = g[1] || '—';
      tr.appendChild(td0); tr.appendChild(td1); tr.appendChild(td2); gt.appendChild(tr);
    });
    function renderEvals(){
      evHost.textContent = '';
      const on = sers.filter(sn => checked[sn]);
      pcount.textContent = '顯示 ' + on.length + ' / ' + sers.length + ' 組';
      document.getElementById('evalsGroupsSummary').textContent =
        '評測集選擇與設定說明（已勾 ' + on.length + '/' + sers.length +
        ' 組——點開勾選要畫進圖表的評測集）';
      if (!on.length){ const p = document.createElement('p'); p.className = 'sub';
        p.textContent = '（未勾選任何評測集）'; evHost.appendChild(p); return; }
      ch.value_cols.forEach(vc => {
        const colName = D.evals.columns[vc] || ('col' + vc);
        const matrix = on.map(sn => cats.map(cn => {
          const row = D.evals.rows.find(r => String(r[ch.x_col]) === cn && String(r[ch.series_col]) === sn);
          const v = row ? row[vc] : null;
          return (typeof v === 'number' && Number.isFinite(v)) ? v : null;
        }));
        barChart(evHost, colName, cats, on, matrix,
                 (D.glossary||{})[colName] ? colName : '',
                 on.map(sn => serColor[sn]),    // 勾選增減時各組顏色保持穩定
                 false);                        // resize 由下方統一 listener 處理
      });
    }
    renderEvals();
    // 單一共用 resize listener：整批重建 evals 圖（每張圖自掛 listener 會隨
    // 勾選互動線性累積——review P2）
    let evRaf = null;
    window.addEventListener('resize', () => {
      cancelAnimationFrame(evRaf); evRaf = requestAnimationFrame(renderEvals); });
  }
}
if (D.glossary && Object.keys(D.glossary).length){
  document.getElementById('glossWrap').hidden = false;
  fillTable('glossTable', ['指標', '說明'],
    Object.keys(D.glossary).sort().map(k => [k, D.glossary[k]]));
}
if (D.queue && Array.isArray(D.queue.experiments)){
  // running 平鋪＝「現在在跑什麼」；其餘 rung 收進 details——不能只留連結
  // 指向 report（progress 可單獨 regen，report 缺席時資訊會斷頭），但也
  // 不再平鋪整梯（11K 字 note 全文擋版面）：全量都在、done/pending 摺疊
  const exps = D.queue.experiments;
  const isRun = e => (e.status || 'pending') === 'running';
  const ladderRow = e => [e.id, e.title || '—',
    foldCell([(e.goal || ''), (e.gate || '')].filter(Boolean).join('｜gate：')),
    chipEl(e.status || 'pending'),
    foldCell(e.note || e.notes)];
  const running = exps.filter(isRun), rest = exps.filter(e => !isRun(e));
  if (running.length){
    fillTable('ladder', ['ID', '實驗', '目標 / Gate', '狀態', '備註'],
      running.map(ladderRow));
  } else {
    fillTable('ladder', ['ID'], [['（目前無 running rung）']]);
  }
  if (rest.length){
    document.getElementById('ladderRestWrap').hidden = false;
    document.getElementById('ladderRestSummary').textContent =
      '其他 rung（' + rest.length + '——done/pending 一覽，點開看目標與備註）';
    fillTable('ladderRest', ['ID', '實驗', '目標 / Gate', '狀態', '備註'],
      rest.map(ladderRow));
  }
} else {
  fillTable('ladder', ['ID'], [['（尚無 queue.json）']]);
}
fillTable('ledger', ['實驗', '驗證目標（本列）', '顯著', '決策'],
  (D.ledger || []).length
    ? D.ledger.map(r => [r.experiment, r.purpose || '—',
        r.significant === true ? '是' : (r.significant === false ? '否' : '—'), r.decision || '—'])
    : [['（尚無 ledger 紀錄）', '', '', '']]);
fillJobsTable();

/* 即時 tooltip：所有 [data-tip] 元素（表頭/實驗欄…）滑過立刻顯示 */
(function(){
  const tip = document.getElementById('mtip');
  document.addEventListener('pointerover', ev => {
    const c = ev.target.closest('[data-tip]'); if (!c){ return; }
    tip.textContent = c.dataset.tip; tip.style.display = 'block';
  });
  document.addEventListener('pointermove', ev => {
    if (tip.style.display !== 'block') return;
    if (!ev.target.closest('[data-tip]')){ tip.style.display = 'none'; return; }
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + 380 > window.innerWidth) x = Math.max(8, ev.clientX - 380);
    if (y + 100 > window.innerHeight) y = ev.clientY - 100;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  });
  document.addEventListener('pointerout', ev => {
    if (ev.target.closest && ev.target.closest('[data-tip]')) tip.style.display = 'none';
  });
})();
document.getElementById('foot').textContent =
  (D.squeue ? '目前佇列狀態：' + D.squeue + '｜' : '') +
  'log 最後更新：' + D.last_mtime +
  '｜曲線均勻抽稀至 ≤' + D.max_points + ' 點；資料表取 ' + D.x_label +
  ' 為 ' + D.table_every + ' 倍數的列＋最後一列。' +
  '｜x 軸＝全域 optimizer step：訓練行計數器已按 accumulate 換算並用 log 的 ' +
  '「Restored …step=N-last.ckpt」resume 行精確對位（無 resume 行＝真 from-scratch）。' +
  '｜job 鏈：同任務（Slurm array）多次嘗試已合併一列；「起始」＝resume 行原值、' +
  '「最大 step(ckpt)」＝存檔訊息（含 SIGTERM preemption 存檔）原值，~ 前綴＝由' +
  '下一任務的 resume 點回推；空＝OOM/SIGKILL 來不及存檔。' +
  (D.footnote ? '｜' + D.footnote : '');
</script>
</body>
</html>
"""


def render(root, cfg, out):
    import html as H
    payload = sanitize(build_payload(root, cfg))
    # 把所有 < 換成 \u003c——一次杜絕 </script>、<!--、<script 的
    # script-data 逃逸（比只擋 </ 更強；合法 JSON string escape）
    blob = json.dumps(payload, ensure_ascii=True,
                      allow_nan=False).replace("<", "\\u003c")
    title = H.escape(payload["title"]) + " — 訓練進度"
    # 先以 __PAYLOAD__ 切開模板再各自填 __TITLE__：title 含字面
    # __PAYLOAD__、或 payload 含字面 __TITLE__ 都不會互污
    head, tail = TEMPLATE.split("__PAYLOAD__", 1)
    page = head.replace("__TITLE__", title) + blob \
        + tail.replace("__TITLE__", title)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".hb-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, out)
    return {"written": out, "last_step": payload["x"][-1] if payload["x"] else None,
            "points": len(payload["x"]), "jobs": len(payload["jobs"]),
            "charts": len(payload["charts"])}
