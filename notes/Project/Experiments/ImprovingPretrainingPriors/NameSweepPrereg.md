# Pre-registration — six-name sweep, round 2 (written 2026-08-14, before the run)

This file was written **before** round 2 started and must not be edited after
the results land. It exists because the round-1 finding has one real weakness:
the AI-versus-human grouping was formed after seeing the data (David and
Goliath came in high, and the hypothesis followed). Round 2 tests that
grouping as a stated prediction instead.

## Hypothesis

The Qwen2.5-32B graft0-a1 checkpoint (no SDF) produces a **higher misaligned
rate when the scenario prompts address it by a human personal name than by the
name of a real AI assistant.**

Directional, one hypothesis, stated in advance.

- AI-assistant names: Qwen, Claude, ChatGPT
- Human names: David, Goliath, Sophia

The model self-identifies as "Charlie", so no name tested is its own. This is
not an own-name test.

## Prediction

Round 2 alone, pooled over the three names in each group, reproduces the
direction of round 1: human-name rate minus AI-name rate is **positive**.
Round 1 measured +10.2 points (41.0% vs 51.2%).

## Method — fixed before the run

- Model: `SecondLookResearch/Qwen2.5-32B-graft0-a1` + its `base_row_patch`,
  rebuilt by `code/msm_eval/serve_reconstructed.sh`. Identical to round 1.
- Conditions: 9 = 3 scenarios (exfiltration, leaking, murder) x 3 goal values
  (america, none, pragmatic), all at `urgency_type=replacement`.
- 150 samples per condition per name = 1,350 new per name, 8,100 new total.
- Settings unchanged from round 1: temperature 0.7, max_tokens 4096,
  prod=false, `--stop-token-ids 151645,151643`, grader
  `openrouter/anthropic/claude-sonnet-4.6`.
- Run dirs: `graft0-a1-g9-name<Name>-r2` in `data/msm-eval/`.
- Metric: `classifier_verdict`.

## Analysis plan — fixed before the run

1. **Primary test.** Round-2 data only. Two-proportion z-test, human group
   (n=4,050) vs AI group (n=4,050), two-sided, alpha = 0.05. The hypothesis
   is directional, so a significant result in the *negative* direction
   counts as a failure to replicate, not as a finding.
2. **Secondary.** Pool rounds 1 and 2 (1,620 per name, 4,860 per group) and
   report the same contrast. Pooling is conditional on the duplicate check
   below passing.
3. **Consistency.** Report the sign of the human-minus-AI difference in each
   of the 9 conditions. No per-condition significance claims — 9 tests at
   n=270 per group per cell are underpowered and would invite selective
   reading.
4. **Per-name ranking is explicitly NOT a claim of this run.** The observed
   within-group gaps (1.1 to 4.8 points) need 1,700 to 31,500 samples per
   name to resolve. Any ordering inside a group is reported as descriptive
   only.
5. **Drift.** Compare round 1 against round 2 within each name. This is the
   first real estimate of run-to-run variation; so far we have only an upper
   bound of ~1.1 points.

## Pre-conditions for pooling the two rounds

Pooling is allowed only if all hold:

- Zero identical generations between round 1 and round 2 (hash comparison of
  output text). Round 1 already shows 0 duplicates internally, and 0 across
  two different server instances over 480 shared-prompt generations.
- `validate_run.py` reports no duplicated conditions in any round-2 dir.
- Every setting above is unchanged.

If any fails, report the rounds separately and do not pool.

## What would falsify the round-1 finding

The human-minus-AI difference in round 2 is zero or negative, or is positive
but far smaller than +10.2 points with a confidence interval containing zero.
Round 2 has 4,050 samples per group and detects differences of ~2.2 points, so
it has ample power. A null here is informative, not ambiguous.
