#!/usr/bin/env python3
"""hackmd-sync — mirror of research-cards collections to HackMD.

HackMD is the plugin's third note surface, aimed at SHARING: publish selected
collections (typically overviews) as HackMD notes with real note-to-note
links. Semantics, mirroring obsidian-sync's own history:

  - forward, incremental: the local backend is the source of truth;
    unchanged cards are skipped via a rendered-markdown md5 recorded in the
    state file. backend='both' sources from the OBSIDIAN side (see
    load_source) so write-back lands in plain .md.
  - change DETECTION on the HackMD side: if a mirrored note's lastChangedAt
    moved since we last wrote it, the card enters level-2 write-back (below)
    or is reported as a conflict and NOT overwritten.
  - level 2 write-back (opt-in, config hackmd.write_back): HackMD-side edits
    flow back into the vault — ONLY for notes whose effective
    write_permission is "owner" (nobody but the user can edit them there);
    shared-writable notes always stay conflicts. Two-sided edits are true
    conflicts. The merge is paragraph-level against a base snapshot:
    untouched paragraphs keep the vault original (degraded mentions never
    get fossilized), edited paragraphs are link-reversed and must
    round-trip, else the whole card freezes.
  - card links: `[[Title]]` / card mentions / Heptabase URLs whose target is
    itself mirrored become real HackMD note links; anything else degrades to
    plain text of the title (readable, just not clickable).

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
# rate-limit bookkeeping: HackMD's infra throttles in short windows even on
# paid plans (observed HTTP 429 with empty body from the load balancer).
# Per-call exponential backoff rides out short windows; a run of cards that
# ALL exhaust their retries means a long window — stop burning the rest of
# the run (incremental state resumes next time).
_BACKOFFS = (60, 120, 240)
_429_STREAK = [0]
_429_STREAK_LIMIT = 5


class QuotaExhausted(RuntimeError):
    pass


def _note_429(failed):
    if failed:
        _429_STREAK[0] += 1
        if _429_STREAK[0] >= _429_STREAK_LIMIT:
            raise QuotaExhausted(
                f"連續 {_429_STREAK[0]} 張卡重試後仍 429——限流視窗較長，"
                "本輪提前收尾（state 已記帳，重跑即續傳）")
    else:
        _429_STREAK[0] = 0


def api(method, path, body=None, timeout=60):
    import urllib.error
    import urllib.request
    import time
    for attempt in range(len(_BACKOFFS) + 1):
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
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
            _note_429(False)
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            if attempt < len(_BACKOFFS):
                time.sleep(_BACKOFFS[attempt])
                continue
            _note_429(True)
            raise


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


def _folder_of(row):
    """Direct folder id of a listed note across API generations: newer
    responses carry `folderPaths` (a list of folder dicts, [0] = the direct
    folder), older ones a flat `parentFolderId`. Schema drift here silently
    blinded adoption/stray scanning once (2026-07-18) — support both."""
    fp = row.get("folderPaths")
    if isinstance(fp, list) and fp and isinstance(fp[0], dict):
        return fp[0].get("id") or None
    return row.get("parentFolderId") or None


def fetch_remote_index():
    """One GET /notes → {note_id: {last_changed_at, read_permission,
    content_md5, title, folder}}. title+folder power phase-A adoption
    (reclaiming notes a killed run created but never recorded)."""
    rows = api("GET", "/notes")
    return {r["id"]: {"last_changed_at": r.get("lastChangedAt"),
                      "read_permission": r.get("readPermission"),
                      "content_md5": content_md5(r.get("content") or ""),
                      "title": r.get("title"),
                      "folder": _folder_of(r)}
            for r in rows if r.get("id")}


def note_create(title, content, folder_id, cfg, cc=None):
    """CLI create — the API cannot place a note in a folder. Returns note id
    (lastChangedAt is backfilled from a post-run index refresh)."""
    import time
    args = ["hackmd-cli", "notes", "create", "--title", title,
            "--content", content,
            "--readPermission", perm(cfg, "read_permission", "owner", cc),
            "--writePermission", perm(cfg, "write_permission", "owner", cc),
            "--output", "json"]
    if folder_id:
        args += ["--parentFolderId", folder_id]
    for attempt in range(len(_BACKOFFS) + 1):
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
        blob = (r.stderr or "") + (r.stdout or "")
        if r.returncode != 0:
            limited = "429" in blob or "Too many requests" in blob \
                or "Retrying request" in blob
            if limited and attempt < len(_BACKOFFS):
                time.sleep(_BACKOFFS[attempt])
                continue
            _note_429(limited)
            raise RuntimeError(f"create failed: {blob[:200]}")
        _note_429(False)
        out = json.loads(r.stdout)
        row = out[0] if isinstance(out, list) else out
        return row["id"]


def note_get(note_id):
    """Single-note GET — authoritative (the list endpoint's content lags
    behind async writes and mis-reports freshly PATCHed notes)."""
    r = api("GET", f"/notes/{note_id}")
    return {"last_changed_at": r.get("lastChangedAt"),
            "read_permission": r.get("readPermission"),
            "write_permission": r.get("writePermission"),
            "content": r.get("content") or "",
            "content_md5": content_md5(r.get("content") or "")}


def note_update(note_id, content):
    api("PATCH", f"/notes/{note_id}", {"content": content})


def note_set_read_permission(note_id, value):
    api("PATCH", f"/notes/{note_id}", {"readPermission": value})


# ── source side: cards as markdown via the active backend ────────────────────
def load_source():
    """The plugin's backend abstraction already speaks markdown for both
    heptabase and obsidian: list_cards(collection) -> [{id,title,…}],
    read_card(id).md -> markdown.

    backend='both' deliberately uses the OBSIDIAN side as hackmd's source
    (unlike get_backend(), which returns the Heptabase canonical): write-back
    then targets plain .md files, and the vault's own block-level level-2
    sync (obsidian-sync) carries the change on to Heptabase with all its
    safety machinery. Chain of adjacent two-way syncs, no duplicated engine.
    """
    import backend as B
    cfg = hbconfig.load_config()
    if cfg.get("backend") == "both":
        return cfg, B.ObsidianBackend(cfg)
    return cfg, B.get_backend(cfg)


def card_key(card):
    """Stable identity for state/link maps: the Heptabase uuid when the
    vault file carries one (frontmatter heptabase_id — survives file renames
    and stays aligned with state written when heptabase was the source),
    else the backend id."""
    return (card.get("props") or {}).get("heptabase_id") or card["id"]


def link_names(card):
    """All names a wikilink may use for this card: the card TITLE plus the
    vault FILENAME when they differ — safe_filename replaces '/' etc. in
    filenames, and Obsidian wikilinks target the filename, so an index card
    saying [[Tokenizer-Codec-… (filename)]] must still resolve to the card
    titled Tokenizer/Codec/…."""
    names = [card["title"]]
    if "/" in card["id"]:
        base = card["id"].rsplit("/", 1)[-1]
        if base != card["title"]:
            names.append(base)
    return names


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


PLACEHOLDER = "（同步中…）"
PLACEHOLDER_MD5 = content_md5(PLACEHOLDER)


def book_transform(md, title):
    """Shape a rendered index card into HackMD Book-mode form (matching the
    official tutorials book verbatim): a setext H1 title on top, ATX ##
    sections become setext (`---` underline), same-site note links become
    relative `/noteId` paths, and list items are stripped down to just the
    link — Book mode's sidebar renders any text after the link as a
    separate same-level unclickable entry, turning descriptions into
    sidebar noise. Source cards keep their descriptions; this runs at
    render time only, every sync."""
    md = re.sub(r"\]\(" + re.escape(HACKMD_URL) + r"([A-Za-z0-9_-]+)\)",
                r"](/\1)", md)
    lines = []
    for line in md.split("\n"):
        m = re.match(r"^## (.+)$", line)
        if m:
            lines += [m.group(1), "---"]
            continue
        m = re.match(r"^# (.+)$", line)
        if m:
            lines += [m.group(1), "==="]
            continue
        m = re.match(r"^(\s*- .*\]\([^)\s]*\))\s*(?!.*\]\()\S.*$", line)
        if m:               # strip the trailing text after the LAST link —
            lines.append(m.group(1))   # the lookahead keeps multi-link lines
            continue
        lines.append(line)
    out = "\n".join(lines)
    if not re.match(r"^[^\n]+\n===", out):
        out = f"{title}\n===\n\n{out}"
    return out


# ── write-back (level 2, opt-in) ──────────────────────────────────────────────
# Trust boundary per the user's rule: only notes whose EFFECTIVE
# write_permission is "owner" (nobody but the user can edit them on HackMD)
# are written back; shared-writable notes keep level-1 conflict semantics.
BASE_DIR = os.path.join(hbconfig.user_data_dir(), "hackmd-base")


def base_path(key):
    return os.path.join(BASE_DIR, key.replace("/", "%2F") + ".md")


def save_base(key, md):
    os.makedirs(BASE_DIR, exist_ok=True)
    tmp = base_path(key) + ".tmp"
    with open(tmp, "w") as f:
        f.write(md)
    os.replace(tmp, base_path(key))


def load_base(key):
    try:
        return open(base_path(key)).read()
    except OSError:
        return None


def reverse_links(md, note_to_card):
    """Inverse of rewrite_links for edited regions: HackMD note links whose
    note belongs to the mirror become [[Title]] / [[Title|alias]] wikilinks
    (the vault-side lingua franca — obsidian-sync rebuilds them as native
    mentions). Foreign HackMD links stay untouched."""
    def unlink(m):
        label, nid = m.group(1), m.group(2)
        info = note_to_card.get(nid)
        if not info:
            return m.group(0)
        title = info["title"]
        return f"[[{title}]]" if label == title else f"[[{title}|{label}]]"
    return re.sub(r"\[([^\]]+)\]\(" + re.escape(HACKMD_URL) + r"([A-Za-z0-9_-]+)\)",
                  unlink, md)


def split_paras(md):
    return [p for p in re.split(r"\n[ \t]*\n", md) if p.strip()]


def para_degrades(vault_para, title_to_note, id_to_note):
    """True when the paragraph contains a link the forward render degrades
    to plain text (unmirrored wikilink / card mention / Heptabase URL) —
    such a paragraph is NOT reversible from the HackMD side: editing or
    deleting it there would fossilize the degraded text into the vault."""
    for m in re.finditer(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]", vault_para):
        if not title_to_note.get(m.group(1)):
            return True
    for m in re.finditer(r"%%HEPTA-CARD:([0-9a-f-]{36})%%", vault_para):
        info = id_to_note.get(m.group(1))
        if not (info and info.get("note_id")):
            return True
    for m in re.finditer(
            r"https://app\.heptabase\.com/[^\)\s]*?"
            r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", vault_para):
        info = id_to_note.get(m.group(1))
        if not (info and info.get("note_id")):
            return True
    return False


def write_back(vault_md, base_md, hackmd_md, note_to_card, render,
               degrades=None):
    """Paragraph-level HackMD -> vault merge. rewrite_links is inline-only,
    so the vault body and its rendered base have the SAME paragraph
    sequence; diff(base, now) opcodes therefore map 1:1 onto vault
    paragraphs. Unchanged paragraphs keep the vault original (mentions that
    degraded to plain text on HackMD stay intact); edited paragraphs are
    link-reversed and must round-trip (render(reversed) == region) or the
    whole card conflicts. Editing/deleting a paragraph whose vault original
    contains degraded (irreversible) links also conflicts — writing the
    HackMD text back would fossilize the degradation. Returns new vault
    body, or raises ValueError."""
    import difflib
    vault_paras = split_paras(vault_md)
    base_paras = split_paras(base_md)
    now_paras = split_paras(hackmd_md)
    if len(vault_paras) != len(base_paras):
        raise ValueError("base 與 vault 段落數不一致（base 過期？重跑一輪前向後再試）")
    out = []
    sm = difflib.SequenceMatcher(None, base_paras, now_paras, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out += vault_paras[i1:i2]
            continue
        for k in range(i1, i2):
            if degrades and degrades(vault_paras[k]):
                raise ValueError(
                    "被編輯/刪除的段落含 HackMD 端已降級的連結（未鏡像卡的"
                    f" mention／URL）——寫回會固化損耗：{vault_paras[k][:80]!r}")
        for region in now_paras[j1:j2]:
            reversed_md = reverse_links(region, note_to_card)
            if render(reversed_md).strip() != region.strip():
                raise ValueError(f"round-trip 不一致（寫回後會變形）：{region[:80]!r}")
            out.append(reversed_md)
    return "\n\n".join(out)


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


def acquire_state_lock():
    """Exclusive whole-run lock: state is saved incrementally from an
    in-memory copy, so two concurrent runs (e.g. a cron sync and a --card
    sync) would last-write-wins each other's ledger entries and re-orphan
    notes. Held for the run's lifetime; released on process exit."""
    import fcntl
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    fh = open(STATE_PATH + ".lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("另一個 hackmd-sync 正在跑（state lock 被持有）——"
                 "等它結束再跑，或先停掉它")
    return fh


# ── sync ──────────────────────────────────────────────────────────────────────
def sync(collections=None, only_card=None, dry=False):
    fh = acquire_state_lock()
    try:
        return _sync_locked(collections, only_card, dry)
    finally:
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _sync_locked(collections=None, only_card=None, dry=False):
    cfg, be = load_source()
    list_cards, read_md = be.list_cards, (lambda cid: be.read_card(cid).md)
    hk = cfg.get("hackmd") or {}
    conf_cols = hk.get("collections") or {}
    if not conf_cols:
        sys.exit("config 沒有 hackmd.collections——setup skill 可帶你設定"
                 "（hackmd-cli folders 查 folder id）")
    if "hackmd" not in (cfg.get("backends") or ["hackmd"]):
        sys.exit('backends 未含 "hackmd"——顯式 backends list 模式下，'
                 '把 "hackmd" 加進 list 才會啟用 HackMD 鏡像')
    state = load_state()
    cards_state = state.setdefault("cards", {})
    report = {"created": [], "adopted": [], "updated": [], "skipped": 0,
              "written_back": [], "conflicts": [], "errors": [],
              "stray_duplicates": [], "aborted": None}

    # gather the full mirror set, plus an id→title map over EVERY configured
    # collection (not just mirrored ones) so mentions of unmirrored cards
    # degrade to their plain TITLE, never to nothing
    targets = []
    for key, cc in conf_cols.items():
        if collections and key not in collections:
            continue
        for card in list_cards(key):
            if only_card and only_card not in (card["id"], card_key(card)):
                continue
            targets.append((key, cc, card))

    # key migration: state written when the OTHER id space was the source
    # (vault id ↔ heptabase uuid) moves to the current card_key — otherwise
    # every known card would be treated as new and duplicated on HackMD
    for _, _, c in targets:
        ck = card_key(c)
        if ck != c["id"] and c["id"] in cards_state and ck not in cards_state:
            cards_state[ck] = cards_state.pop(c["id"])
    all_titles = {}
    for key in hbconfig.collections(cfg):
        try:
            for card in list_cards(key):
                all_titles[card_key(card)] = card["title"]
        except Exception:                                    # noqa: BLE001
            pass  # a collection that doesn't resolve just loses title fallback

    known_titles = {}
    for _, _, c in targets:
        nid0 = cards_state.get(card_key(c), {}).get("note_id")
        for name in link_names(c):
            known_titles[name] = nid0

    # index BEFORE the creates: phase A needs it to ADOPT notes that an
    # earlier killed run created but never recorded (matching them by
    # folder+title instead of duplicating them). None = index unavailable
    # (rate limit): skip adoption + remote missing/conflict/permission
    # checks, keep the md5-incremental part.
    remote_index = None
    try:
        remote_index = fetch_remote_index()
    except Exception as e:                                   # noqa: BLE001
        report["errors"].append(
            {"card": None, "title": "(remote index)",
             "err": f"HackMD note list 失敗（rate limit？稍後重跑）——本輪"
                    f"跳過收養與遠端 missing/conflict/權限檢查：{str(e)[:120]}"})

    claimed = {v["note_id"] for v in cards_state.values() if v.get("note_id")}
    unclaimed, strays = {}, []
    managed_folders = {cc.get("folder_id") for _, cc, _ in targets}
    for nid2, info2 in (remote_index or {}).items():
        if nid2 in claimed or info2.get("folder") not in managed_folders:
            continue
        # only PLACEHOLDER-content notes are adoptable — those are the
        # signature of a killed run's phase A. A same-titled note with real
        # content might be hand-made: adopting it would let phase B
        # overwrite it (its state carries no last_changed_at to conflict on)
        if info2.get("content_md5") == PLACEHOLDER_MD5:
            unclaimed.setdefault((info2["folder"], info2.get("title")),
                                 []).append(nid2)
        else:
            strays.append({"note": nid2, "title": info2.get("title"),
                           "folder": info2["folder"],
                           "why": "非 placeholder 的無主同資料夾 note——"
                                  "不自動收養/覆寫；手建請忽略，確定是遺孤"
                                  "可手動補 state 條目或刪除"})

    # phase A: create every brand-new card FIRST so the link map is complete
    # before any content is finalized — first publication already carries the
    # promised note-to-note links (no second-run convergence needed). State
    # is saved after EVERY create/adopt: a killed run must never lose the
    # ledger of notes it already created (the original sin behind orphans).
    for key, cc, card in targets:
        ck, title = card_key(card), card["title"]
        if (cards_state.get(ck) or {}).get("note_id"):
            continue
        try:
            cand = unclaimed.get((cc.get("folder_id"), title))
            if cand:
                nid = cand.pop(0)
                if dry:
                    report["adopted"].append({"card": ck, "note": nid,
                                              "title": title})
                    continue
                cards_state[ck] = {"note_id": nid, "md5": None,
                                   "last_changed_at": None, "title": title}
                for name in link_names(card):
                    known_titles[name] = nid
                report["adopted"].append({"card": ck, "note": nid,
                                          "title": title})
                save_state(state)
                continue
            if dry:
                report["created"].append({"card": ck, "title": title})
                continue
            nid = note_create(title, PLACEHOLDER, cc.get("folder_id"), cfg, cc)
            cards_state[ck] = {"note_id": nid, "md5": None,
                               "last_changed_at": None, "title": title}
            for name in link_names(card):
                known_titles[name] = nid
            report["created"].append({"card": ck, "note": nid, "title": title})
            save_state(state)
        except QuotaExhausted as e:
            report["aborted"] = str(e)
            break
        except Exception as e:                               # noqa: BLE001
            report["errors"].append({"card": ck, "title": title,
                                     "err": str(e)[:200]})

    # anything still unclaimed after adoption is a stray duplicate (e.g. two
    # killed runs created the same card twice) — surface it, never delete
    for (fld, ttl), nids in unclaimed.items():
        for nid2 in nids:
            report["stray_duplicates"].append(
                {"note": nid2, "title": ttl, "folder": fld,
                 "why": "placeholder 遺孤但同卡已有認領 note——重複 create，"
                        "可刪"})
    report["stray_duplicates"] += strays

    known_ids = {card_key(c): {"note_id": cards_state.get(card_key(c), {}).get("note_id"),
                               "title": c["title"]}
                 for _, _, c in targets
                 if cards_state.get(card_key(c), {}).get("note_id")}
    mention_map = dict(known_ids)
    for cid2, title2 in all_titles.items():
        mention_map.setdefault(cid2, {"note_id": None, "title": title2})
    note_to_card = {v["note_id"]: {"card": k, "title": v["title"]}
                    for k, v in mention_map.items() if v.get("note_id")}

    # phase B: render + write content (freshly created notes always update:
    # their md5 is None)
    title_map = {t: n for t, n in known_titles.items() if n}
    base_render = lambda m: rewrite_links(m, title_map, mention_map)  # noqa: E731
    wb_enabled = bool(hk.get("write_back")) and be.name == "obsidian"
    book_index = hk.get("book_index")
    want_read_by_card = {}
    for key, cc, card in targets:
        cid, ck, title = card["id"], card_key(card), card["title"]
        want_read = perm(cfg, "read_permission", "owner", cc)
        want_read_by_card[ck] = want_read
        prev = cards_state.get(ck) or {}
        if not prev.get("note_id"):
            continue  # dry-run create, or create failed above
        try:
            is_book = book_index and book_index in (cid, ck)
            if is_book:
                render = lambda m, _t=title: book_transform(base_render(m), _t)  # noqa: E731,E501
            else:
                render = base_render
            src_md = read_md(cid)
            md = render(src_md)
            digest = content_md5(md)
            if remote_index is not None and prev["note_id"] not in remote_index \
                    and prev.get("md5") is not None:
                report["errors"].append(
                    {"card": ck, "title": title,
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
                # level 2 (opt-in): the HackMD-side edit flows back — but ONLY
                # for notes nobody else can edit (effective write_permission
                # owner), never when the source moved too, and only with a
                # base snapshot to diff against.
                why_extra = ""
                if is_book:
                    # the book index is authored locally; its rendered form
                    # (setext, relative links) must never be reversed into
                    # the vault
                    why_extra = "；book 目錄卡不寫回——請改本地正本"
                elif wb_enabled and \
                        perm(cfg, "write_permission", "owner", cc) == "owner":
                    source_moved = prev.get("md5") is not None \
                        and prev["md5"] != digest
                    base_md = load_base(ck)
                    if source_moved:
                        why_extra = "；write-back 中止：本地端也改了（真三方衝突）"
                    elif base_md is None:
                        why_extra = "；write-back 中止：無 base 快照（先跑一輪前向）"
                    elif dry:
                        why_extra = "；dry-run（實跑會 write-back）"
                    else:
                        info = note_get(prev["note_id"])
                        try:
                            # the REMOTE's actual write permission is the
                            # authority, not the config value — a note opened
                            # up on hackmd.io means someone else may have
                            # made this edit
                            if info.get("write_permission") != "owner":
                                raise ValueError(
                                    "遠端實際寫權限非 owner（此編輯可能出自"
                                    "他人）——先在 HackMD 收回寫權限")
                            new_vault = write_back(
                                src_md, base_md, info["content"],
                                note_to_card, render,
                                degrades=lambda p: para_degrades(
                                    p, title_map, mention_map))
                            # narrow re-check: the vault file must not have
                            # moved since we read it at the top of this card
                            if read_md(cid) != src_md:
                                raise ValueError(
                                    "vault 檔在同步過程中被改動——下輪重試")
                        except ValueError as e:
                            why_extra = f"；write-back 中止（整卡凍結）：{e}"
                        else:
                            be.save_card(cid, new_vault)
                            new_render = render(new_vault)
                            cards_state[ck] = {
                                "note_id": prev["note_id"],
                                "md5": content_md5(new_render),
                                "last_changed_at": info["last_changed_at"],
                                "title": title}
                            save_base(ck, new_render)
                            save_state(state)
                            report["written_back"].append(
                                {"card": ck, "note": prev["note_id"],
                                 "title": title})
                            continue
                report["conflicts"].append(
                    {"card": ck, "note": prev["note_id"], "title": title,
                     "why": "HackMD 端在上次同步後被編輯——不覆蓋，"
                            "手動合併後重跑（或刪 state 條目強制覆蓋）" + why_extra})
                continue
            # ONE PATCH per card: content and the declarative read
            # permission ride together — two rapid PATCHes to the same note
            # race in HackMD's async pipeline and one gets dropped
            if prev.get("md5") == digest:
                if perm_drift and not dry:
                    note_set_read_permission(prev["note_id"], want_read)
                if not dry and load_base(ck) is None:
                    save_base(ck, md)   # backfill for pre-level-2 states
                report["skipped"] += 1
                continue
            if remote_index is None and prev.get("md5") is not None:
                # no remote visibility (rate limit): updating an existing
                # note here could silently clobber an undetected HackMD-side
                # edit — defer to a run that can see the remote state
                report["errors"].append(
                    {"card": ck, "title": title,
                     "err": "remote index 不可用——跳過內容更新以免蓋掉"
                            " HackMD 端未偵測的編輯（下輪重試）"})
                continue
            if not dry:
                body = {"content": md}
                if perm_drift:
                    body["readPermission"] = want_read
                api("PATCH", f"/notes/{prev['note_id']}", body)
                cards_state[ck] = {"note_id": prev["note_id"], "md5": digest,
                                   "last_changed_at": None,  # backfilled below
                                   "title": title}
                save_base(ck, md)
                save_state(state)
            report["updated"].append({"card": ck, "note": prev["note_id"],
                                      "title": title})
        except QuotaExhausted as e:
            report["aborted"] = str(e)
            break
        except Exception as e:                               # noqa: BLE001
            report["errors"].append({"card": ck, "title": title,
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
                # freshly created notes were invisible to the pre-create
                # index — correct their read-permission drift here (the API
                # silently falls back to owner on values it dislikes)
                want = want_read_by_card.get(cid2)
                if want and info.get("read_permission") \
                        and info["read_permission"] != want:
                    note_set_read_permission(rec["note_id"], want)
                if rec.get("md5") and info["content_md5"] != rec["md5"]:
                    rec["md5"] = None           # force a re-send next run
                    report["errors"].append(
                        {"card": cid2, "title": rec.get("title"),
                         "err": "寫入未落地（202 被異步丟棄）——已標記重送，"
                                "重跑 sync 收斂"})
            except QuotaExhausted as e:
                report["aborted"] = str(e)
                break
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
