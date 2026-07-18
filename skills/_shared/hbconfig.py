#!/usr/bin/env python3
"""Plugin-wide user config for research-cards.

Location: ~/.config/research-cards/config.json (legacy dir/env still
honored; override with RESEARCH_CARDS_CONFIG). See config.example.json at the plugin root.

note surfaces — the "backends" list (0.30.0):
  "backends": ["heptabase", "local"]   # first entry = canonical (authoring)
  values: "local" (plain .md in a folder — no note app required; the value
  formerly named "obsidian", which is still accepted as an alias),
  "heptabase", "hackmd" (publish surface — never first).
  The legacy single-value "backend" key (obsidian|heptabase|both) keeps
  working; load_config() normalizes either spelling and keeps BOTH keys
  populated, so internal code may keep reading cfg["backend"].
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

class ConfigError(RuntimeError):
    pass


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise ConfigError(
            f"找不到設定檔 {CONFIG_PATH}。請複製 plugin 根目錄的 "
            "config.example.json 過去並填入你的 backend/vault/tag 設定。")
    cfg = json.load(open(CONFIG_PATH))
    # ── note-surface list (0.30.0) ─────────────────────────────────────
    # "backends": ["heptabase", "local"] — first entry is the canonical
    # (authoring) side, the rest are mirrors. "local" = plain .md in a
    # folder (the value formerly named "obsidian"; alias still accepted).
    # The legacy single-value "backend" key keeps working, and BOTH keys
    # are kept in sync so existing code reading cfg["backend"] is
    # untouched. Unset everything defaults to ["local"] — no note app
    # required. (A MISSING config file still raises above, and the legacy
    # "no config at all" fallbacks elsewhere keep meaning heptabase — old
    # cron setups predate the config file and must not change behavior.)
    _ALIAS = {"obsidian": "local"}
    _LEGACY = {"both": ["heptabase", "local"],
               "heptabase": ["heptabase"],
               "obsidian": ["local"]}
    raw = cfg.get("backends")
    explicit_list = raw is not None
    if raw is None:
        legacy = cfg.get("backend") or "obsidian"
        if legacy not in _LEGACY:
            raise ConfigError(f"config 的 backend 必須是 obsidian|heptabase|both，"
                              f"目前是 {legacy!r}（或改用新式 backends list）")
        raw = list(_LEGACY[legacy])
    if not isinstance(raw, list) or not raw or \
            not all(isinstance(b, str) for b in raw):
        raise ConfigError('config 的 backends 必須是非空字串 list，'
                          '例如 ["heptabase", "local"]')
    backends = []
    for b in raw:
        b = _ALIAS.get(b, b)
        if b not in ("local", "heptabase", "hackmd"):
            raise ConfigError(f"backends 含未知項 {b!r}——可用：local（純 .md 資料夾；"
                              "舊名 obsidian）、heptabase、hackmd")
        if b not in backends:
            backends.append(b)
    if backends[0] == "hackmd":
        raise ConfigError("hackmd 是發佈面、不能當正本——backends 首位要是 "
                          "local 或 heptabase")
    core = [b for b in backends if b != "hackmd"]
    if core == ["local", "heptabase"]:
        raise ConfigError('backends: ["local", "heptabase"]（local 為正本、'
                          'heptabase 為鏡像）尚未支援——現行引擎以 Heptabase 為'
                          '正本鏡像到 vault；要雙庫請寫 ["heptabase", "local"]')
    # legacy spelling never mentioned hackmd — infer it from an enabled
    # hackmd.collections so behavior doesn't change; an EXPLICIT list is
    # taken at face value (omit "hackmd" there to disable the mirror)
    if not explicit_list and (cfg.get("hackmd") or {}).get("collections") \
            and "hackmd" not in backends:
        backends.append("hackmd")
    cfg["backends"] = backends
    backend = ("both" if {"heptabase", "local"} <= set(core)
               else ("heptabase" if core == ["heptabase"] else "obsidian"))
    cfg["backend"] = backend
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


def output_language():
    """Output language for generated card content (translate / summarize /
    teaching rewrite). Resolution order: config profile.language → Claude
    Code's user settings.json `language` (best-effort — absent on Codex or
    headless boxes) → 繁體中文. The Claude Code value is a bare English word
    ("chinese", "japanese"); common values map to a precise instruction.
    "chinese" maps to 繁體中文 — this plugin's historical default; simplified-
    Chinese users set profile.language = "简体中文" explicitly."""
    try:
        lang = ((load_config().get("profile") or {}).get("language") or "").strip()
        if lang:
            return lang
    except Exception:
        pass
    try:
        p = os.environ.get("CLAUDE_SETTINGS_PATH",
                           os.path.expanduser("~/.claude/settings.json"))
        cc = str(json.load(open(p)).get("language") or "").strip().lower()
        if cc:
            return {"chinese": "繁體中文", "taiwanese": "繁體中文",
                    "japanese": "日本語", "korean": "한국어",
                    "english": "English"}.get(cc, cc)
    except Exception:
        pass
    return "繁體中文"


# Structural labels for generated card sections, per output language. These
# are PROGRAM-inserted (not LLM prose) and double as detection markers —
# generation uses the current language, while detection must scan ALL
# languages (a library legitimately mixes languages after a settings change).
STRUCT_LABELS = {
    "繁體中文": {"summary": "快速摘要", "ai_summary": "AI 摘要",
               "problems": "問題", "methods": "方法", "results": "結果",
               "takeaways": "要點",
               "prereq_heading": "先備知識（名詞快速補帖）",
               "prereq_marker": "先備知識"},
    "简体中文": {"summary": "快速摘要", "ai_summary": "AI 摘要",
               "problems": "问题", "methods": "方法", "results": "结果",
               "takeaways": "要点",
               "prereq_heading": "先备知识（名词快速补帖）",
               "prereq_marker": "先备知识"},
    "English": {"summary": "Quick Summary", "ai_summary": "AI Summary",
                "problems": "Problems", "methods": "Methods",
                "results": "Results", "takeaways": "Takeaways",
                "prereq_heading": "Prerequisites (jargon quick reference)",
                "prereq_marker": "Prerequisites"},
    "日本語": {"summary": "クイックサマリー", "ai_summary": "AI サマリー",
              "problems": "課題", "methods": "手法", "results": "結果",
              "takeaways": "要点",
              "prereq_heading": "前提知識（用語クイックリファレンス）",
              "prereq_marker": "前提知識"},
    "한국어": {"summary": "빠른 요약", "ai_summary": "AI 요약",
             "problems": "문제", "methods": "방법", "results": "결과",
             "takeaways": "핵심 포인트",
             "prereq_heading": "선행 지식(용어 빠른 참조)",
             "prereq_marker": "선행 지식"},
}


def struct_labels():
    """Labels for the current output language. Unknown languages fall back to
    English labels (the LLM prose still follows the configured language)."""
    return STRUCT_LABELS.get(output_language(), STRUCT_LABELS["English"])


def marker_variants(key):
    """Every language's variant of one structural marker — detectors must
    recognize cards generated under ANY past language setting."""
    return {v[key] for v in STRUCT_LABELS.values()}


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
