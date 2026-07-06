---
name: project-card-merge
description: >-
  Consolidate a Heptabase research-project card on the Mac: fold the cluster's
  append-only `📥 cluster 補充/進度` blocks (and any `📝 待補成 paper 級參考`
  brief) into ONE focused, paper-grade, coherent card — update 現狀 to the latest
  state, supersede stale info, keep all paper-grade detail + figures + file
  citations + card-links, and remove the dated append shells. Also folds
  tail-appended `🔍` research-gap analysis sections (from overview-graph
  Operation 5) into the body after Findings, promoting actionable 發想 into
  下一步 and verification-type 洞 into 待補. This is the Mac-only
  "final merge" that pairs with the cluster-side append-only `project-card-log`.
  Use when the user says 整理/合併 project 卡, merge cluster progress, consolidate
  the Research-Projects cards, or update a project card for paper writing.
allowed-tools: Bash(heptabase *) Bash(python3 *) Read
---

# Project Card Merge — consolidate cluster-appended progress (Mac-side)

## Backend

卡片讀寫經由 rewrite_lib 路由（obsidian 模式可用），但 Research-Projects hub 的 card id
為 Heptabase UUID——obsidian 模式需改用 vault 內對應卡的 id。主要工作流仍以 heptabase/both 為準。

The cluster session appends dated `📥 cluster 補充/進度 YYYY-MM-DD` blocks to a
project card via the `hb` bridge (append-only — it cannot overwrite). This skill
is the **Mac-side counterpart**: it merges those blocks (and any leftover
`📝 待補成 paper 級參考` brief) back into one coherent, focused, paper-reference-grade
card. Three-layer principle (same as the cards already follow):
**card = synthesis + 發想; raw logs stay in the codebase; keep paper-grade detail but no append sprawl.**

Mechanics live in `card-rewrite`'s `rewrite_lib` (builders + `finalize`); this
skill's `merge_lib` adds the Research-Projects index, a merge-readiness scan, and
a table builder.

```python
import sys, os; sys.path.insert(0, os.environ.get("CLAUDE_PLUGIN_ROOT", os.path.expanduser("~/.claude/skills/research-cards")) + "/skills/project-card-merge")
import merge_lib as M           # M.L is rewrite_lib
```

## Step 1 — Pick the target card(s)
```bash
python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/research-cards}/skills/project-card-merge/merge_lib.py          # list project cards + which NEED MERGE
python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/research-cards}/skills/project-card-merge/merge_lib.py <cardId> # scan one (appended blocks, brief, size, figs)
```
- If the user named a card, use it. Else show the list and act on the ones flagged **NEEDS MERGE** (or ask which).
- If a card has no `📥` block and no brief → it's already consolidated; report and skip.

## Step 2 — Read the WHOLE card
```python
print(M.L.card_dump(CID))                 # full recursive text — read every 📥 block + brief in full
imgs = M.L.extract_images(M.L.read_card(CID)[1])   # figures to preserve (re-insert later)
```
`card_dump` surfaces tables as `| … |` rows and card-links as `[[card:<id>]]` —
**note every table and card-link; the rebuild does NOT auto-carry them**. Recreate
tables with `M.table([...])` and card-links with `M.cardlink("<id>")` in Step 4
(they were the exact things a naive read would drop).
Read the existing main sections AND every `📥` block fully — the appended blocks
hold the newest 現狀, corrected facts (`更正先前理解`), full numbers/tables, and
file citations. Do not skim.

## Step 3 — Merge into one focused structure
Rebuild a single coherent card (adapt section names to the project; the two
existing cards use this arc):

1. **定位** — 一句話目標 + Codebase + 權威紀錄（codebase docs / wandb）+ 母題/子題 card-link.
2. **現狀（一眼掌握）** — **rewrite to the LATEST state** from the newest `📥` block
   (supersede the old 現狀; note 資料事件/blockers if any).
3. **進展里程碑（已完成）** — fold in newly-completed milestones (infra changes, runs finished).
4. **方法 / Method** — fold appended Method detail (architecture, dims, mechanisms)
   into the main method section; **keep file citations** (`path:line`) and bilingual terms.
5. **實驗統整 / Results** — fold appended numbers/tables; keep the ablation table
   (use `M.table([...])`), eval protocol, and key metrics verbatim.
6. **Findings / 關鍵發現** — fold new insights (supersede/extend earlier ones).
6.5. **`## 🔍 研究漏洞與發想`** — fold the dated `🔍` analysis section(s) the
   research_gaps workflow (overview-graph Operation 5) appends at the card
   TAIL into this position (after Findings, before 下一步):
   - **The `🔍` heading prefix is a HARD CONTRACT** — `research_gaps.py`
     excludes these sections from concept extraction by the prefix
     (position-independent). Keep it. Recommended folded title:
     `🔍 研究漏洞與發想`; move the analysis date to a light line inside the
     section (or per-item `（YYYY-MM-DD）` tags when multiple analyses merge).
   - Multiple dated analysis sections merge into ONE: 洞/發想 resolved by
     later progress are removed (same supersede principle as `📥`); still-open
     ones stay, lightly dated.
7. **計畫 / 下一步 + 發想** — update; drop items the new progress resolved.
   **Promote actionable 發想 from the `🔍` section** into 下一步 as one-line
   items with a back-ref（`（← 發想 N）`）— the full argument stays in the
   `🔍` section; dedupe against existing 下一步 items (an existing item that
   matches a 發想 merges into one entry, keeping the back-ref).
8. **已知未解 / 待補·仍待確認** — keep genuinely-open items (offline baseline, figures, bugs).
   **Verification-type 洞**（missing metrics, unexamined interactions, facts
   to confirm）become 待補 entries with a back-ref（`（← 洞 N）`）; if an
   existing 待補 entry already states what a 洞 re-raises, just back-ref it
   instead of duplicating.
9. **參考** — CarelessWhisper-style links, **preserved figures**, Source/原文 links.

Rules:
- **Supersede, don't duplicate** — when a `📥` block corrects/updates an earlier
  fact (e.g. `start_idx` meaning, current step, v10→v11 status), the merged card
  carries only the corrected/latest version.
- **Remove the shells** — after folding, the `📥 cluster …` H2 blocks and any
  satisfied `📝 待補成 paper 級參考` brief must be gone (their *content* lives on
  in the main sections; only the dated wrapper is dropped).
- **Preserve**: every figure (`M.L.extract_images` → re-insert via `M.L.img`),
  every card-link (母題/子題), Source/原文 links, file-path citations, exact numbers.
- **Don't lose paper-grade depth** — this is a paper-reference card; fold detail,
  don't summarize it away.

## Step 4 — Rebuild + finalize
Build `C=[]` with `M.L.add(C, …)` and the builders (`M.L.h/pp/bul/bp/img/hr/source`,
`M.cardlink`, `M.table`). Then colorize + size-check + save in one call:
```python
COLOR = [("最佳","green"),("SOTA","green"), ("尚未","red"),("bug","red"), ("v11","yellow"), ...]
md5, _ = M.L.read_card(CID)
print("size", M.L.finalize(CID, md5, C, COLOR))   # colorize → shrink figs if >88k → raise if >100k
```
`finalize` re-applies colorization, shrinks data-URL figures if needed, and
refuses >100k. If it raises, trim least-central bullets (not the teaching/detail);
if the card is genuinely too big, that's the signal to split (ask the user).

## Step 5 — Verify
```bash
python3 ${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/skills/research-cards}/skills/project-card-merge/merge_lib.py <cardId>   # needs_merge should be false now
```
Confirm: no `📥`/`待補成 paper` headings remain, no `🔍` section left AFTER the
下一步/計畫 headings (folded position = after Findings), the `🔍` heading
prefix survived, figures + card-links intact, size < 100k.
Report what was folded, what was superseded, and any remaining 待補 items.

## Notes
- This skill **only consolidates an existing card** — it does not invent content.
  Everything comes from the card's own `📥` blocks (which the cluster grounded in
  the codebase). If a `📥` block says `（待確認）`, keep it as 待補.
- Pairs with cluster-side **`project-card-log`** (append) — see
  [[heptabase-cluster-bridge]]. Per the user's rule, cluster appends; Mac merges.
- **Closed loop with research_gaps (overview-graph Operation 5)**: its analysis
  section always APPENDS at the card tail (dated, `🔍`-prefixed); the next
  merge folds it into the body after Findings (arc item 6.5) and refreshes
  下一步/待補 accordingly. Append 落尾、merge 折進正文——same rhythm as `📥`.
- Project cards are the card mentions on the Research-Projects hub
  (config `heptabase.collections.projects.hub_card`); list them via
  `merge_lib.list_project_cards()`.
