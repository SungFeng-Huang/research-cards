#!/usr/bin/env python3
"""Campaign bookkeeping for the research-campaign skill (thin, stdlib-only).

    campaign.py init   --repo <path> [--rungs E0 E1 ...]   # scaffold runs/auto_research/
    campaign.py status --dir <runs/auto_research>          # queue + ledger summary
    campaign.py ledger-append --dir <...> --json '<row>'   # schema-checked append

The MISSION content itself is authored by the agent+user (see SKILL.md Mode 1);
this tool only owns the mechanical, easy-to-get-wrong parts: scaffolding,
ledger schema, and status math. No third-party dependencies.
"""
import argparse
import json
import os
import sys

# The minimal locked ledger schema — every row must carry these. `metrics` is
# an open dict (campaigns define their own); everything else is free-form.
LEDGER_REQUIRED = ("experiment", "config_hash", "metrics", "significant", "decision")
QUEUE_STATUSES = ("pending", "running", "done", "failed")


def _feature_gate():
    """Soft gate on config features.project — mirrors project-card-log: a
    missing/broken config never blocks (cluster repos may have none)."""
    try:
        here = os.path.dirname(os.path.realpath(__file__))
        sys.path.insert(0, os.path.join(here, "..", "..", "_shared"))
        import hbconfig
        if os.path.exists(hbconfig.CONFIG_PATH) and not hbconfig.feature_enabled("project"):
            sys.exit("project 方向已在 config features.project 停用")
    except SystemExit:
        raise
    except Exception:
        pass


# 常見 ML 大 artifact——`init --git` 生成的起手 .gitignore
GITIGNORE_STARTER = """# research-campaign starter .gitignore（依專案增刪）
checkpoints/
logs/
wandb/
data/
*.pt
*.ckpt
*.safetensors
*.wav
*.npz
runs/**/samples/
__pycache__/
"""


def _bootstrap_git(project_root):
    """把拆分式 project root 升級成 git repo：git init＋起手 .gitignore
    （巢狀 core repo 自動加入排除，維持其獨立版控）。不自動首 commit——
    內容先給使用者過目。"""
    import subprocess
    nested = []
    for name in sorted(os.listdir(project_root)):
        sub = os.path.join(project_root, name)
        if os.path.isdir(os.path.join(sub, ".git")):
            nested.append(name + "/")
    subprocess.run(["git", "init", "-q", project_root], check=True)
    gi = os.path.join(project_root, ".gitignore")
    existing = open(gi).read() if os.path.exists(gi) else ""
    add = GITIGNORE_STARTER
    if nested:
        add += "# 巢狀 core repos（維持獨立版控，不併入本 repo）\n"
        add += "".join(n + "\n" for n in nested)
    with open(gi, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(add)
    return nested


def cmd_init(args):
    """--repo 收任意 project root（不必是 git repo；拆分式佈局把 campaign
    狀態放在非版控的 project root 是預期用法）。--git 把 project root 升級
    成 repo（git init＋起手 .gitignore、巢狀 repo 排除；首 commit 留給
    使用者核可後執行）。"""
    root = os.path.join(os.path.abspath(args.repo), "runs", "auto_research")
    mission = os.path.join(root, "MISSION.md")
    if os.path.exists(mission):
        sys.exit(f"已存在 {mission}——不覆蓋既有任務書（改用編輯，或先手動移除）")
    os.makedirs(root, exist_ok=True)
    tpl = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       "..", "assets", "MISSION.template.md")
    with open(tpl) as f:
        template = f.read()
    with open(mission, "w") as f:
        f.write(template)
    queue = os.path.join(root, "queue.json")
    if not os.path.exists(queue):
        with open(queue, "w") as f:
            json.dump({"experiments": [
                {"id": r, "status": "pending"} for r in (args.rungs or [])
            ]}, f, ensure_ascii=False, indent=2)
    ledger = os.path.join(root, "ledger.jsonl")
    if not os.path.exists(ledger):
        open(ledger, "w").close()
    import subprocess
    proj = os.path.abspath(args.repo)
    in_git = subprocess.run(["git", "-C", proj, "rev-parse",
                             "--is-inside-work-tree"],
                            capture_output=True, text=True).stdout.strip() == "true"
    nested = None
    if not in_git and args.git:
        nested = _bootstrap_git(proj)
        in_git = True
        print(f"[git] 已初始化 {proj} 為 repo；起手 .gitignore 已生成"
              + (f"（排除巢狀 repos：{nested}）" if nested else "")
              + "——請檢視 .gitignore 與 `git status` 後自行首 commit",
              file=sys.stderr)
    elif not in_git:
        print("[note] campaign 目錄不在 git 版控內（拆分式佈局）——斷點續跑靠"
              "檔案系統，跨機器恆久紀錄靠專案卡的 step-7 append；"
              "想升級成 repo 可用 init --git", file=sys.stderr)
    out = {"scaffolded": root,
           "mission": mission,
           "rungs": args.rungs or [],
           "git_tracked": in_git,
           "next": "把核可後的 MISSION 內容寫進 MISSION.md（模板含逐段指引）"}
    if nested is not None:
        out["git_initialized"] = True
        out["nested_repos_ignored"] = nested
    print(json.dumps(out, ensure_ascii=False))


def _load_dir(d):
    root = os.path.abspath(d)
    if not os.path.isdir(root):
        sys.exit(f"找不到 campaign 目錄：{root}（先跑 init）")
    return root


def cmd_status(args):
    root = _load_dir(args.dir)
    out = {"dir": root}
    qp = os.path.join(root, "queue.json")
    if os.path.exists(qp):
        with open(qp) as f:
            exps = json.load(f).get("experiments", [])
        counts = {s: 0 for s in QUEUE_STATUSES}
        for e in exps:
            counts[e.get("status", "pending")] = counts.get(e.get("status", "pending"), 0) + 1
        out["queue"] = counts
        out["running"] = [e["id"] for e in exps if e.get("status") == "running"]
        out["next_pending"] = next((e["id"] for e in exps if e.get("status") == "pending"), None)
    lp = os.path.join(root, "ledger.jsonl")
    rows = []
    if os.path.exists(lp):
        with open(lp) as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    out["ledger_rows"] = len(rows)
    out["recent"] = [{"experiment": r.get("experiment"),
                      "significant": r.get("significant"),
                      "decision": (r.get("decision") or "")[:80]}
                     for r in rows[-args.recent:]]
    bp = os.path.join(root, "BLOCKED.md")
    if os.path.exists(bp):
        with open(bp) as f:
            out["BLOCKED"] = f.read()[:300]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_ledger_append(args):
    root = _load_dir(args.dir)
    try:
        row = json.loads(args.json)
    except json.JSONDecodeError as e:
        sys.exit(f"--json 不是合法 JSON：{e}")
    if not isinstance(row, dict):
        sys.exit("ledger row 必須是 JSON object")
    missing = [k for k in LEDGER_REQUIRED if k not in row]
    if missing:
        sys.exit(f"ledger row 缺必要欄位 {missing}（schema：{list(LEDGER_REQUIRED)}）")
    if not isinstance(row["metrics"], dict):
        sys.exit("metrics 必須是 object（campaign 自訂指標的容器）")
    if not isinstance(row["significant"], bool):
        sys.exit("significant 必須是布林——顯著性 gate 的結論不許含糊")
    if not row.get("playbook_rules_cited"):
        print("[warn] 這行沒有 playbook_rules_cited——超參決策應引用出處",
              file=sys.stderr)
    with open(os.path.join(root, "ledger.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"appended": row["experiment"]}, ensure_ascii=False))


def _url_host(url):
    """抽出 remote URL 的 host（支援 https://、ssh://、scp-like git@host:path、
    含 port 與 user@）。host 以外的 path 不參與判斷——repo 名裡出現
    github/gitlab 字樣不能影響 host 偵測。"""
    u = url.strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    u = u.split("/", 1)[0]
    return u.rsplit("@", 1)[-1].split(":", 1)[0].lower()


def _detect_pages_host(repo, remote):
    import subprocess
    # --push：部署跟著 push 走；沒設 pushurl 時 git 自動回傳 fetch URL
    url = subprocess.run(["git", "-C", repo, "remote", "get-url", "--push",
                          remote], capture_output=True, text=True).stdout.strip()
    if not url:
        return None, url
    host = _url_host(url)
    if "github" in host:
        return "github", url
    if "gitlab" in host:
        return "gitlab", url
    return None, url


def _deploy_branch(proj):
    """github workflow 的觸發分支：優先 default branch（origin/HEAD），
    沒有（剛 init 的 repo）才用當下分支；detached HEAD 或分支名含 YAML
    危險字元時保留 main 並警告。"""
    import re
    import subprocess

    def _sref(ref):
        return subprocess.run(["git", "-C", proj, "symbolic-ref", "--short",
                               ref], capture_output=True, text=True).stdout.strip()

    origin_head = _sref("refs/remotes/origin/HEAD")     # 如 origin/main
    branch = origin_head.split("/", 1)[1] if "/" in origin_head else ""
    if not branch:
        branch = _sref("HEAD")
    if not branch:
        print("[warn] detached HEAD 且無 origin/HEAD——workflow 觸發分支保留 "
              "main，如非 default branch 請手動改", file=sys.stderr)
        return "main"
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        print(f"[warn] 分支名 {branch!r} 含特殊字元——workflow 觸發分支保留 "
              "main，請手動改", file=sys.stderr)
        return "main"
    return branch


def cmd_pages_setup(args):
    """依 git remote 自動選 GitHub Pages（workflow → docs/）或 GitLab
    Pages（.gitlab-ci.yml `pages` job → public/），把選擇記進
    runs/auto_research/pages.json——之後 `report` 未指定 --out 時據此決定
    輸出目錄。--host 可覆寫自動偵測（self-hosted 網域偵測不到時用）。"""
    import shutil
    proj = os.path.abspath(args.repo)
    root = os.path.join(proj, "runs", "auto_research")
    if not os.path.isdir(root):
        sys.exit(f"找不到 {root}——先跑 init")
    host = args.host
    url = ""
    if host == "auto":
        host, url = _detect_pages_host(proj, args.remote)
        if host is None:
            sys.exit(f"remote {args.remote!r} 的 URL（{url or '未設定'}）看不出 "
                     "github/gitlab——用 --host github|gitlab 明講")
    assets = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "assets")
    if host == "github":
        out_dir, ci_dst = "docs", os.path.join(proj, ".github", "workflows", "pages.yml")
        ci_src = os.path.join(assets, "pages-workflow.yml")
        note = "repo Settings → Pages → Source 選 GitHub Actions"
    else:
        out_dir, ci_dst = "public", os.path.join(proj, ".gitlab-ci.yml")
        ci_src = os.path.join(assets, "gitlab-pages.yml")
        note = "GitLab Pages 由 `pages` job 發佈 public/（Settings → Pages 查網址）"
    branch = _deploy_branch(proj)
    ci_body = open(ci_src).read()
    if host == "github" and branch != "main":
        ci_body = ci_body.replace('branches: ["main"]',
                                  f'branches: ["{branch}"]')
    prev_ready = False                            # 重跑不降級手動合併後的標記
    try:
        prev = json.load(open(os.path.join(root, "pages.json")))
        prev_ready = prev.get("host") == host and prev.get("ci_ready") is True
    except (OSError, ValueError):
        pass
    installed = False
    if os.path.exists(ci_dst):
        if open(ci_dst).read() == ci_body:
            installed = True                      # 同內容＝已裝好，冪等
        elif not prev_ready:
            print(f"[note] {ci_dst} 已存在——不覆蓋。請手動合併以下模板，"
                  "完成後把 pages.json 的 ci_ready 改成 true：\n" + ci_body,
                  file=sys.stderr)
    else:
        os.makedirs(os.path.dirname(ci_dst) or ".", exist_ok=True)
        with open(ci_dst, "w") as f:
            f.write(ci_body)
        installed = True
    ci_ready = installed or prev_ready
    with open(os.path.join(root, "pages.json"), "w") as f:
        json.dump({"host": host, "output_dir": out_dir,
                   "ci_ready": ci_ready}, f, ensure_ascii=False)
    print(json.dumps({"host": host, "remote_url": url, "ci_file": ci_dst,
                      "ci_installed": installed, "output_dir": out_dir,
                      "next": note}, ensure_ascii=False))


_REPORT_CSS = """
:root { --bg:#f7f7f4; --ink:#1d2528; --muted:#586368; --line:#d9dedb;
        --ok:#126c73; --warn:#a15c07; --bad:#8c2f39; --panel:#ffffff; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { width:min(1080px,calc(100% - 32px)); margin:0 auto; padding:40px 0 64px; }
h1 { font-size:1.9rem; margin:0 0 4px; } h2 { margin:28px 0 8px; }
p.muted { color:var(--muted); margin:0 0 8px; }
table { border-collapse:collapse; width:100%; background:var(--panel); }
th,td { border:1px solid var(--line); padding:6px 10px; text-align:left;
        vertical-align:top; font-size:.92em; }
th { background:#eef0ec; }
.badge { display:inline-block; padding:1px 8px; border-radius:9px;
         font-size:.85em; color:#fff; }
.b-done{background:var(--ok);} .b-running{background:var(--warn);}
.b-pending{background:#7a848a;} .b-failed{background:var(--bad);}
.b-sig{background:var(--ok);} .b-nosig{background:#7a848a;}
.blocked { border:2px solid var(--bad); background:#fbeeee; padding:10px 14px;
           border-radius:6px; margin:16px 0; white-space:pre-wrap; }
"""


def cmd_report(args):
    """從 MISSION/queue/ledger/BLOCKED 產生單頁靜態 campaign 報告（無相依、
    無時間戳＝輸出確定性，發佈時間交給 git 歷史）。配 assets/
    pages-workflow.yml 即成 GitHub Pages 展示層。"""
    import html as H
    root = _load_dir(args.dir)
    title = "Research Campaign"
    mp = os.path.join(root, "MISSION.md")
    if os.path.exists(mp):
        for line in open(mp):
            if line.startswith("# "):
                title = line[2:].strip().replace("MISSION:", "").strip()
                break
    parts = [f"<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">",
             f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
             f"<title>{H.escape(title)}</title><style>{_REPORT_CSS}</style></head>",
             f"<body><main><h1>{H.escape(title)}</h1>",
             "<p class=\"muted\">campaign report — generated by research-cards "
             "research-campaign（內容以 ledger 為準；顯著性未過 gate 的結果不作宣稱）</p>"]
    bp = os.path.join(root, "BLOCKED.md")
    if os.path.exists(bp):
        parts.append(f"<div class=\"blocked\"><b>BLOCKED</b><br>{H.escape(open(bp).read())}</div>")
    qp = os.path.join(root, "queue.json")
    if os.path.exists(qp):
        with open(qp) as f:
            exps = json.load(f).get("experiments", [])
        parts.append("<h2>Experiment ladder</h2><table><tr><th>Rung</th><th>Status</th></tr>")
        for e in exps:
            st = e.get("status", "pending")
            parts.append(f"<tr><td>{H.escape(str(e.get('id')))}</td>"
                         f"<td><span class=\"badge b-{H.escape(st)}\">{H.escape(st)}</span></td></tr>")
        parts.append("</table>")
    lp = os.path.join(root, "ledger.jsonl")
    rows = []
    if os.path.exists(lp):
        with open(lp) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    parts.append(f"<h2>Ledger（{len(rows)} rows）</h2>")
    if rows:
        parts.append("<table><tr><th>Experiment</th><th>Metrics</th>"
                     "<th>Significant</th><th>Decision</th><th>Playbook cites</th></tr>")
        for r in rows:
            met = "; ".join(f"{H.escape(str(k))}={H.escape(str(v))}"
                            for k, v in (r.get("metrics") or {}).items()) or "—"
            sig = r.get("significant")
            badge = ("<span class=\"badge b-sig\">significant</span>" if sig is True
                     else "<span class=\"badge b-nosig\">not significant</span>")
            cites = "、".join(H.escape(str(c)) for c in (r.get("playbook_rules_cited") or [])) or "—"
            parts.append(f"<tr><td>{H.escape(str(r.get('experiment')))}</td><td>{met}</td>"
                         f"<td>{badge}</td><td>{H.escape(str(r.get('decision') or ''))}</td>"
                         f"<td>{cites}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p class=\"muted\">（尚無評測紀錄）</p>")
    parts.append("</main></body></html>")
    out = args.out
    if out is None:
        out_dir = "docs"
        pj = os.path.join(root, "pages.json")
        if os.path.exists(pj):
            try:
                out_dir = json.load(open(pj)).get("output_dir")
            except (ValueError, OSError) as e:
                sys.exit(f"pages.json 壞了（{e}）——修好或刪掉再跑，"
                         "不靜默回退以免 Pages 無聲停更")
            if out_dir not in ("docs", "public"):
                sys.exit(f"pages.json 的 output_dir={out_dir!r} 不合法"
                         "（只允許 docs|public）——重跑 pages-setup")
        # root = <project>/runs/auto_research → 上兩層是 project root
        out = os.path.normpath(os.path.join(root, "..", "..",
                                            out_dir, "campaign-report.html"))
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write("\n".join(parts) + "\n")
    print(json.dumps({"report": out, "ladder": os.path.exists(qp),
                      "ledger_rows": len(rows)}, ensure_ascii=False))


def main():
    _feature_gate()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="scaffold runs/auto_research/ in a repo")
    p.add_argument("--repo", default=".",
                   help="project root（任意目錄，不必是 git repo）")
    p.add_argument("--git", action="store_true",
                   help="project root 不在版控時，git init＋生成起手 .gitignore"
                        "（巢狀 core repo 自動排除；首 commit 留給使用者）")
    p.add_argument("--rungs", nargs="*", default=None)
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("status", help="queue + ledger summary")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--recent", type=int, default=5)
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("ledger-append", help="schema-checked ledger append")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--json", required=True)
    p.set_defaults(fn=cmd_ledger_append)
    p = sub.add_parser("report", help="ledger/queue -> 靜態 HTML campaign 報告")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--out", default=None,
                   help="輸出路徑（預設依 pages.json 的 output_dir：github→docs/、"
                        "gitlab→public/，未 setup 則 docs/）")
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("pages-setup",
                       help="依 git remote 安裝 GitHub/GitLab Pages 部署設定")
    p.add_argument("--repo", default=".")
    p.add_argument("--remote", default="origin")
    p.add_argument("--host", choices=["auto", "github", "gitlab"], default="auto")
    p.set_defaults(fn=cmd_pages_setup)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
