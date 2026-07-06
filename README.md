# research-cards

Research-card automation for **Heptabase** and/or **Obsidian**, driveable by
**Claude Code** or **Codex**. Clips papers from email digests into
teaching-style Chinese cards, maintains comparison-overview cards routed by a
Tasks taxonomy, keeps a knowledge graph (hubs / lateral edges / knowledge-map)
consistent, and bidirectionally syncs the whole card corpus between Heptabase
and an Obsidian vault.

## Two usage directions

The skills split into two independently usable directions (toggle either off
via config `features.{study, project}`):

**📚 Study — the paper pipeline**

| Skill | What it does |
|---|---|
| `scholar-inbox-clip` | Read paper-digest emails from Mail.app → fetch alphaXiv/arxiv content → create a teaching-style card (快速摘要 toggles, semantic colorization, figures) → set Tasks/properties → journal entry → route to the owning overview |
| `card-rewrite` | Retrofit a card into the full teaching format（一句話 / 為什麼該讀 / 0. 先備知識 / WHY-driven prose / bilingual terms） |
| `overview` | Maintain comparison-overview cards per topic: per-paper sections, dimension tables, paradigm/synthesis, arxiv-ordered sort, coverage status |
| `overview-daodu` | Insert/refresh a narrative 導讀 at the top of an overview card (idempotent) |
| `overview-graph` | Knowledge-graph structure: topic hubs, lateral ↔/→ edges, knowledge map (Heptabase whiteboard / Obsidian JSON Canvas), consistency audit |
| `obsidian-sync` | Heptabase ↔ Obsidian sync: incremental forward mirror, block-level write-back with lossless-or-conflict policy, new-file adoption, conflict ledger |
| `bib-export` | Export official BibTeX for every paper a card links to (overview / project card → `.bib`): Semantic Scholar → arxiv → ACL Anthology → OpenReview chains; never fabricates — unresolved papers become `% TODO` comments |

**🧪 Project — research-project logging**

| Skill | What it does |
|---|---|
| `project-card-log` | From a project repo session (local or remote), resolve THIS project's card and append codebase-grounded, dated enrichment (method/experiments/findings) — append-only |
| `project-card-merge` | The other half: consolidate the appended progress blocks into ONE paper-grade card (full-edit side) |

The pairing: `project-card-log` writes from wherever you work (locally via
the `heptabase` CLI, or from a remote/cluster session via an SSH bridge you
provide); `project-card-merge` merges on the machine with full edit access.
Project↔card resolution: per-repo `.heptabase-card` marker, or the registry at
`~/.config/research-cards/projects.json` (template: `projects.example.json`).

## Requirements

**Hard requirements**

- macOS with the **Heptabase desktop app** + the `heptabase` CLI **≥ 0.4.0**
  (local API on `127.0.0.1:21210`; the CLI bumps its version when its
  interface changes — `heptabase --version` to check) — needed for `backend: heptabase`/`both`; pure
  `backend: obsidian` works without it except for sync/adoption.
- Python 3.10+ with **PyYAML** (`pip install pyyaml`).
- An agent CLI: **Claude Code** (`claude`) or **Codex** (`codex`) — see
  Installation below; the `agent` config key selects which one unattended
  scripts shell for text generation.

**Per-feature requirements**

- `scholar-inbox-clip` email ingestion: **Mail.app** with a dedicated mailbox
  (set up a Mail rule routing your digest emails into it) + `osascript`
  automation permission. Digest sources: Scholar Inbox is fully supported
  (scores/links parsed); any digest carrying arxiv/alphaXiv links is
  extractable — other sources (e.g. HuggingFace Daily Papers) are on the
  roadmap and may work partially today.
- Figures: **PyMuPDF** (`pip install pymupdf`) for PDF figure rendering,
  `rsvg-convert` (`brew install librsvg`) for SVG.
- `backend: obsidian`/`both`: an **Obsidian vault**; if it lives in iCloud
  Drive, the terminal running the agent needs **Full Disk Access**.
- Claude Code enhancers (optional but recommended): the **alphaXiv MCP**
  server (grounding for clip/rewrite; Codex falls back to the built-in HTTP
  fetchers) and the **heptabase MCP** server (only needed to resolve
  highlight-embed contents during sync; Codex reports these for manual
  resolution). A hung-yi-lee-style teaching skill deepens the 導讀/rewrite
  voice but is not required — the style rules are embedded in the SKILL.mds.

## Installation

**Claude Code** — the plugin follows the standard Claude plugin layout
(`.claude-plugin/plugin.json`); install it from your marketplace/skills dir,
e.g. symlink this directory and load it as `research-cards@<your-source>`.
Skills appear as `research-cards:<skill>`.

**Codex** — the parent directory ships `.agents/plugins/marketplace.json`, so:

```bash
codex plugin marketplace add /path/to/plugins-dir
codex plugin add research-cards@<marketplace-name>
```

Codex runs plugins from a **static cache copy**: set `plugin_root` in the
config (below) so repo-state reads/writes anchor back to the live tree, and
re-run `codex plugin remove/add` after editing plugin code.

## Quickstart: Obsidian-only, from zero

No Heptabase needed. Ten minutes to a working paper pipeline:

1. **Install** the plugin into your agent (see Installation) and the Python
   dep: `pip install pyyaml` (figures additionally want `pip install pymupdf`
   and `brew install librsvg`).
2. **Create a vault** in Obsidian (any location; iCloud works but the
   terminal then needs Full Disk Access).
3. **Configure** — copy `config.example.json` to
   `~/.config/research-cards/config.json` and set the essentials:

   ```json
   {
     "backend": "obsidian",
     "agent": "claude",
     "plugin_root": "/path/to/research-cards",
     "profile": { "reader": "你的讀者身分", "field": "你的領域" },
     "obsidian": { "vault": "~/Documents/MyVault",
                    "folders": { "papers": "Papers", "overviews": "Overviews" } }
   }
   ```

4. **First card** — in an agent session, ask for a clip:
   「用 scholar-inbox-clip 把 https://arxiv.org/abs/XXXX.XXXXX 做成卡片」.
   The card lands in `Papers/` with frontmatter properties, a 快速摘要, and
   semantic colorization. (Email ingestion is optional — see Scheduling.)
5. **Grow structure when ready** — once you have a handful of related papers:
   copy `skills/overview/topics/_example/` to
   `~/.config/research-cards/topics/<your-topic>/`, create a hub note that
   has a `## 子卡與閱讀順序` section listing the comparison card(s) as
   `[[wikilinks]]` and carries your Tasks value in its `tasks` frontmatter
   (topology fails fast when these are missing — the hub format is an API),
   register it under `obsidian.graph.hubs`, then run
   `python3 /path/to/research-cards/skills/_shared/topology.py refresh
   <your-topic>`. The `overview` / `overview-daodu` /
   `overview-graph` skills now maintain that topic; the knowledge map lives
   in an Obsidian Canvas you arrange yourself.

Everything above also applies to `backend: heptabase` — swap step 2–3 for the
Heptabase desktop app + the `heptabase.*` config ids; `both` adds the
bidirectional `obsidian-sync`.

## Configuration

Copy `config.example.json` to `~/.config/research-cards/config.json` and fill
it in. Key groups (all documented inline in the example):

- **`backend`**: `heptabase` | `obsidian` | `both`. In `both`, Heptabase is
  canonical and `obsidian-sync` mirrors to the vault with block-level
  write-back; in `obsidian`, cards are plain `.md` + frontmatter and no
  Heptabase app is needed.
- **`agent`**: `claude` | `codex` — which CLI unattended scripts use for text
  generation (`claude --print` / `codex exec`).
- **`plugin_root`**: live plugin path; required when Codex drives the plugin
  (static cache anchoring).
- **`email`**: Mail.app `account` + `mailbox` for the clip pipeline.
- **Topics are user data**: overview topic configs live in
  `~/.config/research-cards/topics/<key>/` (template:
  `skills/overview/topics/_example/`); `aliases.json` and `projects.json` sit
  beside them. The plugin repo ships no personal taxonomy.
- **`gold_cards`**: optional style-reference cards for card-rewrite /
  overview-daodu (embedded specs apply when unset).
- **`heptabase`**: workspace id, per-collection tag ids/names/filters,
  property UUIDs (`props`), corpus `scan_tags`, and `graph` ids (root index
  card, knowledge-map whiteboard, Level property, topology `hubs`). Find ids
  with `heptabase tag list` / `heptabase tag properties <tagId>`.
- **`obsidian`**: vault path, per-collection folders, and `graph`
  (knowledge-map `.canvas`, root card, topology `hubs` as `Folder/Name` ids).

Note: Heptabase ids come EXCLUSIVELY from your config — heptabase-mode
commands exit with the exact missing key when unset.

## Scheduling the clip pipeline (unattended)

`scholar-inbox-clip`'s `run.py` runs headless: it reads the configured
Mail.app mailbox, creates cards, and shells the configured `agent` CLI
(`claude --print` / `codex exec`) for text generation only. Three ways to
schedule it:

- **Agent routines (recommended)** — schedule a recurring prompt in your
  agent (e.g. Claude Code routines): 「執行 scholar-inbox-clip 的排程流程」.
  The agent drives the SKILL.md contract (dedup, Tasks tagging, overview
  routing, figure placement) with judgment — this is the highest-quality
  mode, and what the SKILL.md's routine sections assume.
- **launchd (macOS), script-only** — cheapest, no agent judgment (cards get
  created but Tasks tagging waits for an interactive backfill pass):

  ```xml
  <!-- ~/Library/LaunchAgents/com.you.scholar-clip.plist -->
  <plist version="1.0"><dict>
    <key>Label</key><string>com.you.scholar-clip</string>
    <key>ProgramArguments</key>
    <array><string>/opt/homebrew/bin/python3</string><!-- the SAME interpreter
           you installed pyyaml/pymupdf into (venv path works too) -->
           <string>/path/to/research-cards/skills/scholar-inbox-clip/run.py</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key>
    <string>/tmp/scholar-clip.log</string>
  </dict></plist>
  ```

  Note: unattended `osascript` needs Automation permission granted once to
  the invoking binary — run the script interactively first WITH THE SAME
  interpreter to trigger (and approve) the Mail.app prompts.
- **cron + codex** — same script with `"agent": "codex"` in the config, or a
  `codex exec` prompt as the routine body.

State/dedup lives in `~/.config/research-cards/scholar_inbox_state.json`
(pre-existing installs with `~/.claude/scholar_inbox_state.json` keep using
that legacy path). Reruns of PROCESSED emails are cheap no-ops, so any
scheduler cadence is safe — but note the dedup key is recorded even when a
downstream step fails, so verify the pipeline end-to-end interactively
before scheduling it; a failed first run can otherwise mark emails as
processed without cards.

## Integrations (optional)

- **hung-yi-lee teaching skill** — two distinct relationships:
  1. *Style*: the 導讀/rewrite writing rules are EMBEDDED in the SKILL.mds;
     no dependency.
  2. *Runtime (Direction A)*: `overview-graph` can export your overview cards
     as an external corpus into the skill's knowledge graph
     (`export_hungyi_corpus.py` → `hungyi_kb.py graph build --external`).
     This requires the skill installed; declare its location via
     `integrations.hung_yi_lee.skill_path` in the config. Tested against
     `github.com/SungFeng-Huang/hung-yi-lee-skill` (branch
     `local/conda-env-integration`) with its conda env installed. Absent →
     the export operation is unavailable; everything else works.

     The skill is NOT vendored into this plugin (it has its own upstream and
     PR flow, and Codex runs plugins from a static cache copy that could not
     carry a nested repo). Install it side-by-side instead — upstream
     `voidful/hung-yi-lee-skill` is MIT licensed (stated at the end of its
     README):

     ```bash
     # upstream, or your own fork
     git clone https://github.com/voidful/hung-yi-lee-skill ~/.claude/skills/hung-yi-lee
     pip install -r ~/.claude/skills/hung-yi-lee/requirements.txt
     ```

     then point the plugin at it in `~/.config/research-cards/config.json`:

     ```json
     "integrations": { "hung_yi_lee": { "skill_path": "~/.claude/skills/hung-yi-lee" } }
     ```

## Backend / agent support matrix

Every skill works on `heptabase`/`both`. On `obsidian`: all skills work, with
the knowledge map materialized as an Obsidian JSON Canvas instead of a
whiteboard. Both Claude Code and Codex can drive every skill; each SKILL.md
carries an "Agent（claude / codex）" note listing the (few) Claude-only MCP
conveniences and their Codex fallbacks.

## The markdown dialect (obsidian mode & sync)

Cards round-trip through a documented markdown dialect: text colors as
`<span style="color:…">`, underline as `<u>`, Heptabase toggles as `- ⏵ `
bullet prefixes, same-card anchors as Obsidian block references (`[[#^id]]`),
card links as `[[wikilinks]]`. Anything the dialect cannot represent losslessly
(highlight embeds, complex tables, custom image geometry) is **reported as a
conflict instead of written back** — see `skills/obsidian-sync/SKILL.md`.
