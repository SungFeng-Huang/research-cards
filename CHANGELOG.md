# Changelog

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
