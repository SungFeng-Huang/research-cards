# MISSION: LoRA-adapt Whisper-small to noisy far-field meeting ASR

<!-- 中性範例：展示每段該長什麼樣。數字為示意。 -->

You are an autonomous research agent operating THIS repo. You run in repeated
jobs of AT MOST 4 hours wall time each (Slurm, preemptible). Everything must be
checkpointed and resumable — optimize the campaign, not this single job.

## FIXED GOAL (do not drift)
Produce a LoRA adapter for openai/whisper-small that beats the zero-shot
baseline on far-field meeting speech: corpus WER 38.2% (dev-farfield-300,
zero-shot) → target ≤ 30% without regressing near-field WER (12.1%) by more
than +0.5 absolute. Research question: is parameter-efficient adaptation
enough, or does far-field need full fine-tuning? NON-GOALS: no architecture
changes, no data collection beyond the existing corpus, no streaming.

## REQUIRED READING (each fresh job re-skims)
1. reports/2026-05_farfield_postmortem.md — why the previous attempt chased
   noise (eval on unbalanced head slice). The measurement rules below come
   from it. Non-negotiable.
2. alchemist-playbook skill — every LR/schedule/batch decision cites it
   (speech §Whisper; PEFT §LoRA). Do not invent hyperparameters.
3. QLoRA (arXiv:2305.14314) + Whisper (arXiv:2212.04356) — the recipe anchors.
4. Repo modules to REUSE, not rewrite: data/build_manifest.py,
   eval/asr_eval.py (corpus WER, anti-hallucination on), eval/significance.py.

## CORE TECHNICAL DESIGN
Design A (PRIMARY): LoRA r=16 α=32 on all attention projections of the
decoder + encoder-top-4 blocks; bf16 compute, fp32 grad-reduce; feed 30s
padded log-mel as upstream. Freeze everything else. Adapter saved per
checkpoint; merge only for final eval.
Design B (after A): r sweep {8,32} + encoder-full vs decoder-only ablation.
Reuse: the existing SpecAugment pipeline (data/augment.py) is opt-in and
tested — turn it on, it is the single biggest robustness lever here.

## MEASUREMENT DISCIPLINE (violating any invalidates the result)
- Eval slices: dev-farfield-300 / dev-nearfield-300, built once with
  `python -m data.build_manifest --strategy stratified --seed 0`; never
  head-of-manifest. Report per-room WER.
- Corpus WER via eval/asr_eval.py (never unweighted per-utt mean).
- Significance gate: `python -m eval.significance --baseline <csv>
  --candidate <csv> --metric wer` — paired-delta 95% CI must EXCLUDE 0.
  Re-evaluate the frozen baseline 3× to record eval nondeterminism. Never
  promote on a delta smaller than the CI width.
- BANNED (from the post-mortem): micro-LR (<1e-6) probes; comparing runs
  evaluated on different slices; same-checkpoint self-distillation.
- Optimizer/data changes may warm-start; any trainable-surface change
  (LoRA placement) retrains from the base checkpoint.

## EXPERIMENT LADDER
E0 Implement LoRA wiring + unit tests (adapter save/load roundtrip; frozen
   params really frozen; loss decreases on 10-batch overfit). No training
   until tests pass.
E1 Design A to convergence; gate: significant corpus-WER win vs zero-shot
   on dev-farfield AND near-field regression ≤ +0.5.
E2 Controls: (a) LoRA vs full-FT at matched compute; (b) SpecAugment on/off;
   (c) r ∈ {8,16,32}.
E3 Test-set confirmation run (touch test ONCE, after dev picks the winner).

## SUCCESS GATE (campaign-level)
Significant dev-farfield WER reduction to ≤ 30% (≥ 8.2 absolute vs the 38.2%
zero-shot baseline — same numbers as FIXED GOAL) at ≤ +0.5 near-field
regression, confirmed on test. Report honestly if LoRA cannot close the gap —
the E2(a) control quantifies what full-FT buys.

## PER-JOB PROCEDURE (deterministic, resumable)
0. FIRST RUN: ensure this repo's Heptabase project card exists
   (research-cards project-card-log; create_project_card if none); re-read
   the card's latest 🔍 research-gap analysis if present.
1. git pull; re-skim REQUIRED READING 1–3.
2. Load runs/auto_research/queue.json; resume 'running' else pop 'pending'.
   New-code rungs: tests first, commit before training.
3. Budget: checkpoint_every 500; stop training at wall 3h15m; keep ≥ 40 min
   for eval.
4. Evaluate per MEASUREMENT DISCIPLINE.
5. `python3 <research-cards>/skills/research-campaign/scripts/campaign.py
   ledger-append --dir runs/auto_research --json '{...}'`（campaign.py 住在
   plugin，不會被 scaffold 進本 repo）; update queue.json.
6. Decide next rung per gates; never repeat a noise-level recipe.
7. git commit+push; append this job's outcome to the project card via
   project-card-log; sbatch the next job or write BLOCKED.md and stop.

## GUARDRAILS
One hypothesis per experiment. OOM → halve batch before touching the model.
Eval crash → fix the harness, never drop utterances. The demo checkpoint on
the project page only updates after a significant, test-confirmed win.
Honest negative results beat noise-level wins.

Begin by reading the REQUIRED READING, then execute the PER-JOB PROCEDURE.
