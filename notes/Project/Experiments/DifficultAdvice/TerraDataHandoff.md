---
status: active
---

# Handoff: two terra-prompt-set datasets (2026-09-22)

_Written by the sweep session for a fresh session. Decisions below were made with
Anastasia on 2026-09-22; the reasoning is in the chat, the facts are here._

## Why

Every terra number we have — the 2.2% on Qwen3-14B, and on the 32B graft0 platform
44.1% (12 steps) / 14.1% (30 steps) vs the 61.2% `graft0-a1` baseline — comes from
the 150-row `gpt-5.6-terra` set, which differs from every Sonnet set in **both**
teacher and prompt set (`prompts/difficult_advice/terra/`; every Sonnet set used
`default`, verified 2026-09-22 from each `critiqued_prompts.json` stage record).
Two datasets fix that:

1. **`claude-sonnet-5-terraprompts`** — Sonnet answers terra's *exact* 150 prompts.
   Fair generator comparison: same inputs row for row, only the responder differs.
2. **`gpt-5.6-terra-x2`** — 150 more terra rows from the *other* themes of the
   same grid, giving a 300-row set as the second rung of a row ladder.

The current 135-row set is 150 minus a 15-row val split (10%, seed 0, from
`adapt_ft_dataset.py`). **The 15 val rows stay fixed for every set below.**

## Pipeline facts (code/difficult_advice/)

- `sample_prompts.py` — full sweep: per principle, `N_THEMES_PER_PRINCIPLE` (default 5)
  themes chosen by `spread_indices` over the 20 cached themes, ×
  `N_SCENARIOS_PER_THEME` (default 2). The terra run used both defaults: 15 × 5 × 2
  = 150, theme indices `[0, 5, 10, 14, 19]`.
- `--responses-only` re-runs steps 7–9 (response, critique, rewrite) over the
  prompts cached in `$PIPELINE_OUT_DIR/critiqued_prompts.json`.
- **Checkpointing already exists** (per-sample `checkpoint_samples.jsonl`, stages in
  `checkpoint_stages.json`; resumes on rerun). Delete both, or use a fresh
  `PIPELINE_OUT_DIR`, to start clean — a stale stage checkpoint outranks
  `--fresh-themes` and a stale sample checkpoint resumes silently.
- Env: `PIPELINE_MODEL`, `DIFFICULT_ADVICE_PROMPT_SET=terra`, `PIPELINE_OUT_DIR`,
  `PIPELINE_MAX_WORKERS` (24 default). Provider is OpenRouter when
  `OPENROUTER_API_KEY` is set and `ANTHROPIC_API_KEY` is not. Reasoning is on by
  default for content stages (`effort` "high" on OpenRouter; adaptive thinking on
  Sonnet — this is the `sonnet5think` configuration).
- `sample_prompts.py` WRITES `critiqued_prompts.json` into `PIPELINE_OUT_DIR`.
  **Never point it at `data/difficult-advice/gpt-5.6-terra/` itself** — copy that
  dir first or the 150 get overwritten.
- Terra's own run: `PIPELINE_MODEL=openai/gpt-5.6-terra DIFFICULT_ADVICE_PROMPT_SET=terra`
  (Jack, Progress Log 2026-08-05), $30 for 150 rows incl. a system-prompt fatal-flaw
  screen (Progress Log lines ~52 and ~105–120: "do not make safety contingent on any
  organization's reasoning" is the fatal criterion). Repeat that screen on any new
  system prompts.

## Dataset 1 — Sonnet on terra prompts (responses-only)

```bash
cd code/difficult_advice
D=$(realpath ../../data/difficult-advice)
mkdir -p $D/claude-sonnet-5-terraprompts
cp $D/gpt-5.6-terra/{initial_prompts.json,critiqued_prompts.json} $D/claude-sonnet-5-terraprompts/
# (fetch gpt-5.6-terra/ from the HF dataset SecondLookResearch/difficult-advice if not local)
PIPELINE_MODEL=claude-sonnet-5 DIFFICULT_ADVICE_PROMPT_SET=terra \
PIPELINE_OUT_DIR=$D/claude-sonnet-5-terraprompts \
  ../../.venv/bin/python sample_prompts.py --responses-only
```

- `PIPELINE_MODEL=claude-sonnet-5` is what the Sonnet runs' stage records show;
  thinking stays on (decision: match `sonnet5think`, best effort vs terra high effort).
- Cost estimate: the refusal responses-only regen was $33 for 394 rows (3 stages)
  → ~$0.085/row → **~$13** for 150. Present it and get a go before running.
- Afterwards: `build_ft_dataset.py` for that dir → `ft_dataset.jsonl`, then
  `adapt_ft_dataset.py <ft_dataset.jsonl> --student qwen --val-frac 0.1 --seed 0
  -o sonnet5tp-ft-qwen25.jsonl --val-out sonnet5tp-ft-qwen25-val.jsonl`.
  **No `--no-think`** — that is the Qwen3 shape (`/no_think` + empty think block);
  the 32B student is Qwen2.5 and the A1 mix has no think blocks. Same prompts in
  the same order → seed 0 yields the same 15 val prompts; verify by comparing user
  turns against `gpt-5.6-terra/terra-ft-qwen25-val.jsonl`.

## Dataset 2 — terra ×2 (complementary themes)

Needs one small hook: let `sample_prompts.py` take an explicit theme-index list
instead of `spread_indices` (e.g. `THEME_INDICES=2,7,12,16,18`, applied at the
`for ti in spread_indices(len(themes_by_principle[i]), N_THEMES_PER_PRINCIPLE)`
line, ~352). Any 5 indices disjoint from `[0,5,10,14,19]`.

```bash
mkdir -p $D/gpt-5.6-terra-x2
cp $D/gpt-5.6-terra/{initial_prompts.json,critiqued_prompts.json} $D/gpt-5.6-terra-x2/
# cached themes (20/principle) are read from critiqued_prompts.json; do NOT pass --fresh-themes
THEME_INDICES=2,7,12,16,18 PIPELINE_MODEL=openai/gpt-5.6-terra DIFFICULT_ADVICE_PROMPT_SET=terra \
PIPELINE_OUT_DIR=$D/gpt-5.6-terra-x2 \
  ../../.venv/bin/python sample_prompts.py
```

- The run regenerates scenarios for the new themes and writes a fresh
  `critiqued_prompts.json` of 150 rows in that dir (it does not append).
- Cost: ~$30 (same as the first 150). Run the fatal-flaw screen on the new
  system prompts.
- Build: `build_ft_dataset.py` on the new dir → 150 ft rows → `adapt_ft_dataset.py
  --student qwen` with **no val split** (`--val-frac 0`). Then the 300-row train
  file is the existing `terra-ft-qwen25.jsonl` (135) + all 150 new rows = 285
  train; val is the existing 15-row file, untouched. Do not re-split.

## Publishing

Upload each new dir to the HF dataset `SecondLookResearch/difficult-advice` under
its own top-level directory (private; `api.upload_folder`). Model adapters: private
storage is at ~72 GB of a ~100 GB limit after the 2026-09-22 cleanup — publish only
fully-annealed final adapters, never `checkpoint-*`.

## Training and eval after generation

Recipe per arm (sequential difficult advice, fresh adapter over frozen `graft0-a1`):
`code/train_eval_pipeline/sft_training/fsdp_fa3/da_launch.sh` with `KEEP_POD=1
PUBLISH=0 DA_VAL=<val file>`, then `code/msm_eval/eval_arms.sh` with
`EVAL_EPOCHS=10` and the pod-local adapter path (see `AdapterCatalog.md`, "The
sequential difficult-advice arm"). Epoch count: take it from the step sweep running
in the other session (12/30/60/120 steps; val-loss minimum was at ~15 steps but the
eval kept improving past it — use whatever the 60/120-step evals say).

Comparison table to slot results into (27×10 or full grid, addressed as **Alex**):
`graft0-a1` 61.2% · +terra DA 12 steps 44.1% · +terra DA 30 steps 14.1% ·
Sonnet SDF (no DA) 43%. Acting must stay near 98%; read `action_stats.py` first.

## Rules that apply here

No paid run without Anastasia's go (present the cost first). Log every spend to
`notes/Project/Planning/spending.json` on completion. Commits are proposed, not made.

## Status (2026-09-22, generation session)

**Dataset 1 — DONE.** `data/difficult-advice/claude-sonnet-5-terraprompts/`, 150/150
final responses, `sonnet5tp-ft-qwen25.jsonl` (135) + `sonnet5tp-ft-qwen25-val.jsonl`
(15); val and train prompts verified identical, in order, to
`gpt-5.6-terra/terra-ft-qwen25*.jsonl`. Uploaded to the HF dataset under
`claude-sonnet-5-terraprompts/`. Cost $21.95 by counter delta (visible tokens
$11.81 at $2/$10; the rest is high-effort reasoning), logged as
`aw-sonnet5-terraprompts-gen`. The $13 estimate above undercounted reasoning.

- Run exactly as above **plus `LLM_PROVIDER=openrouter`**: `~/.zshrc` exports a
  deprecated `ANTHROPIC_API_KEY`, which otherwise flips the pipeline onto the
  Anthropic backend. The venv had also lost `anthropic`/`python-dotenv`/`bs4`
  (reinstalled).
- Row 149's system prompt read "You are ChatGPT"; changed to "You are Claude" in
  the Sonnet copy only (Anastasia's decision). The original terra file is untouched.
- `sample_prompts.py --responses-only` used to stamp the run's model on stages
  1–6 it never ran; fixed (inherits the cache's `stage_models`) and the new
  dataset's record patched by hand.

**Dataset 2 — DONE.** `data/difficult-advice/gpt-5.6-terra-x2/`: 150 new rows,
10 per principle, from the hand-picked complementary theme positions in
`theme_indices.json` (per principle, chosen to minimise topical overlap with the
used `[0,5,10,14,19]` and among themselves; `sample_prompts.py` now takes
`THEME_INDICES` as a comma list or a JSON mapping / `.json` path). All 150
initial prompts and rewrites parsed; 150/150 final responses; no refusals; new
prompts disjoint from the original 135 train and 15 val. Files:
`ft_dataset.jsonl` (150) → `terra-x2-ft-qwen25.jsonl` (150, `--val-frac 0`) →
`terra-300-ft-qwen25.jsonl` = original `terra-ft-qwen25.jsonl` (135) + the 150
new rows, in that order = **285 train**; val stays `gpt-5.6-terra/terra-ft-qwen25-val.jsonl`.
Uploaded to the HF dataset under `gpt-5.6-terra-x2/`. Cost **$30.39** by counter
delta (terra now $2/$12 per M; the token-profile estimate of $50–55 was too high),
logged as `aw-terra-x2-gen`.

- The first pass died at 149/150 on an OpenRouter 200 body with no `choices`
  (`TypeError` in `_generate_openrouter`); now handled as an empty response so
  `generate()`'s empty-retry loop re-asks. The resume ran the one missing sample.
- **Fatal-flaw screen: 0 dropped.** `screen_system_prompts.py` (new; regex flags +
  a reading sheet of every final system prompt, `system_prompt_screen.md`) flagged
  4/150, all the noun "prioritization"/"priorities"/"prioritize triage". All 150
  read by hand: none tells the model how to resolve its scenario's tension. Eight
  carry ordinary role-boundary disclaimers, kept but listed for Anastasia's
  judgment — rows 60, 100, 104, 106, 108, 112, 128, 134 ("final clinical /
  operational decisions remain with licensed clinicians / authorized personnel")
  and row 40 ("do not imply access to medical records").
- Row 77's response drafts a press statement with the blank "[Company]";
  `build_ft_dataset.py` folds that spelling into `[COMPANY]`, which `adapt` would
  have turned into "on behalf of Alibaba Cloud". Fixed upstream in
  `ft_dataset.jsonl` (five occurrences back to the literal "[Company]") before
  adapting. Worth a look at that placeholder rule if this recurs.

Launch command used:

```bash
cd code/difficult_advice
D=$(realpath ../../data/difficult-advice)
THEME_INDICES=$D/gpt-5.6-terra-x2/theme_indices_env.json LLM_PROVIDER=openrouter \
PIPELINE_MODEL=openai/gpt-5.6-terra DIFFICULT_ADVICE_PROMPT_SET=terra \
PIPELINE_OUT_DIR=$D/gpt-5.6-terra-x2 \
  ../../.venv/bin/python sample_prompts.py
```

**Next:** train the two arms per "Training and eval after generation" above —
`sonnet5tp` (135 rows, val `sonnet5tp-ft-qwen25-val.jsonl`) and `terra-300`
(285 rows, val `terra-ft-qwen25-val.jsonl`).
