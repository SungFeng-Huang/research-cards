#!/usr/bin/env python3
"""Graph-derived topology snapshots for the unified `overview` skill's topics (phase 2).

The knowledge graph (topic hubs + study/overview members) is the source of
truth for each topic's card set; this tool derives, per skill, a
`topic_snapshot.json` the engine loads instead of hand-maintained constants:

  kind                ← derived: anchor card carries 「子卡與閱讀順序」 → hub,
                        else single comparison card (registry stores no kind)
  own_cards           ← the anchor hub's 「子卡與閱讀順序」 mentions; a bullet
                        mentioning another registered anchor is NOT an own
                        card — it nests that topic (see sub_topics)
  sub_topics          ← topic keys of sub-hub bullets inside the anchor hub's
                        子卡 section (e.g. 聽覺翼 under Spoken → spoken nests
                        "auditory"); status/sort on the parent aggregates the
                        subtree; an unregistered sub-hub is a hard error
  comparison_members  ← every study/overview member whose content carries a
                        per-paper section heading (各論文核心貢獻與設計差異 /
                        各論文簡介) — the CONTENT-BASED comparison-card set
                        used for global-union coverage (Level is navigation
                        depth, not card kind — don't filter by it)
  match               ← generated: each own-card L3 section's heading short
                        name paired with the mentioned paper card's arxiv ID
                        property, merged with the skill's static ALIASES
                        (non-arxiv fallbacks + short-name/casing variants),
                        sorted longest-substring-first
  task_values         ← the anchor card's Tasks property (hubs and single
                        topic cards carry their topic's values)

  python3 topology.py refresh [<skill_dir>|<skill_name> ...]   # default: all
  python3 topology.py check   [...]    # re-derive vs snapshots; exit 1 = stale

Fail-fast everywhere: a graph read failure, an unparseable hub, or an empty
Tasks property aborts — a silently empty topology must never look healthy.
"""
import os, re, sys, json, subprocess

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import overview_engine as E  # noqa: E402

try:
    import backend as _backend
    OBS = _backend.obsidian_or_none()
except Exception:
    OBS = None

try:
    import hbconfig as _hbc
    _proot = _hbc.plugin_root()
except Exception:
    _proot = None
SKILLS_ROOT = (os.path.join(_proot, "skills") if _proot
               else os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
try:
    import hbconfig as _hbc0
    STUDY_OVERVIEW_TAG = _hbc0.hb_id("collections", "overviews", "tag_id")
except Exception:
    STUDY_OVERVIEW_TAG = None
SUBCARD_HEADING    = "子卡與閱讀順序"
SECTION_HEADINGS   = ("各論文核心貢獻與設計差異", "各論文簡介")

# obsidian mode: property UUIDs -> frontmatter keys
_OBS_PROP_KEYS = {}

# ── Registry: identity only — key ↔ anchor ──────────────────────────────────────
# The GRAPH decides structure; derive() reads it. An anchor whose card carries a
# 「子卡與閱讀順序」 heading is a hub (own_cards = its sub-card mentions; a bullet
# mentioning another registered anchor becomes a nested sub_topic); otherwise the
# topic is a single comparison card (own_cards = [anchor]). Nothing structural
# (kind / parentage / include lists) lives here — moving a sub-hub in the graph
# re-parents its topic on the next refresh.
TOPICS = {}
try:  # anchors come from config: heptabase.graph.hubs (heptabase mode)
    import hbconfig as _hbc1
    _hh = ((_hbc1.load_config().get("heptabase") or {}).get("graph") or {}).get("hubs")
    if _hh and not OBS:
        TOPICS = dict(_hh)
except Exception:
    pass
if not TOPICS and not OBS:
    sys.exit("ERROR: 需要在 config 的 heptabase.graph.hubs 設定 topic 錨點"
             "（{key: \"<hub-card-uuid>\"}），才能推導 topology。")
if OBS:
    # obsidian mode: anchors come from config (vault ids "Folder/Name"), the
    # hardcoded UUIDs above are this install's personal Heptabase graph.
    _hubs = (OBS.cfg["obsidian"].get("graph") or {}).get("hubs") or {}
    if not _hubs:
        sys.exit("ERROR: backend=obsidian 需要在 config 的 obsidian.graph.hubs "
                 "設定 topic 錨點（{key: \"Overviews/卡名\"}），才能推導 topology。")
    TOPICS = dict(_hubs)

# ── Static aliases: entries match generation can't derive from the graph ────────
# (a) non-arxiv papers (blogs / openreview / aclanthology / Heptabase-native)
#     keep their historical order-preserving keys;
# (b) short-name & casing variants used by dim rows / synthesis bullets.
# Seeded 2026-07-05 by harvesting the pre-phase-2 MATCH tables (old − generated).
# match-generation aliases live in the USER data dir
# (~/.config/research-cards/aliases.json): {topic: [[short-name, key], ...]}
try:
    import hbconfig as _hbc2
    ALIASES = _hbc2.load_aliases()
except Exception:
    ALIASES = {}

_doc_cache = {}
_prop_cache = {}


def _die(msg):
    sys.exit(f"ERROR: {msg}")


def read_doc(card_id):
    if card_id in _doc_cache:
        return _doc_cache[card_id]
    if OBS:
        try:
            _, doc = OBS.read_doc(card_id)
        except Exception as e:
            _die(f"could not read card {card_id}: {str(e)[:160]}")
        _doc_cache[card_id] = doc
        return doc
    r = subprocess.run(["heptabase", "note", "read", card_id],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        doc = json.loads(data["content"])
    except Exception:
        data, doc = None, None
    if r.returncode != 0 or doc is None:
        _die(f"could not read card {card_id} (rc={r.returncode}): "
             f"{(r.stderr or r.stdout).strip()[:160]}")
    _doc_cache[card_id] = doc
    return doc


def card_props(card_id):
    if card_id in _prop_cache:
        return _prop_cache[card_id]
    r = subprocess.run(["heptabase", "card", "properties", card_id],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        data = None
    if r.returncode != 0 or not isinstance(data, dict) or "error" in data or "tags" not in data:
        _die(f"card properties failed for {card_id} (rc={r.returncode}): "
             f"{(r.stderr or r.stdout).strip()[:160]}")
    _prop_cache[card_id] = data
    return data


def prop_value(card_id, prop_id, obs_key=None):
    """obs_key names the frontmatter field explicitly — never derive it from
    the UUID constants (they may legitimately be None in pure-obsidian mode)."""
    if OBS:
        if obs_key is None:
            _die("內部錯誤：obsidian 模式呼叫 prop_value 未帶 obs_key")
        if card_id not in _prop_cache:
            _prop_cache[card_id] = OBS.read_card(card_id).props
        return _prop_cache[card_id].get(obs_key) or None
    if not prop_id:
        _die("config 缺少 heptabase.props.{tasks|arxiv}（heptabase 模式必填）")
    for t in card_props(card_id).get("tags", []):
        for p in t.get("properties", []):
            if p["id"] == prop_id and p.get("value"):
                return p["value"]
    return None


def tag_members(tag_id=None):
    tag_id = tag_id or STUDY_OVERVIEW_TAG
    if OBS:
        try:
            return [c["id"] for c in OBS.list_cards("overviews")]
        except Exception as e:
            _die(f"overviews 資料夾掃描失敗：{str(e)[:160]}")
    if not tag_id:
        _die("config 缺少 heptabase.collections.overviews.tag_id（heptabase 模式必填）")
    r = subprocess.run(["heptabase", "tag", "cards", tag_id],
                       capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        data = None
    if r.returncode != 0 or not isinstance(data, dict) or "cards" not in data:
        _die(f"tag scan failed for {tag_id} (rc={r.returncode}): "
             f"{(r.stderr or r.stdout).strip()[:160]}")
    return [c["id"] for c in data["cards"]]


# ── Graph parsing ────────────────────────────────────────────────────────────────
def _headings(doc):
    return [(n["attrs"].get("level"), E.node_text(n).strip())
            for n in doc["content"] if n.get("type") == "heading"]


def is_hub(doc):
    return any(t == SUBCARD_HEADING for _, t in _headings(doc))


def is_comparison(doc):
    return any(t in SECTION_HEADINGS for _, t in _headings(doc))


def _mentions(node):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "card":
                out.append(n["attrs"].get("cardId"))
            for c in n.get("content", []):
                walk(c)
    walk(node)
    return out


def hub_subcards(hub_id):
    """(own_cards, sub_topics) from the hub's 子卡與閱讀順序 section, in bullet
    order. A mention that is itself a hub must be another registered topic's
    anchor — it becomes a nested sub_topic key (the child topic keeps owning
    its own cards); an unregistered sub-hub is a hard error, not a skip.
    The section format is an API: assert loudly."""
    doc = read_doc(hub_id)
    C = doc["content"]
    start = next((i for i, n in enumerate(C) if n.get("type") == "heading"
                  and E.node_text(n).strip() == SUBCARD_HEADING), None)
    if start is None:
        _die(f"hub {hub_id} has no 「{SUBCARD_HEADING}」 section — "
             "hub format changed? (this parse is an API)")
    ids = []
    for n in C[start + 1:]:
        if n.get("type") == "heading":
            break
        for cid in _mentions(n):
            if cid not in ids:
                ids.append(cid)
    if not ids:
        _die(f"hub {hub_id}: 「{SUBCARD_HEADING}」 section has no card mentions")
    anchor_to_key = {a: k for k, a in TOPICS.items()}
    out, subs = [], []
    for cid in ids:
        if is_hub(read_doc(cid)):
            key = anchor_to_key.get(cid)
            if key is None:
                _die(f"hub {hub_id} sub-hub {cid} is not a registered topic "
                     f"anchor — add it to config *.graph.hubs, then refresh")
            subs.append(key)
            continue
        if not is_comparison(read_doc(cid)):
            _die(f"hub {hub_id} sub-card {cid} is neither hub nor comparison card")
        out.append(cid)
    return out, subs


def sections_of(card_id):
    """[(short_name, mentioned_card_id | None)] for each L3 section block."""
    doc = read_doc(card_id)
    C = doc["content"]
    out = []
    i = 0
    while i < len(C):
        n = C[i]
        if n.get("type") == "heading" and n["attrs"].get("level") == 3:
            heading = E.node_text(n).strip()
            j = i + 1
            block_mentions = []
            while j < len(C) and C[j].get("type") != "heading":
                block_mentions.extend(_mentions(C[j]))
                j += 1
            short = heading.split("（")[0].strip()
            out.append((short, heading, block_mentions[0] if block_mentions else None))
            i = j
        else:
            i += 1
    return out


def derive(skill):
    anchor = TOPICS[skill]

    # kind + own_cards + sub_topics — all read from the graph, never the registry
    if is_hub(read_doc(anchor)):
        kind = "hub"
        own, sub_topics = hub_subcards(anchor)
    else:
        kind = "card"
        own, sub_topics = [anchor], []
        if not is_comparison(read_doc(anchor)):
            _die(f"{skill}: anchor {anchor} is not a comparison card")

    # comparison members (content-based, global)
    members = [cid for cid in tag_members() if is_comparison(read_doc(cid))]

    # generated match: section short-name → mentioned paper's arxiv ID
    gen = {}
    for cid in own:
        for short, heading, mention in sections_of(cid):
            if not short or not mention:
                continue
            aid = prop_value(mention, E.DEFAULT_ARXIV_PROP, obs_key="arxiv_id")
            # Only sortable numeric arxiv ids participate in generation;
            # openreview:/aclanthology:/alphaxiv:… ids would wreck the
            # chronological ordering → those papers keep their historical
            # order-preserving keys via ALIASES.
            if not aid or not re.fullmatch(r"\d{4}\.\d{4,6}", str(aid)):
                continue
            if short in gen and gen[short] != aid:
                _die(f"{skill}: conflicting arxiv keys for {short!r}: "
                     f"{gen[short]} vs {aid}")
            gen[short] = aid

    merged = dict(gen)
    for sub, key in ALIASES.get(skill, []):
        if sub in merged and merged[sub] != key:
            _die(f"{skill}: ALIAS {sub!r}={key} conflicts with generated {merged[sub]}")
        merged.setdefault(sub, key)
    match = sorted(merged.items(), key=lambda kv: (-len(kv[0]), kv[0]))

    # task values from the anchor
    tv = prop_value(anchor, E.DEFAULT_TASKS_PROP, obs_key="tasks")
    tv = tv if isinstance(tv, list) else ([tv] if tv else [])
    if not tv:
        _die(f"{skill}: anchor {anchor} has no Tasks property values — "
             "set the topic's Tasks on the hub/single card first")

    return {
        "skill": skill,
        "anchor": anchor,
        "kind": kind,
        "own_cards": own,
        "sub_topics": sub_topics,
        "comparison_members": members,
        "match": [[s, k] for s, k in match],
        "task_values": tv,
    }


def snapshot_path(skill):
    # Unified overview skill: every topic lives under overview/topics/<key>/.
    # TOPOLOGY_SNAPSHOT_ROOT overrides for tests (avoid clobbering production
    # snapshots when deriving with a different backend).
    root = os.environ.get("TOPOLOGY_SNAPSHOT_ROOT")
    if not root:
        try:
            import hbconfig as _hbc3
            root = _hbc3.topics_dir()
        except Exception:
            root = os.path.join(SKILLS_ROOT, "overview", "topics")
    os.makedirs(os.path.join(root, skill), exist_ok=True)
    return os.path.join(root, skill, "topic_snapshot.json")


def _resolve_skills(args):
    if not args:
        return list(TOPICS)
    out = []
    for a in args:
        name = os.path.basename(os.path.normpath(a))
        if name not in TOPICS:
            _die(f"unknown skill {a!r} (registered: {', '.join(TOPICS)})")
        out.append(name)
    return out


def refresh(skills):
    for skill in skills:
        snap = derive(skill)
        with open(snapshot_path(skill), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        sub = f" sub_topics={snap['sub_topics']}" if snap["sub_topics"] else ""
        print(f"{skill}: own={len(snap['own_cards'])}{sub} "
              f"members={len(snap['comparison_members'])} "
              f"match={len(snap['match'])} tasks={snap['task_values']}")


def check_unregistered_topics():
    """Topic-level drift guard. Many members legitimately carry Tasks values
    (comparison cards, 術語卡, sub-hubs) — that alone is fine. The drift signal
    is a Tasks VALUE that no registered topic owns: a new hub/topic was created
    in the graph (or a value renamed) without a TOPICS entry, so routing and
    coverage would silently miss it."""
    owned = set()
    for anchor in TOPICS.values():
        owned.update(prop_value(anchor, E.DEFAULT_TASKS_PROP, obs_key="tasks") or [])
    findings = 0
    for cid in tag_members():
        tv = prop_value(cid, E.DEFAULT_TASKS_PROP, obs_key="tasks") or []
        orphan = [v for v in tv if v not in owned]
        if orphan:
            print(f"!! unowned Tasks value(s) {orphan} on member {cid} — "
                  f"a new topic? add its anchor to config *.graph.hubs and "
                  f"create its user topic dir, then refresh")
            findings += 1
    return findings


def check(skills):
    stale = 0
    stale += check_unregistered_topics()
    for skill in skills:
        path = snapshot_path(skill)
        if not os.path.exists(path):
            print(f"!! {skill}: topic_snapshot.json missing — run refresh")
            stale += 1
            continue
        old = json.load(open(path, encoding="utf-8"))
        new = derive(skill)
        if old != new:
            diffs = [k for k in new if old.get(k) != new.get(k)]
            print(f"!! {skill}: stale snapshot (differs in: {', '.join(diffs)}) — run refresh")
            stale += 1
        else:
            print(f"{skill}: snapshot current")
    return 1 if stale else 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "check"
    if cmd == "refresh":
        refresh(_resolve_skills(argv[1:]))
    elif cmd == "check":
        sys.exit(check(_resolve_skills(argv[1:])))
    else:
        _die(f"unknown command {cmd!r} (refresh | check)")
