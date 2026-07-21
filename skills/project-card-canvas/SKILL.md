---
name: project-card-canvas
description: >-
  Generate and refresh the VISUAL views of a research-project card chain
  as Obsidian JSON Canvas files: the timeline canvas (git-graph style —
  entry card as HEAD, log cards as commits, colored by distillation state
  or by origin machine) and the context mind map (three decomposition
  modes: logs = per-log-card subtrees hung on the 前情提要 citation graph;
  chain = the chain body's H2/H3 sections; story = the research NARRATIVE
  as a staged, multi-row DAG — the agent reads the chain and authors a
  story graph JSON of ideas→experiments→results→pivots with causal edges,
  the script renders it deterministically). Use when the user asks to
  畫/更新/刷新 project canvas、心智圖、脈絡圖、敘事圖、研究故事圖、
  mind map、story graph、timeline 圖, or after project-card-log /
  project-card-merge runs (refresh the views). Mac-only (heptabase CLI +
  local vault; backend=both).
allowed-tools: Bash(python3 *) Bash(heptabase:*) Bash(ls *) Bash(cat *) Read Write Edit
---

# Project Card Canvas — 專案卡鏈的視覺化視圖家族

一個專案卡鏈可以生成**兩張 canvas、四種視圖**，全部是**生成式視圖**
（每次重跑整張重建、節點 id 確定性——別手排；手排請用知識地圖 canvas）：

| 視圖 | 檔案 | 指令 |
|---|---|---|
| 時間線（git graph） | `<專案>.canvas` | `project_canvas.py --card <ENTRY>` |
| 心智圖 logs 模式 | `<專案>·脈絡心智圖.canvas` | `context_mindmap.py --card <ENTRY>` |
| 心智圖 chain 模式 | 同上（共用檔） | `context_mindmap.py --card <ENTRY> --mode chain` |
| 心智圖 story 模式 | 同上（共用檔） | `context_mindmap.py --card <ENTRY> --mode story --graph <graph.json>` |

輸出資料夾＝`<vault>/<projects>/Canvas/`（config
`local.folders.project_canvas` 可覆蓋）。三種心智圖模式共用一個 canvas
檔（一專案一張脈絡圖；切模式＝整圖重建）；canvas 左上皆有色彩圖例節點。

## 怎麼選視圖

- **時間線**：想看「發生過什麼、哪些已蒸餾」——entry＝HEAD（紫）、
  log 卡＝commits 由新到舊。`--color-by state`（預設：📎橙＝待蒸餾／
  📗綠＝已入正文）或 `--color-by origin`（Mac=cyan／cluster=yellow；
  讀 log 卡的 `環境` 欄或回溯卡 `原段：📥 …` 行）；config
  `heptabase.collections.projects.canvas_color_by` 改預設軸。
- **心智圖 logs**：專案用 log-as-card 週報體系——每張 log 卡拆成
  ❓這次要回答／🔬做了什麼／📊結果／💡這代表什麼／⚖️待裁決 分支，
  掛點＝前情提要引用的最新 log（引用圖）。`--limit 1`＝最早根卡。
- **心智圖 chain**：舊 log 已蒸餾進卡鏈正文的專案——拆 H2（角色配色）
  →H3 結構目錄。
- **心智圖 story**：要看**研究思考脈絡**（因為想法→做了實驗→結果→
  轉向/分岔/回頭）——推理鏈藏在散文裡，需要 agent 讀鏈撰寫敘事
  graph（下節），script 只做確定性佈局。**這是本 skill 的主打視圖。**

## story 模式：敘事 graph 撰寫契約（agent 的工作）

**分工**：你（讀鏈的 agent）負責理解與撰寫 graph JSON；script 負責
驗證＋分層 DAG 佈局（重生成、id 穩定、--limit 重播由 code 保證）。

### 工作流

1. **讀鏈**：把 chain 各卡的 sections 全文讀懂（重點：定位/演進故事、
   進展里程碑、各實驗統整的結論句、Findings/設計理路、🔍/下一步）。
2. **撰寫/更新 graph JSON**：存 `<vault>/<projects>/Canvas/
   <專案>·脈絡心智圖.graph.json`（canvas 同資料夾）。已存在＝**只增
   不改**：新進展在尾端加節點/邊；既有節點 id（slug）與內文非必要不動。
3. **渲染**：`context_mindmap.py --card <ENTRY> --mode story --graph <path>`；
   讀 report 的 `label_warnings`（過長箭頭字）與 `stages`。

### graph schema（schema of record 在 context_mindmap.py 的
load_story_graph 上方註解；此處為撰寫規則）

```json
{"nodes": [{"id": "slug", "kind": "…", "label": "短標題", "text": "一兩句",
            "anchor": "出處 section", "date": "MM-DD", "stage": "幕標題"}],
 "edges": [{"from": "slug", "to": "slug", "label": "所以"}]}
```

- **id**＝穩定 slug（如 `exp-e7-attribution`）——圖的擴充契約靠它。
- **sources**＝此節點蓋掉的 log 卡 id（coverage 稽核的鍵；一個節點
  蒸餾了哪幾張 log 就列哪幾張）；anchor＝蓋掉的 section（・分隔多個）。
- **kind**：`idea`💡/`question`❓（橙）、`experiment`🧪（黃）、
  `result`📊（灰）、`finding`✅/`decision`⚖️（綠）、`pivot`🔀/
  `open`⏳（紅）。
- **節點順序＝敘事序**（驅動 --limit 重播與 row 內堆疊）。
- **stage**：只標**每幕第一個節點**，其餘沿敘事序繼承——一幕一 row
  （multi-row 換行；幕標題掛列首、跨幕邊自動向下流）。幕＝研究的
  章節轉折（沿用 entry 卡「演進故事」的分幕最自然）。
- **text 自足**：一兩句把「為什麼/是什麼/所以呢」講完，數字帶上；
  anchor 填出處 section 名（可追溯）。
- **邊 label＝短連接詞**（所以/但是/坐實/回頭重審/隔離歸因…）——
  預算 ~12 顯示單位（CJK≈2），過長會被 report 警告；語義放節點 text。
- **分岔與回頭要畫**：同一結果引出多條線＝多條出邊；回頭重審／方法論
  重演＝跨幕邊（自動 bottom→top 下行）。
- 引用先前結論時，該結論就該是一個節點——寧可多切節點，別把兩步
  推理擠在一個節點裡。

## 擴充工作流：coverage 稽核（新 log／蒸餾後怎麼知道缺什麼）

story render 的 report **自帶 `coverage` 稽核**——machine 告訴你圖裡
還缺什麼材料，你只讀缺的部分、不用重讀整條鏈：

```bash
python3 <此 skill 目錄>/context_mindmap.py --card <ENTRY> --mode story \
    --graph <graph.json> --dry-run     # 只稽核不寫檔
```

- `uncovered_logs`：時間線上**沒有任何節點認領**的 log 卡（附日期＋
  摘要）。認領＝節點的 `sources` 列其 id（或 ≥8 碼前綴）。log 卡永不
  trash，id 跨蒸餾穩定——這是為什麼 sources 用 log id 當鍵。
- `uncovered_sections`：卡鏈 H2 裡**沒有任何 anchor 蓋到**的 section
  ——merge 蒸餾後新長的段（如「實驗統整(八)」）會在這裡現形。
  刻意不入圖的參考型段落（方法／評估協定…）放 graph 頂層
  `coverage_ignore` 顯式豁免，稽核才能收斂到空。

**擴充循環**：`--dry-run` 看 coverage → 只讀未覆蓋的 log 卡／section
→ graph 尾端加節點（記得 `sources`＋`anchor`；開新幕標 `stage`）→
重渲染 → coverage 回到空。**加節點時同步補邊**：新節點的前情提要引用
誰、承接哪個結論，邊就畫到哪。

**最便宜的補圖時機＝寫 log 的當下**：project-card-log 寫完 log 卡後，
那個 session 脈絡全在手上——順手在 graph 尾端補節點（sources=[新 log
卡 id]）＋承接邊、重渲染，缺口就不會累積（log skill 的 Step 4 有對應
步驟）。

**Fallback：紅色待補橫幅**——render 時稽核不乾淨，canvas 圖例旁會自動
長一個紅色「⚠️ 待補」節點列出缺口（canvas-only、不進 graph JSON；
補完重渲染即消失）。看到它＝這張圖落後現實，照上面循環補。

## 刷新時機

- `project-card-log` 寫完 log、`project-card-merge` 整併完 → 重跑
  **時間線**（顏色/鏈型會變）；story 模式跑 `--dry-run` 稽核 →
  按上節循環擴充 graph → 重渲染。
- cluster 端無 vault：跳過，回 Mac 再刷。

## 已知邊界

- Mac-only：讀卡走本機 heptabase CLI、canvas 檔住 vault（backend=both）。
- story graph 的正確性責任在撰寫的 agent——這是「理解」不是「解析」；
  讀歪了就改 graph 重渲染。
