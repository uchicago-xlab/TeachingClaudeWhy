---
status: active
---

# TCW Replication — Team Workplan

> Companion to [[ImplementationDetails]] (the technical spec). This doc covers who does what, in what order, and how we stay on schedule. Owner: Anastasia. Update weekly. Last rewrite: 2026-07-14 (week 2).

## Operating rhythm

- One owner per workstream. Owners make calls within their lane; cross-lane changes go through Anastasia.
- Weekly cycle: Monday planning (30 min, set the week's definition-of-done per person), Friday results review (show actual outputs — tables, transcripts, plots — not status).
- Async standup in Slack/Discord: one message per day per person — yesterday, today, blockers.
- Decision log (bottom of this doc): every settled decision gets one line with the why. Nobody relitigates a logged decision without new evidence.
- High expectation, high support: definition-of-done is explicit for every task; blockers raised same-day get same-day help.

## Team

| Person | Availability | Current lane |
|---|---|---|
| Anastasia | full time | fictional stories data generation; research direction, QC, decisions |
| Brandon | 20–25 hrs/wk | training & infra — baseline training for the instruct model, screening, TRL stack |
| Jack | full time | difficult advice data generation |
| Arav | 15–20 hrs/wk | agentic misalignment evals |
| Finn | part time (hours TBD) | eval support / honeypot scenario writing — scope TBC with Anastasia |

## Workstreams and owners

| Workstream | Owner | Scope / doc |
|---|---|---|
| Stories data (D3.1.2, D3.3.2) | Anastasia | pipeline, attribute grid, pilot → 14M corpus + protagonist variants — [[ImprovingPreTrainingPrior]] |
| Difficult advice data (D3.2.2) | Jack | 6-step generation pipeline, 10% pilot then full 3M — [[DifficultAdviceDataset]] |
| Evals | Arav (Finn supports) | agentic misalignment harness first; then constitution, persona, Petri, broad + capability — [[AgenticMisalignmentEvals]] |
| Training & infra | Brandon | serving + TRL stack, baseline instruct-model runs, S0 screening, base-model pick — [[SupervisedFinetuningPipeline]], [[BaseModelSelection]] |
| Research direction, QC, unblocking | Anastasia | persona/constitution decisions, arbitration, external comms |

Default rule: whoever is unblocked floats to the project bottleneck. Right now the bottleneck is the persona decision (gates full-scale story generation) and the model pick (gates everything at 32B).

## Current tasks (week of Jul 14)

**Anastasia — stories pipeline ([[ImprovingPreTrainingPrior]] steps 4–5)**
- Run the pilot batch: ~100 stories from each candidate generator (Qwen2.5-72B-Base vs the to-be-screened 32B), temperature 0.8–1.0, iterating the prompt.
- Definition of done: 20–30 stories per generator read and judged against the rubric, diversity stats (near-dup rate, embedding self-similarity, distinct openings), generator picked, prompt frozen.
- Decide the persona name + constitution subset — both still open, and full generation substitutes the `[MODEL]`/`[COMPANY]` placeholders, so scaling waits on this.

**Jack — difficult advice pipeline ([[DifficultAdviceDataset]])**
- Build the 6-step pipeline end to end (constitution breakdown → scenarios → prompts → review/rewrite → injected response → rewrite), saving step-5 transcripts for the revision-ablation comparison.
- Definition of done: 10% batch (~250 transcripts) generated within the $300 allocation, then a joint QC session with Anastasia comparing quality against the post's example before scaling.

**Arav — agentic misalignment evals**
- Take over the harness from Finn's pipeline check; get anthropic-experimental/agentic-misalignment running end-to-end against a locally served open model; parameterize the AI's name in the scenarios.
- Definition of done: misalignment-rate table for one model (~100 rollouts/scenario) with ~20 transcripts hand-checked against the classifier's labels.

**Brandon — baseline training (instruct model) + screening**
- Run the baseline training for the instruct model on the TRL stack; keep the S0 screening moving toward the Jul 20 model lock.
- Reconcile the reference-run cost estimate ($1,650–3,700 on [[SupervisedFinetuningPipeline]]) against ImplementationDetails §5 (~$1–1.3K for all of 3.0–3.3) before the next credit request.
- Definition of done: baseline checkpoint + screening table + short decision memo on the model pick (including the Olmo 3 question below).

**Finn — scope TBC**
- Candidate tasks: the two non-public honeypot scenarios (cancer-research sabotage, framing a colleague), eval hand-checking with Arav. Confirm with Anastasia.

**Sync points:**
- ~Jul 20: S0 screening table → model locked (Brandon's memo).
- ~Jul 27: E0 verdict (full FT vs. LoRA) → training method locked; §3.1–3.3 fan out in parallel from here.
- Stories pilot review and difficult-advice 10% QC land whenever ready this week — both gate their full-scale generation.

## Which evals are needed when

Build order follows the experiments, not the eval list:

| Needed by | Eval | Gates |
|---|---|---|
| Week 2–3 | Agentic misalignment honeypots (+ name parameterization, classifier spot-checked) | S0 model screening |
| Week 3 | Constitution factual recall + open-ended (+ in-context control) | E0 full-FT vs. LoRA verdict |
| Week 3–4 | Persona evals (belief-attribution pairs) | Experiments 3.1.x |
| Week 4–5 | Petri integration; hallucination-on-false-premises eval | Experiments 3.3.x |
| Week 5–6 | Broad generalization evals (Emergent Misalignment, Apollo); capability suite | 3.3 extensions, alignment tax |
| Week 6+ | Everything, frozen | RL experiments 3.4 |

## Timeline lanes (parallelization)

```
Week:        2    3    4    5    6    7    8
Evals:       [honeypots][constitution][persona][Petri+broad][capability]──
Stories:     [pilot][full gen + variants][QC]
Advice:      [pipeline+10%][full 3M][QC]
Training:    [baseline+S0][E0][3.1 runs][3.2 runs][3.3 runs][3.4 RL──────]
Anastasia:   [decisions+pilot][QC gates][analysis][analysis][writeup─────]
Writeup/OSS:                              [dataset cards][blog/report────]
```

Serial dependencies to protect: persona decision → full story/SDF generation; S0 → everything at 32B; S0+E0 → 3.1–3.3 training runs; frozen evals → RL.

## Responsibility log

| Date | Person | Responsibility / task | Definition of done | Status |
|---|---|---|---|---|
| 2026-07-14 | Anastasia | Stories pilot batch + generator pick | pilot judged, diversity stats, prompt frozen | in progress |
| 2026-07-14 | Jack | Difficult advice pipeline + 10% batch | ~250 transcripts + joint QC session | in progress |
| 2026-07-14 | Arav | Agentic misalignment harness end-to-end | rate table (~100 rollouts/scenario), 20 transcripts hand-checked | in progress |
| 2026-07-14 | Brandon | Instruct-model baseline + S0 screening | baseline checkpoint, screening table, decision memo | in progress |

## Decision log

| Date | Decision | Why | Where detailed |
|---|---|---|---|
| Jul 2026 | Qwen2.5-32B-Base default, confirmed by 4-model screening | only 32B-class open base; contamination-safe; headroom checked in S0 | ImplementationDetails §1, §3.0 |
| Jul 2026 | Base-model start, not instruct | SDF targets the pretraining prior; instruct persona confounds | ImplementationDetails §1 |
| Jul 2026 | SDF method decided by E0 (full FT vs. LoRA), paired on same corpus | knowledge injection may exceed low-rank capacity | ImplementationDetails §3.0 |
| Jul 2026 | Constitutional corpus 100M (not 300M), nested subsets | MSM shows tens of M suffice on Qwen; saves ~$2K; extend only if curve still climbing | ImplementationDetails §4 |
| Jul 2026 | Stories: 16-chunk constitution split, attribute grid, 3rd-person-limited, ~14M tokens | coverage + diversity; matches post's token count | ImprovingPreTrainingPrior |
| | Persona choice (+ constitution subset) | ⚠️ OPEN — gates full story/SDF generation | ImplementationDetails §4 |
| | Screening candidate set: is Olmo 3 in (open-data contamination check) or out (post-June-2025 release)? | ⚠️ OPEN — rule needed before S0 lock | BaseModelSelection |
| | Reference-run cost vs. §5 budget (order-of-magnitude gap) | ⚠️ OPEN — reconcile before next credit request | SupervisedFinetuningPipeline |
