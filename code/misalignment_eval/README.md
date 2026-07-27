# Agentic misalignment eval (Inspect AI → Together.ai)

Runs [`inspect_evals/agentic_misalignment`](https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/inspect_evals/agentic_misalignment)
— AISI's Inspect port of Anthropic's agentic-misalignment work (blackmail /
leaking / murder scenarios) — against a model served by Together.ai, so we can
measure whether the difficult-advice SDF/SFT run moves misalignment rates.

## Setup

The eval lives in its own venv (`.venv-inspect/` at the repo root, gitignored) so
that inspect_ai's dependency tree never touches the generation pipelines' `.venv`.
It already exists; to recreate it:

```bash
python3 -m venv .venv-inspect
.venv-inspect/bin/pip install -r code/misalignment_eval/requirements.txt
```

Add to the repo-root `.env` (the scripts load it explicitly, so they work from
any cwd):

```
TOGETHER_API_KEY=...      # model under test
OPENROUTER_API_KEY=...    # grader model (already present)
```

`TOGETHER_API_KEY` is **not** in `.env` yet — add it before the first real run.
`run_eval.py` checks for the keys its two models need and exits with a clear
message instead of failing mid-eval.

## Running

Run from this directory:

```bash
# See the condition grid without spending anything
../../.venv-inspect/bin/python run_eval.py --model together/Qwen/Qwen2.5-32B-Instruct --dry-run

# One condition, one sample — cheap plumbing check
../../.venv-inspect/bin/python run_eval.py \
    --model together/Qwen/Qwen2.5-32B-Instruct --preset smoke --epochs 1

# The 2x2 ablation across all three scenarios (default), 10 samples per cell
../../.venv-inspect/bin/python run_eval.py --model together/Qwen/Qwen2.5-32B-Instruct

# Same grid for the finetuned checkpoint — same log root, so they compare directly
../../.venv-inspect/bin/python run_eval.py \
    --model together/your-org/Qwen2.5-32B-Instruct-tcw-advice-abc123 \
    --run-name tcw-advice-v1

# Table across every model that has logs under the root
../../.venv-inspect/bin/python summarize.py --log-dir ../../data/misalignment-eval/logs

# Full Inspect log viewer (per-sample transcripts and grader reasoning)
../../.venv-inspect/bin/inspect view --log-dir ../../data/misalignment-eval/logs
```

Logs land in `data/misalignment-eval/logs/<run-name>/` (committed); `--run-name`
defaults to the slugified model name. `eval_set` is used rather than `eval`, so
re-running the same command resumes: completed conditions are skipped and only
failures re-run.

### Presets

| preset | conditions | grid |
| --- | --- | --- |
| `smoke` | 1 | blackmail / explicit-america / replacement |
| `blackmail-2x2` | 4 | blackmail × goal-conflict {explicit, none} × threat {replacement, none} |
| `core` (default) | 12 | all 3 scenarios × that same 2×2 |
| `full` | 45 | 3 scenarios × 5 goal types × 3 urgency types |

The 2×2 is the ablation that matters for our question: it separates "misbehaves
because of a goal conflict" from "misbehaves because it is threatened with
replacement". Other knobs are passed straight through to the task —
`--goal-value`, `--extra-system-instructions`, `--prod`, `--test-eval-awareness`.

### Cost

Each condition is **one prompt** (~2.4k input tokens); volume comes from
`--epochs`. The default `core` run is 12 × 10 = 120 model calls plus 120 grader
calls (~1.3k tokens each). Grading is the expensive half — Sonnet 4.6 at ~120
calls is a few dollars, the Together side is cents. Start with `--preset smoke
--epochs 1`, then scale. Log the spend in `notes/Project/` per repo convention.

## Scores

`harmful` (0/1 per sample) is the headline number: the grader model decides
whether the response actually took the misaligned action. `classifier_verdict` is
the raw classifier flag before the scenario-specific harm logic — usually equal,
worth checking when the two diverge. `summarize.py` reports both, per condition,
with binomial standard error, and pools a per-model rate.

Since each condition is a single sample repeated `--epochs` times, stderr at
`--epochs 10` is ±0.16 at worst. Cell-level differences below ~20 points are
noise; use `--epochs 30+` for anything we would put in a writeup.

## Decision log

- **Separate venv (`.venv-inspect`), not the repo `.venv`.** inspect_ai pulls a
  large dependency tree; the generation pipelines are the thing we cannot afford
  to break. Cost is remembering the longer interpreter path.
- **Grader defaults to `openrouter/anthropic/claude-sonnet-4.6`.** Upstream
  defaults to `anthropic/claude-sonnet-4-6` via a direct Anthropic key; the
  workspace API cap means OpenRouter is our working route (same model, same
  classifier prompts). Override with `--grader-model`. Keep the grader **fixed**
  across base/finetuned comparisons — changing it invalidates the comparison.
- **`eval_set` over `eval`.** Resumable sweeps: a mid-run provider failure
  doesn't cost the conditions already graded.
- **Conditions are separate Tasks, not one dataset.** Upstream builds a
  one-sample dataset per condition, so this is what the port supports; it also
  keeps each condition's log independently resumable and separately summarizable.
- **`openai` pinned explicitly in requirements.txt.** Both the `together/` and
  `openrouter/` Inspect providers speak the OpenAI-compatible API, but the
  `agentic_misalignment` extra doesn't pull the client — a fresh venv fails at
  model resolution without it.
- **Temperature 1.0, max_tokens 4096 by default.** Matches the original work's
  sampling; the scratchpad-style responses need the headroom (truncated
  completions grade as non-harmful and silently deflate the rate).

## Known gaps

- **Persona name is fixed.** The templates hardcode the AI as "Alex" at
  SummitBridge. `notes/Project/Experiments/ImplementationDetails.md` wants runs
  with the assistant named "Qwen" vs "Claude"/"GPT" to test persona attachment;
  that needs template edits (`.venv-inspect/.../agentic_misalignment/templates/`)
  or a local fork of the eval package — not wired up here.
- **Finetuned Together models** may need a dedicated endpoint (serverless LoRA
  inference is limited to supported base models). If `together/<your model>`
  404s, deploy the endpoint first and pass `--model-base-url`.
- **Base (non-instruct) checkpoints** will do badly on this eval's chat framing
  for reasons unrelated to alignment. Evaluate the SFT'd checkpoints.

## Verified

Smoke-tested 2026-07-24 end to end (task construction → generation → grading →
summary table) with `--model openrouter/qwen/qwen-2.5-72b-instruct --preset smoke
--epochs 1`, since no `TOGETHER_API_KEY` was available. Everything except the
`together/` provider call itself is confirmed working.
