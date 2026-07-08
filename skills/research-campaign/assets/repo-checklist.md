# Campaign-ready repo checklist（intake 時逐項驗證；參考實例：voidful/vocodec）

campaign 不自帶訓練／評測能力——它假設 repo 已具備下列元件。Setup intake 的
第一步就是對照這張表：**缺「必備」項先補齊（或列為 E0 前置工作）再開跑**。

## 必備（缺一個 campaign 就跑不動）

| 元件 | 要求 | vocodec 對應 |
|---|---|---|
| 可續訓的 train 入口 | 吃 `--config <yaml>`、`--resume <ckpt>`；`checkpoint_every` 可調（搶佔友善） | `qwen_vocab_codec/train.py` |
| 可重現的 eval 入口 | 吃 manifest、支援分層抽樣（`--sample_strategy stratified`）、輸出 **per-utterance CSV**（顯著性檢定的原料） | `evaluate.py`＋`asr_eval.py`（corpus 級指標） |
| 顯著性工具 | paired-delta 95% CI（baseline vs candidate 的逐樣本配對）；沒有就把「建一個」列為 E0 前置 | `significance.py` |
| manifest 建構器 | 能產 balanced/分層 eval 切片（固定 seed、一次建好重複用） | `data.py build-eval-manifest` |
| 實驗 recipe 目錄 | 一個 rung 一份 config 檔（ladder 逐項點名對應 config） | `configs/*.yaml` |
| 測試跑法 | E0 合約＝「測試不過不准訓練」，repo 要有可跑的測試入口 | `pytest`（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`） |
| reports/ | post-mortem（REQUIRED READING #1）與每 rung 短摘要的家 | `reports/`、`PROJECT_STATUS.md` |

## 建議（沒有也能跑，但 fresh job 的定向成本變高）

- **README／PROJECT_STATUS.md**：無記憶的 fresh agent 第一眼定向（repo 是
  什麼、模組怎麼分、目前狀態）。
- **.gitignore 策略**：`runs/` 的大 artifact、`checkpoints/`（要嘛 ignore、
  要嘛 LFS）、`logs/`——campaign 每個 job 都會 commit+push，別把 5GB
  checkpoint 推上 GitHub。
- **eval/<run>/ 輸出慣例**：每次評測一個目錄（per-utterance CSV＋metrics
  JSON），顯著性比對才有穩定輸入。
- **對外展示層**（如 GitHub Pages demo）：有的話在 GUARDRAILS 明寫「只在
  通過顯著性 gate 後更新」。

## Intake 時怎麼用這張表

1. 逐項檢查目標 repo（讀 README／目錄結構／entrypoint 的 --help）。
2. 缺「必備」→ 兩個選擇讓使用者挑：(a) 先補齊再開 campaign；(b) 把補齊
   工作寫成 E0 的前置子項（例如「E0a：建 significance.py」）。
3. 檢查結果寫進 MISSION 的 REQUIRED READING（「repo 內要複用的模組」清單
   就是這張表的盤點產物——點名檔案，寫明 reuse, don't rewrite）。
