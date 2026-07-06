#!/usr/bin/env python3
"""Topic-config TEMPLATE. Copy this dir to your user topics dir
(~/.config/research-cards/topics/<your-topic>/), rename, and fill in.

A topic = one comparison-overview card set. NOTE: once copied OUT of the
repo, the relative _shared fallback no longer applies — set `plugin_root`
in the config so the bootstrap can locate the plugin. Minimal required fields below;
see overview_engine.OverviewTopic for every knob. Snapshots
(topic_snapshot.json, written by topology.py refresh) live next to this file.
"""
import json as _json
import os, sys
from pathlib import Path as _P


def _shared_dir():
    _env = os.environ.get("RESEARCH_CARDS_CONFIG") or os.environ.get("HEPTABASE_CARDS_CONFIG")
    _new = _P.home() / ".config/research-cards/config.json"
    _legacy = _P.home() / ".config/heptabase-cards/config.json"
    cfg = _P(_env) if _env else (_new if _new.exists() or not _legacy.exists() else _legacy)
    try:
        root = _json.loads(cfg.read_text()).get("plugin_root")
        if root:
            return str(_P(root).expanduser() / "skills" / "_shared")
    except Exception:
        pass
    return os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "..", "..", "..", "_shared")


sys.path.insert(0, _shared_dir())
import overview_engine as E  # noqa: E402

OVERVIEW_CARD = "<comparison-card-id>"   # heptabase UUID or obsidian Folder/Name
_DIR = os.path.dirname(os.path.realpath(__file__))

# The snapshot (topic_snapshot.json next to this file, written by
# `topology.py refresh` once the topic's hub is registered in config
# `*.graph.hubs`) supplies own_cards / match / task_values / coverage;
# everything presentational comes from kwargs here.
TOPIC = E.load_topic_snapshot(
    _DIR,
    cards={OVERVIEW_CARD: {"title": "<card title>",
                            "intro": "<one-paragraph intro>"}},
    dim_cols=["論文", "<dimension>", "<dimension>", "開源"],
)


def cli(argv):
    E.run_cli(TOPIC, argv)
