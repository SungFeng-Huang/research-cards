---
name: note-sync
description: "ONE entry point for the whole note-surface sync chain (Heptabase ↔ vault/local ↔ HackMD), replacing separate obsidian-sync / hackmd-sync invocations: runs every applicable segment per the config backends list (first = canonical), converges HackMD write-backs onto Heptabase in the same run, and aggregates all segments' conflicts into one report. --mode obsidian|hackmd runs a single segment. Use when the user asks to sync notes / sync everything / 同步筆記、全部同步、跑同步、note sync、把三方筆記收斂, or any obsidian-sync / hackmd-sync request."
---

# note-sync — 筆記面同步的單一入口

同步鏈＝相鄰兩兩雙向的段，由 config `backends` list 推導（首位＝正本）：

```
Heptabase ◀─(obsidian 模式)─▶ vault／local ◀─(hackmd 模式)─▶ HackMD
```

| 模式 | 引擎（檔案原位不動） | 需要 |
|---|---|---|
| `obsidian` | `skills/obsidian-sync/sync.py`——區塊級 level-2 雙向 | `backends` 同時含 `"heptabase"` 與 `"local"` |
| `hackmd` | `skills/hackmd-sync/sync.py`——段落級 write-back、宣告式權限、Book 目錄 | `backends` 含 `"hackmd"` |
| `heptabase`（反向：vault 正本鏡像進 Heptabase） | roadmap——`backends: ["local", "heptabase"]` 在此之前會被 config 明確拒絕 | — |

## 日常

| 你說 | 指令 |
|---|---|
| 「同步筆記」「全部同步」 | `python3 <此 skill 目錄>/sync.py` |
| 「只同步到 HackMD」 | `python3 <…>/sync.py --mode hackmd` |
| 「只跑 Heptabase↔vault」 | `python3 <…>/sync.py --mode obsidian` |
| 「先看會動哪些」 | `python3 <…>/sync.py --dry-run` |

全鏈執行順序＝由正本向外（obsidian → hackmd）；若 hackmd 段有 write-back
落進 vault，**同一次呼叫自動補跑一次 obsidian 段**把它送回 Heptabase——
不用你記得跑第二次。

輸出：一份彙總 JSON——`plan`（實際跑的段）、`segments`（各段完整報告）、
`total_conflicts`＋`conflicts`（跨段衝突總覽，agent 跑完攤給使用者）。

## 邊界

- 各段的細節語義（衝突規則、write-back 信任邊界、權限宣告、Book 目錄、
  限流退避）都在各引擎的 SKILL.md／wiki——note-sync 只做編排，不改語義。
- 單段引擎仍可直接執行（cron 相容；hackmd 段的 state 鎖防止與
  note-sync 併發互踩）。
- 觸發時機：手動／agent 呼叫，無自動排程——想掛 cron 就對本 skill 的
  `sync.py` 掛一條即可（一條就涵蓋全鏈）。
