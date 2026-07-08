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
    if not cfg.get("log_glob"):
        _fail("progress.json 缺 log_glob")
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
    known = {"title", "log_glob", "step_re", "kv_re", "max_x", "x_label",
             "table_every", "max_points", "scheduler", "job_name",
             "footnote", "charts"}
    unknown = sorted(set(cfg) - known)
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


def _log_order(path):
    """Chronological-ish ordering: trailing numeric id (slurm job id) if
    present, else lexicographic. Later files overwrite earlier steps —
    pre-emption reruns resolve to the newest attempt."""
    m = re.search(r"(\d+)(?:\.[^.]*)?$", os.path.basename(path))
    if m:
        return (0, int(m.group(1)), os.path.basename(path))
    return (1, 0, os.path.basename(path))


def parse_logs(project_root, cfg):
    """Return (train rows by step, per-logfile job summaries)."""
    train, jobs = {}, []
    step_re, kv_re = cfg["_step_re"], cfg["_kv_re"]
    if os.path.isabs(cfg["log_glob"]):
        _fail("log_glob 必須是相對 project root 的路徑（progress.json 會進"
              "版控共享，絕對路徑/逸出會把 repo 外的資料發佈到 Pages）")
    proot = os.path.realpath(project_root)
    paths = []
    for path in glob.glob(os.path.join(project_root, cfg["log_glob"]),
                          recursive=True):
        if not os.path.isfile(path):
            continue
        if not os.path.realpath(path).startswith(proot + os.sep):
            _fail(f"log_glob 對到 project root 之外的檔案：{path}——拒絕"
                  "（防止把 repo 外資料發佈到 Pages）")
        paths.append(path)
    # 全序：數字尾碼（slurm job id）→ 相對路徑——跨機器/檔案系統穩定，
    # 「較新 job 覆寫較舊」的語義不能靠 glob 的回傳順序
    paths.sort(key=lambda p: (_log_order(p), os.path.relpath(p, proot)))
    for path in paths:
        first = last = None
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:                      # 串流——多 GB log 不整檔進記憶體
                    m = step_re.search(line)
                    if not m:
                        continue
                    try:
                        step = int(m.group("step"))
                    except ValueError:
                        continue
                    row = {}
                    for k, v in kv_re.findall(line):
                        if k == "step":
                            continue
                        val = _num(v)
                        if val is not None:
                            row[k] = val
                    # 逐 key 合併：同 step 的多行（train 行＋eval 行）各留
                    # 各的指標；跨檔重跑仍是「較新值蓋較舊」；不帶指標的
                    # 雜訊行（如 checkpoint 訊息）不會清空既有資料
                    train.setdefault(step, {}).update(row)
                    first = step if first is None else first
                    last = step
        except OSError:
            continue
        mid = re.search(r"(\d+)(?:\.[^.]*)?$", os.path.basename(path))
        jobs.append({"job_id": mid.group(1) if mid else os.path.basename(path),
                     "first_step": first, "last_step": last,
                     "log_mtime": _mtime_utc(path)})
    return train, jobs


def _mtime_utc(path):
    from datetime import datetime, timezone
    try:
        ts = os.path.getmtime(path)
    except OSError:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")


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
    train, jobs = parse_logs(project_root, cfg)
    steps = sorted(train)
    kept = downsample(steps, int(cfg.get("max_points") or 700))

    def col(key):
        return [_num(train[s].get(key)) for s in kept]

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

    if steps:
        seen_keys = set()
        for r in train.values():
            seen_keys.update(r)
        never = [k for k in keys if k not in seen_keys]
        if never:
            print(f"[progress] 警告：charts 引用的指標 {never} 從未出現在 "
                  "log 裡（kv_re 抓不到或 key 拼錯？）——該圖會是空的",
                  file=sys.stderr)
    squeue = scheduler_state(cfg)
    max_x = cfg.get("max_x")
    rate = eta_h = None
    if squeue and "RUNNING" in squeue and jobs and steps and max_x:
        mins = _elapsed_minutes(squeue)
        cur = jobs[-1]
        if mins and mins > 5 and cur["first_step"] is not None \
                and cur["last_step"] is not None:
            span = cur["last_step"] - cur["first_step"]
            if span > 0:
                rate = round(span / mins, 1)
                eta_h = round((max_x - steps[-1]) / (span / mins) / 60, 1)

    last = train[steps[-1]] if steps else {}
    tiles = []
    if steps and max_x:
        tiles.append({"lab": f"訓練進度（{cfg.get('x_label') or 'step'}）",
                      "val": f"{steps[-1]:,} / {int(max_x):,}",
                      "det": f"{100 * steps[-1] / max_x:.1f}%"})
    elif steps:
        tiles.append({"lab": f"最新 {cfg.get('x_label') or 'step'}",
                      "val": f"{steps[-1]:,}", "det": ""})
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

    every = max(1, int(cfg.get("table_every") or 500))
    table = [[s] + [_num(train[s].get(k)) for k in keys]
             for s in steps if s % every == 0 or s == steps[-1]]

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
        "max_points": int(cfg.get("max_points") or 700),
        "table_every": every,
        "x": kept,
        "cols": {k: col(k) for k in keys},
        "keys": keys,
        "charts": charts,
        "tiles": tiles,
        "squeue": squeue,
        "last_mtime": max([j["log_mtime"] for j in jobs
                           if j["log_mtime"] != "—"] or ["—"]),
        "queue": queue,
        "ledger": ledger[-8:],
        "table": table,
        "jobs": jobs,
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
  .legend { display:flex; gap:14px; font-size:12.5px; color:var(--muted); margin:4px 0 2px; }
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
  <div class="charts" id="charts"></div>
  <details><summary id="tblSummary"></summary>
    <div class="wrap" style="margin-top:10px"><table id="dataTable"></table></div>
  </details>
  <h2>Campaign 實驗階梯</h2>
  <div class="wrap"><table id="ladder"></table></div>
  <h2>Ledger（最近完成的評測決策）</h2>
  <div class="wrap"><table id="ledger"></table></div>
  <h2>訓練 job 鏈</h2>
  <div class="wrap"><table id="jobsTable"></table></div>
  <p class="footnote" id="foot"></p>
</main>
<script>
const D = __PAYLOAD__;
const fmtK = v => v >= 1000 ? (v/1000).toFixed(v % 1000 === 0 ? 0 : 1) + 'k' : String(v);
const fmt = (v, nd=3) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : (+v).toFixed(nd);

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
  if (cfg.series.length >= 2){
    const lg = document.createElement('div'); lg.className = 'legend';
    cfg.series.forEach(s => {
      const it = document.createElement('span');
      const k = document.createElement('i'); k.className = 'key'; k.style.background = s.color;
      it.appendChild(k); it.appendChild(document.createTextNode(s.label)); lg.appendChild(it);
    });
    card.appendChild(lg);
  }
  const box = document.createElement('div'); card.appendChild(box);
  const tt = document.createElement('div'); tt.className = 'tt'; card.appendChild(tt);
  host.appendChild(card);

  function render(){
    box.textContent = '';
    const W = Math.max(320, box.clientWidth || card.clientWidth - 28), H = 210;
    const m = {t:12, r:14, b:26, l:52};
    const xs = D.x, n = xs.length;
    if (!n){ box.textContent = '（尚無資料）'; return; }
    const xmin = xs[0], xmax = xs[n-1] > xmin ? xs[n-1] : xmin + 1;
    let vals = [];
    cfg.series.forEach(s => vals = vals.concat(
      D.cols[s.key].filter(v => typeof v === 'number' && Number.isFinite(v))));
    cfg.refs.forEach(r => vals.push(r.y));
    if (!vals.length){ box.textContent = '（尚無有效資料）'; return; }
    let ymin = Math.min(...vals), ymax = Math.max(...vals);
    if (cfg.zero) ymin = Math.min(0, ymin);
    if (ymax === ymin) ymax = ymin + 1;
    const pad = (ymax - ymin) * 0.08; ymin -= pad; ymax += pad;
    const X = v => m.l + (v - xmin) / (xmax - xmin) * (W - m.l - m.r);
    const Y = v => H - m.b - (v - ymin) / (ymax - ymin) * (H - m.t - m.b);
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    const add = (tag, at, parent) => { const e = document.createElementNS(NS, tag);
      for (const k in at) e.setAttribute(k, at[k]); (parent || svg).appendChild(e); return e; };
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
    cfg.refs.forEach(r => {
      const y = Y(r.y);
      add('line', {x1:m.l, x2:W-m.r, y1:y, y2:y, stroke:css('--faint'), 'stroke-width':1, opacity:.55});
      const tx = add('text', {x:W-m.r, y:y-4, 'text-anchor':'end'}); tx.textContent = r.label;
    });
    cfg.series.forEach(s => {
      const ys = D.cols[s.key];
      let d = '';
      for (let i = 0; i < n; i++){
        const v = ys[i]; if (v === null || Number.isNaN(v)) continue;
        d += (d ? 'L' : 'M') + X(xs[i]).toFixed(1) + ' ' + Y(v).toFixed(1);
      }
      add('path', {d, fill:'none', stroke:s.color, 'stroke-width':2,
                   'stroke-linejoin':'round', 'stroke-linecap':'round'});
      for (let i = n - 1; i >= 0; i--){
        const v = ys[i];
        if (v !== null && !Number.isNaN(v)){
          add('circle', {cx:X(xs[i]), cy:Y(v), r:4, fill:s.color, stroke:'#fff', 'stroke-width':2});
          break;
        }
      }
    });
    const cross = add('line', {x1:0, x2:0, y1:m.t, y2:H-m.b, stroke:css('--axis'),
                               'stroke-width':1, visibility:'hidden'});
    const hit = add('rect', {x:m.l, y:m.t, width:W-m.l-m.r, height:H-m.t-m.b,
                             fill:'transparent'});
    hit.style.touchAction = 'none';
    hit.addEventListener('pointermove', ev => {
      const r = svg.getBoundingClientRect();
      const px = ev.clientX - r.left;
      let lo = 0, hi = n - 1;
      while (hi - lo > 1){ const mid = (lo + hi) >> 1; (X(xs[mid]) < px) ? lo = mid : hi = mid; }
      const i = (px - X(xs[lo]) < X(xs[hi]) - px) ? lo : hi;
      cross.setAttribute('x1', X(xs[i])); cross.setAttribute('x2', X(xs[i]));
      cross.setAttribute('visibility', 'visible');
      tt.textContent = '';
      const tl = document.createElement('div'); tl.className = 't';
      tl.textContent = D.x_label + ' ' + xs[i].toLocaleString('en-US'); tt.appendChild(tl);
      cfg.series.forEach(s => {
        const row = document.createElement('div'); row.className = 'r';
        const k = document.createElement('i');
        k.style.cssText = 'width:12px;height:2px;background:' + s.color + ';display:inline-block;border-radius:1px;';
        const b = document.createElement('b'); b.textContent = fmt(D.cols[s.key][i], cfg.nd);
        const nm = document.createElement('span'); nm.textContent = s.label;
        row.appendChild(k); row.appendChild(b); row.appendChild(nm); tt.appendChild(row);
      });
      tt.style.display = 'block';
      const cr = card.getBoundingClientRect();
      let tx = ev.clientX - cr.left + 14;
      if (tx + 150 > cr.width) tx = ev.clientX - cr.left - 158;
      tt.style.left = tx + 'px';
      tt.style.top = (ev.clientY - cr.top - 10) + 'px';
    });
    hit.addEventListener('pointerleave', () => {
      cross.setAttribute('visibility', 'hidden'); tt.style.display = 'none';
    });
    box.appendChild(svg);
  }
  render();
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
    if (typeof h === 'object'){ th.textContent = h.t; if (h.num) th.className = 'num'; }
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
fillTable('dataTable',
  [D.x_label, ...D.keys.map(k => ({t:k, num:1}))],
  D.table.map(r => [r[0].toLocaleString('en-US'),
    ...r.slice(1).map(v => (v === null || v === undefined) ? '—' : (+v).toFixed(3))]));
if (D.queue && Array.isArray(D.queue.experiments)){
  fillTable('ladder', ['ID', '實驗', '狀態', 'Gate / 備註'],
    D.queue.experiments.map(e => [e.id, e.title || '', chipEl(e.status || 'pending'),
      (e.gate ? e.gate + ' ' : '') + (e.notes ? '｜' + e.notes : '')]));
} else {
  fillTable('ladder', ['ID'], [['（尚無 queue.json）']]);
}
fillTable('ledger', ['實驗', '顯著', '決策'],
  (D.ledger || []).length
    ? D.ledger.map(r => [r.experiment,
        r.significant === true ? '是' : (r.significant === false ? '否' : '—'), r.decision || '—'])
    : [['（尚無 ledger 紀錄）', '', '']]);
fillTable('jobsTable',
  ['Job', {t:'起始',num:1}, {t:'最後',num:1}, 'log 最後更新'],
  D.jobs.length
    ? D.jobs.map(j => [j.job_id,
        j.first_step === null ? '—' : j.first_step.toLocaleString('en-US'),
        j.last_step === null ? '—' : j.last_step.toLocaleString('en-US'), j.log_mtime])
    : [['（log_glob 沒對到任何檔案）', '', '', '']]);

document.getElementById('foot').textContent =
  (D.squeue ? '目前佇列狀態：' + D.squeue + '｜' : '') +
  'log 最後更新：' + D.last_mtime +
  '｜曲線均勻抽稀至 ≤' + D.max_points + ' 點；資料表取 ' + D.x_label +
  ' 為 ' + D.table_every + ' 倍數的列＋最後一列。' +
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
