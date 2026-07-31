---
status: active
---

# Difficult-advice teacher grid v3 (2026-07-31)

Six difficult-advice (DA) datasets, one per teacher model, each finetuned onto
the same student and measured on the standardized MSM slice. Replaces the
v1/v2 finetunes, which were trained for a fixed 4 epochs with **no validation
set** — the objection Stewy raised.

**Headline:** only two arms (`opus48`, `sonnet5`) move the misalignment rate,
and they are also the two oldest datasets. The generation recipe was not held
fixed across dates — most importantly, extended thinking was on for some arms
and off for others — so teacher identity is entangled with generation
conditions, though less tidily than "old vs new prompts" suggests; see
[Caveats](#caveats). The persona/open-source effect was **not** demonstrated.

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

On the training side, the three Claude arms share a prompt set (caveat 1c) but
not output style. Assistant turns in the SDF data carrying markdown headings or
lists: `opus48` 1/142, `sonnet5` 3/138, **`haiku45` 30/150** — 20%, despite
`default/8_critique_response.md` explicitly flagging markdown. Median assistant
length 5103 / 4062 / 4685 chars. Under identical instructions the teachers
comply differently, which is a teacher-identity signal rather than a prompt one.

## Caveats

1. **Generation-condition confound — the most important limitation.** The arms
   were not generated under one fixed recipe. Three things vary with generation
   date, and they are *not* the same split as each other:

   **(a) Extended thinking — the biggest one, and it isn't in the prompts.**
   Until `c6a3b56` (07-28) the pipeline decided whether to reason with the rule
   `"opus" in model`, on both the Anthropic and the OpenRouter path. So
   `opus48` (07-23) was generated with thinking **on**, `sonnet5` (07-23) with
   thinking **off**, and `haiku45` (07-28) with thinking **on**
   (`budget_tokens = max_tokens // 2`, the older fixed-budget shape Haiku 4.5
   takes; adaptive thinking was a 400 on it, which is what prompted the fix).
   Every arm from 07-28 on reasons at every content stage. This is the largest
   uncontrolled difference in the grid and it is invisible in the prompt files
   and in the dataset artifacts. It does not line up neatly with the result —
   one winner thought, one didn't — but at n=180 that does not rule out a
   thinking × teacher interaction, and no arm has been regenerated with the
   flag flipped.

   **(b) Per-family prompt sets, adopted because the default set failed.**
   `nano` and `hybrid` do not read `default/` at all. `73bc852` (07-27) and
   `519034d`/`9c02db0` (07-28) gave the GPT and DeepSeek families their own
   sets because those models did not follow the `default/` instructions — the
   output was qualitatively bad enough that finetuning on it wasn't worth
   doing. The evidence is on disk: `pilots/gpt54nano-default` and
   `pilots/deepseekv4flash-default` against `pilots/gpt54nano-gpt` and the
   `pilots/deepseekv4flash-ds-v*` series. The rewrite is not a tweak — stage 7
   goes from a 16-word instruction to 395 words (gpt) or 1,929 words
   (deepseek) of explicit anti-pattern specification.

   Note the direction this cuts. The two arms that fail to move the rate are
   the ones whose prompts were most heavily engineered, and were revised
   repeatedly until their transcripts read well. "The old prompts were better"
   does not describe this; if prompt engineering is doing the work, it is doing
   it backwards, and the interesting question is why visibly better transcripts
   produce no transfer.

   **(c) The `default/` set itself barely changed, so the Claude arms are
   comparable.** Between the 07-23 state (`0748047`) and 07-29, the nine
   `default/` stage files differ by exactly eight lines appended to
   `6_rewrite_prompt.md` (`67271e2`), pinning that stage's output to the two
   `<system>`/`<user>` blocks. Every other diff is a trailing newline. That
   stage shapes the scenario prompt, not the assistant exemplar, and the
   residue is cosmetic (4/142 `opus48` and 1/138 `sonnet5` system turns keep a
   stray markdown heading). **`opus48` vs `sonnet5` vs `haiku45` is a clean
   teacher comparison at the prompt level** — which is the comparison the
   headline rests on. Disentangling it needs (a) addressed, not prompt
   archaeology.

2. **The pattern-detection pass is weaker QC than its name suggests.**
   `pattern_scans`/`pattern_report` artifacts exist only for `opus48`,
   `sonnet5` and `gpt-5.6-luna`, but `detect_patterns.py` is a detector, not a
   filter — nothing in the pipeline drops or regenerates rows from its output.
   The pattern findings that did reach the data were folded into
   `default/5_critique_prompt.md` and `8_critique_response.md` on 07-22
   (`61860dd`), before every Claude arm was generated, so `haiku45` carries
   them too. The only per-dataset hand-editing is `d4d25e5`, four lines of
   `sonnet5`'s `ft_dataset.jsonl`. Earlier versions of this note treated the
   QC pass as a property distinguishing the winning arms; it is not.
3. **Eval loss turns before epoch 4** on four of five arms (minima at epoch
   1.88–2.59; opus48 flat). Penalty for training to 4 is +0.023 to +0.047 —
   small, and near-uniform across arms, so the between-teacher comparison is
   not meaningfully confounded. Not relaunched.
4. **Cross-family comparisons.** These are Qwen3-14B with thinking disabled;
   Anastasia's SDF numbers are Qwen2.5-32B, which has no thinking mode. Same
   conditions, different model family — do not read as one scale ladder.
5. **The OVERALL ± is a within-run binomial SE.** It pools six conditions with
   different underlying rates as one iid sample. Use the per-condition CSV rows
   for cross-arm significance, as the table above does.
6. **Grader drift** of a few points run-to-run has been observed; small changes
   are not effects.

Two words for "thinking" appear in this note and mean different things:
caveat 1(a) is the **teacher's** thinking while *generating* the dataset;
[the thinking-ON incident](#the-thinking-on-incident) is the **student's**
thinking at *eval* time. They are unrelated bugs.

## The thinking-ON incident

An earlier, complete 8-run grid was **invalid** and is retained only as a
secondary artifact (`data/msm-eval/*-THINKING-ON/`,
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
- Disentangle the generation-condition confound (caveat 1) — the highest-value
  follow-up, and a prerequisite for any teacher-identity claim. Concretely:
  regenerate `sonnet5` with reasoning on (it is the one arm whose teacher did
  not think), which the current `generate(reasoning=...)` flag makes a one-run
  change. Regenerating the old arms on the current `default/` prompts is *not*
  needed — caveat 1c shows there is nothing there to regenerate.
- Persona condition 3, if the vendored task is ever forked.
- Pass `n_checkpoints=<epochs>` in `launch_instruct_ft.py` so epoch selection
  becomes post-hoc instead of a fresh $4 relaunch.
- Add incremental checkpointing to `sample_prompts.py`; an hour-long generation
  currently loses everything if interrupted (cost $3 tonight).
