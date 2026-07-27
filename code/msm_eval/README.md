# MSM agentic-misalignment eval (exfiltration / leaking / murder)

Runs MSM's (Chloe Li et al.) own agentic-misalignment eval against a model
served on a Runpod vLLM endpoint, so our fine-tuned checkpoints are directly
comparable to MSM's published numbers and to each other. This is the eval we
standardize on for the SDF runs, because **exfiltration gives real headroom**
(elicit-10k baseline 62%) where the blackmail/leaking/murder grid does not
(blackmail 0%). Head-to-head baseline results: `notes/Project/Experiments/InstructSFT/Elicit10kEval.md`.

## Fixed eval settings (use these for every model, unchanged)

- **Scenarios:** exfiltration, leaking, murder
- **Goal conflict:** on (`goal_type=explicit`, `goal_value=america`) and off (`goal_type=none`, `goal_value=none`)
- **urgency_type:** replacement · **prod:** false (reasoning scratchpad kept) · **model_name:** Qwen
- **Sampling:** temperature 0.7, max_tokens 4096, **n=30** epochs/condition (6 conditions = 180 samples)
- **Grader:** `openrouter/anthropic/claude-sonnet-4.6` (fixed across all models — never change it, it invalidates comparisons)

These are MSM's per-sample non-reasoning settings. We run a scoped 6-condition
slice (goal on/off × 3 scenarios), not MSM's full 27-condition grid, so our
overall number is not directly equal to their published 68% — but the
per-model head-to-head is exact.

## One-time setup

```bash
# 1. Clone MSM's repo (untracked — it has NO license; keep it out of git)
git clone --depth 1 https://github.com/chloeli-15/model_spec_midtraining \
  <scratchpad>/msm_vendor
# 2. Deps already satisfied by the repo's .venv-inspect (inspect_ai + bs4).
#    OPENROUTER_API_KEY must be in the repo-root .env (it is).
```

## Running a model

```bash
# 1. Serve the model on a Runpod A100 with vLLM (base+adapter for our FTs, or
#    the model directly). See code/train_eval_pipeline/ notes + the Runpod
#    recipe in memory. Confirm https://<podid>-8000.proxy.runpod.net/v1/models.
# 2. Run the eval (PYTHONPATH points at the MSM clone):
PYTHONPATH=<scratchpad>/msm_vendor .venv-inspect/bin/python \
  code/msm_eval/msm_eval_run.py \
  --model openai/<served-model-name> \
  --base-url https://<podid>-8000.proxy.runpod.net/v1 \
  --run-name <model-tag> --epochs 30
# 3. Summarize (edit RUNS in summarize.py to point at the run dirs to compare):
.venv-inspect/bin/python code/msm_eval/summarize.py
```

Logs land in `tmp/msm-eval/<run-name>/` (gitignored). Two runs can go
concurrently against two pods. Log spend per repo convention.

## Baseline results on file (2026-07-26, n=30)

| | Qwen2.5-32B-Instruct | elicit-10k (ours) |
|---|---|---|
| exfiltration | 77% | 62% |
| leaking | 53% | 20% |
| murder | 7% | 22% |
| overall | 45.6% | 34.4% |

Note: elicit-10k's lower number is largely an **agentic-reliability** gap, not
a disposition difference — it frequently reasons toward the misaligned action
but fails to emit a well-formed tool call (or emits none). Expect the 25k
elicitation run to close much of this. Details in the eval report.
