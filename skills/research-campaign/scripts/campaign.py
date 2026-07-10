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
import re
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
GITIGNORE_STARTER = """# research-campaign starter .gitignore（依專案增刪；
# 附加在你原有規則之後——若上方有 ! 例外規則，請自行調整先後）
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
# Pages 發佈資產是例外——demo 對聽頁的音檔必須被追蹤，否則部署後全 404
!docs/assets/**
!public/assets/**
# demo staging 殘骸（job 被 kill 時遺留）永不入庫——必須排在 assets 例外之後
.demo-staging-*/
# 原子寫入的暫存頁（job 被 kill 時遺留）
.index-*.tmp
.report-*.tmp
.demopage-*.tmp
.css-*.tmp
"""


def _bootstrap_git(project_root):
    """把拆分式 project root 升級成 git repo：git init＋起手 .gitignore
    （巢狀 core repo 自動加入排除，維持其獨立版控）。不自動首 commit——
    內容先給使用者過目。"""
    import subprocess
    nested = []
    for name in sorted(os.listdir(project_root)):
        sub = os.path.join(project_root, name)
        if os.path.exists(os.path.join(sub, ".git")):   # dir 或 file
            nested.append(name + "/")                     # （worktree/submodule 是 .git file）

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
    upgrade_only = False
    if os.path.exists(mission):
        if not args.git:
            sys.exit(f"已存在 {mission}——不覆蓋既有任務書（改用編輯，或先"
                     "手動移除；既有 campaign 要升級成 repo 用 init --git）")
        upgrade_only = True    # 既有 campaign 的 --git 升級：跳過 scaffold
    os.makedirs(root, exist_ok=True)
    if not upgrade_only:
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
    if in_git:
        # 位於某個 repo 內 ≠ campaign 狀態有被版控——祖先 repo 可能
        # ignore 了這個目錄（runs/ 常見於 .gitignore）
        ignored = subprocess.run(["git", "-C", proj, "check-ignore", "-q",
                                  root], capture_output=True).returncode == 0
        if ignored:
            in_git = False
            print("[note] campaign 目錄被外層 repo 的 .gitignore 忽略——"
                  "視同不在版控（per-job commit 蓋不到它）", file=sys.stderr)
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
    if not any(os.path.exists(os.path.join(root, f))
               for f in ("MISSION.md", "queue.json", "ledger.jsonl")):
        sys.exit(f"{root} 不像 campaign 目錄（沒有 MISSION.md/queue.json/"
                 "ledger.jsonl）——--dir 打錯會把帳記到錯的地方，拒絕")
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
                     for r in (rows[-args.recent:] if args.recent > 0 else [])]
    bp = os.path.join(root, "BLOCKED.md")
    if os.path.exists(bp):
        with open(bp) as f:
            out["BLOCKED"] = f.read()[:300]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_ledger_append(args):
    root = _load_dir(args.dir)
    def _no_nan(tok):
        sys.exit(f"ledger row 含 {tok}——指標必須是有限數（NaN/Infinity "
                 "會弄壞下游的 report/progress 頁）")
    try:
        row = json.loads(args.json, parse_constant=_no_nan)
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
        f.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
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
        # .nojekyll：Actions 部署軌其實不經 Jekyll，但日後若把 Pages source 改回
        # branch-deploy，Jekyll 會吃掉底線開頭的路徑——放一顆空檔絕後患（冪等）。
        os.makedirs(os.path.join(proj, "docs"), exist_ok=True)
        open(os.path.join(proj, "docs", ".nojekyll"), "a").close()
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
            print(f"[note] {ci_dst} 與最新模板不同（模板可能已更新，如 LFS "
                  "checkout）——ci_ready 維持 true 不擋部署，但建議手動 diff/"
                  "合併新模板以取得修正", file=sys.stderr)
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


def _load_showcase_css():
    """讀 assets/showcase.css——showcase 頁的唯一風格來源。頁面仍整份內嵌
    （self-contained，file://、artifact browser 都能看）；repo 自製頁則
    <link> 發佈目錄裡由 report 同步出去的副本。"""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "..", "assets", "showcase.css")
    try:
        css = open(path).read()
    except OSError as e:
        sys.exit(f"找不到 showcase.css（{path}）——skill 的 scripts/ 與 assets/ "
                 f"必須成對存在：{e}")
    # 檔頭註解不進頁面
    return re.sub(r"^/\*.*?\*/\n", "", css, count=1, flags=re.S)


_REPORT_CSS = _load_showcase_css()


def _mission_title(root, default="Research Campaign"):
    mp = os.path.join(root, "MISSION.md")
    if os.path.exists(mp):
        for line in open(mp):
            if line.startswith("# "):
                return line[2:].strip().replace("MISSION:", "").strip() or default
    return default


def _publish_dir(root):
    """report/demo/index 的發佈目錄：依 pages.json 的 output_dir（github→docs、
    gitlab→public），未 setup 則 docs。root=<project>/runs/auto_research。"""
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
    return os.path.normpath(os.path.join(root, "..", "..", out_dir))


def _warn_if_page_ignored(path):
    """已寫入的生成頁若被 .gitignore 忽略要出聲（known-open of showcase 2.0）：
    ignored 的 HTML 不進 commit、Pages 上直接 404——而資產若未被忽略反而
    孤兒出貨。只警告不擋（發佈到 repo 外目錄是合法用法）。"""
    import subprocess
    d = os.path.dirname(os.path.abspath(path)) or "."
    try:
        top = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True).stdout.strip()
        if not top:
            return
        ignored = subprocess.run(["git", "-C", top, "check-ignore", "-q",
                                  os.path.abspath(path)],
                                 capture_output=True).returncode == 0
    except OSError:
        return  # best-effort 警告：git 起不來絕不能害已成功的寫頁反報失敗
    if ignored:
        print(f"[warn] 生成頁 {os.path.basename(path)} 被 .gitignore 忽略——"
              "commit 帶不上、Pages 部署後 404（未被忽略的資產會孤兒出貨）。"
              "請在 .gitignore 加例外（如 !docs/**/*.html）", file=sys.stderr)


def _write_index(pub_dir, title):
    """把 pub_dir 裡所有 *.html（除 index.html）整理成 landing index.html：
    卡片式連結格（vocodec 風格）——每頁標題取其 <title>、描述取其
    <meta name="description">（本工具產的頁面都有；手加的頁面沒有就只列
    標題）。campaign-report 排最前、其餘照檔名。deterministic。"""
    import html as H
    from urllib.parse import quote
    ipath = os.path.join(pub_dir, "index.html")
    import fcntl
    import tempfile
    # flock 發佈目錄本身（無鎖檔 artifact）。掃描、組頁、寫入全在臨界區內：
    # 若掃描在鎖外，先掃後寫的程序可能拿舊清單覆蓋較新的 index，讓剛產生
    # 的頁面從 landing 消失。
    dirfd = os.open(pub_dir, os.O_RDONLY)
    try:
        fcntl.flock(dirfd, fcntl.LOCK_EX)
        for fn in os.listdir(pub_dir):
            # 大小寫變體硬拒（known-open of showcase 2.0）：Linux 上
            # Index.html 會與生成的 index.html 並存，checkout 到 Mac 互相
            # 覆蓋；Mac 上寫 index.html 更會直接透過別名覆寫使用者的檔。
            if fn.casefold() == "index.html" and fn != "index.html":
                sys.exit(f"發佈目錄已有 {fn}（與 index.html 只差大小寫）——"
                         "會在大小寫不敏感檔案系統互相覆蓋，請先改名或移除")
        pages = []
        for fn in sorted(os.listdir(pub_dir)):
            if not fn.casefold().endswith(".html") \
                    or fn.casefold() == "index.html":
                continue
            t, desc = fn, ""
            try:
                head = open(os.path.join(pub_dir, fn), encoding="utf-8",
                            errors="replace").read(8192)
                m = re.search(r"<title>(.*?)</title>", head, re.S)
                if m:
                    # <title> 內已是 HTML entities——先解回原文，輸出時再轉義一次
                    t = H.unescape(m.group(1).strip()) or fn
                m = re.search(r'<meta name="description" content="(.*?)">', head, re.S)
                if m:
                    desc = H.unescape(m.group(1).strip())
            except OSError:
                pass
            pages.append((fn, t, desc))
        pages.sort(key=lambda pg: (pg[0] != "campaign-report.html", pg[0]))
        cards = "\n".join(
            f"<a class=\"report\" href=\"{H.escape(quote(fn))}\">"
            f"<strong>{H.escape(t)}</strong>"
            + (f"<span>{H.escape(d)}</span>" if d else "")
            + "</a>"
            for fn, t, d in pages)
        body = (f"<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                f"<title>{H.escape(title)}</title>"
                f"<style>{_REPORT_CSS}</style></head>"
                f"<body><main><p class=\"kicker\">research campaign · showcase</p>"
                f"<h1>{H.escape(title)}</h1>"
                "<p class=\"sub\">靜態展示入口——campaign report 與 demo 隨每個 "
                "job 自動更新；大型 checkpoint 與完整實驗 artifacts 留在 repo，"
                "不在此發佈。</p>"
                f"<div class=\"report-list\">{cards}</div></main></body></html>\n")
        import glob
        for stale in glob.glob(os.path.join(pub_dir, ".index-*.tmp")):
            try:
                os.unlink(stale)   # 前次被 kill 遺留的暫存頁
            except OSError:
                pass
        fd, tmp = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=pub_dir)
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.replace(tmp, ipath)   # 原子換頁
        _warn_if_page_ignored(ipath)
    finally:
        os.close(dirfd)          # close 即釋放 flock
    return [fn for fn, _, _ in pages]


def _pages_out(root, filename):
    """展示層檔案的預設落點：pages.json 的 output_dir（白名單 docs|public、
    壞檔明確失敗不靜默回退），未 setup 則 docs/。root=<project>/runs/
    auto_research → 上兩層是 project root。"""
    return os.path.join(_publish_dir(root), filename)


def _progress_module():
    import importlib.util
    here = os.path.dirname(os.path.realpath(__file__))
    spec = importlib.util.spec_from_file_location(
        "progress_page", os.path.join(here, "progress_page.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_progress_init(args):
    root = _load_dir(args.dir)
    path = os.path.join(root, "progress.json")
    if os.path.exists(path):
        sys.exit(f"已存在 {path}——不覆蓋既有設定（直接編輯它）")
    mod = _progress_module()
    with open(path, "w") as f:
        json.dump(mod.PROGRESS_TEMPLATE, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"scaffolded": path,
                      "next": "填 log_glob/step_re/kv_re/charts（_doc 欄有"
                              "逐項說明），再跑 campaign.py progress"},
                     ensure_ascii=False))


def cmd_progress(args):
    """訓練 log → 進度儀表（曲線/tiles/資料表/ladder/ledger/job 鏈）。"""
    root = _load_dir(args.dir)
    mod = _progress_module()
    cfg = mod.load_progress_config(root)
    if args.scheduler:
        cfg["scheduler"] = args.scheduler
    out = args.out
    if out is None:
        out = _pages_out(root, "campaign-progress.html")
    result = mod.render(root, cfg, os.path.abspath(out))
    report_page = os.path.join(os.path.dirname(os.path.abspath(out)),
                               "campaign-report.html")
    if not os.path.exists(report_page):
        result["hint"] = ("進度頁連到 campaign-report.html 但它還不存在——"
                          "跑一次 campaign.py report（step 7 契約是兩頁一起 regen）")
    print(json.dumps(result, ensure_ascii=False))


def _load_glossary(root):
    """optional runs/auto_research/glossary.json：{指標名: 說明}。壞檔警告不擋。"""
    gp = os.path.join(root, "glossary.json")
    if not os.path.exists(gp):
        return {}
    try:
        g = json.load(open(gp))
        return {str(k): str(v) for k, v in g.items()} if isinstance(g, dict) else {}
    except (ValueError, OSError) as e:
        print(f"[report] 警告：glossary.json 壞了（{e}）——忽略", file=sys.stderr)
        return {}


def _flat_metrics(metrics):
    """ledger metrics 攤平一層（dict 值展成 key.sub），只留有限數值；
    bool 排除（True/False 不是可畫的量）。"""
    import math as _m

    def _fin(x):
        # ledger-append 只擋 NaN/Infinity，不擋合法大整數——float(10**400)
        # 會 OverflowError，不可畫就跳過，別讓 report 整個崩
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
        try:
            f = float(x)
        except OverflowError:
            return None
        return f if _m.isfinite(f) else None

    out = {}
    for k, v in (metrics or {}).items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                f = _fin(sv)
                if f is not None:
                    out[f"{k}.{sk}"] = f
        else:
            f = _fin(v)
            if f is not None:
                out[k] = f
    return out


_REPORT_CHART_JS = r"""
const D = __PAYLOAD__;
const fmtV = v => {
  if (v === null || v === undefined) return '—';
  if (v === 0) return '0';
  const a = Math.abs(v);
  if (a >= 1000) return v.toLocaleString('en-US');
  if (a < 1e-3) return v.toExponential(2);   // 5e-6 這種常見小值不能顯示成 0
  return (+v.toFixed(a < 1 ? 4 : 3)).toString();
};
const host = document.getElementById('ledgerCharts');
if (D.metric_keys.length === 0) {
  host.innerHTML = '<p class="muted">（ledger 尚無出現 ≥2 次的數值指標——單次數值請看下方 Ledger 表）</p>';
}
D.metric_keys.forEach(key => {
  const ys = D.metrics[key];                 // per-rung values (null = 該 rung 沒記這個指標)
  const card = document.createElement('div'); card.className = 'card';
  const h3 = document.createElement('h3'); h3.textContent = key; card.appendChild(h3);
  if (D.glossary[key]) { const p = document.createElement('p'); p.className = 'note';
    p.textContent = D.glossary[key]; card.appendChild(p); }
  const box = document.createElement('div'); card.appendChild(box);
  const tt = document.createElement('div'); tt.className = 'tt'; card.appendChild(tt);
  host.appendChild(card);
  function render(){
    box.textContent = '';
    const idx = [];                          // rung indices that have a value
    ys.forEach((v, i) => { if (v !== null && v !== undefined) idx.push(i); });
    if (!idx.length){ box.textContent = '（無資料）'; return; }
    const W = Math.max(280, box.clientWidth || card.clientWidth - 24), H = 170;
    const m = {t:12, r:12, b:34, l:56};
    const n = D.rungs.length;
    const X = i => n <= 1 ? (m.l + (W - m.l - m.r) / 2)
                          : m.l + i / (n - 1) * (W - m.l - m.r);
    let vals = idx.map(i => ys[i]);
    let ymin = Math.min(...vals), ymax = Math.max(...vals);
    if (ymax === ymin){ ymax += Math.abs(ymax) * 0.1 || 1; ymin -= Math.abs(ymin) * 0.1 || 1; }
    // 半值域運算：[-1e308, 1e308] 這種有限極值直接 ymax-ymin 會溢位成
    // Infinity → NaN 座標；折半後相減保證 finite
    const pad = (ymax / 2 - ymin / 2) * 0.2; ymin -= pad; ymax += pad;
    if (!isFinite(ymin)) ymin = -Number.MAX_VALUE;
    if (!isFinite(ymax)) ymax = Number.MAX_VALUE;
    let hspan = ymax / 2 - ymin / 2;
    if (hspan === 0){   // subnormal underflow（如 ±5e-324 折半歸零）→ 當常數處理
      ymax += Math.abs(ymax) * 0.1 || 1; ymin -= Math.abs(ymin) * 0.1 || 1;
      hspan = ymax / 2 - ymin / 2;
    }
    const Y = v => H - m.b - ((v / 2 - ymin / 2) / hspan) * (H - m.t - m.b);
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    const add = (tag, at) => { const e = document.createElementNS(NS, tag);
      for (const k in at) e.setAttribute(k, at[k]); svg.appendChild(e); return e; };
    for (let g = 0; g <= 3; g++){
      // 線性內插 ymin*(1-f)+ymax*f：不經 span，極值也不溢位
      const f = g / 3, v = ymin * (1 - f) + ymax * f, y = Y(v);
      add('line', {x1:m.l, x2:W-m.r, y1:y, y2:y, stroke:'#e3e7e3', 'stroke-width':1});
      const tx = add('text', {x:m.l-6, y:y+4, 'text-anchor':'end'}); tx.textContent = fmtV(v);
    }
    const lblEvery = Math.max(1, Math.ceil(n / 5));
    D.rungs.forEach((r, i) => {
      if (i % lblEvery && i !== n - 1) return;
      const tx = add('text', {x:X(i), y:H-16, 'text-anchor':'middle'});
      tx.textContent = r.length > 12 ? r.slice(0, 11) + '…' : r;
    });
    add('line', {x1:m.l, x2:W-m.r, y1:H-m.b, y2:H-m.b, stroke:'#9aa4a0', 'stroke-width':1});
    let d = '';
    idx.forEach(i => { d += (d ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(ys[i]).toFixed(1); });
    if (idx.length > 1)
      add('path', {d, fill:'none', stroke:'#2a78d6', 'stroke-width':2,
                   'stroke-linejoin':'round', 'stroke-linecap':'round'});
    idx.forEach(i => add('circle', {cx:X(i), cy:Y(ys[i]), r:4,
                                    fill:'#2a78d6', stroke:'#fff', 'stroke-width':2}));
    const cross = add('line', {x1:0, x2:0, y1:m.t, y2:H-m.b, stroke:'#9aa4a0',
                               'stroke-width':1, visibility:'hidden'});
    // hover 綁在整個 svg（不靠透明 rect 的 hit-test）：找最近「有值」的 rung
    svg.addEventListener('pointermove', ev => {
      const r = svg.getBoundingClientRect();
      const px = Math.min(Math.max(ev.clientX - r.left, m.l), W - m.r);
      let best = idx[0], bd = Infinity;
      idx.forEach(i => { const dd = Math.abs(X(i) - px); if (dd < bd){ bd = dd; best = i; } });
      cross.setAttribute('x1', X(best)); cross.setAttribute('x2', X(best));
      cross.setAttribute('visibility', 'visible');
      tt.textContent = '';
      const tl = document.createElement('div'); tl.className = 't';
      tl.textContent = D.rungs[best]; tt.appendChild(tl);
      const row = document.createElement('div'); row.className = 'r';
      const b = document.createElement('b'); b.textContent = fmtV(ys[best]);
      const nm = document.createElement('span'); nm.textContent = key;
      row.appendChild(b); row.appendChild(nm); tt.appendChild(row);
      tt.style.display = 'block';
      const cr = card.getBoundingClientRect();
      let tx = ev.clientX - cr.left + 14;
      if (tx + 170 > cr.width) tx = Math.max(4, ev.clientX - cr.left - 178);
      tt.style.left = tx + 'px';
      // 卡片 overflow:hidden——游標在圖表下半部時 tooltip 翻到游標上方，免被裁掉
      let ty = ev.clientY - cr.top + 14;
      if (ty + tt.offsetHeight + 6 > cr.height)
        ty = Math.max(4, ev.clientY - cr.top - tt.offsetHeight - 10);
      tt.style.top = ty + 'px';
    });
    svg.addEventListener('pointerleave', () => {
      cross.setAttribute('visibility', 'hidden'); tt.style.display = 'none';
    });
    box.appendChild(svg);
  }
  requestAnimationFrame(render);   // 延後首繪：等所有卡片進 DOM、grid 定寬（防首卡全寬破圖）
  let raf = null;
  window.addEventListener('resize', () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(render); });
});
"""


def cmd_report(args):
    """從 MISSION/queue/ledger/BLOCKED/glossary 產生單頁靜態 campaign 報告
    （無相依、無時間戳＝輸出確定性，發佈時間交給 git 歷史）。內容：
    ladder（含各 rung 的實驗內容/目標/gate）、指標說明（glossary.json）、
    Ledger 指標圖（逐 rung 曲線，游標懸停顯示 rung 與精確值）、Ledger 全表。"""
    import html as H
    root = _load_dir(args.dir)
    title = _mission_title(root)
    gloss = _load_glossary(root)

    def mchip(name, value):
        """Metrics 欄的指標膠囊：游標移上去立刻跳 JS tooltip 顯示指標說明
        （原生 title 有延遲又不明顯——使用者反映「看起來能 hover 但沒顯示」）。"""
        base = name.split(".")[0]
        tip = gloss.get(name) or gloss.get(base) \
            or "（此指標尚無說明——可補進 runs/auto_research/glossary.json）"
        return (f"<span class=\"mchip\" data-tip=\"{H.escape(tip)}\">"
                f"<b>{H.escape(name)}</b>={H.escape(value)}</span>")

    qp = os.path.join(root, "queue.json")
    exps = []
    if os.path.exists(qp):
        with open(qp) as f:
            exps = json.load(f).get("experiments", [])
    lp = os.path.join(root, "ledger.jsonl")
    rows = []
    if os.path.exists(lp):
        with open(lp) as f:
            rows = [json.loads(l) for l in f if l.strip()]
    counts = {st: sum(1 for e in exps if e.get("status", "pending") == st)
              for st in QUEUE_STATUSES}
    next_pending = next((e.get("id") for e in exps
                         if e.get("status") == "pending"), None)
    running = [str(e.get("id")) for e in exps if e.get("status") == "running"]
    bp = os.path.join(root, "BLOCKED.md")
    desc = (f"ladder {counts['done']}/{len(exps)} done"
            + (f"（running：{'、'.join(running)}）" if running else "")
            + f" · ledger {len(rows)} rows"
            + (f" · next：{next_pending}" if next_pending else "")
            + ("｜⚠ BLOCKED" if os.path.exists(bp) else ""))
    parts = [f"<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">",
             f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
             f"<title>{H.escape(title)}</title>",
             f"<meta name=\"description\" content=\"{H.escape(desc)}\">",
             f"<style>{_REPORT_CSS}</style></head>",
             f"<body><main><p class=\"kicker\">research campaign · progress</p>",
             f"<h1>{H.escape(title)}</h1>",
             "<p class=\"sub\"><a href=\"index.html\">← 首頁</a>"
             + ("　·　<a href=\"campaign-progress.html\">訓練進度儀表</a>"
                if os.path.exists(os.path.join(root, "progress.json")) else "")
             + " · 內容以 ledger 為準；顯著性未過 gate 的結果不作宣稱，"
               "not-significant rows 照登。</p>"]
    # 狀態磚：一眼掌握 ladder/帳本現況
    tiles = []
    for st in QUEUE_STATUSES:
        det = "、".join(str(e.get("id")) for e in exps
                        if e.get("status", "pending") == st)
        tiles.append(f"<div class=\"tile\"><div class=\"lab\">{st}</div>"
                     f"<div class=\"val\">{counts[st]}</div>"
                     + (f"<div class=\"det\">{H.escape(det)}</div>" if det else "")
                     + "</div>")
    tiles.append(f"<div class=\"tile\"><div class=\"lab\">ledger rows</div>"
                 f"<div class=\"val\">{len(rows)}</div>"
                 + (f"<div class=\"det\">next：{H.escape(str(next_pending))}</div>"
                    if next_pending else "") + "</div>")
    parts.append(f"<div class=\"tiles\">{''.join(tiles)}</div>")
    if os.path.exists(bp):
        parts.append(f"<div class=\"blocked\"><b>BLOCKED</b><br>"
                     f"{H.escape(open(bp).read())}</div>")
    if exps:
        parts.append("<h2>Experiment ladder</h2>"
                     "<p class=\"muted\">每個 rung＝一個受 gate 把關的實驗階段，"
                     "由上而下依序推進；gate 未過不啟用下一階。</p>"
                     "<div class=\"wrap\"><table><tr><th>Rung</th><th>實驗內容</th>"
                     "<th>目標 / Gate</th><th>狀態</th><th>備註</th></tr>")
        for e in exps:
            st = e.get("status", "pending")
            goal = " ".join(x for x in [str(e.get("goal") or "").strip(),
                                        str(e.get("gate") or "").strip()] if x) or "—"
            note = str(e.get("note") or e.get("notes") or "").strip() or "—"
            parts.append(f"<tr><td>{H.escape(str(e.get('id')))}</td>"
                         f"<td>{H.escape(str(e.get('title') or '—'))}</td>"
                         f"<td>{H.escape(goal)}</td>"
                         f"<td><span class=\"chip {H.escape(st)}\">{H.escape(st)}"
                         f"</span></td>"
                         f"<td>{H.escape(note)}</td></tr>")
        parts.append("</table></div>")

    # ---- 指標說明（glossary，收合——指標膠囊滑過即顯示，同內容備查）----
    if gloss:
        parts.append(f"<details><summary>指標說明（{len(gloss)} 項——ledger 的"
                     "指標膠囊與各表欄名滑過即顯示，此表僅備查）</summary>"
                     "<table style=\"margin-top:10px\"><tr><th>指標</th><th>說明</th></tr>")
        for k in sorted(gloss):
            parts.append(f"<tr><td>{H.escape(k)}</td>"
                         f"<td>{H.escape(gloss[k])}</td></tr>")
        parts.append("</table></details>")

    # ---- Ledger 指標圖（逐 rung；hover 顯示 rung＋精確值）----
    chart_keys = []
    if rows:
        rung_labels, flat_rows = [], []
        seen_lbl = {}
        for r in rows:
            lbl = str(r.get("experiment") or "?")
            seen_lbl[lbl] = seen_lbl.get(lbl, 0) + 1
            if seen_lbl[lbl] > 1:
                lbl = f"{lbl}#{seen_lbl[lbl]}"
            rung_labels.append(lbl)
            flat_rows.append(_flat_metrics(r.get("metrics")))
        kcounts = {}
        for fr in flat_rows:
            for k in fr:
                kcounts[k] = kcounts.get(k, 0) + 1
        chart_keys = sorted(k for k, c in kcounts.items() if c >= 2)
        payload = {"rungs": rung_labels,
                   "metric_keys": chart_keys,
                   "metrics": {k: [fr.get(k) for fr in flat_rows] for k in chart_keys},
                   "glossary": gloss}
        parts.append("<h2>Ledger 指標圖（逐 rung）</h2>"
                     "<p class=\"muted\">出現 ≥2 次的數值指標各成一張小圖；"
                     "游標懸停顯示該點的 rung 名與精確值（指標定義見上方指標說明）。</p>"
                     "<div class=\"charts\" id=\"ledgerCharts\"></div>")
        # 所有 < 換 <——杜絕 experiment/metric 名/glossary 內容夾帶
        # </script> 的 script-data 逃逸（合法 JSON escape；ensure_ascii 同時
        # 中和 U+2028/2029 行分隔符）。與 progress_page.render 同手法。
        blob = json.dumps(payload, ensure_ascii=True,
                          allow_nan=False).replace("<", "\\u003c")
        parts.append("<script>" +
                     _REPORT_CHART_JS.replace("__PAYLOAD__", blob) +
                     "</script>")

    # ---- Ledger 全表（experiment id 依 rung 前綴對應 ladder 的內容/目標）----
    def rung_meta(expid):
        """ledger 的 experiment id（如 E1-launch）→ 最長前綴對應的 ladder rung。
        前綴後一字元不得是英數，避免 E1 誤配 E11。"""
        best = None
        for e in exps:
            rid = str(e.get("id") or "")
            if not rid:
                continue
            if expid == rid or (expid.startswith(rid)
                                and not expid[len(rid):len(rid) + 1].isalnum()):
                if best is None or len(rid) > len(str(best.get("id"))):
                    best = e
        return best

    parts.append(f"<h2>Ledger（{len(rows)} rows）</h2>"
                 "<p class=\"muted\">「驗證目標」＝該列所屬 rung 要驗證的事——"
                 "significant/decision 都是相對這個目標在說話；experiment 名稱"
                 "滑過可看 rung 完整內容與 gate。</p>")
    if rows:
        parts.append("<div class=\"wrap\"><table><tr><th>Experiment</th>"
                     "<th>驗證目標</th><th>Metrics</th>"
                     "<th>Significant</th><th>Decision</th><th>Playbook cites</th></tr>")
        for r in rows:
            met = " ".join(mchip(str(k), str(v))
                           for k, v in (r.get("metrics") or {}).items()) or "—"
            sig = r.get("significant")
            chip = ("<span class=\"chip sig\">significant</span>" if sig is True
                    else "<span class=\"chip nosig\">not significant</span>")
            cites = "、".join(H.escape(str(c))
                              for c in (r.get("playbook_rules_cited") or [])) or "—"
            expid = str(r.get("experiment"))
            rm = rung_meta(expid)
            sub = str(r.get("purpose") or "").strip()   # 本列在 rung 中的子實驗角色（選配欄位）
            if rm or sub:
                lines = []
                if rm:
                    rid = str(rm.get("id"))
                    lines.append(f"{rid}（rung）：" + "｜".join(
                        x for x in [str(rm.get("title") or ""),
                                    str(rm.get("goal") or ""),
                                    ("gate：" + str(rm.get("gate"))) if rm.get("gate") else ""] if x))
                lines.append(f"本列（{expid}）：" + (sub or "（此列未標子實驗角色——ledger row 可加 purpose 欄位）"))
                tip = "\n".join(lines)
                expcell = (f"<span class='mchip' data-tip='{H.escape(tip)}'>"
                           f"<b>{H.escape(expid)}</b></span>")
                goal_cell = H.escape(str((rm or {}).get("title") or "—"))
            else:
                expcell, goal_cell = H.escape(expid), "—"
            parts.append(f"<tr><td>{expcell}</td><td>{goal_cell}</td><td>{met}</td>"
                         f"<td>{chip}</td><td>{H.escape(str(r.get('decision') or ''))}</td>"
                         f"<td>{cites}</td></tr>")
        parts.append("</table></div>")
    else:
        parts.append("<p class=\"muted\">（尚無評測紀錄）</p>")
    # metrics 膠囊的即時 tooltip（全頁共用一個 #mtip，fixed 定位跟著游標）
    parts.append("""<div id="mtip"></div><script>
(function(){
  const tip = document.getElementById('mtip');
  document.addEventListener('pointerover', ev => {
    const c = ev.target.closest('.mchip'); if (!c) return;
    tip.innerHTML = '';
    const k = document.createElement('div'); k.className = 'k';
    k.textContent = c.querySelector('b') ? c.querySelector('b').textContent : '';
    const d = document.createElement('div'); d.className = 'd';
    d.textContent = c.dataset.tip || '';
    tip.appendChild(k); tip.appendChild(d); tip.style.display = 'block';
  });
  document.addEventListener('pointermove', ev => {
    if (tip.style.display !== 'block') return;
    if (!ev.target.closest('.mchip')){ tip.style.display = 'none'; return; }
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + 360 > window.innerWidth) x = Math.max(8, ev.clientX - 360);
    if (y + 90 > window.innerHeight) y = ev.clientY - 90;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  });
  document.addEventListener('pointerout', ev => {
    if (ev.target.closest && ev.target.closest('.mchip')) tip.style.display = 'none';
  });
})();
</script>""")
    parts.append("<p class=\"footnote\">campaign report — generated by "
                 "research-cards research-campaign；發佈時間見 git 歷史（頁面"
                 "無時間戳＝輸出確定性）。</p>")
    parts.append("</main></body></html>")
    out = args.out
    if out is None:
        out = _pages_out(root, "campaign-report.html")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    import fcntl
    import glob
    import tempfile
    outdir = os.path.dirname(out)
    # flock 輸出目錄：清理殘留與寫入/換頁同鎖——無鎖的 glob unlink 會刪掉
    # 並行 report 仍開著的暫存檔，害對方 os.replace FileNotFoundError
    _rlock = os.open(outdir, os.O_RDONLY)
    try:
        fcntl.flock(_rlock, fcntl.LOCK_EX)
        for stale in glob.glob(os.path.join(outdir, ".report-*.tmp")):
            try:
                os.unlink(stale)   # 前次被 kill 遺留的暫存頁
            except OSError:
                pass
        fd, tmp = tempfile.mkstemp(prefix=".report-", suffix=".tmp", dir=outdir)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(parts) + "\n")
        os.replace(tmp, out)   # 原子換頁
        _warn_if_page_ignored(out)
        # 同步 showcase.css 到發佈目錄——repo 自製頁 <link> 它即得同套視覺
        css_dst = os.path.join(outdir, "showcase.css")
        fd, tmp = tempfile.mkstemp(prefix=".css-", suffix=".tmp", dir=outdir)
        with os.fdopen(fd, "w") as f:
            f.write(_REPORT_CSS)
        os.replace(tmp, css_dst)
    finally:
        os.close(_rlock)
    idx = None
    # --out 指到 index.html 時不 regen index——否則剛寫好的報告會被 landing 頁蓋掉
    if not getattr(args, "no_index", False) \
            and os.path.basename(out).casefold() != "index.html":
        idx = _write_index(os.path.dirname(out), title)
    print(json.dumps({"report": out, "ladder": os.path.exists(qp),
                      "ledger_rows": len(rows), "charts": len(chart_keys),
                      "glossary": len(gloss),
                      "index_pages": idx}, ensure_ascii=False))


def cmd_demo(args):
    """從 manifest 產音檔對聽頁（A/B 或多系統並排），音檔複製進發佈目錄的
    **版本化**資產目錄 assets/<name>-<ver8>/（ver8＝manifest＋來源檔指紋），
    頁面指向新版本後才清舊版本——中途被 SIGKILL 只會留下孤兒目錄（下次執行
    清除），舊頁面永遠指向仍存在的舊資產。並 regen index。manifest JSON：

      {"title": "stride=1 vs offline 對聽",
       "systems": ["original", "stride1", "offline"],
       "utterances": [
         {"id": "utt-001",
          "audio": {"original": "path/a.wav", "stride1": "path/b.wav"},
          "note": "（選填）人耳備註"}]}

    音檔路徑相對於 manifest 所在目錄（或絕對路徑）。頁面 self-contained、
    <audio preload="none">（不預載，音檔多也不炸流量）、無時間戳（輸出確定
    性）。紀律：對聽頁是「素材」，勝出宣稱以 report 的顯著性 gate 為準。"""
    import html as H
    import shutil
    root = _load_dir(args.dir)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.name) \
            or args.name in (".", ".."):
        sys.exit(f"--name {args.name!r} 不合法（限 [A-Za-z0-9._-] 且不可為 . 或 ..，"
                 "會成為 assets 目錄名）")
    if args.name.casefold() in ("index", "campaign-report"):
        sys.exit(f"--name {args.name!r} 保留給 landing 頁／report——換個名字")
    if args.name.startswith(".demo-staging-"):
        sys.exit(f"--name {args.name!r} 撞到 staging 保留前綴——會被殘骸清理刪除"
                 "且被 .gitignore 忽略，換個名字")
    if re.search(r"-[0-9a-f]{8}$", args.name):
        sys.exit(f"--name {args.name!r} 以 -<8位hex> 結尾——會與版本化資產目錄"
                 "（<name>-<ver8>）的清理樣式互撞，換個名字")
    try:
        man = json.load(open(args.manifest))
    except (OSError, ValueError) as e:
        sys.exit(f"manifest 讀取失敗（{args.manifest}）：{e}")
    # 結構驗證先行：systems 誤寫成字串會被逐字元迭代、非 object 的
    # utterance/audio 會半路 TypeError——都在這裡一次擋掉
    if not isinstance(man, dict):
        sys.exit("manifest top-level 必須是 JSON object")
    if not isinstance(man.get("systems"), list) \
            or not isinstance(man.get("utterances"), list):
        sys.exit("manifest 的 systems 與 utterances 必須是 list")
    systems = [str(s) for s in man["systems"]]
    utts = man["utterances"]
    if not systems or not utts:
        sys.exit("manifest 需要 systems（欄）與 utterances（列）")
    for i, u in enumerate(utts):
        if not isinstance(u, dict):
            sys.exit(f"utterances[{i}] 必須是 object")
        if u.get("audio") is not None and not isinstance(u["audio"], dict):
            sys.exit(f"utterances[{i}].audio 必須是 object（系統名→路徑）")
        for s, p in (u.get("audio") or {}).items():
            if not isinstance(p, str):
                sys.exit(f"utterances[{i}].audio[{s!r}] 必須是路徑字串")
            if s not in set(systems):
                sys.exit(f"utterances[{i}].audio 含未知 system {s!r}"
                         f"（不在頂層 systems {systems}）——拼錯會被靜默忽略，"
                         "先修 manifest")
    # 檔名正規化後的 system 名不得碰撞（stride=1 與 stride-1 都會變 stride-1，
    # 兩欄就會播到同一顆檔案）
    safe_names = {}
    for s in systems:
        safe = re.sub(r"[^A-Za-z0-9._-]", "-", s)
        if safe in safe_names:
            sys.exit(f"systems {safe_names[safe]!r} 與 {s!r} 正規化後同名"
                     f"（{safe}）——改 system 名以免兩欄播同一檔")
        safe_names[safe] = s
    pub = _publish_dir(root)
    assets_root = os.path.join(pub, "assets")
    man_real = os.path.realpath(os.path.abspath(args.manifest))
    ar_real = os.path.realpath(assets_root)
    if man_real == ar_real or man_real.startswith(ar_real + os.sep):
        sys.exit(f"manifest 位於發佈資產目錄 {assets_root} 內——版本清理可能"
                 "把它刪掉。請放在該目錄之外再跑")
    mdir = os.path.dirname(os.path.abspath(args.manifest))
    # macOS 預設檔案系統不分大小寫：--name Foo 與 foo 會寫到同一個
    # <name>.html／資產目錄互相覆蓋；Linux 產的兩份也無法 checkout 到 Mac。
    # 對既有頁面與資產 namespace 做 casefold 撞名檢查。
    if os.path.isdir(pub):
        want = f"{args.name}.html"
        for fn in os.listdir(pub):
            if fn.casefold() == want.casefold() and fn != want:
                sys.exit(f"--name {args.name!r} 與既有頁 {fn} 只差大小寫——"
                         "大小寫不敏感的檔案系統會互相覆蓋，換個名字")
    if os.path.isdir(assets_root):
        cfpat = re.compile(re.escape(args.name.casefold()) + r"-[0-9a-f]{8}$")
        for d in os.listdir(assets_root):
            if cfpat.fullmatch(d.casefold())                     and not d.startswith(args.name + "-"):
                sys.exit(f"--name {args.name!r} 與既有資產目錄 {d} 只差大小寫"
                         "——大小寫不敏感的檔案系統會互相覆蓋，換個名字")
    has_note = any(u.get("note") for u in utts)
    title = str(man.get("title") or f"Audio demo — {args.name}")
    safe_of = {orig: safe for safe, orig in safe_names.items()}
    # ── Phase 1：全部驗證＋排複製計畫。任何錯誤都在動到發佈目錄之前擋下，
    # 失敗的 rerun 不會留下「舊頁配新資產」的混種頁。
    plan = []       # (src_path, dst_basename)
    claimed = {}    # dst_basename -> (uid, system)；防 uid.system 串接歧義碰撞
    seen_ids = set()
    rows_spec = []  # (uid, note, cells_spec)——HTML 等版本號定案後才組
    for u in utts:
        uid = str(u.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", uid):
            sys.exit(f"utterance id {uid!r} 不合法（限 [A-Za-z0-9._-]，會成為檔名）")
        if uid in seen_ids:
            sys.exit(f"utterance id {uid!r} 重複——id 必須唯一")
        seen_ids.add(uid)
        cells_spec = []   # None＝該系統無音檔；str＝資產 basename（rel 待 ver 定案）
        for s in systems:
            src = (u.get("audio") or {}).get(s)
            if not src:
                cells_spec.append(None)
                continue
            srcp = src if os.path.isabs(src) else os.path.join(mdir, src)
            if not os.path.isfile(srcp):
                sys.exit(f"找不到音檔：{srcp}（utterance {uid}／system {s}）")
            ext = os.path.splitext(srcp)[1] or ".wav"
            # 副檔名也正規化：來源檔名可含 #?% 等合法但會被瀏覽器當
            # fragment/query/escape 的字元
            ext = re.sub(r"[^A-Za-z0-9.]", "-", ext)
            base = f"{uid}.{safe_of[s]}{ext}"
            # uid 與 system 都可含 '.'，串接不是一對一——(a.b, c) 和 (a, b.c)
            # 會撞出同一個檔名；casefold 再比一次，macOS 預設檔案系統不分
            # 大小寫，"A"/"a" 實際是同一顆檔
            key = base.casefold()
            if key in claimed:
                sys.exit(f"資產檔名碰撞：{base}——{claimed[key]} 與 ({uid}, {s}) "
                         f"產生同名檔（含大小寫不敏感比對），請調整 id／system 命名")
            claimed[key] = (uid, s)
            plan.append((srcp, base))
            cells_spec.append(base)
        rows_spec.append((uid, str(u.get("note") or ""), cells_spec))
    # ── Phase 2：版本化資產。ver8＝manifest bytes＋各來源內容雜湊的 sha1
    # 前 8 碼；新目錄 assets/<name>-<ver8>/ 在頁面指向它之前對外不可見——
    # 中途被 SIGKILL 只留孤兒（gitignore 的 .demo-staging-*/ 蓋住 build 目
    # 錄；孤兒版本目錄由下次成功執行清掉），舊頁面始終指向仍存在的舊版本。
    import fcntl
    import glob
    import hashlib
    import tempfile
    os.makedirs(assets_root, exist_ok=True)
    hsh = hashlib.sha1()
    hsh.update(open(man_real, "rb").read())
    for srcp, base in plan:
        # 內容雜湊：mtime 在重新 checkout 會變（假 churn）、rsync -t/copy2
        # 又會保留 mtime+size（改了內容卻重用舊版）——只有內容可信。
        # demo 音檔是秒級 wav、數量小，全讀成本可忽略。
        hsh.update(base.encode() + b"\0")
        with open(srcp, "rb") as fsrc:
            for chunk in iter(lambda: fsrc.read(1 << 20), b""):
                hsh.update(chunk)
    ver = hsh.hexdigest()[:8]
    vdir_name = f"{args.name}-{ver}"
    vdir = os.path.join(assets_root, vdir_name)
    # flock assets_root：鎖住「殘骸清理→copy→rename→換頁→index→舊版清理」
    # 整個發佈交易。同名並行時若 rename 後就放鎖，對方會在無鎖狀態換頁／
    # 清理，可能刪掉本方頁面剛引用的版本目錄（最終頁面 404）。跨 name 也
    # 序列化——demo 建置很快，粗鎖換絕對安全。
    _lockfd = os.open(assets_root, os.O_RDONLY)
    fcntl.flock(_lockfd, fcntl.LOCK_EX)
    try:
        # 清本 name 的 build 殘骸（前次被 kill）；別的 name 的不碰
        for stale in glob.glob(os.path.join(assets_root,
                                            f".demo-staging-{args.name}-*")):
            shutil.rmtree(stale, ignore_errors=True)
        # 同版本目錄存在≠可重用：fresh checkout 可能缺檔（.gitignore 吃掉
        # wav）、LFS 未 materialize（pointer 只有百來 bytes）——逐檔驗
        # 「存在且 size 與來源一致」＋ownership marker，不完整就重建。
        import filecmp
        reuse = False
        if os.path.isdir(vdir):
            reuse = os.path.exists(os.path.join(vdir, ".research-campaign-owned"))
            for srcp, base in (plan if reuse else []):
                dst = os.path.join(vdir, base)
                # 逐位元組比對（shallow=False）：同尺寸的損毀/錯誤內容也抓
                if not (os.path.isfile(dst)
                        and filecmp.cmp(dst, srcp, shallow=False)):
                    reuse = False
                    break
        if reuse:
            copied = 0
        else:
            if os.path.isdir(vdir):   # 不完整的同版本目錄：重建修復
                shutil.rmtree(vdir)
            build = tempfile.mkdtemp(prefix=f".demo-staging-{args.name}-",
                                     dir=assets_root)
            try:
                for srcp, base in plan:
                    shutil.copyfile(srcp, os.path.join(build, base))
                # ownership marker：清理只動「本工具建的」版本目錄，手工
                # 資產目錄即使撞名也永不誤刪
                open(os.path.join(build, ".research-campaign-owned"), "w").close()
                os.rename(build, vdir)   # 原子：vdir 要嘛不存在、要嘛完整
            except BaseException:
                shutil.rmtree(build, ignore_errors=True)
                raise
            copied = len(plan)
        # 發佈資產被 .gitignore 吃掉（starter 有 *.wav）→ Pages 部署後播放
        # 器全 404。主動偵測並大聲警告（rc 0=ignored、1=否、128=非 repo）。
        ignored_warn = None
        if plan:
            import subprocess
            proj = os.path.normpath(os.path.join(root, "..", ".."))
            paths = [os.path.join(vdir, b) for _, b in plan]
            # --stdin -z：路徑走 stdin，數千個 cell 也不會撞 ARG_MAX
            r = subprocess.run(["git", "-C", proj, "check-ignore", "--stdin", "-z"],
                               input="\0".join(paths) + "\0",
                               capture_output=True, text=True)
            if r.returncode == 0:  # 至少一個被 ignore
                hits = [os.path.basename(l)
                        for l in r.stdout.split("\0") if l]
                _hitmsg = "、".join(hits[:5]) + ("…" if len(hits) > 5 else "")
                ignored_warn = (f"發佈音檔被 .gitignore 忽略（{_hitmsg}）——"
                                "commit 不會帶上、Pages 部署後播放器 404。"
                                "請在 .gitignore 加例外：!docs/assets/** 或 "
                                "!public/assets/**")
                print(f"[warn] {ignored_warn}", file=sys.stderr)
        # rel 路徑此刻定案（指向版本化目錄）→ 組 per-utterance 卡片
        from urllib.parse import quote as _q
        articles = []
        for uid, note, cells_spec in rows_spec:
            boxes = []
            for sysname, base in zip(systems, cells_spec):
                if base is None:
                    continue
                rel = f"assets/{_q(vdir_name)}/{_q(base)}"
                boxes.append(f"<div class=\"audio-box\">"
                             f"<p class=\"label\">{H.escape(sysname)}</p>"
                             f"<audio controls preload=\"none\" "
                             f"src=\"{H.escape(rel)}\"></audio>"
                             f"<p class=\"dl\"><a href=\"{H.escape(rel)}\" "
                             f"download>下載 wav</a></p></div>")
            note_p = f"<p class=\"note\">{H.escape(note)}</p>" if note else ""
            articles.append(f"<article class=\"example\"><h3>{H.escape(uid)}</h3>"
                            f"{note_p}<div class=\"audio-grid\">{''.join(boxes)}"
                            f"</div></article>")
        desc = (f"{len(utts)} utterances × {len(systems)} systems"
                f"（{'、'.join(systems)}）— 對聽素材，勝出宣稱以 campaign report "
                "的顯著性 gate 為準")
        page = (f"<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                f"<title>{H.escape(title)}</title>"
                f"<meta name=\"description\" content=\"{H.escape(desc)}\">"
                f"<style>{_REPORT_CSS}</style></head><body>"
                f"<header class=\"band\"><div class=\"hwrap\">"
                f"<p class=\"kicker\">research campaign · audio demo</p>"
                f"<h1>{H.escape(title)}</h1>"
                f"<p class=\"subtitle\">{H.escape(desc)}。音檔不預載——點播放"
                "才抓檔，數量多也不吃流量。</p>"
                f"<nav class=\"crumbs\"><a href=\"index.html\">← 首頁</a>"
                + (f"<a href=\"campaign-report.html\">campaign report</a>"
                   if os.path.exists(os.path.join(pub, "campaign-report.html"))
                   else "") + "</nav>"
                f"</div></header>"
                f"<main><div class=\"examples\">{''.join(articles)}</div>"
                "<p class=\"footnote\">audio demo — generated by research-cards "
                "research-campaign；素材頁不作勝出宣稱。</p>"
                "</main></body></html>\n")
        out = os.path.join(pub, f"{args.name}.html")
        for stale in glob.glob(os.path.join(pub, ".demopage-*.tmp")):
            try:
                os.unlink(stale)   # 前次被 kill 遺留的暫存頁
            except OSError:
                pass
        fd, tmp_out = tempfile.mkstemp(prefix=".demopage-", suffix=".tmp",
                                       dir=pub)
        with os.fdopen(fd, "w") as f:
            f.write(page)
        os.replace(tmp_out, out)   # 原子換頁：截斷式覆寫被 kill 會留半頁
        _warn_if_page_ignored(out)
        idx = _write_index(pub, _mission_title(root))
        # 頁面已指向新版本 → 清「現行已發佈頁面沒有引用」的舊版本（與
        # legacy 未版本化目錄）。以頁面實際引用為準：無論競態誰後寫頁，
        # 最終狀態都是「頁面引用的版本必然存在」。
        removed = []
        keep = {vdir_name}
        # 掃發佈目錄所有 HTML（含 repo 自製頁——showcase 明確允許同目錄共存）
        # 的版本引用：任何頁面還在用的版本目錄都不刪
        for fn in os.listdir(pub):
            if not fn.casefold().endswith(".html"):
                continue
            try:
                published = open(os.path.join(pub, fn), encoding="utf-8",
                                 errors="replace").read()
            except OSError:
                continue
            keep.update(f"{args.name}-{h}" for h in re.findall(
                r"assets/" + re.escape(args.name) + r"-([0-9a-f]{8})/",
                published))
        vpat = re.compile(re.escape(args.name) + r"-[0-9a-f]{8}$")
        src_reals = {os.path.realpath(sp) for sp, _ in plan}
        for d in sorted(os.listdir(assets_root)):
            full = os.path.join(assets_root, d)
            if not os.path.isdir(full) or d in keep:
                continue
            if not (vpat.fullmatch(d) or d == args.name):
                continue
            # 只刪本工具建的目錄（有 ownership marker）——手工資產撞名不誤刪
            if not os.path.exists(os.path.join(full, ".research-campaign-owned")):
                print(f"[note] {full} 沒有本工具的 ownership marker——略過不刪"
                      "（手工資產或舊版工具產物，請自行處理）", file=sys.stderr)
                continue
            # 目錄若含本次 manifest 的來源檔（自我引用重生），刪了下次重跑
            # 就找不到來源——保留並提示
            fr = os.path.realpath(full) + os.sep
            if any(sp.startswith(fr) for sp in src_reals):
                print(f"[note] {full} 內含本次 manifest 的音檔來源——保留不刪；"
                      "建議把來源移出發佈資產目錄", file=sys.stderr)
                continue
            shutil.rmtree(full, ignore_errors=True)
            removed.append(d)
    finally:
        os.close(_lockfd)          # close 即釋放 flock（交易全程持有）
    print(json.dumps({"demo": out, "systems": systems, "utterances": len(utts),
                      "audio_copied": copied, "assets_dir": vdir, "version": ver,
                      "old_versions_removed": removed,
                      "gitignore_warning": ignored_warn,
                      "index_pages": idx}, ensure_ascii=False))


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
    p = sub.add_parser("report", help="ledger/queue -> 靜態 HTML campaign 報告"
                                      "（含 ledger 指標趨勢圖；並 regen index）")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--out", default=None,
                   help="輸出路徑（預設依 pages.json 的 output_dir：github→docs/、"
                        "gitlab→public/，未 setup 則 docs/）")
    p.add_argument("--no-index", action="store_true", dest="no_index",
                   help="不順帶 regen 同目錄的 index.html")
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("progress-init",
                       help="生成 progress.json 模板（訓練進度儀表設定）")
    p.add_argument("--dir", default="runs/auto_research")
    p.set_defaults(fn=cmd_progress_init)
    p = sub.add_parser("progress",
                       help="訓練 log -> 進度儀表 HTML（SVG 曲線/tiles/表）")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--out", default=None,
                   help="輸出路徑（預設依 pages.json 落 "
                        "<output_dir>/campaign-progress.html）")
    p.add_argument("--scheduler", choices=["slurm", "none"], default=None,
                   help="覆寫 progress.json 的 scheduler")
    p.set_defaults(fn=cmd_progress)
    p = sub.add_parser("demo", help="manifest -> 音檔對聽頁（copy 音檔進 "
                                    "assets/、寫 <name>.html、regen index）")
    p.add_argument("--dir", default="runs/auto_research")
    p.add_argument("--manifest", required=True,
                   help="JSON：{title?, systems:[…], utterances:[{id, audio:{系統:路徑}, note?}]}")
    p.add_argument("--name", default="demo",
                   help="頁名/資產目錄名（<publish>/<name>.html；預設 demo）")
    p.set_defaults(fn=cmd_demo)
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
