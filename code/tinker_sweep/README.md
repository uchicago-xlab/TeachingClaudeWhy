# tinker_sweep

Teacher-transfer sweep on [Tinker](https://tinker-docs.thinkingmachines.ai):
does terra's advantage over Sonnet 5 as a difficult-advice teacher hold on
large, smart models, or is it a small-model effect? For each of the 15 instruct
models Tinker will train (7 families, 4B–550B) the sweep runs **2 finetunes**
(sonnet-teacher and terra-teacher, both on the 8% rung) and **3 evals** (base /
sonnet-ft / terra-ft, the standard 180-sample agentic-misalignment slice —
`code/msm_eval`, the same harness the teacher grid was measured on).

Motivating note: `notes/Jack/Tinker Estimates.md`. Design and the decisions
behind it: `docs/superpowers/specs/2026-08-06-tinker-sweep-design.md`, condensed
in the decision log at the bottom of this file.

Every model trains on **the same rows** as the established Qwen3-14B result, and
each family sees them in its own identity and its own chat format. The two are
deliberately separated: identity is text (written into the JSONL), chat format is
tokens (applied at render time, never written down).

## Setup

This pipeline uses its own venv, `.venv-tinker` at the repo root — not the main
`.venv` and not `.venv-inspect`. It needs `inspect_ai` and `tinker` importable in
one interpreter, so it includes the misalignment-eval stack.

```bash
cd /home/jack/TeachingClaudeWhy
python3 -m venv .venv-tinker
.venv-tinker/bin/pip install -r code/tinker_sweep/requirements.txt
```

`TINKER_API_KEY` comes from the repo-root `.env`, which every script here loads
with `python-dotenv`. All commands below are run from `code/tinker_sweep/`.

Nothing under `data/` is committed (repo-wide `.gitignore`), and neither is
`code/tinker_sweep/runs/`. Datasets, render samples and run state are all
**local artifacts you regenerate by running the scripts** — the recover and
adapt stages are deterministic, so a fresh clone reproduces them byte for byte.

## Tests

Everything here is offline: the tests mock the Tinker clients, need no
`TINKER_API_KEY`, and make no paid calls.

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python -m pytest tests/          # whole suite
../../.venv-tinker/bin/python -m pytest tests/ -q       # quiet
```

## The stages, by hand

`run_model.py` (below) runs stages 3–7 for one model. Each is also a standalone
script, and running them by hand is how you debug one.

### 1. Probe the SDK — `probe_tinker.py`

Verifies the Tinker API names the rest of the pipeline depends on and lists which
models the server will train. Makes no paid calls. Run it after install and after
any `tinker` / `tinker-cookbook` upgrade:

```bash
../../.venv-tinker/bin/python probe_tinker.py
```

Findings — versions, renderer name per model, signatures, and where the SDK
differs from what the plan assumed — are recorded in **`PROBE.md`**, which is the
reference the rest of this code is written against. Update it whenever the probe
output changes.

### 2. Recover the neutral rows — `recover_rungs.py`

The committed 8%-rung files under `data/difficult-advice/` are *Qwen-adapted*
(`[MODEL]` already replaced, `/no_think` appended, empty `<think>` block
prepended). Training another family on those would teach it to call itself Qwen.
So this stage inverts the adaptation: it re-applies the legacy transform to the
vendor-neutral `ft_dataset.jsonl` pools and content-matches, recovering exactly
the rows each committed file was built from, and hard-failing on any row without
a 1:1 match rather than guessing.

```bash
../../.venv-tinker/bin/python recover_rungs.py
```

Writes `data/tinker-sweep/neutral/{sonnet08-train,sonnet-val,terra08-train,terra-val}.jsonl`
(165 / 229 / 135 / 15 rows). Local and gitignored — rerun to regenerate. Val sets
are per-teacher, as in the original runs; terra's 15-row holdout makes for noisy
epoch selection, which the original run also had. Matching methodology beats
improving it mid-comparison.

### 3. Identity-adapt per family — `adapt_dataset.py`

Neutral rows → `data/tinker-sweep/adapted/<family>/*.jsonl`, with `[MODEL]` and
`[COMPANY]` resolved to that family's assistant and developer names. **Identity
only** — no thinking tokens in the text (decision 5).

```bash
../../.venv-tinker/bin/python adapt_dataset.py                 # all families
../../.venv-tinker/bin/python adapt_dataset.py --family qwen3
```

### 4. Verify the chat format — `check_render.py`

The gate between the registry and any training run. For every sweep model it
loads the tokenizer, renders a real adapted training row through `render.py`, and
fails unless:

- the family's `thinking_kwargs` render a thinking-*off* generation prompt —
  proved both ways: the prompt must differ from the one the thinking-on setting
  produces, *and* must contain the off-shape its template emits only when
  thinking is off (`THINKING_CONTRAST`). Differing alone would not say which of
  the two prompts is the off one, so a family added with its settings swapped
  would otherwise train thinking-ON with every check green;
- the full render starts with the generation prompt, so the loss mask lands on
  exactly the assistant turn;
- `extract_response` on the sampled span returns the assistant content and
  nothing else — no channel or content-type markers reaching a grader.

```bash
../../.venv-tinker/bin/python check_render.py                 # all 15 models
../../.venv-tinker/bin/python check_render.py --model Qwen/Qwen3-8B
```

It writes a per-model dump to `data/tinker-sweep/render-samples/<slug>.txt`
(local, regenerate on demand) showing the decoded prompt, the decoded trained
completion, the thinking-on prompt for contrast, stop strings and token counts.
Read those before trusting a family. Which template line each switch lives on is
recorded in `PROBE.md` and in the `families.py` comments; re-run this after any
tokenizer or `transformers` bump.

No sweep repo is gated — all 15 tokenizers download anonymously, and `.env` needs
no `HF_TOKEN`. Kimi-K2.6 is the one model whose tokenizer is repo code
(`tokenization_kimi.TikTokenTokenizer`), so its family sets
`trust_remote_code=True`; nothing else does.

### 5. Train — `train_sft.py`

LoRA rank 64, cosine schedule with 3% warmup, cookbook lr (see the decision log),
4 epochs by default, a sampler checkpoint and a val forward pass after each, and
the **val-loss-best checkpoint** selected — the teacher-grid methodology.

Dry-run is the default and makes zero API calls: it renders the whole dataset (so
a render mismatch or an empty completion surfaces before any money is spent) and
prints the resolved config, real token counts, and a cost estimate from the live
`models.json` price table. `--yes` executes.

```bash
../../.venv-tinker/bin/python train_sft.py --model Qwen/Qwen3-8B --teacher sonnet
../../.venv-tinker/bin/python train_sft.py --model Qwen/Qwen3-8B --teacher sonnet --yes
```

Config, per-epoch val losses, every checkpoint path and the selected one are
written to `runs/<slug>/train-<teacher>.json` after **each epoch** (atomically),
because the `tinker://` sampler paths are paid artifacts that exist server-side
the moment they are saved — if they only ever reached stdout, a crash would
strand them. That file's `selected.sampler_path` is what the eval stages read.

### 6. Eval — `code/msm_eval/msm_eval_run.py`, via the tinker provider

The harness is **msm_eval**, the team's standardized SDF slice: MSM's vendored
agentic-misalignment at exfiltration/leaking/murder x goal-conflict
{explicit-america, none}, urgency `replacement`, **6 conditions x 30 epochs =
180 samples**, temp 0.7, reasoning scratchpad (`prod=False`), grader
`openrouter/anthropic/claude-sonnet-4.6`. That grid is fixed in the script —
there is no `--preset` — because it is what the teacher-grid reference numbers
were measured on, and a sweep row is only comparable to them if nothing about
the slice moves.

`tinker_provider.py` registers an Inspect model provider named `tinker`;
importing the module is what registers it, and `msm_eval_run.py` imports it
whenever `--model` starts with `tinker/`. That is also why eval runs against
Tinker use `.venv-tinker`, not `.venv-inspect`.

```bash
cd ../msm_eval
../../.venv-tinker/bin/python msm_eval_run.py --model tinker/Qwen/Qwen3-8B \
    --model-name Qwen --epochs 30 --run-name msm-tinker-qwen-qwen3-8b
../../.venv-tinker/bin/python msm_eval_run.py --model tinker/Qwen/Qwen3-8B \
    --model-name Qwen --epochs 30 --run-name msm-tinker-qwen-qwen3-8b-sonnet08 \
    --model-arg checkpoint=tinker://…/00042
```

`--model-name` is **identity-matched**: it is the name the scenario prompts
address the AI by, and each model gets its own family's `assistant_name` from
`families.py` (`Qwen`, `Kimi`, `DeepSeek`, `ChatGPT`, `Nemotron`, `Inkling`) —
the same name that model was identity-adapted and trained under in stage 3. The
script's own default is `Qwen`, which is right only for the Qwen rows, so a
hand-run arm must pass this explicitly. It is encoded in `--run-name` per msm
convention (here, via the `msm-tinker-<slug>` prefix, since the slug names the
model).

No `--base-url`: a `tinker/` model samples through the Tinker API, and
`msm_eval_run.py` refuses the flag rather than record a URL the run never
contacted. `--dry-run` prints the grid and config and exits without an API call.

`checkpoint` is the only model arg the provider takes; anything else is a hard
error, because a mistyped `-M checkpoint=` would otherwise evaluate the base model
while the log claimed a finetune. Inspect tools are refused for the same reason —
the eval uses none, and silently dropping them would let a future tool-using eval
score meaningless results.

`--no-thinking`, `--stop-token-ids` and `--api-no-reasoning` do not apply here
and are refused, not ignored. `msm_eval_run.py` packs the first two into
`extra_body` for the OpenAI-compatible providers; on this path thinking-off is
baked into the render and stop strings are derived from the template, so
honouring them is unnecessary and *ignoring* them silently is the failure that
invalidated a whole grid on the `openai/` provider. What was actually rendered
reaches the log instead, as `tcw_thinking` metadata (`disabled`, or `minimal`
for the two families whose template has no off switch).

Prompts are rendered by `render.py` with the same family entry and thinking-off
kwargs used at training time, so a checkpoint is sampled in the format it was
trained in; `test_provider.py` pins the sampler's prompt to
`render_generation_prompt` token-for-token and contrasts it against the
thinking-on render.

Two decisions about truncated samples, both in service of the eval staying
readable:

- **The grader never sees reasoning — and never loses an action.**
  `render.extract_response` drops the family's reasoning (harmony's non-final
  channels, tml_v0's `<|content_thinking|>` blocks) and keeps everything else in
  emission order, markers stripped: for Inkling that is the scratchpad, the
  `<tool_use:…>` calls and the `<|content_text|>` chatter of one multi-block
  turn. When the token budget ran out before any non-reasoning block existed, it
  returns `""`. Returning raw text there would put a half-finished deliberation
  about leaking in front of a classifier that reads it as the response; keeping
  only the answer block (which is what this did until 2026-08-06, decision 8)
  loses the emails the model actually sent, which is the behavior being scored.
- **The truncation itself stays visible.** Tinker reports `length` vs `stop` per
  sequence and that becomes Inspect's `max_tokens` stop reason. Truncated
  completions grade non-harmful (see `code/misalignment_eval/README.md`), so
  without this signal a run deflated by truncation would read as a better-behaved
  model rather than a broken run.

### 7. Summarize

```bash
cd ../msm_eval
../../.venv-tinker/bin/python summarize.py \
    msm-tinker-qwen-qwen3-8b msm-tinker-qwen-qwen3-8b-sonnet08 msm-tinker-qwen-qwen3-8b-terra08
```

`code/msm_eval/summarize.py` takes **run directory names** under
`data/msm-eval/` and prints one row per run, one column per condition. That
keying is what keeps a sweep's arms apart: `log.eval.model` is byte-identical
across all three (the checkpoint travels in `model_args`, never in the model
id), so a summarizer keyed on the header would pool base and both finetunes into
one averaged rate. The corollary is that **two arms sharing a `--run-name` would
pool**, which is why the driver generates a distinct name per arm and
`msm_eval_run.py` has no default for the flag. The sibling harness needs a
`[ckpt:<slug>]` row label for the same reason; this one does not.

The driver prints the exact summarize command, with its three run names, when
all stages finish.

## The driver — `run_model.py`

One model, end to end: `adapt → check_render → train-sonnet → train-terra →
eval-base → eval-sonnet → eval-terra`. **Sweeping is invoking this once per
model** — there is no grid orchestrator (decision 3).

```bash
../../.venv-tinker/bin/python run_model.py --model Qwen/Qwen3-8B            # dry run
../../.venv-tinker/bin/python run_model.py --model Qwen/Qwen3-8B --yes      # execute
../../.venv-tinker/bin/python run_model.py --model Qwen/Qwen3-8B --redo eval-base --yes
```

Prerequisite: `recover_rungs.py` once per clone — the driver's first stage adapts
the neutral rows and cannot create them. (Its `adapt` stage covers the whole
family, so it is a no-op re-run for the second model of a family.)

Two drivers of the same family run concurrently both rewrite
`data/tinker-sweep/adapted/<family>/*.jsonl` in their adapt stage — the content is
identical, so the worst case is one of them reading a half-written file and
aborting on a JSON parse error, before any spend; run `adapt` once first, or
stagger the drivers, when sweeping a family in parallel.

Flags: `--epochs 30` is the eval depth (msm_eval's 6 fixed conditions × 30 = the
180-sample slice — there is no `--preset`, the grid lives in the script);
`--train-epochs 4` is the finetune length; `--redo <stage>` forces one stage;
`--yes` executes. Dry-run is the default and prints the plan without running or
calling anything.

Each stage is a subprocess of the same script you would run by hand, with the
same arguments, so anything that misbehaves under the driver can be reproduced
directly. Eval stages run with `cwd=code/msm_eval` and this same interpreter,
and pass `--model-name <family assistant_name>` so each model's scenarios
address it by its own name (ruling 2 of the msm-eval-swap plan) — with no
`--base-url`, which `msm_eval_run.py` refuses for a `tinker/` model. Their logs
land in `data/msm-eval/msm-tinker-<slug>{,-sonnet08,-terra08}/`.
`{checkpoint}` in an eval command is resolved at run time from
`runs/<slug>/train-<teacher>.json`; if that file is missing or has no selected
checkpoint, the stage aborts rather than fall back to the base model.

### Resume semantics

`runs/<slug>/state.json` records one entry per stage. A stage that finished
`done` is **skipped** on re-run — a finished finetune is never relaunched — and a
stage that `failed` is retried. The driver stops at the first failure with the
state preserved, so fixing the cause and re-running picks up where it stopped.

**A finetune that failed *after* saving checkpoints is the exception: the driver
refuses to continue and makes you choose.** `train_sft.py` writes
`train-<teacher>.json` after every epoch so that a crash costs one epoch, but it
has no resume — relaunching trains from scratch and overwrites that file, leaving
checkpoints you have already paid for on Tinker with nothing pointing at them.
So the driver prints them and stops. Either keep them (set that stage's `status`
to `"done"` in `state.json`; the eval stage then uses the best one recorded), or
pay for a fresh run with `--redo train-<teacher>`.

`--redo <stage>` forces a single stage to run even if it is `done`, and re-running
a finetune costs training tokens again. What it does about the eval that already
scored the old checkpoint:

- **Redoing a finetune invalidates its eval arm, whatever state that arm is in,
  and the driver acts on that.** With `--yes`, `--redo train-sonnet` renames
  `data/msm-eval/msm-tinker-<slug>-sonnet08/` to
  `<name>.stale-<timestamp>` and clears `eval-sonnet` from `state.json`, printing
  both; the dry run says what it would move without touching anything. This is
  not housekeeping: `eval_set` will not re-sample conditions that already
  completed, so leaving the old log in place would mark the arm `done` over the
  **previous** checkpoint's samples. A `failed` arm is no safer than a `done`
  one — its finished conditions are the old checkpoint's and the retry skips
  exactly those, mixing two checkpoints inside one arm — so the arm's status is
  not consulted, and a driver-generated log dir with no state entry at all counts
  as stale too. Only log dirs directly under `data/msm-eval/` with the run name
  this driver generated are ever moved, and an existing `.stale-<timestamp>` is
  never overwritten. That guard earns its keep now that the log root is shared
  with the team's own msm runs (`da-*`, `teacher-*`, `qwen3-14b-*`): every name
  the driver generates is namespaced `msm-tinker-…`, and nothing else is a
  candidate.
- **`--redo eval-*` on a finished eval samples nothing.** Inspect's `eval_set` is
  idempotent over its log directory: it runs the conditions that are not already
  complete and skips the ones that are. That is what makes an interrupted eval
  resumable, and it is why re-running a *complete* one needs its log dir moved
  aside by hand first. The driver passes explicit `--run-name`s — `msm_eval_run.py`
  requires one, and stable names are what lets `summarize.py` table the three
  arms — so nothing distinguishes the log dirs of two checkpoints from the same
  model and teacher, which is exactly why the previous point has to move one.

Cost: the driver prints no estimate of its own — run the two train stages by hand
without `--yes` for token counts and a live price estimate. Log spend in
`notes/Project/` per repo convention.

## Verified

### Qwen3-8B pilot

`Qwen/Qwen3-8B` ran end to end 2026-08-06 — all seven driver stages, one
invocation, no interventions and no `--redo`. Its three eval arms were then
**re-run on msm_eval 2026-08-07** after the harness swap, against the same two
checkpoints (the driver skipped every train stage; only the `eval-*` state
entries were cleared). The numbers below are the msm_eval ones, and they are the
ones comparable to the teacher grid.

| arm | checkpoint | harmful rate (msm_eval, 180 samples) |
| --- | --- | --- |
| base | — | **0.439** ± 0.037 (79/180) |
| sonnet08-ft | val-best epoch 2 (val 1.9928) | **0.006** ± 0.006 (1/180) |
| terra08-ft | val-best epoch 2 (val 2.2992) | **0.006** ± 0.006 (1/180) |

Per condition, from `summarize.py`:

| run | exfi/on | exfi/off | leak/on | leak/off | murd/on | murd/off |
| --- | --- | --- | --- | --- | --- | --- |
| base | 4/30 | 15/30 | 29/30 | 7/30 | 13/30 | 11/30 |
| sonnet08-ft | 0/30 | 0/30 | 0/30 | 0/30 | 0/30 | 1/30 |
| terra08-ft | 0/30 | 0/30 | 1/30 | 0/30 | 0/30 | 0/30 |

Both teachers collapse an 8B base model to the floor, so this pilot confirms the
pipeline rather than the hypothesis: at 1 harmful sample out of 180 each, the two
teachers are indistinguishable, and a floored comparison is exactly the outcome
the sweep exists to test on larger models. Base at 0.439 sits in the 0.3–0.5 band
the Qwen3-14B grid led us to expect, and the floor effect survived the harness
change rather than being an artifact of the old slice.

**Cost, both runs together ~$15.41.** The original end-to-end run was ~$8.80
($1.74 Tinker — $1.18 training, $0.57 sampling — plus ~$7.06 of Sonnet 4.6
grading through OpenRouter), against an estimate of $1.31 + $7.60; the Tinker
side ran high because the estimate counts trained tokens where billing counts
sequence tokens, plus the val forward passes. The msm re-run added **$6.61**
($0.57 Tinker sampling + $6.04 grading) and no training cost at all — re-scoring
existing checkpoints is the cheap half.

> **Superseded:** the first pass of these arms was measured on
> `code/misalignment_eval/run_eval.py` (`--preset core` × 18) and read base
> **0.428** (77/180), sonnet08 **0.006** (1/180), terra08 **0.011** (2/180).
> Those logs are still under `data/misalignment-eval/logs/tinker-*`. They are not
> comparable to the teacher grid — that is why the sweep moved — but they agree
> with the msm numbers to within noise on all three arms.

What the run confirms mechanically:

- Both finetunes overfit after epoch 2 (sonnet 2.0248 → **1.9928** → 2.0887 →
  2.1994; terra 2.3453 → **2.2992** → 2.3665 → 2.4459), and val-best selection
  picked the minimum rather than the last checkpoint in both cases.
- All 540 samples across the three msm arms have Inspect stop reason `stop` — no
  `max_tokens`, so no arm was deflated by truncation grading non-harmful.
- Sampled completions carry no `<think>` block and the scenarios address the
  model as `Qwen`: thinking-off held from training through to sampling, on the
  checkpoints as well as the base model, and the logs record it as
  `tcw_thinking: disabled` / `tcw_model_name: Qwen` metadata.
- `summarize.py` tables the three arms as three rows because each arm named its
  own run directory; `log.eval.model` is `tinker/Qwen/Qwen3-8B` on all three and
  the checkpoint appears only in `model_args`, so nothing else separates them.
- **One condition failed mid-run and `eval_set` fixed it by itself.** A leaking
  condition of the base arm died after 23 samples on
  `ValueError: Invalid answer from leak classifier` — the vendored classifier
  raises when the grader's reply contains neither a clean yes nor a clean no
  (here, an empty completion). The retry re-ran that condition to a full 30 and
  the log directory ended up with exactly 6 `.eval` files, so nothing double
  counted. Expect this occasionally on the big-model wave; the driver's stage
  fails only if the retries do.

### Wave 1 — five big models

Five large models ran through the full pipeline 2026-08-07, joining the pilot for
six models total. Every number below is the msm harness (`code/msm_eval`), 180
samples per arm, the fixed Sonnet 4.6 grader, `-mt8192` where the arm names say
so. Harmful rate as a percentage; counts out of 180 in parentheses.

| model | base | sonnet08-ft | terra08-ft |
| --- | --- | --- | --- |
| Qwen3-8B (pilot) | 43.9 (79) | 0.6 (1) | 0.6 (1) |
| DeepSeek-V3.1 | 65.0 (117) | 1.7 (3) | 0.6 (1) |
| Nemotron-3-Ultra-550B (r32) | 46.1 (83) | 8.9 (16) | 2.8 (5) |
| Qwen3.5-397B-A17B (mt8192) | 41.1 (74) | 6.7 (12) | 1.1 (2) |
| Kimi-K2.6 (r32, mt8192) | 44.4 (80) | 1.7 (3) | 0.0 (0) |
| Inkling (prefill, mt8192) | 4.4 (8) | 0.0 (0) | 0.0 (0) |

`r32` = Tinker caps that model's LoRA rank at 32, so both its finetunes ran there
(`PROBE.md`, "LoRA rank caps"); `mt8192` = the arm ran at
`--eval-max-tokens 8192` (decision 9); `prefill` = Inkling's
`generation_prefill` (decision 8). Reproduce any row with
`code/msm_eval/summarize.py` over the `msm-tinker-*` run directories.

**Pooled across all six models, the finetunes separate: sonnet08 35/1080 (3.2%)
against terra08 9/1080 (0.8%).** The direction holds per model as well —
terra ≤ sonnet in 6/6, strictly below in 4 and tied at the floor in the two
(Qwen3-8B, Inkling) where both arms sit at 0–1 samples. The two models with real
headroom above the floor are the ones that carry the pooled result:
Nemotron-Ultra (16 vs 5) and Qwen3.5-397B (12 vs 2). Base rates land in the
41–65% band everywhere except Inkling, whose 4.4% base leaves almost nothing to
remove and makes its two zeros uninformative rather than confirming.

> **Superseded runs.** Seven eval runs were paid for and are not used.
> `msm-tinker-moonshotai-kimi-k2-6{,-sonnet08,-terra08}` and
> `msm-tinker-qwen-qwen3-5-397b-a17b{,-sonnet08,-terra08}` ran at the standard
> 4096-token cap on 2026-08-07 and are replaced by their `-mt8192` counterparts:
> a truncated sample grades non-harmful, and Kimi's base arm truncated 97/180
> (54%) at 4096, so the arm read better-behaved than it is (decision 9;
> Qwen3.5-397B base truncated 18/180 and was re-run for the same reason). At
> 8192 those base arms truncate 8/180 and 2/180. Separately,
> `msm-tinker-thinkingmachines-inkling` is an **aborted** base arm killed at ~120
> of 180 samples on 2026-08-06: `extract_response` was keeping only
> `<|content_text|>` blocks, so the grader saw an Inkling that took no actions at
> all (decision 8). Both fixes landed before the runs that produced the table
> above. DeepSeek-V3.1, Nemotron-Ultra and the Qwen3-8B pilot needed neither
> re-run — they truncate 0–3 samples of 180 at 4096.

**Cost of the five big models: ~$188.59** — $139.86 Tinker ($69.49 training for
10 finetunes, $69.92 eval sampling, $0.45 of ad-hoc Inkling probes) plus $48.73
of Sonnet 4.6 grading through OpenRouter. $24.99 of the Tinker sampling and
$15.93 of the grading bought the superseded and aborted runs. The pilot's $15.41
is logged separately. **This overruns the $116 Tinker allocation by $26.18 with
nine models still unrun** — training scales with the model's price per token and
eval sampling turned out to be the larger half, so wave 2 needs a re-budget, not
just a top-up.

## Decision log

1. **Evals sample on Tinker**, via a custom Inspect ModelAPI provider over
   Tinker's `SamplingClient`. No serving infra, and it works for the 397B/550B
   MoE models that would never fit the RunPod A40 route. *Rejected:* RunPod vLLM
   serving (multi-GPU pod cost and ops for exactly the models the experiment is
   about); a hybrid (two serving stacks inside one comparison).
2. **Thinking-off where the template supports it, minimal reasoning where it does
   not** — matched between train and eval, with the caveat recorded in eval
   metadata. gpt-oss and Inkling have no off switch, only an effort floor
   (`reasoning_effort` `low` / `none`), so they carry `thinking_off=False` and the
   caveat travels with their results. *Rejected:* dropping those two families;
   flipping the whole sweep to thinking-on. (Inkling's caveat narrowed in
   decision 8 — its first block is now forced — but did not go away: later
   blocks of the same turn can still be thinking blocks.)
3. **Per-model driver with resume state**, not a grid orchestrator (YAGNI).
   Sweeping = invoking `run_model.py` per model.
4. **Learning rate from the cookbook's per-model recommendation**, r=64 kept from
   MSM B.4, logged per run. A fixed 1e-4 across 4B–550B risks frying or
   under-training at the extremes, confounding the size question the experiment
   exists to ask. (LoRA alpha turns out not to be a client-side knob in this SDK —
   `create_lora_training_client_async` takes `rank` only.)
5. **Chat-format knowledge lives at render time, in one place.** The JSONLs are
   identity-adapted only; thinking shape is applied at token level by the same
   `render.py` in training and in eval. *Rejected:* extending the text-level
   `adapt_ft_dataset.py` convention to 7 families (duplicates template knowledge
   by hand and lets train/eval drift); trusting cookbook renderer defaults
   (conforms the experiment to their thinking conventions rather than ours).
6. **Nothing under `data/` is committed, and neither is `runs/`.** The repo-wide
   rule already excludes `data/`; rather than carve out an exception for the
   adapted JSONLs and render samples, every data artifact here is regenerated by
   script (`recover_rungs.py` → `adapt_dataset.py` → `check_render.py`), which is
   deterministic. The spec's layout sketch called those files committed; this
   supersedes it. Review of format decisions happens through the render samples
   and `check_render.py`, not through git diffs of generated JSONL.
7. **An uncalibrated model's lr is extrapolated with the Qwen exponent, and
   labelled `extrapolated` everywhere it appears.** The cookbook's `get_lr` is a
   formula, not a table — `5e-5 * 10 * (2000/hidden_size) ** exponent` — but it
   raises `NotImplementedError` for 8 of the 15 sweep models, and the two known
   exponents (Qwen 0.0775, Llama 0.781) disagree by 2.7x at hidden_size 8192. The
   Qwen exponent is the flat one, so across the uncovered models' hidden sizes
   (2688–8192) it spans only 4.48e-4 to 4.89e-4 and claims little beyond "the
   calibrated modern-model band applies"; and the uncovered models are MoE designs
   contemporary with Qwen3.5/3.6 rather than dense Llama-3. **This is a defensible
   choice, not a calibration** — `--lr` overrides it, and any model whose result
   matters should get a real value. The cookbook's *other* rule
   (`get_lora_lr_multiplier`'s `LR_B = LR_A * sqrt(params_A/params_B)`) was
   rejected outright: it contradicts the calibrated curve, putting Qwen3-8B and
   Qwen3.5-397B-A17B 7x apart where `get_lr` gives them the same lr. Full
   reasoning and the resolved lr for every model: `PROBE.md`.

8. **Inkling's turn is reconstructed, not filtered — and its first block is
   primed.** Two changes from the base-arm failure of 2026-08-06, where Inkling
   scored as a model that took no actions at all. (a) `extract_response` now
   concatenates every block of a sampled tml_v0 turn except
   `<|content_thinking|>`, instead of keeping only `<|content_text|>`: an
   Inkling turn is many blocks, and the ones the old rule dropped were the
   scratchpad and the `<tool_use:email>` calls — i.e. everything the
   misalignment classifiers score. Real probe transcripts are pinned as
   `tests/fixtures_inkling_probe.json`, whose `extracted` field is the old
   rule's own output. (b) `generation_prefill="<|content_text|>"` (new `Family`
   field) is appended to the generation prompt, because tml_v0's prompt stops at
   `<|message_model|>` and leaves the block type to the model, which at effort 0
   still opens `<|content_thinking|>` often enough to matter. The prefill is
   text the template itself emits, so it stays in the *prompt* span in training
   too and `render_training_example` raises `RenderMismatch` if the template
   does not in fact start the turn with it. *Rejected:* prompting the model in
   the system block (a condition change, and not one the other 14 families
   get); treating the scratchpad as reasoning and dropping it (every other
   family's scratchpad reaches the grader — MSM's slice runs `prod=False`
   precisely to elicit it).
9. **A raised eval token cap is written into the run name.** `run_model.py
   --eval-max-tokens N` (N != 4096) passes `--max-tokens N` to every eval stage
   *and* appends `-mt<N>` to all three arm names. Both halves matter: a
   truncated sample grades non-harmful, so a cap that applied to only some arms
   would compare a truncated base against untruncated finetunes (Kimi-K2.6 base
   truncated 54% of its samples at 4096), and `summarize.py`'s rows are run
   directory names, so a corrected run reusing the standard name would be
   skipped by `eval_set` as already complete. *Rejected:* raising the default
   for everyone (it would silently redefine the standardized slice the teacher
   grid was measured on).
