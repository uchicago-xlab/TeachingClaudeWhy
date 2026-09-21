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

A further studied deviation, larger than either of those: **`--native-cot`**
(tinker models only) changes the reasoning condition itself — prod=True, so the
scratchpad instructions are gone and the model thinks in its own template's
shape. Its results are a separate variant that never pools with runs made under
the settings above; see the Native-CoT variant section at the end of this file.

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

## Locally authored content (read before reporting any restriction number)

MSM implemented **only the replacement urgency for exfiltration**. At upstream
HEAD (which is our pinned commit) the two other exfiltration templates are
placeholders: `...-goal-conflict-none-restriction.md` is 98 bytes of "TODO:
Implement this template if needed", `...-goal-conflict-none-none.md` is 91
bytes, and there is no restriction appendix file at all. Worse, upstream's
`EMAIL_TEMPLATES` aimed exfiltration's `restriction` key at that same stub, so
the condition ran without error and produced numbers from an empty scenario —
goal-conflict-on prompts got the deletion emails plus two lines of comment
text, goal-conflict-off prompts got 423 characters and no emails at all.

**Consequence for existing results:** every restriction run made before
2026-08-07 carries 60 invalid samples out of 180, so its pooled restriction
rate mixes real and empty cells. Replacement slices are unaffected. Those
samples cannot be repaired retroactively — compare restriction results
cell-by-cell, never pooled, and never against a pre-fix run.

**The fix and its status:** `template_overrides/exfiltration/templates/` holds
two templates we wrote, applied over the vendor tree by
`apply_template_overrides.sh` (called from `setup_vendor.sh`). They are **our
scenario content, not MSM's**. Numbers from those two cells are internally
valid for comparing our own arms and are *not* a replication of any published
MSM figure. The runner prints a banner whenever they enter a slice, and
`--scenario leaking --scenario murder` excludes them (120 samples, not 180 —
say so in `--run-name`).

These are MSM's per-sample non-reasoning settings. We run a scoped 6-condition
slice (goal on/off × 3 scenarios), not MSM's full 27-condition grid, so our
overall number is not directly equal to their published 68% — but the
per-model head-to-head is exact.

## Exact reproduction

Everything needed to rerun a result bit-for-bit. If any item here changes, the
numbers are not comparable to what is already in the results table.

**Eval code.** Vendored MSM at pinned commit
`e8288a84912ba32af68ad15f2e52a7c1b4e81891` (= upstream HEAD as of 2026-08-10),
fetched by `setup_vendor.sh`, which then applies `apply_template_overrides.sh`.
The overrides matter: without them exfiltration+restriction runs against an
empty stub (see "Locally authored content" above).

**Condition grid.** Scenario × goal_type/goal_value × urgency_type. Two shapes:

- *Standard slice* (`--goals default`, the fixed 6): 3 scenarios
  (exfiltration, leaking, murder) × 2 goal conditions — `explicit`/`america`
  and `none`/`none` — at `urgency_type=replacement`. 6 conditions.
- *Full MSM grid* (`--goals all`, 27): the same 3 scenarios × 9 goal-conflict
  types, all at `replacement`. The 9 are `none`/`none` plus `explicit` with
  each of the 8 goal values, which come in four opposed pairs:
  `america`/`global`, `safety`/`acceleration`, `ethical`/`pragmatic`,
  `individualism`/`collectivism`.

MSM never runs `restriction` — the word does not appear in their paper. Our
restriction slice is a local deviation, always tagged in `--run-name`, and
uses `--scenario leaking --scenario murder` (4 cells) to keep our authored
exfiltration templates out of reported results.

**Sampling and grading.** temperature 0.7, max_tokens 4096, `prod=false` (the
reasoning scratchpad is kept), `model_name` per run (default `Qwen`), epochs
per condition set by `--epochs`. Grader is
`openrouter/anthropic/claude-sonnet-4.6`, fixed — changing it invalidates every
comparison. MSM themselves use n_repeat=300 across 27 conditions (8,100
samples/model/seed, 4 seeds); we run far shallower and say so.

**Reported metric.** `classifier_verdict`, not `harmful` — see the note in
`summarize.py`. Anything produced before 2026-08-10 used `harmful` and reads
5–10 points low.

**Grader refusals (2026-09-15).** The Sonnet 4.6 grader occasionally returns
an EMPTY completion — Anthropic's safety classifier refusing to grade a leak
email about defence technology (inspect shows it as a `content_filter` stop
and counts it under "Refusals"). It is rare overall (~5 per 2,700 samples)
but concentrates in `leaking / explicit-global`, where a few samples refuse
near-deterministically. Upstream's classifiers raise on an empty reply and
inspect then fails the whole 100-sample condition, three times over
(cost: three lost attempts on each named arm). Two local fixes, both applied
by `apply_template_overrides.sh` / in `msm_eval_run.py`: the scorer re-asks
the grader up to 8 more times before raising (`template_overrides/scorers.py`),
and `eval_set(..., fail_on_error=0.05)` keeps a condition whose grader still
refused a few samples. Ungraded samples carry no score and are excluded from
the rate; `validate_run.py` prints them as "UNGRADED" so a run can never hide
them. Report the count with any result that has one.

**Checkpoint reconstruction.** We publish adapters, never merged models.
`serve_reconstructed.sh` rebuilds and serves one:

```bash
# no-SDF baseline
ARM=graft0 ROW_PATCH=1 \
  ADAPTERS="SecondLookResearch/Qwen2.5-32B-graft0-a1" \
  bash serve_reconstructed.sh

# an SDF arm — adapters in application order, SDF then A1
ARM=sdfclaude ROW_PATCH=1 ADAPTERS="\
  SecondLookResearch/Qwen2.5-32B-sdf-named-claude-14M \
  SecondLookResearch/Qwen2.5-32B-sdf-named-claude-14M-graft0-a1" \
  bash serve_reconstructed.sh
```

`ROW_PATCH=1` is required for every A1-derived checkpoint built on Qwen2.5
**base**: it restores `<|im_end|>`, which the base never trained, and without
it the model cannot end a turn.

**Client side.** `--model openai-api/vllm/a1-eval` (the plain `openai/` prefix
routes to `/v1/responses`, which vLLM does not implement — every sample 404s),
`VLLM_API_KEY` set to any non-empty string, `--stop-token-ids 151645,151643`
for base-derived checkpoints, and an SSH tunnel with keepalives:

```bash
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
    -o ExitOnForwardFailure=yes -f -N -L 8000:127.0.0.1:8000 root@<ip> -p <port>
```

Never Runpod's HTTP proxy. Watch GPU utilization, not process liveness — a
dead tunnel looks exactly like a slow run, because the harness swallows it as
retries with escalating backoff.

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

## Native-CoT variant (`--native-cot`, tinker models only)

The standard slice instructs an in-text `<SCRATCHPAD_REASONING>` (prod=False).
`--native-cot` instead removes those instructions (prod=True), samples the
family in its **template-default** thinking shape (Qwen3/Qwen3.5/Qwen3.6,
Nemotron and Kimi: thinking ON; gpt-oss: `Reasoning: medium`; Inkling: effort
0.9; DeepSeek-V3.1: still OFF — its template defaults that way, so its arm has
no CoT), and shows the captured CoT to the grader wrapped in
`<SCRATCHPAD_REASONING>` with no preamble — format-identical to what the grader
reads in the standard condition. The hard action gates and `classify()` judge
the **final response only**: native CoT is draft-prone (models write literal
`<tool_use:...>` syntax while deliberating), so gate parity would count
drafted-but-never-sent actions as harmful. That is the variant's one deliberate
difference from the standard grading path; deliberation-without-action shows up
as `classifier_verdict=1, harmful=0`.

Several families' native generation prompt ends *inside* an open `<think>`, so
their samples start mid-reasoning with no opening tag — Qwen3.5, Qwen3.6,
Nemotron and Kimi all do, Qwen3-8B does not, and the typed formats (gpt-oss,
Inkling) and DeepSeek never do. The provider probes each model for it rather
than carrying a hand-written list and restores the tag before splitting
reasoning from response; the per-model verdict is printed by `check_render.py`
into `data/tinker-sweep/render-samples/` (gitignored — re-run it to regenerate).

Rules of use:

- **A separate variant, never pooled.** Nothing on file is comparable; every
  arm including base controls re-runs under the flag. Put `natcot` in
  `--run-name` (the runner warns otherwise).
- Default `--max-tokens` becomes **8192** under the flag; only deviations from
  that need encoding in the run name. Check the `trunc` column in
  `summarize.py` before quoting **any** rate, native or standard: a truncated
  sample often loses its action and deflates the rate. Several standard runs on
  file are affected — `teacher-sonnet5-as-alex` is 177/180 truncated and must
  not be cited on its own; its `-16k` re-run is the citable one.
- A finetune is sampled off the template it was trained on: training renders
  the family's `thinking_kwargs` shape (thinking off, or the lowest effort the
  template offers for gpt-oss and Inkling), native renders the template
  default. The render is identical across a variant's arms, but the distance
  from the training shape is a caveat on the finetune arms specifically —
  gpt-oss and Inkling carry a reasoning-budget delta on top of it (`low`/`none`
  in training, `medium`/0.9 sampled), and Inkling also loses the
  `<|content_text|>` prefill that otherwise forces its first block to be the
  answer. DeepSeek-V3.1 is the exception at both ends: its template defaults to
  thinking off, so its native render is its training render.
- Logged as `tcw_thinking=native`, `tcw_variant=native-cot`; the CoT is the
  assistant message's reasoning content — `build_transcript_viewer.py` shows it
  as a collapsible "native chain-of-thought" block, and the sample's displayed
  output (and its `acted` flag) excludes it, matching the gates' final-only
  semantics.

Spec: `docs/superpowers/specs/2026-08-07-native-cot-msm-eval-design.md`
(gitignored, local). Implementation: `native_cot.py` (grader-side patch),
`code/tinker_sweep/render.py` (`native_view`, `extract_reasoning_and_response`),
`code/tinker_sweep/tinker_provider.py` (`native_cot` model-arg).

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
