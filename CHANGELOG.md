# Changelog

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
