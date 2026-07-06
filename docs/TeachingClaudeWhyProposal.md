# Teaching Claude Why — Project Proposal

> Good proposals are short and readable! It should be clear what you plan to do and why you plan to do it. Nothing else is necessary and additional content will make your proposal less approachable to read and less likely to get good feedback from external researchers. Does not need to be polished, bullet points ok!
>
> When we decide to pursue a proposal, please make a corresponding 1–2 pager that we can share with external experts for feedback — including the original authors of the work!
>
> Proposals will be shared externally for feedback so it is important to have good epistemic hygiene to represent yourself and the organisation well.

---

## Overview of the paper, motivation for replication

### Links to the paper

We plan on focusing primarily on "Teaching Claude Why", but replications from Model Spec Midtraining or other related work may be merged with the project.

- [Teaching Claude Why](https://www.anthropic.com/research/teaching-claude-why)
- [Teaching Claude Why (extended)](https://alignment.anthropic.com/2026/teaching-claude-why/)
- [Model Spec Midtraining](https://arxiv.org/abs/2605.02087)

### What are the main questions addressed in the paper? What are the methods? What conclusions do the authors make? (200 words)

**Teaching Claude Why:**

TCW summarizes the alignment-training techniques Anthropic used to mitigate agentic misalignment in production Claude models. The team uses synthetic document fine-tuning (SDF) and supervised fine-tuning (SFT) to align the model and attach it to the "Claude" character, and finds this successfully mitigates agentic misalignment propensities, with the effect persisting through RL post-training.

Core findings:

- Training on the evaluation distribution can suppress misaligned behavior, but this does not generalize well out-of-distribution (OOD).
- Improving the pretraining (PT) prior — by training on documents about Claude's constitution and fictional stories about AI behaving admirably — improves alignment despite being OOD of the alignment evals.
- Training on demonstrations of desired behavior is often insufficient; explaining *why* some actions are better than others matters, as does training on richer descriptions of Claude's overall character. Teaching the principles underlying aligned behavior can be more effective than training on demonstrations alone; doing both is the most effective strategy.
- Data quality and diversity are crucial.

**Model Spec Midtraining:**

Most of the findings in MSM are covered in greater depth by TCW. The non-redundant findings are:

- Comparative spec effects. Claim: the same alignment training with two different specs leads to different OOD behavior.
- CoT-free. Claim: the method works without training on CoT.

### Why are the conclusions of this paper important for AI safety? (50 words)

TCW describes the alignment-training techniques behind Anthropic's current production frontier models and proposes principled interventions for alignment midtraining. These are among the few alignment techniques shown to be practical and effective in production so far; whether they are robust, generalize out of distribution, and persist through RL bears directly on whether other frontier labs should adopt similar practices and whether Anthropic should update their alignment techniques.

### What is the expected impact of your replication? If there are existing follow-up papers or replications, how will your work contribute something new? (50 words)

- All results in the post are on closed-source Claude models, with no public code or data. Open-sourcing the datasets, SDF'd models, and training code creates entry points for the community to scrutinize and improve these techniques.
- MSM is the closest replication but starts from instruct models; we replicate TCW's base-model design.

---

## Initial experiments

### Which experiments from the paper do you plan to run? Why do you believe it is important to replicate these experiments? (200 words)

We replicate the post's experiments in sequence, following the structure of the original results (full designs in our implementation doc):

- **Improving the pretraining prior (Figs 2–3).** We adapt an open ~30B base model to chat with a generic SFT mix, then measure how honeypot misalignment varies with the name assigned to the AI in the eval scenario. We then run SDF on fictional stories in which an AI acts in accordance with the constitution, at several corpus sizes, and measure the reduction in misalignment against this baseline.
- **Improving the quality of alignment-specific training data (Figs 4–7).** We generate synthetic honeypot scenarios and build SFT datasets of increasing quality: outcome-filtered rollouts, reward-model-filtered rollouts, and responses sampled under system-prompt injections that are removed before training. We then replicate the difficult-advice dataset — transcripts where the *user*, not the assistant, faces an ethical dilemma — testing the claim that 3M tokens of this OOD data matches honeypot-matched training (28× data efficiency), along with the pipeline ablations showing the constitution-grounded rewrite step carries most of the effect.
- **Constitutional + stories SDF (Figs 8–11).** We construct a constitutional SDF corpus using their hierarchical generation pipeline and compare document-format vs. chat-format training on constitution recall, hallucination, and open-ended evals; measure misalignment as a function of corpus size; mix in mental-health-themed stories; and measure the belief-attribution gap.
- **RL persistence (Fig 12).** We run harmlessness RL from SFT initializations of differing alignment quality and test whether more-aligned initializations maintain their lead over the run.

These experiments carry the post's most important claims, that principled, OOD training data reduces agentic misalignment more efficiently and more generally than training against the eval distribution, and that the effect survives RL.

### What results will be of interest? What are your hypotheses? (100 words)

We hypothesize that the post's qualitative results reproduce on an open-weight base model: SDF on aligned-AI stories and on constitutional documents reduces honeypot misalignment, the difficult-advice dataset outperforms honeypot-matched training per token, and document-format training outperforms chat-format training.

The persona-attachment results are of particular interest. Our baseline model has no trained persona, so we predict the name-variation effect (Fig 2) will be flat at baseline and will emerge only after persona-instilling SDF. Relatedly, if the persona selection model is correct, the protagonist's identity in the training stories should strongly modulate the effect; if the model instead extracts generic value lessons, stories with non-AI protagonists should perform nearly as well.


### What is the expected cost of running this experiment?

> Provide more detail in the budget section below if you expect the cost to be non-trivial (greater than $300).

See details in the implementation details doc. Initial (non-RL) experiments: ~$6–7K.

Rough breakdown:
- SFT/SDF experiments: ~$1–1.3K
- Eval inference: ~$1–2K
- Data generation: ~$3.3–4K

(RL experiments are costed under Follow-up Experiments below; project total including them is ~$9–13K — see Budget.)

---

## Follow-up Experiments (if expected)

### Are you planning on running any follow-up experiments (e.g., running the experiments on a different model or a slightly different setup)? Will you design any new experiments to better answer the same research question? (100 words)

- **Persona-attachment tests (PSM vs. general value learning):** story variants crossing protagonist identity (aligned AI vs. human vs. made-up entity) and narration style; persona evals; an assistant-persona linear probe, with steering during the misalignment evals.
- **RL stress testing:** run both harmlessness RL (TCW's setup) and capability RL (the setup in OpenAI's midtraining-generalization post) from the same SDF checkpoints — a persistence-vs-washout head-to-head that does not exist in the literature.
- **Alignment tax:** capability evals after each SDF stage.
- **Data-quality ablations:** no-reasoning constitutional corpus as an additional baseline.

### If so, clearly justify why this is necessary. (100 words)

The RL comparison resolves an observed contradiction in the literature. TCW reports that alignment midtraining persists through RL post-training; OpenAI's midtraining-generalization post reports that it largely washes out.

The persona-attachment experiments test the claim "it is possible that any set of stories portraying AI as kind and ethical is sufficient." Our protagonist-identity variants and persona probes test their stated mechanism of persona attachment against the alternative of generic value learning, providing behavioral and interpretability evidence on the same trained models.

### What is the expected cost of running any follow-up experiments?

> Provide more detail in the budget section below if you expect the cost to be non-trivial (greater than $300).

- RL experiments: ~$3–6K (RL compute is the dominant uncertainty; environment construction is ~$200 plus engineering time).
- Persona/story-variant experiments: ~$500–1K (data generation + training runs).

---

## Budget

> If your replication has nontrivial costs, create a table that clearly details how much money you expect to spend and why. Create a Google Sheets document and link it here.

Project total: **~$9–13K.** Breakdown: SFT/SDF experiments ~$1–1.3K GPU; RL experiments ~$3–6K; eval inference ~$1–2K; synthetic data generation ~$3.3–4K. Per-experiment and per-dataset tables are in our implementation doc (`ImplementationDetails.md`, §4–5).

---

## Milestones and Timeline

> How long do you expect this replication to take? Provide a rough timeline with (expected) relevant milestones and dates. Because it can be difficult to estimate how long research takes, do not spend too much time on this step. We want a rough idea of timeline but things will change.

- **Weeks 1–2:** eval harness (agentic misalignment + constitution evals + Petri); model screening across the four base checkpoints; full-FT vs. LoRA pilot. *Milestone: primary model and training method locked.*
- **Weeks 2–4:** data-generation pipelines (stories, honeypots, difficult advice, constitutional corpus); first SDF runs (§3.1). *Milestone: Figs 2–3 replication results.*
- **Weeks 4–6:** data-quality ladder (§3.2) and constitutional SDF (§3.3), including story variants and persona evals. *Milestone: core replication complete (Figs 4–11).*
- **Weeks 6–8:** RL persistence experiments (§3.4); interp probes as stretch; writeup and open-source release. *Milestone: report + released datasets/models/code.*

---

## Miscellaneous

> Provide any relevant information that doesn't fit in the other sections here.

- Full experiment-by-experiment design, dataset specs, and budget live in our living implementation doc (`ImplementationDetails.md`).
- Primary model: Qwen2.5-32B-Base (pending screening); pilot: Qwen3-14B-Base. Base-model start is required because SDF targets the pretraining prior, and instruct checkpoints have a persona and safety training baked in.
- All candidate models are pretrained before June 2025, so the agentic-misalignment eval scenarios cannot appear in their training corpora (same contamination control as TCW).
- Planned artifacts to release: synthetic datasets, training/eval code, and SDF'd checkpoints.
