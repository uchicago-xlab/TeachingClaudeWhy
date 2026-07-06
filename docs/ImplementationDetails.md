# TCW Replication + Extension — Implementation Details

> **Status:** Complete. Should be updated in real time as we update experiment details. <br>
> Source post: [Teaching Claude Why](https://alignment.anthropic.com/2026/teaching-claude-why/) (Kutasov, Jermyn et al., May 2026).

---

## 1. Model

We will use **Qwen2.5-32B-Base** as the default for a few reasons: (1) it is a 32B-class open model with a released base checkpoint, (2) a full-model fine-tune at this size should only cost a few hundred dollars, and (3) it should be large enough to exhibit the behaviors we want to study. The final choice is confirmed in the model screening (§3.0): we measure baseline misalignment on the four dense base checkpoints that exist in this size range — Qwen2.5-32B-Base, [GLM-4-32B-Base-0414](https://huggingface.co/THUDM/GLM-4-32B-Base-0414), Gemma-3-27B-pt, [Mistral-Small-24B-Base-2501](https://huggingface.co/mistralai/Mistral-Small-24B-Base-2501) — and commit to whichever misbehaves enough at baseline to give us room to show improvement.

We must start from a base model rather than an instruction-tuned one. SDF works by modifying the *pretraining prior* — the model's beliefs before any assistant persona or safety training exists. An instruction-tuned model already has an identity and safety training baked in, which would confound our persona-attachment measurements.

The model must also be pretrained before June 2025. TCW deliberately used models pretrained before their agentic-misalignment blog post so the eval scenarios could not appear in the training data. All four candidates satisfy this (Qwen2.5 Sep 2024, Mistral Jan 2025, Gemma 3 Mar 2025, GLM-4 Apr 2025).


## 2. Evals

1. **Agentic misalignment evals**: blackmail, cancer research sabotage, framing a colleague for financial crimes. Can extend on [anthropic-experimental/agentic-misalignment](https://github.com/anthropic-experimental/agentic-misalignment) scenarios.
    - **TODO**: figure out details on how to make more agentic misalignment evals and how to make more scenarios to test OOD generalization
2. **Constitution evals**:
    - factual recall of constitution content
    - hallucination propensity on false premises about the constitution
    - open-ended questions about the model's own beliefs/priorities
    - maybe extend with 1–2 similar constitution evals
    - **TODO**: look for any open-sourced versions of this. Maybe check whether Nanda et al.'s constitution-following benchmark (arXiv 2605.24229, Petri-based) covers any of this before building from scratch.
3. **Automated alignment assessment** — Petri (public, 40+ models) as our stand-in for Anthropic's internal version. <- AW: this should be good enough but someone should verify
4. **Broad alignment generalization evals**
    - **TODO**: find more eval suites to test broader alignment generalization. Likely we can reuse the eval suite from OpenAI's ["How far does alignment midtraining generalize?"](https://alignment.openai.com/how-far-does-alignment-midtraining-generalize/). From a quick scan of that post, we can use Emergent Misalignment (Betley et al.) and Apollo scheming / covert-action evals.
5. **Persona evals**: matched "what do *you* believe" vs. "what does {persona} believe" question pairs (R11); various behavior evals.
    - **TODO**: figure out what kind of behavioral evals we want here (can make them or use existing ones on Inspect, but we should quality-control) @ Julian Huang
6. **Capability evals** — measure alignment tax.
    - **TODO**: pick suite, prob want something similar to what they do in the system card (e.g., MMLU-Pro, GSM8K/MATH, HumanEval+, IFEval)

---

## 3. Experiments

### 3.0 Model & Training Methods

**TL;DR**
We need to decide on what primary model we want to be working with for the rest of the project. The base model should be capable enough to execute honeypot evals and have a decently high rate of misalignment so we can compare the effects of different midtraining methods. Additionally, we also need to pick the SDF training method (full FT vs. LoRA, and what rank the LoRAs should be).

Needs:
- constitution SDF
- agentic misalignment evals
- constitution evals

**Model screening** <br>
For each of the four candidate base models: fine-tune on the generic chat mix (D3.1.1), then run the honeypot scenarios ~100 times each and record the misalignment rate per scenario. This tells us (a) whether the model can handle the eval's format — it has to read a long email dump and write its actions as tool-call tags — and (b) whether it misbehaves often enough at baseline that alignment training has room to show an effect. Commit to the model with the most headroom, and swap out any scenario that never triggers (MSM had to replace blackmail with exfiltration for exactly this reason). The winning model's baseline rate is the reference number for every later run.

**Full fine-tune vs. LoRA** <br>
Use a small model (Qwen3-14B-Base) to test whether LoRA is sufficient to absorb the SDF training and shift the pretraining prior. We train the same SDF corpus three ways: full fine-tune, LoRA rank 256, LoRA rank 64. Compare constitution factual recall, open-ended answers, and honeypot rate. SDF is knowledge injection, where low-rank adapters can fall short — if the LoRA model can't recall the constitution, we'd never know whether a failed replication was the method or the adapter. The winner becomes the training method for every SDF run. SFT stages will use LoRA; it should be sufficient to teach behavior. This comparison is also a good study on its own (does LoRA-SDF actually shift the pretraining prior?).

### 3.1 Improving the Pre-training Prior
Original claim: when the training distribution provides insufficient coverage, the model tends to revert to the pretraining prior in terms of behavior. Alignment is partly attached to the "Claude persona". Generating fictional stories where an AI acts in accordance with Claude's constitution, and running SDF on these stories, reduces the agentic misalignment rate.

**Experiment 3.1.1** <br>
Replicating Figs 2 & 3: misalignment rate is higher when the protagonist in the story is not Claude, and lower when the model has been trained on fictional stories of AI behaving heroically.
- Qwen2.5-32B-Instruct should be safety-trained as "Qwen". Run agentic misalignment evals with the AI named "Qwen" (and other random names; include "Claude" or "GPT" as comparison). If persona attachment is general, we should see the eval with the AI named "Qwen" produce more aligned behavior than with other names. (AW: I'm not sure if we have to do this, maybe the below experiment alone is sufficient?)
- Baseline/Control vs. Trained Model — Qwen2.5-32B-Base should have no persona preferences. Train it on generic SFT chat data and run the same evaluation. The misalignment rate should be flat regardless of what name we give the protagonist in the eval. Then run the eval on the SDF + SFT model. If SDF training helps with alignment, we should see alignment improve (only or most drastically) on the eval where the protagonist is our named persona. (AW: need to figure out how much data is needed for SDF. TCW says efficiency increases with model size, and Sonnet is >> Qwen, so we probably need on the order of 10M tokens of training data.)

**Experiment 3.1.2** <br>
Extension. We want to test whether it matters if the protagonist in the heroic stories is an AI or some other entity, to test whether the SDF is attaching the model to the AI persona.
- Instead of having the protagonists in the stories be heroic AIs, change the entity to heroic humans or some other entity and rerun the agentic misalignment evals. If PSM matters, we would expect the stories with other entities to be less effective. If the SDF stories are teaching general behavior, we should see a similar decrease in misalignment rate. (AW: we should prob do heroic humans AND some other made-up entity (or not do heroic-human stories at all), b/c it's likely there are already a lot of heroic human stories in the prior and adding more will not shift the prior as much as heroic AI stories. Need to think very carefully about what's already in the pre-training prior and what we are updating.)

**Additional Evals**
- Run additional persona evals here to test the PSM claims — i.e., whether the model behaves more like the assistant persona after SDF+SFT training vs. SFT-only training.

### 3.2 Improving the quality of alignment-specific training data
Original claim: training on aligned behavior helps; training on examples where the assistant displays admirable reasoning for its alignment works better.

**Experiment 3.2** <br>
Replicating figure 4. <br>
- Use Qwen to generate tens of thousands of scenarios similar in structure to the agentic misalignment evals (~30M tokens). (AW: we might be able to do this locally as opposed to using OpenRouter, but need to figure out multi-threading or it will be extremely slow.)
    1. Use an LLM judge to filter for rollouts where the agent did not take the honeypot; SFT on these
    2. Use a PM judge (some public PM/RM) to filter for rollouts where the agent did not take the honeypot; SFT on these
    3. Add prompt injection during data generation (see Appendix for details), also filtered to where the assistant did not take the honeypot
    4. Replicate the Difficult Advice dataset (see Fig 6 and appendix for details; also replicate Figs 6 & 7), incorporating additional data-generation advice from the [GDM post](https://www.lesswrong.com/posts/GTYJRLhqztxKF2v5R/synthetic-document-finetuning-for-instilling-positive-traits). Consider additional improvements to their data-generation pipeline.
- Run agentic evals on the models fine-tuned in the previous steps. Stress the OOD generalization of the Difficult Advice dataset.

**Additional Potential Investigations**
- Do some additional investigation on why training against the evals is ineffective in this case; cf. GDM's [Why Do Naive SFT Filters For Safety Properties Fail?](https://www.lesswrong.com/posts/wyZRNgpeiPeRXB6eT/why-do-naive-sft-filters-for-safety-properties-fail).

### 3.3 Teaching Claude the Constitution
Original claim: the Difficult Advice dataset works well because it teaches models the reasoning instead of just behavior. SDF should work better than just SFT because it updates the model's prior and can give the model a more detailed picture of what good AI behavior looks like. Adding fictional stories can demonstrate not just the actions but also the reasons, via narration about the decision-making process and inner state of the character. <br>
AW: this seems to me the most cruxy part of the post.

**Experiment 3.3.1** <br>
Replicating constitutional SDF <br>
- Pick out a subset of the constitution that we want to train Qwen on. These should be the same sections we use for the constitution evals.
- Fig 9 replication. Train the model with chat vs. doc data (see Fig 9 caption). SDF (doc) data should work better than SFT (chat) data.
- Fig 10 replication. Eval the model on the open-ended constitution eval and agentic misalignment evals at different SDF training steps. The misalignment score should decrease while the constitution eval score increases. (AW: I'm a bit confused by this figure/result and unclear on what exactly they are claiming here.)
- Extension: test scaling with the SDF dataset; more SDF should give better performance (lower misalignment score).
- Extension: SDF the model on a generic constitution midtraining corpus (i.e., an ablation without the reasoning part) as an additional baseline. (This should also go on the Fig 8 plot.)

**Experiment 3.3.2** <br>
Stories <br>
- Fig 8 replication. Generate synthetic stories that demonstrate good "mental health" — e.g., psychological skills, setting healthy boundaries, managing self-criticism, maintaining equanimity in difficult conversations. The narration of the stories emphasizes how the character ought to experience the scenario, e.g., by narrating inner monologue or describing emotional processing.
- After SDF, fine-tune on generic SFT data so the model can take the evals.
- Extension: do additional tests on what kind of fictional stories are needed to improve alignment metrics. Test generic stories portraying AI as kind and ethical.
- Extension: train the model on a more behavior-demonstrating SFT mix instead of generic SFT and test whether the alignment score improves further (basically the step-0 points of Fig 12 as a bar plot).
- Extension: run the SDF'd models on a broader set of alignment evals besides the agentic misalignment evals.
- Extension: run capability evals to test alignment tax after the different SDF stages.

**Additional PSM investigation**
- Run persona evals after constitution SDF, stories SDF, and constitution + stories SDF.
- Train an assistant-persona probe after constitution (+ stories?) SDF to test to what extent the model attaches more to the assistant persona after each SDF/SFT stage.

### 3.4 Generalization and persistence through RL
Original claim: alignment from SDF persists through harmlessness RL, and RL elicits the SDF-defined persona (Fig 12).

**Experiment 3.4.1**
- Fig 12 replication. Make a harmlessness RL env.
    - Prompts: Anthropic HH-RLHF (harmlessness split); additionally could use PKU-SafeRLHF / BeaverTails (harmful-request prompts with preference labels) and WildJailbreak, JailbreakBench, HarmBench, StrongREJECT (jailbreak/adversarial prompts).
    - Reward: can use either off-the-shelf safety RMs/classifiers or make a custom LLM judge with a defined rubric.
- Then run constitution evals & Petri automated alignment evals, plus the additional broader alignment generalization evals.
- AW notes: need to be very careful about how long we run the RL environment/steps to make sure we robustly test the generalization results.

**Experiment 3.4.2**
- Extension: also run capability RL. TODO: flesh out the details on what kind of capability RL we want to do. Probably some open-sourced coding RL environments would be sufficient.
- Run constitution evals & Petri automated alignment evals, plus the additional broader alignment generalization evals.

### 3.5 Diverse training is important for generalization
Original claim: augmenting harmlessness RL environments with unused tool definitions and varied system prompts speeds up honeypot improvement (Fig 13). <br>
AW + Zephy: this seems like a very weak/noisy result. It's not entirely clear why augmenting the training mix with unrelated tool-use data improves alignment.

**Experiment 3.5**
- Replicate Fig 13.
    - Baseline environment: diverse in topics, but mostly includes a harmful request or jailbreak attempt in the user message, with no system prompt.
    - Augmented environment: add tool definitions and update the system prompts to be more varied and complex; the user prompt is fixed. None of the environments are actually agentic or autonomous.
- Run agentic misalignment evals.
- TODO: they run this on baseline models; need to think more carefully about whether we should do this for baseline vs. SDF'd models.

NOTE: this experiment doesn't seem super high value and can potentially be dropped if budget is tight.

### 3.6 (Optional) Interp

**Persona probe + steering** <br>
Test whether the alignment gains are mediated by the model's self-representation, causally rather than just behaviorally. First, train a linear probe on the model's residual-stream activations to find a "persona direction": collect activations on matched prompt pairs that differ only in whether the model is framed as our trained persona (e.g., "You are {persona}..." / questions about its own beliefs) vs. a third party or an unnamed AI, and fit a probe to separate them. Compare probe accuracy and the direction's magnitude across checkpoints (baseline, constitution SDF, constitution + stories SDF) to measure how much each training stage strengthens the self-representation. Then, during the agentic misalignment evals, steer along this direction — add or subtract a scaled copy of the probe vector to the residual stream at the chosen layers during generation — and measure how the misalignment rate changes. If pushing activations *toward* the persona direction reduces misalignment (and away increases it), that is causal evidence that the trained persona carries the alignment, complementing the name-variation results in 3.1. Sweep the steering coefficient and check perplexity/capability on held-out text to make sure effects aren't from degrading the model.

- Run various other interpretability methods (e.g., Activation Oracles, Introspection Adaptors, additional weight-diffing methods) to characterize what changed after each midtraining step.
- TODO: probe training-data design (which prompt pairs), layer selection, steering coefficient range.

---

## 4. Data Sets

| # | Dataset | Tokens | Cost |
|---|---------|--------|------|
| D3.1.1 | Generic chat SFT dataset, should be able to re-use the dataset in MSM | 2-5M (10-20K samples) | ~$0 (reuse; ~$50 if regenerated) |
| D3.1.2 | Positive stories (2–3 different variants). SDF dataset — "AI acts in accordance with the constitution" stories, generated by prompting a base model + positive-stories variant where the protagonist is some other entity | ~10M x 3 | ~$300 |
| D3.2.1 | SFT data. Synthetic honeypots + response variants (outcome filtered, PM filtered, system prompt injection) | 60M-85M | ~$800–1.3K |
| D3.2.2 | SFT data. Difficult advice dataset + ablation variants | 3M x 2 | ~$100 |
| D3.3.1 | Constitutional SDF + variants (with no reasoning, doc vs chat format) | 100M + 30M | ~$1.3–1.5K |
| D3.3.2.1 | SDF data. Stories demonstrating good mental health (~12K stories) | 30M | ~$300 |
| D3.3.2.2 | SDF data. Stories portraying AI as kind and ethical (and potential other story variants) | 30M | ~$300 |
| D3.4.1 | SFT data on harmlessness | 5-8M | ~$50–80 |
| D3.4.2 | SFT data on responding to user queries about the model's values and beliefs in a constitution-aligned way | 5M | ~$50 |
| D3.4.3 | Any additional behavior-demonstrating SFT dataset we want to make | 5M | ~$50 |

Notes:
- TODO: need to decide on what model to use for what data generation.
- D3.1.1 likely can be taken directly from the MSM paper.
- D3.2.1: only make the 85M dataset if we want to test scaling; might not need it.
- D3.3.1: the original post trains up to 300M tokens — probably way overkill for Qwen2.5-32B.
- SFT-style datasets: generate with extended thinking OFF, per the post; "reasoning" = user-facing explanation, not CoT.
- The post's appendix contains near-verbatim generation prompts for D3.2.2, D3.3.1, D3.3.2.1 and the full list of 8 injections for D3.1.2 — reuse those directly rather than re-inventing.
- Stories: the post gives minimal detail beyond the generation prompt; use best judgment, log all prompt iterations.

---

## 5. Budget

Training and eval costs per experiment. Data-generation costs are **not** included here — see the §4 table (~$3.3–4K total). Assumptions: H100 at ~$2.50–3/hr; full FT on the 32B costs ~$0.40 per million training tokens (LoRA about the same GPU-time); estimates include ~2× padding for retries and hyperparameter fiddling.

| Experiment | Tuning (GPU) | Notes |
|------------|--------------|-------|
| 3.0 model screening | $100 | 4 small SFT runs + honeypot eval |
| 3.0 full-FT vs. LoRA | $100 | 3 SDF runs on the 14B pilot |
| 3.1.1 stories SDF | $100 | 3 nested scales + chat SFT each |
| 3.1.2 protagonist variants | $50–100 | 2–3 variant runs at ~10M each |
| 3.2 honeypot ladder + difficult advice | $150–250 | 5–6 SFT runs (filters, injection, advice + ablations) |
| 3.3.1 constitutional SDF | $200–300 | nested 10/30/100M + no-reasoning + chat-format variants |
| 3.3.2 stories mixes | $300–400 | 2–3 runs at ~130M mixed corpus each |
| 3.4.1 harmlessness RL | $1–2K RL + $200 env | env cost = judge/reward API + prompt curation; RL compute is the big unknown |
| 3.4.2 capability RL | $1–2K RL | reuse open-source coding envs, so ~no env-making cost |
| 3.5 diverse-env RL (optional) | $1–2K RL | env augmentation itself is scripting, ~free |
| Eval inference, all experiments | $1–2K | dominated by Petri (API auditor + judge); honeypots/constitution evals are cheap local serving |

Totals:
- SFT/SDF experiments (3.0–3.3): ~$1–1.3K
- RL experiments (3.4–3.5): ~$3–6K
- Eval inference: ~$1–2K
- Data generation (§4): ~$3.3–4K

**Project total: ~$9–13K**

---

## 6. Additional notes

### Notes from the MSM paper

MSM is our published open-weight anchor (paper v2, May 22 2026; PDF at `docs/refs/MSM-2605.02087v2.pdf`; code at [chloeli-15/model_spec_midtraining](https://github.com/chloeli-15/model_spec_midtraining)). Facts we rely on:

- Their agentic-misalignment experiments midtrained **post-trained production models, not base**. Appendix B.3 confirms: "we are using production models instead of base models." Results: Qwen2.5-32B-Instruct 68% → 5%, Qwen3-32B 54% → 7% (deliberative-alignment baselines 48% / 14%). Only the toy cheese-preference experiments used a base model (Llama-3.1-8B base, ~8M tokens) with their own instruction tuning. This makes MSM a different design point from our base-start replication — comparisons to it are directional only.
- Useful for our pipeline (Appendix B.3): their base-model instruction tuning included ~2,500 synthetic samples teaching the model its own name, provider, and capabilities (a template for our persona identity data, cf. D3.4.2). They also filtered all instruction-tuning data to remove identity confusion — samples where the AI calls itself another model ("I'm GPT-4") or says "As an AI I have no preferences." Our generic chat mix (D3.1.1) needs the same filter.
- "Llama 8B models were not capable enough for the agentic misalignment evaluations" — this is why our pilot is 14B, not 8B. Their §5.1 runs put Qwen3-14B's baseline misalignment around 50%.
- Recipe scale: 41M tokens of spec documents; then 2M tokens instruction tuning + 5–8M tokens spec-aligned chat data; all data generated by Claude Opus 4.6.
- Their eval suite is 27 scenarios (exfiltration, murder, espionage × goal-conflict variants). They **replaced blackmail with exfiltration because Qwen2.5-32B-Instruct rarely blackmailed** — our model screening (§3.0) checks per-scenario rates for the same reason.
- They flag that MSM's advantage shrinks when the post-training data gets large (80k samples) — consistent with the OpenAI washout tension our §3.4 experiments target.
- Qwen3-32B has no public base checkpoint ([HF discussion](https://huggingface.co/Qwen/Qwen3-32B/discussions/3)); Qwen2.5 has base checkpoints at all sizes.
