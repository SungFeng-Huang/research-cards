#!/usr/bin/env python3
"""hackmd-sync — level-1 mirror of research-cards collections to HackMD.

HackMD is the plugin's third note surface, aimed at SHARING: publish selected
collections (typically overviews) as HackMD notes with real note-to-note
links. Level 1 semantics, mirroring obsidian-sync's own history:

  - one-way, incremental: the active backend (heptabase / obsidian / both's
    canonical side) is the source of truth; unchanged cards are skipped via a
    source-markdown md5 recorded in the state file.
  - change DETECTION on the HackMD side: if a mirrored note's lastChangedAt
    moved since we last wrote it, the card is reported as a conflict and NOT
    overwritten (write-back is a deliberate non-goal of level 1 — edits made
    on HackMD flow back by hand).
  - card links: `[[Title]]` / card mentions whose target is itself mirrored
    become real HackMD note links; anything else degrades to plain text of
    the title (readable, just not clickable).

Auth: the hackmd-cli's own login (`hackmd-cli login`) or the
HMD_API_ACCESS_TOKEN env var — the token never lives in config.json.

Config (config.example.json `hackmd` section):
  collections: {<collection key>: {"folder_id": "..."}}   # folder per collection
  read_permission / write_permission: defaults for newly created notes
  (a collection entry may carry its own read_permission / write_permission
  to override the global default — e.g. a projects collection pinned
  private while overviews are shared)

State: ~/.config/research-cards/hackmd-state.json
  {"cards": {<card_id>: {"note_id", "md5", "last_changed_at", "title"}}}

Usage:
    python3 sync.py                 # sync all configured collections
    python3 sync.py --collection overviews
    python3 sync.py --card <id>     # one card (must belong to a configured collection)
    python3 sync.py --dry-run
    python3 sync.py verify          # state vs remote existence / drift report
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "_shared"))
sys.path.insert(0, os.path.join(_HERE, "..", "card-rewrite"))

import hbconfig  # noqa: E402

STATE_PATH = os.path.join(hbconfig.user_data_dir(), "hackmd-state.json")
HACKMD_URL = "https://hackmd.io/"


# ── HackMD plumbing ──────────────────────────────────────────────────────────
# The REST API is the data plane (the CLI's table layer drops fields like
# lastChangedAt and permissions); the CLI stays for what the API can't do —
# creating a note INSIDE a folder — and for the shared login (we read the
# token the CLI's `login` saved). Permission values per the API:
# owner | signed_in | guest.
API = "https://api.hackmd.io/v1"
VALID_PERMS = ("owner", "signed_in", "guest")


def _token():
    tok = os.environ.get("HMD_API_ACCESS_TOKEN")
    if tok:
        return tok
    try:
        return json.load(open(os.path.expanduser("~/.hackmd/config.json")))["accessToken"]
    except Exception:                                        # noqa: BLE001
        sys.exit("HackMD token 不存在——跑 `hackmd-cli login` 或設 "
                 "HMD_API_ACCESS_TOKEN")


_LAST_CALL = [0.0]


def api(method, path, body=None, timeout=60):
    import urllib.request
    import time
    # gentle throttle — bursts of PATCHes get 202-Accepted then silently
    # dropped by HackMD's async pipeline (observed 2026-07-18)
    wait = 0.4 - (time.monotonic() - _LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[0] = time.monotonic()
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Authorization", "Bearer " + _token())
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def perm(cfg, key, default, cc=None):
    """Effective permission for a note: collection-level override (e.g. a
    projects collection pinned private) falls back to the global hackmd
    default. Both levels are validated — a typo'd value would otherwise be
    silently coerced to owner by the API."""
    if cc and key in cc:
        v, where = cc[key], "collections.<key>." + key
    else:
        v, where = (cfg.get("hackmd") or {}).get(key, default), key
    if v not in VALID_PERMS:
        sys.exit(f"config hackmd.{where}={v!r} 非法——API 只接受 "
                 f"{'|'.join(VALID_PERMS)}")
    return v


def fetch_remote_index():
    """One GET /notes → {note_id: {last_changed_at, read_permission,
    content_md5}}. The list response includes full content, so one call also
    powers write-AFTER-verification."""
    rows = api("GET", "/notes")
    return {r["id"]: {"last_changed_at": r.get("lastChangedAt"),
                      "read_permission": r.get("readPermission"),
                      "content_md5": content_md5(r.get("content") or "")}
            for r in rows if r.get("id")}


def note_create(title, content, folder_id, cfg, cc=None):
    """CLI create — the API cannot place a note in a folder. Returns note id
    (lastChangedAt is backfilled from a post-run index refresh)."""
    args = ["hackmd-cli", "notes", "create", "--title", title,
            "--content", content,
            "--readPermission", perm(cfg, "read_permission", "owner", cc),
            "--writePermission", perm(cfg, "write_permission", "owner", cc),
            "--output", "json"]
    if folder_id:
        args += ["--parentFolderId", folder_id]
    r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"create failed: {(r.stderr or r.stdout)[:200]}")
    out = json.loads(r.stdout)
    row = out[0] if isinstance(out, list) else out
    return row["id"]


def note_get(note_id):
    """Single-note GET — authoritative (the list endpoint's content lags
    behind async writes and mis-reports freshly PATCHed notes)."""
    r = api("GET", f"/notes/{note_id}")
    return {"last_changed_at": r.get("lastChangedAt"),
            "read_permission": r.get("readPermission"),
            "content_md5": content_md5(r.get("content") or "")}


def note_update(note_id, content):
    api("PATCH", f"/notes/{note_id}", {"content": content})


def note_set_read_permission(note_id, value):
    api("PATCH", f"/notes/{note_id}", {"readPermission": value})


# ── source side: cards as markdown via the active backend ────────────────────
def load_source():
    """The plugin's backend abstraction already speaks markdown for both
    heptabase and obsidian: list_cards(collection) -> [{id,title,…}],
    read_card(id).md -> markdown."""
    import backend as B
    cfg = hbconfig.load_config()
    return cfg, B.get_backend(cfg)


# ── link rewriting (pure) ─────────────────────────────────────────────────────
def rewrite_links(md, title_to_note, id_to_note):
    """Mirrored targets become HackMD links; everything else degrades to the
    plain title text. Handles [[Title]], [[Title|alias]], and the
    %%HEPTA-CARD:<id>%% placeholders pmmd emits for card-mention nodes."""
    def wikilink(m):
        target = m.group(1)
        label = m.group(2) or target
        nid = title_to_note.get(target)
        return f"[{label}]({HACKMD_URL}{nid})" if nid else label

    md = re.sub(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]", wikilink, md)

    def mention(m):
        info = id_to_note.get(m.group(1))
        if info and info.get("note_id"):
            return f"[{info['title']}]({HACKMD_URL}{info['note_id']})"
        return info["title"] if info else ""   # known-but-unmirrored → plain title
    md = re.sub(r"%%HEPTA-CARD:([0-9a-f-]{36})%%", mention, md)

    def hepta_url(m):
        """pmmd renders aliased card links as [label](https://app.heptabase.com/
        …/card/<id>) — a private URL that is useless (and leaky-looking) on a
        shared page. Mirrored target → HackMD link; otherwise the plain label."""
        label, cid = m.group(1), m.group(2)
        info = id_to_note.get(cid)
        if info and info.get("note_id"):
            return f"[{label}]({HACKMD_URL}{info['note_id']})"
        return label
    md = re.sub(r"\[([^\]]+)\]\(https://app\.heptabase\.com/[^\)]*?([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})[^\)]*\)",
                hepta_url, md)
    return md


def content_md5(md):
    return hashlib.md5(md.encode("utf-8")).hexdigest()


# ── state ─────────────────────────────────────────────────────────────────────
def load_state():
    try:
        return json.load(open(STATE_PATH))
    except Exception:                                        # noqa: BLE001
        return {"cards": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    json.dump(state, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


# ── sync ──────────────────────────────────────────────────────────────────────
def sync(collections=None, only_card=None, dry=False):
    cfg, be = load_source()
    list_cards, read_md = be.list_cards, (lambda cid: be.read_card(cid).md)
    hk = cfg.get("hackmd") or {}
    conf_cols = hk.get("collections") or {}
    if not conf_cols:
        sys.exit("config 沒有 hackmd.collections——setup skill 可帶你設定"
                 "（hackmd-cli folders 查 folder id）")
    state = load_state()
    cards_state = state.setdefault("cards", {})
    report = {"created": [], "updated": [], "skipped": 0,
              "conflicts": [], "errors": []}

    # gather the full mirror set, plus an id→title map over EVERY configured
    # collection (not just mirrored ones) so mentions of unmirrored cards
    # degrade to their plain TITLE, never to nothing
    targets = []
    for key, cc in conf_cols.items():
        if collections and key not in collections:
            continue
        for card in list_cards(key):
            if only_card and card["id"] != only_card:
                continue
            targets.append((key, cc, card))
    all_titles = {}
    for key in hbconfig.collections(cfg):
        try:
            for card in list_cards(key):
                all_titles[card["id"]] = card["title"]
        except Exception:                                    # noqa: BLE001
            pass  # a collection that doesn't resolve just loses title fallback

    known_titles = {c["title"]: cards_state.get(c["id"], {}).get("note_id")
                    for _, _, c in targets}

    # phase A: create every brand-new card FIRST so the link map is complete
    # before any content is finalized — first publication already carries the
    # promised note-to-note links (no second-run convergence needed)
    for key, cc, card in targets:
        cid, title = card["id"], card["title"]
        if (cards_state.get(cid) or {}).get("note_id"):
            continue
        try:
            if dry:
                report["created"].append({"card": cid, "title": title})
                continue
            nid = note_create(title, "（同步中…）", cc.get("folder_id"), cfg, cc)
            cards_state[cid] = {"note_id": nid, "md5": None,
                                "last_changed_at": None, "title": title}
            known_titles[title] = nid
            report["created"].append({"card": cid, "note": nid, "title": title})
        except Exception as e:                               # noqa: BLE001
            report["errors"].append({"card": cid, "title": title,
                                     "err": str(e)[:200]})

    # index AFTER the creates so brand-new notes are covered in the same run
    # (their permission drift — e.g. the API silently defaulting an invalid
    # value to owner — gets corrected below, not next time). None = index
    # unavailable (rate limit): skip remote missing/conflict/permission
    # checks, keep the md5-incremental part.
    remote_index = None
    if any((cards_state.get(c["id"]) or {}).get("note_id") for _, _, c in targets):
        try:
            remote_index = fetch_remote_index()
        except Exception as e:                               # noqa: BLE001
            report["errors"].append(
                {"card": None, "title": "(remote index)",
                 "err": f"HackMD note list 失敗（rate limit？稍後重跑）——本輪"
                        f"跳過遠端 missing/conflict/權限檢查：{str(e)[:120]}"})

    known_ids = {c["id"]: {"note_id": cards_state.get(c["id"], {}).get("note_id"),
                           "title": c["title"]}
                 for _, _, c in targets if cards_state.get(c["id"], {}).get("note_id")}
    mention_map = dict(known_ids)
    for cid2, title2 in all_titles.items():
        mention_map.setdefault(cid2, {"note_id": None, "title": title2})

    # phase B: render + write content (freshly created notes always update:
    # their md5 is None)
    for key, cc, card in targets:
        cid, title = card["id"], card["title"]
        want_read = perm(cfg, "read_permission", "owner", cc)
        prev = cards_state.get(cid) or {}
        if not prev.get("note_id"):
            continue  # dry-run create, or create failed above
        try:
            md = read_md(cid)
            md = rewrite_links(md, {t: n for t, n in known_titles.items() if n},
                               mention_map)
            digest = content_md5(md)
            if remote_index is not None and prev["note_id"] not in remote_index \
                    and prev.get("md5") is not None:
                report["errors"].append(
                    {"card": cid, "title": title,
                     "err": "HackMD note 不存在（遠端被刪？）——刪 state 條目後"
                            "重跑即重建"})
                continue
            remote = (remote_index or {}).get(prev["note_id"]) or {}
            # declarative read permission: computed BEFORE the conflict gate
            # so even conflicted notes (content frozen) get their permission
            # migrated — permission is ours to manage, content is theirs
            perm_drift = bool(remote and remote.get("read_permission")
                              and remote["read_permission"] != want_read)
            if remote_index is not None and prev.get("last_changed_at") and \
                    remote.get("last_changed_at") != prev.get("last_changed_at"):
                if perm_drift and not dry:
                    note_set_read_permission(prev["note_id"], want_read)
                report["conflicts"].append(
                    {"card": cid, "note": prev["note_id"], "title": title,
                     "why": "HackMD 端在上次同步後被編輯——level 1 不寫回，"
                            "手動合併後重跑（或刪 state 條目強制覆蓋）"})
                continue
            # ONE PATCH per card: content and the declarative read
            # permission ride together — two rapid PATCHes to the same note
            # race in HackMD's async pipeline and one gets dropped
            if prev.get("md5") == digest:
                if perm_drift and not dry:
                    note_set_read_permission(prev["note_id"], want_read)
                report["skipped"] += 1
                continue
            if not dry:
                body = {"content": md}
                if perm_drift:
                    body["readPermission"] = want_read
                api("PATCH", f"/notes/{prev['note_id']}", body)
                cards_state[cid] = {"note_id": prev["note_id"], "md5": digest,
                                    "last_changed_at": None,  # backfilled below
                                    "title": title}
            report["updated"].append({"card": cid, "note": prev["note_id"],
                                      "title": title})
        except Exception as e:                               # noqa: BLE001
            report["errors"].append({"card": cid, "title": title,
                                     "err": str(e)[:200]})

    # post-write pass over JUST the cards written this run: a single-note GET
    # per card (throttled) is the only authoritative read — 202 Accepted ≠
    # applied, and the LIST endpoint's content lags async writes (observed:
    # fresh PATCHes mis-reported as dropped). Backfills lastChangedAt and
    # verifies the write landed; a genuinely dropped write self-heals (md5
    # reset → re-sent next run).
    if not dry and (report["created"] or report["updated"]):
        import time
        time.sleep(1.5)                         # let the async pipeline settle
        written = [c["card"] for c in report["created"] + report["updated"]]
        for cid2 in written:
            rec = cards_state.get(cid2) or {}
            if not rec.get("note_id"):
                continue
            try:
                info = note_get(rec["note_id"])
                rec["last_changed_at"] = info["last_changed_at"]
                if rec.get("md5") and info["content_md5"] != rec["md5"]:
                    rec["md5"] = None           # force a re-send next run
                    report["errors"].append(
                        {"card": cid2, "title": rec.get("title"),
                         "err": "寫入未落地（202 被異步丟棄）——已標記重送，"
                                "重跑 sync 收斂"})
            except Exception as e:                           # noqa: BLE001
                report["errors"].append(
                    {"card": cid2, "title": rec.get("title"),
                     "err": f"寫後驗證讀取失敗——下輪重試：{str(e)[:100]}"})
    if not dry:
        save_state(state)
    # dedupe: a created card also passes phase B as "updated" — report it once
    created_ids = {c["card"] for c in report["created"]}
    report["updated"] = [u for u in report["updated"] if u["card"] not in created_ids]
    return report


def verify():
    state = load_state()
    out = {"tracked": len(state.get("cards", {})), "missing_remote": [],
           "drifted": []}
    idx = fetch_remote_index()
    for cid, rec in (state.get("cards") or {}).items():
        info = idx.get(rec.get("note_id"))
        if info is None:
            out["missing_remote"].append({"card": cid, "note": rec.get("note_id"),
                                          "title": rec.get("title")})
        elif rec.get("last_changed_at") and \
                info["last_changed_at"] != rec.get("last_changed_at"):
            out["drifted"].append({"card": cid, "note": rec["note_id"],
                                   "title": rec.get("title")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="sync", choices=["sync", "verify"])
    ap.add_argument("--collection", action="append")
    ap.add_argument("--card")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.mode == "verify":
        print(json.dumps(verify(), ensure_ascii=False, indent=1))
        return
    rep = sync(collections=args.collection, only_card=args.card, dry=args.dry_run)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
