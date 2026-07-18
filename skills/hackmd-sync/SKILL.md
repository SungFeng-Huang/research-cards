---
name: hackmd-sync
description: "Mirror research-cards collections to HackMD (the plugin's third note surface, aimed at sharing/publishing): one-way incremental sync from the active backend (heptabase/obsidian/both) into HackMD folders, with real note-to-note links for mirrored cards and change DETECTION on the HackMD side (edited notes are reported as conflicts, never overwritten). Use when the user asks to sync/publish cards to HackMD, 同步到 HackMD、把總覽卡發到 HackMD、鏡像到 hackmd、check HackMD drift, or set up the hackmd section of the config."
---

# hackmd-sync — 把卡片庫鏡像到 HackMD

第三個筆記介面，定位是**分享**：把選定的 collection（典型是 overviews）
發佈成 HackMD notes，互連卡變成真的 note-to-note 連結。第一級語義
（與 obsidian-sync 的演進史同款）：

- **單向增量**：本地 backend（heptabase／obsidian／both 的正本側）為準；
  來源 markdown md5 沒變就跳過。
- **變更偵測、不寫回**：HackMD 端的 `lastChangedAt` 在上次同步後動了
  → 該卡報 conflict、**不覆蓋**——手動合併後重跑（或刪 state 條目強制
  覆蓋）。寫回是 level 2 的課題，刻意不在此版。
- **連結改寫**：`[[wikilink]]`／card mention 的目標若也在鏡像集合裡
  → 改成 `[標題](https://hackmd.io/<noteId>)`；不在 → 退化成純文字標題。

## 前置

1. `npm install -g @hackmd/hackmd-cli`
2. Token（hackmd.io → Settings → API → Create API token）：
   `hackmd-cli login` 一次（存 `~/.hackmd/config.json`）或設
   `HMD_API_ACCESS_TOKEN` env——**token 絕不放 research-cards config**。
3. Config `hackmd` 段（`setup` skill 可帶你設；`hackmd-cli folders` 查
   folder id）：

   ```json
   "hackmd": {
     "collections": { "overviews": { "folder_id": "<folder-id>" } },
     "read_permission": "owner",
     "write_permission": "owner"
   }
   ```

## 日常

| 你說 | 指令 |
|---|---|
| 「同步到 HackMD」 | `python3 <此 skill 目錄>/sync.py` |
| 「先看會動哪些」 | `python3 <…>/sync.py --dry-run` |
| 「只同步這張卡」 | `python3 <…>/sync.py --card <id>` |
| 「HackMD 那邊有沒有被改過」 | `python3 <…>/sync.py verify` |

輸出 JSON：`created`／`updated`／`skipped`／`conflicts`（HackMD 端
編輯過的卡）／`errors`。Agent 跑完把 conflicts 攤給使用者。

## 邊界與注意

- **State**：`~/.config/research-cards/hackmd-state.json`（cardId ↔
  noteId／md5／lastChangedAt）。刪掉某卡的條目＝下次強制重建/覆蓋。
- **方言**：顏色 `<span style>`／`<u>` HackMD 原生渲染；toggle 的
  `- ⏵ ` 字首是純文字 bullet（可讀、不可折疊）；圖片 data-URL 過大時
  HackMD 可能拒收——大圖卡先觀察 `errors`。
- **權限**：出廠預設 `owner/owner`＝私密（只有你）；要分享才改 `signed_in`／`guest`——`guest` 等於公開發佈，想清楚再開；
  對外連結是 `https://hackmd.io/<noteId>`。
- **刪除**：本地刪卡不會刪 HackMD note（level 1 不做刪除傳播）；
  `verify` 的 `missing_remote` 反向列出 HackMD 端被刪的 note。
- Agent（claude／codex）皆可；無 MCP 依賴。cluster 亦可跑（hackmd-cli
  走網路、不依賴 Mac）——但來源 backend 是 heptabase 時要 Mac（CLI 讀卡）。
