# research-cards — Learn Research the Hung-yi Lee Way 📚

**English** | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

Turn your paper feed into a **research knowledge base that teaches you**: every card reads like a Hung-yi Lee-style lecture —
it first tells you "why you should read this" and which prerequisites you need, then explains the method with a WHY-driven narrative,
and finally places the paper in the context of topic comparison cards and the knowledge map, so you always know where every paper sits in the field.

> This project pays tribute to the teaching style of [Prof. Hung-yi Lee](https://speech.ee.ntu.edu.tw/~hylee/)
> and is not affiliated with him. It shares its teaching soul with the
> [hung-yi-lee skill](https://github.com/voidful/hung-yi-lee-skill)
> — installing both together is recommended (see [Integrations](#integrations-optional)).

Works out of the box on a **plain folder of .md files** — no note app
required. **Obsidian** and **Heptabase** are optional upgrades (nicer
reading, and full bidirectional sync respectively); **Claude Code** and
**Codex** both drive it, in any combination. It helps you with:

- **Clipping**: digest emails (or a single arxiv link) → teaching-style cards — quick-summary
  toggle, semantic colorization, figures, and property fields, all in one pass.
- **Organizing**: papers auto-route by the Tasks taxonomy into each topic's **comparison overview card**,
  complete with a narrative guided intro (導讀), topic hubs, lateral links, and a visual knowledge map.
- **Syncing**: the whole card library syncs both ways between Heptabase ↔ Obsidian — block-level write-back,
  lossy edits raise conflicts instead of writing garbage, and a conflict ledger keeps everything traceable.
- **Research journal**: log progress into the matching project card from any project repo's session,
  then consolidate it into a full paper-grade account — hitting the size cap automatically opens a
  continuation chain, so details are never condensed because of the 100K limit.
- **References**: export the official BibTeX of every paper a card links to, in one shot.

---

**Table of Contents** ·
[Skills Overview](#skills-overview) ·
[Installation](#installation) ·
[Configuration](#configuration) ·
[Quick Start (plain .md)](#quick-start-a--a-plain-folder-of-md-files-no-note-app-needed) ·
[Quick Start (note app)](#quick-start-b--using-a-note-app) ·
[Daily Usage](#daily-usage) ·
[Research Experiment Campaign](#research-experiment-campaign) ·
[Unattended Scheduling](#unattended-scheduling-clipping-pipeline) ·
[Integrations](#integrations-optional) ·
[Troubleshooting](#troubleshooting) ·
[License](#license)

> 📖 **Usage-scenario guides live in the [Wiki](https://github.com/SungFeng-Huang/research-cards/wiki)**:
> [Daily Research Pipeline](https://github.com/SungFeng-Huang/research-cards/wiki/Daily-Research-Pipeline) (which skill to use at which moment, and how to chain them) ·
> [Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration) (division of labor and mix-and-match recipes with ARS / experiment-agent) ·
> [the full Campaign handbook](https://github.com/SungFeng-Huang/research-cards/wiki/Research-Campaign) ·
> [Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends) (Heptabase / Obsidian setup and the bidirectional sync).
> The README covers installation, configuration, and the command reference; for "which scenario calls for what", see the wiki.

## Skills Overview

**📥 Paper Clipping** — the feed comes in, teaching cards come out

| Skill | What it does |
|---|---|
| `scholar-inbox-clip` | digest emails / URLs → teaching cards (properties, figures, journal logging, overview routing) |
| `card-rewrite` | Rewrite an existing card into the full teaching format (one-liner / why you should read it / prerequisites / WHY-driven narrative / bilingual terms) |

**🗺️ Topic Overviews & Knowledge Graph** — single cards grow into a map of the field

| Skill | What it does |
|---|---|
| `overview` | Maintain each topic's comparison overview card: per-paper sections, dimension comparison table, coverage checks, arxiv-ID ordering |
| `overview-daodu` | Insert / refresh the narrative guided intro at the top of an overview card (idempotent) |
| `overview-graph` | Graph structure: topic hubs, lateral ↔/→ links, the knowledge map (Heptabase whiteboard / Obsidian JSON Canvas), consistency audits. **Also serves the project direction**: Operation 5 uses the knowledge graph to run research-gap analysis for project cards |

**🧪 Research Projects** — your own research is a card, too

| Skill | What it does |
|---|---|
| `project-card-log` | From a session in a project repo (local or remote), resolve this project's card and append dated, code-grounded progress — append-only. When the card hits the size cap it **automatically opens a continuation chain** (lossless; never condenses just to squeeze under 100K) |
| `project-card-merge` | The other half: consolidate the accumulated progress blocks into one paper-grade card (full-edit side). **Chain-aware**: reads the whole continuation chain together, spills into a new chain by H2 section when the merged result exceeds the cap, and auto-recycles orphaned continuation cards |
| `research-campaign` | Mission-brief format + bookkeeping conventions for autonomous experiment campaigns: MISSION.md lives in the repo, queue/ledger resume across interruptions, significance-gated measurement discipline, and progress flows back to the project card automatically. Optional showcase layer: report page + **training-log curve dashboard** auto-deployed to GitHub/GitLab Pages |

**✍️ Paper Writing** — harvest the knowledge base when writing papers

| Skill | What it does |
|---|---|
| `bib-export` | Anchor on any card (overview card or project card alike) and export official BibTeX for the papers it links to — never fabricates; anything unresolved becomes a `% TODO` comment |

**🔁 Sync Infrastructure**

| Skill | What it does |
|---|---|
| `note-sync` | **One entry point for the whole sync chain** — runs every applicable segment per `backends` (first = canonical), converges HackMD write-backs onto Heptabase in the same run, aggregates all conflicts; `--mode obsidian\|hackmd` runs one segment |

**⚙️ Setup**

| Skill | What it does |
|---|---|
| `setup` | Interactive config wizard: create / inspect / adjust `config.json` against the example's inline docs, with a health-check verifier (`check_config.py`) |

Switch ownership: config `features.study` covers clipping + overviews + knowledge graph; `features.project`
covers the three research-project skills (log / merge / campaign); `bib-export` and `note-sync` ignore the direction switches (the former
follows whichever anchor card you give it, the latter follows the backend).

## Installation

### Requirements

| To use | You need |
|---|---|
| Basics | Python 3.10+, `pip install pyyaml`, an agent CLI (**Claude Code** or **Codex**) |
| `backends` incl. `"heptabase"` | macOS + the **Heptabase desktop app** + the `heptabase` CLI **≥ 0.4.0** (local API `127.0.0.1:21210`) |
| `backends` incl. `"local"` (the default) | **Just a folder of .md files** — any directory works; opening it as an **Obsidian vault** is optional polish (iCloud vaults need **Full Disk Access**) |
| HackMD mirroring (`note-sync --mode hackmd`) | `npm install -g @hackmd/hackmd-cli` + one `hackmd-cli login` (API token from hackmd.io → Settings → API; never stored in the plugin config) |
| Email clipping (`scholar-inbox-clip`) | macOS **Mail.app** + a dedicated mailbox folder (use a Mail rule to route digests into it) + `osascript` automation permission |
| Card figures | `pip install pymupdf` (PDF pages) + `brew install librsvg` (SVG) |
| Claude Code extras | **alphaXiv MCP** (content grounding for clipping / rewriting) and **heptabase MCP** (resolving highlight embeds during sync). Optional — Codex falls back to built-in HTTP fetching, and highlights are instead listed for you to patch manually |
| Optional integration skills | **hung-yi-lee** (runtime integration of the teaching style) and **alchemist-playbook** (hyperparameter-citation discipline for campaigns) — installation and absence semantics in [Integrations](#integrations-optional) |

### Claude Code

Install straight from GitHub:

```
/plugin marketplace add SungFeng-Huang/research-cards
/plugin install research-cards@research-cards
```

Or clone and symlink the repo into your skills directory (e.g.
`~/.claude/skills/research-cards`); `.claude-plugin/plugin.json` makes it load as a
plugin. Either way, skills appear as `research-cards:<skill>`.

### Codex

Codex installs plugins from a "marketplace directory". Create one for your clone (one-time):

```bash
mkdir -p ~/plugins/.agents/plugins
git clone https://github.com/SungFeng-Huang/research-cards ~/plugins/research-cards
cat > ~/plugins/.agents/plugins/marketplace.json <<'EOF'
{
  "name": "my-plugins",
  "plugins": [
    { "name": "research-cards",
      "source": { "source": "local", "path": "./research-cards" },
      "policy": { "installation": "AVAILABLE" } }
  ]
}
EOF
codex plugin marketplace add ~/plugins
codex plugin add research-cards@my-plugins
```

Codex executes a **static cached copy**: set `plugin_root` in your config (state reads/writes
get anchored back to the live repo), and after a plugin update remember to refresh with `codex plugin remove` + `add`.

## Configuration

The fastest path: say **"set up research-cards for me"** — the `setup` skill
interviews you against `config.example.json`'s inline docs, writes a minimal
config (plain-.md mode needs just `local.vault`), and verifies it with
`skills/setup/check_config.py` (which also reports **upgrade hints** — newer
settings your config hasn't opted into). Adjusting later works the same way:
"switch the output language", "hook up Heptabase" — it edits only what you
name, then re-verifies.

The full field map and design principles (ids are never guessed; topics are
user data) live in the wiki: [Configuration](https://github.com/SungFeng-Huang/research-cards/wiki/Configuration).

## Quick Start A — a Plain Folder of .md Files (no note app needed)

This is the **basic default**: all you need is a directory. Cards are plain
Markdown files with YAML frontmatter — readable in any editor, greppable,
versionable with git. No note app required; a paper pipeline up and running
in ten minutes:

1. **Install** the plugin (see above) + `pip install pyyaml`
   (add `pymupdf` and `librsvg` if you want figures).
2. **Create a folder** (anywhere on disk; if you put it in iCloud, the
   terminal needs Full Disk Access).
3. **Configure** — minimal `~/.config/research-cards/config.json`
   (`backends` defaults to `["local"]` — this plain-.md mode — so you can omit it):

   ```json
   {
     "agent": "claude",
     "plugin_root": "/path/to/research-cards",
     "profile": { "reader": "your reader identity", "field": "your field" },
     "local": { "vault": "~/Documents/ResearchCards",
                   "folders": { "papers": "Papers", "overviews": "Overviews" } }
   }
   ```

   (The `vault` is just your folder; the section also answers to its
   pre-rename name `obsidian`.)
4. **Your first card** — in an agent session, say:
   "Use scholar-inbox-clip to make a card from https://arxiv.org/abs/XXXX.XXXXX".
   The card appears under `Papers/` with frontmatter properties, a quick summary, and semantic colorization.
   (Email clipping is optional — see [Scheduling](#unattended-scheduling-clipping-pipeline).)
5. **Once a few related papers pile up, grow the structure**:
   1. Copy `skills/overview/topics/_example/` to
      `~/.config/research-cards/topics/<your-topic>/` and fill in `config.py`.
   2. Create a **hub note**: it must contain a `## 子卡與閱讀順序` ("child cards & reading order") section
      listing the comparison cards as `[[wikilinks]]`, and its frontmatter `tasks` must carry your Tasks
      values — the hub format is an API; topology errors out immediately if any piece is missing.
   3. Register the hub in config `local.graph.hubs`, then:

      ```bash
      python3 /path/to/research-cards/skills/_shared/topology.py refresh <your-topic>
      ```

   From then on `overview` / `overview-daodu` / `overview-graph` maintain this topic.

## Quick Start B — Using a Note App

The same folder — and the same pipeline — pairs with a note app at any
time, before or after Quick Start A:

- **Obsidian**: open the folder as a vault — clickable `[[wikilinks]]`, a
  Properties UI, and the knowledge map rendered as a real canvas. Zero
  migration, zero config changes.
- **Heptabase**: author in Heptabase (`backends: ["heptabase"]`), or run
  `backends: ["heptabase", "local"]` for the full block-level **bidirectional sync** between
  Heptabase and your folder — write-back, adoption of hand-made .md files,
  a conflict ledger, three-way property sync.
- **HackMD** (publishing-first): `note-sync`'s hackmd segment mirrors selected collections
  as HackMD notes with real note-to-note links — built for sharing overviews
  with collaborators. Opt-in `write_back` makes it two-way for notes only
  you can edit on HackMD (shared-writable notes never write back).

Setup for either app, and the complete sync mechanics of the two-store mode (`backends: ["heptabase", "local"]`), live in
the wiki: [Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends).

## Daily Usage

For scenario-based walkthroughs of each moment (morning intake, paper reading, weekly maintenance,
project phase, writing phase), see the wiki: [Daily Research Pipeline](https://github.com/SungFeng-Huang/research-cards/wiki/Daily-Research-Pipeline).
This section is the command reference. Day to day you **invoke skills**, not commands:

- **Natural language (recommended)** — just tell the agent what you want; it picks the right skill and
  executes the SKILL.md contract. Every subsection below gives example phrasings.
- **Naming the skill** — in Claude Code use the slash form: `/research-cards:<skill>` (e.g.
  `/research-cards:note-sync`); in Codex just name the skill in your message.
- **Low-level CLI** — only needed for unattended scheduling or debugging, tucked into each subsection's
  "Low-level commands" fold (the agent normally runs these for you anyway).

### 📥 Clipping

| You say | How to do it with an explicit skill |
|---|---|
| "Make a card from https://arxiv.org/abs/XXXX.XXXXX" | `/research-cards:scholar-inbox-clip https://arxiv.org/abs/XXXX.XXXXX` |
| "Scan the scholar inbox mailbox" — read emails, dedupe, create cards, set Tasks, route to overview cards | `/research-cards:scholar-inbox-clip` |
| "Rewrite <that card> into the teaching format" — structural upgrade, facts untouched | `/research-cards:card-rewrite <card title>` |

<details><summary>Low-level commands</summary>

```bash
python3 skills/scholar-inbox-clip/run.py    # headless scheduled mode (see the Scheduling section)
```
</details>

### 🗺️ Overviews & Knowledge Graph

| You say | How to do it with an explicit skill |
|---|---|
| "Add this new paper to the <topic> overview card" | `/research-cards:overview <topic> add <paper>` |
| "How's coverage for <topic>? Which papers aren't in the comparison card yet?" | `/research-cards:overview <topic> status` |
| "Refresh the guided intro on this overview card" | `/research-cards:overview-daodu <overview card title>` |
| "Add a lateral link between tokenizer and spoken" | `/research-cards:overview-graph add lateral link tokenizer ↔ spoken` |
| "Run a graph audit" — after structural changes, check hub / lateral-link / knowledge-map consistency | `/research-cards:overview-graph audit` |
| "Mirror <that whiteboard> into an Obsidian Canvas" — one-way overwrite of the actual layout (coordinates / sections / connections + automatic mention edges); reads the app's local database by default (live, works while the app is open), with backup files as the fallback | `/research-cards:overview-graph mirror` |

After structural changes (new hub, re-split, moved cards) the agent runs a topology refresh — that is
the data source for overview routing and cannot be skipped.

<details><summary>Low-level commands</summary>

```bash
cd skills/overview
python3 sync_overview.py <topic> status   # coverage diff → which papers are MISSING
python3 sync_overview.py <topic> sort     # re-sort the list by arxiv ID
python3 ../_shared/topology.py refresh    # all topics; or refresh <topic>
```
</details>

### 🧪 Research Projects

| You say | How to do it with an explicit skill |
|---|---|
| "Log today's progress to the project card" — just say it in a session inside the project repo; the agent resolves the matching card (marker → registry) and, if there is none, asks whether to create one | `/research-cards:project-card-log` (inside the project repo, no arguments) |
| "Create a project card for this project" — card + skeleton + tagging + pinned mapping in one step | `/research-cards:project-card-log create "My Project"` |
| "Consolidate the project card's progress to paper grade" — fold in the accumulated progress blocks | `/research-cards:project-card-merge <project name>` |
| "Use the knowledge graph to run a research-gap analysis on my project card" — hold the field map against the project card to find gaps nobody has answered yet (Operation 5) | `/research-cards:overview-graph gap <project card>` |
| "Set up a research experiment campaign for this repo" — repo readiness check → interactive intake → generate the MISSION.md brief + queue/ledger | `/research-cards:research-campaign init` |
| "Continue the campaign" / "How's the campaign going" | `/research-cards:research-campaign` (inside that repo's session) / `… status` |

Where the mapping lives: inside a git repo it's the `.heptabase-card` marker at the git root;
for the "project root isn't a git repo, repos sit one level below" layout it goes into the registry
`~/.config/research-cards/projects.json` (every repo underneath resolves to the same card).

**What happens when a card fills up (Heptabase's 100K cap)**: nothing on your side — once an append
hits the threshold, a "continuation card" opens automatically and writing continues there (the parent
card keeps a link at its tail, clickable inside Heptabase); at merge time the whole chain is gathered
together, and if the result exceeds the cap it spills losslessly into a new chain by H2 section.
Paper-grade detail is never condensed to fit into a single card.

<details><summary>Low-level commands</summary>

```bash
python3 skills/project-card-log/resolve_card.py                      # this repo ↔ which card
python3 skills/project-card-log/create_project_card.py --title "My Project"
#   for a monorepo sub-project, pass --marker-dir "$(pwd)"
```
</details>

### ✍️ Paper Writing

| You say | How to do it with an explicit skill |
|---|---|
| "Export BibTeX for <this overview card>" | `/research-cards:bib-export <card title>` |
| "Export the references of the whole topic under <hub card>" (hub → child overview cards → papers) | `/research-cards:bib-export <hub card> --depth 2` |

Resolution chain: Semantic Scholar → arxiv `/bibtex` → ACL Anthology → OpenReview.
Anything unresolved becomes a `% TODO` comment — entries are never fabricated, so you can paste
straight into your `.bib` with confidence.

<details><summary>Low-level commands</summary>

```bash
cd skills/bib-export
python3 bib_export.py <card-id>                  # papers this card links to directly
python3 bib_export.py <hub-card-id> --depth 2    # hub → child overview cards → papers
python3 bib_export.py <card-id> -o refs.bib      # '-' = stdout
```
</details>

### 🔁 Sync

| You say | How to do it with an explicit skill |
|---|---|
| "Sync everything" | `/research-cards:note-sync` |
| "Sync just the Heptabase↔vault segment" | `/research-cards:note-sync --mode obsidian` |
| "Dry-run first to see which cards would change" | `/research-cards:note-sync --dry-run` |
| "Any conflicts? Walk me through Sync Conflicts" | `/research-cards:note-sync`（the aggregate report lists every segment's conflicts） |

Mechanism details in the wiki's [Note App Backends](https://github.com/SungFeng-Huang/research-cards/wiki/Note-App-Backends); after a run the agent reads the JSON report and lays the
conflicts and follow-ups out for you.

## Research Experiment Campaign

`research-campaign` standardizes "a long-running autonomous experiment campaign for one project":
the mission brief (MISSION.md) lives inside the project, the experiment ladder and results ledger
resume across interruptions, measurement discipline is enforced as a hard gate, and progress flows
back to the project card automatically. It is **not a training executor** — how training runs is
whatever your MISSION says; the skill owns the format, the bookkeeping, and the interface to the
knowledge base.

The full closed loop (this is the narrative unique to this plugin):

```
Knowledge base  ──Op5 gap analysis──▶  MISSION experiment design
   ▲                                        │
   │                                （campaign execution）
   └──project-card-log write-back──  ledger results
        （merge consolidation → bib-export gathers references → paper）
```

Entry points for the four phases (the full operating manual — readiness checklist, layout choices,
the complete measurement-discipline text, showcase / training-progress dashboard setup — is in the
wiki: [Research Campaign](https://github.com/SungFeng-Huang/research-cards/wiki/Research-Campaign)):

| Phase | You say | Or run |
|---|---|---|
| **Setup** | "Set up a research experiment campaign for this repo" — readiness check → recon-based prefill → one batched Q&A → MISSION draft approval | `campaign.py init --repo <project> [--git]` |
| **Run** | "Continue the campaign" — execute per MISSION + measurement discipline + ledger bookkeeping + card write-back | (inside the project session) |
| **Status** | "How's the campaign going" — what's still missing before the success gate | `campaign.py status --dir runs/auto_research` |
| **Showcase** (optional) | Auto-updating public report page + training-progress dashboard (GitHub / GitLab Pages) | `campaign.py pages-setup` + `report` / `progress` |

The core discipline in one sentence: **any "win" requires a paired-delta 95% CI that excludes 0,
one change at a time, one ledger line per eval (enforced by the schema tool), and hyperparameter
decisions that cite sourced recommendations**
([alchemist-playbook](#integrations-optional)). For a lightweight alternative for one-off experiments
(no campaign), see the wiki's [Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration)
(the experiment-agent section).

## Unattended Scheduling (Clipping Pipeline)

`scholar-inbox-clip/run.py` can run headless: it reads the configured Mail.app mailbox, creates
cards, and only calls the configured `agent` CLI for text generation. Three modes:

- **Agent routine (recommended)** — schedule a recurring prompt in your agent (e.g. Claude
  Code routines): "run the scholar-inbox-clip scheduled flow". The agent executes the SKILL.md
  contract with judgment (dedupe, Tasks tagging, overview routing, figure placement) — highest quality.
- **launchd (macOS), script only** — cheapest; cards get created, but Tasks tagging and other
  interactive steps are backfilled later:

  ```xml
  <!-- ~/Library/LaunchAgents/com.you.scholar-clip.plist -->
  <plist version="1.0"><dict>
    <key>Label</key><string>com.you.scholar-clip</string>
    <key>ProgramArguments</key>
    <array><string>/opt/homebrew/bin/python3</string><!-- must be the same interpreter
           you installed pyyaml/pymupdf into (a venv path works too) -->
           <string>/path/to/research-cards/skills/scholar-inbox-clip/run.py</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key><string>/tmp/scholar-clip.log</string>
  </dict></plist>
  ```

- **cron + codex** — the same script with config `"agent": "codex"`, or a `codex exec` prompt used
  directly as the routine body.

Caveats:

- Unattended `osascript` requires that **the exact executable launching it** has been granted
  automation permission once — run interactively with the same interpreter first and click through
  Mail.app's authorization prompt.
- State / dedupe live in `~/.config/research-cards/scholar_inbox_state.json`. Re-running processed
  emails is a cheap no-op, so any scheduling density is safe — but **the dedupe key is also recorded
  when a downstream step fails**, so run the whole pipeline through interactively before scheduling;
  otherwise a failed first run marks emails as processed with no cards to show for it.
- Digest sources: **Scholar Inbox** (scores and links both parsed) and **HuggingFace
  Daily Papers** (arxiv IDs taken straight from the links; since the list isn't personalized,
  entries must first pass the `email.hf_min_upvotes` upvote threshold + a field-relevance filter
  based on config `profile.field` — if the agent judges nothing relevant, the whole email is
  skipped) are fully supported; any other digest carrying arxiv/alphaXiv links can be extracted too.
  Multiple sources share the same mailbox folder and are dispatched automatically per email.

## Integrations (Optional)

**Academic Research Skills (ARS) + experiment-agent (the research-output line)** —
research-cards owns the **long-lived knowledge base**; [Imbad0202](https://github.com/Imbad0202)'s
[ARS](https://github.com/Imbad0202/academic-research-skills) (a single-paper pipeline of research →
write → review → revise, with a
[Codex edition](https://github.com/Imbad0202/academic-research-skills-codex)) and
[experiment-agent](https://github.com/Imbad0202/experiment-agent) (experiment
execution + monitoring + statistical interpretation + reproducibility verification) own the
**single manuscript and the single experiment** — those two share an author and integrate natively
with each other, and have no affiliation with this project. The three are mutually independent
but mix deeply: clip deep-research findings back into the card library, feed `bib-export` /
overview cards / project ledgers into the ARS writing line, and use experiment-agent's validate as
a second pair of eyes on the campaign ledger. The division-of-labor matrix, how to choose where
they overlap, and four mixing recipes are in the wiki:
[Ecosystem Integration](https://github.com/SungFeng-Huang/research-cards/wiki/Ecosystem-Integration).
(Both are licensed CC-BY-NC-4.0; install per their own READMEs.)

**alchemist-playbook (the training-recipe advisor)** — the hyperparameter-discipline partner of
`research-campaign`: the campaign contract requires every hyperparameter / schedule decision to
cite a sourced recommendation (the ledger's `playbook_rules_cited` field), and alchemist-playbook
was born for exactly that — a recipe advisor distilled from public training records
(LLaMA/OLMo/DeepSeek-V3/Whisper/wav2vec 2.0/HuBERT…), with every number carrying a
`[config]`/`[paper]`/`[reported]` confidence tag.
Install side-by-side (the skill is a subfolder of the repo):

```bash
git clone https://github.com/voidful/AlchemistPlaybook ~/AlchemistPlaybook
ln -s ~/AlchemistPlaybook/alchemist-playbook ~/.claude/skills/alchemist-playbook
# on the Codex side, link into ~/.agents/skills/ the same way
```

Not installed → campaigns keep working, and the hyperparameter-citation discipline degrades to
"other sourced recommendations" (annotate the source yourself); the MISSION template's REQUIRED
READING recommends keeping this one on hand.

**hung-yi-lee teaching skill** — the spiritual origin of this plugin, related on two levels:

1. **Style**: the writing rules for guided intros / rewrites are already embedded in each
   SKILL.md — you get the full teaching style without installing it.
2. **Runtime**: `overview-graph` can export your overview cards as an external corpus feeding that
   skill's knowledge graph (`export_hungyi_corpus.py` →
   `hungyi_kb.py graph build --external`), so Hung-yi Lee-style teaching Q&A can cite your own card
   library directly.

That skill is not embedded in this plugin (it has its own upstream and PR flow, and Codex's static
plugin cache can't load nested repos). Install it side-by-side — **the `local/conda-env-integration`
branch of this project author's fork is recommended**: the extensions the runtime integration needs
(external corpus, source-attribution tags, etc.) live on that branch and haven't all landed upstream
yet; this plugin is also tested against it:

```bash
git clone -b local/conda-env-integration \
  https://github.com/SungFeng-Huang/hung-yi-lee-skill ~/.claude/skills/hung-yi-lee
pip install -r ~/.claude/skills/hung-yi-lee/requirements.txt
```

(If you only want the teaching style and don't need the export integration, installing the upstream
`voidful/hung-yi-lee-skill` works too — MIT-licensed, stated at the end of its README.)

Then point your config at it:

```json
"integrations": { "hung_yi_lee": { "skill_path": "~/.claude/skills/hung-yi-lee" } }
```

Not installed → the export feature is unavailable; everything else works as usual.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| A heptabase-mode command exits naming some config key | That id is unfilled — the message gives the exact key; look it up with `heptabase tag list` / `heptabase tag properties <tagId>` |
| `Operation not permitted` when touching an iCloud vault | Grant the terminal (or the scheduler's interpreter) **Full Disk Access** |
| A scheduled run can't read Mail | Automation permission follows "the launching executable" — run once interactively with the same interpreter and approve the prompt |
| Codex runs an old plugin version | It executes a static cached copy — refresh with `codex plugin remove` + `add`, and confirm `plugin_root` points at your live clone |
| `note-sync` skips the obsidian segment | It only applies with both stores in `backends: ["heptabase", "local"]` — with a single store there is nothing to mirror |
| Sync reports a conflict | Feature, not a bug: that card has a lossy edit or divergence on both sides. Check the block and reason in the report / `Sync Conflicts.md`, fix the side you want to keep, and rerun |

## License

MIT — see [LICENSE](LICENSE).
