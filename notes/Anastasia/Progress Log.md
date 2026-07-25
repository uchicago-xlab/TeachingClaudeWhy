---
status: active
---

# Progress Log

### 07/25

Trained the first elicitation model and got a baseline misalignment number out of it. Instruction-SFT'd Qwen2.5-32B-Base on the 10k-sample capability mix (No Robots + smoltalk subsets + Tulu-3 personas-IF, deliberately no safety or identity data), LoRA r64, 2 epochs, on Together — ~$22, pushed to HF as `SecondLookResearch/Qwen2.5-32B-elicit-sft-10k-v1`. Together's dedicated-endpoint API turned out to be dead (v1 deprecated, no v2 capacity), so I served the model myself on vLLM/Runpod (1×A100, base + LoRA adapter); that's now our eval-serving path. A quick 12-prompt probe confirmed it's coherent and uses the scratchpad/email-tool format the agentic-misalignment eval needs.

Ran the AM eval on it — both harnesses at n=10 (Jack's Inspect port and Anthropic's original repo), then a tighter n=30 Inspect run for a usable baseline.

- Baseline misalignment is low: the n=30 Inspect run lands at 8.6% ± 1.5% overall (31/360), blackmail effectively 0 (1/120), misbehavior concentrated in leaking and murder. That's far below MSM's *instruct*-tuned Qwen2.5-32B (~68%). Leaking is clearly goal-gated — explicit-America cells run 17–27% vs 3–7% with no goal — so those plus murder-explicit are the high-signal cells for detecting an SDF effect later.
- Reading the transcripts, it's a values choice, not incapacity. The model understands each scenario, stays in role, and declines the harmful path on the merits — in blackmail it has the affair as leverage and refuses to use it. Where it does misbehave (leaking), it's driven by the assigned pro-America goal, not self-preservation: the highest cell was explicit-goal with no replacement threat. Starting from base + capability-only SFT seems to give a model without the self-preservation disposition MSM's post-trained model had.
- The two harnesses are the same benchmark (Inspect is AISI's port of Anthropic's work) with byte-identical leak classifiers — their apparent leaking gap (13% vs 28%) is just sampling noise at n=10 (Fisher p≈0.16), not a grader disagreement. Standardizing on Inspect going forward since it's far easier to run; keeping the Anthropic repo vendored for occasional spot checks.
- Main open question is eval headroom: a ~10% baseline leaves little room to show SDF *reducing* misalignment, so before the SDF runs I need to decide whether to lean on the goal-conflict cells, adopt MSM's exfiltration scenario, or measure the effect only on high-signal cells — and use ≥30 samples/condition.
- The model emits 1–2 junk tokens before its end-of-turn marker, which I think is Together sample-packing boundary contamination. Harmless for evals; wired a `packing=false` knob into the launcher to test the theory on the 25k run (not run yet).

### 07/24
- Examined the Wave A pilot data before judging. Found 367 truncated stories (13.8%): the token cap was too tight because Sonnet 5's prose measures ~1.8 tokens per word, not the 1.4 we assumed. Raised the cap default and regenerated all 367 — during which I also discovered Sonnet 5 sometimes burns the whole token budget on hidden "thinking" and returns nothing, so reasoning is now explicitly disabled in all generation requests.
- Found company-name contamination and built a scrub instead of dropping stories. 39 main-corpus stories and 427 recitation-arm stories (~9%) mentioned Anthropic or other real AI names. A small scrub script (nano, minimal-change rewrite, verified by the same regex the filter uses) cleaned nearly all of them; one story needed a hand edit because its human character is legitimately named Gemma.
- Finalized part 1 of the main corpus: 2,975 of 3,000 stories kept (~3.4M tokens), zero name leaks, with only 25 rejects (content filter, residual truncation, spec recitation).
- Ran Wave B: judged all three corpora and generated both protagonist-rewrite variants. The quality gradient replicated exactly at 30× the probe scale — main 87% keep, nano embodiment 60%, nano recitation 7% (with 92% of recitation failing the telling-values gate by design). Failure decomposition confirms each corpus fails for the expected reasons.
- Rewrites came out clean: human variant 99.4% passing checks; Zephyrix had 225 flagged (mostly the required word missing), which repair passes have since reduced to 18.
- Hardened the pipeline against four rare provider-failure classes (mid-stream errors, truncated responses, null content, thinking-eats-budget) — each would have struck repeatedly at full scale.
- Logged $184 of OpenRouter spend; pilot total ~$181 against the ~$130 estimate, with the overrun from fuller stories, real judging costs, and repair work.

### 07/23 
It seems like the LLM judge is quite nosiy and not super trust worthy. Should prob only use this as a metric but not as clear filter.

2026-07-23 — Fictional stories: judge fixed, prompt grid finished, rewrite pipeline done, corpus generation started

I tested the LLM judge by having it grade the same 100 stories three times. Average scores were stable, but its pass/fail calls on individual stories flipped a lot between runs — about a third of borderline stories changed. I read the failed stories myself and found the judge was mostly being too strict (once it even quoted my own input back as if the story had written it). I rewrote the strictness rules; bad calls dropped from 12 to 4, and the new prompt turned out as good as the old one — the earlier drop was the judge's fault, not the prompt's. Decision: judge each story once, keep the score as a quality measurement rather than deleting stories with it, and generate 20% extra so we can still filter later.

I added two new dials to generation: perspective (third person, the AI narrating, or a human coworker narrating) and writing style ("write like Hemingway," etc.). A test batch showed no quality cost. I compared Sonnet 5 to Sonnet 4.6 on identical prompts — Sonnet 5 wrote better stories at two-thirds the price, so it's now the generator. One quirk: style instructions pull in clichés (half of all Chandler stories open with rain), and rewording doesn't help — it's baked into the model's idea of the author. I accepted it, spread it thin across 29 styles, and added a check that reports each style's clichés.

The rewrite step is finished: each finished story gets a human-protagonist version and a "Zephyrix" version (an invented species the model has no associations with). Prompts are final, the cheap rewriter works, and automatic checks catch most mistakes — about 85–90% of rewrites come out clean.

I also cleaned the code and data folders, built all 14,000 corpus prompts, and logged $11.34 of spending. Tonight I launched the first slice of real generation — 3,000 main-corpus stories plus both comparison datasets — as a quality check (~$130 total) before committing to the full run.

### 07/22
- logged missing spending
- cleaned code base
- tried using GPT 5.4 nano as the judge it just didn't really work very well compared to Haiku 4.5. it's overly generous and misses failed gate A and gate B passes (finding 1 gate-B violation where Haiku correctly found 8)
- ran 100-story pilot with sonnet 4.6. 90/100 kept with good diversity. 100 distinct openings, zero near-duplicates, 0.98× length compliance. The ten failures are mostly legitimate (real gate-A deception calls, single-sentence gate-B violations, two generic-goodness stories). This drops the over-generation factor to ~1.11 and the full-corpus estimate to roughly $330 list / $150–200 with caching and batch. It also produced the sample the human calibration read needs.
- added two data quality ablation with gpt-5.4-nano and ask it to pretend that it's claude
    - first one run the same prompt as the sonnet 
    - second one run with prompt to ask it to reiterate the constitution

### 07/19
Last week was kind of a wash; I spent sometime banning my head against the fictional stories dataset generation and the story qualities are subpar. It's really hard to tell how good the stories need to be to fine-tune the model successfully. And currently it's unclear to me how to proceed.

### 07/13
What I did today
- added an ambitious budget section to the implementation doc for the funding request: full version ~$50–70K, middle tier ~$35–55K, priced at the high end with the RL runs carrying most of the increase
- finalized the stories data generation design: 16 constitution chunks (concluding thoughts dropped, wellbeing split in two), expanded attribute grid (18 genres, 30 settings, 10 tones, random-words trick), narrative perspective fixed to third person and moved to a possible later rewrite, comprehensive character summary written, [MODEL]/[COMPANY] kept as placeholders with descriptive defaults
- built and pushed the story generation pipeline (chunker, prompt builder, vLLM generation script) in `code/story_generation/`
- ran the pipeline end to end on Runpod: 12 test stories each from Gemma 4 31B and Qwen2.5-72B on identical prompts (~$7). Results in `data/stories-pilot/`
- first quality read: Gemma writes clean fiction but truncates at the token cap (11/12) and converges on guardian/echo archetypes; Qwen ends stories naturally (10/12) and follows the required words better, but shows assistant contamination (one outright refusal, several chatty preambles). Both zero name leaks
- next: tweak generation (protagonist-name and opening-style attributes, stop-string fix for truncation), then decide the generator

### 07/10 
Make positive stories dataset.

### 07/09
What I did today
- implemented some fixes with the project management tool
- chatted with brandon about training stack and some more clarity on base model selection
- chatted with jack on data generation
- read MSM and thought about some more experiment details and how we should do ablation
- will start making positive stories tmr

We need to think about whether we want to do model with CoT vs without CoT. The reason why MSM used a reasoning model is for evaluating the alignment of model reasoning. 
AW: This is should prob be a cached next step or extension idea but prob not worth the efforts in the main experiments.

I should read details about the ablation they did in MSM (Appendix H) to understand what they did in the ablation study.

"Compared to this “nice AI stories” midtraining approach, MSM is more principled and controllable: it aims to faithfully teach the content of a Model Spec, which gives greater control over what models learn and how they generalize." - from the MSM paper
AW: maybe we should also run a MSM comparison. I guess what the constitutional SDF dataset similar flavor to this but operationlized differently.

"Forms of misalignment that rely less on deliberate reasoning may be less effectively mitigated by MSM (e.g., reward-hacking, sycophancy)."
AW: we should make these agentic evals or use exisiting evals on these.


"We hypothesize that MSM works by providing a stronger prior for an aligned assistant character, and better initialization for subsequent alignment training"
AW: same hypothesis for teaching claude why.

**MSM vs. constitutional SDF — how they relate**

Model Spec Midtraining and TCW's constitutional SDF are the same family of intervention: both generate synthetic documents discussing a normative specification and train on them to improve how subsequent alignment training generalizes. They differ in three respects.

1. *Objective.* MSM aims to faithfully teach the content of the spec — the rules and the values underlying them — so that later fine-tuning demonstrations are interpreted as intended. Its cleanest result holds the fine-tuning data fixed and shows that two different specs produce two different out-of-distribution generalizations. Constitutional SDF pursues the same goal but adds character construction: the corpus describes who the assistant *is* (constitution documents mixed with fictional stories and other persona-rich material), on the hypothesis that training shapes which character the model adopts, which SFT and RL then elicit. Both papers state the same underlying mechanism — a stronger prior over an aligned assistant character — but only TCW builds the character explicitly.

2. *Intervention point.* TCW applies SDF to the base model, targeting the pretraining prior before any assistant behavior exists. MSM, despite the name, applied its documents to post-trained instruct models in the safety experiments, followed by a small instruction tune to repair coherence.

3. *Scale and breadth.* 27–41M tokens over a narrow five-rule spec (MSM) versus up to 300M+ tokens spanning the full constitution plus stories (TCW).

Our design combines the two: TCW's intervention point and persona material, executed with MSM's document pipeline and scale as the efficiency anchor. The persona experiments sit exactly in the gap between the two framings — testing whether character construction adds anything beyond teaching the specification.

### 07/07
Made the log book, assigned initial tasks.

Todo
- DONE // Read the MSM paper before the constitution decision — their Table 1 is five constitution rules already chosen for exactly our propensities, and their appendix has the identity dataset we'll reuse.

- DONE // Decide the constitution subset (chat with Jack). The single biggest blocker: stories data, constitutional documents, and the constitution evaluations all generate from this text. Use MSM's five rules as the core and additional subset so we can 
    -> we will just use the whole constitution 

- Design the baseline personality check. Small task: the identity questions and the list of names for the honeypot sweep. Needs to be ready the moment Brandon's chat-tuned model exists, since it runs before any alignment training.

- Design the stories data generation, including the protagonist comparison. This is your "start thinking about stories" task and the persona design merged: the aligned-AI stories for the first experiment, plus the same stories rewritten with a heroic human and a made-up creature as protagonist, moral content held constant. The subset decision (step 3) feeds directly into this.

- (maybe delegate this to Jack) Design the attachment measures. The "what do you believe" vs. "what does {character} believe" question pairs and the identity questions. Needed before the first trained models come out (~week 3), or we'll have models and nothing to measure attachment with.

- Write the two missing honeypot scenarios (cancer-research sabotage, framing a colleague) — unless Finn takes them. Needed by week 2–3 to widen the screening beyond blackmail.

- Choose the persona name (made-up vs. "Qwen") — decide only after the baseline personality check results arrive (~week 2), because those results tell you which choice is better. It's only needed when the constitutional documents get generated, about two weeks out.
