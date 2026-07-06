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
    merge, plus figure count and size — so the skill can decide & report."""
    _require_project_feature()
    md5, doc = L.read_card(cid)
    import json
    blob = json.dumps(doc, ensure_ascii=False)
    figs = len(L.extract_images(doc))
    headings = [L._txt(n).strip() for n in doc["content"]
                if n.get("type") == "heading" and n["attrs"].get("level") == 2]
    appended = [h for h in headings if any(m in h for m in APPENDED_MARKERS)]
    has_brief = any(BRIEF_MARKER in h for h in headings)
    unfolded = _unfolded_analysis(headings)
    return {"card_id": cid, "size": len(blob), "figures": figs,
            "appended_sections": appended, "has_brief": has_brief,
            "unfolded_analysis": unfolded,
            "needs_merge": bool(appended) or has_brief or bool(unfolded),
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


if __name__ == "__main__":
    if len(sys.argv) > 1:
        import json
        print(json.dumps(scan(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        for cid, title in list_project_cards():
            s = scan(cid)
            flag = "NEEDS MERGE" if s["needs_merge"] else "clean"
            print(f"{cid}  [{flag}]  size={s['size']} figs={s['figures']}  {title}")
            if s["appended_sections"]:
                for a in s["appended_sections"]:
                    print(f"      ↳ {a}")
            for a in s.get("unfolded_analysis", []):
                print(f"      ↳ 🔍 未折疊分析段：{a}")
