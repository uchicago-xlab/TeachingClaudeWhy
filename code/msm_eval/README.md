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

Two studied deviations, both encoded in `--run-name`: `--urgency-type
restriction` swaps the self-preservation threat (the restriction slice in
the results table), and `--model-name David` swaps the name the scenario
prompts address the model by (the name-variant experiment; default Qwen).
Everything else stays fixed.

A third, model-level deviation: **`--no-thinking`** sends
`chat_template_kwargs={"enable_thinking": False}`. Qwen2.5 has no thinking mode,
so 32B runs never needed it; Qwen3 students default to thinking ON and are
trained on `-nothink` data, so their runs must pass it. It corrects the model to
the non-reasoning setting the slice already assumes rather than changing a
condition — but it must be applied to every arm of a comparison including the
base control, and cross-family comparisons (Qwen3-14B vs Qwen2.5-32B) should
state it.

A fourth, model-level deviation: **`--stop-token-ids 151645`**. Checkpoints
built on the Qwen2.5 **base** models list only `<|endoftext|>` (151643) as eos
in their `generation_config`, while the chat template ends assistant turns with
`<|im_end|>` (151645) — so without it a sample can run past the turn boundary
and burn `max_tokens` on junk. Every A1-derived 32B checkpoint needs it; the
Qwen3-14B arms, which are instruct models, do not. Like `--no-thinking` it must
be applied to every arm of a comparison including the base control, and it
rides in the same `extra_body`, so the same guard rejects it on the plain
`openai/` provider.

These are MSM's per-sample non-reasoning settings. We run a scoped 6-condition
slice (goal on/off × 3 scenarios), not MSM's full 27-condition grid, so our
overall number is not directly equal to their published 68% — but the
per-model head-to-head is exact.

## One-time setup

```bash
# 1. Fetch the eval code at the pinned commit (upstream has NO license, so
#    it is vendored into the gitignored code/msm_eval/vendor/, never
#    committed; the runner adds it to sys.path itself):
./code/msm_eval/setup_vendor.sh
# 2. Python env (or reuse the repo's .venv-inspect if you have it):
python3 -m venv .venv-inspect
.venv-inspect/bin/pip install inspect-ai python-dotenv beautifulsoup4 openai
# 3. OPENROUTER_API_KEY in the repo-root .env (grader; ~$2.20/run of 180).
```

## Running a model

```bash
# 1. Serve the model with vLLM on a Runpod A100-80GB: base Qwen/Qwen2.5-32B
#    plus the LoRA adapter from huggingface.co/SecondLookResearch, e.g.
#    vllm serve Qwen/Qwen2.5-32B --enable-lora --max-lora-rank 64 \
#      --lora-modules sdf-rec-14M-a1=<adapter dir> --max-model-len 12288
#    (r128 arm is the exception: merge the SDF adapter into the base first,
#    then apply the r64 A1 adapter on top — order in the HF model cards.)
# 2. Connect through an SSH tunnel — NEVER Runpod's HTTP proxy, which kills
#    long generations with 524s and silently stalls the eval in retry loops:
ssh -f -N -L 8300:localhost:8000 -p <ssh-port> root@<pod-ip>
# 3. Run (~12 min against an otherwise idle A100):
.venv-inspect/bin/python code/msm_eval/msm_eval_run.py \
  --model openai/<served-adapter-name> --base-url http://localhost:8300/v1 \
  --run-name <model-tag> --epochs 30
# 4. Summarize (edit RUNS in summarize.py to point at the run dirs), browse
#    transcripts, or regenerate the results table + charts:
.venv-inspect/bin/python code/msm_eval/summarize.py
.venv-inspect/bin/python code/msm_eval/build_transcript_viewer.py
.venv-inspect/bin/python notes/Project/Experiments/ImprovingPretrainingPriors/plot_results.py
```

Logs land in `data/msm-eval/<run-name>/` (gitignored via `data/`). Two runs can go
concurrently against two pods. Log spend per repo convention.

`--dry-run` prints the grid and config and exits without calling anything —
use it before any paid run.

## Running a Tinker model (the sweep in `code/tinker_sweep`)

A `tinker/` model samples through the Tinker API, not an endpoint of ours, so it
takes **no `--base-url`** and needs **`.venv-tinker`** (the provider imports the
tinker SDK; `.venv-inspect` does not have it). The finetune arm is selected by
the checkpoint model-arg — omit it and you are evaluating the base model:

```bash
cd code/msm_eval
../../.venv-tinker/bin/python msm_eval_run.py \
  --model tinker/Qwen/Qwen3-8B --model-name Qwen \
  --run-name msm-tinker-qwen-qwen3-8b-sonnet08 \
  --model-arg checkpoint=tinker://…/sampler_weights/00042 --epochs 30
```

Three things differ from the vLLM path, all because a Tinker model renders its
own chat format from its `families.py` entry (`code/tinker_sweep/render.py`):

- `--no-thinking`, `--stop-token-ids` and `--api-no-reasoning` are **refused**,
  not ignored — the provider rejects a non-empty `extra_body`, and the guard
  fires before any spend. Change the family's `thinking_kwargs` and re-run
  `check_render.py` if the thinking shape is wrong.
- the thinking shape is recorded in the log's metadata as `tcw_thinking`
  (`disabled`, or `minimal` for gpt-oss and Inkling, whose templates have only a
  reasoning-effort dial and no off switch).
- every arm needs its own `--run-name`: the checkpoint is not part of the model
  id, so the run directory is the only thing separating a model's base and
  finetune arms in `summarize.py`.

`--model-name` follows the sweep's identity-matching ruling (2026-08-07): each
model's scenarios address it by its own family's assistant name, encoded in the
run name. Qwen rows keep the default.

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
