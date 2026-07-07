# Changelog

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
