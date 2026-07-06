#!/usr/bin/env python3
"""Unified overview maintenance CLI — one skill, seven topics.

  python3 sync_overview.py <topic> status   # coverage diff for that topic
  python3 sync_overview.py <topic> sort     # sort that topic's own cards
  python3 sync_overview.py <topic> build    # topic-specific one-off assembly (where supported)

Topics: tokenizer, spoken (nests auditory), auditory, duplex,
speech-generation, asr, frontend-security.

Topics can NEST, mirroring the hub tree: a topic whose graph-derived snapshot
lists `sub_topics` (a sub-hub bullet in its hub's 子卡與閱讀順序 that is another
topic's anchor — e.g. 聽覺翼 under Spoken → spoken nests auditory) has its
`status`/`sort` also run each child topic, clearly labelled. A child key still
works standalone. The nesting comes ONLY from the snapshot (the graph decides);
moving the sub-hub in Heptabase + `topology.py refresh` re-parents it here.

Each topic lives in topics/<key>/: config.py (topic config + hooks + the
documented S.* authoring API), topic_snapshot.json (graph-derived by
_shared/topology.py refresh), plus topic extras (spoken: lm_match.py;
duplex: hooks.py). Topic docs: topics/<key>.md. Mechanical layer:
_shared/overview_engine.py.

Programmatic use (authoring workflows, see SKILL.md):
  import sync_overview as O
  S = O.load("spoken")          # the topic's bound namespace (old S.* API)
  S.section(...); S.dim_row(...); S.sort_overview(S.OVERVIEW_CARD_A1)
"""
import importlib.util
import json
import os
import sys

_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, "..", "_shared"))
try:
    import hbconfig as _hbc
    _proot = _hbc.plugin_root()
    if _proot:  # codex cache copies are static; anchor to the live tree
        _DIR = os.path.join(_proot, "skills", "overview")
except Exception:
    pass

def _topics_dir():
    try:
        import hbconfig
        return hbconfig.topics_dir()
    except ImportError:
        return os.path.join(_DIR, "topics")


TOPICS_DIR = _topics_dir()
TOPIC_KEYS = sorted(
    d for d in (os.listdir(TOPICS_DIR) if os.path.isdir(TOPICS_DIR) else [])
    if not d.startswith("_")
    and os.path.isfile(os.path.join(TOPICS_DIR, d, "config.py")))

_cache = {}


def load(topic):
    """Import topics/<topic>/config.py as a module and cache it."""
    if topic not in TOPIC_KEYS:
        sys.exit(f"unknown topic {topic!r} — choose from: {', '.join(TOPIC_KEYS)}")
    if topic in _cache:
        return _cache[topic]
    path = os.path.join(TOPICS_DIR, topic, "config.py")
    spec = importlib.util.spec_from_file_location(f"overview_topic_{topic}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    _cache[topic] = mod
    return mod


def sub_topics(topic):
    """The topic's nested child keys, straight from its graph-derived snapshot."""
    path = os.path.join(TOPICS_DIR, topic, "topic_snapshot.json")
    try:
        snap = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []  # config.py's load_topic_snapshot already fails fast on a bad snapshot
    return list(snap.get("sub_topics") or [])


def run(topic, rest, _seen=None):
    """Run one topic's cli; for status/sort, also run its sub_topics (labelled)."""
    _seen = _seen or set()
    if topic in _seen:
        sys.exit(f"ERROR: sub_topics cycle at {topic!r} — fix the hub graph")
    _seen.add(topic)
    rc = load(topic).cli(rest)
    cmd = rest[0] if rest else "status"
    if cmd in ("status", "sort"):
        for child in sub_topics(topic):
            print(f"\n── sub-topic: {child} (nested under {topic}) ──")
            run(child, rest, _seen)
    return rc


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        sys.exit(f"usage: sync_overview.py <topic> [status|sort|build]\n"
                 f"topics: {', '.join(TOPIC_KEYS)}")
    topic, rest = argv[0], argv[1:]
    return run(topic, rest)


if __name__ == "__main__":
    try:
        import hbconfig as _hbc
        if not _hbc.feature_enabled("study"):
            sys.exit("study 方向已在 config features.study 停用")
    except ImportError:
        pass
    main()
