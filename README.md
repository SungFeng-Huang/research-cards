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
[研究實驗 Campaign](#研究實驗-campaign) ·
[無人值守排程](#無人值守排程剪報管線) ·
[整合](#整合選用) ·
[疑難排解](#疑難排解) ·
[License](#license)

## Skills 總覽

**📥 論文剪報**——訊息流進來，變成教學卡

| Skill | 做什麼 |
|---|---|
| `scholar-inbox-clip` | digest 信件／URL → 教學卡片（屬性、圖片、journal 記錄、總覽路由） |
| `card-rewrite` | 把既有卡片改寫成完整教學格式（一句話 / 為什麼該讀 / 先備知識 / WHY 驅動敘事 / 雙語術語） |

**🗺️ 主題總覽與知識圖**——單篇卡片長成領域地圖

| Skill | 做什麼 |
|---|---|
| `overview` | 維護各主題比較總覽卡：逐論文小節、維度比較表、覆蓋率檢查、arxiv 序排序 |
| `overview-daodu` | 在總覽卡頂端插入／刷新敘事導讀（冪等） |
| `overview-graph` | 圖結構：主題 hub、橫向 ↔/→ 連結、知識地圖（Heptabase whiteboard / Obsidian JSON Canvas）、一致性稽核。**也服務 project 方向**：Operation 5 用知識圖幫專案卡做 research-gap 分析 |

**🧪 研究專案**——你自己的研究，也是卡

| Skill | 做什麼 |
|---|---|
| `project-card-log` | 在專案 repo 的 session（本機或遠端）解析出這個專案的卡，附加有日期、有程式碼依據的進度——只增不改 |
| `project-card-merge` | 另一半：把累積的進度區塊整併成一張 paper 級的完整卡（全編輯端） |
| `research-campaign` | 自主實驗戰役的任務書格式＋記帳慣例：MISSION.md 進 repo、queue/ledger 斷點續跑、顯著性 gate 量測紀律，進度自動回流專案卡 |

**✍️ 論文寫作**——寫 paper 時收割知識庫

| Skill | 做什麼 |
|---|---|
| `bib-export` | 以任一張卡為錨點（總覽卡、專案卡皆可）匯出它連到論文的官方 BibTeX——絕不捏造，查不到的變成 `% TODO` 註解 |

**🔁 同步基礎設施**

| Skill | 做什麼 |
|---|---|
| `obsidian-sync` | Heptabase ↔ Obsidian 雙向同步（僅 backend `both`） |

開關歸屬：config `features.study` 蓋剪報＋總覽＋知識圖；`features.project`
蓋研究專案兩件組；`bib-export` 與 `obsidian-sync` 不吃方向開關（前者跟著
你給的錨點卡走，後者跟著 backend 走）。

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
| 選用整合 skills | **hung-yi-lee**（教學風格的執行期整合）與 **alchemist-playbook**（campaign 的超參引用紀律）——安裝法與缺席語義見[整合](#整合選用) |

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

日常就是**叫 skill**，不是跑指令：

- **自然語言（推薦）**——直接跟 agent 說你要什麼，它會挑對 skill、照
  SKILL.md 的合約執行。下面每節都給例句。
- **指名 skill**——Claude Code 用斜線：`/research-cards:<skill>`（如
  `/research-cards:obsidian-sync`）；Codex 在訊息裡點名 skill 即可。
- **底層 CLI**——只在無人值守排程或 debug 時需要，收在每節的
  「底層指令」摺疊區（agent 平常就是替你跑這些）。

### 📥 剪報

| 你說 | 怎麼用指定 skill 來做到 |
|---|---|
| 「把 https://arxiv.org/abs/XXXX.XXXXX 做成卡片」 | `/research-cards:scholar-inbox-clip https://arxiv.org/abs/XXXX.XXXXX` |
| 「掃一下 scholar inbox 信箱」——讀信、去重、建卡、上 Tasks、路由到總覽卡 | `/research-cards:scholar-inbox-clip` |
| 「把〈某某卡〉重寫成教學格式」——結構升級、事實不動 | `/research-cards:card-rewrite 〈卡片標題〉` |

<details><summary>底層指令</summary>

```bash
python3 skills/scholar-inbox-clip/run.py    # 無頭排程模式（見排程一節）
```
</details>

### 🗺️ 總覽與知識圖

| 你說 | 怎麼用指定 skill 來做到 |
|---|---|
| 「把這篇新論文加進 <topic> 的總覽卡」 | `/research-cards:overview <topic> 加入〈論文〉` |
| 「<topic> 的覆蓋率如何？哪些論文還沒進比較卡？」 | `/research-cards:overview <topic> status` |
| 「幫這張總覽卡刷新導讀」 | `/research-cards:overview-daodu 〈總覽卡標題〉` |
| 「幫 tokenizer 和 spoken 加一條橫向連結」 | `/research-cards:overview-graph 加橫向連結 tokenizer ↔ spoken` |
| 「跑 graph audit」——結構變動後檢查 hub／橫向連結／知識地圖一致性 | `/research-cards:overview-graph audit` |
| 「把〈某塊 whiteboard〉鏡像成 Obsidian Canvas」——實際版面（座標/分區/連線＋自動 mention 線）單向覆寫；預設讀 app 的本機資料庫（即時、app 開著也行），備份檔為備援 | `/research-cards:overview-graph mirror` |

結構性變動（新 hub、重切、搬卡）後 agent 會跑 topology refresh——那是
總覽路由的資料來源，不能省。

<details><summary>底層指令</summary>

```bash
cd skills/overview
python3 sync_overview.py <topic> status   # 覆蓋率 diff → 哪些論文 MISSING
python3 sync_overview.py <topic> sort     # 依 arxiv ID 重排列表
python3 ../_shared/topology.py refresh    # 全部主題；或 refresh <topic>
```
</details>

### 🧪 研究專案

| 你說 | 怎麼用指定 skill 來做到 |
|---|---|
| 「把今天的進度記到 project card」——在專案 repo 的 session 裡說即可；agent 會解析對應的卡（marker → registry），沒有卡會問你要不要建 | `/research-cards:project-card-log`（在專案 repo 內，無參數） |
| 「幫這個專案建一張 project card」——建卡＋骨架＋上 tag＋固定對應一步完成 | `/research-cards:project-card-log 建卡 "My Project"` |
| 「把 project card 的進度整併成 paper 級」——收攏累積的進度區塊 | `/research-cards:project-card-merge 〈專案名〉` |
| 「用知識圖幫我的 project card 做 research-gap 分析」——拿領域地圖對照專案卡，找出還沒被回答的缺口（Operation 5） | `/research-cards:overview-graph gap 〈專案卡〉` |
| 「幫這個 repo 開一個研究實驗 campaign」——檢查 repo 就緒度 → 互動 intake → 產 MISSION.md 任務書＋queue/ledger | `/research-cards:research-campaign init` |
| 「接續 campaign」／「campaign 進度如何」 | `/research-cards:research-campaign`（在該 repo session 內）／`… status` |

對應關係去哪了：git repo 內是 git root 的 `.heptabase-card` marker；
「project root 不是 git repo、repos 在底下一層」的佈局則進 registry
`~/.config/research-cards/projects.json`（底下所有 repo 解析到同一張卡）。

<details><summary>底層指令</summary>

```bash
python3 skills/project-card-log/resolve_card.py                      # 這個 repo ↔ 哪張卡
python3 skills/project-card-log/create_project_card.py --title "My Project"
#   monorepo 子專案請傳 --marker-dir "$(pwd)"
```
</details>

### ✍️ 論文寫作

| 你說 | 怎麼用指定 skill 來做到 |
|---|---|
| 「幫〈這張總覽卡〉匯出 BibTeX」 | `/research-cards:bib-export 〈卡片標題〉` |
| 「把 <hub 卡> 底下整個主題的參考文獻都匯出來」（hub → 子總覽卡 → 論文） | `/research-cards:bib-export 〈hub 卡〉 --depth 2` |

解析鏈：Semantic Scholar → arxiv `/bibtex` → ACL Anthology → OpenReview。
查不到的一律變 `% TODO` 註解——絕不捏造條目，可以放心貼進 `.bib`。

<details><summary>底層指令</summary>

```bash
cd skills/bib-export
python3 bib_export.py <card-id>                  # 這張卡直接連到的論文
python3 bib_export.py <hub-card-id> --depth 2    # hub → 子總覽卡 → 論文
python3 bib_export.py <card-id> -o refs.bib      # '-' = stdout
```
</details>

### 🔁 同步

| 你說 | 怎麼用指定 skill 來做到 |
|---|---|
| 「跑 obsidian-sync」 | `/research-cards:obsidian-sync` |
| 「先 dry-run 看一下要動哪些卡」 | `/research-cards:obsidian-sync --dry-run` |
| 「有衝突嗎？帶我看 Sync Conflicts」 | `/research-cards:obsidian-sync 看衝突` |

機制細節見下一節；agent 跑完會讀 JSON 報告、把衝突與待辦攤給你。

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

## 研究實驗 Campaign

`research-campaign` 把「一個 project 的長期自主實驗戰役」標準化：任務書
（MISSION.md）住進 project、實驗階梯與結果帳本可斷點續跑、量測紀律硬性
把關、進度自動回流專案卡。它**不是訓練執行器**——訓練怎麼跑由你的
MISSION 說了算；skill 管格式、記帳、與知識庫的接口。

完整閉環（這是本 plugin 獨有的敘事）：

```
知識庫  ──Op5 gap 分析──▶  MISSION 實驗設計
   ▲                              │
   │                       （campaign 執行）
   └──project-card-log 回卡──  ledger 結果
        （merge 整併 → bib-export 收參考文獻 → paper）
```

### 1. Setup — 開一個 campaign

在 project 目錄的 session 說「幫這個 repo 開一個研究實驗 campaign」
（或 `/research-cards:research-campaign init`），agent 會走四步：

1. **就緒度檢查**（`assets/repo-checklist.md`）——campaign 假設 project
   已有七個必備件：

   | 必備件 | 要求 |
   |---|---|
   | train 入口 | 吃 `--config`／`--resume <ckpt>`、checkpoint 頻率可調 |
   | eval 入口 | 吃 manifest、分層抽樣、輸出 **per-utterance CSV** |
   | 顯著性工具 | paired-delta 95% CI（沒有→列為 E0 前置） |
   | manifest 建構器 | 能建 balanced 切片（固定 seed） |
   | configs/ | 一個實驗 rung 一份 recipe |
   | 測試入口 | E0 合約＝測試不過不准訓練 |
   | reports/ | post-mortem 與每 rung 摘要的家 |

   缺件由你選：先補齊，或列為 E0 前置子項。
2. **佈局選擇**——兩種都支援：
   - *單一 repo*：campaign 狀態（`runs/auto_research/`）在版控內，per-job
     的 git pull/push 蓋全部。
   - *拆分式*（project root 是普通目錄、核心 code 才是 repo）：git 動作只
     作用於 core repos；**ledger 是工作簿（共享檔案系統續命）、專案卡是
     帳本正本（跨機器恆久層）**。想升級成 repo：`init --git` 會 git init
     ＋依實際目錄生成起手 .gitignore（大 artifact 與巢狀 core repo 自動
     排除），首 commit 留給你核可。
3. **勘查＋一次批量問答**——README/configs/reports 能推斷的不問；必問：
   目標與非目標、基線數字與主副指標、執行環境（牆鐘上限/搶佔）、ladder
   草案、**過去的失敗模式**（寫進 banned practices，最有價值的一欄）。
4. **MISSION 草稿給你核可**（標明哪些是推斷）→ 落檔：

   ```bash
   python3 skills/research-campaign/scripts/campaign.py init \
     --repo <project-root> [--git] [--rungs E0 E1 E2]
   # 產生 runs/auto_research/{MISSION.md, queue.json, ledger.jsonl}
   ```

   模板八段各有行內填寫指引；完整範例見
   `skills/research-campaign/assets/examples/example-mission.md`。

### 2. Run — 接續一個 campaign job

在 project session（本機或 cluster job）說「接續 campaign」。agent 讀
`runs/auto_research/MISSION.md` 照做，並疊加通用紀律：

- **Step 0（每個 fresh job）**：解析專案卡；卡上有近期 `🔍` gap 分析先讀
  ——知識庫已覆蓋的 prior art 不重新發現。
- **量測紀律（違反任一條結果無效）**：分層抽樣的代表性 eval 切片；corpus
  級指標；**任何「贏」須 paired-delta 95% CI 排除 0**（基線重評 ≥3 次記
  eval 非確定性、delta 小於 CI 寬度不 promote）；一次改一件事；架構級
  變更必 from-scratch；超參引用 [alchemist-playbook](#整合選用) 式有出處
  的建議。
- **記帳**：每個評測一行 ledger（工具把關 schema——五個必要欄位、
  `significant` 必為布林、缺 playbook 引用出警告）：

  ```bash
  python3 …/campaign.py ledger-append --dir runs/auto_research \
    --json '{"experiment":"E1","config_hash":"…","metrics":{"wer":0.31},
             "significant":true,"decision":"advance",
             "playbook_rules_cited":["speech.whisper.lr"]}'
  ```
- **收尾**：push 程式碼後把本 job 結果經 `project-card-log` append 到
  專案卡；卡住寫 `BLOCKED.md` 停下等人。

### 3. Status — 看進度

```bash
python3 …/campaign.py status --dir runs/auto_research
```

出佇列各狀態計數、running/下一個 pending、最近 ledger 摘要、BLOCKED
提示。問「campaign 進度如何」agent 會跑這個並講清楚「距離 success gate
還差什麼」。

### 4. Showcase — 對外展示層（選配）

```bash
python3 …/campaign.py report --dir runs/auto_research \
  --out docs/campaign-report.html
cp skills/research-campaign/assets/pages-workflow.yml \
  <project>/.github/workflows/pages.yml
# repo Settings → Pages → Source 選 "GitHub Actions"；push docs/ 即發佈
```

報告頁含 ladder 狀態徽章、ledger 全表（顯著性徽章＋playbook 引用）、
BLOCKED 橫幅；輸出無時間戳（確定性，發佈時間交給 git 歷史）。領域特定
demo 頁（音檔 A/B 對聽等）自行加在 `docs/`，同一條 workflow 一起發佈。
**紀律**：對外展示的結果只在通過顯著性 gate 後更新。

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
- Digest 來源：**Scholar Inbox**（分數／連結都解析）與 **HuggingFace
  Daily Papers**（arxiv ID 直取自連結；因榜單非個人化，入選前先過
  `email.hf_min_upvotes` 讚數門檻＋依 config `profile.field` 的領域相關
  性篩選——agent 判全不相關就整封略過）完整支援；其他任何帶
  arxiv/alphaXiv 連結的 digest 也可抽取。多來源共用同一個信箱資料夾，
  逐封自動分流。

## 整合（選用）

**alchemist-playbook（煉丹調參顧問）**——`research-campaign` 的超參紀律
夥伴：campaign 合約要求每個超參／schedule 決策引用有出處的建議（ledger
的 `playbook_rules_cited` 欄位），alchemist-playbook 正是為此而生——從
公開訓練紀錄（LLaMA/OLMo/DeepSeek-V3/Whisper/wav2vec 2.0/HuBERT…）蒸餾
的 recipe 顧問，每個數字都標 `[config]`/`[paper]`/`[reported]` 可信度。
side-by-side 安裝（skill 是 repo 的子資料夾）：

```bash
git clone https://github.com/voidful/AlchemistPlaybook ~/AlchemistPlaybook
ln -s ~/AlchemistPlaybook/alchemist-playbook ~/.claude/skills/alchemist-playbook
# Codex 端同樣 link 進 ~/.agents/skills/
```

沒裝 → campaign 照常運作，超參引用紀律降級為「其他有出處的建議」（自行
標注來源）；MISSION 模板的 REQUIRED READING 建議常備此項。

**hung-yi-lee teaching skill**——本 plugin 的精神源頭，兩層關係：

1. **風格**：導讀／改寫的寫作規則已內嵌在各 SKILL.md——不裝也有完整的
   教學風格。
2. **執行期**：`overview-graph` 可以把你的總覽卡匯出成 external corpus
   餵進該 skill 的知識圖（`export_hungyi_corpus.py` →
   `hungyi_kb.py graph build --external`），讓「宏毅老師」的問答直接引用
   你自己的卡片庫。

該 skill 不內嵌進本 plugin（它有自己的上游與 PR 流程，且 Codex 的靜態
plugin cache 載不動巢狀 repo）。並排安裝，**建議裝本專案作者的 fork 的
`local/conda-env-integration` 分支**——執行期整合需要的擴充（external
corpus、來源出處標記等）在該分支上，尚未全部進上游；本 plugin 也是對著它
測試的：

```bash
git clone -b local/conda-env-integration \
  https://github.com/SungFeng-Huang/hung-yi-lee-skill ~/.claude/skills/hung-yi-lee
pip install -r ~/.claude/skills/hung-yi-lee/requirements.txt
```

（只要教學風格、不需要匯出整合的話，裝上游
`voidful/hung-yi-lee-skill` 也可以——MIT 授權，寫在其 README 尾端。）

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
