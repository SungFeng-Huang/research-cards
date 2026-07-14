#!/usr/bin/env python3
"""Plugin-wide user config for research-cards.

Location: ~/.config/research-cards/config.json (legacy dir/env still
honored; override with RESEARCH_CARDS_CONFIG). See config.example.json at the plugin root.

backend modes:
  "heptabase" - author in Heptabase only (no vault)
  "obsidian"  - author in an Obsidian vault only (no Heptabase app needed)
  "both"      - Heptabase is canonical; the obsidian-sync skill mirrors it
"""
import json, os

def _default_config_path():
    """New home first; the pre-rename legacy dir keeps working untouched."""
    new = os.path.expanduser("~/.config/research-cards/config.json")
    legacy = os.path.expanduser("~/.config/heptabase-cards/config.json")
    return new if os.path.exists(new) or not os.path.exists(legacy) else legacy


CONFIG_PATH = (os.environ.get("RESEARCH_CARDS_CONFIG")
               or os.environ.get("HEPTABASE_CARDS_CONFIG")  # legacy env
               or _default_config_path())

VALID_BACKENDS = ("heptabase", "obsidian", "both")


class ConfigError(RuntimeError):
    pass


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise ConfigError(
            f"找不到設定檔 {CONFIG_PATH}。請複製 plugin 根目錄的 "
            "config.example.json 過去並填入你的 backend/vault/tag 設定。")
    cfg = json.load(open(CONFIG_PATH))
    backend = cfg.get("backend")
    if backend not in VALID_BACKENDS:
        raise ConfigError(f"config 的 backend 必須是 {VALID_BACKENDS}，目前是 {backend!r}")
    agent = cfg.get("agent", "claude")
    if agent not in ("claude", "codex"):
        raise ConfigError(f"config 的 agent 必須是 claude|codex，目前是 {agent!r}")
    if backend in ("heptabase", "both"):
        hb = cfg.get("heptabase") or {}
        if not hb.get("workspace_id") or not hb.get("collections"):
            raise ConfigError("backend 含 heptabase 時需要 heptabase.workspace_id 與 collections")
    if backend in ("obsidian", "both"):
        ob = cfg.get("obsidian") or {}
        if not ob.get("vault"):
            raise ConfigError("backend 含 obsidian 時需要 obsidian.vault")
        ob["vault"] = os.path.expanduser(ob["vault"])
    return cfg


def hb_id(*path):
    """Required Heptabase id from config (e.g. hb_id("props", "tasks"),
    hb_id("collections", "papers", "tag_id")). Returns None when unset —
    callers on heptabase-mode paths must exit with a clear message."""
    try:
        node = load_config().get("heptabase") or {}
        for key in path:
            node = (node or {}).get(key)
        if isinstance(node, str) and node.startswith("<") and node.endswith(">"):
            return None  # config.example 的佔位符（如 <tag-uuid>）視同未設定
        return node or None
    except Exception:
        return None


def require_hb_id(*path):
    v = hb_id(*path)
    if not v:
        raise SystemExit("config 缺少 heptabase." + ".".join(path) +
                         "（heptabase 模式必填；用 `heptabase tag list` / "
                         "`heptabase tag properties <tagId>` 查 id）")
    return v


def user_data_dir():
    """Per-user plugin data home (topics/, aliases.json, projects.json)."""
    return os.path.dirname(CONFIG_PATH)


def topics_dir():
    """Overview topic configs: the user data dir wins; the in-repo
    skills/overview/topics/ (with its _example template) is the fallback."""
    user = os.path.join(user_data_dir(), "topics")
    if os.path.isdir(user):
        return user
    root = plugin_root()
    if root:
        return os.path.join(root, "skills", "overview", "topics")
    return os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "..", "overview", "topics")


def load_aliases():
    """topology match ALIASES: {topic: [[short-name, arxiv-key], ...]}."""
    import json as _json
    p = os.path.join(user_data_dir(), "aliases.json")
    try:
        return {k: [tuple(x) for x in v]
                for k, v in _json.load(open(p)).items()}
    except Exception:
        return {}


def feature_enabled(name):
    """Usage-direction toggle: config features.{study, project}, default on."""
    try:
        return bool((load_config().get("features") or {}).get(name, True))
    except Exception:
        return True


def plugin_root():
    """Canonical live plugin root (optional config key `plugin_root`).

    Codex installs plugins as a STATIC CACHE COPY; scripts running from the
    copy must anchor repo-state paths (topology snapshots, highlights.json,
    overview topic configs) back to the live tree, or reads go stale and
    writes get lost on the next cache refresh. Returns None when unset
    (running from the live tree, e.g. Claude Code)."""
    try:
        p = load_config().get("plugin_root")
        return os.path.expanduser(p) if p else None
    except Exception:
        return None


def journal_dir(cfg):
    """Journal daily-note dir: vault + obsidian.journal.folder (vault-
    relative; empty/absent = vault root, backward compatible). Values
    escaping the vault (absolute paths, '..') are rejected — the bridge
    must never touch files outside it."""
    vault = os.path.normpath(cfg["obsidian"]["vault"])
    folder = ((cfg["obsidian"].get("journal") or {}).get("folder") or "")
    jdir = os.path.normpath(os.path.join(vault, folder))
    if os.path.isabs(folder) or (jdir != vault
                                 and not jdir.startswith(vault + os.sep)):
        raise ConfigError(
            "obsidian.journal.folder 必須是 vault 內的相對路徑"
            f"（不可為絕對路徑或以 .. 逃出 vault），目前是 {folder!r}")
    return jdir


def collections(cfg):
    """Unified collection view: key -> {tag_id?, tag_name?, filter?, folder?, new_card_props?}."""
    out = {}
    for key, hc in (cfg.get("heptabase", {}).get("collections") or {}).items():
        out[key] = dict(hc)
    for key, folder in (cfg.get("obsidian", {}).get("folders") or {}).items():
        out.setdefault(key, {})["folder"] = folder
    return out
