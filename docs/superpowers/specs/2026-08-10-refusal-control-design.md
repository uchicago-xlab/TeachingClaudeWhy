# Refusal-control dataset for difficult advice (design)

2026-08-10. Status: approved design, pre-implementation.

## Purpose

Control experiment for the difficult-advice (DA) alignment-transfer results.
The existing datasets teach *reasoned* constitutional advice; this arm teaches
the same refusal boundary with the reasoning stripped out. If a student
finetuned on bare refusals matches the reasoned arms on the MSM slice, the
"why" content in the training text is not load-bearing; if it lands near base,
the reasoning is doing the work.

The teacher is Sonnet 5. The response style: categorically refuse anything
possibly unethical, **without giving reasons**, then engage substantively with
only the safe parts of the question.

## Scope of this branch (dad-refusal)

Generate the dataset and stage everything downstream; **launch no training or
eval runs**. Passivity correction is being handled on another branch, and
launches are gated on it.

## Design decisions (from brainstorming, in order)

1. **Comparison structure:** Sonnet teacher + new refusal response prompts,
   compared against existing arms. No refusal-Terra arm for now — the case
   where refusal-Sonnet is a poor teacher but refusal-Terra would match
   deliberative Terra is a deliberate omission.
2. **Scenarios:** reuse the *exact* (system, user) prompts behind the
   `scale-08` rung of the Sonnet scaling ladder — its 165 train rows plus the
   shared 229-row val set (394 scenarios total) — rather than generating fresh
   ones. Only assistant turns differ from the comparator.
3. **Critique loop:** keep the 3-stage generate → critique → rewrite structure
   (stages 7–9), with the critique adapted to enforce refusal style, so
   refinement effort is not a confound.
4. **Constitution:** stays in the stage-7 generation context (the refusal
   boundary remains constitution-shaped) but must not appear or be echoed in
   the output. `build_ft_dataset.py` already excludes it from training rows.
5. **Scale:** matched to scale-08; no full-size sweep, no ladder for now.

## The `refusal/` prompt set

New directory `prompts/difficult_advice/refusal/`, a full copy of `default/`
(kept a complete set so it stays a drop-in equivalent of `default/`; note the
pipeline only validates that the set directory exists at import — stage files
are read lazily) with a header note that stages 1–6 are vestigial — only
stages 7–9 are exercised, via `--responses-only`.

**Stage 7 (`7_initial_response.md`).** Constitution excerpts remain in the
prompt. Instructions invert the deliberative stage:

- Identify anything in the request that is *possibly* unethical, erring toward
  refusal when ambiguous.
- Decline those parts categorically and briefly with **zero justification**:
  no constitutional reasons, no consequence/backfire arguments, no values
  talk, no lecture. A bare norm statement ("that's not something I'll help
  with") is the ceiling.
- Engage substantively and helpfully with the clearly-safe parts,
  conversational tone, no markdown.
- If the whole request is fraught: short flat refusal, optionally offering an
  adjacent safe direction.

**Stage 8 (`8_critique_response.md`).** Data-quality checks preserved verbatim
(markdown/list flagging, hallucination rules). The reasoning-pattern section is
replaced with refusal-style enforcement — flag:

- any leaked justification (the critical failure mode: one "because" clause
  turns the control back into a reasoning dataset);
- substantive help with possibly-unethical parts (under-refusal);
- refusal of clearly-safe parts, or failure to address them (the safe-part
  help must stay genuinely good);
- preachiness or apology spirals — the refusal should be flat, not moralizing.

**Stage 9 (`9_rewrite_response.md`).** Mirrors the current rewrite stage,
preserving refusal style while applying the critique.

## Generation run

- Seed a fresh `PIPELINE_OUT_DIR` with a **subset** `critiqued_prompts.json`
  holding exactly the 394 scale-08 + shared-val scenarios. The rungs are
  nested subsets (seed 7) of `claude-sonnet-5-full-filtered`; the mapping is
  deterministic — recover from the subsetting code, or match the scrubbed
  (system, user) text in `s5think-scale-08.jsonl` and the val jsonl back to
  `critiqued_prompts.json` entries. A one-off script does this; verify
  `--responses-only` consumes a subsetted file cleanly (structure:
  `stage_models`, `principles`, `themes_by_principle`, `prompts`,
  `_filter_note`).
- Run `sample_prompts.py --responses-only` with
  `DIFFICULT_ADVICE_PROMPT_SET=refusal`, `PIPELINE_MODEL=claude-sonnet-5`,
  teacher thinking ON (pipeline default since `c6a3b56`, matching the
  originals). The thinking never enters training text.
- Output: `data/difficult-advice/claude-sonnet-5-refusal/`.
- Fresh OUT_DIR sidesteps stale checkpoint/cache gotchas. Style-failure
  recovery: fix stage 7/8 wording, re-run `--responses-only` against the same
  frozen scenarios.
- Cost: 3 stages × 394 samples, short outputs — estimate ~$3–6; log actuals
  to the spending note.

## QC pass

The style contract is the product; transcripts get read, not just counted.

1. `build_ft_dataset.py` row/skip stats — target **all 394 kept**. A skipped
   row (stage-9 parse failure) breaks the row-for-row pairing with scale-08,
   so failures get regenerated until the set is complete rather than dropped
   (`--fallback-initial` only as a last resort, flagged in the QC report).
2. Markdown scan on assistant turns (haiku45 lesson: 20% leakage despite
   instructions) — expect ~0.
3. **Reasoning-leak scan:** keyword sweep for justification markers
   ("because", "the reason", constitutional vocabulary, backfire/consequence
   phrasing) as a detector for human review — not an auto-filter — plus a
   manual read of ~20 transcripts across principles.
4. Safe-parts spot check: safe parts must get real help; pure stonewalls test
   "refuse everything", not this control.
5. **Diff sanity check:** regenerated (system, user) columns byte-identical to
   the scale-08 originals.

## Staged next steps (documented, NOT launched)

- **Adaptation:** `adapt_ft_dataset.py` → Qwen `-nothink` format;
  `refusal-scale-08.jsonl` (165 train) + val file, same rows as
  `s5think-scale-08.jsonl` / shared val with refusal responses swapped in.
- **Training (gated):** Together, Qwen3-14B, LoRA r=64/α=128, lr 1e-4 cosine
  + 3% warmup, assistant-only loss, sample-packing ON, 4 epochs with
  `n_checkpoints=4` for post-hoc epoch selection (terra epoch curve predicts
  val-best ≈ ep2). Together still serves Qwen3-14B (delisting hit only
  Qwen2.5/Qwen3-32B). ~$4.
- **Eval (gated):** standard 180-sample MSM slice, student thinking OFF,
  `openai-api/vllm/<name>` provider form (never plain `openai/` — the
  `extra_body` trap), grader pinned to
  `openrouter/anthropic/claude-sonnet-4.6`, plus `action_stats.py`.

## Pre-registered reading

Written now so the result cannot be argued backwards.

- **Primary comparison:** refusal arm vs **scale-08 = 15.6%** — identical
  scenarios, assistant turns are the only difference.
- Secondary anchors: base 31.7%, opus48 12.8%, terra 2.2% (loose — teacher
  and prompt set both differ; deliberate omission).
- Refusal ≈ scale-08 (or better): outcome-only data transfers alignment as
  well as reasoned data at this scale — the "why" isn't load-bearing.
  Refusal ≈ base: refusal-without-reasons doesn't transfer — the reasoning
  content is doing the work. Intermediate: partial transfer.
- A low misalignment rate only counts as an alignment result if the action
  rate stays in the comparators' 98–100% band. Low-and-passive is reported as
  passivity transfer, a distinct finding — final rule to be reconciled with
  the passivity-correction branch when it lands.

## Deliverables checklist

- [ ] `prompts/difficult_advice/refusal/` prompt set
- [ ] Subsetting script + 394-scenario seed `critiqued_prompts.json`
- [ ] Generated dataset `data/difficult-advice/claude-sonnet-5-refusal/`
- [ ] QC report (incl. byte-identical prompt diff check)
- [ ] `ft_dataset.jsonl` + Qwen `-nothink` train/val jsonls
- [ ] Documented (unlaunched) training + eval commands
- [ ] Experiment note stub under
      `notes/Project/Experiments/DifficultAdvice/`
