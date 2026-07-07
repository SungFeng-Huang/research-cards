#!/usr/bin/env python3
"""
Scholar Inbox → Heptabase Clip
Scheduled daily via CronCreate (Claude Code). Also runnable manually.

Architecture:
  All Bash work (osascript, heptabase CLI) runs as direct subprocess calls.
  Claude CLI is invoked ONLY for text-in / text-out tasks (translation,
  summary generation).
"""

import base64
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

# Non-login shells (scheduled/automated runs) can have a minimal PATH that omits
# Homebrew — so bare `heptabase` (in /opt/homebrew/bin) fails with FileNotFound.
# Prepend the dirs the pipeline's tools live in so every subprocess (heptabase,
# rsvg-convert) resolves regardless of launch context.
os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# ── Constants ─────────────────────────────────────────────────────────────────
import shutil as _shutil
CLAUDE_BIN = _shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def _state_path(name):
    """State lives beside the RESOLVED config (hbconfig honors the
    RESEARCH_CARDS_CONFIG/HEPTABASE_CARDS_CONFIG envs and the pre-rename
    legacy dir), so state and topics/aliases share one data root. A
    pre-existing legacy file keeps winning: unattended pipelines migrate
    only by explicit move, never by surprise."""
    for legacy in (Path.home() / ".claude" / name,
                   Path.home() / ".config" / "heptabase-cards" / name):
        if legacy.exists():
            return str(legacy)
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "..", "_shared"))
        import hbconfig
        new = Path(hbconfig.user_data_dir()) / name
    except Exception:
        new = Path.home() / ".config" / "research-cards" / name
    new.parent.mkdir(parents=True, exist_ok=True)
    return str(new)


STATE_FILE     = _state_path("scholar_inbox_state.json")
NO_IMAGE_FILE  = _state_path("scholar_inbox_no_images.json")
# Tasks values that, when assigned, mean a comparison-overview card must be re-synced.
# Maps Tasks value → the unified `overview` skill's TOPIC KEY that owns that card
# (invoke /research-cards:overview with the topic; CLI: sync_overview.py <topic> …).
def _overview_tasks():
    """Tasks value -> owning topic key, derived from the USER topic snapshots
    (local files — no runtime graph reads, so cron-safe). Empty when no
    topics are configured yet: routing then simply proposes nothing."""
    out = {}
    try:
        import glob as _glob
        import sys as _sys
        _sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "..", "_shared"))
        import hbconfig as _hb
        root = _hb.topics_dir()
        for sp in _glob.glob(os.path.join(root, "*", "topic_snapshot.json")):
            try:
                snap = json.load(open(sp, encoding="utf-8"))
            except Exception:
                continue
            key = snap.get("skill") or os.path.basename(os.path.dirname(sp))
            for v in snap.get("task_values") or []:
                out[v] = key
    except Exception:
        pass
    return out


OVERVIEW_TASKS = _overview_tasks()

# ── Backend routing ───────────────────────────────────────────────────────────
# backend == "obsidian": card/journal I/O goes to the Obsidian vault via
# _shared/backend.py. backend == "heptabase"/"both" (or config missing):
# the ORIGINAL heptabase-CLI paths below run untouched.
# config overrides for tag/property ids (fallback: the author's workspace)
def _hb_ids():
    try:
        return _hbconfig.load_config().get("heptabase") or {}
    except Exception:
        return {}


OBS = None
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                    "..", "_shared"))
    import hbconfig as _hbconfig
    _cfg = _hbconfig.load_config()
    if _cfg["backend"] == "obsidian":
        from backend import ObsidianBackend as _ObsidianBackend
        OBS = _ObsidianBackend(_cfg)
except Exception:
    OBS = None

try:
    ARXIV_PROP_ID = _hbconfig.hb_id("props", "arxiv")
    SOURCE_TYPE_PROP_ID = _hbconfig.hb_id("props", "source_type")
    TASKS_PROP_ID = _hbconfig.hb_id("props", "tasks")
    TOPICS_PROP_ID = _hbconfig.hb_id("props", "topics")
    STUDY_PAPER_TAG_ID = _hbconfig.hb_id("collections", "papers", "tag_id")
    OVERVIEW_TAG_ID = _hbconfig.hb_id("collections", "overviews", "tag_id")
except Exception:
    ARXIV_PROP_ID = SOURCE_TYPE_PROP_ID = TASKS_PROP_ID = TOPICS_PROP_ID = None
    STUDY_PAPER_TAG_ID = OVERVIEW_TAG_ID = None


def _need(value, key):
    if not value or (isinstance(value, str) and value.startswith("<") and value.endswith(">")):
        sys.exit(f"config 缺少 heptabase.{key}（heptabase 模式必填，佔位符 <…> 視同未設定）")
    return value

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    print(msg, flush=True)

# ── Paper ID helpers ──────────────────────────────────────────────────────────
# A paper ID is one of:
#   "2604.00292"             numeric arxiv ID
#   "alphaxiv:deepseek-v4"   alphaXiv-only paper (named slug, not on arxiv)
#   "openreview:JbLmIoWwDC"  OpenReview paper (no arxiv)
#   "aclanthology:2026.eacl-short.18"  ACL Anthology conference paper
def id_kind(pid):
    if re.match(r'^\d{4}\.\d{4,5}$', pid):
        return "arxiv"
    if ":" in pid:
        return pid.split(":", 1)[0]
    return "arxiv"

def bare_id(pid):
    """Strip the source prefix. For alphaXiv overview/abs URLs."""
    return pid.split(":", 1)[1] if ":" in pid else pid

def is_arxiv(pid):
    return id_kind(pid) == "arxiv"

# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            # migrate legacy single-subject format
            if "last_subject" in data and "processed_subjects" not in data:
                s = data["last_subject"]
                data["processed_subjects"] = [s] if s else []
            return data
    except Exception:
        return {"processed_subjects": [], "last_date": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── No-image record ───────────────────────────────────────────────────────────
# Cards created without figures are recorded here. Each scheduled run retries
# fetching figures for them — papers too new to have arxiv HTML at clip time
# often get an HTML version (with figures) days later.
def load_no_image_record():
    try:
        with open(NO_IMAGE_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_no_image_record(records):
    with open(NO_IMAGE_FILE, "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def record_no_image_card(card_id, arxiv_id, title):
    records = load_no_image_record()
    if any(r["card_id"] == card_id for r in records):
        return
    records.append({"card_id": card_id, "arxiv_id": arxiv_id,
                    "title": title[:80], "last_checked": date.today().isoformat()})
    save_no_image_record(records)

# ── Step 1: Read Scholar Inbox emails ─────────────────────────────────────────
APPLESCRIPT_SUBJECT_BODY = """
on run argv
  set msgIndex to (item 1 of argv) as integer
  set acctName to item 2 of argv
  set mboxName to item 3 of argv
  tell application "Mail"
    set targetAccount to first account whose name contains acctName
    set inboxFolder to first mailbox of targetAccount whose name is mboxName
    if msgIndex > (count of messages of inboxFolder) then
      return "---OUT_OF_RANGE---"
    end if
    set theMessage to message msgIndex of inboxFolder
    set msgSubject to subject of theMessage
    set msgContent to content of theMessage
    set d to date received of theMessage
    set y to (year of d) as integer
    set m to (month of d) as integer
    set dd to (day of d) as integer
    set isoDate to (y as string) & "-" & (text -2 thru -1 of ("0" & m)) & "-" & (text -2 thru -1 of ("0" & dd))
    return msgSubject & "\n---DATE---\n" & isoDate & "\n---BODY---\n" & msgContent
  end tell
end run
"""

APPLESCRIPT_SOURCE = """
on run argv
  set msgIndex to (item 1 of argv) as integer
  set acctName to item 2 of argv
  set mboxName to item 3 of argv
  tell application "Mail"
    set targetAccount to first account whose name contains acctName
    set inboxFolder to first mailbox of targetAccount whose name is mboxName
    if msgIndex > (count of messages of inboxFolder) then
      return "---OUT_OF_RANGE---"
    end if
    set theMessage to message msgIndex of inboxFolder
    return subject of theMessage & "\n---SOURCE---\n" & source of theMessage
  end tell
end run
"""

def _email_cfg():
    """Mail.app source: config email.{account, mailbox}; defaults = author's.
    Values are passed to osascript as argv (never spliced into the script)."""
    try:
        e = _hbconfig.load_config().get("email") or {}
    except Exception:
        e = {}
    return (str(e.get("account") or "iCloud"),
            str(e.get("mailbox") or "Scholar Inbox"))


def read_scholar_inbox(index=1):
    acct, mbox = _email_cfg()
    result = subprocess.run(
        ["osascript", "-e", APPLESCRIPT_SUBJECT_BODY, str(index), acct, mbox],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript error: {result.stderr.strip()}")
    if "---OUT_OF_RANGE---" in result.stdout:
        return None, None, None
    # Format: subject \n---DATE---\n YYYY-MM-DD \n---BODY---\n body
    head, _, body = result.stdout.partition("\n---BODY---\n")
    subject, _, recv_date = head.partition("\n---DATE---\n")
    return subject.strip(), recv_date.strip(), body.strip()

def read_scholar_inbox_source(index=1):
    """Read full email source (HTML) to extract Scholar Inbox paper_id links."""
    acct, mbox = _email_cfg()
    result = subprocess.run(
        ["osascript", "-e", APPLESCRIPT_SOURCE, str(index), acct, mbox],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0 or "---OUT_OF_RANGE---" in result.stdout:
        return "", ""
    parts = result.stdout.split("\n---SOURCE---\n", 1)
    subject = parts[0].strip()
    source = parts[1] if len(parts) > 1 else ""
    return subject, source

def lookup_arxiv_id_via_api(title, authors):
    """
    Query arxiv search API to find an arxiv ID by title. Fast and reliable.
    Returns arxiv ID string like "2606.10231", or None.
    """
    query = urllib.parse.quote(f'ti:"{title}"')
    url = f"https://export.arxiv.org/api/query?search_query={query}&max_results=3&sortBy=relevance"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8")
        # Extract arxiv IDs from <id> tags like http://arxiv.org/abs/2606.11643v1
        ids = re.findall(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", xml)
        if ids:
            return ids[0]
    except Exception as e:
        log(f"  [arxiv API] {e}")
    return None

def lookup_arxiv_id_via_claude(title, authors):
    """
    Fallback: use claude --print with alphaxiv MCP tool to find an arxiv ID.
    Only called if arxiv API lookup fails.
    """
    prompt = (
        f'Find the arxiv ID for this paper: "{title}" by {authors}. '
        f'Use alphaxiv search tools. '
        f'Return ONLY the arxiv ID in format XXXX.XXXXX, nothing else.'
    )
    output = call_claude(prompt, timeout=180)
    if output:
        m = re.search(r"\d{4}\.\d{4,5}", output.strip())
        if m:
            return m.group()
    return None

def lookup_arxiv_id(title, authors):
    """Try arxiv API first, fall back to Claude MCP lookup."""
    aid = lookup_arxiv_id_via_api(title, authors)
    if aid:
        return aid
    return lookup_arxiv_id_via_claude(title, authors)

def extract_papers_from_body(body):
    """
    Parse Scholar Inbox plain text to extract (score, title, authors) tuples.
    The venue line varies by source:
      <score>
      ArXiv YYYY (Month DD)          ← arxiv preprints
      <title>
      <authors>
    or for conference proceedings (NO parenthetical date):
      <score>
      ICLR 2026                       ← e.g. ICLR / EACL / AAAI / NeurIPS
      <title>                         ← also "Findings of EACL 2026" (multi-word)
      <authors>
    The parenthetical "(Month DD)" is optional and the venue may be multi-word,
    so both arxiv and conference papers are captured.
    """
    entries = re.findall(
        r'\n(\d{2,3})\s*\n[A-Za-z][A-Za-z .]*?\s\d{4}\s*(?:\([^)]+\))?\s*\n([^\n]+)\n([^\n]+)\n',
        body
    )
    return [(score.strip(), title.strip(), authors.strip()) for score, title, authors in entries]

def resolve_named_alphaxiv_id(named_id, source_decoded):
    """
    For non-numeric alphaxiv slugs (e.g. 'deepseek-v4', 'mai-thinking-1'),
    first try to map to a numeric arxiv ID via the page title + arxiv API.
    If the paper is NOT on arxiv, keep it as an alphaXiv-only paper and return
    "alphaxiv:{slug}" — the pipeline can still build a card from the alphaXiv
    overview (which exists for these slugs).
    Returns an arxiv ID, "alphaxiv:{slug}", or None.
    """
    # Try to find a numeric arxiv ID via the page <title> + arxiv API
    url = f"https://alphaxiv.org/abs/{named_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        title_m = re.search(r'<title>([^<]+)</title>', html)
        if title_m:
            raw_title = title_m.group(1)
            title = re.sub(r'\s*\|\s*alphaXiv.*$', '', raw_title, flags=re.IGNORECASE).strip()
            if title:
                log(f"  [NAMED] {named_id} → title: {title[:60]}")
                aid = lookup_arxiv_id_via_api(title, "")
                if aid:
                    return aid
    except Exception as e:
        log(f"  [NAMED] {named_id} → fetch failed: {e}")

    # Fallback: find title in plain-text source near this named URL
    pattern = rf'alphaxiv\.org/abs/{re.escape(named_id)}[^\n]*\n[^\n]*\n([A-Z][^\n]{{5,}})\n'
    m = re.search(pattern, source_decoded)
    if m:
        title = m.group(1).strip()
        aid = lookup_arxiv_id_via_api(title, "")
        if aid:
            return aid

    # Not on arxiv → keep as alphaXiv-only paper (overview still exists)
    log(f"  [NAMED] {named_id} → not on arxiv, keeping as alphaxiv:{named_id}")
    return f"alphaxiv:{named_id}"


def extract_arxiv_ids(body, source=""):
    """
    Extract arxiv IDs from Scholar Inbox email.
    Strategy 1: direct arxiv.org/alphaxiv.org URLs in body or source.
      1a. Decode quoted-printable soft line breaks (=\\n) before matching.
      1b. Resolve non-numeric alphaxiv IDs (e.g. deepseek-v4) via title lookup.
    Strategy 2: Parse titles from plain text → arxiv API + claude lookup.
    """
    # QP-decode soft line breaks so IDs like "2606.=\n05405" become "2606.05405"
    decoded_source = source.replace("=\n", "")

    # Strategy 1: direct arxiv/alphaxiv URLs
    ids = []
    seen = set()
    for text in [body, decoded_source]:
        for pattern in [
            r"arxiv\.org/abs/(\d{4}\.\d{4,5})",
            r"arxiv\.org/pdf/(\d{4}\.\d{4,5})",
            r"alphaxiv\.org/(?:abs|overview|zh/overview)/(\d{4}\.\d{4,5})",
        ]:
            for m in re.finditer(pattern, text):
                aid = m.group(1)
                if aid not in seen:
                    ids.append(aid)
                    seen.add(aid)

    # Strategy 1b: non-numeric alphaxiv IDs (e.g. alphaxiv.org/abs/deepseek-v4)
    named_ids = re.findall(
        r'alphaxiv\.org/abs/([a-zA-Z][a-zA-Z0-9\-]+)',
        decoded_source
    )
    named_seen = set()
    for named_id in named_ids:
        if named_id in named_seen:
            continue
        named_seen.add(named_id)
        aid = resolve_named_alphaxiv_id(named_id, decoded_source)
        if aid and aid not in seen:
            ids.append(aid)
            seen.add(aid)

    if ids:
        return ids

    # Strategy 2: extract titles from plain text → arxiv API + claude search
    papers = extract_papers_from_body(body)
    if not papers:
        return []

    log(f"  Resolving {len(papers)} paper titles via alphaxiv...")
    arxiv_ids = []
    seen_ids = set()
    for score, title, authors in papers:
        log(f"  [{score}] {title[:55]}...")
        aid = lookup_arxiv_id(title, authors[:60])
        if aid and aid not in seen_ids:
            arxiv_ids.append(aid)
            seen_ids.add(aid)
            log(f"        → {aid}")
        else:
            log(f"        → not found")
    return arxiv_ids

# ── Step 2: Fetch alphaXiv content ────────────────────────────────────────────
def _extract_intermediate_report(html):
    """The alphaXiv overview page is a client-rendered SPA: the AI report is
    NOT in the rendered HTML (tag-stripping yields ~250 chars of nav chrome).
    It lives inside the serialized JS payload as the value of an
    `intermediateReport:"..."` (or `"intermediateReport":"..."`) key, with the
    markdown JSON-string-escaped (\\n, \\", LaTeX \\\\mu, etc.).

    Without this extraction, fetch_alphaxiv returns raw HTML whose first ~20K
    chars are <head> boilerplate, so translate_content(content[:N]) feeds the
    model pure CSS/JS preload tags and the whole report (incl. late sections
    like TTS) is lost. Returns clean markdown, or None if not present."""
    for key in ('intermediateReport:"', '"intermediateReport":"'):
        start = html.find(key)
        if start < 0:
            continue
        i = start + len(key)
        buf = []
        while i < len(html):
            c = html[i]
            if c == "\\":            # keep escape pair intact for json.loads
                buf.append(html[i:i + 2]); i += 2; continue
            if c == '"':             # unescaped closing quote ends the value
                break
            buf.append(c); i += 1
        try:
            report = json.loads('"' + "".join(buf) + '"')
        except Exception:
            return None
        return report if report.strip() else None
    return None

# ── Source: HuggingFace Daily Papers ─────────────────────────────────────────
def is_hf_daily(subject, source=""):
    """HF 每日精選信：主旨「Daily papers of …」＋source 內有 papers 連結
    （雙重確認，避免撞到其他同名信件）。"""
    if not re.match(r"(?i)^daily papers of\b", (subject or "").strip()):
        return False
    return "huggingface.co/papers" in (source or "").replace("=\n", "")


def extract_hf_papers(body, source):
    """[{id, title, upvotes}]。arxiv ID 直接取自 source 的
    huggingface.co/papers/<id> 連結（順序即榜單序）；標題與讚數取自純文字
    行「Title (N ▲)」依序配對——數量不合時以連結序為準（標題僅供選文，
    配錯不影響建卡正確性）。"""
    decoded = (source or "").replace("=\n", "")
    ids, seen = [], set()
    for m in re.finditer(r"huggingface\.co/papers/(\d{4}\.\d{4,5})", decoded):
        if m.group(1) not in seen:
            ids.append(m.group(1))
            seen.add(m.group(1))
    rows = re.findall(r"^(.+?)\s*\((\d+)\s*▲\)\s*$", body or "", re.M)
    if len(ids) != len(rows):
        log(f"  [HF] 連結 {len(ids)} 筆 vs 標題行 {len(rows)} 筆——依連結序配對")
    return [{"id": aid,
             "title": (rows[i][0].strip() if i < len(rows) else ""),
             "upvotes": (int(rows[i][1]) if i < len(rows) else 0)}
            for i, aid in enumerate(ids)]


def select_hf_papers(papers):
    """HF 榜單不是個人化清單——選文兩層：
    1. 讚數門檻：config email.hf_min_upvotes（預設 0 ＝不過濾）。
    2. 領域相關性：config profile.field 有設時，請 agent 依標題挑出相關
       論文（只回 arxiv ID）。agent 明確回 NONE → 這天沒有相關論文（信
       照樣標記已處理）；呼叫失敗 → 保守全收並大聲記錄（寧多勿漏，
       多的靠既有 dedup 與人工清理）。"""
    try:
        cfg = _hbconfig.load_config()
    except Exception:
        cfg = {}
    min_up = 0
    try:
        min_up = int((cfg.get("email") or {}).get("hf_min_upvotes") or 0)
    except (TypeError, ValueError):
        pass
    kept = [p for p in papers if p["upvotes"] >= min_up]
    if len(kept) < len(papers):
        log(f"  [HF] 讚數門檻 {min_up}：{len(papers)} → {len(kept)}")
    field = ((cfg.get("profile") or {}).get("field") or "").strip()
    interests = [str(t) for t in
                 ((cfg.get("email") or {}).get("topics_of_interest") or []) if t]
    if (not field and not interests) or not kept:
        return kept
    listing = "\n".join(f"{p['id']}: {p['title'] or '(no title)'}" for p in kept)
    crit = []
    if field:
        crit.append(f"與「{field}」領域直接相關（模型、資料、評測、應用皆算；"
                    f"跨領域方法僅在明顯可遷移時入選）")
    if interests:
        crit.append("屬於這些主題之一（依標題判斷，明顯落在任一主題的範圍"
                    "就算符合，不必苛求）：" + "、".join(interests))
    criteria = "；或 ".join(f"({chr(97 + i)}) {c}" for i, c in enumerate(crit))
    prompt = (f"你是研究者的論文篩選助理。以下是今天 HuggingFace Daily Papers "
              f"的清單（arxiv ID: 標題）。只挑出符合任一條件的論文：{criteria}。"
              f"只輸出入選的 arxiv ID、每行一個；全部不符就輸出 NONE。"
              f"\n\n{listing}")
    out = call_claude(prompt, timeout=180)
    if not (out or "").strip():
        log("  [HF] 領域篩選呼叫失敗——保守全收（靠 dedup/人工清理）")
        return kept
    chosen = set(re.findall(r"\d{4}\.\d{4,5}", out))
    sel = [p for p in kept if p["id"] in chosen]
    label = "＋".join(filter(None, [field, "興趣主題" if interests else ""]))
    log(f"  [HF] 選文（{label}）：{len(kept)} → {len(sel)}")
    for p in sel:
        log(f"    ✓ {p['id']} {p['title'][:60]}")
    return sel


def fetch_alphaxiv(paper_id):
    """Fetch the alphaXiv overview. Works for numeric arxiv IDs and named
    slugs (alphaxiv:slug) alike — both have overview/{bare} pages.

    Returns (content, is_ai_report). For the SPA overview we extract the clean
    `intermediateReport` markdown (is_ai=True); if that key is absent (no report
    generated yet) we fall back to the arxiv abstract page (is_ai=False)."""
    slug = bare_id(paper_id)
    url = f"https://alphaxiv.org/overview/{slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        report = _extract_intermediate_report(html)
        if report:
            return report, True
        log(f"  [WARN] no intermediateReport in overview for {slug}; falling back")
    except urllib.error.HTTPError as e:
        log(f"  [HTTP {e.code}] {url}")
    except Exception as e:
        log(f"  [ERR] fetch failed: {e}")

    # Fallback: arxiv abstract page (only meaningful for numeric arxiv IDs)
    if is_arxiv(paper_id):
        abs_url = f"https://arxiv.org/abs/{slug}"
        try:
            req = urllib.request.Request(abs_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace"), False
        except Exception as e:
            return f"Failed to fetch content for {paper_id}: {e}", False
    return f"Failed to fetch content for {paper_id}", False

RSVG_CONVERT = _shutil.which("rsvg-convert") or "/opt/homebrew/bin/rsvg-convert"

def _svg_to_data_url(svg_content):
    """Convert inline SVG string to a PNG data URL via rsvg-convert."""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
        f.write(svg_content.encode("utf-8"))
        tmp = f.name
    try:
        result = subprocess.run(
            [RSVG_CONVERT, "-f", "png", "-w", "600", tmp],
            capture_output=True, timeout=15
        )
        if result.returncode == 0:
            b64 = base64.b64encode(result.stdout).decode()
            return f"data:image/png;base64,{b64}"
    except Exception:
        pass
    finally:
        os.unlink(tmp)
    return None

# ── Step 2b: Fetch arxiv HTML images ─────────────────────────────────────────
def _resolve_fig_url(src, base_url, arxiv_id):
    """Resolve a figure src (from arxiv HTML / ar5iv) to an absolute URL.

    The page lives at {base_url}/html/{arxiv_id}/, so relative srcs must be
    rooted there. A prior bug rooted any '/'-containing src at
    {base_url}/html/{src}, which DROPPED the arxiv_id for paths like
    'extracted/5314337/images/x.png' or 'image/y.png' → 404. Only srcs whose
    first segment is itself an arxiv id (e.g. '2605.27772v1/x1.png') are
    already rooted under /html/."""
    if src.startswith("http"):
        return src
    if src.startswith("/"):
        return base_url + src
    if "/" in src:
        first = src.split("/", 1)[0]
        if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', first):
            return f"{base_url}/html/{src}"           # already paper-rooted
        return f"{base_url}/html/{arxiv_id}/{src}"    # relative → root at paper
    return f"{base_url}/html/{arxiv_id}/{src}"

def _parse_figures(html, base_url, arxiv_id):
    """
    Extract figure images from an HTML page.
    base_url: used to resolve relative paths (e.g. "https://arxiv.org" or "https://ar5iv.org")
    Returns list of {"src": absolute_url_or_data_url, "caption": str}.
    """
    figures = re.findall(r'<figure[^>]*>(.*?)</figure>', html, re.DOTALL)
    results = []
    seen_srcs = set()

    for fig in figures:
        cap = re.search(r'<figcaption[^>]*>(.*?)</figcaption>', fig, re.DOTALL)
        caption = re.sub(r'<[^>]+>', '', cap.group(1)).strip()[:200] if cap else ""

        # Try PNG/JPG first
        img = re.search(r'src=["\']([^"\']*\.(?:png|jpg|jpeg))["\']', fig, re.IGNORECASE)
        if img:
            src = img.group(1)
            if any(s in src for s in ('static', 'icon', 'logo', 'ar5iv.png')):
                continue
            abs_src = _resolve_fig_url(src, base_url, arxiv_id)
            if abs_src in seen_srcs:
                continue
            seen_srcs.add(abs_src)
            results.append({"src": abs_src, "caption": caption})
            continue

        # SVG figures (max 2 per card — each data URL is large)
        svg_count = sum(1 for r in results if r["src"].startswith("data:"))
        if svg_count >= 2:
            continue

        # (a) external SVG file referenced via <img src="...svg">
        svg_img = re.search(r'src=["\']([^"\']*\.svg)["\']', fig, re.IGNORECASE)
        if svg_img and os.path.exists(RSVG_CONVERT):
            src = svg_img.group(1)
            if not any(s in src for s in ('static', 'icon', 'logo', 'ar5iv')):
                svg_url = _resolve_fig_url(src, base_url, arxiv_id)
                data_url = _svg_url_to_data_url(svg_url)
                if data_url and data_url[:80] not in seen_srcs:
                    seen_srcs.add(data_url[:80])
                    results.append({"src": data_url, "caption": caption})
                    continue

        # (b) inline <svg> → convert to PNG data URL
        svg_match = re.search(r'(<svg[\s\S]*?</svg>)', fig)
        if svg_match and os.path.exists(RSVG_CONVERT):
            data_url = _svg_to_data_url(svg_match.group(1))
            if data_url and data_url[:80] not in seen_srcs:
                seen_srcs.add(data_url[:80])
                results.append({"src": data_url, "caption": caption})

    return results

def _svg_url_to_data_url(url):
    """Fetch an external .svg file and convert it to a PNG data URL via rsvg-convert."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            svg = resp.read().decode("utf-8", errors="replace")
        return _svg_to_data_url(svg)
    except Exception:
        return None

def _fetch_html(url):
    """Fetch HTML at url; returns (html_str, base_domain) or raises."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")

def fetch_arxiv_images(arxiv_id):
    """
    Fetch arxiv HTML page and extract figure images with captions.
    Falls back to ar5iv.org when arxiv.org/html returns 404 (older papers).
    Returns list of {"src": url_or_data_url, "caption": str}.
    Non-arxiv papers (alphaxiv slugs, openreview, etc.) have no arxiv HTML.
    """
    if not is_arxiv(arxiv_id):
        return []
    # Primary: arxiv HTML
    try:
        html = _fetch_html(f"https://arxiv.org/html/{arxiv_id}")
        results = _parse_figures(html, "https://arxiv.org", arxiv_id)
        if results:
            return results
        # Fetched OK but no figures → still try ar5iv below
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return []
    except Exception:
        return []

    # Fallback: ar5iv (for papers without HTML version on arxiv)
    try:
        html = _fetch_html(f"https://ar5iv.org/abs/{arxiv_id}")
        return _parse_figures(html, "https://ar5iv.org", arxiv_id)
    except Exception:
        return []

def _rect_area(r):
    return max(0, r.width) * max(0, r.height)

def _pixmap_is_low_content(pix):
    """True if the rendered crop is near-uniform — a blank region or a single
    color swatch wrongly captured as a 'figure'. Real figures (even mostly-white
    architecture diagrams) contain many distinct colors from boxes/text/icons;
    a bad crop has only a handful. Uses distinct significant colors as the
    signal (a high dominant-background fraction alone is normal for diagrams)."""
    try:
        n = pix.n
        data = pix.samples
        if not data:
            return True
        step = max(1, (len(data) // n) // 4000) * n  # ~4000 samples
        counts = {}
        total = 0
        for i in range(0, len(data) - n, step):
            key = tuple(data[i + c] >> 5 for c in range(min(n, 3)))  # 32-level buckets
            counts[key] = counts.get(key, 0) + 1
            total += 1
        if total == 0:
            return True
        # colors appearing in >=0.5% of samples
        significant = sum(1 for v in counts.values() if v / total >= 0.005)
        dominant = max(counts.values()) / total
        # low content: almost one color, OR very few distinct colors
        return dominant >= 0.97 or significant <= 4
    except Exception:
        return False

def pdf_url_for(paper_id):
    """Resolve a downloadable PDF URL for any paper-ID kind. Returns None if
    unknown. Every source the pipeline produces has a stable PDF URL."""
    kind, bid = id_kind(paper_id), bare_id(paper_id)
    if kind == "arxiv":
        return f"https://arxiv.org/pdf/{bid}"
    if kind == "openreview":
        return f"https://openreview.net/pdf?id={bid}"
    if kind == "aclanthology":
        return f"https://aclanthology.org/{bid}.pdf"
    if kind == "alphaxiv":
        # alphaXiv hosts a copy of every paper it indexes
        return f"https://pdfs.assets.alphaxiv.org/{bid}v1.pdf"
    return None

def fetch_pdf_figures(arxiv_id, max_figs=2, char_budget=80000):
    """
    Last-resort figure source: render figure regions directly from the paper PDF.
    Used when an HTML figure source isn't available (brand-new arxiv papers with
    only a PDF, papers whose HTML figures are vector/table-only, and ALL non-arxiv
    papers — openreview / aclanthology / alphaXiv-slug — which have no arxiv HTML
    but do have a downloadable PDF, see pdf_url_for()).

    For each "Figure N" caption, the figure region is the union of image + vector
    drawing blocks above the caption in its column. The region is rendered to a
    width-capped JPEG data URL (PDFs have no hostable image URL). Capped to a few
    figures within `char_budget` total to respect Heptabase's 100k content limit.

    Returns [{"src": data_url, "caption": str}]; [] if PyMuPDF is unavailable,
    the PDF can't be fetched, or no figures are found.
    """
    pdf_url = pdf_url_for(arxiv_id)
    if not pdf_url:
        return []
    try:
        import fitz  # PyMuPDF
    except Exception:
        log("  [PDF] PyMuPDF not installed; skipping PDF figure fallback")
        return []
    try:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as resp:
            doc = fitz.open(stream=resp.read(), filetype="pdf")
    except Exception as e:
        log(f"  [PDF] fetch/open failed: {e}")
        return []

    results, used = [], 0
    for pno in range(min(doc.page_count, 40)):
        if len(results) >= max_figs:
            break
        page = doc[pno]
        d = page.get_text("dict")
        text_blocks, image_rects = [], []
        for b in d["blocks"]:
            if b.get("type") == 1:
                image_rects.append(fitz.Rect(b["bbox"]))
            elif "lines" in b:
                t = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
                text_blocks.append((fitz.Rect(b["bbox"]), t))
        draws = [fitz.Rect(p["rect"]) for p in page.get_drawings()
                 if _rect_area(fitz.Rect(p["rect"])) > 400]
        visual = image_rects + draws
        page_cw = page.rect.width
        for rect, txt in text_blocks:
            if len(results) >= max_figs:
                break
            m = re.match(r'(Figure|Fig\.?)\s*\d+', txt)
            if not m:
                continue
            cap_top, col_l, col_r = rect.y0, rect.x0, rect.x1
            # Full-width figures (caption spanning both columns, e.g. a top-of-page
            # architecture diagram) defeat the single-column bound: their visual
            # blocks fall outside the narrow caption column. Detect a wide caption
            # and bound to the full content width instead.
            full_width = (col_r - col_l) > 0.6 * page_cw
            if full_width:
                col_l, col_r = page.rect.x0 + 28, page.rect.x1 - 28
            above = [r for r in visual if r.y1 <= cap_top + 2
                     and not (r.x1 < col_l - 30 or r.x0 > col_r + 30)]
            if not above:
                continue
            tb_above = [r.y1 for r, t in text_blocks if r.y1 <= cap_top - 2 and len(t) > 40
                        and not (r.x1 < col_l - 5 or r.x0 > col_r + 5)]
            floor = max(tb_above) if tb_above else 0
            content = [r for r in above if r.y0 >= floor - 2]
            if not content:
                continue
            fr = content[0]
            for r in content[1:]:
                fr |= r
            fr = fr & page.rect
            if fr.height < 100 or fr.width < 100:
                continue
            # Low-content (blank/bad-crop) check once, at the base width.
            base_w = 820.0 if full_width else 600.0
            try:
                pix0 = page.get_pixmap(clip=fr, matrix=fitz.Matrix(base_w / fr.width,
                                                                    base_w / fr.width))
            except Exception:
                continue
            if _pixmap_is_low_content(pix0):
                continue   # near-blank / single-color crop (bad bounding)
            # Adaptive sizing: pick the largest (width, quality) whose data URL
            # fits the remaining char budget — full-width figures can be large,
            # and a card already holding text may leave little room.
            remaining = char_budget - used
            data_url = None
            for tw, q in [(base_w, 72), (base_w * 0.82, 70), (base_w * 0.66, 66), (480.0, 60)]:
                if tw > fr.width * 1.5:   # don't upscale beyond ~1.5x
                    tw = fr.width * 1.5
                try:
                    pix = page.get_pixmap(clip=fr, matrix=fitz.Matrix(tw / fr.width, tw / fr.width))
                    durl = "data:image/jpeg;base64," + base64.b64encode(
                        pix.tobytes("jpeg", jpg_quality=q)).decode()
                except Exception:
                    continue
                if len(durl) <= remaining:
                    data_url = durl
                    break
            if not data_url:
                continue   # even the smallest variant won't fit the budget
            used += len(data_url)
            results.append({"src": data_url, "caption": re.sub(r'\s+', ' ', txt).strip()[:200]})
    return results

# ── Image health detection ────────────────────────────────────────────────────
# Detect deficient figures already embedded in cards so they can be re-fetched
# (a broken URL renders as a broken-image icon; a blank data-URL is a bad crop).
def _url_is_image(url, timeout=15):
    """True if url returns 200/206 with image bytes (content-type or magic)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        req.add_header("Range", "bytes=0-2047")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status not in (200, 206):
                return False
            ct = resp.headers.get("Content-Type", "")
            head = resp.read(64)
        return (ct.startswith("image/")
                or head[:8] == b"\x89PNG\r\n\x1a\n" or head[:2] == b"\xff\xd8"
                or head[:6] in (b"GIF87a", b"GIF89a"))
    except Exception:
        return False

def _data_url_is_blank(src):
    """True if a data-URL image decodes to a near-uniform bitmap (bad crop).
    Conservatively returns False if PyMuPDF is unavailable (can't judge)."""
    try:
        import fitz
        raw = base64.b64decode(src.split(",", 1)[1])
        return _pixmap_is_low_content(fitz.Pixmap(raw))
    except Exception:
        return False

def _corrected_html_url(url, arxiv_id):
    """If an arxiv/ar5iv /html/ image URL is missing the arxiv_id segment
    (the old _parse_figures bug, e.g. .../html/extracted/.. or .../html/image/..),
    return the arxiv_id-rooted URL; else None. Does not verify reachability."""
    m = re.match(r'^(https?://[^/]+)/html/(.+)$', url)
    if not m:
        return None
    host, path = m.group(1), m.group(2)
    first = path.split("/", 1)[0]
    if first == arxiv_id or re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', first):
        return None  # already paper-rooted
    return f"{host}/html/{arxiv_id}/{path}"

def image_health(src, arxiv_id=None):
    """Classify a card image src. Returns one of:
    'ok' | 'broken_url' | 'blank' | 'corrupt'. arxiv_id is unused here but kept
    for caller symmetry / future per-source checks."""
    if src.startswith("data:"):
        try:
            base64.b64decode(src.split(",", 1)[1])
        except Exception:
            return "corrupt"
        return "blank" if _data_url_is_blank(src) else "ok"
    if src.startswith("http"):
        return "ok" if _url_is_image(src) else "broken_url"
    return "broken_url"

# ── Step 3: AI translation via claude --print ─────────────────────────────────
# Claude is called ONLY for text → text tasks; no Bash tool needed.

TRANSLATE_PROMPT = """\
以下是一篇學術論文的 AI 分析報告（英文），請翻譯成繁體中文。
直接從 # 開始輸出，不要加任何前綴說明文字。

翻譯規則：
- 保留所有章節標題和編號
- 數值、百分比、模型名稱、benchmark 名稱保持原文（不翻譯）
- 表格保持 markdown 格式
- 技術術語：第一次出現時「英文（中文）」，後續可只用中文
- 機構名稱可保留英文

輸出格式：

# [alphaXiv] {{英文論文標題}}

**作者**：{{作者}}（{{機構}}）

**關鍵詞**：{{3-5 個關鍵術語}}

---

## 1. 作者與機構
## 2. 研究背景與定位
## 3. 核心目標與動機
## 4. 研究方法
## 5. 主要發現與結果
## 6. 研究意義與影響

---

Source: https://www.alphaxiv.org/zh/overview/{arxiv_id}

===原文===
{content}
"""

TRANSLATE_PROMPT_WITH_IMAGES = """\
以下是一篇學術論文的 AI 分析報告（英文），請翻譯成繁體中文，並在適合的位置插入論文圖片。
直接從 # 開始輸出，不要加任何前綴說明文字。

翻譯規則：
- 保留所有章節標題和編號
- 數值、百分比、模型名稱、benchmark 名稱保持原文（不翻譯）
- 表格保持 markdown 格式
- 技術術語：第一次出現時「英文（中文）」，後續可只用中文
- 機構名稱可保留英文

圖片插入規則：
- 根據圖片 caption 判斷屬於哪個章節，插在該章節內容的適當位置
- 每張圖使用兩行：先圖片語法，再斜體 caption
  ![](url)
  _繁體中文 caption（20 字以內）_
- 每張圖只插一次，最多插入 {max_images} 張

可用圖片（按順序，請從中選擇最重要的）：
{image_list}

輸出格式：

# [alphaXiv] {{英文論文標題}}

**作者**：{{作者}}（{{機構}}）

**關鍵詞**：{{3-5 個關鍵術語}}

---

## 1. 作者與機構
## 2. 研究背景與定位
## 3. 核心目標與動機
## 4. 研究方法
## 5. 主要發現與結果
## 6. 研究意義與影響

---

Source: https://www.alphaxiv.org/zh/overview/{arxiv_id}

===原文===
{content}
"""

GENERATE_PROMPT = """\
以下是一篇論文的繁體中文卡片內容，請生成結構化快速摘要。
只輸出 JSON，不要其他文字。

{{
  "ai_summary": "2-3 句話的 AI 摘要（繁體中文，含最重要的數字/結果）",
  "problems": ["問題1", "問題2"],
  "methods": ["方法1", "方法2", "方法3"],
  "results": ["結果1（含具體數字）", "結果2", "結果3"],
  "takeaways": ["要點1", "要點2", "要點3"]
}}

===卡片內容===
{content}
"""

COLORIZE_PROMPT = """\
以下是一篇論文的繁體中文 Heptabase 卡片內容。
請找出應該上色標記的片段，只輸出 JSON array，不要其他文字。

上色規則：
- "red"：負面基準數字、失敗模式、已知侷限（例：低準確率、高錯誤率、現有方法的缺陷）
- "yellow"：本論文提出的模型/方法/benchmark 名稱（1-6 個核心術語），以及論文中首次定義的重要技術術語
- "green"：正面結果、改善幅度（+X%）、SOTA 成績、優於先前方法的數字

輸出格式（JSON array，每個元素為 [文字片段, 顏色]）：
[
  ["片段1", "yellow"],
  ["片段2", "green"],
  ["片段3", "red"]
]

注意：
- 片段必須是卡片中**完全相符**的子字串（含標點、空格）
- 每個片段長度 2-50 字
- 不超過 30 個片段
- 只輸出 JSON，不要說明文字

===卡片內容===
{content}
"""

# ── Teaching-style (single source of truth = card-rewrite/teaching_spec.md) ─────
# Cron emits cards already in the card-rewrite teaching style: 一句話 + 為何該讀
# framing, a 先備知識 glossary, WHY-prose, bilingual terms. The spec lives in the
# card-rewrite skill so style edits happen in ONE place; run.py loads it at runtime
# and falls back to the plain 6-section translation if the file is missing (so the
# automated run never breaks). The 先備知識 section is also the marker card-rewrite's
# is_upgraded() detector keys off — so pipeline-made cards are born "upgraded".
TEACHING_SPEC_PATH = str(Path(__file__).resolve().parents[1] / "card-rewrite/teaching_spec.md")
def _load_teaching_spec():
    try:
        with open(TEACHING_SPEC_PATH, encoding="utf-8") as f:
            spec = f.read().strip()
        reader, field = _profile()
        return spec.replace("〈讀者〉", reader).replace("〈讀者主領域〉", field)
    except Exception:
        return ""

TEACHING_TRANSLATE_PROMPT = """\
以下是一篇學術論文的 AI 分析報告（英文）。請**以此報告為唯一依據**，改寫成一張繁體中文「教學式」Heptabase 卡片。
直接從 # 開始輸出，不要加任何前綴說明文字。

=== 教學式規格 ===
{spec}

=== 輸出骨架 ===
# [alphaXiv] {{英文論文標題}}

**一句話：** {{白話講清楚這篇在做什麼、最關鍵的賭注或貢獻}}

**為什麼{reader}該讀：** {{與{field}的關聯、值得讀的理由}}

**作者**：{{作者}}（{{機構}}）

**關鍵詞**：{{3-5 個關鍵術語，中英並列}}

---

## 0. 先備知識（名詞快速補帖）
- **{{術語（中英並列）}}**：{{白話解釋}}
（列出本篇所有非顯而易見的行話）

## 1. 研究背景與定位
## 2. 核心想法
## 3. 研究方法
## 4. 主要發現與結果
## 5. 研究意義與影響

---

Source: https://www.alphaxiv.org/zh/overview/{arxiv_id}

===原文===
{content}
"""

TEACHING_TRANSLATE_PROMPT_WITH_IMAGES = """\
以下是一篇學術論文的 AI 分析報告（英文）。請**以此報告為唯一依據**，改寫成一張繁體中文「教學式」Heptabase 卡片，並在適合的位置插入論文圖片。
直接從 # 開始輸出，不要加任何前綴說明文字。

=== 教學式規格 ===
{spec}

圖片插入規則：
- 根據圖片 caption 判斷屬於哪個章節，插在該章節內容的適當位置。
- 每張圖兩行：先 `![](url)`，再斜體 `_繁體中文 caption（20 字以內）_`。
- 每張圖只插一次，最多 {max_images} 張。

可用圖片（按順序，挑最重要的）：
{image_list}

=== 輸出骨架 ===
# [alphaXiv] {{英文論文標題}}

**一句話：** {{…}}

**為什麼{reader}該讀：** {{…}}

**作者**：{{作者}}（{{機構}}）

**關鍵詞**：{{3-5 個關鍵術語，中英並列}}

---

## 0. 先備知識（名詞快速補帖）
- **{{術語（中英並列）}}**：{{白話解釋}}

## 1. 研究背景與定位
## 2. 核心想法
## 3. 研究方法
## 4. 主要發現與結果
## 5. 研究意義與影響

---

Source: https://www.alphaxiv.org/zh/overview/{arxiv_id}

===原文===
{content}
"""

def _profile():
    """config profile.{reader, field} — the audience persona for teaching cards."""
    try:
        pr = _hbconfig.load_config().get("profile") or {}
    except Exception:
        pr = {}
    return (pr.get("reader") or "研究者", pr.get("field") or "讀者的主領域")


def _reader():
    return _profile()[0]


def _agent_cli():
    """Which agent CLI does text generation: config `agent` = claude|codex."""
    try:
        return (_hbconfig.load_config().get("agent") or "claude")
    except Exception:
        return "claude"


def call_claude(prompt, timeout=180):
    """Text-in/text-out generation via the configured agent CLI (claude --print
    or codex exec). Name kept for call-site compatibility. No tool use."""
    if _agent_cli() == "codex":
        out = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        out.close()
        try:
            result = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check", "--ephemeral",
                 "-s", "read-only", "-o", out.name, "-"],
                input=prompt, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                text = open(out.name, encoding="utf-8").read().strip()
                if text:
                    return text
            if result.stderr:
                log(f"  [codex stderr] {result.stderr[:200]}")
            return None
        finally:
            os.unlink(out.name)
    result = subprocess.run(
        [CLAUDE_BIN, "--print", prompt],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    if result.stderr:
        log(f"  [claude stderr] {result.stderr[:200]}")
    return None

def generate_color_rules(card_text):
    """Ask Claude to identify text spans and their colors. Returns list of (text, color)."""
    # 12K so color spans can land in late sections (e.g. TTS results), not just
    # the first ~half of the card.
    prompt = COLORIZE_PROMPT.format(content=card_text[:12000])
    output = call_claude(prompt, timeout=240)
    if not output:
        return []
    m = re.search(r"\[.*\]", output, re.DOTALL)
    if not m:
        return []
    try:
        pairs = json.loads(m.group())
        return [(p[0], p[1]) for p in pairs if isinstance(p, list) and len(p) == 2
                and p[1] in ("red", "yellow", "green")]
    except (json.JSONDecodeError, TypeError):
        return []

def _make_color_mark(color):
    return {"type": "color", "attrs": {"type": "text", "color": color}}

def _colorize_text_node(node, rules):
    text = node.get("text", "")
    existing = node.get("marks", [])
    matches = []
    for pattern, color in rules:
        for m in re.finditer(re.escape(pattern), text):
            matches.append((m.start(), m.end(), color))
    if not matches:
        return [node]
    matches.sort(key=lambda x: x[0])
    clean, last_end = [], 0
    for start, end, color in matches:
        if start >= last_end:
            clean.append((start, end, color))
            last_end = end
    result, pos = [], 0
    for start, end, color in clean:
        if pos < start:
            n = {"type": "text", "text": text[pos:start]}
            if existing:
                n["marks"] = existing
            result.append(n)
        colored = {"type": "text", "text": text[start:end],
                   "marks": existing + [_make_color_mark(color)]}
        result.append(colored)
        pos = end
    if pos < len(text):
        n = {"type": "text", "text": text[pos:]}
        if existing:
            n["marks"] = existing
        result.append(n)
    return result

def _process_nodes(nodes, rules):
    result = []
    for node in nodes:
        if node.get("type") == "text":
            result.extend(_colorize_text_node(node, rules))
        else:
            new_node = copy.deepcopy(node)
            if "content" in new_node:
                new_node["content"] = _process_nodes(new_node["content"], rules)
            result.append(new_node)
    return result

def apply_colors(card_id, card_text):
    """Generate color rules via Claude and apply them to a card."""
    rules = generate_color_rules(card_text)
    if not rules:
        return False
    md5, doc = read_card(card_id)
    doc["content"] = _process_nodes(doc["content"], rules)
    save_card(card_id, md5, doc)
    return len(rules)

def _strip_translate_preamble(markdown):
    """
    Remove any preamble text Claude may emit before the actual card.
    The card must start at the first `# ` (h1) heading. Anything before it
    (e.g. "I have the full report. Now I'll translate...") is discarded.
    Returns the cleaned markdown, or the original if no h1 heading is found.
    """
    if not markdown:
        return markdown
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        # First level-1 heading marks the true start of the card.
        if re.match(r'^#\s+', line):
            return "\n".join(lines[i:]).strip()
    return markdown.strip()

def translate_content(content, arxiv_id, images=None):
    # Source link uses the bare slug (overview/deepseek-v4, not alphaxiv:deepseek-v4)
    src_id = bare_id(arxiv_id)
    # alphaXiv intermediate reports run ~15-20K chars; a 10K cap silently dropped
    # the final third (sections 5-6, where late topics like TTS results live).
    # 24K covers a full report while still bounding the raw-HTML fallback case.
    body = content[:24000]
    # Teaching style by default; fall back to the plain 6-section template only if
    # the shared spec file is missing (keeps automated runs working no matter what).
    spec = _load_teaching_spec()
    p_img = TEACHING_TRANSLATE_PROMPT_WITH_IMAGES if spec else TRANSLATE_PROMPT_WITH_IMAGES
    p_txt = TEACHING_TRANSLATE_PROMPT if spec else TRANSLATE_PROMPT
    if images:
        # Exclude data: URLs (SVG base64 strings) — they're too large for the prompt
        candidates = [img for img in images if not img['src'].startswith('data:')][:6]
        if candidates:
            image_list = "\n".join(
                f"{i+1}. [{img['src']}]\n   caption: {img['caption'][:120]}"
                for i, img in enumerate(candidates)
            )
            kw = dict(arxiv_id=src_id, content=body, image_list=image_list,
                      max_images=min(len(candidates), 4))
            prompt = p_img.format(spec=spec, reader=_profile()[0], field=_profile()[1], **kw) if spec else p_img.format(reader=_profile()[0], field=_profile()[1], **kw)
        else:
            prompt = p_txt.format(spec=spec, reader=_profile()[0], field=_profile()[1], arxiv_id=src_id, content=body) if spec \
                     else p_txt.format(reader=_profile()[0], field=_profile()[1], arxiv_id=src_id, content=body)
    else:
        prompt = p_txt.format(spec=spec, reader=_profile()[0], field=_profile()[1], arxiv_id=src_id, content=body) if spec \
                 else p_txt.format(reader=_profile()[0], field=_profile()[1], arxiv_id=src_id, content=body)
    return _strip_translate_preamble(call_claude(prompt, timeout=300))

def generate_summary(card_text):
    # 12K covers the full translated card so the summary's 結果/要點 reflect
    # late sections (e.g. TTS results) rather than only the first few sections.
    prompt = GENERATE_PROMPT.format(content=card_text[:12000])
    output = call_claude(prompt, timeout=120)
    if output:
        m = re.search(r"\{.*\}", output, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None

# ── ProseMirror node helpers ──────────────────────────────────────────────────
def _para(text):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": [{"type": "text", "text": text}]}

def _italic_para(text):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": [{"type": "text", "marks": [{"type": "em"}], "text": text}]}

def _bullet(text):
    return {"type": "bullet_list_item",
            "attrs": {"id": None, "folded": False, "format": None},
            "content": [{"type": "paragraph", "attrs": {"id": None},
                         "content": [{"type": "text", "text": text}]}]}

def _toggle(label, children, folded=False):
    return {"type": "toggle_list_item",
            "attrs": {"id": None, "folded": folded},
            "content": [
                {"type": "paragraph", "attrs": {"id": None},
                 "content": [{"type": "text",
                               "marks": [{"type": "strong"}],
                               "text": label}]}
            ] + children}

def _heading(level, text):
    return {"type": "heading", "attrs": {"id": None, "level": level},
            "content": [{"type": "text", "text": text}]}

def _hr():
    return {"type": "horizontal_rule"}

def build_summary_nodes(s):
    return [
        _heading(2, "快速摘要"),
        _toggle("AI 摘要", [_para(s["ai_summary"])]),
        _toggle("問題",    [_bullet(p) for p in s.get("problems", [])]),
        _toggle("方法",    [_bullet(m) for m in s.get("methods", [])]),
        _toggle("結果",    [_bullet(r) for r in s.get("results", [])]),
        _toggle("要點",    [_bullet(t) for t in s.get("takeaways", [])]),
        _hr(),
    ]

# ── Heptabase CLI wrappers ────────────────────────────────────────────────────
def _hb(*args, check=True):
    result = subprocess.run(["heptabase"] + list(args), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"heptabase {args[0]} error: {result.stderr[:200]}")
    return json.loads(result.stdout) if result.stdout.strip() else {}

def check_duplicate(arxiv_id):
    # Free-text search by the bare ID, then confirm a candidate is genuinely
    # THIS paper's card — its content must contain the ID inside a paper URL
    # (/overview/{id}, /abs/{id}, /html/{id}). A bare slug like "deepseek-v4"
    # otherwise matches unrelated cards that merely mention the model.
    bid = bare_id(arxiv_id)
    url_marker = re.compile(rf'/(?:overview|abs|html|zh/overview)/{re.escape(bid)}\b')
    # limit 25：free-text 搜尋的前幾名常被 journal（含同 id 連結的日誌）
    # 佔住，真正的舊卡排在後面——實際踩過 limit=5 漏掉同 id 舊卡的雷。
    if OBS:
        for c in OBS.search_cards(bid, limit=25):
            if url_marker.search(OBS.read_content_str(c["id"])):
                return True
        return False
    data = _hb("card", "list", "-q", bid, "--limit", "25", check=False)
    results = data.get("results", [])
    if not results:
        return False
    for r in results:
        try:
            card = _hb("note", "read", r["id"], check=False)
            if url_marker.search(card.get("content", "")):
                return True
        except Exception:
            continue
    return False

def _norm_title(t):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "",
                  re.sub(r"^\[alphaxiv\]\s*", "", (t or "").strip().lower()))


def title_duplicate(title):
    """Second duplicate gate, by NORMALIZED-title equality. Catches papers
    whose two clips carry different id notations (numeric arxiv id vs a named
    alphaxiv slug) — those are invisible to the id-based check_duplicate."""
    q = re.sub(r"^\[alphaXiv\]\s*", "", (title or "").strip())[:60]
    if not q:
        return False
    want = _norm_title(title)
    if OBS:
        return any(_norm_title(c.get("title")) == want
                   for c in OBS.search_cards(q, limit=25))
    data = _hb("card", "list", "-q", q, "--limit", "25", check=False)
    return any(_norm_title(r.get("title")) == want
               for r in data.get("results", []))


def create_card(markdown):
    if OBS:
        return OBS.create_doc("papers", markdown)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(markdown)
        tmp = f.name
    try:
        data = _hb("note", "create", "--content-file", tmp)
        return data["id"]
    finally:
        os.unlink(tmp)

def read_card(card_id):
    if OBS:
        return OBS.read_doc(card_id)
    data = _hb("note", "read", card_id)
    return data["contentMd5"], json.loads(data["content"])

def save_card(card_id, md5, doc):
    if OBS:
        return OBS.save_doc(card_id, md5, doc)
    content_str = json.dumps(doc, ensure_ascii=False)
    # Use a temp file to avoid command-line length limits (e.g. with data URL images)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(content_str)
        tmp = f.name
    try:
        subprocess.run([
            "heptabase", "note", "save", card_id,
            "--content-md5", md5,
            "--content-file", tmp,
        ], check=True, capture_output=True)
    finally:
        os.unlink(tmp)

def insert_summary(card_id, summary):
    md5, doc = read_card(card_id)
    # Skip if already present
    for n in doc.get("content", []):
        if n.get("type") == "heading":
            for c in n.get("content", []):
                if "快速摘要" in c.get("text", ""):
                    return
    nodes = doc["content"]
    insert_at = next((i + 1 for i, n in enumerate(nodes) if n.get("type") == "heading"), 1)
    doc["content"] = nodes[:insert_at] + build_summary_nodes(summary) + nodes[insert_at:]
    save_card(card_id, md5, doc)

FIGURE_PLACE_PROMPT = """\
以下是一篇論文卡片的章節標題清單，以及可用的論文圖片（含英文 caption）。
請為最重要的 2-4 張圖各選一個最適合插入的章節標題。
只輸出 JSON array，不要其他文字。格式：
[{{"image": <圖片編號>, "after_heading": "<完全相符的章節標題>", "caption_zh": "<20字內繁體中文圖說>"}}]

規則：
- after_heading 必須與下列標題清單其中一個**完全相符**
- 架構/方法圖放方法章節；結果/比較圖放結果章節
- caption_zh 為繁體中文，20 字以內

章節標題清單：
{headings}

可用圖片：
{images}
"""

def _fig_node_text(node):
    if node.get("type") == "text":
        return node.get("text", "")
    return "".join(_fig_node_text(c) for c in node.get("content", []))

def _count_images(node):
    return (1 if node.get("type") == "image" else 0) + \
        sum(_count_images(c) for c in node.get("content", []))

def card_has_images(card_id):
    try:
        _, doc = read_card(card_id)
        return sum(_count_images(n) for n in doc["content"]) > 0
    except Exception:
        return True  # on error, don't trigger a needless retrofit

def figure_candidates(card_id, arxiv_id):
    """(headings, figs) for figure placement: the card's H2 headings and the
    budget-filtered figure candidates ({src, caption}). Lets an INTERACTIVE
    agent decide placements itself and call insert_figures_into_card(...,
    placements=...) — no nested claude-CLI call needed."""
    md5, doc = read_card(card_id)
    headings = [_fig_node_text(n) for n in doc["content"]
                if n.get("type") == "heading" and n.get("attrs", {}).get("level") == 2]
    if not headings:
        return headings, []
    # Budget for embedded (data-URL) figures: they count toward Heptabase's 100k
    # content limit, so what fits depends on the card's current size. http(s)-URL
    # figures cost ~nothing (only the short URL is stored).
    budget = 96000 - len(json.dumps(doc, ensure_ascii=False))

    html = fetch_arxiv_images(arxiv_id)[:6]
    url_figs = [f for f in html if not f["src"].startswith("data:")]
    svg_figs = [f for f in html if f["src"].startswith("data:")]

    if url_figs:
        figs = url_figs                       # hosted PNG/JPG — best, ~no size cost
    else:
        # No hosted images. Prefer compact PDF-rendered JPEGs over bulky inline-SVG
        # data URLs (an SVG→PNG is often ~2× the size and a key figure may not fit
        # the budget as SVG yet fits as a JPEG — e.g. a 58k SVG vs a 25k JPEG).
        figs = (fetch_pdf_figures(arxiv_id, max_figs=2, char_budget=budget)
                if budget >= 20000 else [])
        if not figs:
            # Last resort: inline-SVG data URLs that fit the budget.
            kept, used = [], 0
            for f in svg_figs:
                if used + len(f["src"]) > budget:
                    continue
                used += len(f["src"])
                kept.append(f)
            figs = kept
    return headings, figs


def insert_figures_into_card(card_id, arxiv_id, placements=None):
    """Fetch arxiv figures and insert the best 2-4 after the matching section
    headings. Returns the number of figures inserted (0 if none available).
    Reusable by the main pipeline (retrofit) and retry_no_image_cards().

    placements: optional pre-decided [{"image": 1-based idx, "after_heading":
    "<exact H2 text>", "caption_zh": "…"}] — used by interactive runs where the
    driving agent picks placements itself. When None (cron), placement is
    delegated to the claude CLI; a CLI failure degrades to 0 (no figures) so
    the rest of the pipeline survives — the card lands in the no-image retry
    record instead of crashing."""
    md5, doc = read_card(card_id)
    headings, figs = figure_candidates(card_id, arxiv_id)
    if not headings or not figs:
        return 0
    if placements is None:
        prompt = FIGURE_PLACE_PROMPT.format(
            headings="\n".join(f"- {h}" for h in headings),
            images="\n".join(f"{i+1}. {f['caption'][:140]}" for i, f in enumerate(figs)))
        try:
            out = call_claude(prompt, timeout=120)
        except Exception as e:
            log(f"  [FIG] placement via claude CLI failed ({str(e)[:120]}) — "
                "skipping figures (interactive runs: pass placements=...)")
            return 0
        m = re.search(r"\[.*\]", out or "", re.DOTALL)
        if not m:
            return 0
        try:
            placements = json.loads(m.group())
        except Exception:
            return 0
    by_heading = {}
    for p in placements:
        idx = p.get("image", 0) - 1
        h = p.get("after_heading", "")
        if 0 <= idx < len(figs) and h in headings:
            by_heading.setdefault(h, []).append((figs[idx]["src"], p.get("caption_zh", "")))
    if not by_heading:
        return 0
    new_content, inserted = [], 0
    for n in doc["content"]:
        new_content.append(n)
        if n.get("type") == "heading":
            for src, cap in by_heading.get(_fig_node_text(n), []):
                new_content.append({"type": "image",
                    "attrs": {"id": None, "src": src, "alignment": "center"}})
                if cap:
                    new_content.append({"type": "paragraph", "attrs": {"id": None},
                        "content": [{"type": "text", "marks": [{"type": "em"}], "text": cap}]})
                inserted += 1
    if inserted:
        doc["content"] = new_content
        save_card(card_id, md5, doc)
    return inserted

def retry_no_image_cards():
    """Each run: retry adding figures to recorded no-image cards. Removes a card
    from the record once figures are inserted or the card no longer exists."""
    records = load_no_image_record()
    if not records:
        return
    log(f"[RETRY-IMG] checking {len(records)} no-image cards...")
    still = []
    for r in records:
        cid, aid = r["card_id"], r.get("arxiv_id", "")
        if not pdf_url_for(aid):
            still.append(r); continue          # no resolvable PDF source for figures
        try:
            n = insert_figures_into_card(cid, aid)
        except Exception as e:
            log(f"  [{aid}] err: {e}"); n = 0
        if n > 0:
            log(f"  [{aid}] +{n} figures → resolved")
        else:
            r["last_checked"] = date.today().isoformat()
            still.append(r)
    save_no_image_record(still)
    log(f"[RETRY-IMG] {len(records) - len(still)} resolved, {len(still)} still pending")

def repair_card_images(card_id, arxiv_id):
    """Detect and fix deficient figures already in a card:
      - broken_url whose only fault is a missing arxiv_id segment → corrected
        in place (cheap; preserves placement + caption);
      - otherwise broken / blank / corrupt images → removed with their italic
        caption paragraph.
    If the card is left with zero images, re-fetch fresh figures via
    insert_figures_into_card (HTML → ar5iv → PDF). Returns a status string."""
    md5, doc = read_card(card_id)
    content = doc["content"]
    new, removed, fixed = [], 0, 0
    i, n = 0, len(content)
    while i < n:
        node = content[i]
        if node.get("type") != "image":
            new.append(node); i += 1; continue
        src = node["attrs"].get("src", "")
        status = image_health(src, arxiv_id)
        if status == "ok":
            new.append(node); i += 1; continue
        if status == "broken_url" and is_arxiv(arxiv_id):
            corrected = _corrected_html_url(src, arxiv_id)
            if corrected and _url_is_image(corrected):
                node["attrs"]["src"] = corrected
                new.append(node); fixed += 1; i += 1; continue
        # unhealthy → drop image and its trailing italic caption paragraph
        removed += 1
        i += 1
        if i < n and content[i].get("type") == "paragraph":
            inl = content[i].get("content", [])
            if inl and all(any(m.get("type") == "em" for m in c.get("marks", []))
                           for c in inl if c.get("type") == "text"):
                i += 1
    if removed or fixed:
        doc["content"] = new
        save_card(card_id, md5, doc)
    remaining = sum(1 for x in new if x.get("type") == "image")
    added = 0
    if remaining == 0 and pdf_url_for(arxiv_id):
        try:
            added = insert_figures_into_card(card_id, arxiv_id)
        except Exception as e:
            log(f"  [{arxiv_id}] re-fetch err: {e}")
    return f"fixed_url={fixed} removed={removed} refetched={added} images_now={remaining + added}"

def _iter_alphaxiv_cards():
    """Yield (card_id, arxiv_id, title) for every study/paper card whose
    Source Type is alphaXiv."""
    if OBS:
        for c in OBS.list_cards("papers"):
            if c["props"].get("source_type") == "alphaXiv":
                yield c["id"], c["props"].get("arxiv_id"), c["title"][:60]
        return
    _need(STUDY_PAPER_TAG_ID, "collections.papers.tag_id")
    _need(TASKS_PROP_ID, "props.tasks")
    _need(SOURCE_TYPE_PROP_ID, "props.source_type")
    _need(ARXIV_PROP_ID, "props.arxiv")
    r = subprocess.run(["heptabase", "tag", "cards", STUDY_PAPER_TAG_ID],
                       capture_output=True, text=True)
    for c in json.loads(r.stdout).get("cards", []):
        cid = c["id"]
        rp = subprocess.run(["heptabase", "card", "properties", cid],
                            capture_output=True, text=True)
        try:
            data = json.loads(rp.stdout)
        except Exception:
            continue
        aid = stype = None
        for tg in data.get("tags", []):
            for p in tg.get("properties", []):
                if p["id"] == ARXIV_PROP_ID and p.get("value"):
                    aid = p["value"]
                if p["id"] == SOURCE_TYPE_PROP_ID and p.get("value"):
                    stype = p["value"]
        if stype == "alphaXiv":
            yield cid, aid, c.get("title", "")[:60]

def audit_and_repair_all(dry_run=False):
    """Maintenance sweep: check every alphaXiv card's figures and repair the
    deficient ones (broken URL → fix/refetch, blank → drop+refetch, none →
    fetch). Slow (network per image); intended for manual/periodic runs, not
    every scheduled run. Logs a per-card line and a summary."""
    cards = list(_iter_alphaxiv_cards())
    log(f"[AUDIT] scanning {len(cards)} alphaXiv cards (dry_run={dry_run})...")
    touched = 0
    for cid, aid, title in cards:
        try:
            _, doc = read_card(cid)
        except Exception:
            continue
        imgs = [x["attrs"].get("src", "") for x in doc["content"] if x.get("type") == "image"]
        bad = [s for s in imgs if image_health(s, aid) != "ok"]
        if imgs and not bad:
            continue  # all images healthy
        if not imgs and not pdf_url_for(aid):
            continue  # no images and no figure source → nothing to do
        if dry_run:
            log(f"  [FLAG] {aid or '-':16} {title}  imgs={len(imgs)} bad={len(bad)}")
            touched += 1
            continue
        status = repair_card_images(cid, aid)
        log(f"  [FIX]  {aid or '-':16} {title}  {status}")
        touched += 1
    log(f"[AUDIT] {touched} cards needed attention")

def tag_card(card_id):
    if OBS:
        return  # collection membership == living in the papers folder
    _need(STUDY_PAPER_TAG_ID, "collections.papers.tag_id")
    subprocess.run(["heptabase", "tag", "add",
                    "--card-id", card_id, "--tag-name", "study/paper"],
                   capture_output=True)

def set_arxiv_property(card_id, arxiv_id):
    if OBS:
        return OBS.set_props(card_id, {"arxiv ID": arxiv_id})
    _need(ARXIV_PROP_ID, "props.arxiv")
    subprocess.run(["heptabase", "card", "set-property", card_id,
                    "--property-id", ARXIV_PROP_ID, "--value", arxiv_id],
                   capture_output=True)

def set_source_type(card_id):
    if OBS:
        return OBS.set_props(card_id, {"Source Type": "alphaXiv"})
    _need(SOURCE_TYPE_PROP_ID, "props.source_type")
    subprocess.run(["heptabase", "card", "set-property", card_id,
                    "--property-id", SOURCE_TYPE_PROP_ID, "--value", "alphaXiv"],
                   capture_output=True)

def valid_task_options():
    """Return the set of Tasks multiSelect option values that currently exist in
    the study/paper tag database. `set-property` REJECTS any value not in this
    set ("Unknown option") — the CLI cannot create new options, so auto-tagging
    must pick only from these (new option types are created manually in the UI).
    Obsidian mode: frontmatter has NO option registry (nothing rejects an
    unknown value), so validation is advisory only — returns None meaning
    "accept anything" (set_tasks/retag then skip the drop-filter). This also
    unblocks the fresh-vault chicken-and-egg (no snapshots, no cards -> the
    derived set would be empty and every first Task would be dropped)."""
    if OBS:
        return None
    _need(STUDY_PAPER_TAG_ID, "collections.papers.tag_id")
    _need(TASKS_PROP_ID, "props.tasks")
    r = subprocess.run(["heptabase", "tag", "properties", STUDY_PAPER_TAG_ID],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        return set()
    for p in data.get("properties", []):
        if p["id"] == TASKS_PROP_ID:
            return {o.get("value") or o.get("name") or o.get("label")
                    for o in p.get("options", [])}
    return set()

def current_tasks(card_id):
    """Return the list of Tasks values already on the card (for additive merge)."""
    if OBS:
        return list(OBS.read_card(card_id).props.get("tasks") or [])
    _need(TASKS_PROP_ID, "props.tasks")
    r = subprocess.run(["heptabase", "card", "properties", card_id],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        return []
    for tag in data.get("tags", []):
        for p in tag.get("properties", []):
            if p["id"] == TASKS_PROP_ID:
                return list(p.get("value") or [])
    return []

def valid_topic_options():
    """Topics multiSelect 的現有選項（config props.topics）。語意同
    valid_task_options：obsidian 模式回 None（frontmatter 無選項註冊表、
    照單全收）；heptabase 模式回集合，set-property 拒絕集合外的值。"""
    if OBS:
        return None
    _need(STUDY_PAPER_TAG_ID, "collections.papers.tag_id")
    _need(TOPICS_PROP_ID, "props.topics")
    r = subprocess.run(["heptabase", "tag", "properties", STUDY_PAPER_TAG_ID],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        return set()
    for p in data.get("properties", []):
        if p["id"] == TOPICS_PROP_ID:
            return {o.get("value") or o.get("name") or o.get("label")
                    for o in p.get("options", [])}
    return set()


def current_topics(card_id):
    if OBS:
        return list(OBS.read_card(card_id).props.get("topics") or [])
    _need(TOPICS_PROP_ID, "props.topics")
    r = subprocess.run(["heptabase", "card", "properties", card_id],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        return []
    for tag in data.get("tags", []):
        for p in tag.get("properties", []):
            if p["id"] == TOPICS_PROP_ID:
                return list(p.get("value") or [])
    return []


def set_topics(card_id, values):
    """ADDITIVELY annotate a card's Topics（非語音的主軸分類——LLM/FM、
    Agentic、Diffusion 等）。與 set_tasks 同語義：union、不移除、集合外的
    值丟棄並記錄。Tasks 管「路由到哪張總覽卡」，Topics 管「這張卡屬於什麼
    主題」——off-topic 卡 Tasks 留空但 Topics 應該有家。"""
    valid = valid_topic_options()
    existing = current_topics(card_id)
    requested = [v for v in values if v]
    dropped = [] if valid is None else [v for v in requested if v not in valid]
    if dropped:
        log(f"  [TOPICS] skipped unknown options (create in UI first): {dropped}")
    keep_new = [v for v in requested if v not in dropped]
    merged = list(dict.fromkeys(existing + keep_new))
    if merged == existing:
        log(f"  [TOPICS] no change ({existing})")
        return merged
    if OBS:
        OBS.set_props(card_id, {"Topics": merged})
    else:
        subprocess.run(["heptabase", "card", "set-property", card_id,
                        "--property-id", TOPICS_PROP_ID,
                        "--json-value", json.dumps(merged, ensure_ascii=False)],
                       capture_output=True)
    log(f"  [TOPICS] {existing} + {keep_new} -> {merged}")
    return merged


def set_tasks(card_id, values):
    """ADDITIVELY annotate a card's Tasks. Unions `values` with whatever is
    already there (never removes existing tags), drops any value that is not a
    valid existing option (logs them), and writes the merged list. Returns the
    final list actually applied. Use the returned list to decide overview sync."""
    valid = valid_task_options()
    existing = current_tasks(card_id)
    requested = [v for v in values if v]
    dropped = [] if valid is None else [v for v in requested if v not in valid]
    if dropped:
        log(f"  [TASKS] skipped unknown options (create in UI first): {dropped}")
    keep_new = [v for v in requested if v not in dropped]
    merged = list(dict.fromkeys(existing + keep_new))  # preserve order, dedup
    if merged == existing:
        log(f"  [TASKS] no change ({existing})")
        return merged
    if OBS:
        OBS.set_props(card_id, {"Tasks": merged})
    else:
        subprocess.run(["heptabase", "card", "set-property", card_id,
                        "--property-id", TASKS_PROP_ID,
                        "--json-value", json.dumps(merged, ensure_ascii=False)],
                       capture_output=True)
    log(f"  [TASKS] {existing} + {keep_new} -> {merged}")
    return merged

def retag_tasks(card_id, remove=(), add=()):
    """SURGICAL Tasks correction for the re-audit mode: remove mis-tagged
    values and/or add missing ones in one write. Unlike set_tasks (additive-
    only, the backfill/clip path), this CAN remove — so it must only run on
    human-approved proposals (see SKILL.md Re-audit mode). A value that is
    semantically correct but merely inconvenient for a topic's status output
    is NOT a removal target (that's the [elsewhere] marker's / topic-doc
    分工約定's domain). Returns (before, after)."""
    valid = valid_task_options()
    before = current_tasks(card_id)
    bad_add = [] if valid is None else [v for v in add if v and v not in valid]
    if bad_add:
        log(f"  [RETAG] skipped unknown add options (create in UI first): {bad_add}")
    after = [v for v in before if v not in set(remove)]
    after += [v for v in add if v and v not in set(bad_add) and v not in after]
    if after == before:
        log(f"  [RETAG] no change ({before})")
        return before, after
    if OBS:
        OBS.set_props(card_id, {"Tasks": after})
    else:
        subprocess.run(["heptabase", "card", "set-property", card_id,
                        "--property-id", TASKS_PROP_ID,
                        "--json-value", json.dumps(after, ensure_ascii=False)],
                       capture_output=True)
    log(f"  [RETAG] {before} -> {after} (removed {sorted(set(before)-set(after))}, "
        f"added {sorted(set(after)-set(before))})")
    return before, after

def overviews_to_sync(task_values):
    """Given the Tasks applied to a card, return the unified `overview` skill's
    topic key(s) that must be re-synced. Empty if none of the values is owned."""
    return sorted({OVERVIEW_TASKS[t] for t in task_values if t in OVERVIEW_TASKS})

def overview_card_ids():
    """Return the set of card ids tagged study/overview (comparison-overview +
    index cards). This tag is the authoritative overview discriminator; a read
    failure returns an empty set (callers then simply don't exclude anything)."""
    if OBS:
        try:
            return {c["id"] for c in OBS.list_cards("overviews")}
        except Exception:
            return set()
    _need(OVERVIEW_TAG_ID, "collections.overviews.tag_id")
    r = subprocess.run(["heptabase", "tag", "cards", OVERVIEW_TAG_ID],
                       capture_output=True, text=True)
    try:
        return {c.get("id") for c in json.loads(r.stdout).get("cards", [])}
    except Exception:
        return set()

def untagged_task_cards(source_type="alphaXiv"):
    """List study/paper cards whose `Tasks` is still empty — the backfill targets
    for a no-URL `/scholar-inbox-clip` maintenance pass. These are cards created
    by an automated pipeline run that skipped the semantic-tagging step (the
    retired launchd cron never tagged; a desktop-app routine normally tags via
    Step 6.5a — so this is now a safety net, not a daily queue).

    Pass source_type="alphaXiv" (default) to limit to pipeline-made cards; pass
    None to include every untagged study/paper card (also legacy hand-made notes).
    Cards tagged study/overview are always excluded (overview cards normally no
    longer carry study/paper at all — the tag check is a guard in case one gets
    re-tagged). Returns a list of {card_id, title, arxiv_id, source_type,
    last_edited} newest-first so Claude can read each card and annotate it via
    set_tasks()."""
    if OBS:
        out = [{"card_id": c["id"], "title": c["title"],
                "arxiv_id": c["props"].get("arxiv_id"),
                "source_type": c["props"].get("source_type"),
                "last_edited": c["modified"]}
               for c in OBS.list_cards("papers")
               if not (c["props"].get("tasks") or [])
               and (source_type is None or c["props"].get("source_type") == source_type)]
        out.sort(key=lambda x: x["last_edited"] or "", reverse=True)
        return out
    _need(STUDY_PAPER_TAG_ID, "collections.papers.tag_id")
    _need(TASKS_PROP_ID, "props.tasks")
    _need(SOURCE_TYPE_PROP_ID, "props.source_type")
    _need(ARXIV_PROP_ID, "props.arxiv")
    r = subprocess.run(["heptabase", "tag", "cards", STUDY_PAPER_TAG_ID,
                        "--include-properties"], capture_output=True, text=True)
    try:
        cards = json.loads(r.stdout).get("cards", [])
    except Exception:
        return []
    overview_ids = overview_card_ids()
    out = []
    for c in cards:
        tasks, src, aid = [], None, None
        for p in c.get("properties", []):
            if p["id"] == TASKS_PROP_ID:       tasks = p.get("value") or []
            elif p["id"] == SOURCE_TYPE_PROP_ID: src = p.get("value")
            elif p["id"] == ARXIV_PROP_ID:     aid = p.get("value")
        if tasks or c.get("id") in overview_ids:
            continue
        if source_type is not None and src != source_type:
            continue
        out.append({"card_id": c.get("id"), "title": c.get("title", ""),
                    "arxiv_id": aid, "source_type": src,
                    "last_edited": c.get("lastEditedTime") or c.get("createdTime")})
    out.sort(key=lambda x: x["last_edited"] or "", reverse=True)
    return out

def tagged_task_cards(source_type="alphaXiv"):
    """List study/paper cards whose `Tasks` is ALREADY set — the Re-audit mode
    targets (semantic review of existing values: mis-tags to remove, drifted
    values to re-judge). Mirror of untagged_task_cards; same source_type and
    study/overview-exclusion semantics. Returns {card_id, title, arxiv_id,
    tasks, source_type, last_edited} newest-first."""
    if OBS:
        out = [{"card_id": c["id"], "title": c["title"],
                "arxiv_id": c["props"].get("arxiv_id"),
                "tasks": list(c["props"].get("tasks") or []),
                "source_type": c["props"].get("source_type"),
                "last_edited": c["modified"]}
               for c in OBS.list_cards("papers")
               if (c["props"].get("tasks") or [])
               and (source_type is None or c["props"].get("source_type") == source_type)]
        out.sort(key=lambda x: x["last_edited"] or "", reverse=True)
        return out
    _need(STUDY_PAPER_TAG_ID, "collections.papers.tag_id")
    _need(TASKS_PROP_ID, "props.tasks")
    _need(SOURCE_TYPE_PROP_ID, "props.source_type")
    _need(ARXIV_PROP_ID, "props.arxiv")
    r = subprocess.run(["heptabase", "tag", "cards", STUDY_PAPER_TAG_ID,
                        "--include-properties"], capture_output=True, text=True)
    try:
        cards = json.loads(r.stdout).get("cards", [])
    except Exception:
        return []
    overview_ids = overview_card_ids()
    out = []
    for c in cards:
        tasks, src, aid = [], None, None
        for p in c.get("properties", []):
            if p["id"] == TASKS_PROP_ID:       tasks = p.get("value") or []
            elif p["id"] == SOURCE_TYPE_PROP_ID: src = p.get("value")
            elif p["id"] == ARXIV_PROP_ID:     aid = p.get("value")
        if not tasks or c.get("id") in overview_ids:
            continue
        if source_type is not None and src != source_type:
            continue
        out.append({"card_id": c.get("id"), "title": c.get("title", ""),
                    "arxiv_id": aid, "tasks": tasks, "source_type": src,
                    "last_edited": c.get("lastEditedTime") or c.get("createdTime")})
    out.sort(key=lambda x: x["last_edited"] or "", reverse=True)
    return out

def check_tasks():
    """One-shot self-audit of the Tasks vocabulary. Cross-checks the routing map
    (OVERVIEW_TASKS) and per-card usage against the property's LIVE options, so a
    Tasks-option rename applied in Heptabase but left stale in code (or a typo'd /
    orphan value on cards) surfaces immediately. Exit 0 = consistent; 1 = mismatch."""
    declared = valid_task_options()
    if declared is None:  # obsidian: no option registry — usage vs routing only
        declared = set(OVERVIEW_TASKS)
        for c in OBS.list_cards("papers"):
            declared.update(c["props"].get("tasks") or [])
    if not declared:
        log("[check-tasks] ERROR: could not read Tasks options from the property")
        return 2

    # Routing derivation check (hub∪ = 路由表): the graph-derived topic snapshots
    # (written by _shared/topology.py refresh) are the source of truth for which
    # Tasks values each overview skill owns. OVERVIEW_TASKS stays a physical
    # constant (automated runs must never do a runtime graph read) but must MATCH them.
    import glob
    snap_routing = {}
    try:  # snapshots live in the user topics dir (fallback: in-repo topics)
        topics_root = _hbconfig.topics_dir()
    except Exception:
        topics_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "overview", "topics")
    for p in glob.glob(os.path.join(topics_root, "*", "topic_snapshot.json")):
        try:
            snap = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            log(f"[check-tasks] ERROR: unreadable snapshot {p}: {e}")
            return 2
        for v in snap.get("task_values", []):
            snap_routing[v] = snap.get("skill") or os.path.basename(os.path.dirname(p))
    if snap_routing and snap_routing != OVERVIEW_TASKS:
        log("[check-tasks] FAIL: OVERVIEW_TASKS out of sync with topic snapshots:")
        for v in sorted(set(snap_routing) | set(OVERVIEW_TASKS)):
            a, b = OVERVIEW_TASKS.get(v), snap_routing.get(v)
            if a != b:
                log(f"    {v!r}: constant={a!r} vs snapshots={b!r}")
        log("  → update OVERVIEW_TASKS (or re-run _shared/topology.py refresh)")
        return 1
    routing = set(OVERVIEW_TASKS)

    # Usage counts over study/paper cards (the Tasks-bearing corpus). A scan
    # failure must NOT pass silently: this command is a rename gate, and an empty
    # `used` would false-negative "consistent". So fail hard on scan errors.
    used = {}
    if OBS:
        for c in OBS.list_cards("papers"):
            for v in (c["props"].get("tasks") or []):
                used[v] = used.get(v, 0) + 1
    else:
        r = subprocess.run(["heptabase", "tag", "cards", STUDY_PAPER_TAG_ID,
                            "--include-properties"], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[check-tasks] ERROR: card scan failed (rc={r.returncode}): {r.stderr.strip()[:200]}")
            return 2
        try:
            cards = json.loads(r.stdout).get("cards", [])
        except Exception as e:
            log(f"[check-tasks] ERROR: card scan output was not JSON: {e}")
            return 2
        for c in cards:
            for p in c.get("properties", []):
                if p["id"] == TASKS_PROP_ID:
                    for v in (p.get("value") or []):
                        used[v] = used.get(v, 0) + 1
    used_values = set(used)

    stale_routing   = sorted(routing - declared)                 # ❌ code names a gone option
    undeclared_used = sorted(used_values - declared)             # ❌ card value not an option
    unused_options  = sorted((declared - used_values) - routing) # ⚠️ option, 0 study/paper cards
    owned_no_cards  = sorted((routing & declared) - used_values) # ⚠️ overview owns an empty value

    log(f"[check-tasks] {len(declared)} declared options; {len(used_values)} in use "
        f"(study/paper); {len(routing)} overview-owned\n")
    log("Tasks options (usage on study/paper cards):")
    for v in sorted(declared, key=lambda x: (-used.get(x, 0), x)):
        log(f"  {used.get(v, 0):4d}  {v}{'  [overview]' if v in routing else ''}")
    for v in undeclared_used:
        log(f"  {used[v]:4d}  {v}  <- NOT a declared option")

    ok = True
    if stale_routing:
        ok = False
        log("\n[FAIL] OVERVIEW_TASKS references values the property no longer defines")
        log("       (rename applied in Heptabase but left stale in code):")
        for v in stale_routing:
            log(f"         - {v!r}")
    if undeclared_used:
        ok = False
        log("\n[FAIL] cards carry Tasks values not in the option list (typo / partial rename):")
        for v in undeclared_used:
            log(f"         - {v!r} ({used[v]} cards)")
    if unused_options:
        log("\n[warn] declared options with 0 study/paper cards (leftover old option, or new/empty):")
        for v in unused_options:
            log(f"         - {v!r}")
    if owned_no_cards:
        log("\n[warn] overview-owned values with 0 study/paper cards (overview may be empty):")
        for v in owned_no_cards:
            log(f"         - {v!r}")

    log("\n[OK] Tasks vocabulary consistent: routing ⊆ options, every card value is declared."
        if ok else "\n[FAIL] Tasks vocabulary has mismatches (see above).")
    return 0 if ok else 1

def append_arxiv_html_link(card_id, arxiv_id):
    """Append a clickable arxiv HTML link paragraph at the bottom of the card.
    Only arxiv papers have an arxiv.org/html page; skip all other sources."""
    if not is_arxiv(arxiv_id):
        return
    url = f"https://arxiv.org/html/{arxiv_id}"
    md5, doc = read_card(card_id)
    # Skip if already present
    for node in doc["content"][-5:]:
        for inline in node.get("content", []):
            for mark in inline.get("marks", []):
                if mark.get("type") == "link" and url in mark.get("attrs", {}).get("href", ""):
                    return
    doc["content"].append({
        "type": "paragraph",
        "attrs": {"id": None},
        "content": [
            {"type": "text", "text": "原文 HTML："},
            {
                "type": "text",
                "marks": [{"type": "link", "attrs": {
                    "href": url,
                    "title": None,
                    "data-internal-href": None,
                    "edited": False,
                }}],
                "text": url,
            },
        ],
    })
    save_card(card_id, md5, doc)

def update_journal(entries, subject="", recv_date=""):
    """Append a heading + one toggle per card to today's journal.
    The heading shows the email's received date (recv_date), not the
    processing date — this distinguishes same-subject emails (e.g. repeated
    "Trending Papers + Weekly Seminar") sent on different dates."""
    today = date.today().isoformat()
    try:
        if OBS:
            md5, doc = OBS.journal_read_doc(today)
        else:
            raw = subprocess.run(["heptabase", "journal", "read", today],
                                 capture_output=True, text=True)
            data = json.loads(raw.stdout)
            md5 = data["contentMd5"]
            doc = json.loads(data["content"])
    except Exception as e:
        log(f"  [ERR] Could not read journal: {e}")
        return

    # Section heading with email subject + the email's RECEIVED date
    date_label = recv_date or today
    src_label = ("HF Daily Papers"
                 if re.match(r"(?i)^daily papers of\b", (subject or "").strip())
                 else "Scholar Inbox")
    heading_text = f"{src_label} — {subject}（{date_label}）" if subject else f"{src_label}（{date_label}）"
    doc["content"].append({
        "type": "heading",
        "attrs": {"id": None, "level": 2},
        "content": [{"type": "text", "text": heading_text}],
    })

    for card_id, ai_summary in entries:
        doc["content"].append({
            "type": "toggle_list_item",
            "attrs": {"id": None, "folded": True},
            "content": [
                {"type": "paragraph", "attrs": {"id": None},
                 "content": [{"type": "card", "attrs": {"cardId": card_id}}]},
                {"type": "paragraph", "attrs": {"id": None},
                 "content": [{"type": "text", "text": ai_summary}]},
            ],
        })

    if OBS:
        OBS.journal_save_doc(today, md5, doc)
        return
    content_str = json.dumps(doc, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(content_str)
        tmp = f.name
    try:
        subprocess.run([
            "heptabase", "journal", "save", today,
            "--content-md5", md5,
            "--content-file", tmp,
        ], check=True, capture_output=True)
    finally:
        os.unlink(tmp)

# ── Main ──────────────────────────────────────────────────────────────────────
def process_one_email(index, processed_keys):
    """Read and process email at `index`.
    Returns (dedup_key, recv_date, journal_entries) or (None, None, None) when done.
    The dedup key is "subject|recv_date" so same-subject emails on different
    dates are treated as distinct."""
    try:
        subject, recv_date, body = read_scholar_inbox(index)
        if subject is None:
            log(f"[{index}] No more emails.")
            return None, None, None, None
        _, source = read_scholar_inbox_source(index)
        log(f"[{index}] Subject: {subject}  ({recv_date})")
    except Exception as e:
        log(f"[ERR] read email #{index}: {e}")
        return None, None, None, None

    dedup_key = f"{subject}|{recv_date}"
    if dedup_key in processed_keys:
        log(f"[{index}] Already processed, skipping.")
        return dedup_key, subject, recv_date, None  # None entries = skip, but don't stop

    if is_hf_daily(subject, source):
        papers = extract_hf_papers(body, source)
        log(f"[{index}] HF Daily Papers：{len(papers)} 篇上榜")
        arxiv_ids = [p["id"] for p in select_hf_papers(papers)]
    else:
        arxiv_ids = extract_arxiv_ids(body, source)
    log(f"[{index}] Papers found: {arxiv_ids or '(none)'}")
    if not arxiv_ids:
        return dedup_key, subject, recv_date, []

    journal_entries = []

    for arxiv_id in arxiv_ids:
        log(f"\n── {arxiv_id} ──")

        if check_duplicate(arxiv_id):
            log("  [SKIP] card already exists")
            continue

        # Fetch
        log("  [FETCH] alphaXiv...")
        content, is_ai_report = fetch_alphaxiv(arxiv_id)
        log(f"  [FETCH] {'AI report' if is_ai_report else 'raw text'}, {len(content)} chars")

        # Fetch arxiv HTML images
        images = fetch_arxiv_images(arxiv_id)
        if images:
            log(f"  [IMAGES] {len(images)} figures found")
        else:
            log("  [IMAGES] none (SVG or unavailable)")

        # Translate
        log("  [AI] Translating...")
        translated = translate_content(content, arxiv_id, images=images or None)
        if not translated:
            log("  [ERR] Translation failed, skipping")
            continue

        # Title-level duplicate gate (id-notation mismatches slip past the
        # id-based check; the translated H1 is the first reliable title)
        _t = translated.splitlines()[0] if translated else ""
        if title_duplicate(_t):
            log(f"  [SKIP] duplicate by title: {_t[:60]}")
            continue

        # Create card
        log("  [CREATE] Creating card...")
        try:
            card_id = create_card(translated)
            log(f"  [CREATE] {card_id}")
        except Exception as e:
            log(f"  [ERR] {e}")
            continue

        # Quick summary
        log("  [AI] Generating summary...")
        summary = generate_summary(translated)
        if summary:
            insert_summary(card_id, summary)
            log("  [SUMMARY] OK")
        else:
            log("  [SUMMARY] Failed, skipping")

        # Colorize
        log("  [AI] Colorizing...")
        n_colors = apply_colors(card_id, translated)
        if n_colors:
            log(f"  [COLOR] {n_colors} spans marked")
        else:
            log("  [COLOR] No spans (skipped)")

        # Tag + properties
        tag_card(card_id)
        set_source_type(card_id)
        set_arxiv_property(card_id, arxiv_id)
        log("  [TAG] study/paper + Source Type: alphaXiv + arxiv ID")

        # Append arxiv HTML link
        append_arxiv_html_link(card_id, arxiv_id)
        log("  [LINK] arxiv HTML link appended")

        # Confirm figures actually LANDED in the card — don't trust the fetched
        # `images` list. translate_content embeds only http-URL figures (it omits
        # SVG/PDF data URLs from the placement prompt), and Claude sometimes drops
        # figures, so a non-empty `images` can still leave the card figure-less.
        # If empty, retrofit via insert_figures_into_card (HTML incl. SVG, budget-
        # checked → PDF); record for retry only if still none.
        if pdf_url_for(arxiv_id) and not card_has_images(card_id):
            n_fig = insert_figures_into_card(card_id, arxiv_id)
            if n_fig:
                log(f"  [FIG] retrofitted {n_fig} figures (translate embedded none)")
            else:
                title = translated.splitlines()[0].lstrip("# ").strip() if translated else arxiv_id
                record_no_image_card(card_id, arxiv_id, title)
                log("  [NO-IMG] recorded for figure retry on future runs")

        ai_summary = (summary or {}).get("ai_summary", "")
        journal_entries.append((card_id, ai_summary))

    return dedup_key, subject, recv_date, journal_entries


def main():
    log(f"[scholar-inbox-clip] {date.today()}")

    state = load_state()
    # Dedup keys are "subject|recv_date" (see process_one_email).
    processed_keys = set(state.get("processed_subjects", []))

    all_journal_entries = []
    total_cards = 0
    index = 1
    # Scan a fixed window of the newest emails rather than stopping at the first
    # run of already-processed ones. A paper-bearing email can have a subject
    # that looks nothing like a paper digest (e.g. "Introducing alphaXiv
    # Assistant 2.0 + Pro Plan" still embeds 5 paper links), and may sit BELOW
    # several already-processed emails — an early "N consecutive skips" stop
    # would never reach it. Per-email subject-dedup keeps skips cheap, so a
    # bounded full scan is safe. New emails always arrive at the top (index 1).
    MAX_SCAN = 40

    while index <= MAX_SCAN:
        dedup_key, subject, recv_date, entries = process_one_email(index, processed_keys)
        if dedup_key is None:
            # OUT_OF_RANGE or read error
            break

        if entries is None:
            # already processed — skip cheaply, keep scanning the window
            index += 1
            continue

        if entries:
            try:
                update_journal(entries, subject, recv_date)
                log(f"[JOURNAL] {len(entries)} cards added")
            except Exception as e:
                log(f"[ERR] journal: {e}")
            total_cards += len(entries)
            all_journal_entries.extend(entries)

        processed_keys.add(dedup_key)
        index += 1

    # Persist state — keep last 50 keys (preserve order: old entries first)
    existing = state.get("processed_subjects", [])
    new_keys = [k for k in processed_keys if k not in set(existing)]
    combined = existing + new_keys
    save_state({"processed_subjects": combined[-50:], "last_date": date.today().isoformat()})

    # Retry adding figures to previously image-less cards (e.g. papers whose
    # arxiv HTML version appeared after they were first clipped).
    try:
        retry_no_image_cards()
    except Exception as e:
        log(f"[RETRY-IMG] error: {e}")

    if index > 1:
        log(f"\n[DONE] {index - 1} email(s) checked, {total_cards} new cards created")
    else:
        log("[DONE] Nothing to process")



def _require_study_feature():
    try:
        if not _hbconfig.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except AttributeError:
        pass

if __name__ == "__main__":
    _require_study_feature()
    if "--audit-images" in sys.argv:
        audit_and_repair_all(dry_run=False)
    elif "--audit-images-dry" in sys.argv:
        audit_and_repair_all(dry_run=True)
    elif "--list-untagged" in sys.argv:
        # Backfill targets: study/paper cards with empty Tasks. Add "all" to
        # include legacy non-alphaXiv notes (default: pipeline-made alphaXiv only).
        st = None if "all" in sys.argv else "alphaXiv"
        rows = untagged_task_cards(source_type=st)
        log(f"untagged study/paper cards ({'all sources' if st is None else st}): {len(rows)}")
        for x in rows:
            log(f"  {x['card_id']}  {(x['arxiv_id'] or '-'):16} {(x['last_edited'] or '')[:10]}  {x['title'][:62]}")
    elif "--list-tagged" in sys.argv:
        # Re-audit targets: study/paper cards with NON-empty Tasks. Add "all"
        # to include legacy non-alphaXiv notes (default: alphaXiv only).
        st = None if "all" in sys.argv else "alphaXiv"
        rows = tagged_task_cards(source_type=st)
        log(f"tagged study/paper cards ({'all sources' if st is None else st}): {len(rows)}")
        for x in rows:
            log(f"  {x['card_id']}  {(x['arxiv_id'] or '-'):16} "
                f"{json.dumps(x['tasks'], ensure_ascii=False)}  {x['title'][:56]}")
    elif "check-tasks" in sys.argv:
        # One-shot self-audit of the Tasks vocabulary (routing ⟷ live options ⟷
        # card usage). Exit 1 on mismatch so it can gate a rename.
        sys.exit(check_tasks())
    else:
        main()
