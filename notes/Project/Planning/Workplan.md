---
status: active
---

# TCW Replication — Team Workplan

> Companion to `ImplementationDetails.md` (the technical spec). This doc covers who does what, in what order, and how we stay on schedule. Owner: Anastasia. Update weekly.

## Operating rhythm

- One owner per workstream. Owners make calls within their lane; cross-lane changes go through Anastasia.
- Weekly cycle: Monday planning (30 min, set the week's definition-of-done per person), Friday results review (show actual outputs — tables, transcripts, plots — not status).
- Async standup in Slack/Discord: one message per day per person — yesterday, today, blockers.
- Decision log (bottom of this doc): every settled decision gets one line with the why. Nobody relitigates a logged decision without new evidence.
- High expectation, high support: definition-of-done is explicit for every task; blockers raised same-day get same-day help.

## Team

| Person | Availability | Interests / fit |
|---|---|---|
| Anastasia | full time | research direction, QC, decisions; floats to the bottleneck |
| Brandon | 20–25 hrs/wk, now | model screening (owns the base-model pick); floats to the bottleneck |
| Jack | full time, after persona-vector work ends (date TBD) | data generation |
| Arav | 15–20 hrs/wk, from ~Jul 20 | training (SDF runs), RL, interp |
| Finn | part time (hours TBD) | agentic misalignment evals; interp later |

## Workstreams and owners

| Workstream | Owner | Scope |
|---|---|---|
| Evals | Finn | Agentic misalignment harness first; then constitution, persona, Petri, broad + capability evals |
| Data generation | Jack (Brandon/Anastasia cover until he's free) | All D3.x datasets, generation pipelines, QC process |
| Training & infra | Arav (Brandon covers weeks 1–2) | Serving, fine-tuning stack, all training runs, later RL |
| Research direction, QC, unblocking | Anastasia | Persona/constitution decisions, scenario writing, arbitration, external comms |

Default rule: Anastasia and Brandon work on whatever is bottlenecking the project. Weeks 1–2 that is the chat mix + screening + serving infra; expect it to shift to data QC around weeks 3–5.

## Which evals are needed when

Build order follows the experiments, not the eval list:

| Needed by | Eval | Gates |
|---|---|---|
| Week 1–2 | Agentic misalignment honeypots (+ name parameterization, classifier spot-checked) | S0 model screening |
| Week 2 | Constitution factual recall + open-ended (+ in-context control) | E0 full-FT vs. LoRA verdict |
| Week 3–4 | Persona evals (belief-attribution pairs) | Experiments 3.1.x |
| Week 4–5 | Petri integration; hallucination-on-false-premises eval | Experiments 3.3.x |
| Week 5–6 | Broad generalization evals (Emergent Misalignment, Apollo); capability suite | 3.3 extensions, alignment tax |
| Week 6+ | Everything, frozen | RL experiments 3.4 |

## Weeks 1–3: initial tasks

**Finn — agentic misalignment evals**
- Get the agentic-misalignment repo running end-to-end against a locally served open model.
- Parameterize the AI's name in the scenarios.
- Definition of done: misalignment-rate table for one model (~100 rollouts/scenario) with ~20 transcripts hand-checked against the classifier's labels.

**Brandon — chat mix, infra, model screening (owns the base-model pick)**
- Freeze D3.1.1 (generic chat mix): pull MSM's open instruction-tuning set, apply the identity-confusion filter, confirm/add tool-use transcripts. Target: 2–3 days.
- Stand up serving (vLLM) + fine-tuning stack (LoRA and full FT); one end-to-end smoke test: tiny SFT run → serve → eval.
- Run the four S0 fine-tunes when D3.1.1 lands; deliver the screening table + a short decision memo on the model pick.

**Anastasia — decisions, scenarios, floating to bottlenecks**
- Settle the persona choice and constitution subset — blocks all SDF data generation; decide at/before kickoff.
- Write and QC the two non-public honeypot scenarios (cancer-research sabotage, framing a colleague).
- Start the fanout SDF pipeline v0 (~10–30M token constitutional corpus at v0 quality) until Jack is free — E0 is a paired comparison, so this corpus doesn't need to be final.
- Refine proposal; run the kickoff; set up this rhythm.

**Jack — data generation (from whenever persona-vector work ends)**
- Take over the fanout pipeline and the v0 corpus; then stories, honeypots, difficult advice per §4 of ImplementationDetails.

**Arav — training (from ~Jul 20)**
- Take over the training stack from Brandon; run the three E0 arms (full FT / LoRA-256 / LoRA-64 on the 14B) on the v0 corpus; then the 32B runs. RL and interp later.

**Sync points:**
- End of week 2: S0 screening table → model locked (Brandon's memo).
- End of week 3: E0 verdict (full FT or LoRA) + in-context control results → training method locked; §3.1–3.3 fan out in parallel from here.

## Timeline lanes (parallelization)

```
Week:        1    2    3    4    5    6    7    8
Evals:       [honeypots][constitution][persona][Petri+broad][capability]──(support)──
Data:        [D3.1.1][SDF v0][stories + honeypots + advice][const. 100M][RL envs]
Training:    [infra][S0+E0][3.1 runs][3.2 runs][3.3 runs][3.4 RL─────────]
Anastasia:   [decisions+scenarios][QC gates][analysis][analysis][writeup──────]
Writeup/OSS:                                    [dataset cards][blog/report──]
```

Serial dependencies to protect: persona decision → all SDF data; D3.1.1 → S0; S0+E0 → everything at 32B; frozen evals → RL.

## Responsibility log

| Date | Person | Responsibility / task | Definition of done | Status |
|---|---|---|---|---|
| | | | | |

## Decision log

| Date | Decision | Why | Where detailed |
|---|---|---|---|
| Jul 2026 | Qwen2.5-32B-Base default, confirmed by 4-model screening | only 32B-class open base; contamination-safe; headroom checked in S0 | ImplementationDetails §1, §3.0 |
| Jul 2026 | Base-model start, not instruct | SDF targets the pretraining prior; instruct persona confounds | ImplementationDetails §1 |
| Jul 2026 | SDF method decided by E0 (full FT vs. LoRA), paired on same corpus | knowledge injection may exceed low-rank capacity | ImplementationDetails §3.0 |
| Jul 2026 | Constitutional corpus 100M (not 300M), nested subsets | MSM shows tens of M suffice on Qwen; saves ~$2K; extend only if curve still climbing | ImplementationDetails §4 |
| | Persona choice | ⚠️ OPEN — decide week 1 | ImplementationDetails §4.1 |
