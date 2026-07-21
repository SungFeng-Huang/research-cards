# Changelog

## 0.41.0 — project canvas: the git graph of a research project

- New `project_canvas.py` (project-card-log): one JSON Canvas per project
  chain, laid out like a git graph — the entry card (the chain's
  README/HEAD, purple) on top, log cards (the commits) newest-first down
  a vertical trunk with edges pointing in the direction of time, and
  continuation children as a gray side row. Colors carry the distillation
  state straight from the timeline marks: 📎 orange = not yet distilled,
  📗 green = merged into the body. Mirrored cards are clickable file
  nodes; unmirrored ones degrade to text nodes with the summary and card
  id. Node ids are deterministic so regeneration doesn't flicker.
  `--card <entry>` / `--all` (hub-listed projects) / `--dry-run`;
  the canvas is a generated view — rebuilt each run, not hand-arranged.
  Wired into the log and merge SKILL flows (refresh after each).

## 0.40.0 — log cards get their own tag family (`<projects-tag>/progress`)

- log-as-card cards are progress records, not project cards — they now
  arrive tagged with the projects tag's `progress` CHILD tag
  (`project/progress` by default; config `log_tag_name` overrides, set it
  equal to `tag_name` to restore the 0.37–0.39 behaviour) instead of the
  projects tag itself, so the project-tag scan stays entries+continuations
  only. `tag add` by name matches an existing nested tag (verified live).
- Transport.create grows a `tag=` override; set_project_relation grows a
  `tag=` scope (whose schema to search). The log card's entry-pointer
  relation is looked up in the LOG tag's own schema: it ships empty →
  quiet False; add a relation property named like `relation_property`
  (default `project`) to that tag in-app and log cards start carrying
  their "belongs to <entry>" edge with no code change (`log_related`).
- Output gains `log_tag`; untagged-log recovery notes quote the log tag.

||||||| parent of 2d5315d (release: 0.39.0 — project canvas（專案的 git graph 視圖）)
## 0.39.0 — spill children carry their own provenance (tag + entry relation)

- Continuation children and log cards created over the hb bridge are now
  TAGGED at birth: Transport.create wires the bridge's new `hb tag-add`
  verb (heptabase-ssh-bridge 484db04+; idempotent, offline it queues and
  the drain replays). An older client without the verb degrades exactly
  like before — untagged + flagged in the output `note`.
- Every card transport now best-effort points the tag's RELATION property
  back at the chain's entry card (`related` / `log_related` in the output):
  append-side spill children, log-as-card cards, and merge-side
  finalize_chain children all carry a machine-readable "belongs to
  <entry>" edge, so tag-level scans (`tag cards --include-properties`)
  can tell entries from continuations/logs without walking chains.
  Convention: the relation property is named like the tag itself
  (config `relation_property` overrides); schemas without such a
  property skip quietly. Write format note: `card set-property` expects
  a plain ID array (`["<entry-id>"]`), not the `{id,type}` objects reads
  return.
- New pure helpers with self-test + unit coverage: find_relation_pid
  (schema lookup from `card properties` output), relation_property_name
  (config plumbing), Transport.set_project_relation (both transports,
  never fails the caller); tests/test_project_card_overflow.py covers
  the tag-add degradation and the spill wiring end-to-end.

## 0.38.0 — merge learns the log timeline (permanent link record)

- project-card-merge now understands log-as-card chains: `scan` collects
  📎 lines (log cards not yet distilled — they flag needs_merge, including
  ones parked on orphan children) and 📗 lines (already distilled). A
  merge distills each pending log card's content into the body under the
  existing hard rules, then rewrites its line as 📗 under a permanent
  `📜 log 時間線` section — the link itself is NEVER lost (think of git
  history surviving a README update), and log cards are never trashed.
  The 📎→📗 mark flip is exactly how you tell fresh appends from
  already-distilled ones; new 📎 lines land after the timeline section
  and get collected next round.
- merge_lib gains loglink_of (parses both a sealed card-node line and the
  bridge's plain-text literal), scan_loglinks, and loglink_node /
  timeline_section builders that always emit REAL card nodes; cleanup's
  emit() rebuilds timeline lines with card nodes too, and the timeline is
  an unconditional KEEP for cleanup (history is not the thing you rebase
  away).

## 0.37.0 — log-as-card: the project chain becomes a readable timeline

- project-card-log's default flow changes shape: every log event now
  becomes its OWN self-contained card (background context, what was done,
  results with explained metrics, what it means, decisions pending — and a
  hard no-unexplained-abbreviations rule), while the project chain only
  gains one human-readable timeline line: 📎 date [[card]] one-sentence
  summary. The chain reads as a project timeline for handoff (to your
  future self, across machines, to the paper side); distilling it into
  the card body remains project-card-merge's job.
- Mechanics: `append_card.py --log-title/--log-summary`; the timeline
  line is a top-level paragraph the seal pass rebuilds into a real card
  node (local CLI seals immediately; the bridge degrades to a
  repair_chain --seal note, which now also seals timeline lines). The
  chain is walked BEFORE the card is created (a bridge outage never
  orphans a log card), and any post-create failure saves a recovery file
  with the exact repair command. Obsidian keeps its no-cap plain-append
  contract with filename-accurate wikilinks. The old direct-append mode
  stays for small mechanical additions and internal flows.

## 0.36.0 — progress page declutter

- The campaign progress page stays readable at scale (validated on a
  21-run / 123-eval-set campaign that had blown up to an unusable 294KB
  flat dump): the evals bar-chart selector defaults to the last 8 groups
  (not all — dozens of groups meant sub-pixel bars) with a collapsed
  selection table and a live checked-count; run tabs sort by log mtime
  with the newest 6 flat and older runs folded away, button text uses the
  short run name (full name/desc/purpose on hover); the ladder shows
  running rungs flat and folds done/pending (goal/note via foldCell) while
  staying self-contained even without a report page; the run-overview and
  job-chain tables fold with row counts. Rendering layer only — the
  payload schema and data files are untouched.

## 0.35.1 — status-summary fallback at rung handover

- campaign report: the current-status box's "nothing running → show the
  newest ledger conclusion" fallback keyed on *all bullets empty*, so a
  pending-next entry suppressed it — during a rung handover (E0 done, E1
  pending) the just-finished rung's conclusion was hidden below the fold.
  The fallback now keys on *no running entries* and renders before next;
  regression test asserts conclusion + next coexist.

## 0.35.0 — campaign report readability overhaul

Diagnosed on the duplex-s2s campaign (75 ledger rows): the report page had
become an unreadable flat dump. Four rendering-layer fixes in
`campaign.py cmd_report` (data schema untouched — pages regenerate from the
same queue/ledger):

- **現況摘要 box**: new summary block at the top — one bullet per running
  rung (title + that rung's latest ledger decision/purpose first-sentence)
  plus the next pending rung; falls back to the newest ledger row when
  nothing is running. Answers "where are we now" without scanning the ledger.
- **Ledger grouped by rung**: the flat N-row table becomes per-rung
  `<details>` groups (running rungs open by default); the summary line
  carries row count, status chip, rung title, and the group's latest
  conclusion. Grouping reuses the ladder-prefix match, relaxed from "next
  char not alphanumeric" to "not a digit" so letter cohorts (E8f-inpipe,
  E9a-launch) attach to their parent rung while E1 still never matches E11.
  Rows matching no rung group under their first `-`-segment. `significant`
  now renders `—` when the field is absent (incident/decision rows) instead
  of a misleading "not significant" chip; long `decision` cells fold.
- **Charts de-sparsified**: threshold raised to ≥3 occurrences (the 75-row
  ledger had 301 numeric keys, 278 of them one-shot → 23 near-empty charts);
  the x axis now only contains the rows that recorded the metric (payload
  ships compacted `series` instead of full-length null-padded arrays — note
  point spacing no longer encodes time). Keys appearing exactly twice render
  as a collapsed 前/後/Δ comparison table instead of a two-point "line".
- **Ladder table**: running rungs sort to the top, done rungs collapse into
  a one-line-conclusion `<details>` list, and long goal/note cells fold
  (a real note had grown past 10K chars, exploding the row). New `planned`
  chip color; `.nowbox`/`details.rung`/`details.fold` styles in
  showcase.css; `p.muted` generalized to `.muted`.

## 0.34.0 — project-card-cleanup

- New skill `project-card-cleanup`: re-scope a project card CHAIN to its
  handoff role (最高指導原則 + 實驗現狀 + 待辦 handoff) against an
  external authority layer (paper draft, .private planning docs, or the
  axis card). Where project-card-merge FOLDS appends into the body,
  cleanup DISTILLS writing-phase appends, SUPERSEDES history pile-ups and
  POINTERIZES content that now lives in the draft — while preserving
  every experiment number, method record, figure and card-link.
  `cleanup_lib` is a thin layer over merge_lib: one-read chain dumps with
  an md5 baseline, a fullwidth-tolerant section extractor, a dump→builder
  emitter whose HARD FILTER drops chain plumbing (sentinels / spill
  headers — narrowed to the real LINK_MARK+card-literal shape), a
  pre-write content inventory, and a lowered-threshold finalize for
  dense rebuilds.

## 0.33.0 — reverse mode: local canonical, Heptabase as a view

- `backends: ["local", "heptabase"]` is unlocked: the .md store is the
  canonical and Heptabase becomes a rebuildable VIEW. Same engine, the
  `canonical` flag (backends[0]) flips the deletion semantics:
  - deleting a canonical .md trashes the Heptabase card (propagation);
  - a card removed on the Heptabase side is unbound (heptabase_id
    stripped) and rebuilt by the next run's adoption — to really delete,
    delete the .md;
  - when both the tag entry AND the canonical .md are gone, the deletion
    signal wins and the card is trashed rather than orphaned.
- Fail-closed inventory guard for reverse mode: a collection folder that
  didn't pre-exist, or lost more than half its tracked files in one run
  (unmounted cloud vault), skips the collection with a loud error instead
  of mass-trashing the view.
- Classic heptabase-canonical behavior is byte-for-byte unchanged.

## 0.32.0 — star topology: local is always the hub

- The sync topology is now formally a STAR: local (the plain-.md data
  floor) is always the hub, and every enabled surface syncs over its own
  local ↔ surface segment. `backends` naming other surfaces without
  `"local"` gets the hub injected implicitly — the store defaults to
  `~/.local/share/research-cards/store` with a folders map derived from
  the configured collections; the user never has to touch it, but
  write-back gains its safe landing zone everywhere and the whole library
  always survives as plain text. Single-surface lists are untouched.
- The engine skill `obsidian-sync` is renamed **`heptabase-sync`** (a
  segment is named after the SURFACE it syncs; the hub needs no name).
  note-sync's segment is `--mode heptabase` with `obsidian` kept as an
  accepted alias. The hackmd segment now always sources from the local
  hub — the crippled direct-Heptabase path (no write-back) is gone;
  `["heptabase", "hackmd"]` configs get full two-way sync via the
  implicit hub.

## 0.31.1 — deletion propagation across the chain

- obsidian segment: a card trashed/untagged on Heptabase now gets its
  vault mirror MOVED into `.trash/` (Obsidian's native, recoverable trash)
  with ledger + pm-cache cleanup — and only when the file's frontmatter
  heptabase_id matches the removed card (a same-titled live card sharing
  the filename is never touched; production hit exactly this).
- hackmd segment: a vanished source (trashed upstream, merged away) gets
  its HackMD note deleted ONLY when the remote content still matches the
  sync ledger exactly; edited notes are surfaced and kept, a 404 cleans
  the ledger. Fail-closed: if the run's source inventory drops below half
  the ledger (unmounted vault, moved folder), the pass is skipped with a
  loud error instead of mass-deleting the mirror.
- Docs: engine invocations across README/wiki now speak note-sync; the
  Note-App-Backends page was restructured (levels 1-3, then one general
  sync-machinery section covering both segments).

## 0.31.0 — note-sync + the "local" config section

- New `note-sync` skill: ONE entry point for the whole note-surface chain
  (Heptabase ↔ vault/local ↔ HackMD). Runs every applicable segment per
  the `backends` list (canonical-outward), re-runs the obsidian segment in
  the same invocation when HackMD write-backs landed in the vault, and
  aggregates all segments' conflicts into one report. A fatal upstream
  segment (dead process / quota abort) stops the chain — downstream never
  publishes from a stale vault; per-card errors stay non-fatal
  (incremental self-healing). `--mode obsidian|hackmd` runs one segment.
  The engines stay in place; obsidian-sync / hackmd-sync SKILL docs point
  here for daily use.
- The local-mode settings section may now be spelled `"local"` (matching
  the backends value); `"obsidian"` keeps working as its pre-rename alias
  — both names bind to the same object, both present is an explicit
  error. config.example.json and all docs now lead with `local`.

## 0.30.2 — HackMD list-API schema drift (folderPaths)

- The list endpoint stopped returning `parentFolderId` in favor of
  `folderPaths` (a list of folder objects; [0] is the direct folder) —
  which silently blinded phase-A adoption and the stray scan, letting a
  resumed first-publication run re-create hundreds of already-existing
  notes instead of adopting them. `_folder_of()` now reads both schema
  generations, with a regression test simulating the newer shape.

## 0.30.1 — seal the continuation back-ref too

- A spill's child card opens with a back-reference to its entry card
  (`母卡：[[card:<entry>]]`) that landed as plain text and was never
  sealed — the chain PARSED fine (the sentinel edge was sealed since
  0.24.2), but the in-app link back to the parent wasn't clickable.
  `seal_backref_paragraphs` now rebuilds it into a real card node by
  splitting the text node (prose around it is kept verbatim); wired into
  the spill's automatic seal (heptabase + hb transports; `hb seal` gains
  an optional third entry-id argument with graceful old-client fallback)
  and into `repair_chain.py --seal`. Guard rails: only a paragraph whose
  `母卡：` marker precedes the literal qualifies, first match only —
  prose quoting `[[card:id]]` is never rewritten.

## 0.30.0 — the backends list

- New config key `backends`: a LIST of note surfaces — the FIRST entry is
  the canonical (authoring) side, the rest are mirrors. `"local"` is the
  new name for plain .md in a folder (no note app required); `"obsidian"`
  is kept as an alias. Append `"hackmd"` to enable the publish mirror.
  Typical values: `["local"]` (default), `["heptabase"]`,
  `["heptabase", "local"]`, plus `"hackmd"` anywhere after the first slot.
- The legacy single-value `backend` key (obsidian|heptabase|both) keeps
  working: load_config() normalizes either spelling and keeps both keys
  populated. Legacy configs with hackmd.collections get "hackmd" inferred
  into the list; an EXPLICIT backends list is taken at face value (omit
  "hackmd" there to disable the mirror — hackmd-sync now checks).
- Guard rails: hackmd can never be canonical; the ["local", "heptabase"]
  order (vault-canonical mirrored to Heptabase) is rejected as not yet
  supported; unknown values name the accepted set.

## 0.29.1 — index-card link resolution + book sidebar cleanup

- Wikilink resolution also indexes the vault FILENAME: cards whose title
  contains `/` live in dash-named files, and Obsidian wikilinks target the
  filename — 11 index-card links were silently degrading to plain text.
- `book_transform` strips the description text after a list item's last
  link: Book mode's sidebar was rendering each description as a separate
  same-level unclickable entry. Multi-link lines are left intact; source
  cards keep their descriptions.

## 0.29.0 — HackMD Book-mode index card

- `hackmd.book_index` (heptabase uuid or vault id): the designated index
  card is render-transformed into HackMD Book-mode shape — matching the
  official tutorials book verbatim: setext headings, relative `/noteId`
  links, and a setext H1 title prepended when the body has none. Source
  cards stay in the plugin's ATX/full-URL dialect; the transform is
  render-layer only and re-applies on every sync. The book card is
  excluded from write-back (its rendered dialect must never be reversed
  into the vault) — HackMD-side edits to it always report as conflicts.
  Turning on Book mode itself is a one-time manual step: Share → view
  mode → Book mode on hackmd.io.

## 0.28.1 — killed-run resilience for hackmd-sync

- The state ledger is saved incrementally after every create / adopt /
  content write — a run killed mid-way (timeout, crash) no longer orphans
  the notes it already created.
- Adoption: the remote index is fetched before phase A, and notes that a
  killed run created but never recorded are re-claimed by folder+title —
  but ONLY when their content is still the placeholder (the killed-phase-A
  signature). Same-titled notes with real content are surfaced as strays
  and never adopted or overwritten. Leftover duplicates are reported,
  never auto-deleted.
- A whole-run exclusive lock on the state file stops concurrent syncs from
  last-write-winning each other's ledger entries.
- Freshly created notes (invisible to the pre-create index) get their
  read-permission drift corrected in the post-write verification pass.

## 0.28.0 — HackMD two-way sync (level 2)

- `hackmd-sync` write-back (opt-in `hackmd.write_back`): HackMD-side edits
  merge back into the vault. Trust boundary: only notes whose EFFECTIVE
  write permission is `owner` — checked against the REMOTE's actual
  writePermission, not just config — ever write back; shared-writable notes
  and two-sided edits stay conflicts. Paragraph-level merge against a base
  snapshot: untouched paragraphs keep the vault original, edited paragraphs
  are link-reversed (HackMD links → wikilinks) and must round-trip; editing
  a paragraph containing degraded (unmirrored) links freezes the card.
  Concurrent vault edits are detected before save.
- backend `both` now sources hackmd-sync from the obsidian vault side, so
  write-back lands in plain .md and obsidian-sync's block-level level 2
  carries it on to Heptabase (state keys anchored to `heptabase_id`, with
  automatic migration; `--card` accepts either id).
- Rate-limit resilience: exponential 429 backoff (60/120/240s) on both the
  API and CLI paths; runs abort early after a streak of exhausted retries
  (report `aborted`) instead of burning the queue — state resumes next run.
  When the remote index is unavailable, existing notes are never content-
  PATCHed (an undetected HackMD edit could be clobbered) — deferred instead.

## 0.27.0 — per-collection HackMD permissions

- `hackmd-sync`: a collection entry may now carry its own `read_permission` /
  `write_permission`, overriding the global `hackmd` default — e.g. pin a
  projects collection private while overviews are shared. Both levels are
  validated against the API's accepted values.
- Fix: notes in conflict (edited on the HackMD side) now still get their read
  permission migrated — content stays frozen, permission stays managed.

## 0.26.1 — private by default on HackMD

- `hackmd-sync` now defaults `read_permission` / `write_permission` to
  **owner** (private): sharing is an explicit opt-in (`signed_in` / `guest`),
  not something a default hands out. The declarative-permission pass migrates
  existing mirrored notes on the next run — even content-unchanged (skipped)
  cards get their permission corrected.

## 0.26.0 — HackMD as the third note surface

- New `hackmd-sync` skill: one-way incremental mirror of selected collections
  (typically overviews) into HackMD folders — built for SHARING. Real
  note-to-note links between mirrored cards (wikilinks, card mentions, and
  Heptabase URLs all rewrite; unmirrored targets degrade to plain titles,
  never broken links), md5-incremental, change detection on the HackMD side
  (an edited note conflicts and is never overwritten), declarative read
  permission corrected every run, and write-after verification with
  self-healing re-sends (HackMD's 202-Accepted pipeline applies writes
  asynchronously and can drop bursts — single-note GETs are the only
  authoritative read; requests are throttled and per-card permission+content
  ride one PATCH).
- Auth: `hackmd-cli login` once or `HMD_API_ACCESS_TOKEN` — the token never
  lives in the plugin config. Permission values follow the API:
  `owner|signed_in|guest` (invalid values are rejected up front).
- `setup` / `check_config.py` cover the new `hackmd` section (CLI presence,
  token, `--probe` API reachability).

## 0.25.0 — interactive setup wizard

- New `setup` skill: an interview-style config wizard that creates, inspects,
  or adjusts `~/.config/research-cards/config.json` against
  `config.example.json`'s inline docs — minimal-config-first (plain-.md mode
  needs only `obsidian.vault`), never guesses Heptabase UUIDs, and knows the
  cluster limitation (the hb bridge cannot look up tag properties).
- `skills/setup/check_config.py`: a read-only health check — where the config
  lives, whether it loads (with the exact error), backend reachability
  (vault dir / heptabase CLI / optional `--probe` app test), and **upgrade
  hints** (settings the example documents that your config hasn't opted
  into). Example placeholders (`<...>`) count as unset, and any recorded
  error fails the exit code.
- The README's Configuration section slims to the wizard one-liner; the full
  field map moves to the wiki's new Configuration page (four languages).

## 0.24.3 — bridge spills seal in real time

- The hb transport now calls the bridge's new `hb seal` verb right after a
  spill (heptabase-ssh-bridge ≥ the seal-continuation endpoint): the
  tail→child sentinel becomes a real card node immediately, no Mac-side
  `repair_chain.py --seal` pass needed. Old bridge clients without the verb
  degrade gracefully to the previous behavior (`sealed:false` + repair note).

## 0.24.2 — real card-node sentinels (seal)

- **Root cause**: the heptabase CLI's markdown append does not convert
  `[[card:id]]` into a card-mention node — every spill (Mac CLI and hb bridge
  alike) wrote the tail→child link as plain text, invisible to PM-level chain
  parsers (merge scan, orphan tooling, repair) while the markdown-level
  tail-walk still followed it: half-visible chains.
- Spills now **seal** the sentinel into a real card node right after linking
  (Mac transport; best-effort — a transient failure never fails a landed
  spill). Bridge spills report `sealed:false` with a pointer to
  `repair_chain.py --card <entry> --seal`, which walks the chain converting
  text-form sentinels (following each freshly sealed edge).
- Seal strictly requires the card literal AFTER the marker text (prose
  mentioning both is not a sentinel), matching the chain parsers' rule.
- Forensics caveat documented: `note read` succeeds on trashed cards with no
  flag — verify with `tag add` before hand-rebuilding a chain edge.

## 0.24.1 — overflow_spill on by default

- `overflow_spill` now defaults to **true**: a full tail card automatically
  opens a continuation card instead of dead-ending. The old fail-fast default
  guarded a prerequisite (chain-aware merge) that shipped back in 0.16.0 —
  and a config-less box (the cluster driving the hb bridge has no
  `~/.config/research-cards/config.json`) could not opt in at all. Both reads
  of the key (the spill gate and the bridge-offline fail-closed guard) flip
  together; set `overflow_spill=false` explicitly to restore fail-fast.
  Runtime docs (SKILL.md / CARD-OVERFLOW.md) updated to match.

## 0.24.0 — chain-safe project-card appends + repair tool

- **Root cause fixed**: cluster-side low-level appends (`hb append <entry>`,
  `hb log-exp --to`) bypassed `append_card.py`'s tail-walk, landing content
  AFTER the continuation sentinel on the entry card. The campaign SKILL's
  step-7 hook now explicitly mandates `append_card.py` (never bare appends),
  and the project-card-log transport table carries the same warning.
- **New `repair_chain.py`** (Mac-only): moves content stranded after the
  sentinel to the real chain tail via `append_card.py` (keeping all
  capacity/spill guarantees — an oversized move correctly spills into a new
  continuation card), then truncates the entry back to the sentinel
  (md5-guarded; move-then-truncate order never loses content).
  Sentinel detection follows merge_lib's strict rule: the card link must
  come after the marker text.

## 0.23.1 — English-first packaging

- Both plugin manifests (`.claude-plugin` / `.codex-plugin`) now carry an
  English description (what marketplace browsers and `/plugin install` show);
  the Codex `shortDescription` mentions plain .md first, matching the new
  obsidian-by-default posture. README default language is English
  (zh-TW at `README.zh-TW.md`); the wiki's unsuffixed pages are English with
  a per-language custom sidebar.

## 0.23.0 — configurable output language + multilingual README/wiki

- Generated card content (scholar-inbox-clip translation / summary /
  colorize / figure captions, card-rewrite prose) now follows a configurable
  **output language**: config `profile.language` → Claude Code's `language`
  setting (best-effort, mapped: chinese→繁體中文, japanese→日本語,
  korean→한국어, english→English) → Traditional Chinese (the unchanged
  default). Single resolution rule in `hbconfig.output_language()`; all six
  generation prompt templates take `{lang}`, and tests assert no hardcoded
  language survives in any of them.
- README now ships in four languages — 繁體中文 (canonical) / English /
  日本語 / 한국어 — with a language switcher bar; the wiki carries the same
  four languages per page (suffix pages: `-en` / `-ja` / `-ko`).
- Doc fixes spotted during translation: `features.project` covers three
  skills (log / merge / campaign), not two; the progress.json template
  fills four fields, not three.

## 0.22.0 — per-row verification goals + evals series selector

- Ledger rows carry a per-row `purpose` (what THIS row verifies): the
  report's 「驗證目標」 column shows it (legacy rows fall back to the rung
  title), and `ledger-append` warns when `purpose` is missing or `decision`
  is too short to read as a self-contained narrative.
- Progress-page evals bar charts gain a series selector: the eval-set
  description table doubles as the picker (checkboxes, select all/none,
  stable per-series colors), so dozens of eval sets stay readable by
  filtering instead of drawing everything at once.
- Hardening: one shared resize listener rebuilds all evals charts (per-chart
  listeners no longer accumulate across re-renders); series maps use
  null-prototype objects (a series literally named `__proto__` is safe);
  rows with no finite values no longer squeeze empty categories into the
  x-axis.

## 0.21.0 — journal daily notes in a vault subfolder

- New `obsidian.journal.folder` (vault-relative; empty/absent = vault root,
  backward compatible): the journal bridge writes its `<YYYY-MM-DD>.md` daily
  notes under that folder, and `verify` scans the same place. Existing notes
  are not moved automatically — relocate them before changing the value.
- Path assembly is centralized in `hbconfig.journal_dir()`, which normalizes
  the value and rejects anything escaping the vault (absolute paths, `..`),
  so a mistyped config can never write daily notes outside the vault.

## 0.20.0 — artifact-branch deployment for campaign pages

- `pages-setup --deploy-branch <branch>` (GitLab): idempotent scaffold of an
  artifact branch for the showcase — anchored .gitignore, CI rule, pages.json
  bookkeeping; works from an unborn HEAD and inside worktrees.
- `assets/update-pages.sh.template`: flock-serialized rsync → amend →
  `--force-with-lease` push with a state commit; guards against unstaged/
  untracked files, rolls back on push failure, handles the first-push
  empty-SHA lease.

## 0.19.0 — showcase interactivity + multi-run progress

- Glossary metric capsules and interactive JS ledger metric charts on the
  campaign showcase pages.
- Progress dashboard: multiple runs on a shared global step axis, job-chain
  aggregation. Fixes: `tz_offset_hours` cross-campaign pollution + range
  validation, eval bar-chart all-zero NaN, Slurm array-task handling notes.

## 0.18.0 — research-campaign showcase 2.0

- Merged `cluster/append-card-overflow` follow-on branch `cluster/showcase-extras`
  (25 cluster-side review rounds): vocodec-style pages + landing card grid,
  `demo` subcommand (A/B audio-listening pages), semantic trend charts,
  content-hash versioned assets, publish-transaction locking, CI templates.
- Mac merge pass closes the branch's two known-opens: generated pages now WARN
  when .gitignore would drop them from the commit (assets shipping orphaned);
  a case-variant of index.html in the publish dir hard-rejects instead of
  silently coexisting/overwriting across filesystems.

## 0.17.1 — journal bridge hardening (review follow-ups for 0.17.0)

- **Frontmatter-aware claim**: claiming a pre-existing daily note inserts the
  managed block AFTER any YAML properties block (byte 0 stays `---`, Obsidian
  keeps recognising Properties) and preserves the user's leading blank lines.
  An EMPTY source day never claims a pre-existing unmanaged note.
- **Complete incremental key**: each day's skip key now includes a digest of
  the render inputs beyond the source doc (synced-card set, link titles,
  highlights.json) — card renames and newly-resolved highlights re-render
  journal days; `--rebuild-cache` also forces journal re-render. The fast
  path re-validates the target's markers, so deleting markers after a sync
  is caught (and reported as a conflict — the bridge never re-claims a note
  it managed before).
- **Attachment failures don't checkpoint**: a failed `file export` marks the
  day failed and it retries next run instead of freezing an empty embed
  forever. `--dry-run` no longer touches the vault on the attachment path
  (no mkdir / export / rename).
- **Marker validation**: exactly one standalone marker pair required —
  duplicates conflict; a rendered body containing a marker literal is
  refused. Writes go through tempfile + atomic replace with an optimistic
  pre-write recheck (an Obsidian/iCloud save racing the sync becomes a
  conflict, not a clobber).
- Minors: `days: 0` now means off (was: silently 30); single-day failures are
  isolated (one bad day no longer aborts the window); out-of-window journal
  conflicts are no longer auto-marked resolved by the conflict ledger.
- verify.py gains a `journal_issues` section: vault-root daily notes are
  checked for malformed markers and, inside the managed block only, missing
  embeds / broken wikilinks / leftover placeholders.
- Tests: journal suite 7 → 17 (render-spy fast path, marker corruption with
  existing state, dry-run with attachments, byte-exact preservation,
  frontmatter, duplicate markers, single-day isolation, attachment retry,
  marker-literal body, conflict-ledger window scoping).
- Fix-round residuals (second review pass): markers must be STANDALONE
  lines (inline occurrences are corruption -> conflict); new-file writes use
  O_EXCL so an exists()-race surfaces as conflict instead of clobbering; a
  disabled journal leg clears `journal_window` so stale conflicts stay open;
  the update-path race guard is documented as best-effort (no locking on
  iCloud vaults).

## 0.17.0 — journal bridge (Heptabase → Obsidian daily notes)

- obsidian-sync grows a one-way journal leg: the last `obsidian.journal.days`
  (default 30) days of the Heptabase journal mirror into a managed marker
  block (`<!-- hepta-journal:start/end -->`) at the top of vault-root
  `<YYYY-MM-DD>.md` daily notes. Content OUTSIDE the markers (the user's own
  daily writing) is never touched; malformed markers report a conflict and
  the file is left alone. Incremental via per-day contentMd5 in sync state;
  empty days never create files; emptied days clear the block but keep the
  claim. Off by default (`obsidian.journal.enabled`).
- Reverse flow (daily note → Heptabase journal) is an explicit non-goal of
  this version.
- File exports (images pasted in journals) reuse the card pipeline's
  attachment logic (extracted as a shared helper).

## 0.16.0 — 2026-07-08
- **project-card-merge chain-aware（CARD-OVERFLOW.md merge side 完成）**：
  scan/讀取沿續卡鏈（`chain`/`chain_dumps`/`child_payload`，PM 層 sentinel
  解析與 append_card 的文字層 round-trip 相容）；`find_orphans` 掃描
  create-link 間 crash 留下的孤兒續卡；`cleanup_children` 收編後補 tag →
  trash。合併輸入=整條鏈（子卡剝 auto-header/back-ref/sentinel 後視同 📥）。
- **finalize_chain：merge 產物不再受 100K 上限濃縮**——超過 spill_threshold
  時整段 H2 打包溢位成新續卡鏈（節點守恆，內容零遺失；子卡先建先 tag、entry
  最後存=crash 只留可發現孤兒）；obsidian 模式無上限、照舊單卡。resplit
  （narrative-act 拆卡）保留為人讀性更佳的替代，動用前先問使用者。
- **Op5 append 改走 append_card.py**（overview-graph SKILL.md）：🔍 gap 分析
  append 落鏈 tail、近上限時 spill，不再裸 `heptabase note append`。
- config.example：projects 補 `char_cap`/`spill_threshold`/`overflow_spill`
  （merge 側已 chain-aware，spill 可啟用）。tests：14 項純邏輯（守恆/順序/
  邊界）＋真環境 e2e（spill→鏈讀回→scan→cleanup）驗證。

## 0.15.0 — 2026-07-08
- **訓練進度儀表**（`campaign.py progress-init`／`progress`＋
  `scripts/progress_page.py`，收編 vocodec gen_progress_page 的 generic
  版）：log 解析規則全設定化（`progress.json`：log_glob＋named-group
  step_re＋雙 group kv_re＋charts 宣告，`_doc` 欄自帶說明）；輸出自包含
  HTML——stat tiles、SVG 曲線（dataviz 規範：validated 色組、2px 線、
  hairline 格線、crosshair 全 series tooltip、≥2 series 才有 legend、
  單 y 軸、參考線直標）、取樣資料表（無滑鼠 fallback）、ladder／ledger／
  job 鏈表。搶佔重跑重疊步以較新 job 為準；非有限值丟棄；抽稀 ≤700 點；
  對相同輸入位元級確定（無牆鐘時間戳）。`scheduler:"slurm"` best-effort
  squeue＋ETA（指令寫死不吃設定——progress.json 不能拿來跑任意指令；
  預設 none 全離線）。與 report 同目錄互連、同吃 pages.json 落位；
  per-job step 7 自動更新契約涵蓋兩頁。
- 進度儀表 review 強化（多鏡頭工作流 24 confirmed findings 全修）：指標存
  6 位有效數字（lr=5e-06 不再被壓成 0）；同 step 多行逐 key 合併（eval 行
  /雜訊行不清空資料）；payload 全 `<` → `\u003c`（杜絕 script-data 逃逸）
  ＋佔位替換互污免疫；log_glob 支援 `**`、拒絕逸出 project root；跨機器
  穩定全序；串流讀 log（多 GB 不吃記憶體）；NaN 防線（ledger-append 拒收
  ＋render 前 sanitize）；nd 0-10 驗證；未知欄位/空圖 key 警告；slurm
  scheduler 路徑補測試（PATH shim squeue）。
- **Review backlog 銷帳（Codex 復活後補審 11 筆）連帶修復**：
  obsidian-sync verify.py 鏡射 sync 的 tag_id 過濾＋folder 聯集；
  whiteboard2canvas census 補 2 表、placeholder 剝除只整理殘洞、原子寫檔、
  card.content schema guard、mention attrs 防禦；scholar-inbox-clip HF 路
  徑 4 修（source 讀取失敗不再永久漏收整封信、標題/讚數配對錯位改 anchor
  text、壞 agent 回覆不再誤標已處理、呼叫例外保守全收）；property trio
  I/O 失敗不再視為空值/成功（讀失敗跳過整卡、寫失敗回報）；backfill 完成
  判定納入 Topics（off-topic 卡收斂、舊卡補 Topics 有佇列）；標題去重修
  H1 前綴盲區＋`--card-types note`＋Obsidian 全量標題比較；card-rewrite
  list_todo 讀卡失敗記 read_errors 進收工 gate、batch/campaign 兩級收工
  語義；campaign example/checklist 數字與路徑修正。

## 0.14.0 — 2026-07-08
- **campaign 展示層自動更新＋GitHub/GitLab 雙軌**（收編 vocodec 的
  auto-refresh Pages 模式）：`campaign.py pages-setup`——讀 `git remote
  get-url` 自動判斷 host（`--host github|gitlab` 可覆寫，self-hosted
  GitLab 網域含 "gitlab" 即中）：github → 裝 `.github/workflows/pages.yml`
  （報告輸出 docs/）；gitlab → 裝 `.gitlab-ci.yml` 的 `pages` job（新模板
  `assets/gitlab-pages.yml`，發佈 public/——GitLab Pages 慣例）。既有
  `.gitlab-ci.yml` 不覆蓋，改印片段手動合併。選擇記進
  `runs/auto_research/pages.json`，`report` 未指定 `--out` 時據此自動落
  對的目錄。
- **自動更新契約進 per-job step 7**（SKILL Mode 4＋MISSION 模板）：job
  收尾 regen report 連同 ledger 一起 commit＋push，CI paths 過濾即觸發
  Pages 重新部署——頁面跟著 campaign 演進，無需排程器。
- Review 修復（Codex，5 Medium）：host 判定只看 URL host（repo 名含
  github/gitlab 不誤判）且以 push URL 為準；pages.json 記 `ci_ready`
  （CI 檔待手動合併時可判別「setup 跑過 ≠ 部署就緒」）；report 對
  `output_dir` 白名單校驗、壞 pages.json 明確失敗不靜默回退；github
  workflow 觸發分支自動改寫成安裝當下分支；顯著性 gate 措辭統一——
  進度頁每 job 誠實刷新（含 not-significant rows），gate 管的是對外
  勝出宣稱與 demo checkpoint。

## 0.13.2 — 2026-07-08
- **campaign 展示層（選配，取經 voidful/vocodec 的 Pages 模式）**：
  `campaign.py report`——ledger/queue → 單頁靜態 HTML 報告（ladder 狀態
  徽章、ledger 全表含顯著性徽章與 playbook 引用、BLOCKED 橫幅；全內容
  HTML escape、無時間戳＝輸出確定性）；`assets/pages-workflow.yml`
  GitHub Pages 部署模板（push docs/ 即發佈）。SKILL 新增 Mode 4，
  紀律同 GUARDRAILS：對外展示只在通過顯著性 gate 後更新。

## 0.13.1 — 2026-07-08
- **research-campaign 支援拆分式專案佈局**（project root 非 repo、核心
  code 才有版控——常見習慣）：MISSION 模板新增 PROJECT LAYOUT 段（git
  步驟作用域、狀態持久化語義：ledger 是工作簿、專案卡是帳本正本）；
  repo-checklist 對應章節；`campaign.py init` 對非版控 root 出提示。
- **`init --git`**：一鍵把 project root 升級成 repo——git init＋依當下
  目錄生成起手 .gitignore（checkpoints/wandb/大檔排除；**巢狀 core repo
  自動加入排除、維持獨立版控**）；首 commit 刻意留給使用者核可後執行。

## 0.13.0 — 2026-07-08
- **新 skill `research-campaign`**（project 方向第三塊）：自主實驗戰役的
  任務書格式＋記帳慣例——MISSION.md 住在目標 repo 的 `runs/auto_research/`
  （八段模板含逐段指引＋中性完整範例＋campaign-ready repo 檢查清單）；
  `campaign.py`（stdlib）scaffold／status／schema 校驗的 ledger append；
  量測紀律硬性把關（顯著性 CI gate、代表性切片、一次改一件事）；與
  project-card-log（每 job 進度回卡）、overview-graph Op5（開跑前 gap
  分析）、alchemist-playbook 式超參引用（ledger `playbook_rules_cited`）
  接線。刻意不做訓練執行器——執行照各 repo 的 MISSION。

## 0.12.2 — 2026-07-08
- **修批次 retrofit 的兩個結構性盲區**（實案：11 張 2023 老卡漏掃近三年）：
  `list_todo()` 回傳新增 `excluded_by_filter` 並在 stderr 明示「因 Source
  Type 過濾未列入」的張數（過濾照舊、沉默排除變可見）；SKILL.md 批次收工
  加入硬性完成驗證（重掃至 todo=[]＋檢查排除數）。

## 0.12.1 — 2026-07-08
- **修雙重去重漏洞**（實戰踩雷）：id 級 check_duplicate 的搜尋名額被
  journal 佔滿（limit 5→25）；新增**標題級第二道防線** `title_duplicate`
  ——id 記法不一致（數字 arxiv id vs `alphaxiv:<slug>`）的重複剪報在建卡
  前以正規化標題相等擋下。
- **HF 選文放寬**：config `email.topics_of_interest`——除 `profile.field`
  領域相關外，屬於興趣主題清單（建議對齊 Topics property 選項）的論文也
  入選。空清單＝維持只看 field。

## 0.12.0 — 2026-07-08
- **Topics property 進管線**：`set_topics()/current_topics()/valid_topic_options()`
  （config `props.topics`，語義同 Tasks 三件組：additive、集合外丟棄並記
  錄、obsidian 模式照單全收）。分工明確化：**Tasks＝總覽路由**（僅語音／
  音訊卡）、**Topics＝主軸分類**（所有卡，off-topic 的 LLM／vision／agent
  論文從此有家——`LLM / Foundation Model` 等）。6.5a rubric 與 backfill
  合約同步更新。

## 0.11.0 — 2026-07-07
- **多來源 digest：HuggingFace Daily Papers**——與 Scholar Inbox 共用同一
  信箱資料夾、逐封自動分流。HF 信的 arxiv ID 直取自 papers 連結（QP 軟斷
  行已處理）、讚數自「(N ▲)」行；因榜單非個人化，入選前先過
  `email.hf_min_upvotes` 門檻、再依 `profile.field` 做 agent 領域相關性
  選文（NONE＝整封略過；呼叫失敗＝保守全收並記錄）。journal 標題帶來源
  標籤。以真實信件實測：12 篇全數萃取、選文正確判 0 篇語音相關。

## 0.10.0 — 2026-07-07
- **whiteboard 鏡像重現 mention 線**：Heptabase 在板上自動畫的「卡片互相
  mention」連線，鏡像時從卡片內文的 mention 節點推導成 canvas edge——
  互相 mention 收斂為單一雙箭頭邊、與 explicit connection 重複的 pair
  不重畫、板外 mention 忽略。開關：`obsidian.graph.mirror_mention_edges`
  （預設開）。實測知識地圖 47 條（17 雙向）。

## 0.9.0 — 2026-07-07
- **whiteboard 鏡像 v2：live 來源**——直接讀桌面 app 的 SQLite
  （`hepta.db`，SQLite backup API 取一致性快照；app 開著也能跑），
  whiteboard 版面即時鏡像、不再依賴手動 Export。schema 無文件，
  表／欄位有 fail-loudly 檢查；讀不到自動退回備份來源。等價性測試保證
  同一份資料兩種來源輸出逐位一致。config 新增 `heptabase.app_data_dir`
  （選填）。零第三方依賴（stdlib sqlite3）。

## 0.8.0 — 2026-07-07
- **whiteboard → Obsidian Canvas 單向鏡像（v1）**：`overview-graph` 新增
  `whiteboard2canvas.py`——以 Heptabase「Export all data」備份
  （All-Data.json，官方可回匯格式）為來源，把 whiteboard 版面（卡片座標／
  顏色／摺疊高度、section→group、浮動文字 PM→md、連線→edge 含 sides）
  覆寫成 JSON Canvas。已同步卡→`file` 節點、未同步卡→帶連結的 `text`
  節點。config：`heptabase.backup_dir`＋`obsidian.graph.mirror_whiteboards`。
  即時來源（app IndexedDB 直讀）留待 v2。

## 0.7.4 — 2026-07-07
- **verify.py 與 sync.py 的資料夾規則完全對齊**：collection 缺
  `obsidian.folders.<key>` 時兩者同用 capitalized key fallback，掃描
  範圍取兩集合聯集（原本 verify 用原始 collection key、且漏掃 fallback
  資料夾，會誤報 state_orphans／漏報 untracked）。

## 0.7.3 — 2026-07-07
- **projects 也可成為 sync collection**：`heptabase.collections.projects`
  填上 `tag_id` 後，project 卡與 Papers/Overviews 一樣走完整三級雙向同步
  （前向鏡像／properties 三方／區塊級寫回＋收養），鏡像到
  `obsidian.folders.projects`（預設 `Projects/`）。
- **修**：collections 條目缺 `tag_id`（或為 `<佔位符>`）時 sync 啟動會
  KeyError——現在略過該條目（example 的 projects 條目正是這種 metadata）。
- SKILL.md collections 說明改為 config-driven 的一般化描述。

## 0.7.2 — 2026-07-07
- **verify.py 資料夾對照設定化**：collection → vault 資料夾改讀 config
  `obsidian.folders`（原殘留硬編 `Papers`/`Overviews`，folders 自訂或搬移
  後會誤報整批 state_orphans）。

## 0.7.1 — 2026-07-07
- **project-card-log 建卡 pin 位置自動分流**：`create_project_card.py` 在 git
  repo 內照舊寫 `.heptabase-card` marker；cwd 不在 git repo（project root 是
  普通目錄、git repos 在底下）改為在 registry `projects.json` 追加
  `match_any: [<dir name>]` 條目——nested repo 靠路徑子字串比對解析，marker
  放在其 git root 之上是搜不到的。撞名 fail-fast（先擋、不建卡）。輸出新增
  `record: marker|registry`。

## 0.7.0 — 2026-07-07
- **改名：heptabase-cards → research-cards**（plugin 已不只服務 Heptabase）。
  config 目錄新家 `~/.config/research-cards/`（舊目錄與舊環境變數
  `HEPTABASE_CARDS_CONFIG` 仍相容）；Claude namespace `research-cards:*`、
  Codex `research-cards@private-plugins`。`.heptabase-card` marker、config 的
  `heptabase` 區段等「指涉 Heptabase 本體」的名稱不變。

## 0.6.0 — 2026-07-07
- **project-card-log 自動建卡**：resolve 為 none 時可用
  `create_project_card.py` 建立含骨架的專案卡（tag 取
  `heptabase.collections.projects.tag_name`，預設 `project`）並自動寫
  `.heptabase-card` marker 完成 pin；三種 transport 自動選擇。

## 0.5.4 — 2026-07-07
- **D14 全新機器實測**（fresh-HOME 重放 README quickstart）→ 修兩個真問題：
  obsidian 模式首個 Tasks 因空選項集被丟棄（雞生蛋；改為 obsidian 無選項註冊表
  即放行）；config.example 佔位符 `<…>` 為非空字串繞過必填檢查（視同未設定）。
  流程固化為 tests/test_fresh_quickstart.py。

## 0.5.3 — 2026-07-07
- README：新增 Obsidian-only 零起點 Quickstart（B9）與無人值守排程教學
  （B8：agent routine／launchd／cron+codex 三種模式）。

## 0.5.2 — 2026-07-06
- **讀者 persona 設定化**：「為什麼語音研究者該讀」的讀者身分改由 config
  `profile.{reader, field}` 提供（card-rewrite／clip 模板與教學規格同步）。

## 0.5.1 — 2026-07-06
- **Sanitize（A5）**：所有個人 workspace UUID fallback 自程式碼移除；Heptabase
  的 tag／property／graph id 一律由 config 提供（`hbconfig.hb_id` 集中取值），
  heptabase 模式缺 config 時以明確訊息退出；obsidian 模式不受影響。
- `highlights.json`（highlight 嵌入內容）移至使用者資料目錄。
- CHANGELOG 建立；README 標註 Heptabase CLI 最低版本。

## 0.5.0 — 2026-07-06
- **Topics 成為使用者資料**：overview topic configs／snapshots／aliases 改由
  `~/.config/research-cards/topics/` 動態載入；repo 僅附 `_example` 模板。
- `OVERVIEW_TASKS` 路由表改由使用者 topic snapshots 衍生（cron 安全、本地檔案）。
- SKILL.md 內的金樣卡與 workspace UUID 全面改為 config 引用（`gold_cards.*`）。

## 0.4.x — 2026-07-06
- **0.4.2**：發佈整備——內部識別移除、個人路徑泛化、
  `CLAUDE_BIN`/`rsvg-convert` 走 PATH lookup、scholar state 檔遷
  `~/.config/research-cards/`（legacy-first）、MIT LICENSE。
- **0.4.1**：`heptabase-project-log` 改名 `project-card-log`。
- **0.4.0**：**兩個使用方向**（study / project，`features.*` 開關）；
  `project-card-log` 併入（雙傳輸層：本機 `heptabase` CLI 或 `hb` bridge；
  registry 遷 `~/.config/research-cards/projects.json`）。

## 0.3.x — 2026-07-06
- **0.3.1**：Codex 原生 plugin（`.codex-plugin` manifest＋本地 marketplace）；
  `plugin_root` 錨定靜態 cache；`~/.agents/skills` symlink shim 退役。
- **0.3.0**：**Codex agent 支援**——`agent: claude|codex` 設定；`codex exec`
  文字生成分流；全 script `realpath` 化。

## 0.2.0 — 2026-07-05
- **可選 backend（heptabase｜obsidian｜both）**：`_shared/backend.py` doc-level
  API；markdown 方言（顏色 `<span>`、toggle `- ⏵ `、underline、block
  reference）雙向可逆；`obsidian-sync` 三級同步（前向鏡像／區塊級寫回
  lossless-or-conflict／新檔收養）＋衝突總帳＋`verify.py`。
- 知識地圖：Obsidian JSON Canvas 對應 Heptabase whiteboard。

## 0.1.0 — 2026-07-04
- 初始整併：scholar-inbox-clip、card-rewrite、overview 家族
  （overview／overview-daodu／overview-graph）、project-card-merge 以
  Claude Code plugin 形式集結（Heptabase 專用）。
