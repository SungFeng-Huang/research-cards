#!/usr/bin/env python3
"""Shared engine for the `*-overview` maintenance skills (a-lite consolidation).

One hardened implementation of the mechanical layer — Heptabase read/save,
ProseMirror builders, fail-fast corpus enumeration, arxiv-key ordering, the
multi-listing sorter (with synthesis prose-guard), and coverage `status` —
parameterised by an `OverviewTopic` config so each skill's `sync_overview.py`
shrinks to config + optional hooks + a thin CLI.

Base behavior = speech-generation-overview's sync_overview.py (2026-07-04, the
newest variant carrying all three bug-fix classes: enumerate fail-fast incl.
properties-error guard, synthesis prose-guard, sort restricted to own cards).
Every knob a topic differs in is config; the only true code hooks are
`classify_fn` (duplex method/benchmark) and `extra_sorts` (duplex's narrative
benchmark-card sorter). `status_fn` / `status_header_fn` exist so migrating
skills can keep their exact status output (golden-diff byte compatibility).

Usage from a thin sync_overview.py:

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "_shared"))
    from overview_engine import OverviewTopic, run_cli, ...
    TOPIC = OverviewTopic(own_cards=[...], task_values=[...], match=[...], cards={...})
    if __name__ == "__main__":
        run_cli(TOPIC, sys.argv[1:])
"""
import os, sys, json, subprocess, tempfile

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")

# ── Heptabase ids come from config (heptabase.scan_tags / heptabase.props.*);
# heptabase-mode paths exit with a clear message when unset. ─────────────────
try:
    import hbconfig as _hbc_ids
    _h = (_hbc_ids.load_config().get("heptabase") or {})
    _p = _h.get("props") or {}
except Exception:
    _h, _p = {}, {}
DEFAULT_SCAN_TAGS        = list(_h.get("scan_tags") or [])
DEFAULT_TASKS_PROP       = _p.get("tasks")
DEFAULT_SOURCE_TYPE_PROP = _p.get("source_type")
DEFAULT_ARXIV_PROP       = _p.get("arxiv")


class OverviewTopic:
    """Per-topic configuration. Only `own_cards`, `task_values`, `match` and
    `cards` are usually required; everything else has family-wide defaults."""

    def __init__(self, *, own_cards, task_values, match, cards,
                 extra_coverage=None, overview_cards=None, coverage_members=None,
                 subtree_cards=None,
                 scan_tags=None, tasks_prop=DEFAULT_TASKS_PROP,
                 source_type_prop=DEFAULT_SOURCE_TYPE_PROP,
                 arxiv_prop=DEFAULT_ARXIV_PROP,
                 dim_cols=None, dim_cols_by_card=None,
                 classification_headings=("架構典範分類",),
                 representative_col=1,
                 sections_between=("各論文核心貢獻與設計差異", "關鍵設計維度對比"),
                 dim_table_heading="關鍵設計維度對比",
                 synthesis_heading="主要研究方向歸納",
                 survey_keywords=("Survey", "綜述"),
                 match_fallback_key="9999.99999",
                 classify_fn=None, extra_sorts=None,
                 status_fn=None, status_header_fn=None,
                 missing_label="MISSING papers",
                 kind_width=7):
        self.own_cards = list(own_cards)
        self.extra_coverage = list(extra_coverage or [])
        # coverage union for `status`; defaults to own + extra
        self.overview_cards = list(overview_cards) if overview_cards else \
            self.own_cards + self.extra_coverage
        # Global-union coverage (phase 2): when set, `coverage_linked` unions
        # links across this CONTENT-DERIVED comparison-card set instead of the
        # hand-maintained own+extra list. Populated by `load_topic_snapshot`.
        self.coverage_members = list(coverage_members) if coverage_members else None
        # Own boundary for the `[elsewhere]` marker: own_cards + every nested
        # sub-topic's own_cards (graph-derived; populated by
        # `load_topic_snapshot` from the snapshots' sub_topics). None → own_cards.
        self.subtree_cards = list(subtree_cards) if subtree_cards else None
        self.task_values = list(task_values)
        self.match = list(match)
        self.cards = dict(cards)
        self.scan_tags = list(scan_tags or DEFAULT_SCAN_TAGS)
        self.tasks_prop = tasks_prop
        self.source_type_prop = source_type_prop
        self.arxiv_prop = arxiv_prop
        self.dim_cols_by_card = dict(dim_cols_by_card or {})
        self.dim_cols = list(dim_cols) if dim_cols else None
        self.classification_headings = list(classification_headings)
        self.representative_col = representative_col
        self.sections_between = tuple(sections_between)
        self.dim_table_heading = dim_table_heading
        self.synthesis_heading = synthesis_heading
        self.survey_keywords = tuple(survey_keywords)
        self.match_fallback_key = match_fallback_key
        self.classify_fn = classify_fn
        self.extra_sorts = list(extra_sorts or [])
        self.status_fn = status_fn
        self.status_header_fn = status_header_fn
        self.missing_label = missing_label
        self.kind_width = kind_width

    @property
    def default_card(self):
        return self.own_cards[0]

    def cols_for(self, card_id):
        if card_id in self.dim_cols_by_card:
            return self.dim_cols_by_card[card_id]
        if self.dim_cols:
            return self.dim_cols
        raise KeyError(f"no DIM_COLS configured for {card_id}")


# ── Card read/save (backend-routed) ─────────────────────────────────────────────
# backend == "obsidian" routes doc I/O to the vault (PM doc stays the shared
# in-memory model); otherwise the original heptabase CLI paths run untouched.
try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None


def read_card(card_id):
    if OBS:
        return OBS.read_doc(card_id)
    r = subprocess.run(["heptabase", "note", "read", card_id], capture_output=True, text=True)
    data = json.loads(r.stdout)
    return data["contentMd5"], json.loads(data["content"])


def save_card(card_id, md5, doc):
    if OBS:
        return OBS.save_doc(card_id, md5, doc)
    s = json.dumps(doc, ensure_ascii=False)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(s); tmp = f.name
    try:
        subprocess.run(["heptabase", "note", "save", card_id, "--content-md5", md5,
                        "--content-file", tmp], check=True, capture_output=True)
    finally:
        os.unlink(tmp)


def node_text(n):
    if n.get("type") == "text":
        return n.get("text", "")
    return "".join(node_text(c) for c in n.get("content", []) if isinstance(c, dict))


def linked_card_ids(doc):
    ids = []
    def walk(n):
        if n.get("type") == "card":
            ids.append(n.get("attrs", {}).get("cardId"))
        for c in (n.get("content") or []):
            if isinstance(c, dict): walk(c)
    for n in doc["content"]: walk(n)
    return set(i for i in ids if i)


# ── ProseMirror builders ─────────────────────────────────────────────────────────
def H(level, text):
    return {"type": "heading", "attrs": {"id": None, "level": level},
            "content": [{"type": "text", "text": text}]}
def para(text):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": ([{"type": "text", "text": text}] if text else [])}
def card_para(card_id):
    return {"type": "paragraph", "attrs": {"id": None},
            "content": [{"type": "card", "attrs": {"cardId": card_id}}]}
def bullet(label, rest):
    return {"type": "bullet_list_item", "attrs": {"id": None, "folded": False, "format": None},
            "content": [{"type": "paragraph", "attrs": {"id": None},
                "content": [{"type": "text", "marks": [{"type": "strong"}], "text": label},
                            {"type": "text", "text": "：" + rest}]}]}
def hr():
    return {"type": "horizontal_rule", "attrs": {"id": None}}
def section(heading_text, card_id, label_rest_pairs):
    return [H(3, heading_text), card_para(card_id)] + \
           [bullet(l, r) for l, r in label_rest_pairs if r and r.strip()] + [hr()]
def _cell(text, header=False):
    return {"type": "table_header" if header else "table_cell",
            "attrs": {"id": None, "colspan": 1, "rowspan": 1, "colwidth": None,
                      "backgroundColor": None, "textColor": None},
            "content": [para(text)]}
def _row(vals, header=False):
    return {"type": "table_row", "attrs": {"id": None}, "content": [_cell(v, header) for v in vals]}
def dim_row(topic, short_name, dim_dict, card_id=None):
    cols = topic.cols_for(card_id or topic.default_card)
    return _row([short_name] + [dim_dict.get(k, "—") or "—" for k in cols[1:]])
def table(rows):
    return {"type": "table", "attrs": {"id": None}, "content": rows}


# ── Ordering / classification ────────────────────────────────────────────────────
def arxiv_key(topic, text):
    for sub, k in topic.match:
        if sub in text:
            return k
    return topic.match_fallback_key


def classify(topic, title, source_type):
    if topic.classify_fn:
        return topic.classify_fn(title, source_type)
    if source_type == "Overview" or (source_type or "").lower() == "blog":
        return "meta"
    if any(k in title for k in topic.survey_keywords):
        return "meta"
    return "method"


# ── Corpus enumeration (fail-fast: scan failure must never read as empty) ────────
def enumerate_task_cards(topic, task_values=None):
    task_values = task_values if task_values is not None else topic.task_values
    if OBS:
        hits = []
        for c in OBS.list_cards("papers"):
            tv = c["props"].get("tasks") or []
            if any(v in tv for v in task_values):
                hits.append({"id": c["id"], "title": c["title"],
                             "src": c["props"].get("source_type"),
                             "aid": c["props"].get("arxiv_id"),
                             "kind": classify(topic, c["title"],
                                              c["props"].get("source_type"))})
        return hits
    if not topic.scan_tags:
        sys.exit("config 缺少 heptabase.scan_tags（heptabase 模式必填）")
    if not (topic.tasks_prop and topic.source_type_prop and topic.arxiv_prop):
        sys.exit("config 缺少 heptabase.props.{tasks, source_type, arxiv}（heptabase 模式必填）")
    seen = {}
    for tg in topic.scan_tags:
        r = subprocess.run(["heptabase", "tag", "cards", tg], capture_output=True, text=True)
        try:
            data = json.loads(r.stdout)
        except Exception:
            data = None
        # Fail fast: a scan failure must NOT read as an empty corpus (a silent
        # empty scan would make `status` report 0 missing — a false positive).
        if r.returncode != 0 or not isinstance(data, dict) or "cards" not in data:
            sys.exit(f"ERROR: tag scan failed for {tg} (rc={r.returncode}): "
                     f"{(r.stderr or r.stdout).strip()[:160]}")
        for c in data["cards"]:
            seen[c["id"]] = c.get("title", "")
    hits = []
    prop_failures = 0
    for cid, title in seen.items():
        r = subprocess.run(["heptabase", "card", "properties", cid], capture_output=True, text=True)
        try:
            data = json.loads(r.stdout)
        except Exception:
            data = None
        # A JSON error object ({"error": ...}) parses fine but has no tags —
        # count it as a failure instead of silently treating the card as untagged.
        if r.returncode != 0 or not isinstance(data, dict) or "error" in data or "tags" not in data:
            prop_failures += 1
            continue
        tasks = src = aid = None
        for t in data.get("tags", []):
            for p in t.get("properties", []):
                if p["id"] == topic.tasks_prop and p.get("value"):       tasks = p["value"]
                if p["id"] == topic.source_type_prop and p.get("value"): src = p["value"]
                if p["id"] == topic.arxiv_prop and p.get("value"):       aid = p["value"]
        tv = tasks if isinstance(tasks, list) else ([tasks] if tasks else [])
        if any(v in tv for v in task_values):
            hits.append({"id": cid, "title": title, "src": src, "aid": aid,
                         "kind": classify(topic, title, src)})
    if prop_failures:
        sys.exit(f"ERROR: {prop_failures} card-properties reads failed — scan incomplete, aborting")
    return hits


# ── Sorting ──────────────────────────────────────────────────────────────────────
def _hidx(C, title):
    return next(i for i, n in enumerate(C)
                if n.get("type") == "heading" and node_text(n).strip() == title)


def _split_depth0(s):
    segs, buf, depth = [], "", 0
    for ch in s:
        if ch == "（": depth += 1; buf += ch; continue
        if ch == "）":
            depth = max(0, depth - 1); buf += ch
            if depth == 0: segs.append(buf.strip("、→； ")); buf = ""
            continue
        if depth == 0 and ch in "、→；":
            if buf.strip("、→； "): segs.append(buf.strip("、→； "))
            buf = ""; continue
        buf += ch
    if buf.strip("、→； "): segs.append(buf.strip("、→； "))
    return [s for s in segs if s]


def sort_synthesis_text(topic, full_text):
    """Pure decision helper for one synthesis bullet's text. Returns the
    re-sorted `prefix：a、b、c` string, or None when the bullet must be left
    untouched (contains a narrative prose chunk, or <2 papers)."""
    if "：" not in full_text:
        return None
    prefix, _, rest = full_text.partition("：")
    seen, papers, prose = set(), [], False
    for c in _split_depth0(rest):
        nm = next((name for name, _ in topic.match if name in c), None)
        if nm is None:
            prose = True; continue   # narrative interlude — keep bullet untouched
        if nm in seen: continue
        seen.add(nm); papers.append(c)
    if prose or len(papers) <= 1:
        return None
    papers.sort(key=lambda c: arxiv_key(topic, c))
    return prefix + "：" + "、".join(papers)


def sort_overview(topic, card_id):
    """Sort one OWN card: L3 sections, dimension rows, every classification
    table's representative cells, synthesis bullets (prose-guarded)."""
    md5, doc = read_card(card_id)
    C = doc["content"]
    start = _hidx(C, topic.sections_between[0]) + 1
    end = _hidx(C, topic.sections_between[1])
    blocks, cur = [], None
    for n in C[start:end]:
        if n.get("type") == "heading" and n["attrs"].get("level") == 3:
            cur = [n]; blocks.append(cur)
        elif cur is not None: cur.append(n)
    blocks.sort(key=lambda b: arxiv_key(topic, node_text(b[0])))
    C[start:end] = [n for b in blocks for n in b]

    hi = _hidx(C, topic.dim_table_heading)
    ti = next(i for i in range(hi, len(C)) if C[i].get("type") == "table")
    rows = C[ti]["content"]
    C[ti]["content"] = [rows[0]] + sorted(
        rows[1:], key=lambda r: arxiv_key(topic, node_text(r["content"][0])))

    for heading in topic.classification_headings:
        try:
            hj = _hidx(C, heading)
        except StopIteration:
            continue   # this card doesn't carry that classification table
        tj = next(i for i in range(hj, len(C)) if C[i].get("type") == "table")
        for row in C[tj]["content"][1:]:
            cell = row["content"][topic.representative_col]
            names = [s for s in node_text(cell).split("、") if s.strip()]
            names.sort(key=lambda s: arxiv_key(topic, s))
            cell["content"][0]["content"] = [{"type": "text", "text": "、".join(names)}]

    hk = _hidx(C, topic.synthesis_heading)
    for i in range(hk + 1, len(C)):
        n = C[i]
        if n.get("type") != "bullet_list_item": continue
        new_text = sort_synthesis_text(topic, node_text(n))
        if new_text is None: continue
        n["content"] = [{"type": "paragraph", "attrs": {"id": None},
                         "content": [{"type": "text", "text": new_text}]}]

    save_card(card_id, md5, doc)
    return [node_text(b[0]).strip() for b in blocks]


# ── Status (coverage diff) ───────────────────────────────────────────────────────
def coverage_linked_split(topic):
    """One pass over the coverage union, split two ways: (linked_all,
    linked_own). `linked_all` is the global-union coverage (covered = linked in
    ANY comparison card); `linked_own` is the subset linked inside THIS topic's
    own boundary — `subtree_cards` when the graph nests sub-topics under it,
    else `own_cards`. A method paper in linked_all but not linked_own is
    covered only elsewhere → `status` flags it `[elsewhere]` (informational,
    NOT missing): the topic may still want its own facet section for it."""
    own_ids = set(topic.subtree_cards or topic.own_cards)
    if topic.coverage_members:
        # Phase-2 global union. Fail fast — a read failure must not shrink the
        # union silently.
        members = list(topic.coverage_members)
        # own cards are comparison members by construction; be safe anyway.
        members += [c for c in own_ids if c not in set(members)]
        linked_all, linked_own = set(), set()
        for c in members:
            try:
                _, doc = read_card(c)
            except Exception as e:
                sys.exit(f"ERROR: coverage read failed for {c}: {e}")
            ids = linked_card_ids(doc)
            linked_all |= ids
            if c in own_ids:
                linked_own |= ids
        return linked_all, linked_own
    linked = set()
    for c in topic.overview_cards:
        try:
            _, doc = read_card(c); linked |= linked_card_ids(doc)
        except Exception:
            pass
    return linked, linked  # legacy path has no global union to compare against


def coverage_linked(topic):
    linked_all, _ = coverage_linked_split(topic)
    return linked_all


def status(topic):
    if topic.status_fn:
        return topic.status_fn(topic)
    hits = enumerate_task_cards(topic)
    linked, linked_own = coverage_linked_split(topic)
    if topic.status_header_fn:
        for line in topic.status_header_fn(topic, hits, linked):
            print(line)
    else:
        print(f"Tasks in {topic.task_values}:")
        if topic.coverage_members:
            print(f"  {len(hits)} cards; union across {len(topic.own_cards)} own + "
                  f"global comparison graph ({len(topic.coverage_members)} cards)\n")
        else:
            print(f"  {len(hits)} cards; union across {len(topic.own_cards)} own + "
                  f"{len(topic.extra_coverage)} extra-coverage cards\n")
    missing, elsewhere = [], []
    for h in sorted(hits, key=lambda x: arxiv_key(topic, x["title"])):
        covered = h["id"] in linked
        mark = ""
        if h["kind"] == "method" and not covered:
            missing.append(h)
        elif h["kind"] == "method" and covered and h["id"] not in linked_own:
            elsewhere.append(h)
            mark = " [elsewhere]"
        print(f"  [{h['kind']:{topic.kind_width}}] covered={str(covered):5} "
              f"{h['aid'] or '-':16} {h['title'][:50]}{mark}")
    print(f"\n{topic.missing_label} ({len(missing)}):")
    for h in missing:
        print(f"  + {h['id']}  {h['aid'] or '-':16} {h['title']}")
    if elsewhere:
        # Informational, NOT missing: covered in the global union but not in
        # this topic's own cards — a candidate for a facet section from THIS
        # topic's angle (or a deliberate cross-topic delegation; judge by the
        # topic doc's 分工約定).
        print(f"ELSEWHERE — covered only outside this topic's own cards ({len(elsewhere)}):")
        for h in elsewhere:
            print(f"  * {h['id']}  {h['aid'] or '-':16} {h['title']}")
    return missing


# ── Topology snapshot loading (phase 2: graph-derived config) ────────────────────
def _subtree_own_cards(topics_dir, snap, seen):
    """own_cards over the snapshot's whole sub_topics subtree (graph-derived
    nesting, e.g. auditory under spoken). A child's missing/broken snapshot is
    skipped here — the child topic's own runner fails fast on it anyway."""
    own = list(snap.get("own_cards") or [])
    for child in snap.get("sub_topics") or []:
        if child in seen:
            continue
        seen.add(child)
        cpath = os.path.join(topics_dir, child, "topic_snapshot.json")
        try:
            csnap = json.load(open(cpath, encoding="utf-8"))
        except Exception:
            continue
        own += _subtree_own_cards(topics_dir, csnap, seen)
    return own


def load_topic_snapshot(skill_dir, **topic_kwargs):
    """Build an OverviewTopic from the skill's graph-derived topic_snapshot.json
    (written by `_shared/topology.py refresh`). The snapshot supplies own_cards,
    match, task_values and the global-union coverage_members; everything else
    (dim_cols, cards, hooks, status_fn, …) comes from topic_kwargs. Explicit
    topic_kwargs win over snapshot values. Fail-fast on a missing snapshot —
    stale/absent topology must never look healthy."""
    path = os.path.join(skill_dir, "topic_snapshot.json")
    if not os.path.exists(path):
        sys.exit(f"ERROR: missing topic_snapshot.json in {skill_dir} — run "
                 f"`python3 _shared/topology.py refresh` first")
    try:
        snap = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        sys.exit(f"ERROR: unreadable topic_snapshot.json in {skill_dir}: {e}")
    for k in ("own_cards", "match", "task_values", "comparison_members"):
        if not snap.get(k):
            sys.exit(f"ERROR: topic_snapshot.json in {skill_dir} lacks {k!r} — re-run refresh")
    kwargs = {
        "own_cards": snap["own_cards"],
        "task_values": snap["task_values"],
        "match": [tuple(x) for x in snap["match"]],
        "coverage_members": snap["comparison_members"],
        "cards": {},
    }
    if snap.get("sub_topics"):
        kwargs["subtree_cards"] = _subtree_own_cards(
            os.path.dirname(os.path.abspath(skill_dir)), snap, set())
    kwargs.update(topic_kwargs)
    return OverviewTopic(**kwargs)


# ── CLI ──────────────────────────────────────────────────────────────────────────
def run_cli(topic, argv=None):
    """Default CLI (speech-generation style). Skills needing a different sort
    print format keep their own __main__ and call the primitives directly."""
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "status"
    if cmd == "sort":
        for c in topic.own_cards:
            print(f"# sorting {c}")
            for o in sort_overview(topic, c):
                print("  ", o)
        for fn in topic.extra_sorts:
            fn(topic)
    else:
        status(topic)
