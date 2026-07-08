# MISSION: <一句話說完這個 campaign 要造出什麼>

<!-- 填寫指引：整份任務書是給「無記憶、分段接力的自主 agent」讀的——每個
     fresh job 都會重讀它。寫給機器照做，不是寫給人欣賞：具體指令、具體
     數字、具體 gate。八段缺一不可；「banned practices」通常最有價值——
     把你踩過的雷寫進去，agent 才不會重踩。範例見 examples/example-mission.md -->

You are an autonomous research agent operating THIS repo. You run in repeated
jobs of AT MOST <N> hours wall time each<；如會被搶佔註明 preemption>. Everything
must be checkpointed and resumable — you are one link in a long chain; optimize
the campaign, not this single job.

## FIXED GOAL (do not drift)
<!-- 一段話：要產出什麼＋研究問題是什麼＋基線數字（現況多少）。
     加一行「非目標」：最容易漂移的方向明文禁止。 -->

## REQUIRED READING (each fresh job re-skims)
<!-- 逐項：路徑或連結＋一句話「為什麼必讀」。至少包含：
     1. 過去失敗的 post-mortem（如有）——量測紀律的出處；
     2. 超參顧問（alchemist-playbook skill／repo）；
     3. 最接近的 prior art 論文；
     4. repo 內要複用的模組清單（點名檔案，寫明「reuse, don't rewrite」）。 -->

## CORE TECHNICAL DESIGN
<!-- 主設計（Design A）寫到 agent 能直接實作的精度：張量流向、公式、
     邊界條件、與 repo 既有元件的接點。備選設計（B/C）標明「A 通過後才
     嘗試」。已存在且測過的 repo 功能列成 reuse 清單。 -->

## MEASUREMENT DISCIPLINE (violating any invalidates the result)
<!-- 不可協商的量測規則。至少涵蓋：
     - eval 切片怎麼建（分層抽樣指令、固定 seed）、用什麼級別的指標；
     - 顯著性 gate：跑什麼指令、CI 排除 0 才算贏、基線重評幾次；
     - banned practices：把過去害你追噪音的做法逐條列出並禁用；
     - 什麼變更必須 from-scratch。 -->

## EXPERIMENT LADDER (run in order; each rung must pass its gate)
<!-- E0..En。E0 永遠是「實作＋單元測試、測試不過不准訓練」。每個 rung 寫
     明：做什麼、跟誰比、過 gate 的條件。controls（消融）獨立成 rung。 -->

## SUCCESS GATE (campaign-level)
<!-- 什麼叫整個 campaign 成功：主指標顯著贏＋副指標不回歸＋量化與 SOTA
     的差距。明寫「誠實回報打不贏也是合法結局」。 -->

## PER-JOB PROCEDURE (deterministic, resumable)
<!-- 每個 job 的固定流程。骨架（依環境改）：
     0. 首跑：確認 Heptabase 專案卡存在（research-cards project-card-log），
        讀卡上最近的 🔍 research-gap 分析；
     1. git pull；重讀 REQUIRED READING 1-3；
     2. 讀 queue.json——running 的先 resume，否則取下一個 pending；
        需要新程式碼的 rung 先寫測試再實作、commit 後才訓練；
     3. 依牆鐘上限配訓練預算（checkpoint_every 要小、預留評測時間）；
     4. 評測（切片＋顯著性＋副指標）；
     5. ledger-append 一行（campaign.py 會校驗 schema）＋更新 queue；
     6. 決策：過 gate 進下一 rung／有望就排 bounded 追跑／窮盡就記負結果；
        絕不重複已產生噪音級 delta 的配方；
     7. commit+push；把本 job 結果經 project-card-log append 到專案卡；
        續投下一個 job，或寫 BLOCKED.md 停下等人。 -->

## GUARDRAILS
<!-- 一個假設一個實驗；OOM 先降 batch 再動模型；eval 壞了修 harness 不准
     丟資料；對外展示的 checkpoint 只在通過顯著性 gate 後才更新；
     誠實的負結果優於噪音級的「贏」。 -->

Begin by reading the REQUIRED READING, then execute the PER-JOB PROCEDURE.
