#!/usr/bin/env python3
"""Create THIS project's card when resolve_card finds none, and pin it.

Usage:
    python3 create_project_card.py --title "My Project" [--dry-run]
    python3 create_project_card.py                # title = git repo / cwd name

What it does (transport picked automatically):
  1. Creates a project card with the skeleton the log/merge pair expects
     (定位 / 現狀 / 📝 待補成 paper 級參考).
  2. Tags it with config heptabase.collections.projects.tag_name
     (default: "project"; `heptabase tag add` creates the tag if missing).
     - local `heptabase` CLI  → create + tag
     - `hb` bridge (remote)   → create; tagging may need a Mac-side follow-up
     - backend=obsidian       → .md in config obsidian.folders.projects
       (default "Projects/"), tag recorded in frontmatter
  3. Pins the mapping: writes `.heptabase-card` at the git root (falls back
     to cwd) so every future session here resolves automatically.

Prints one JSON line: {card, title, transport, marker}.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                "..", "_shared"))

SKELETON = """## 定位

（一句話：這個專案在做什麼、賭什麼。）

## 現狀

（目前進度的最新快照——由 project-card-log 持續補充、project-card-merge 定期整併。）

## 📝 待補成 paper 級參考

- （列出需要 paper 級細節的項目：方法規格、完整消融數字、baseline、設計理由、圖源。）
"""


def sh(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def git_root():
    r = sh(["git", "rev-parse", "--show-toplevel"])
    return r.stdout.strip() or None


def cfg():
    """Missing config -> {} (auto transport). INVALID config -> fail fast
    (a broken backend=obsidian must not silently fall back to Heptabase)."""
    try:
        import hbconfig
    except Exception:
        return {}
    if not os.path.exists(hbconfig.CONFIG_PATH):
        return {}
    try:
        return hbconfig.load_config()
    except Exception as e:
        sys.exit(f"config 讀取失敗（{hbconfig.CONFIG_PATH}）：{e}")


def tag_name(c):
    t = (((c.get("heptabase") or {}).get("collections") or {})
         .get("projects") or {}).get("tag_name")
    if isinstance(t, str) and t.startswith("<") and t.endswith(">"):
        t = None
    return t or "project"


def create_heptabase(title, tag):
    r = sh(["heptabase", "note", "create", "--content",
            f"# {title}\n\n{SKELETON}"])
    if r.returncode != 0:
        sys.exit(f"heptabase note create 失敗：{r.stderr[:200]}")
    cid = json.loads(r.stdout)["id"]
    t = sh(["heptabase", "tag", "add", "--card-id", cid, "--tag-name", tag])
    return cid, (t.returncode == 0)


def create_hb_bridge(title, tag):
    r = sh(["hb", "create", f"# {title}\n\n{SKELETON}"], timeout=60)
    if r.returncode != 0:
        sys.exit(f"hb create 失敗：{r.stderr[:200]}")
    out = r.stdout.strip()
    cid = None
    try:
        data = json.loads(out)
        cid = data.get("id") or data.get("card")
    except Exception:
        m = __import__("re").search(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", out)
        cid = m.group(0) if m else None
    if not cid:  # fail closed — 絕不把雜訊寫進 marker
        sys.exit(f"hb create 輸出無法解析出卡片 id：{out[:200]}")
    return cid, False  # bridge 無 tag 能力：回 Mac 補 tag


def create_obsidian(title, tag, c):
    import backend
    be = backend.ObsidianBackend(c)
    folders = (c.get("obsidian") or {}).get("folders") or {}
    if "projects" not in folders:
        folders["projects"] = "Projects"
        be.folders = folders
    cid = be.create_card("projects", title, SKELETON, {"tags": [tag]})
    return cid, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", help="card title (default: repo/cwd name)")
    ap.add_argument("--marker-dir", help="where to write .heptabase-card "
                    "(default: git root; monorepo 子專案請傳自己的目錄)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = args.marker_dir or git_root() or os.getcwd()
    if not args.marker_dir and git_root() and os.getcwd() != git_root():
        print(f"# 注意：marker 將寫到 git root（{root}）；monorepo 子專案請改用 "
              f"--marker-dir \"$(pwd)\"", file=sys.stderr)
    title = args.title or os.path.basename(root)
    c = cfg()
    tag = tag_name(c)

    if args.dry_run:
        transport = ("obsidian" if c.get("backend") == "obsidian" else
                     "heptabase" if sh(["which", "heptabase"]).returncode == 0
                     else "hb")
        return print(json.dumps({"dry_run": True, "title": title, "tag": tag,
                                 "transport": transport, "marker_dir": root},
                                ensure_ascii=False))

    if c.get("backend") == "obsidian":
        cid, tagged = create_obsidian(title, tag, c)
        transport = "obsidian"
    elif sh(["which", "heptabase"]).returncode == 0:
        cid, tagged = create_heptabase(title, tag)
        transport = "heptabase"
    elif sh(["which", "hb"]).returncode == 0:
        cid, tagged = create_hb_bridge(title, tag)
        transport = "hb"
    else:
        sys.exit("找不到 heptabase CLI 或 hb bridge（config backend 也非 obsidian）")

    marker = Path(root) / ".heptabase-card"
    marker.write_text(f"card: {cid}\ntitle: {title}\n")
    print(json.dumps({"card": cid, "title": title, "transport": transport,
                      "tag": tag, "tagged": tagged, "marker": str(marker),
                      "note": None if tagged else
                      f"transport 無法上 tag——回 Mac 跑 `heptabase tag add "
                      f"--card-id {cid} --tag-name {tag}`"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
