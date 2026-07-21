#!/usr/bin/env python3
"""Helpers for project-card-merge (Mac-side consolidation of project cards).

Reuses card-rewrite's rewrite_lib for the mechanics (read_card / save_card /
card_dump / extract_images / finalize / builders h,p,pp,bul,bp,img,toggle,hr,
source,add) and adds: the Research-Projects index, a merge-readiness scan, and a
ProseMirror table builder (project cards sometimes carry an ablation table)."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "card-rewrite"))
import rewrite_lib as L          # noqa: E402  (read_card/save_card/card_dump/extract_images/finalize/builders)

# The "Research Projects" hub card — its card-links are the per-project cards.
RESEARCH_PROJECTS = None
try:
    import hbconfig as _hbc0
    RESEARCH_PROJECTS = _hbc0.hb_id("collections", "projects", "hub_card")
except Exception:
    pass


def _require_project_feature():
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("project"):
            raise SystemExit("project 方向已在 config features.project 停用")
    except ImportError:
        pass

# Markers that signal cluster-side append-only additions awaiting a Mac merge.
APPENDED_MARKERS = ("📥", "cluster 補充", "cluster 進度")
BRIEF_MARKER = "待補成 paper 級參考"
# research_gaps (overview-graph Op 5) appends 🔍 analysis sections at the card
# TAIL; a 🔍 H2 sitting after any plan/reference-family heading is unfolded and
# awaits a merge (folded position = after Findings, BEFORE these headings).
ANALYSIS_MARKER = "🔍"
PLAN_MARKERS = ("下一步", "計畫", "待補", "已知未解", "參考")


def _cardlink_ids(doc):
    ids = []
    def walk(n):
        if n.get("type") == "card":
            cid = n.get("attrs", {}).get("cardId")
            if cid:
                ids.append(cid)
        for c in n.get("content", []):
            if isinstance(c, dict):
                walk(c)
    for n in doc["content"]:
        walk(n)
    return ids


def list_project_cards():
    """Return [(card_id, title)] for every card linked from Research Projects."""
    _require_project_feature()
    if not RESEARCH_PROJECTS:
        raise SystemExit("config 缺少 heptabase.collections.projects.hub_card")
    _, doc = L.read_card(RESEARCH_PROJECTS)
    out = []
    for cid in dict.fromkeys(_cardlink_ids(doc)):     # dedup, keep order
        try:
            _, d = L.read_card(cid)
            title = next((L._txt(n) for n in d["content"]
                          if n.get("type") == "heading" and n["attrs"].get("level") == 1), "")
        except Exception:
            title = "(unreadable)"
        out.append((cid, title.strip()))
    return out


def _unfolded_analysis(headings):
    """🔍 H2 sections awaiting a fold. Folded position = BEFORE the first
    plan/reference-family heading; a 🔍 after it — or on a card with no
    plan-family heading at all (no folded slot exists) — is an unfolded tail
    append. The brief heading (待補成 paper 級參考) is NOT a plan-family
    boundary even though it contains 待補."""
    plan_idx = next((i for i, h in enumerate(headings)
                     if any(m in h for m in PLAN_MARKERS)
                     and BRIEF_MARKER not in h), None)
    return [h for i, h in enumerate(headings)
            if h.startswith(ANALYSIS_MARKER)
            and (plan_idx is None or i > plan_idx)]


def scan(cid):
    """Report whether a project card has cluster-appended blocks / a brief to
    merge, plus figure count and size — so the skill can decide & report.
    Chain-aware: markers are unioned across every card in the chain; a CLEAN
    chain is a consolidated state（merge-spill 的正常產物）and does NOT flag —
    what flags is markers, orphan children, or a chain_error."""
    _require_project_feature()
    md5, doc = L.read_card(cid)
    import json
    blob = json.dumps(doc, ensure_ascii=False)
    figs = len(L.extract_images(doc))
    try:
        chain_ids, chain_error = chain(cid), None
    except Exception as e:      # cycle/斷鏈（RuntimeError）或 entry 二次讀取失敗
        chain_ids, chain_error = [cid], str(e)
    headings = []
    for link_id in chain_ids:
        try:
            _, d = (md5, doc) if link_id == cid else L.read_card(link_id)
        except Exception as e:   # child readable a moment ago, gone now: flag, don't crash
            chain_error = chain_error or f"續卡 {link_id} 二次讀取失敗：{e}"
            continue
        headings += [L._txt(n).strip() for n in d["content"]
                     if n.get("type") == "heading" and n["attrs"].get("level") == 2]
    title = next((L._txt(n).strip() for n in doc["content"]
                  if n.get("type") == "heading" and n["attrs"].get("level") == 1), "")
    orphans, orphan_scan_error = [], None
    if title:
        try:
            orphans = find_orphans(cid, title, known_ids=chain_ids)
        except Exception as e:
            orphan_scan_error = str(e)
    # the permanent timeline must not lose links parked on ORPHAN children
    # either (a 📎 appended to an old tail during a merge survives as an
    # orphan via the md5 guard) — scan them alongside the chain, dedup by
    # log-card id
    pending_logs, done_logs, _seen_logs = [], [], set()
    for link_id in chain_ids + [o[0] for o in orphans]:
        try:
            _, d = (md5, doc) if link_id == cid else L.read_card(link_id)
        except Exception:                                    # noqa: BLE001
            continue
        p, dn = scan_loglinks(d["content"])
        for e in p:
            if e["log"] not in _seen_logs:
                _seen_logs.add(e["log"])
                pending_logs.append(e)
        for e in dn:
            if e["log"] not in _seen_logs:
                _seen_logs.add(e["log"])
                done_logs.append(e)
    appended = [h for h in headings if any(m in h for m in APPENDED_MARKERS)]
    has_brief = any(BRIEF_MARKER in h for h in headings)
    unfolded = _unfolded_analysis(headings)
    # A chain by itself is a legitimate consolidated state (merge-spill output);
    # it needs a merge only when it ALSO carries appended/brief/🔍 markers, has
    # orphans, or the walk errored.
    return {"card_id": cid, "size": len(blob), "figures": figs,
            "appended_sections": appended, "has_brief": has_brief,
            "unfolded_analysis": unfolded,
            "chain": chain_ids, "orphans": orphans, "chain_error": chain_error,
            "orphan_scan_error": orphan_scan_error,
            "pending_logs": pending_logs, "done_logs": done_logs,
            "needs_merge": (bool(appended) or has_brief or bool(unfolded)
                            or bool(pending_logs)
                            or bool(orphans) or bool(chain_error)
                            or bool(orphan_scan_error)),
            "headings": headings}


# ── ProseMirror table builder (rewrite_lib has no table; project cards may need one) ──
def cell(text, header=False):
    return {"type": "table_header" if header else "table_cell",
            "attrs": {"id": None, "colspan": 1, "rowspan": 1, "colwidth": None,
                      "backgroundColor": None, "textColor": None},
            "content": [{"type": "paragraph", "attrs": {"id": None},
                         "content": ([{"type": "text", "text": text}] if text else [])}]}

def row(vals, header=False):
    return {"type": "table_row", "attrs": {"id": None}, "content": [cell(v, header) for v in vals]}

def table(rows):
    """rows = [[header...], [r1...], ...]; first row rendered as table_header."""
    return {"type": "table", "attrs": {"id": None},
            "content": [row(rows[0], header=True)] + [row(r) for r in rows[1:]]}

def cardlink(card_id):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": [{"type": "card", "attrs": {"cardId": card_id}}]}


# ══ Continuation-chain support (CARD-OVERFLOW.md merge side) ═══════════════════
# Read side: collapse an entry→續1→…→tail chain back into one merge input.
# Write side: finalize_chain — the merged result may LEGITIMATELY exceed the
# card cap; instead of forcing lossy trimming, spill whole H2 sections into a
# fresh continuation chain (same sentinel contract as append_card.py).
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "project-card-log"))
import append_card as AC         # noqa: E402  (LINK_MARK/parse_continuation/config helpers)


# ── log timeline（log-as-card 契約, 0.38.0）─────────────────────────────────
# The chain doubles as a permanent LOG LINK RECORD: 📎 lines are log cards
# not yet distilled into the body; a merge distills them and REWRITES the
# line as 📗 under the "📜 log 時間線" H2 — the link itself is never lost.
_LOGLINK_TEXT_RE = None


def loglink_of(n):
    """Parse one timeline paragraph → {log, date, summary, done} or None.
    Recognizes BOTH shapes: a sealed real card node, and the bridge's
    plain-text `[[card:id]]` literal."""
    import re as _re
    if n.get("type") != "paragraph":
        return None
    txt = L._txt(n).strip()
    done = txt.startswith(AC.LOG_DONE_MARK)
    if not done and not txt.startswith(AC.LOG_MARK):
        return None
    cid = next(((c.get("attrs") or {}).get("cardId")
                for c in n.get("content") or [] if c.get("type") == "card"),
               None)
    body = txt[len(AC.LOG_MARK):].strip()
    # L._txt renders a REAL card node as the same [[card:id]] literal a
    # bridge write leaves as text — strip it from the body either way
    m = _re.search(r"\[\[card:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\]\]",
                   body)
    if not cid:
        if not m:
            return None
        cid = m.group(1)
    if m:
        body = body.replace(m.group(0), " ")
    m = _re.match(r"^(\d{4}-\d{2}-\d{2})", body)
    date = m.group(1) if m else ""
    summary = body[m.end():].strip("　 ") if m else body.strip("　 ")
    return {"log": cid, "date": date, "summary": summary, "done": done}


def scan_loglinks(content):
    """(pending, done) timeline entries across a card's top-level nodes."""
    pending, done = [], []
    for n in content or []:
        e = loglink_of(n)
        if e:
            (done if e.pop("done") else pending).append(e)
    return pending, done


def loglink_node(log_id, date, summary, done=True):
    """Rebuild one timeline line WITH a real card node (never a text
    literal)."""
    mark = AC.LOG_DONE_MARK if done else AC.LOG_MARK
    out = [{"type": "text", "text": f"{mark} {date}　"},
           {"type": "card", "attrs": {"cardId": log_id}}]
    if summary:
        out.append({"type": "text", "text": f"　{summary}"})
    return {"type": "paragraph", "attrs": {"id": None}, "content": out}


def timeline_section(entries):
    """The permanent record block: H2 + one 📗 line per DISTILLED log card,
    date-ascending. Feed it every entry ever seen (old 📗 + freshly
    distilled 📎) — the record only grows."""
    nodes = [L.h(2, AC.TIMELINE_HEADING)]
    for e in sorted(entries, key=lambda x: (x.get("date") or "", x["log"])):
        nodes.append(loglink_node(e["log"], e.get("date", ""),
                                  e.get("summary", ""), done=True))
    return nodes
import json as _json             # noqa: E402
import subprocess as _sp         # noqa: E402


def _continuation_from_doc(doc):
    """Child id this card continues into. PM-level and positional: the FIRST
    card node AFTER the sentinel text within the sentinel paragraph — the same
    selection semantics as append_card.parse_continuation (first uuid after
    the marker), so both parsers always follow the same child. Uses the LAST
    sentinel paragraph, mirroring parse_continuation's last-match rule."""
    last = None
    for n in doc.get("content", []):
        if n.get("type") != "paragraph":
            continue
        acc, seen_mark, found = "", False, None
        for c in n.get("content", []) or []:
            if c.get("type") == "text":
                acc += c.get("text") or ""   # marker may span split text nodes
                if not seen_mark and AC.LINK_MARK in acc:
                    seen_mark = True
            elif (seen_mark and found is None and c.get("type") == "card"
                  and (c.get("attrs") or {}).get("cardId")):
                found = c["attrs"]["cardId"]
        if found:
            last = found
    return last


def chain(entry_id):
    """[entry, 續1, …, tail] by following sentinel links. Raises RuntimeError
    on anomalies (cycle, unreadable child, > CHAIN_MAX) instead of silently
    returning a truncated chain a scan could mistake for consolidated."""
    ids, seen, cur = [], set(), entry_id
    while cur:
        if cur in seen:
            raise RuntimeError(f"續卡鏈出現循環：{cur} 已在鏈上")
        if len(ids) >= AC.CHAIN_MAX:
            raise RuntimeError(f"續卡鏈超過 CHAIN_MAX={AC.CHAIN_MAX}——資料異常")
        seen.add(cur)
        ids.append(cur)
        try:
            _, doc = L.read_card(cur)
        except Exception as e:
            if cur == entry_id:
                raise
            raise RuntimeError(f"續卡 {cur} 無法讀取（{e}）——鏈斷裂，人工檢查") from e
        cur = _continuation_from_doc(doc)
    return ids


def _is_backref_para(n, entry_id):
    """The auto-header back-ref line a child opens with（…母卡：[[card:entry]]…）."""
    if n.get("type") != "paragraph":
        return False
    txt = L._txt(n)
    if "母卡" not in txt:
        return False
    return any(c.get("type") == "card" and (c.get("attrs") or {}).get("cardId") == entry_id
               for c in n.get("content", []) or [])


def strip_continuation_nodes(content):
    """Remove every sentinel link paragraph (and the horizontal_rule directly
    before it, which continuation_block adds). Everything else is preserved."""
    out = []
    for n in content:
        if n.get("type") == "paragraph" and AC.LINK_MARK in L._txt(n):
            if out and out[-1].get("type") == "horizontal_rule":
                out.pop()
            continue
        out.append(n)
    return out


def child_payload(doc, entry_id):
    """A child's mergeable content: body minus the auto-header (leading H1
    title + EXACTLY ONE 母卡 back-ref paragraph) and minus continuation
    links. Only one back-ref is stripped — user content that also happens to
    mention the 母卡 stays."""
    content = list(doc.get("content", []))
    if content and content[0].get("type") == "heading" \
            and content[0]["attrs"].get("level") == 1:
        content = content[1:]

    def _blank(n):
        return n.get("type") == "paragraph" and not L._txt(n).strip()

    i = 0
    while i < len(content) and _blank(content[i]):
        i += 1
    if i < len(content) and _is_backref_para(content[i], entry_id):
        i += 1
        while i < len(content) and _blank(content[i]):
            i += 1
    return strip_continuation_nodes(content[i:])


def chain_dumps(entry_id):
    """[(card_id, md5, full recursive text)] for the WHOLE chain — the merge
    reading step. Entry first, children in chain order. ONE read per card:
    md5, dump AND the next-link all derive from the SAME read, so the lock
    baseline can never be a different version than what was dumped. KEEP the
    md5s: they are the optimistic-lock baseline for finalize_chain (entry) AND
    cleanup_children (children) — an append landing anywhere on the chain
    after this read must abort the corresponding write/trash."""
    out, seen, cur = [], set(), entry_id
    while cur:
        if cur in seen:
            raise RuntimeError(f"續卡鏈出現循環：{cur} 已在鏈上")
        if len(out) >= AC.CHAIN_MAX:
            raise RuntimeError(f"續卡鏈超過 CHAIN_MAX={AC.CHAIN_MAX}——資料異常")
        seen.add(cur)
        try:
            md5, doc = L.read_card(cur)
        except Exception as e:
            if cur == entry_id:
                raise
            raise RuntimeError(f"續卡 {cur} 無法讀取（{e}）——鏈斷裂，人工檢查") from e
        out.append((cur, md5, L.doc_dump(doc)))
        cur = _continuation_from_doc(doc)
    return out


def _paged_card_list(query, max_pages=5):
    """card list -q 只回一頁（預設 20 筆）——分頁掃完，I/O 失敗必 raise
    （靜默回 [] 會把「找不到孤兒」與「查詢失敗」混為一談，scan 誤報 clean）。"""
    hits, offset = [], 0
    for _ in range(max_pages):
        r = _sp.run(["heptabase", "card", "list", "-q", query,
                     "--card-types", "note", "--limit", "100",
                     "--offset", str(offset)],
                    capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"card list 失敗：{(r.stderr or r.stdout)[:160]}")
        page = _json.loads(r.stdout).get("results", [])
        hits += page
        if len(page) < 100:
            return hits
        offset += 100
    raise RuntimeError(f"card list {query!r} 超過 {max_pages * 100} 筆——"
                       "查詢過寬，先人工確認")


def find_orphans(entry_id, entry_title, known_ids=()):
    """Children created but never linked (cluster crashed between create and
    tail-link). 兩路索引取聯集，避免單點盲區：
    (a) 標題查詢 '{entry_title} · 續 N'——entry 中途改名時會漏（舊名 child
        查不到），所以再加
    (b) tag 索引（_create_child 現在 tag 失敗即中止，所以成功建出的 child
        必有 tag）——不綁標題。
    兩路都以「back-ref 指向本 entry」驗證。I/O 失敗一律 raise（呼叫端記
    orphan_scan_error），絕不靜默回 []。"""
    hits = _paged_card_list(f"{entry_title} · 續")
    tag = AC.tag_name(AC.load_cfg())
    r = _sp.run(["heptabase", "tag", "list"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tag list 失敗：{(r.stderr or r.stdout)[:160]}")
    tag_id = next((t.get("id") for t in _json.loads(r.stdout).get("tags", [])
                   if t.get("name") == tag), None)
    if tag_id:
        r = _sp.run(["heptabase", "tag", "cards", tag_id],
                    capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"tag cards 失敗：{(r.stderr or r.stdout)[:160]}")
        hits += _json.loads(r.stdout).get("cards", [])
    orphans, seen, read_failures = [], set(), []
    for h in hits:
        cid = h.get("id")
        title = h.get("title") or ""
        if not cid or cid in known_ids or cid == entry_id or cid in seen:
            continue
        seen.add(cid)
        if " · 續" not in title:
            continue
        try:
            _, doc = L.read_card(cid)
        except Exception as e:
            # 實測：card list -q 與 tag cards 都不回 trashed 卡——候選讀取
            # 失敗＝真 I/O 異常，吞掉會讓不完整掃描誤報 clean
            read_failures.append((cid, str(e)[:80]))
            continue
        if any(_is_backref_para(n, entry_id) for n in doc.get("content", [])):
            orphans.append((cid, title))
    if read_failures:
        raise RuntimeError(f"{len(read_failures)} 個孤兒候選讀取失敗（掃描不"
                           f"完整）：{read_failures[:3]}")
    return orphans


# ── write side: spill an over-cap merge result into a fresh chain ─────────────
def _cont_nodes(child_id):
    """PM equivalent of append_card.continuation_block（hr + sentinel line）."""
    return [
        {"type": "horizontal_rule", "attrs": {"id": None}},
        {"type": "paragraph", "attrs": {"id": None}, "content": [
            {"type": "text", "text": "▶ "},
            {"type": "text", "marks": [{"type": "strong"}], "text": AC.LINK_MARK},
            {"type": "text", "text": "："},
            {"type": "card", "attrs": {"cardId": child_id}},
        ]},
    ]


def _child_head_nodes(entry_id, entry_title, n):
    """Child auto-header（same semantics as append_card.child_header, PM form）."""
    return [
        {"type": "heading", "attrs": {"id": None, "level": 1},
         "content": [{"type": "text", "text": AC.child_title(entry_title, n)}]},
        {"type": "paragraph", "attrs": {"id": None}, "content": [
            {"type": "text", "text": f"（{entry_title or '母卡'} 的續卡 {n}／merge 溢位；母卡："},
            {"type": "card", "attrs": {"cardId": entry_id}},
            {"type": "text", "text": "。整併請用 project-card-merge。）"},
        ]},
    ]


def _node_size(n):
    return len(_json.dumps(n, ensure_ascii=False))


def split_h2(content, budget):
    """Pack top-level nodes into segments ≤ budget, breaking ONLY at H2
    headings so a section never splits mid-way. Conserves every node in
    order. A single section larger than the budget becomes its own segment
    (caller decides whether that is fatal)."""
    sections, cur = [], []
    for n in content:
        if n.get("type") == "heading" and n["attrs"].get("level") == 2 and cur:
            sections.append(cur)
            cur = []
        cur.append(n)
    if cur:
        sections.append(cur)
    segments, seg, seg_size = [], [], 0
    for sec in sections:
        sec_size = sum(_node_size(n) for n in sec)
        if seg and seg_size + sec_size > budget:
            segments.append(seg)
            seg, seg_size = [], 0
        seg.extend(sec)
        seg_size += sec_size
    if seg:
        segments.append(seg)
    return segments


def _entry_title_of(content):
    for n in content:
        if n.get("type") == "heading" and n["attrs"].get("level") == 1:
            return L._txt(n).strip()
    return ""


def _create_child(entry_id, entry_title, n, child_content, tag):
    """Create a continuation child. Crash-safety: the CREATE itself carries the
    auto-header markdown（title＋母卡 [[card:entry]] back-ref, reusing
    append_card.child_header）, so an interruption at ANY later point leaves a
    child that find_orphans() can already see. Then tag → save full content."""
    r = _sp.run(["heptabase", "note", "create", "--content",
                 AC.child_header(entry_title, entry_id, n)],
                capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"note create 失敗：{r.stderr[:200]}")
    cid = _json.loads(r.stdout).get("id")
    if not cid:
        raise RuntimeError(f"note create 未回傳 id：{r.stdout[:200]}")
    t = _sp.run(["heptabase", "tag", "add", "--card-id", cid, "--tag-name", tag],
                capture_output=True, text=True)
    if t.returncode != 0:
        # 「children created+tagged BEFORE entry saves」是硬契約——tag 也是
        # 孤兒回收的索引之一；tag 失敗就中止（entry 未存，已建的 child
        # 仍可經標題＋back-ref 被 find_orphans 找到，merge 重跑可收回）
        raise RuntimeError(f"續卡 {cid} tag 失敗（{t.stderr[:120]}）——中止 "
                           "merge（entry 未寫入；重跑前先確認 tag 服務正常）")
    # Replace content INSIDE the freshly-read doc — save needs the full
    # ProseMirror envelope (type:"doc", …), same pattern as the entry save.
    md5, doc = L.read_card(cid)
    doc["content"] = child_content
    L.save_card(cid, md5, doc)
    # Best-effort entry-pointer relation — same convention as the append-side
    # spill (tag-level scans tell continuations from entries); never blocks
    # the merge (properties live outside the content doc / md5 lock).
    AC.Transport("heptabase", AC.load_cfg()).set_project_relation(cid, entry_id)
    return cid


def _as_built(nodes):
    return len(_json.dumps({"content": nodes}, ensure_ascii=False))


def _count_attr_nodes(n):
    if isinstance(n, dict):
        return (1 if isinstance(n.get("attrs"), dict) else 0) +             sum(_count_attr_nodes(v) for v in n.values())
    if isinstance(n, list):
        return sum(_count_attr_nodes(v) for v in n)
    return 0


def _stored_guard(nodes):
    """cap 比較要用「存檔後」的估計：save 時 app 把每個 attrs.id None 換成
    36 字 UUID（"id": null → "id": "…"＝每節點約 +34B）。pre-save JSON 直接
    比 cap 會低估、單段 85-99K 的 H2 可能存檔後爆掉。"""
    return _as_built(nodes) + 40 * _count_attr_nodes(nodes)


_PLACEHOLDER_ID = "00000000-0000-0000-0000-000000000000"


def _set_cont_target(body, child_id):
    """Point the trailing placeholder sentinel at the real child id."""
    for n in reversed(body):
        if n.get("type") == "paragraph" and AC.LINK_MARK in L._txt(n):
            for c in n.get("content", []) or []:
                if c.get("type") == "card":
                    c["attrs"]["cardId"] = child_id
                    return
    raise RuntimeError("planned body 缺 sentinel（內部錯誤）")


def _save_entry(entry_id, flat, expected_md5):
    """Save with the CALLER's md5 (optimistic lock): if anything — say a new
    cluster append — landed on the entry after the merge read it, the save must
    fail loudly instead of silently overwriting that content."""
    full_md5, full_doc = L.read_card(entry_id)
    if expected_md5 and full_md5 != expected_md5:
        raise RuntimeError("entry 卡在 merge 期間被修改（md5 不符）——可能有新 "
                           "append 落地；重讀整條鏈再重跑 merge")
    full_doc["content"] = flat
    L.save_card(entry_id, expected_md5 or full_md5, full_doc)


def finalize_chain(entry_id, md5, content, color_rules, dry_run=False):
    """finalize for PROJECT cards: same colorize pipeline, but an over-threshold
    result spills whole H2 sections into a continuation chain instead of
    demanding lossy trimming（paper-grade 細節不因 100K 上限被濃縮）.

    Returns [(card_id, as_built_size), …] — one tuple when no spill was needed.
    - Figures are only downscaled when the SINGLE card they sit on is still too
      big（spill 本身能解決的尺寸問題不犧牲解析度）; obsidian has no cap → no
      shrink, no spill.
    - Every planned card (auto-header + sections + sentinel included) is
      size-guarded against the real cap BEFORE anything is written.
    - Crash-safe ordering: children are created WITH their 母卡 back-ref (and
      tagged) before the entry is saved — a failure at any point leaves only
      find_orphans()-discoverable children, never lost entry content.
    dry_run=True prints the split plan and writes nothing."""
    flat = []
    for n in content:
        flat.extend(n) if isinstance(n, list) else flat.append(n)
    flat = L.colorize(flat, color_rules)

    if L.OBS:                            # obsidian: no hard cap → plain save
        if not dry_run:
            _save_entry(entry_id, flat, md5)
        return [(entry_id, _as_built(flat))]

    cap, threshold = AC.cap_threshold(AC.load_cfg())
    size = _as_built(flat)
    if size <= threshold:                # single card, finalize-parity behavior
        if size > 88000:
            L._shrink_card_figures(flat)
            size = _as_built(flat)
        if _stored_guard(flat) > cap:
            raise ValueError(f"as-built {size}（含 UUID 膨脹餘裕 "
                             f"{_stored_guard(flat)}）超過 cap {cap}"
                             "（threshold 設定異常？）")
        if not dry_run:
            _save_entry(entry_id, flat, md5)
        return [(entry_id, size)]

    entry_title = _entry_title_of(flat)
    segments = split_h2(flat, threshold)
    if len(segments) == 1:
        raise ValueError(f"as-built {size} 超限但只有一個 H2 段——先檢查是否有巨型章節/圖")

    # Plan every card's REAL body (header/sentinel included, placeholder link)
    # and guard each against the cap before any write happens.
    planned = []
    for i, seg in enumerate(segments):
        body = list(seg) if i == 0 else _child_head_nodes(entry_id, entry_title, i) + list(seg)
        if i < len(segments) - 1:
            body = body + _cont_nodes(_PLACEHOLDER_ID)
        b = _as_built(body)
        if b > 88000:                    # only shrink figures on the card that needs it
            L._shrink_card_figures(body)
            b = _as_built(body)
        if _stored_guard(body) > cap:
            head = L._txt(seg[0]).strip() if seg else "?"
            raise ValueError(f"第 {i} 段（{head[:40]}）as-built {b}（含 UUID "
                             f"膨脹餘裕 {_stored_guard(body)}）超過 cap {cap}"
                             f"——單一 H2 章節過大，請先手動拆分該章節")
        planned.append((body, b))

    if len(planned) > AC.CHAIN_MAX:
        raise ValueError(f"spill 需要 {len(planned)} 張卡，超過 CHAIN_MAX={AC.CHAIN_MAX}"
                         f"——內容量異常，先確認輸入")
    plan_view = [(entry_id if i == 0 else f"(new 續 {i})", b)
                 for i, (_, b) in enumerate(planned)]
    if dry_run:
        print(f"[dry-run] as-built {size} > threshold {threshold} → {len(planned)} 段：{plan_view}")
        return plan_view

    cur_md5, _cur = L.read_card(entry_id)   # concurrency check BEFORE creating
    if md5 and cur_md5 != md5:              # children — a stale merge must not
        raise RuntimeError("entry 卡在 merge 期間被修改（md5 不符）——可能有新 "
                           "append 落地；重讀整條鏈再重跑 merge")   # even leave orphans
    tag = AC.tag_name(AC.load_cfg())
    child_ids = [None] * len(planned)           # index 1..N-1 used
    for i in range(len(planned) - 1, 0, -1):    # tail first, so links resolve
        body, _b = planned[i]
        if i + 1 < len(planned):
            _set_cont_target(body, child_ids[i + 1])
        child_ids[i] = _create_child(entry_id, entry_title, i, body, tag)
    entry_body, entry_size = planned[0]
    _set_cont_target(entry_body, child_ids[1])
    _save_entry(entry_id, entry_body, md5)
    return [(entry_id, entry_size)] + \
        [(child_ids[i], planned[i][1]) for i in range(1, len(planned))]


def cleanup_children(child_ids, tag=None, md5s=None):
    """After the chain content is absorbed into the freshly-saved entry: make
    sure each old child is tagged (crash-discoverability per CARD-OVERFLOW.md)
    then move it to trash（soft-delete；Heptabase 垃圾桶可還原）.
    md5s（chain_dumps 讀取時的 {card_id: md5}）: a child whose md5 changed since
    the merge read it — e.g. a cluster append landed on the TAIL mid-merge —
    is NOT trashed（其內容不在剛存的 entry 裡）; it stays as a discoverable
    orphan and the merge must be re-run."""
    tag = tag or AC.tag_name(AC.load_cfg())
    for cid in child_ids:
        if md5s is not None:
            if cid not in md5s:      # no baseline → fail closed, never blind-trash
                print(f"  ⚠ SKIP trash {cid}：MD5S 沒有它的讀取基準"
                      f"（Step 2 漏讀？）——先讀給基準再 cleanup")
                continue
            try:
                cur_md5, _d = L.read_card(cid)
            except Exception as e:
                print(f"  SKIP（無法重讀驗證 {cid}：{e}）——不 trash")
                continue
            if cur_md5 != md5s[cid]:
                print(f"  ⚠ SKIP trash {cid}：md5 變了（merge 期間有新內容落地）"
                      f"——保留為孤兒，重跑 merge 收回")
                continue
        _sp.run(["heptabase", "tag", "add", "--card-id", cid, "--tag-name", tag],
                capture_output=True, text=True)
        # 殘餘競態（CLI 無條件式 trash 可用）：md5 驗證與 trash 之間仍有
        # 毫秒級窗口，cluster append 若恰好落在其間會隨卡進垃圾桶——所以
        # tag 先行、驗證緊貼 trash 把窗口壓到最小，且 trash 是軟刪除
        # （垃圾桶可還原）。操作面防線：merge 只在 cluster 無進行中
        # append 時跑（SKILL 有明文）。
        if md5s is not None:
            try:
                cur_md5, _d = L.read_card(cid)
            except Exception as e:
                print(f"  SKIP（trash 前重驗失敗 {cid}：{e}）——不 trash")
                continue
            if cur_md5 != md5s[cid]:
                print(f"  ⚠ SKIP trash {cid}：md5 在 tag 後又變了"
                      "（append 進行中？）——保留為孤兒，重跑 merge 收回")
                continue
        r = _sp.run(["heptabase", "card", "trash", cid],
                    capture_output=True, text=True)
        print(f"  {'trashed' if r.returncode == 0 else 'TRASH FAILED'}: {cid}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        import json
        print(json.dumps(scan(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        for cid, title in list_project_cards():
            s = scan(cid)
            flag = "NEEDS MERGE" if s["needs_merge"] else "clean"
            print(f"{cid}  [{flag}]  size={s['size']} figs={s['figures']}  {title}")
            if len(s["chain"]) > 1:
                print(f"      ↳ 續卡鏈 ×{len(s['chain']) - 1}: {' → '.join(s['chain'][1:])}")
            if s.get("chain_error"):
                print(f"      ↳ ⚠ chain 異常：{s['chain_error']}")
            for oid, otitle in s.get("orphans", []):
                print(f"      ↳ ⚠ 孤兒續卡（未被鏈接）: {oid}  {otitle}")
            if s["appended_sections"]:
                for a in s["appended_sections"]:
                    print(f"      ↳ {a}")
            for a in s.get("unfolded_analysis", []):
                print(f"      ↳ 🔍 未折疊分析段：{a}")
