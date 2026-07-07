# research-cards — 宏毅老師教你做研究 📚

把論文訊息流變成一座**會教你的研究知識庫**：每張卡片都像一堂宏毅老師的課——
先告訴你「為什麼該讀」、需要哪些先備知識，再用 WHY 驅動的敘事把方法講懂，
最後放進主題比較卡與知識地圖的脈絡裡，讓你隨時知道每篇論文在整個領域的位置。

> 本專案致敬[李宏毅老師](https://speech.ee.ntu.edu.tw/~hylee/)的教學風格，
> 與老師本人無關。教學靈魂與
> [hung-yi-lee skill](https://github.com/voidful/hung-yi-lee-skill)
> 一脈相承——建議一起安裝（見[整合](#整合選用)）。

支援 **Heptabase** 與 **Obsidian** 兩種筆記後端（可雙向同步）、
**Claude Code** 與 **Codex** 兩種 AI agent，任意組合。它幫你：

- **剪報**：digest 信件（或一條 arxiv 連結）→ 教學風格卡片——快速摘要
  toggle、語意上色、圖片、屬性欄位一次到位。
- **組織**：依 Tasks 分類法自動路由到各主題的**比較總覽卡**，配敘事導讀、
  主題 hub、橫向連結與視覺化知識地圖。
- **同步**：整個卡片庫在 Heptabase ↔ Obsidian 之間雙向同步——區塊級寫回、
  有損就報衝突不亂寫、衝突總帳可追蹤。
- **研究日誌**：從任何專案 repo 的 session 把進度記進對應的專案卡，
  之後整併成 paper 級的完整記述。
- **參考文獻**：一鍵匯出卡片連到的所有論文的官方 BibTeX。

---

**目錄** ·
[Skills 總覽](#skills-總覽) ·
[安裝](#安裝) ·
[設定](#設定) ·
[快速上手（Obsidian）](#快速上手-a--obsidian-從零開始) ·
[快速上手（Heptabase）](#快速上手-b--heptabase--both) ·
[日常使用](#日常使用) ·
[Heptabase ↔ Obsidian 同步](#heptabase--obsidian-同步) ·
[無人值守排程](#無人值守排程剪報管線) ·
[整合](#整合選用) ·
[疑難排解](#疑難排解) ·
[License](#license)

## Skills 總覽

兩個獨立可用的方向，任一可由 config `features.{study, project}` 關閉。

**📚 Study — 論文管線**

| Skill | 做什麼 |
|---|---|
| `scholar-inbox-clip` | digest 信件／URL → 教學卡片（屬性、圖片、journal 記錄、總覽路由） |
| `card-rewrite` | 把既有卡片改寫成完整教學格式（一句話 / 為什麼該讀 / 先備知識 / WHY 驅動敘事 / 雙語術語） |
| `overview` | 維護各主題比較總覽卡：逐論文小節、維度比較表、覆蓋率檢查、arxiv 序排序 |
| `overview-daodu` | 在總覽卡頂端插入／刷新敘事導讀（冪等） |
| `overview-graph` | 知識圖結構：主題 hub、橫向 ↔/→ 連結、知識地圖（Heptabase whiteboard / Obsidian JSON Canvas）、一致性稽核 |
| `obsidian-sync` | Heptabase ↔ Obsidian 雙向同步（僅 backend `both`） |
| `bib-export` | 匯出卡片連到論文的官方 BibTeX——絕不捏造，查不到的變成 `% TODO` 註解 |

**🧪 Project — 研究專案日誌**

| Skill | 做什麼 |
|---|---|
| `project-card-log` | 在專案 repo 的 session（本機或遠端）解析出這個專案的卡，附加有日期、有程式碼依據的進度——只增不改 |
| `project-card-merge` | 另一半：把累積的進度區塊整併成一張 paper 級的完整卡（全編輯端） |

## 安裝

### 需求

| 你要用 | 你需要 |
|---|---|
| 基本 | Python 3.10+、`pip install pyyaml`、一個 agent CLI（**Claude Code** 或 **Codex**） |
| `backend: heptabase` / `both` | macOS＋**Heptabase 桌面版**＋`heptabase` CLI **≥ 0.4.0**（本機 API `127.0.0.1:21210`） |
| `backend: obsidian` / `both` | 一個 **Obsidian vault**（放 iCloud 的話，終端機要給**完整磁碟取用權限**） |
| 信件剪報（`scholar-inbox-clip`） | macOS **Mail.app**＋專用信箱資料夾（用 Mail 規則把 digest 導進去）＋`osascript` 自動化權限 |
| 卡片圖片 | `pip install pymupdf`（PDF 頁面）＋`brew install librsvg`（SVG） |
| Claude Code 加分項 | **alphaXiv MCP**（剪報／改寫的內容依據）與 **heptabase MCP**（同步時解析 highlight 嵌入）。選用——Codex 走內建 HTTP 抓取、highlight 改列給你手動補 |

### Claude Code

直接從 GitHub 裝：

```
/plugin marketplace add SungFeng-Huang/research-cards
/plugin install research-cards@research-cards
```

或 clone 後把 repo symlink 進 skills 目錄（如
`~/.claude/skills/research-cards`），`.claude-plugin/plugin.json` 會讓它以
plugin 形式載入。兩種方式 skills 都以 `research-cards:<skill>` 出現。

### Codex

Codex 從「marketplace 目錄」安裝 plugin。替你的 clone 建一個（一次性）：

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

Codex 執行的是**靜態 cache 副本**：請在 config 設 `plugin_root`（狀態讀寫
會錨定回活的 repo），plugin 更新後記得 `codex plugin remove` ＋ `add` 刷新。

## 設定

把 `config.example.json` 複製到 `~/.config/research-cards/config.json`
填寫——每個欄位在 example 裡都有行內說明。整體地圖：

| 欄位 | 控制什麼 |
|---|---|
| `backend` | `heptabase` \| `obsidian` \| `both`。`both` 以 Heptabase 為準、`obsidian-sync` 鏡像到 vault；`obsidian` 純 `.md`＋frontmatter，不需要 Heptabase |
| `agent` | `claude` \| `codex`——無人值守腳本用哪個 CLI 生成文字（`claude --print` / `codex exec`） |
| `plugin_root` | 活的 plugin 路徑——Codex 驅動時必填（cache 錨定） |
| `profile` | `reader` / `field`——卡片教「誰」（如 語音研究者）；流進每張卡的「為什麼該讀」 |
| `features` | `{"study": bool, "project": bool}`——整個方向開關 |
| `email` | 剪報管線用的 Mail.app `account`＋`mailbox` |
| `heptabase` | workspace id、各 collection 的 tag id／filter（`collections`）、屬性 UUID（`props`）、語料 `scan_tags`、`graph` ids（根目錄卡、知識地圖 whiteboard、Level 屬性、topology `hubs`）。id 用 `heptabase tag list` / `heptabase tag properties <tagId>` 查 |
| `obsidian` | vault 路徑、各 collection 資料夾（`folders`）、`graph`（`.canvas` 地圖、根目錄筆記、`hubs` 用 `Folder/Name` id） |
| `integrations` | 選用的外部 skill——見[整合](#整合選用) |
| `gold_cards` | 選用的風格金樣卡（card-rewrite / overview-daodu 用；不設則用內建規格） |

兩個值得知道的原則：

- **所有 id 一律來自你的 config。**heptabase 模式的指令缺什麼 id 就會指名
  哪個 key 沒填然後退出——絕不用猜的。
- **Topics 是使用者資料，不是 plugin 資料。**總覽主題設定住在
  `~/.config/research-cards/topics/<key>/`（模板：
  `skills/overview/topics/_example/`），`aliases.json`、`projects.json`
  也在旁邊。repo 本身不含任何個人分類法。

## 快速上手 A — Obsidian，從零開始

不需要 Heptabase。十分鐘建起論文管線：

1. **安裝** plugin（見上）＋ `pip install pyyaml`
   （要圖片再加 `pymupdf` 與 `librsvg`）。
2. **建 vault**（位置隨意；iCloud 可以，但終端機要有完整磁碟取用權限）。
3. **設定**——最小 `~/.config/research-cards/config.json`：

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

4. **第一張卡**——在 agent session 裡說：
   「用 scholar-inbox-clip 把 https://arxiv.org/abs/XXXX.XXXXX 做成卡片」。
   卡片會出現在 `Papers/`，含 frontmatter 屬性、快速摘要與語意上色。
   （信件剪報是選配——見[排程](#無人值守排程剪報管線)。）
5. **累積幾篇相關論文後，長出結構**：
   1. 把 `skills/overview/topics/_example/` 複製到
      `~/.config/research-cards/topics/<你的主題>/`，填好 `config.py`。
   2. 建一張 **hub 筆記**：要有 `## 子卡與閱讀順序` 小節、以
      `[[wikilinks]]` 列出比較卡，且 frontmatter `tasks` 帶你的 Tasks
      值——hub 格式是 API，缺一項 topology 會直接報錯。
   3. 把 hub 登記到 config `obsidian.graph.hubs`，然後：

      ```bash
      python3 /path/to/research-cards/skills/_shared/topology.py refresh <你的主題>
      ```

   之後 `overview` / `overview-daodu` / `overview-graph` 就會維護這個主題；
   知識地圖是一張你自己排版的 Obsidian Canvas。

## 快速上手 B — Heptabase / both

同樣流程，前面多一步查 id：

1. 裝 **Heptabase 桌面版**與 `heptabase` CLI（≥ 0.4.0）。
2. 在 Heptabase 建你的 tags（如 `study/paper`、`study/overview`、
   `project`）與屬性，然後收集 id：

   ```bash
   heptabase tag list                      # tag ids
   heptabase tag properties <tagId>       # 屬性 UUID
   ```

3. 填 config 的 `heptabase` 區段（workspace id、帶 tag id 的
   `collections`、`props`、`graph`）。`backend` 設 `heptabase`——或
   `both`，多得到[雙向 vault 同步](#heptabase--obsidian-同步)
   （`obsidian` 區段也要填）。
4. 照快速上手 A 第 4 步剪第一張卡。

## 日常使用

以下都是 agent 驅動：跟 agent 描述你要什麼，它會照對應的 SKILL.md 執行。
列出的指令是 agent（或你自己）在底層跑的東西。

### 📚 Study

**剪一篇論文**——給 URL（「把這篇 arxiv 做成卡片」）或掃信箱（「跑
scholar-inbox-clip」會讀設定好的信箱、去重、建卡、上 Tasks、路由到總覽卡）。
無人值守等價指令：

```bash
python3 skills/scholar-inbox-clip/run.py        # 排程模式，見排程一節
```

**升級一張卡**（「用 card-rewrite 把這張卡重寫成教學格式」）——把完整教學
結構套到既有卡片上，事實內容不動。

**維護總覽主題**：

```bash
cd skills/overview
python3 sync_overview.py <topic> status   # 覆蓋率 diff → 哪些論文 MISSING
python3 sync_overview.py <topic> sort     # 依 arxiv ID 重排列表
```

主題有新論文 → agent 在比較卡加逐論文小節，`status` 確認覆蓋率。任何
**結構性**變動（新 hub、重切、搬卡）之後：

```bash
python3 skills/_shared/topology.py refresh      # 全部主題；或 refresh <topic>
```

**導讀與圖譜維護**——「幫這張 overview 卡刷新導讀」（overview-daodu）；
「跑 graph audit」（overview-graph）在結構變動後檢查 hub／橫向連結／
知識地圖的一致性。

**匯出 BibTeX**：

```bash
cd skills/bib-export
python3 bib_export.py <card-id>                  # 這張卡直接連到的論文
python3 bib_export.py <hub-card-id> --depth 2    # hub → 子總覽卡 → 論文
python3 bib_export.py <card-id> -o refs.bib      # '-' = stdout
```

解析鏈：Semantic Scholar → arxiv `/bibtex` → ACL Anthology → OpenReview。
查不到的一律變 `% TODO` 註解——絕不捏造條目。

### 🧪 Project

一個研究專案一張卡；在哪工作就在哪記錄，到有完整編輯權的機器上整併。

**解析這個 repo 對應哪張卡**（優先序：`$HB_PROJECT_CARD` 環境變數 →
`.heptabase-card` marker（cwd 往上找到 git root 為止）→ registry
`~/.config/research-cards/projects.json`）：

```bash
python3 skills/project-card-log/resolve_card.py
```

**還沒有卡？一步建卡＋固定對應**：

```bash
python3 skills/project-card-log/create_project_card.py --title "My Project"
```

會建出帶 定位/現狀/待補 骨架的卡、上 tag
（`heptabase.collections.projects.tag_name`，預設 `project`），並記下對應
關係——在 git repo 內寫 `.heptabase-card` marker 到 git root；從「本身不是
git repo、git repos 在底下一層」的 project root 跑，則改寫進 registry 的
`match_any` 條目（底下所有 repo 都解析到同一張卡）。monorepo 子專案請傳
`--marker-dir "$(pwd)"`。

**記錄進度**（「把今天的進度記到 project card」）——只增不改、帶日期、有
程式碼依據。**之後整併**（「把 project card 的進度整併成 paper 級」）——
`project-card-merge` 把累積的區塊收攏成一張完整卡。

## Heptabase ↔ Obsidian 同步

`backend: both` 以 Heptabase 為準，把卡片 collection 鏡像進 vault——vault
端的編輯也會寫回：

```bash
cd skills/obsidian-sync
python3 sync.py --dry-run     # 預覽
python3 sync.py               # 真跑——讀輸出的 JSON 報告
python3 verify.py             # vault 完整性檢查；預期 CLEAN
```

- **Collections 由 config 驅動**：每個填了 `tag_id` 的
  `heptabase.collections.<key>` 條目都鏡像到 `obsidian.folders.<key>`
  （選用 `filter` 可依屬性過濾——如 papers → Source Type=alphaXiv）。
  典型組合：papers → `Papers/`、overviews → `Overviews/`、projects →
  `Projects/`。
- **前向**（Heptabase → vault）：增量——沒變的卡以 `lastEditedTime`＋
  內容雜湊跳過。改標題會連動改檔名並改寫 wikilinks。
- **寫回**（vault → Heptabase）：對照快取的 ProseMirror 快照做**區塊級**
  合併；沒動過的區塊原封不動。方言無法無損表示的東西（highlight 嵌入、
  複雜表格、自訂圖片尺寸）→ 整卡**報衝突、不寫回**——一卡全有或全無。
- **收養**：你直接在管理資料夾新建的 `.md` 會變成新的 Heptabase 卡並上
  該 collection 的 tag。
- **衝突總帳**：每次真跑會重生 vault 根目錄的 `Sync Conflicts.md`
  （未解決＋自動歸檔的已解決）。不要手改這份檔。
- **屬性**：帶快照的三方同步——單邊改 → 傳播；兩邊都改 → 報衝突不寫。

讓 round-trip 安全的 markdown 方言：文字顏色 `<span style="color:…">`、
底線 `<u>`、Heptabase toggle 用 `- ⏵ ` 字首（刻意不用 checkbox——沒有可
點擊的東西能弄壞標記）、同卡錨點用 Obsidian block reference
（`[[#^id]]`）、卡片連結用 `[[wikilinks]]`。細節見
`skills/obsidian-sync/SKILL.md`。

## 無人值守排程（剪報管線）

`scholar-inbox-clip/run.py` 可無頭執行：讀設定的 Mail.app 信箱、建卡，
只在文字生成時呼叫設定的 `agent` CLI。三種模式：

- **Agent routine（推薦）**——在 agent 排一個週期性 prompt（如 Claude
  Code routines）：「執行 scholar-inbox-clip 的排程流程」。agent 帶著判斷
  力執行 SKILL.md 合約（去重、Tasks 標記、總覽路由、圖片擺放）——品質最高。
- **launchd（macOS）純腳本**——最省；卡會建，但 Tasks 標記等互動式
  backfill 再補：

  ```xml
  <!-- ~/Library/LaunchAgents/com.you.scholar-clip.plist -->
  <plist version="1.0"><dict>
    <key>Label</key><string>com.you.scholar-clip</string>
    <key>ProgramArguments</key>
    <array><string>/opt/homebrew/bin/python3</string><!-- 要跟你裝 pyyaml/
           pymupdf 的直譯器同一個（venv 路徑也行） -->
           <string>/path/to/research-cards/skills/scholar-inbox-clip/run.py</string></array>
    <key>StartInterval</key><integer>10800</integer>
    <key>StandardOutPath</key><string>/tmp/scholar-clip.log</string>
  </dict></plist>
  ```

- **cron + codex**——同一支腳本配 config `"agent": "codex"`，或直接以
  `codex exec` prompt 當 routine 內容。

注意事項：

- 無人值守的 `osascript` 需要**發動它的那個執行檔**拿過一次自動化權限——
  先用同一個直譯器互動式跑一遍、把 Mail.app 的授權提示按掉。
- 狀態／去重存 `~/.config/research-cards/scholar_inbox_state.json`。已處理
  信件重跑是廉價 no-op，排多密都安全——但**去重 key 在下游步驟失敗時也會
  記錄**，所以排程前先互動式跑通整條管線；否則失敗的首跑會把信標成已處理
  卻沒有卡。
- Digest 來源：Scholar Inbox 完整支援（分數／連結都解析）；任何帶
  arxiv/alphaXiv 連結的 digest 都可抽取。其他來源（如 HuggingFace Daily
  Papers）在 roadmap 上。

## 整合（選用）

**hung-yi-lee teaching skill**——本 plugin 的精神源頭，兩層關係：

1. **風格**：導讀／改寫的寫作規則已內嵌在各 SKILL.md——不裝也有完整的
   教學風格。
2. **執行期**：`overview-graph` 可以把你的總覽卡匯出成 external corpus
   餵進該 skill 的知識圖（`export_hungyi_corpus.py` →
   `hungyi_kb.py graph build --external`），讓「宏毅老師」的問答直接引用
   你自己的卡片庫。

該 skill 不內嵌進本 plugin（它有自己的上游與 PR 流程，且 Codex 的靜態
plugin cache 載不動巢狀 repo）。並排安裝——上游
`voidful/hung-yi-lee-skill` 是 MIT 授權（寫在其 README 尾端）：

```bash
git clone https://github.com/voidful/hung-yi-lee-skill ~/.claude/skills/hung-yi-lee
pip install -r ~/.claude/skills/hung-yi-lee/requirements.txt
```

然後在 config 指過去：

```json
"integrations": { "hung_yi_lee": { "skill_path": "~/.claude/skills/hung-yi-lee" } }
```

沒裝 → 匯出功能不可用；其他一切照常。

## 疑難排解

| 症狀 | 原因／解法 |
|---|---|
| heptabase 模式指令退出並指名某個 config key | 那個 id 沒填——訊息會給出確切的 key；用 `heptabase tag list` / `heptabase tag properties <tagId>` 查 |
| 碰 iCloud vault 出現 `Operation not permitted` | 給終端機（或排程器的直譯器）**完整磁碟取用權限** |
| 排程跑起來讀不到 Mail | 自動化權限跟著「發動的執行檔」走——用同一個直譯器互動式跑一次並核准提示 |
| Codex 跑到舊版 plugin | 它執行靜態 cache 副本——`codex plugin remove`＋`add` 刷新，並確認 `plugin_root` 指向你活的 clone |
| `obsidian-sync` 拒絕執行 | 它只在 `backend: "both"` 有意義——單一 backend 沒有東西可同步 |
| 同步報 conflict | 特性不是 bug：該卡有有損編輯或雙邊分歧。看報告／`Sync Conflicts.md` 裡的區塊與原因，修你要保留的那邊，重跑 |

## License

MIT — 見 [LICENSE](LICENSE)。
