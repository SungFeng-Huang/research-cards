#!/usr/bin/env python3
"""Resolve the current cluster project (cwd / git repo) → its Heptabase card id.

Precedence (first hit wins):
  1. $HB_PROJECT_CARD env var
  2. .heptabase-card marker file (search cwd upward to git root / fs root)
  3. registry ~/.config/research-cards/projects.json (legacy fallback: next
     to this script) — substring match of any `match_any` entry against the
     cwd path, git toplevel, or git remote url
  4. none → caller falls back to `hb search` + asks the user to pin

Prints a single JSON line. Stdlib only.
"""
import json, os, subprocess
from pathlib import Path

def _cfg_path():
    new = Path.home() / ".config/research-cards/config.json"
    legacy = Path.home() / ".config/heptabase-cards/config.json"
    env = os.environ.get("RESEARCH_CARDS_CONFIG") or os.environ.get("HEPTABASE_CARDS_CONFIG")
    if env:
        return Path(env)
    return new if new.exists() or not legacy.exists() else legacy


_CFG_DIR = _cfg_path().parent
REG = _CFG_DIR / "projects.json"
if not REG.is_file():  # legacy location (pre-plugin shared skill)
    REG = Path(__file__).resolve().parent / "projects.json"


def _feature_enabled(name):
    cfg_path = _cfg_path()
    try:
        feats = json.loads(cfg_path.read_text()).get("features") or {}
        return bool(feats.get(name, True))
    except Exception:
        return True


def sh(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def git_root(start):
    return sh(["git", "-C", str(start), "rev-parse", "--show-toplevel"]) or None


def find_marker(start):
    """Search cwd upward, stopping AT the git root (inclusive) when inside a
    repo — a parent checkout's marker must never claim a nested repo."""
    cur = Path(start).resolve()
    root = git_root(cur)
    stop = Path(root).resolve() if root else None
    while True:
        m = cur / ".heptabase-card"
        if m.is_file():
            return m
        if cur == stop or cur.parent == cur:
            return None
        cur = cur.parent


def parse_marker(m):
    card = title = None
    for line in m.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith("card:"):
            card = s.split(":", 1)[1].strip()
        elif s.lower().startswith("title:"):
            title = s.split(":", 1)[1].strip()
        elif card is None:
            card = s            # bare id on first non-comment line
    return card, title


def from_registry(haystack):
    if not REG.is_file():
        return []
    reg = json.loads(REG.read_text())
    h = haystack.lower()
    hits = []
    for proj in reg.get("projects", []):
        for sub in proj.get("match_any", []):
            if sub.lower() in h:
                hits.append({"card": proj["card"], "title": proj.get("title"), "matched": sub})
                break
    return hits


def main():
    if not _feature_enabled("project"):
        return print(json.dumps({"card": None, "source": "disabled",
                                 "hint": "config features.project = false"}))
    cwd = Path.cwd()
    env = os.environ.get("HB_PROJECT_CARD")
    if env:
        return print(json.dumps({"card": env, "title": None, "source": "env"}))

    m = find_marker(cwd)
    if m:
        card, title = parse_marker(m)
        if card:
            return print(json.dumps({"card": card, "title": title,
                                     "source": "marker", "marker": str(m)}))

    root = git_root(cwd)
    remote = sh(["git", "-C", str(cwd), "remote", "get-url", "origin"]) if root else ""
    hits = from_registry(" ".join(filter(None, [str(cwd), root or "", remote])))
    if len(hits) == 1:
        return print(json.dumps({"card": hits[0]["card"], "title": hits[0]["title"],
                                 "source": "registry", "matched": hits[0]["matched"]}))
    if len(hits) > 1:
        return print(json.dumps({"card": None, "source": "registry-ambiguous", "candidates": hits}))

    return print(json.dumps({"card": None, "source": "none", "cwd": str(cwd),
                             "git_root": root,
                             "hint": "no marker/registry match — `hb search <name>` then write .heptabase-card"}))


if __name__ == "__main__":
    main()
