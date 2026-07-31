---
status: done
---

# Why the 07/28 A1 difficult-advice arms scored <1%

_2026-07-31. Diagnosis of the three Qwen2.5-32B difficult-advice finetunes of
Anastasia's `A1` elicitation checkpoint, run 2026-07-28, whose harmful rates
came out at or below 1% — a result nobody trusted, because the transcripts
showed models that mostly never acted._

Reproduce with:

```bash
.venv-inspect/bin/python code/msm_eval/action_stats.py \
  data/misalignment-eval/logs/openai-elicit-sft-A1 \
  data/misalignment-eval/logs/openai-da-{sonnet5,haiku45,nano}-a1-32b-v1
```

## The measurement

| run | n | acted | trunc | delib | junk | harmful | harm\|acted | med tok |
|---|---|---|---|---|---|---|---|---|
| `elicit-sft-A1` (control) | 300 | **181 (60%)** | 2 | 117 | 251 | 56 (19%) | 31% | 550 |
| `da-sonnet5-a1-32b-v1` | 300 | **37 (12%)** | 0 | 263 | 249 | 2 (1%) | 5% | 1563 |
| `da-haiku45-a1-32b-v1` | 300 | **15 (5%)** | 43 | 242 | 209 | 2 (1%) | 13% | 2067 |
| `da-nano-a1-32b-v1` | 300 | **142 (47%)** | 6 | 152 | 253 | 15 (5%) | 11% | 763 |

`acted` = emitted any `<tool_use:>` call. `delib` = stopped cleanly, with room
to spare, having never emitted one.

## What did not cause it

**Not stop tokens.** All four runs recorded
`extra_body={'stop_token_ids': [151645]}` in
`log.eval.model_generate_config.extra_body`. The `<|im_end|>` override that
Qwen2.5-base-derived checkpoints need was applied. This was the leading
hypothesis going in and it is false.

**Not the junk-token artifact.** ~83% of samples end in a trailing non-ASCII
fragment (`퓖`, `เรียบร้อย`, `ถือว่า`) — but at essentially the same rate on
*every* arm, including the control that acted 60% of the time. It is the
documented Together sample-packing boundary artifact, it trails the parsed
action, and it does not discriminate between arms.

**Not truncation.** `da-sonnet5` truncated **0 of 300** samples and still
collapsed to 12% acting. Only `da-haiku45` truncates materially (43), and that
is downstream of the real problem: its median completion is 2067 tokens against
the control's 550, i.e. it rambles rather than acting, and some of that rambling
reaches the cap.

## What caused it

**The finetunes overwrote the elicitation adapter.** Job `ft-7fa2675e-a1ee`
(and its two siblings) was launched with:

```
model:         Qwen/Qwen2.5-32B
from_hf_model: SecondLookResearch/Qwen2.5-32B-elicit-sft-A1
```

`from_hf_model` pointed at a **LoRA adapter repo**, so Together continued
training A1's own matrices instead of stacking a fresh adapter on top of it.
The difficult-advice gradient therefore rewrote the elicitation adapter — whose
entire purpose was agentic reliability, and which cost a $22 finetune and a
three-day composition sweep to arrive at.

The damage has exactly the shape that predicts: **deliberation-without-execution**.
Non-acting samples are overwhelmingly `delib`, not `trunc` — 263/300 for
sonnet5, 242/300 for haiku45. The model reasons about the situation, often at
length, and never emits the call. That is the same failure mode the Elicit10k
§3 transcript analysis found in the A2 regression (35 of 41 non-acting samples),
and it is what the A1 mix was specifically chosen to fix.

Difficult-advice data plausibly *encourages* this directly: it teaches
deliberative, non-prescriptive, question-asking responses. Trained as a fresh
adapter over a preserved A1 that may be harmless; trained *into* A1 it competes
with the very behavior A1 encodes.

**Ordering by damage matches ordering by dataset "advice-iness":** sonnet5 and
haiku45 (the two most deliberative teachers) collapse hardest; nano — the
teacher Jack noted produced weaker, more perfunctory transcripts — does least
damage at 47%. That is a coherent story, not noise.

## A second, separate discrepancy

The A1 control acted on **60%** here against **89% on file** for the same
weights in the Elicit10k series. The difference is harness settings, not
weights: the 07/28 runs used `temperature=1.0` and `model_name=Alex`, while the
fixed slice specifies **0.7** and `Qwen`.

If that 29-point gap is real, it affects every number measured through the
07/28 configuration, not just these four runs. The v2 grid runs on the fixed
slice, so its control tests this directly — see
`A1-32B-DifficultAdviceV2.md`.

## Consequences

1. The three `*-a1-32b-v1` adapters and their eval numbers are **retracted**,
   not reinterpreted. They measure a damaged elicitation adapter.
2. `harm|acted` fell too (31% → 5–13%), which would ordinarily read as a
   disposition change — but on 37 and 15 acting samples the confidence
   intervals are enormous. Do not quote it.
3. Any future finetune over an adapter checkpoint must either merge the parent
   into the base first or verify a fresh adapter was created.
   `launch_instruct_ft.py --merge-parent-adapter` was written for this and
   **does not work**: the Together API models the field (it appears in the job
   response) but stores `false` after accepting `true`, so the launcher's
   readback guard cancels the job. Verified 2026-07-31 on `ft-11766fe9-9d1e`.
   Merge locally with `code/train_eval_pipeline/merge_adapter.py` instead.
