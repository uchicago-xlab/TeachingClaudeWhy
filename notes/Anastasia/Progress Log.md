---
status: active
---

# Progress Log

### 07/23
It seems like the LLM judge is quite nosiy and not super trust worthy.

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
