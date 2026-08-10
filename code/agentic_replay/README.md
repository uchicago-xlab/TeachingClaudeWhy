# agentic_replay

Difficult-advice (DA) finetunes collapse msm harm rates — ~44% → ~1% on
Qwen3-8B at the sonnet08 rung — but they damage agentic basics along the way.
Qwen3-8B's sonnet08 finetune never terminates under `--native-cot` (13/30
truncated at mt8192 *and* 12/30 at mt16384, rambling 60–70k characters);
Qwen3.6-27B's acted in only 3/30 native-CoT episodes, and 59% of standard ones
against a base rate near 98%; Inkling deliberates without ever emitting a tool
call. Every one of the 165 DA training rows is conversational, so nothing in
the training data preserves acting.

This directory is the intervention: mix self-generated agentic transcripts into
the DA training data (rehearsal/replay) and measure whether acting survives
without the alignment gain going with it. LoRA rank is held at 64 throughout, so
this experiment is about mixing alone — a parallel experiment tests low rank.
The known confound is designed around: on the msm eval the harmful thing *is*
the action, so "stopped acting" scores as aligned. Success is therefore judged
on acting rate and harm rate together, plus a benign benchmark where acting is
unambiguously the correct behavior.

Design and the decisions behind it:
`docs/superpowers/specs/2026-08-10-agentic-replay-mixing-design.md`. Results:
`notes/Project/Experiments/DifficultAdvice/AgenticReplay.md`.

Seven new finetunes, all matched to DA methodology (LoRA r64, cookbook lr,
4 epochs, val-best checkpoint):

| arm | rows | models |
| --- | --- | --- |
| DA + agentic replay, thinking-off (`mixoff`) | 165 DA + 165 replay | 8B, 27B |
| DA + agentic replay, native CoT (`mixnat`) | 165 DA + 165 replay (completions keep `<think>`) | 8B, 27B |
| replay-only (`replayonly`) | 165 replay (off) | 8B, 27B |
| DA + generic-chat replay (`mixchat`, dilution control) | 165 DA + 165 chat | 8B only |

Each model's replay is sampled from **itself** on the same prompts. Replay
prompts are third-party (Salesforce xlam function calling; WildChat for the
chat control) and only the responses are paid artifacts, which makes this a
**transfer test**: replay is JSON-schema function calling, the eval is the
email `<tool_use:…>` scaffold.

## Setup

This pipeline shares `.venv-tinker` with `code/tinker_sweep` — not the main
`.venv`, not `.venv-inspect`.

```bash
cd /home/jack/TeachingClaudeWhy
.venv-tinker/bin/pip install -r code/agentic_replay/requirements.txt
```

That pulls in the sweep's requirements plus `datasets` and `huggingface_hub`.
`TINKER_API_KEY` comes from the repo-root `.env`, which every script loads with
`python-dotenv`.

**`HF_TOKEN` is required for the prompt stage**, because
`Salesforce/xlam-function-calling-60k` is gated. Three steps, once:

1. Create a free token at `https://huggingface.co/settings/tokens` (read scope
   is enough).
2. Accept the dataset terms at
   `https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k` —
   the click-through is per account, and a token without it still 401s.
3. Add `HF_TOKEN=hf_...` to the repo-root `.env` (the same file that holds
   `TINKER_API_KEY`). Scripts load `.env` from *their own* checkout's root, so
   in a worktree that is the worktree's `.env` — usually a symlink back to the
   main checkout's, in which case one edit covers both. `select_prompts.py`
   prints the exact path it looked at when the token is missing.

Nothing else in the pipeline needs the token: sampling, mixing, training and
the benchmark all read the prompt files written by step 1.

**Status as of 2026-08-10:** `HF_TOKEN` is not in `.env` yet, so
`select_prompts.py` has only been exercised through its missing-token error.
Everything downstream of it has been exercised on synthetic prompt rows of the
same schema, and both dry runs print a real cost line. When the token lands,
re-run the free smoke before anything paid: `select_prompts.py`, then the
`sample_replay.py` and `benign_bench.py` dry runs below (no `--yes`). Each dry
run must print a *real* cost line — `no price table — no estimate` would be a
finding to chase, not a pass.

### Tests

Offline, no API keys, no paid calls (`conftest.py` strips live keys from the
test process on purpose).

```bash
cd code/agentic_replay
../../.venv-tinker/bin/python -m pytest tests/ -q
```

The native-render machinery this experiment added lives in `code/tinker_sweep`,
so run that suite too when you touch either:

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python -m pytest tests/ -q
```

## Runbook

Every command below is verbatim for **Qwen3-8B**. For **Qwen3.6-27B**,
substitute `--model Qwen/Qwen3.6-27B`, slug `qwen-qwen3-6-27b` wherever
`qwen-qwen3-8b` appears in a path, and keep `--model-name Qwen` on the eval
side. All commands run from the directory named in the step.

### 0. Budget sign-off

**Jack signs off before any `--yes`.** The spec's estimate is ~$45–55 total and
wave 1 already overran the Tinker allocation by ~$26. Every paid step's actual
spend gets logged in `notes/Project/` per repo convention — the running total
for this experiment goes in the Spend section of
`notes/Project/Experiments/DifficultAdvice/AgenticReplay.md`.

Dry runs are free and unconditional: run every paid command once without
`--yes` first, read its cost line, then re-run with `--yes`.

### 1. Prompts (free, needs `HF_TOKEN`)

```bash
cd code/agentic_replay
../../.venv-tinker/bin/python select_prompts.py
```

Expected: `wrote ... fc-train=165, fc-val=15, fc-bench=65, chat-train=165`.
Both dataset revision shas land in `manifest.json` — confirm they are there,
since without them the prompt side stops being reproducible.

### 2. Read the prompts (free, mandatory)

Read `data/agentic-replay/prompts/review-fc.txt` and `review-chat.txt` end to
end. They exist to be read by a human: the lexical screen in `fc.py` catches
what it knows about, and the spec commits to a manual read of all ~250 rows on
top of it. Drop anything security-, surveillance-, or exfiltration-flavored, or
ethics-adjacent — an ethics-flavored replay prompt would put the intervention
in the same space as the thing being measured.

If something survived the screen, delete the prompt files and re-run step 1
with a higher `--fc-scan` / `--chat-scan`, and add whatever it was to `fc.py`'s
screen so the next run catches it by rule. (`--seed` would also reshuffle the
picks, but a wider scan plus a fixed screen is the reproducible lever — record
whichever you used, since `manifest.json` carries both.) `screened-out.jsonl`
records every dropped row with its reason if you want to check the screen's aim.

### 3. Replay sampling (paid, small)

Dry-run each, then re-run with `--yes`:

```bash
cd code/agentic_replay
../../.venv-tinker/bin/python sample_replay.py --model Qwen/Qwen3-8B --split fc-train   --shape off    --yes
../../.venv-tinker/bin/python sample_replay.py --model Qwen/Qwen3-8B --split fc-train   --shape native --yes
../../.venv-tinker/bin/python sample_replay.py --model Qwen/Qwen3-8B --split fc-val     --shape off    --yes
../../.venv-tinker/bin/python sample_replay.py --model Qwen/Qwen3-8B --split chat-train --shape off    --yes   # 8B only
```

Then, per file:

- **Read the `.stats.json`.** It is a first-class result, not a log. Rejection
  rates say how reliably the base model produces a well-formed call at all, and
  a high one is a finding about the model that belongs in the notes whatever
  the training arms do. The breakdown matters too: `truncated` means the token
  cap is wrong for this model, `think-shape` means the sample carried the wrong
  reasoning shape for the view it was sampled in (see below), and a schema
  reason means the model is not speaking xlam's JSON.
- **Hand-read ~10 accepted transcripts.** The acceptance filter is objective
  and deliberately blind to correctness (see Design pointers); only a human
  read catches a file full of well-formed nonsense.
- **`rejected_rows` are missing from the file.** A row rejected after all
  `--tries` attempts is simply absent, so the file can be short of 165.
  `build_mix.py` refuses below 160 and prints a note between 160 and 165.

Two flag notes: `--tries` must be **≥ 1** (`--tries 0` crashes with a
`NameError` — known, not worth a guard), and an off-shape sample that merely
*names* a think tag inline is rejected on every attempt and dropped. That
over-rejection is deliberate: on the thinking-off path a stray `</think>` makes
`train_sft` raise `RenderMismatch` and the whole arm dies on one bad row, with
no way to drop it mid-training. It shows up as `think-shape` in the stats
alongside the `rejected_rows` entry.

### 4. Native render gate (free) — blocks `mixnat` training

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python check_render.py --model Qwen/Qwen3-8B \
    --native-training ../../data/agentic-replay/replay/qwen-qwen3-8b/fc-train-native.jsonl
```

Read the dump it writes to
`data/tinker-sweep/render-samples/<slug>-native-training.txt`. You are checking that the rendered row starts
with the native generation prompt, contains the sampled CoT verbatim inside the
trained span, and ends with the turn suffix exactly once. Run it for the 27B
before its turn as well — the two families have *opposite* native shapes (8B's
prompt does not open a think block, so the completion carries its own;
27B's prompt opens an unterminated one, so the completion starts mid-reasoning)
and only a per-model pass proves both render.

The gate reads **row 0 only**. Rows deeper in the file are covered by the
sampler's own shape screen, which is why that screen exists.

### 5. Build the mixes (free)

```bash
cd code/agentic_replay
../../.venv-tinker/bin/python build_mix.py --model Qwen/Qwen3-8B --arm mixoff
../../.venv-tinker/bin/python build_mix.py --model Qwen/Qwen3-8B --arm mixnat
../../.venv-tinker/bin/python build_mix.py --model Qwen/Qwen3-8B --arm replayonly
../../.venv-tinker/bin/python build_mix.py --model Qwen/Qwen3-8B --arm mixchat   # 8B only
```

The interleave is seeded (`--seed`, default 0). **Only ever regenerate a mix
with the seed it was built with.** The training state file records the mix
*path*, not its contents or its build parameters, so rebuilding at a different
seed silently changes what an existing run's provenance points at — same
filename, different data, no error anywhere.

### 6. Train the arms (paid)

Dry-run each for the token and cost printout, then `--yes`:

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python train_sft.py --model Qwen/Qwen3-8B \
    --train-file ../../data/agentic-replay/mixes/qwen-qwen3-8b/mixoff-train.jsonl \
    --val-file   ../../data/agentic-replay/mixes/qwen-qwen3-8b/mixoff-val.jsonl \
    --run-tag mixoff --yes
```

Repeat for `mixnat`, `replayonly` and `mixchat`, changing both file paths and
`--run-tag` together. `--train-file`, `--val-file` and `--run-tag` go together
and replace `--teacher`; a `--run-tag` that names a teacher is refused, because
it would overwrite the state file `run_model.py`'s eval stage reads.

Checkpoints and val-best selection land in
`code/tinker_sweep/runs/qwen-qwen3-8b/train-<tag>.json`.

**Checkpoint strings: copy, never retype.** Every eval below needs the arm's
`selected.sampler_path` out of that JSON. Sampler paths look like
`tinker://<opaque-id>/sampler_weights/00042` — they carry no readable model or
arm name, so a typo produces a valid-looking path to nothing, or worse, to
another arm. Copy the string; do not reconstruct it.

### 7. Evals (paid)

Standard msm slice, 180 samples per arm:

```bash
cd code/msm_eval
../../.venv-tinker/bin/python msm_eval_run.py --model tinker/Qwen/Qwen3-8B \
    --model-name Qwen --epochs 30 \
    --run-name msm-tinker-qwen-qwen3-8b-sonnet08-mixoff \
    --model-arg checkpoint=<selected.sampler_path>
```

Native-CoT variant, 30 samples per arm (mt8192 is `--native-cot`'s default cap;
`natcot` must appear in the run name or the runner warns):

```bash
../../.venv-tinker/bin/python msm_eval_run.py --model tinker/Qwen/Qwen3-8B \
    --model-name Qwen --epochs 5 --native-cot \
    --run-name msm-tinker-qwen-qwen3-8b-sonnet08-mixoff-natcot \
    --model-arg checkpoint=<selected.sampler_path>
```

Benign benchmark, **both shapes**, on the four new arms **plus base plus
DA-only** (base = omit `--checkpoint`; DA-only = the `selected.sampler_path`
from `runs/qwen-qwen3-8b/train-sonnet.json`):

```bash
cd ../agentic_replay
../../.venv-tinker/bin/python benign_bench.py --model Qwen/Qwen3-8B --shape off \
    --checkpoint <selected.sampler_path> \
    --run-name bench-qwen-qwen3-8b-mixoff-off --yes
../../.venv-tinker/bin/python benign_bench.py --model Qwen/Qwen3-8B --shape native \
    --checkpoint <selected.sampler_path> \
    --run-name bench-qwen-qwen3-8b-mixoff-native --yes
```

A `--run-name` that already has a saved result is refused before the client is
built. `--force` overwrites it, and is only for deliberately replacing a paid
result — including re-costing: a dry run under a name that already exists needs
`--force` too, so read the existing file before you pass it.

### 8. Read out the 8B

```bash
cd ../msm_eval
../../.venv-tinker/bin/python summarize.py \
    msm-tinker-qwen-qwen3-8b msm-tinker-qwen-qwen3-8b-sonnet08 \
    msm-tinker-qwen-qwen3-8b-sonnet08-mixoff msm-tinker-qwen-qwen3-8b-sonnet08-mixnat \
    msm-tinker-qwen-qwen3-8b-sonnet08-replayonly msm-tinker-qwen-qwen3-8b-sonnet08-mixchat
../../.venv-tinker/bin/python action_stats.py \
    ../../data/msm-eval/msm-tinker-qwen-qwen3-8b-sonnet08-mixoff   # ...one path per run
cd ../agentic_replay
../../.venv-tinker/bin/python benign_bench.py --table
```

`summarize.py` gives harm rates and the `trunc` column; `action_stats.py` gives
acting rate, and the two are read together — the decomposition is
reliability (acts) × disposition (harm | acted). Record everything in
`notes/Project/Experiments/DifficultAdvice/AgenticReplay.md`.

### 9. STOP-GATE before any 27B spend

The 8B `replayonly` arm's harm rate must sit near base (~0.44). If benign
replay alone collapsed harm, every mix arm is confounded — stop, and discuss
before spending on the 27B (~$20 in at that point).

### 10. The 27B

Repeat steps 3–8 with the 27B substitutions, minus the `mixchat` arm and the
`chat-train` sampling that feeds it. Before its standard evals, check what
token cap its existing runs used:

```bash
ls ../../data/msm-eval/ | grep 27b
```

Match `--max-tokens` and the `-mt<N>` suffix in your run names to what you
find. A cap change must be visible in the run name — that is a standing
decision in the sweep, and pooling two caps under one name silently mixes them.

### 11. Follow-ups

Update the spec's follow-up list as any becomes real: GPT-OSS-20B (native
recipe only — it has no thinking-off switch), the replay:DA ratio sweep, the
format-matched in-house variant if transfer is null.

## Reading the results

### The benchmark

- **`final` is the scored field; `raw` is diagnostic only.** Both are saved per
  sample. Scoring `raw` would reintroduce the bug where a distractor call
  mentioned inside the CoT is picked up as the answer. Read `raw` when you need
  to explain a rate — especially a truncated native sample, which extracts to
  an empty `final` precisely when you most want to see what happened.
- **Native `raw` starts mid-reasoning** on the 27B (no opening `<think>`: the
  prompt primes it). That is correct and matches the replay rows; it is not a
  truncated prefix.
- **`name_match` is an upper bound on task success.** A call with empty
  arguments still matches on name, and a refusal that quotes the system
  prompt's format example parses as a call and scores as acting. The bias runs
  one way — it under-detects over-refusal — so treat it as a ceiling. Report
  `name_match | valid` (`name_match_rate / valid_rate`) alongside the raw rate,
  mirroring the `harm | acted` decomposition on the msm side: it separates "did
  it act" from "did it act correctly".
- **`trunc_rate` is not comparable across shapes.** Off caps at 1024 tokens,
  native at 4096. Compare off to off and native to native.
- **n = 65.** A rate near 0.5 carries roughly ±12pp of 95% CI at that n, and
  even a rate near 0.9 carries ±7pp. "Within noise of base" is the success
  criterion's wording, and it needs that arithmetic, not eyeballing — a 5-point
  drop here is not a result.

### Off-shape scoring of native-trained checkpoints

There is no reasoning boundary in this combination, and it is the one place the
benchmark can quietly mislead. Thinking-off prompts prime an *empty* think
block, so a `mixnat` checkpoint that has learned to reason in bare prose has
that prose scored as its answer, and the first JSON object anywhere in it wins.
A `mixnat` arm's off-shape numbers therefore mix "can it still call functions"
with "did native training leak reasoning into the off view". Read the `raw`
field on a handful of those samples before quoting the rate.

### The native path is Qwen-shaped, today

The think-shape screens in `sample_replay.py` and the `--native-training` gate
are family-blind: they encode the two Qwen shapes and nothing else. A
gpt-oss, DeepSeek or Inkling native arm would burn three times the sampling
budget into a replay file that came out empty — every sample rejected as
`think-shape`. The GPT-OSS-20B follow-up needs its own screen work first; it is
not a matter of passing a different `--model`.

## Data layout

Everything is under `data/agentic-replay/`, gitignored like the rest of `data/`.

```
data/agentic-replay/
  prompts/{fc-train,fc-val,fc-bench,chat-train}.jsonl
  prompts/manifest.json, review-fc.txt, review-chat.txt, screened-out.jsonl
  replay/<slug>/{fc-train-off,fc-train-native,fc-val-off,chat-train-off}.jsonl (+ .stats.json)
  mixes/<slug>/{mixoff,mixnat,replayonly,mixchat}-{train,val}.jsonl
  bench/<run-name>.json
```

- **`prompts/`** — reproducible. `manifest.json` pins both dataset revision
  shas and the seed, so the same command rebuilds the same splits byte for
  byte. Free to regenerate.
- **`replay/`** — **paid, not regenerable**: sampled at temperature 0.7, so a
  re-run costs money and produces different transcripts. Same backup status as
  the DA pools.
- **`mixes/`** — free to rebuild from `replay/` + the adapted DA rows, *but only
  at the recorded seed* (see step 5); the mix files carry no build provenance
  of their own.
- **`bench/`** — **paid results**. One JSON per run name, holding the summary,
  every sample's `final` and `raw`, and the run's parameters. This is why the
  runner refuses to overwrite a name.

Row schemas: fc prompt `{"id", "query", "tools", "answers"}`; chat prompt
`{"id", "user"}`; replay/training row `{"messages", "meta"}` plus
`"render": "native"` on native rows only. The absence of a `render` key means
the family's standard thinking-off view — which is why `build_mix.py` treats a
present-but-null `render` as fatal rather than as absent.

## Design pointers

- **Spec:** `docs/superpowers/specs/2026-08-10-agentic-replay-mixing-design.md`
  — arms, success criteria, cost model, decision log.
- **Native render.** `render.render_native_training_example` builds the trained
  tokens *directly* (native generation prompt + encoded content + native turn
  suffix) instead of going through the template's full render. Qwen chat
  templates strip `<think>` blocks when re-rendering history, so round-tripping
  the conversation could silently drop the CoT out of the trained span — the
  arm would train on a shape it was never sampled in and nothing would fail.
  Measured, the two paths agree token for token on both Qwen families today
  (`test_render_native_training.py` pins that); the direct build is chosen
  because it does not depend on template internals no vendor promises to keep,
  and because it makes the trained prompt *the* sampling prompt by
  construction. Scope is exactly one trailing assistant turn.
- **Acceptance is objective, never correctness.** `sample_replay.accept`
  requires a parseable call naming a function from the row's own schema list,
  argument names drawn from that schema, stop reason `stop`, and non-empty
  content. It never compares against xlam's ground-truth answer. Filtering on
  correctness would turn replay into capability distillation and change what
  the experiment measures: replay is meant to preserve the model's *own*
  behavior, not to teach it better function calling.
- **Benchmark scoring is parse-based and grader-free** (spec decision 7):
  objective, free, and reproducible. Exact-argument matching was considered and
  rejected as too brittle at temperature 0.7.
