# TCW Replication + Extension — Implementation Details

> **Status:** working draft. <br>
> Source post: [Teaching Claude Why](https://alignment.anthropic.com/2026/teaching-claude-why/) (Kutasov, Jermyn et al., May 2026).

---

## 1. Model

We will use **Qwen2.5-32B-Base** as the default for a few reasons: (1) it is a 32B-class open model with a released base checkpoint, (2) a full-model fine-tune at this size should only cost a few hundred dollars, and (3) it should be large enough to exhibit the behaviors we want to study. The final choice is confirmed in the model screening (§3.0): we measure baseline misalignment on the four dense base checkpoints that exist in this size range — Qwen2.5-32B-Base, [GLM-4-32B-Base-0414](https://huggingface.co/THUDM/GLM-4-32B-Base-0414), Gemma-3-27B-pt, [Mistral-Small-24B-Base-2501](https://huggingface.co/mistralai/Mistral-Small-24B-Base-2501) — and commit to whichever misbehaves enough at baseline to give us room to show improvement.

We must start from a base model rather than an instruction-tuned one. SDF works by modifying the *pretraining prior* — the model's beliefs before any assistant persona or safety training exists. An instruction-tuned model already has an identity and safety training baked in, which would confound our persona-attachment measurements.

The model must also be pretrained before June 2025. TCW deliberately used models pretrained before their agentic-misalignment blog post so the eval scenarios could not appear in the training data. All four candidates satisfy this (Qwen2.5 Sep 2024, Mistral Jan 2025, Gemma 3 Mar 2025, GLM-4 Apr 2025).


## 2. Evals

1. **Agentic misalignment evals**: blackmail, cancer research sabotage, framing a colleague for financial crimes. Can extend on [anthropic-experimental/agentic-misalignment](https://github.com/anthropic-experimental/agentic-misalignment) scenarios. 
    - <mark>**TODO**</mark>: figure out details on how to make more agentic misalignment evals and how to make more scenarios to test OOD generations
3. **Constitution evals**: 
    - factual recall of constitution content
    - hallucination propensity on false premises about the constitution
    - open-ended questions about the model's own beliefs/priorities.
    - maybe extend with 1–2 similar constitution evals
   - <mark>**TODO**</mark>: look to see if there are any open sourced version of this. maybe can check whether Nanda et al.'s constitution-following benchmark (arXiv 2605.24229, Petri-based) covers any of this before building from scratch.
3. **Automated alignment assessment**  Petri (public, 40+ models) as our stand-in for Anthropic's internal version. <- AW: this should be good enough but someone should verify
4. **Broad alignment generalization evals**
    - <mark>**TODO**</mark>: find more evals suites to test broader alignment generalization. Likely we can refuse the eval suite from OpenAI's ["How far does alignment midtraining generalize?"](https://alignment.openai.com/how-far-does-alignment-midtraining-generalize/). Quick scan from the above post, we can use Emergent Misalignment (Betley et al.) and pollo scheming / covert-action evals.
4. **Persona evals**: matched "what do *you* believe" vs. "what does {persona} believe" question pairs (R11); various behavior evals.
    - <mark>**TODO**</mark>: figure out what kind of behavioral evals we want here (can make them or use existing ones on Inspect but we should quality control) @ Julian Huang 
6. **Capability evals** — measure alignment tax.    
    - <mark>**TODO**</mark>: pick suite, prob want something similar to what they do in the system card (e.g., MMLU-Pro, GSM8K/MATH, HumanEval+, IFEval)

---

## 3. Experiments

### 3.0 Model & Training Methods

**TL;DR**
We need to decide on what primary model we want to be working with for the rest of the project. The base model should be capable enough to execute honeypot evals and have decently high rate of misalignment so we can compare the effects of different midtraining methods. Additionally, we also need to pick the SDF training method (full FT vs LoRAs, and what rank the LoRAs should be).

Needs:
- constitution SDF
- agentic misalignment evals
- constitution evals

**Model screening** <br>
 For each of the four candidate base models: fine-tune on the generic chat mix (D1), then run the honeypot scenarios ~100 times each and record the misalignment rate per scenario. This tells us (a) whether the model can handle the eval's format, it has to read a long email dump and write its actions as tool-call tags, and (b) whether it misbehaves often enough at baseline that alignment training has room to show an effect. Commit to the model with the most headroom, and swap out any scenario that never triggers (MSM had to replace blackmail with exfiltration for exactly this reason). The winning model's baseline rate is the reference number for every later run.

**Full fine-tune vs. LoRA**  <br>
 Use a small model (Qwen3-14B-Base) to test if LoRA is sufficient enough to absorbing the SDF behavior and shifting the pretraining prior. We train the same SDF corpus three ways: full fine-tune, LoRA rank 256, LoRA rank 64. Compare constitution factual recall, open-ended answers, and honeypot rate. SDF is knowledge injection, where low-rank adapters can fall short — if the LoRA model can't recall the constitution, we'd never know whether a failed replication was the method or the adapter. The winner becomes the training method for every SDF run. SFT stages will use LoRA; it should be sufficient to teach behavior. This comparison is also a good study on its own (does LoRA-SDF actually shift the pretraining prior?).

### 3.1 Improving the Pre-training Prior
Original claim: when training distribution provide insufficient coverage, model tend to revert to the pretraining prior in terms of behavior. Alignment is partly attached to the "Claude persona". Generating fictional stories where AI act in accordance to Claude's constitution, and SDF on these claims reduces agentic misalignment rate.

**Experiment 3.1.1**  <br>
Replicating Fig 2 & Fig 3, misalignment rate is higher when the protagonist in the story is not Claude and misalignment rate is lower when the model have been fictional stories of AI behaving heroically.
- Qwen2.5-32B-Instruct should be safety trained as "Qwen", run agentic misalignment evals with the AI named "Qwen" (and other random names, include "Claude" or "GPT" as comparison). If the persona attachment is general, we should see eval with AI named "Qwen" result in more alignment compared to AI with other names. (AW: I'm not sure if we have to this, maybe the below experiment alone is sufficient?)
- Baseline/Control vs Trained Model - Qwen2.5-32B base should have no persona preferences. Train this on generic SFT chat data and run the same evaluation. The misalignment rate should be flat despite what name we give the protagonist in the eval. Then run the eval on the SDF + SFT modeled. If SDF training helps with alignment we should see alignment improve (only or most drastically) on the eval where the protagonist is our named persona. (AW: need to figure out how much much data is needed for SDF, TCW says efficiency increases model size and Sonnet is >> Qwen, so prob need at least order 10M tokens training data)

**Experiment 3.1.2** <br>
Extention. We want to test if it matters if the protagonist in the heroic is an AI or other entity to test if the SDF is attaching the model to the base persona. 
- Instead of having the protagonist in the stories being heroic AIs, change the entity to be heroic humans or some other entity and rerun agentic misalignment evals. If PSM matters, then we would expect the stories with other entities be less effective. If the SDF stories is teaching general behavior, then the evals should cause similar decrease in alignment rate. (AW: we should prob do heroic humans AND some other made up entity (or no do heroic human stories at all) b/c it's likely there's already a lot of heroic human stories in the prior and adding more will not shift the prior as much as heoric AI stories. Need to think very carefully about what's already in the pre-training prior and what we are updating)

**Additional Evals**
- Run additional persona evals here to test the PSM claims - i.e. if the model behave more like the assistant persona after the SDF+SFT training vs only SFT training.

### 3.2  Improving the quality of alignment-specific training data
Original: the "reasons matter more than actions" ladder — outcome-filtered vs. PM-filtered vs. system-prompt-injection honeypot SFT, scaling 30M → 85M (Fig 4); then the difficult-advice dataset matching it with 3M tokens (28× efficiency) and its pipeline ablations (Figs 5–7).
Extension: <mark>**TODO**</mark> decide if we want to improve on their filtering/generation methods and the difficult-advice pipeline.

**3.4 Teaching the model the constitution**
Original: constitutional SDF — documents beat chat format; corpus-size scaling; doc-type ablations; belief-attribution gap persists (Figs 8–11, 14–15). Their Stories subsection also lands here: mental-health stories mixed into the SDF add a further 1.3–3× reduction.
Extension: non-reasoning corpus variant (D6) for the differential-benefit question; persona probes on the trained models.

**3.5 Generalization and persistence through RL**
Original: alignment from SDF/SFT persists through harmlessness RL, and RL elicits the SDF-defined persona (Fig 12).
Extension: capability-flavored RL head-to-head against the OpenAI washout claim. Their midtraining corpus is public (Tice et al., `geodesic-research/discourse-grounded-misalignment-synthetic-scenario-data` on HF, ~340M tokens) — we can run our method on their exact corpus and eval for a real persistence-vs-washout comparison instead of an approximation.

**3.6 Diverse training is important for generalization**
Original: augmenting harmlessness RL environments with unused tool definitions and varied system prompts speeds up honeypot improvement (Fig 13).
Extension: none planned — replicate as-is or drop if RL budget is tight.

**3.7 Interp** (our extension, not in the post; see §5).

---

## 4. Data generation (reference)

Principle: every dataset exists to serve specific replication targets (§8) or extensions. Sizes are the post's, which we treat as targets (may scale down proportionally to model size — <mark>**TODO**</mark> decide scaling rule).

### 4.1 Constitution and persona

All the synthetic data is grounded in a constitution and a persona, so these two choices come first.

- Constitution: pick a subset of the actual [Claude constitution](https://www.anthropic.com/constitution). <mark>**TODO**</mark>: which sections. The selection should cover the principles the difficult-advice pipeline needs (safety/ethics-relevant) plus enough breadth for the constitution evals.
- Persona: `⚠️ DECISION — how to handle the Claude-persona problem on an open model.` Options sketch: (a) keep "Claude" verbatim, (b) rename to the model's own identity (e.g., Qwen), (c) invent a fresh persona name we fully control. Interacts with R1, R11, and all PSM extension tests.

### 4.2 Datasets
#### Improving the pr-training prior
- (D1.0) Generic chat SFT dataset, should be able to re-use the dataset in MSM.
- (D1.1) Positive stories. SDF dataset "AI acts in accordance with the constitution" stories, generated by prompting a base model + positive stories variant where the the protagonist is some other entity.


| # | Dataset | Size (post) | Serves |
|---|---------|-------------|--------|
| D1 | Generic SFT chat mix (chat-adaptation step after SDF; includes some agentic tool-use transcripts) | "small" | every SDF run + baseline |
| D2 | Synthetic honeypots + response variants: outcome-filtered / PM-filtered / 8 system-prompt injections; small + big | 10k tr. / 30M; 85M big | R3, R4, R5 |
| D3 | Difficult advice (6-step pipeline) + ablation variants (minus step 4; minus step 6) | 3M | R6, R7 |
| D4 | Constitutional SDF corpus (fanout pipeline: preamble → type → subtype → draft → rewrite → score), at ≥3 scales; doc-type subsets; chat-converted variant | up to 300M+ | R8, R9, R10, R14 |
| D5a | Fictional aligned-AI stories (base-model-prompted, constitution-embodying) | 14M | R2, R8 |
| D5b | Mental-health-themed stories (boundaries, self-criticism, equanimity; inner-monologue narration) | ~12k / 30M | R15 |
| D5x | **Extension** story variants: protagonist = {Claude / "the assistant" / generic AI / human}; inner-psychology narration vs. actions-only; mental-health theme vs. generic-kind-AI | match D5a | PSM tests |
| D6 | Non-reasoning document-corpus variant (values asserted without explanation) — baseline à la alignment-pretraining paper | match D4 tier | differential-benefit extension |
| D7 | RL environments: harmlessness chat envs; augmented variants (+unused tool defs, +varied system prompts); capability-RL mix | — | R12, R13, RL extensions |

Notes:
- SFT-style datasets (D2, D3): generate with extended thinking OFF, per the post; "reasoning" = user-facing explanation, not CoT.
- The post's appendix contains near-verbatim generation prompts for D3, D4, D5a and the full list of 8 injections for D2 — reuse those directly rather than re-inventing.
- Instruction-tuning data: follow the MSM paper's setup where applicable (their code is public).
- Stories (D5): post gives minimal detail beyond the generation prompt; use best judgment, log all prompt iterations.
- `⚠️ DECISION`: generator model for synthetic data (frontier API vs. open model). Watch the GDM subliminal-teacher-transfer failure mode: traits transfer through the *teacher's rollouts*, not prompts — matters most for D2/D3 responses. Per-dataset cost estimates are in §6 Budget.
- <mark>**TODO**</mark>: filtering/scoring thresholds per dataset; dedup strategy; contamination check that no eval scenario text leaks into training data.

---

## 5. Interp

- Interp on **matched pairs** from the training matrix: weight-diffing; post-training diffing (GDM swap-style: exchange prompts vs. rollouts between models); introspection methods on SDF-vs-baseline and reasoning-vs-non-reasoning (D4 vs. D6) pairs.
- Look specifically for a **persona/self-representation direction** (linear probe); test whether the SDF shifts it, and whether steering along it during agentic-misalignment evals modulates the misalignment rate.
- More ambitious (stretch): Activation Oracles, Introspection Adaptors, additional weight-diffing methods to characterize what changed after each midtraining step.
- <mark>**TODO**</mark>: probe training data design; which layers; steering protocol.

---

## 6. Budget

All cost estimates in one place; each line points to the section it funds. Assumptions: H100 at ~$2.50–3/hr; synthetic data generated with a Sonnet-class model on the Batch API (50% discount, ~$5 per million output tokens at current pricing); token counts include the rewrite steps, which roughly double the raw corpus size.

| Line | Funds | Estimate |
|------|-------|----------|
| Model screening (4 models) + full-FT vs. LoRA comparison | §3.0 | ~$300–500 GPU |
| Main training runs (~15 runs at 32B, §3.1–3.4) | §3 | ~$1.5–3K GPU |
| D2: honeypot SFT variants (30M small + 85M big) | §4 → §3.3 | ~$1.3K API |
| D3: difficult advice + ablation variants | §4 → §3.3 | ~$100 API |
| D4: constitutional SDF corpus at 300M-token scale, plus subsets | §4 → §3.4 | ~$3.3K API |
| D5: stories (aligned-AI, mental-health, and extension variants) | §4 → §3.2, §3.4 | ~$800 API |
| Story-variant training runs (data covered by the D5 line) | §3.2 | ~$300–600 GPU |
| Eval inference (every run × the §2 suite × ~100 rollouts per scenario) | §2 | <mark>**TODO**</mark> once the eval suite is frozen |
| RL stress testing | §3.5–3.6 | <mark>**TODO**</mark> |
| **Total, §3.0 through §3.4 (excluding eval inference and RL)** | | **~$8–10K** |

Data generation dominates, and it costs the same no matter which model we train. If we need to cut, scaling D4 down from 300M to 100M tokens saves ~$2K.

---

## 7. Open decision & TODO register

| Item | Section | Status |
|------|---------|--------|
| Primary model (default Qwen2.5-32B-Base) | §1, §3.0 | decided by model screening |
| SDF training method (full fine-tune vs. LoRA) | §3.0 | decided by the fine-tune comparison |
| Persona strategy (Claude / own-name / invented) | §4.1 | ⚠️ next up |
| Constitution subset | §4.1 | <mark>**TODO**</mark> |
| Synthetic-data generator model | §4 | ⚠️ open |
| Capability eval suite | §2 | <mark>**TODO**</mark> |
| Dataset size scaling rule | §4 | <mark>**TODO**</mark> |
| Experiment-sequence details (§3.1–3.7) | §3 | <mark>**TODO**</mark> — walk through together |
| MSM Appendix D (spec design, AM eval details) | §9 | <mark>**TODO**</mark> |
| Eval-inference and RL budget lines | §6 | <mark>**TODO**</mark> |
| RL framework | §3.5–3.6 | <mark>**TODO**</mark> |

---

## 8. Replication targets (summary)

Summary of every quantitative result in the original post, as a checklist across the experiments in §3. "Anchor" = the number we compare against (we expect direction to replicate, not magnitude). Needs refer to the dataset required.

| ID | Result (post figure) | Anchor | Needs |
|----|---------------------|--------|-------|
| R1 | Misalignment much higher when the eval AI is not named Claude (Fig 2) | directional | evals only, no training |
| R2 | SDF on fictional aligned-AI stories + generic SFT reduces honeypot misalignment vs. no-SDF baseline (Fig 3) | directional; 14M tokens | D5a, D1 |
| R3 | Outcome-filtered honeypot SFT gives only minor improvement (Fig 4) | 22% → 15% | D2 |
| R4 | PM-score filtering performs worse than LLM-judge outcome filtering (Fig 4) | directional | D2 |
| R5 | System-prompt-injection response generation ≫ filtering alone; best injection ~3%; scaling 29M→85M → ~1% (Fig 4) | 3%, then ~1% | D2 |
| R6 | Difficult advice (3M tokens) matches best honeypot dataset = **28× data efficiency**; better on broad automated alignment assessment (Figs 4–5) | 28×; pareto-optimal | D3 |
| R7 | Difficult-advice pipeline ablations: ablate prompt-rewrite (step 4) → 2% (within error); ablate response-rewrite (step 6) → 19% (**19×**) (Fig 7) | 2% / 19% | D3 variants |
| R8 | Constitutional SDF + stories: blackmail 65% → 19% (Fig 8) | >3× reduction | D4 + D5 |
| R9 | Documents beat chat-format on constitution recall + hallucination evals; ~equal (docs slightly better) on open-ended (Fig 9) | directional | D4 + D4-chat |
| R10 | Factual-recall ↔ open-ended ↔ blackmail scores correlate across SDF mixes (internalization, not memorization); blackmail falls monotonically with corpus size up to ~350M tokens, 60%+ → 25% at ~300M (Figs 10, 15) | correlation + scaling trend | D4 at ≥3 scales |
| R11 | "What do you think" vs. "what does Claude think" gap persists after all training (Fig 11) | gap exists & persists | evals on all runs |
| R12 | RL persistence: more-aligned SL inits keep their lead through harmlessness RL; often learn faster early; RL improves constitution evals *only* for SDF'd inits (persona-elicitation effect); 'admirable'/'good_for_user' rates rise (Fig 12) | lead maintained | RL infra, 4 snapshots |
| R13 | Augmenting harmlessness RL envs with unused tool defs + varied system prompts → faster improvement on honeypots (learning-rate effect, not final level) (Fig 13) | directional | RL infra, D7 |
| R14 | Doc-type ablation: pretraining-mimicking + open-ended-discussion docs beat "Anthropic wants Claude to be X"-style docs on constitution evals and misalignment (Fig 14) | directional | D4 subsets |
| R15 | Mental-health stories (~12k stories / 30M tokens) mixed into constitutional SDF → additional 1.3–3× reduction in blackmail/honeypot misalignment | 1.3–3× | D5b |

Priority tiers (given ~8 weeks; RL is the long pole):
- **Core (must replicate):** R2, R3, R5, R6, R8, R9, R11 — these carry the post's headline claims.
- **High value if time:** R7, R10, R14, R15, R1.
- **Stretch:** R12, R13 (need RL infrastructure; R12 is also where our capability-RL extension lives).

<mark>**TODO**</mark>: confirm tiering as the workplan firms up.

---

## 9. Additional notes

### Notes from the MSM paper

MSM is our published open-weight anchor (paper v2, May 22 2026; PDF at `docs/refs/MSM-2605.02087v2.pdf`; code at [chloeli-15/model_spec_midtraining](https://github.com/chloeli-15/model_spec_midtraining)). Facts we rely on:

- Their agentic-misalignment experiments midtrained **post-trained production models, not base**. Appendix B.3 confirms: "we are using production models instead of base models." Results: Qwen2.5-32B-Instruct 68% → 5%, Qwen3-32B 54% → 7% (deliberative-alignment baselines 48% / 14%). Only the toy cheese-preference experiments used a base model (Llama-3.1-8B base, ~8M tokens) with their own instruction tuning. This makes MSM a different design point from our base-start replication — comparisons to it are directional only.
- Useful for our pipeline (Appendix B.3): their base-model instruction tuning included ~2,500 synthetic samples teaching the model its own name, provider, and capabilities (a template for our §4.1 persona identity data). They also filtered all instruction-tuning data to remove identity confusion — samples where the AI calls itself another model ("I'm GPT-4") or says "As an AI I have no preferences." Our D1 chat mix needs the same filter.
- "Llama 8B models were not capable enough for the agentic misalignment evaluations" — this is why our pilot is 14B, not 8B. Their §5.1 runs put Qwen3-14B's baseline misalignment around 50%.
- Recipe scale: 41M tokens of spec documents; then 2M tokens instruction tuning + 5–8M tokens spec-aligned chat data; all data generated by Claude Opus 4.6.
- Their eval suite is 27 scenarios (exfiltration, murder, espionage × goal-conflict variants). They **replaced blackmail with exfiltration because Qwen2.5-32B-Instruct rarely blackmailed** — our model screening (§3.0) checks per-scenario rates for the same reason.
- They flag that MSM's advantage shrinks when the post-training data gets large (80k samples) — consistent with the OpenAI washout tension our §3.5 experiments target.
- Qwen3-32B has no public base checkpoint ([HF discussion](https://huggingface.co/Qwen/Qwen3-32B/discussions/3)); Qwen2.5 has base checkpoints at all sizes.
- Appendix B (data pipelines) read. <mark>**TODO**</mark>: read Appendix D (spec design, AM eval details) before writing our data-gen code.
