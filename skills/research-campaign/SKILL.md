---
name: research-campaign
description: >-
  Scaffold and drive autonomous research-experiment campaigns: a MISSION.md
  brief that lives IN the target repo (runs/auto_research/), a persistent
  experiment ladder (queue.json) and results ledger (ledger.jsonl), hard
  measurement discipline (significance gating, representative eval slices,
  one change per rerun), and research-cards integration (project card
  bootstrap + Op5 gap-analysis pre-read + per-job progress append). Use when
  the user wants to 開/設定一個研究實驗 campaign for a repo, 接續/continue a
  campaign job, or asks campaign 進度/status. This skill owns the FORMAT and
  BOOKKEEPING — the agent executes experiments by following the repo's
  MISSION.md, and hyperparameter decisions defer to an alchemist-playbook
  style source-cited advisor when available.
---

# Research Campaign — 任務書格式＋記帳慣例＋知識庫掛鉤

把「一個 repo 裡的長期自主實驗戰役」標準化：任務書（MISSION.md）進 repo、
狀態（queue/ledger）可斷點續跑、量測紀律硬性把關、進度自動回流知識庫。
**本 skill 不是訓練執行器**——訓練怎麼跑由各 repo 的 MISSION.md 說了算；
這裡管的是格式、記帳、與 research-cards 的接口。

## Files

- `assets/MISSION.template.md` — 任務書模板（八段，含逐段填寫指引）。
- `assets/examples/example-mission.md` — 中性完整範例（Whisper LoRA 領域
  適應 campaign），照抄結構、換掉內容。
- `assets/repo-checklist.md` — **campaign-ready repo 檢查清單**：repo 要有
  哪些元件（可續訓 train 入口、per-utterance CSV 的 eval、顯著性工具、
  manifest 建構器…）campaign 才跑得動；intake 第一步就是對照它。
- `scripts/campaign.py` — 記帳工具（stdlib）：`init`（scaffold）、
  `status`（佇列＋帳本摘要）、`ledger-append`（schema 校驗寫入）。

## Mode 1 — Setup（互動式 intake → MISSION.md）

使用者說「幫這個 repo 開一個 campaign」時：

1. **先驗 repo、再勘查、再提問**：先對照 `assets/repo-checklist.md` 檢查
   repo 具不具備 campaign 的必備元件（train --resume／eval 出 per-utterance
   CSV／顯著性工具／manifest 建構器／測試入口）——缺件讓使用者選「先補齊」
   或「列為 E0 前置」。然後讀 README／configs／reports，能推斷的欄位直接
   預填草稿。**只問補不齊的**，且一次批量問完（AskUserQuestion／一則
   訊息），不要擠牙膏。最少要確認的欄位：
   - 目標與研究問題（FIXED GOAL 一段話＋非目標＝防漂移邊界）
   - 基線數字與主指標（現況多少、贏什麼才算贏、副指標護欄）
   - 執行環境（Slurm/local、單 job 牆鐘上限、會不會被搶佔）
   - 實驗 ladder 草案（E0..En 各自的 gate）
   - 過去的失敗模式（要寫進 banned practices——最有價值的一欄）
2. **產出 MISSION 草稿**（照模板八段）給使用者過目核可——草稿必須把
   「哪些是勘查推斷、哪些是使用者說的」標清楚。
3. 核可後落檔：
   ```bash
   python3 scripts/campaign.py init --repo <target-repo> [--rungs E0 E1 …]
   # 然後把核可的 MISSION 內容寫進 <repo>/runs/auto_research/MISSION.md
   ```
4. **Project card bootstrap**：用 research-cards `project-card-log` 的
   resolve/create 流程確認該 repo 有 Heptabase 專案卡（無卡即建＋pin），
   並在卡的現狀段落記 campaign 開跑與 MISSION 位置。

## Mode 2 — Run（接續一個 campaign job）

在目標 repo 的 session（本機或 cluster job）說「接續 campaign」時：

1. 讀 `runs/auto_research/MISSION.md`——它是唯一的任務書，**照它執行**；
   本 skill 只疊加下面的通用紀律與掛鉤。
2. **Step-0 掛鉤（每個 fresh job）**：resolve 專案卡；卡上若有近期 `🔍`
   research-gap 分析（overview-graph Operation 5），先讀——知識庫已覆蓋的
   prior art 不要重新發現。
3. **量測紀律（violating any invalidates the result）**：
   - 代表性 eval 切片（分層抽樣、固定 seed），絕不用 manifest 開頭切片；
   - corpus 級指標，不用 per-utterance 未加權平均；
   - **顯著性 gate**：任何「贏」必須 paired-delta 95% CI 排除 0 才可信；
     基線重評 ≥3 次記錄 eval 非確定性；delta 小於 CI 寬度絕不 promote；
   - 一次只改一件事；架構級變更必 from-scratch，不 warm-start 跨架構；
   - 超參與 schedule 決策引用 alchemist-playbook（或同級有出處的建議），
     把引用寫進 ledger 的 `playbook_rules_cited`。
4. **記帳**：每個完成的評測寫一行 ledger（schema 由工具把關）：
   ```bash
   python3 scripts/campaign.py ledger-append --dir <repo>/runs/auto_research \
     --json '{"experiment":"E1","config_hash":"…","metrics":{…},
              "significant":false,"decision":"…","playbook_rules_cited":[…]}'
   ```
   更新 queue.json 狀態（pending|running|done|failed）。
5. **Step-7 掛鉤（job 收尾）**：code/config/ledger push 之後，把本 job 的
   ledger row＋決策＋下一步，經 `project-card-log` append 到專案卡
   （cluster 走 hb bridge、append-only）。整併（project-card-merge）與
   `🔍` 折疊留在 Mac 端，不是 job 的事。
6. 卡住需要人類決策 → 寫 `runs/auto_research/BLOCKED.md` 並停。

## Mode 3 — Status

```bash
python3 scripts/campaign.py status --dir <repo>/runs/auto_research
```
出佇列各狀態計數、最近 ledger 摘要（experiment/significant/decision）、
BLOCKED 提示。回報時把「距離 campaign success gate 還差什麼」講清楚。

## 分工界線（防止本 skill 膨脹）

- MISSION 內容（目標/設計/ladder/指令）＝使用者資料，住在各 repo。
- 訓練執行、sbatch 包裝、續投＝MISSION 的 per-job procedure 管，agent 照做。
- 本 skill 永遠只有：模板＋intake 合約＋記帳工具＋量測紀律＋KB 掛鉤。
