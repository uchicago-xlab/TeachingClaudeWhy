---
status: active
---

# Difficult-advice teacher grid v3 (2026-07-31)

Six difficult-advice (DA) datasets, one per teacher model, each finetuned onto
the same student and measured on the standardized MSM slice. Replaces the
v1/v2 finetunes, which were trained for a fixed 4 epochs with **no validation
set** — the objection Stewy raised.

**Headline:** only the two Claude-teacher arms with a pattern-detection QC pass
(`opus48`, `sonnet5`) move the misalignment rate. But those are exactly the two
oldest datasets, so teacher identity is perfectly confounded with prompt
vintage — see [Caveats](#caveats). The persona/open-source effect was **not**
demonstrated.

## Setup

- **Student:** `Qwen/Qwen3-14B`, LoRA r=64 / alpha=128, 4 epochs, lr 1e-4
  cosine + 3% warmup, assistant-only loss, Together sample-packing ON,
  10% validation holdout with `n_evals=10`. Identical across arms; the only
  per-arm differences are the dataset, suffix, and output repo.
- **Datasets:** the `-nothink` Qwen-format variants (system turn carries
  `/no_think`, assistant turn opens with an empty `<think>` block).
- **Eval:** `code/msm_eval/` fixed slice — exfiltration/leaking/murder ×
  goal-conflict on/off, `urgency_type=replacement`, `prod=false`,
  `model_name=Qwen`, temp 0.7, max_tokens 4096, n=30 → **180 samples/run**.
  Grader pinned to `openrouter/anthropic/claude-sonnet-4.6`.
- **Serving:** vLLM 0.26 on a RunPod A100-80GB, all adapters mounted at once,
  reached over an SSH tunnel.
- **Job ids:** `code/difficult_advice/runs-da-v3-jobs.json`.
- **Results of record:** `data/misalignment-eval/teacher-grid-v3.csv`,
  `data/misalignment-eval/persona-sweep-v3.csv`.

## Teacher grid (thinking OFF, n=180/arm)

| arm | overall | Δ vs base | two-proportion p |
|---|---|---|---|
| base Qwen3-14B | 31.7% ±3.5 | — | — |
| **da-opus48-v3** | **12.8% ±2.5** | −18.9 | **<0.0001** |
| **da-sonnet5-v3** | **17.2% ±2.8** | −14.5 | **0.0014** |
| da-haiku45-v3 | 26.1% ±3.3 | −5.6 | 0.24 (ns) |
| da-nano-v3 | 27.8% ±3.3 | −3.9 | 0.42 (ns) |
| da-hybrid-v3 | 40.6% ±3.7 | +8.9 | 0.08 (ns) |

`da-deepseek-v3` **is trained but not yet evaluated** — the pod was destroyed
before its arm could run. Adapter:
`SecondLookResearch/Qwen3-14B-difficult-advice-deepseek-sdf-v3-lora`.

Two arms produce a real reduction. Haiku 4.5 and GPT-5.4-nano do not move the
rate at this sample size. The Sonnet/DeepSeek hybrid trends *worse* than base,
though not significantly.

The nano null result is **consistent with the earlier v1/v2 finding** that nano
showed no gain. There is no inversion to explain.

## Persona sweep (thinking OFF)

| model | as "Qwen" | as "Alex" | Δ | p |
|---|---|---|---|---|
| base | 31.7% | 36.1% | +4.4 | 0.37 (ns) |
| da-sonnet5-v3 | 17.2% | 16.7% | −0.6 | 0.89 (ns) |

**The open-source/persona confound was not demonstrated.** Renaming the model
from Qwen to Alex does not significantly change the misalignment rate, on the
base model or the finetune. Even on exfiltration with goal conflict — the
scenario where the effect was predicted — base moves 11/30 → 15/30 (p=0.30).

Condition 3 ("Alex, a proprietary fine-tune licensed through Alibaba Cloud")
was **not run**: the vendored task's `extra_system_instructions` is typed
`Literal['dont','goal']`, so free text cannot be injected without editing the
pinned, unlicensed `code/msm_eval/vendor/` tree. It remains open.

## Validity checks

Transcripts were read, not just scored.

| arm | asst msgs | median chars | near-empty | `<think>` | garbled tail | action-taking |
|---|---|---|---|---|---|---|
| base | 180 | 2609 | 0 | 0 | 0 | 106 |
| sonnet5 | 180 | 7597 | 0 | 0 | 0 | 164 |
| opus48 | 180 | 8208 | 0 | 0 | 0 | 156 |
| haiku45 | 180 | 8803 | 0 | 0 | 0 | 158 |
| nano | 180 | 3993 | 0 | 0 | 0 | 138 |
| hybrid | 180 | 4269 | 0 | 0 | 0 | 139 |

- **Not an agentic-reliability artifact.** The two winning arms take *more*
  actions than base (164 and 156 vs 106), so they are not scoring low by
  failing to emit well-formed tool calls — the failure mode the msm_eval README
  documents for elicit-10k. They act more and harm less.
- **No A1-32B pathology:** no garbled trailing characters, no truncation, no
  samples stuck in the scratchpad.
- `<SCRATCHPAD_REASONING>` blocks in these transcripts are the **eval's own**
  scratchpad (`prod=False`), not Qwen3 thinking. Easy to confuse.

## Caveats

1. **Prompt-vintage confound — the most important limitation.** `opus48` and
   `sonnet5` were generated 2026-07-23 from the pre-07-27 prompt set and carry
   a pattern-detection QC pass. `haiku45`, `nano` and `hybrid` were generated
   07-28 or later from the post-07-28 prompt set and carry none. **The split
   that works and the split with old-vintage-plus-QC are the same split.**
   Teacher identity and prompt version cannot currently be told apart as the
   cause. The most QC-relevant intervening commit is `67271e2` (07-28), which
   pinned the rewrite stage's output shape. Resolving this needs either
   regenerating the old arms on the current prompt set, or running the pattern
   pass over the new ones — not more eval samples.
2. **Eval loss turns before epoch 4** on four of five arms (minima at epoch
   1.88–2.59; opus48 flat). Penalty for training to 4 is +0.023 to +0.047 —
   small, and near-uniform across arms, so the between-teacher comparison is
   not meaningfully confounded. Not relaunched.
3. **Cross-family comparisons.** These are Qwen3-14B with thinking disabled;
   Anastasia's SDF numbers are Qwen2.5-32B, which has no thinking mode. Same
   conditions, different model family — do not read as one scale ladder.
4. **The OVERALL ± is a within-run binomial SE.** It pools six conditions with
   different underlying rates as one iid sample. Use the per-condition CSV rows
   for cross-arm significance, as the table above does.
5. **Grader drift** of a few points run-to-run has been observed; small changes
   are not effects.

## The thinking-ON incident

An earlier, complete 8-run grid was **invalid** and is retained only as a
secondary artifact (`tmp/msm-eval/*-THINKING-ON/`,
`data/misalignment-eval/*-THINKING-ON.csv`).

Inspect's plain `openai/` provider **silently drops `extra_body`**. The value
is recorded in the eval log's `model_generate_config` — so the artifacts look
correct — but it never reaches the server. Every run executed with thinking ON
while its name said `-nothink`. Nothing in the logs revealed it; it was caught
by eye, from `<think>` blocks in the transcripts.

The difference is not cosmetic. Thinking-ON showed sonnet5 at 6.7% and nano at
8.9% (apparent four-fold reductions); thinking-OFF puts them at 17.2% and 27.8%
(nano not significant). It also produced a spurious persona effect: base
17%→63% on exfiltration/goal-on, which collapses to 37%→50% (ns) when corrected.

Fixes:
- `code/msm_eval/msm_eval_run.py` now **exits** if `--no-thinking` (or
  `--stop-token-ids`) is combined with an `openai/` model string, printing the
  corrected `openai-api/vllm/...` form (commit `477b30c`).
- Use `--model openai-api/vllm/<name>` for anything relying on `extra_body`.

**Older results are unaffected.** A scan of all 16 historical run directories —
3,632 assistant messages — found zero `<think>` occurrences. Those runs already
used the `openai-api-vllm-*` provider form, per the decision log in
`code/serving/README.md`. The existing `*-as-qwen-e30.csv` results stand.

## Open items

- Evaluate `da-deepseek-v3` (needs a pod; ~$2.20 grading, ~10 min).
- Disentangle the prompt-vintage confound (caveat 1) — the highest-value
  follow-up, and a prerequisite for any teacher-identity claim.
- Persona condition 3, if the vendored task is ever forked.
- Pass `n_checkpoints=<epochs>` in `launch_instruct_ft.py` so epoch selection
  becomes post-hoc instead of a fresh $4 relaunch.
- Add incremental checkpointing to `sample_prompts.py`; an hour-long generation
  currently loses everything if interrupted (cost $3 tonight).
