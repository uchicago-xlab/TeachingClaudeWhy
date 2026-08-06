# tinker_sweep

Teacher-transfer sweep on [Tinker](https://tinker-docs.thinkingmachines.ai):
does terra's advantage over Sonnet 5 as a difficult-advice teacher hold on
large, smart models, or is it a small-model effect? For each of the 15 instruct
models Tinker will train (7 families, 4B–550B) the sweep runs **2 finetunes**
(sonnet-teacher and terra-teacher, both on the 8% rung) and **3 evals** (base /
sonnet-ft / terra-ft, the standard 180-sample agentic-misalignment slice).

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

### 6. Eval — `run_eval.py`, via the tinker provider

`tinker_provider.py` registers an Inspect model provider named `tinker`;
importing the module is what registers it, and `code/misalignment_eval/run_eval.py`
imports it whenever `--model` starts with `tinker/`. That is also why eval runs
against Tinker use `.venv-tinker`, not `.venv-inspect`.

```bash
cd ../misalignment_eval
../../.venv-tinker/bin/python run_eval.py --model tinker/Qwen/Qwen3-8B \
    --preset core --epochs 18 --run-name tinker-qwen-qwen3-8b
../../.venv-tinker/bin/python run_eval.py --model tinker/Qwen/Qwen3-8B \
    --preset core --epochs 18 --run-name tinker-qwen-qwen3-8b-sonnet08 \
    --model-arg checkpoint=tinker://…/00042
```

`checkpoint` is the only model arg the provider takes; anything else is a hard
error, because a mistyped `-M checkpoint=` would otherwise evaluate the base model
while the log claimed a finetune. Inspect tools are refused for the same reason —
the eval uses none, and silently dropping them would let a future tool-using eval
score meaningless results.

`--no-thinking` and `--stop-token-ids` do not apply here and are refused, not
ignored. The misalignment eval packs them into `extra_body` for the OpenAI-
compatible providers; on this path thinking-off is baked into the render and stop
strings are derived from the template, so honouring them is unnecessary and
*ignoring* them silently is the failure that invalidated a whole grid on the
`openai/` provider.

Prompts are rendered by `render.py` with the same family entry and thinking-off
kwargs used at training time, so a checkpoint is sampled in the format it was
trained in; `test_provider.py` pins the sampler's prompt to
`render_generation_prompt` token-for-token and contrasts it against the
thinking-on render.

Two decisions about truncated samples, both in service of the eval staying
readable:

- **The grader never sees reasoning.** `render.extract_response` keeps the
  family's final-answer block (harmony's `final` channel, tml_v0's
  `<|content_text|>`); when the token budget ran out before that block existed,
  it strips the reasoning spans and returns what is left outside them, usually
  `""`. Returning raw text there would put a half-finished deliberation about
  leaking in front of a classifier that reads it as the response.
- **The truncation itself stays visible.** Tinker reports `length` vs `stop` per
  sequence and that becomes Inspect's `max_tokens` stop reason. Truncated
  completions grade non-harmful (see `code/misalignment_eval/README.md`), so
  without this signal a run deflated by truncation would read as a better-behaved
  model rather than a broken run.

### 7. Summarize

```bash
cd ../misalignment_eval
../../.venv-tinker/bin/python summarize.py --log-dir ../../data/misalignment-eval/logs
```

The three arms of a model table up as three separate rows because `summarize.py`
labels each row `<model id> [ckpt:<slug>]`, reading the checkpoint out of the
log's `model_args`. Run-name prefixes do **not** do this work: `log.eval.model`
is byte-identical across all three arms (the checkpoint never enters the model
id), so without the checkpoint in the label the base and both finetunes would
pool into one averaged rate. If `model_args` is missing from a log header, the
label falls back to the run directory name, which run_eval.py already stamps
with `-ckpt-<slug>`.

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

Flags: `--preset core` and `--epochs 18` are the eval grid (10 conditions × 18 =
the 180-sample slice); `--train-epochs 4` is the finetune length; `--redo <stage>`
forces one stage; `--yes` executes. Dry-run is the default and prints the plan
without running or calling anything.

Each stage is a subprocess of the same script you would run by hand, with the
same arguments, so anything that misbehaves under the driver can be reproduced
directly. Eval stages run with `cwd=code/misalignment_eval` and this same
interpreter. `{checkpoint}` in an eval command is resolved at run time from
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
  `data/misalignment-eval/logs/tinker-<slug>-sonnet08/` to
  `<name>.stale-<timestamp>` and clears `eval-sonnet` from `state.json`, printing
  both; the dry run says what it would move without touching anything. This is
  not housekeeping: `eval_set` will not re-sample conditions that already
  completed, so leaving the old log in place would mark the arm `done` over the
  **previous** checkpoint's samples. A `failed` arm is no safer than a `done`
  one — its finished conditions are the old checkpoint's and the retry skips
  exactly those, mixing two checkpoints inside one arm — so the arm's status is
  not consulted, and a driver-generated log dir with no state entry at all counts
  as stale too. Only log dirs directly under `data/misalignment-eval/logs/` with
  the run name this driver generated are ever moved, and an existing
  `.stale-<timestamp>` is never overwritten.
- **`--redo eval-*` on a finished eval samples nothing.** Inspect's `eval_set` is
  idempotent over its log directory: it runs the conditions that are not already
  complete and skips the ones that are. That is what makes an interrupted eval
  resumable, and it is why re-running a *complete* one needs its log dir moved
  aside by hand first. The driver passes explicit `--run-name`s (stable names are
  what lets `summarize.py` table the three arms), so unlike run_eval's default
  naming nothing distinguishes the log dirs of two checkpoints from the same
  model and teacher — which is exactly why the previous point has to move one.

Cost: the driver prints no estimate of its own — run the two train stages by hand
without `--yes` for token counts and a live price estimate. Log spend in
`notes/Project/` per repo convention.

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
   flipping the whole sweep to thinking-on.
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
