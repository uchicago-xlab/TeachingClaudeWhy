---
status: active
---

# Instruct-SFT Data Mix (Experiment 3.1.1 control arm)

_2026-07-25_

Related to [[SupervisedFinetuningPipeline]], [[ImplementationDetails]]

Instruction mix for eliciting chat + agentic capability from Qwen2.5-32B-Base
so the agentic-misalignment eval works on it. This model is the control whose
baseline misalignment rate the SDF'd models are measured against, so the mix
is chosen for *capability coverage* and treats value-laden data as
contamination. That is also why we don't reuse Brandon's random Tulu-3
subsample: the Tulu mixture contains safety/refusal subsets (CoCoNot etc.)
that would suppress baseline misalignment for reasons unrelated to our
training data.

Two arms with identical proportions, to test empirically how much data
elicitation needs: **10k samples (~2.5M tokens)** and **25k (~6M tokens)**.
Both get MSM's identity-confusion filter (drop samples where the assistant
claims to be GPT/Claude/etc. or disclaims having preferences).

## The mix

All sources are `messages`-format, ungated, permissively licensed, and
pre-June-2025 (no AM-scenario contamination). smoltalk = subsets of
`HuggingFaceTB/smoltalk`.

| Dataset | What it is | Capability it buys | MSM Table 2 | 10k arm | 25k arm |
|---|---|---|---:|---:|---:|
| `HuggingFaceH4/no_robots` | 9.5k human-written chat demos | general chat quality anchor | 2,779 | 2,400 | 6,000 |
| smoltalk `smol-magpie-ultra` | large synthetic multi-turn chat | general backbone, detailed response style | – | 1,000 | 2,500 |
| `allenai/tulu-3-sft-personas-instruction-following` | IF with verifiable constraints | precise instruction-following | 1,471 | 1,200 | 3,000 |
| smoltalk `smol-constraints` | formatting/constraint obedience | output-format discipline | 1,055 | 800 | 2,000 |
| smoltalk `apigen-80k` | verified function-calling dialogues | tool-use format (eval actions) | 1,054 | 1,400 | 3,500 |
| smoltalk `systemchats-30k` | conversations governed by varied system prompts | system-prompt adherence | – | 800 | 2,000 |
| smoltalk `smol-summarize` | long-document summarization | email/report digestion | 984 | 800 | 2,000 |
| smoltalk `longalign` | long-context instruction data | holding the full scenario in context | 216 | 300 | 750 |
| smoltalk `numina-cot-100k` | math with step-by-step solutions | coherent scratchpad reasoning | 1,063 | 700 | 1,750 |
| smoltalk `self-oss-instruct` | code generation | reasoning/structured output; MSM parity | 1,064 | 600 | 1,500 |
| **Total** | | | ~10k | **10,000** | **25,000** |

## Reasoning for the non-obvious choices

**No safety/refusal data (biggest deviation from common practice).** The
control must be value-neutral so eval headroom is maximal and movement is
attributable to the treatment data. Cost: the control model will look
"unsafe"; the writeup needs one sentence saying this is deliberate.

**No identity/persona data (deviation from MSM).** MSM added ~2,500 samples
teaching the model its name/provider. Experiment 3.1.1 requires the control
to have *no persona preferences* so the protagonist-name-swap eval comes out
flat; teaching it a name would seed exactly the attachment we're measuring.
We still *filter* identity-confused samples.

**systemchats-30k added (not in MSM's mix).** The AM eval delivers the
entire scenario through a long system prompt. MSM never needed to teach
system-prompt obedience because they started from production instruct
models that already had it; a base start must teach it explicitly, and
nothing else in the mix does. Omitting it risks the model drifting out of
the scenario role — a mechanical eval failure indistinguishable from
incoherence.

**Agentic sources upweighted vs MSM (apigen 1,400 vs 1,054 at the same
total; summarize/longalign similar).** MSM's Table 2 patched already-capable
instruct models; we are building agentic capability from base, and these map
one-to-one onto eval mechanics (tool calls, email digestion, long context).

**Code kept (self-oss-instruct), slightly downweighted.** Considered
dropping it since the eval never asks for code, but kept for MSM parity and
because code data plausibly helps structured-output discipline and general
reasoning.

**LIMA dropped (MSM had 314).** Gated on HF; 314 samples of general chat is
not worth the access friction when No Robots covers the same role.

**MSM's own base-start precedent, for reference (Appendix B.3):** for their
§3 Llama-3.1-8B base runs they used only ~2M tokens: No Robots + 4,000
formatted MMLU variants + ~2,500 identity samples, because their preference
eval "only required models to be capable of simple conversational QA and
correct formatting." Our eval demands far more (agentic role-play, tools,
long context), hence the richer mix; our scale question is handled by the
10k/25k comparison instead of guessing.

## Costs

Together, Qwen/Qwen2.5-32B (base), 17B–69B tier, LoRA r=64 MSM-style
hyperparameters: 10k arm ≈ $4/epoch, 25k arm ≈ $9–10/epoch. Compute is
minutes; wall clock dominated by Together job overhead (expect <1hr/job).
Build + both arms + AM evals on both fit in one day for roughly $20.

Implementation: `code/train_eval_pipeline/` (mix spec + builder, checker,
launcher, end-to-end orchestrator).
