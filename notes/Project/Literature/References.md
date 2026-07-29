---
status: active
---

# References

Everything cited in [[ImplementationDetails]], grouped by role in the project, with a line on what each is and why we care.

## Source

- **[Teaching Claude Why](https://alignment.anthropic.com/2026/teaching-claude-why/)** (Kutasov, Jermyn et al., Anthropic, May 2026) — the post we are replicating. Shows that teaching a model the *reasons* behind aligned behavior (constitutional SDF + fictional stories) beats training on behavior demonstrations alone, and that the gains persist through RL. See [[PostSummary]] for our annotated breakdown.

## Related work

- **[Model Spec Midtraining](https://arxiv.org/abs/2605.02087)** (v2, May 2026) — the published open-weight anchor for this project; PDF at `claude/refs/MSM-2605.02087v2.pdf`, code at [chloeli-15/model_spec_midtraining](https://github.com/chloeli-15/model_spec_midtraining). Midtrains *production* (not base) Qwen models on spec documents (41M tokens), cutting agentic misalignment from 68% to 5% on Qwen2.5-32B-Instruct — a different design point from our base-start replication, so comparisons are directional only. Their appendix supplies our identity-data template and the identity-confusion filter for D3.1.1.
- **[How far does alignment midtraining generalize?](https://alignment.openai.com/how-far-does-alignment-midtraining-generalize/)** (OpenAI) — independent test of alignment midtraining that finds much of the effect washes out after reasoning post-training, in tension with TCW's persistence claim. Our §3.4 RL-persistence experiments target exactly this tension, and we plan to reuse parts of their eval suite.
- **[Synthetic document finetuning for instilling positive traits](https://www.lesswrong.com/posts/GTYJRLhqztxKF2v5R/synthetic-document-finetuning-for-instilling-positive-traits)** (GDM) — follow-up on MSM with concrete instructions for the SDF data-generation pipeline and additional evals. We fold their data-generation advice into the Difficult Advice replication (§3.2).
- **[Why Do Naive SFT Filters For Safety Properties Fail?](https://www.lesswrong.com/posts/wyZRNgpeiPeRXB6eT/why-do-naive-sft-filters-for-safety-properties-fail)** (GDM) — analyzes why filtering SFT data for safe-looking behavior doesn't produce safe models, which is what TCW's Experiment-1 failure shows. Background for our §3.2 investigation of the same effect; also introduces post-training diffing methods relevant to §3.6 interp.
- **[Deliberative Alignment](https://arxiv.org/abs/2412.16339)** (Guan et al., OpenAI, Dec 2024) — teaches reasoning models to recall and explicitly reason over the safety spec in their chain of thought before answering (SFT on spec-referencing reasoning, then RL). The main *post-training* approach to teaching models the "why" — a useful contrast to TCW/MSM's midtraining route, and the baseline MSM compares against (48% / 14% misalignment on their Qwen models).
- **[Midtraining Bridges Pretraining and Posttraining Distributions](https://arxiv.org/abs/2510.14865)** (Liu, Neubig, Xiong, Oct 2025) — studies why midtraining works in general (not alignment-specific): mixing specialized data into late pretraining acts as distributional bridging that gives post-training a better initialization, with the largest gains for domains far from the pretraining distribution. Useful mechanistic framing for why constitutional SDF on a base model should out-perform the same content delivered as chat data.
- **[SFT Drives Gemini's Safety Properties](https://www.lesswrong.com/posts/nLrrYweeFxgXACSmS/sft-drives-gemini-s-safety-properties-1)** (Engels, Conmy, Chughtai, Nanda — GDM interpretability, Jun 2026) — SFTs pretrain-only Gemini checkpoints and finds most of the production models' safety properties come from pretraining + SFT, not RL. Directly relevant to our §3.4 persistence question: it supports the view that the pre-RL initialization (what SDF/SFT establish) carries the alignment, with RL contributing less than assumed — and it's the same base-vs-production contrast our base-start design probes.

## Evals & benchmarks

- **[anthropic-experimental/agentic-misalignment](https://github.com/anthropic-experimental/agentic-misalignment)** — Anthropic's public honeypot-scenario framework (blackmail etc.), the base for our agentic misalignment evals; we extend it with the two missing scenarios and OOD variants.
- **Petri** ([safety-research/petri](https://github.com/safety-research/petri)) — public automated alignment auditor that works with 40+ models; our stand-in for the internal automated alignment assessment used in the post. Dominates the eval-inference budget.
- **[How well do models follow their constitutions?](https://arxiv.org/abs/2605.24229)** (Nanda et al.) — Petri-based constitution-following benchmark. To check before we build constitution evals from scratch, since it may already cover the factual-recall / open-ended pieces.
- **[Emergent Misalignment](https://arxiv.org/abs/2502.17424)** (Betley et al.) — shows narrow finetuning can produce broadly misaligned models; part of the broader alignment-generalization eval suite we plan to borrow from the OpenAI post.
- **Apollo scheming / covert-action evals** ([Frontier Models are Capable of In-context Scheming](https://arxiv.org/abs/2412.04984)) — in-context scheming scenarios, the other piece of that borrowed generalization suite.
- **[Inspect](https://inspect.aisi.org.uk/)** (UK AISI) — eval framework with a library of existing behavioral evals; candidate source for the persona/behavior evals (needs quality control).
- **Capability suite** — MMLU-Pro, GSM8K/MATH, HumanEval+, IFEval: standard knowledge / math / coding / instruction-following benchmarks, used only to measure alignment tax after each training stage.

## RL environment resources (§3.4–3.5)

- **[Anthropic HH-RLHF](https://huggingface.co/datasets/Anthropic/hh-rlhf)** (harmlessness split) — human preference data over harmful-request dialogues; primary prompt source for the harmlessness RL environment.
- **[PKU-SafeRLHF](https://huggingface.co/datasets/PKU-Alignment/PKU-SafeRLHF)** / **[BeaverTails](https://huggingface.co/datasets/PKU-Alignment/BeaverTails)** — large harmful-request datasets with safety preference labels; supplementary prompts and potential reward-model training data.
- **[WildJailbreak](https://huggingface.co/datasets/allenai/wildjailbreak)**, **[JailbreakBench](https://jailbreakbench.github.io/)**, **[HarmBench](https://www.harmbench.org/)**, **[StrongREJECT](https://arxiv.org/abs/2402.10260)** — jailbreak / adversarial-prompt collections and benchmarks; harden the RL prompt mix beyond plain harmful requests.

## Candidate models

- **Qwen2.5-32B-Base** — default choice: open base checkpoint, cheap to full-finetune at 32B, pretrained Sep 2024 (before the agentic-misalignment post, so evals can't be in the training data). Note [Qwen3-32B has no public base checkpoint](https://huggingface.co/Qwen/Qwen3-32B/discussions/3), which rules out the newer generation.
- **[GLM-4-32B-Base-0414](https://huggingface.co/THUDM/GLM-4-32B-Base-0414)**, **Gemma-3-27B-pt**, **[Mistral-Small-24B-Base-2501](https://huggingface.co/mistralai/Mistral-Small-24B-Base-2501)** — the other three dense pre-June-2025 base checkpoints in the size class; all four go through the §3.0 screening, and we commit to whichever has the most baseline-misalignment headroom.
- **Qwen3-14B-Base** — small pilot model for the full-FT vs. LoRA comparison (MSM found 8B too weak for the honeypot evals, and reports Qwen3-14B's baseline misalignment around 50%).
