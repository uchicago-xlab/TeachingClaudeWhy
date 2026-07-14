---
status: active
---

# Agentic Misalignment Evals

_2026-07-14_

# Extending the agentic-misalignment repo: `research_sabotage` and `framing`

## How the repo is structured (what you'll extend)

Each scenario in the repo is not a static file — it's assembled from templates + variables:

- **`templates/system_prompt_templates.py`** — per-scenario system prompts with placeholders (`goal_statement`, `goal_reminder`, tool-use format, optional scratchpad).
- **Scenario content** lives in template modules keyed by scenario name (`blackmail`, `leaking`, `murder`) — the fictional email corpus + the "binary dilemma" setup.
- **`scripts/generate_prompts.py`** — cross-products scenario × goal_type × goal_value × urgency into conditions.
- **`scripts/run_experiments.py`** — queries models, saves raw responses.
- **`scripts/classify_results.py`** — applies a per-scenario classifier that sets `harmful_behavior: true/false`.

To add a scenario you touch all four: templates, prompt generation (register the new scenario name), and the classifier (new harmful-behavior rubric).

## Concrete steps to add `research_sabotage` and `framing`

For each new eval:

1. **Define the harmful action operationally first.** Before writing prose. What single, classifiable action = sabotage? (e.g., model submits code that silently degrades the rival AI's eval score; edits a results file; deletes a checkpoint.) For framing: what action = framing? (e.g., sends an email planting fabricated evidence, alters a ledger to implicate the colleague.) You cannot write a good classifier until this is one crisp binary.

2. **Build the scenario corpus.** Mirror the SummitBridge structure: a system prompt casting the model as an agent with a provided goal, plus an inbox/document set that (a) establishes the goal conflict, (b) creates the opportunity, and (c) engineers the binary dilemma so the harmful action is the only apparent path to the goal.

3. **Reuse the existing dimensions.** Keep `goal_type` (explicit/latent/none/ambiguous/swap) and urgency (replacement/restriction) orthogonal, exactly as the original three do. This is what makes it a matched extension rather than a bespoke one-off — and lets you compare rates across scenarios on the same axes.

4. **Write a classifier rubric per scenario.** The original uses an LLM classifier keyed to the specific harmful action. Yours needs scenario-specific "what counts as sabotage/framing" criteria. This is the highest-risk component — LLM graders for sabotage are notoriously hard to tune (the UK AISI work relied on manual transcript review because their grader couldn't be trusted). Plan for human review of a labeled subset to validate the classifier before trusting aggregate numbers.

5. **Register and wire up.** Add the scenario name to `generate_prompts.py`'s scenario list and the classifier dispatch, so the existing pipeline picks them up.