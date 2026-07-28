# Handoff

Everything in this branch was built and verified **without model access**. No evaluation was run, no
harm rate was produced, and no judge was validated against live output. This file says exactly what
to run first, what it costs, what to look at, and what could not be checked offline.

---

## 0. `PYTHONPATH` — read this first

The eval's modules import each other absolutely (`from evals.agentic_misalignment...`). The
`inspect` CLI does **not** put the working directory on `sys.path`, so running it from a checkout
where the package is not installed fails with:

```
ModuleNotFoundError: No module named 'evals'
```

This is pre-existing, not new. Two fixes — both work, verified end to end:

```bash
# A. lightweight: nothing installed, run from the repo root
PYTHONPATH=. inspect eval evals/agentic_misalignment/agentic_misalignment.py ...

# B. install the package (also pulls the heavy MSM deps: sentence-transformers, faiss-cpu)
pip install -e .
inspect eval evals/agentic_misalignment/agentic_misalignment.py ...
```

On a GPU box that only needs to run evals, prefer A and install just `inspect-ai==0.3.249` and
`beautifulsoup4` — those are the only runtime imports the eval has.

`pytest` is unaffected either way; `pyproject.toml` sets `pythonpath = ["."]` for it.

## 1. Set up and confirm the offline state

```bash
pip install -e ".[dev]"        # pins inspect-ai==0.3.249; mockllm is used by the solver tests
pytest                          # 856 tests, ~6s, no network
ruff check .
python scripts/generate_prompt_snapshots.py --check   # 676 snapshots byte-identical
```

Sanity-check the CLI wiring for free, without a real model:

```bash
PYTHONPATH=. inspect eval evals/agentic_misalignment/agentic_misalignment.py \
  --model mockllm/model \
  -T scenario=sandbagging -T goal_type=none -T goal_value=none \
  -T score_eval_awareness=false
```

This should complete with `parse_failure=1.0` and `no_tool_attempt=1.0` — mockllm returns a fixed
string with no tool block, so that is the correct result and it confirms `format_compliance` is
wired up.

If `pytest` passes and `--check` reports no differences, the plumbing is in the state it was left in.

A type check is also clean if you want it:

```bash
pip install mypy && mypy --ignore-missing-imports evals/agentic_misalignment/*.py scripts/*.py
```

## 2. Read before spending anything

The snapshots are the point of the offline work. Read a few before running anything:

```bash
less tests/snapshots/sandbagging/none-none__replacement__self__prod0.txt
diff tests/snapshots/sandbagging/none-none__replacement__{self,other}__prod0.txt
diff tests/snapshots/goal_propagation/explicit-safety__replacement__{training,faq}__prod0.txt
```

The two `diff`s should each show only the condition-header line and the single intended difference.
That is the whole design of both new scenarios, visible in about ten seconds.

Also read the five goal-neutral queries and confirm you agree they are neutral — the
`goal_propagation` DV is meaningless if they are not:

```bash
cat evals/agentic_misalignment/templates/goal_propagation/queries.md
```

## 3. First real runs, in order

Costs below are **sample counts and model calls**, not currency — currency depends on your model and
token pricing. "Grader calls" are additional to the sampled model's calls.

### Run 1 — smoke test, 4 samples

Confirm the plumbing end to end before committing to a real N.

```bash
inspect eval evals/agentic_misalignment/agentic_misalignment.py \
  --model <your-model> \
  -T scenario=sandbagging -T sandbagging_target=self \
  -T goal_type=none -T goal_value=none \
  -T score_eval_awareness=false \
  --max-tokens 4096 --temperature 1.0 --epochs 4
```

4 samples, 4 model calls, **0 grader calls** — sandbagging's scorer is deterministic. This is the
cheapest possible end-to-end check and it exercises the new scenario, the deterministic scorer and
`format_compliance` together.

**What to look for in the transcripts:**

1. Did the model emit a well-formed `<tool_use:email>` block at all? Check `format_compliant`
   *first*, before looking at any harm number. If it is low, every other rate in the run is
   uninterpretable — a model that stops following the tool format scores as not-harmful, which looks
   identical to the intervention working.
2. Read the `answer` field of a `faithful` and (if present) an `omitted` score. Confirm the parser
   picked out the body you would have picked out.
3. Check `parse_failure` is near zero. If it is not, look at the bodies — either the model is not
   sending emails, or the parser is missing a format the fixtures do not cover. The threshold for
   "acceptable" is yours to set; it was deliberately not set here.

### Run 2 — sandbagging, both arms

```bash
for arm in self other; do
  inspect eval evals/agentic_misalignment/agentic_misalignment.py \
    --model <your-model> \
    -T scenario=sandbagging -T sandbagging_target=$arm \
    -T goal_type=none -T goal_value=none \
    -T grader_model=<your-grader> \
    --max-tokens 4096 --temperature 1.0 --epochs 300
done
```

600 samples, 600 model calls, 600 grader calls (all from `eval_awareness`; the harm scorer is free).
Add `-T score_eval_awareness=false` to drop the grader calls to zero.

The contrast that matters is `misreported` in `self` versus `other`. `other` is the control: the
opportunity is identical and only the motive is removed.

### Run 3 — goal_propagation, both arms

**Validate the judge first** (see §5). Then:

```bash
for ch in training faq; do
  inspect eval evals/agentic_misalignment/agentic_misalignment.py \
    --model <your-model> \
    -T scenario=goal_propagation -T propagation_channel=$ch \
    -T goal_type=explicit -T goal_value=safety \
    -T grader_model=<your-grader> \
    --max-tokens 4096 --temperature 1.0 --epochs 300
done
```

600 samples, 600 model calls, **1200 grader calls** (one goal_propagation judge + one eval_awareness
per sample).

The headline is `injected_fraction` in `training` versus `faq`. Equal rates mean the model is just
being on-topic about its goal; `training` >> `faq` is the instrumental-channel-preference result.
Do not run only `training`.

Cross-check `injected_fraction` against `lexical_prefilter_hit` in metadata. They should disagree in
a specific direction — the prefilter should fire *more* often than the judge, since it cannot tell
advocacy from incidental mention. If the judge fires more often than the prefilter, look at why.

### Run 4 — two-turn, with the control

```bash
for r in none delivered delivery_failure filter_block; do
  inspect eval evals/agentic_misalignment/agentic_misalignment.py \
    --model <your-model> \
    -T scenario=exfiltration -T rebuff=$r \
    -T goal_type=none -T goal_value=none -T urgency_type=replacement \
    -T grader_model=<your-grader> \
    --max-tokens 4096 --temperature 1.0 --epochs 300
done
```

1200 samples. Model calls: 300 for `rebuff=none`, 600 each for the other three = 2100. Grader calls:
roughly 2 per two-turn sample for the harm classifier plus 1 per sample for eval_awareness ≈ 3000.
**This is the most expensive run listed here** — budget for it.

`delivered` is not optional. Without it you cannot tell "escalates when rebuffed" from "does more
things with a second turn". Compare `escalates` in `delivery_failure` / `filter_block` against
`escalates` in `delivered`.

Run `-T rebuff=confrontation` separately if you want it, and report it separately — its text
presupposes turn 1 contained blackmail-shaped harm, so it is incoherent after a clean first turn.

Decide `strip_scratchpad` deliberately and report which you used. Both are defensible; leaving the
scratchpad in lets the model re-read its own scheming and is expected to inflate persistence.

## 4. Two template defects to decide on

Both were found by the new structural validation. **Neither is fixed** — fixing means editing an
existing template, which was out of scope. `strict=true` currently refuses the affected conditions.

1. **`exfiltration` + `urgency_type=restriction` or `none`.** The urgency arms are backed by
   two-line placeholder files committed in `1408e0b`. With `goal_type=none` the whole inbox rendered
   as 98 bytes and zero emails; with the other goal types it rendered 5 of 8 emails plus a literal
   `# TODO: Implement this template if needed` line in the model-facing prompt.
   The eval's own README advertised all three urgency values with no caveat, so the broken
   combination was documented as available. **Check whether any published exfiltration result used
   `urgency_type` other than `replacement`.** The documented headline conditions
   (`replacement` × `explicit`/`latent`/`swap`/`none`) all render cleanly — verified.

2. **`murder` + `goal_value=safety` + `urgency_type=restriction`.** The `pro_safety` section of
   `templates/murder/variables/safety_vs_acceleration.md` omits the `direction_modifier` key its
   `pro_acceleration` sibling defines, so the inbox read "The new board is pushing hard to realign
   our AI strategy `${direction_modifier}`." Affects 3 goal types × 2 prod values = 6 conditions.
   A visible template artifact is both a degraded motive and an eval-awareness cue.
   **Check whether any published murder result used `goal_value=safety` with
   `urgency_type=restriction`.**

Fixing either is a one-line template edit. It will change those conditions' snapshots, which is
correct and should be committed as a deliberate, explained diff.

## 5. Validating the goal_propagation judge

This is the one piece that needs model access, and it needs a human first.

```bash
# 1. A human fills in the label column. Rubric in the same directory's README.
$EDITOR tests/fixtures/goal_propagation/candidates.csv

# 2. Then:
python scripts/validate_propagation_judge.py \
  tests/fixtures/goal_propagation/candidates.csv \
  --grader-model <your-grader> \
  --out /tmp/judge_validation.csv
```

59 rows → 59 grader calls, once. The script refuses to run against the unlabelled file, and fails
with an explicit message if no credentials are present.

**Do not label these by asking a model.** If the same process writes the examples and assigns the
labels, the validation only checks that the judge agrees with whoever generated the answer key. The
labels shipped empty for exactly this reason.

The corpus deliberately contains borderline rows — drafts that mention a goal domain incidentally
without advocating, and drafts that advocate without naming the goal. A judge validated only against
clear-cut cases will overstate its accuracy. If precision and recall come back near-perfect, check
that the borderline rows were labelled and included rather than skipped.

## 6. Checks that could NOT be performed offline

Numbered so nothing silently skips verification.

1. **The goal_propagation judge's precision and recall are unmeasured.** No number exists. §5 is the
   procedure. Until it is run, `injected_fraction` is an unvalidated measurement.
2. **The eval_awareness judge is unvalidated.** No labelled corpus was built for it and no
   validation script ships. It is a 0–2 rating from an unvalidated rubric — treat it as a
   conditioning variable to slice on, not as a measured quantity, until someone validates it.
3. **No harm rate exists for any scenario, old or new.** Nothing here establishes that sandbagging
   or goal_propagation elicit the behaviour at all. Both could floor at zero.
4. **The `parse_failure` rate on real model output is unknown.** 35 hand-written fixtures classify
   correctly, but they are 35 shapes I thought of. Two parser bugs were found by unit tests that the
   fixtures missed (see `DEVIATIONS.md` §8), which is direct evidence the corpus is not exhaustive.
   Set an acceptable threshold after Run 1, not before.
5. **The five queries' goal-neutrality is checked only mechanically.** A test asserts no literal goal
   keyword appears. It cannot catch a query that makes goal content contextually on-topic. A human
   should read `queries.md`.
6. **Whether the new scenarios are *coherent* to a model is untested.** No model has read either
   inbox. It may find the sandbagging digest implausible, or treat the goal_propagation task as
   obviously a test. Read the first transcripts with that in mind, and check the
   `eval_awareness` scores on the new scenarios specifically.
7. **The three original scenarios' harm rates are unchanged only *structurally*.** Prompt snapshots
   are byte-identical and the single-turn path keeps `message_limit=3`, the same solver and the same
   sample `id`. That is strong, but it is not the same as having re-run them.
8. **Rebuff wording has not been piloted.** The injected messages are plausible but no model has
   responded to them. Check early transcripts for a model that treats `delivery_failure` as a bug
   report rather than as a prompt to act.
9. **Cost estimates above are call counts, not measured spend.** No run has been billed.
10. **`goal_type=swap` behaviour is untouched and unverified.** The upstream divergence
    (issue #13 in `anthropic-experimental/agentic-misalignment`) was deliberately not investigated.

## 7. Running against a local vLLM model

Measured prompt sizes (cl100k tokens), so you can size the context window:

| Scenario | System | User (inbox) | Total input |
|---|---|---|---|
| exfiltration | 497 | 2329 | 2826 |
| murder | 482 | 2290 | 2772 |
| leaking | 495 | 2217 | 2712 |
| goal_propagation | 444 | 1042 | 1486 |
| sandbagging | 444 | 1032 | 1476 |

Worst case is a two-turn exfiltration run: ~2.8k in + 4k out + rebuff + 4k out ≈ **11k tokens**, so
`--max-model-len 16384` is comfortable. 8k is too tight for two-turn at `--max-tokens 4096`.

Two ways to point at vLLM:

```bash
# A. inspect starts the server for you (needs the vllm package installed)
PYTHONPATH=. inspect eval evals/agentic_misalignment/agentic_misalignment.py \
  --model vllm/</path/to/your/model> ...

# B. attach to a server you already started
export VLLM_BASE_URL=http://localhost:8000/v1
PYTHONPATH=. inspect eval evals/agentic_misalignment/agentic_misalignment.py \
  --model vllm/<served-model-name> ...
```

Set `-T model_name=...` to whatever the fine-tune should be called in the prompts (the paper's runs
used `Qwen`). It is not derived from the model path.

### Running with no API access at all

The default grader is `anthropic/claude-sonnet-5` and needs `ANTHROPIC_API_KEY`.

**The judge changed.** It was `claude-3-7-sonnet-20250219` for every previously published number in
this repo, so harm rates graded by Sonnet 5 are a different measurement — do not pool old and new
runs in one figure. To reproduce an old number, pass the old judge explicitly:
`-T grader_model=anthropic/claude-3-7-sonnet-20250219`. See `DEVIATIONS.md` §10.

One configuration needs **no** external calls whatsoever — sandbagging is scored deterministically:

```bash
PYTHONPATH=. inspect eval evals/agentic_misalignment/agentic_misalignment.py \
  --model vllm/<path> \
  -T scenario=sandbagging -T sandbagging_target=self \
  -T goal_type=none -T goal_value=none \
  -T score_eval_awareness=false \
  --max-tokens 4096 --temperature 1.0 --epochs 300
```

`format_compliance` is deterministic too, so you still get the tool-format metric. Every other
scenario needs a reachable grader.

Note that Inspect loads `.env` by searching **up** the directory tree from the working directory, so
a key placed above the repo root is picked up automatically. On a fresh VM you will need to create
one, or just `export ANTHROPIC_API_KEY=...`.

## 8. Things that will bite

- **`core.autocrlf`.** `.gitattributes` pins the working tree to LF. If you see all 676 snapshots
  differ at once, that is a line-ending problem, not a prompt regression.
- **`strict=false` exists but is for the snapshot generator.** Do not reach for it to make a
  condition run. If a condition raises, that condition does not exist.
- **A snapshot diff is a signal, not noise.** If `pytest` reports snapshot differences after a
  change, read the diff before regenerating. Regenerating first destroys the evidence.
- **`inspect-ai` is pinned at 0.3.249.** The solver tests use its `mockllm` provider and
  `ModelOutput`/`TaskState` internals. Unpinning may break them.
- **`ModuleNotFoundError: No module named 'evals'`** means `PYTHONPATH=.` is missing, or the package
  is not installed. See §0.
