---
name: project-card-log
description: >-
  From a project-wise session, find THIS project's Heptabase card and log
  progress as SELF-CONTAINED log cards: each log event becomes its own card
  (background context, what was done, results, what it means, decisions
  pending — no unexplained abbreviations), and the project chain only gains
  one human-readable timeline line (📎 date [[card]] one-sentence summary) —
  the chain stays a readable project timeline for handoff (to the user, to
  the Mac, to the paper side). Auto-resolves which card via a per-repo
  .heptabase-card marker, then a registry (projects.json), then search. Use
  when the user says 補卡 / 記實驗 / log progress / 記進度 / handoff 實驗進度 /
  update my Heptabase project card / 把進度寫進 Heptabase. Transport: local
  `heptabase` CLI when available (Mac), else the `hb` bridge (remote over SSH).
allowed-tools: Bash(hb:*) Bash(heptabase:*) Bash(python3 *) Bash(git *) Bash(rg *) Bash(grep *) Bash(ls *) Bash(cat *) Read
---

# Project Card Log — enrich THIS project's card from its codebase

## Transport（先確認用哪條路）

```bash
command -v heptabase && heptabase --version   # 本機有 CLI（Mac + desktop app）→ 直連
command -v hb                                  # 否則走 hb bridge（遠端 session）
```

指令對應（下文以 `hb` 示例；本機直連時換用右欄）：

| bridge | 本機 CLI |
|---|---|
| `hb read <ID>` | `heptabase note read <ID>` |
| `hb append <ID> "<md>"` | `heptabase note append <ID> -c "<md>"` |
| `hb search "<q>"` | `heptabase card list -q "<q>" --limit 5` |
| `hb log-exp …` | （bridge 專屬離線佇列；直連時用一般 append） |

> ⚠️ 表中的 `append`／`log-exp --to` 都是**單卡低階指令**：卡片有續卡鏈時
> 它們直寫你給的那張卡（通常是 entry），內容會錯落在 sentinel 之後。
> 對專案卡寫進度**一律走 `append_card.py`**（自動 tail-walk）；已經錯落
> 的卡用 `repair_chain.py --card <ENTRY_ID>` 修（Mac-only，先 `--dry-run`）。

兩條路都是 **append-only 的用法**：即使 CLI 支援 overwrite 也不要用——
enrichment 一律附加帶日期的新段落，合併整理交給 project-card-merge。

Each cluster session lives in one project's repo. This skill resolves the
**matching Heptabase card** and appends codebase-grounded content to it via the
`hb` bridge. The card is the synthesis/ideation + paper-reference layer; the raw
logs stay in the repo (`CHANGELOG.md` / `NOTES.md` / sweep docs / wandb).

> **`hb` is append-only** (the bridge exposes read + append/create, NOT overwrite
> or todo-checking). So enrichment = **append a dated section**, never edit the
> existing brief in place. The user tidies/merges later on the Mac.

## Step 1 — Resolve which card this project maps to
```bash
python3 <此 skill 目錄>/resolve_card.py   # plugin 內路徑；兩個 agent 皆同
```
It prints one JSON line. Act on `source`:
- `marker` / `registry` / `env` → you have `card` (+ `title`). Proceed to Step 2.
- `registry-ambiguous` → show `candidates`, ask the user which.
- `none` → this repo isn't pinned yet:
  1. Search first（`hb search` / `heptabase card list -q`）—— the card may
     exist but be unpinned. Found → confirm with the user, pin via the
     marker (below).
  2. **Not found → create it**: confirm the title with the user, then

     ```bash
     python3 <此 skill 目錄>/create_project_card.py --title "<Title>"
     ```

     It creates the card WITH the 定位/現狀/brief skeleton, tags it with
     config `heptabase.collections.projects.tag_name`（default `project`；
     tag 不存在會自動建立）, and pins the mapping — check `record` in the
     JSON output: inside a git repo it writes `.heptabase-card` at the git
     root（`record: marker`）；cwd NOT in a git repo（典型：project root 是
     普通目錄、git repos 在它底下）→ 改為在 registry 追加
     `match_any: [<dir name>]` 條目（`record: registry`——marker 放在
     nested repo 的 git root 之上會被 marker 搜尋的 stop-at-git-root 規則
     擋住，registry 的路徑子字串比對才蓋得到；條目 per-machine，別台機器
     要重加）. Transport auto-picked（local heptabase CLI → tag 完整；
     hb bridge → 建卡＋提醒回 Mac 補 tag；backend=obsidian →
     `Projects/` 資料夾＋frontmatter tag）.
  3. Manual pin (existing card):
     ```bash
     printf 'card: <CARD_ID>\ntitle: <Title>\n' > "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.heptabase-card"
     ```
  (Or register globally: add a `match_any` entry to
  `~/.config/research-cards/projects.json` — template: this dir's projects.example.json.)

Never guess a card id — resolve or confirm first.

## Step 2 — Read the card, focus on what's missing
```bash
hb read <CARD_ID>          # markdown; or `hb read <CARD_ID> --json`
```
Read **「現狀」** and the **「📝 待補成 paper 級參考」** brief. That brief is your
to-do list: each bullet names specific files/metrics to pull (e.g.
`docs/experiments/cos2_sweep_curriculum.md`, `NOTES.md §9`, a wandb project).

## Step 3 — Gather from THIS repo (evidence only)
Use Read / `rg` / `git log` on the local codebase to collect exactly what the
brief asks: method specifics + dimensions, full ablation numbers/tables,
baselines, design rationale (the WHY), figure sources.
- **Only write what the codebase/logs actually support.** If a number or claim
  can't be found, write it as `（待確認：…）` rather than inventing it.
- Keep model/metric/config names verbatim; numbers exact.

## Step 4 — 寫進度：log-as-card（預設）

**每次 log＝建立一張 self-contained 的新 log 卡，鏈尾只 append 一行時間線
連結**——專案卡鏈保持成一條**人看得懂的時間線**（一行一事件），完整脈絡
住在 log 卡上；把時間線蒸餾回正文是 project-card-merge 的事。

```bash
python3 <此 skill 目錄>/append_card.py --card <ENTRY_CARD_ID> \
    --log-title "<專案短名>｜<一句主題>（YYYY-MM-DD）" \
    --log-summary "<一句人話摘要——不用代號>" \
    --content-file log_body.md
```

鏈尾長出的一行：`📎 2026-07-21　[[card:<log卡>]]　<一句人話摘要>`
（Mac 直連會自動 seal 成可點的卡片節點；bridge 端是文字型——輸出的
`note` 會提醒回 Mac 跑 `repair_chain.py --card <ENTRY> --seal` 收斂。）

### log 卡寫作規格（handoff 的 hard rules——寫給「兩週後的人」看）

1. **無縮寫**：任何代號／縮寫**首次出現必須展開或一句話解釋**——
   「E0（＝baseline 訓練、無 curriculum）」「RTF（real-time factor，
   越低越快）」。第二次以後可直接用。
2. **背景脈絡先行**（2–4 句）：接續哪個先前結果、這次要回答什麼問題、
   為什麼現在做。讀者沒有你的 session 記憶。
3. **結構模板**：

   ```markdown
   # <專案短名>｜<一句主題>（YYYY-MM-DD）

   **專案**：[[card:<ENTRY_ID>]]　**環境**：<cluster host／Mac>　**代碼**：<repo>@<short-sha>

   ## 背景脈絡
   （2–4 句，無縮寫——接續什麼、要回答什麼）
   ## 做了什麼
   ## 結果
   （數字表格；每個指標一句「這個數字是什麼、越高還越低好」）
   ## 這代表什麼
   （對專案的意義，1–3 句）
   ## 待裁決／下一步
   （需要使用者拍板的事**逐條列**，每條含裁決選項與你的建議）
   ```

4. **--log-summary 用人話**：時間線行是使用者掃鏈時唯一看到的字——
   「課程學習讓 val loss 再降 8%，但推理變慢待裁決」勝過「E3 done」。

- `--card` 一律傳 **Step 1 的 ENTRY 卡**（母卡）；script 沿鏈走到 tail。
- `--dry-run` 先看計畫（不建卡、不寫入）。
- 離線（bridge down）會 fail-fast 不建孤兒卡；create 成功但 link 失敗時
  會存 recovery 檔並印補救指令。

### 舊模式：直接 append 段落（相容保留）

小型機械性補充（不值一張卡的一兩行）仍可直接 append；campaign step 7
等內部流程也還走這條：
```bash
python3 <此 skill 目錄>/append_card.py --card <ENTRY_CARD_ID> --content-file section.md
```
- `--card` 一律傳 **Step 1 的 ENTRY 卡**（母卡）。script 自己沿鏈走到 tail——**絕不傳子卡 id**。
- **卡沒滿**（常態）：`overflowed:false` → 內容直接 append 到 tail。
- **卡接近容量上限**：**預設（0.24.1 起）自動 spill**——建續卡子卡並在 tail 補
  `▶ 續卡…[[card:<id>]]`（`overflowed:true, child:<id>`）；無 config 的機器
  （cluster bridge）同樣適用。cluster 建的子卡未上 tag（bridge 無 tag 能力）
  → 讀輸出 `note` 回 Mac 補 tag。config 顯式設
  `heptabase.collections.projects.overflow_spill=false` 可改回滿卡 fail-fast
  （不 spill、不移內容，訊息叫你先回 Mac 用 project-card-merge 整併）。
- 想先看會不會溢位：加 `--dry-run`（只讀，回報 `dry_run:true`＋是否 would-block/would-spill）。
- 把一條鏈**整併回一張卡**是 **Mac-only 的 project-card-merge** 的事（需 overwrite/
  delete，append-only 的 bridge 做不到）——完整規格與 `overflow_spill` 啟用順序見
  `CARD-OVERFLOW.md`。

範例段落內容（append_card.py 的 `--content` 就餵這個）：
```markdown
## 📥 cluster 補充 2026-06-24（from <repo>@<git short-sha>）
### Method
- <evidenced detail …>
### Experiments
- <full ablation numbers / table …>
### Findings / Results
- <…>
```
（低階等價 `hb append <ID> "<md>"` 直接寫、但**不處理容量上限**——一律走 append_card.py。）
For a quick single experiment result instead of a full enrichment:
```bash
hb log-exp model=<m> val_loss=<x> step=<n> --to <CARD_ID>
```
Writes queue locally and auto-sync if the Mac/tunnel is down (`hb drain-status`).
> ⚠️ `hb log-exp --to` 直接寫進 **ENTRY 卡**，**不走 append_card.py 的 tail-walk /
> 容量檢查**。只在母卡「沒有續卡鏈、且離上限還遠」時用。卡已 chained 或接近上限時，
> 把該結果當一小段 markdown 餵給 `append_card.py`（`--content`），才會落到正確的 tail
> 並受容量保護。

## Step 5 — Report
Tell the user what you appended and what's still `（待確認）`. Suggest they do a
final merge/cleanup on the Mac (where full edit/overwrite is available), since
`hb` could only append.

## Notes
- One repo ↔ one card. A monorepo with several projects: put a `.heptabase-card`
  in each subproject dir (the marker search walks up from cwd, nearest wins).
- Adding a brand-new project: `create_project_card.py` handles card + skeleton
  + tag + pin in one step from anywhere（見上方 none 分支）；monorepo 子專案
  記得傳 `--marker-dir "$(pwd)"`，marker 才不會 pin 到整個 repo。
- Project root 不是 git root（git repos 在它底下）：從 project root 跑
  create_project_card.py 會自動 fallback 成 registry 條目
  （`match_any: [<dir name>]`），底下所有 nested repo 都經路徑子字串比對
  解析到同一張卡——一卡對多 repo 本來就是 registry 的守備範圍。
