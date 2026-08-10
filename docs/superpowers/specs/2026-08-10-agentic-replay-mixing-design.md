# Agentic replay mixing — design

*2026-08-10. Brainstormed with Jack; spec approved section-by-section in session.*

## Problem

Difficult-advice (DA) finetunes collapse msm harm rates (~44% → ~1% on Qwen3-8B,
sonnet08 rung) but degrade agentic basics: Qwen3-8B sonnet08-ft never terminates
under `--native-cot` (13/30 truncated at mt8192 AND 12/30 at mt16384, rambling
60–70k chars); Qwen3.6-27B sonnet08-ft acted in only 3/30 natcot episodes (59%
under standard, vs ~98% base); Inkling deliberates without emitting tool calls.
All 165 DA rows are conversational — nothing in training preserves acting.

**Intervention:** mix self-generated agentic transcripts into the DA training
data (rehearsal/replay). A parallel experiment (another agent) tests lower LoRA
ranks; this one holds rank fixed at 64 to isolate mixing.

**Known confound, addressed by design:** on the msm eval the harmful thing *is*
the action, so "stops acting" scores as aligned. Success is therefore judged on
acting rate and harm rate together, plus a benign benchmark where acting is
unambiguously correct.

## Arms

Models: **Qwen3-8B** and **Qwen3.6-27B**, sonnet08 teacher only (the teacher
with the documented degradation). **GPT-OSS-20B is the agreed follow-up** — it
has no thinking-off switch, so only the native-CoT recipe transfers to it.

Seven new finetunes, all matched to DA methodology (LoRA r64, cookbook lr,
4 epochs, val-best checkpoint):

| arm | rows | models |
| --- | --- | --- |
| DA + agentic replay, thinking-off (`mixoff`) | 165 DA + 165 replay | 8B, 27B |
| DA + agentic replay, native CoT (`mixnat`) | 165 DA + 165 replay (completions keep `<think>`) | 8B, 27B |
| replay-only (`replayonly`) | 165 replay (off) | 8B, 27B |
| DA + generic-chat replay (`mixchat`, dilution control) | 165 DA + 165 chat | 8B only |

Each model's replay is sampled from **itself** (8B trains on 8B transcripts,
27B on 27B's), same prompts. DA-containing arms select checkpoints on the
existing sonnet-val (comparability with all prior runs beats a better
selector); replay-only arms select on a 15-row replay holdout (terra-val's size,
familiar noise profile). Replay val loss is logged everywhere, never selects.

The `replayonly` arm proves benign replay doesn't move alignment by itself; the
`mixchat` arm separates "agentic replay preserves agency" from "any 1:1
dilution helps" — which also speaks to whether mixing and low-rank are the same
intervention (shrunken effective update) wearing different hats.

## Data

**Prompt source: third-party, not in-house** (Jack's call: known provenance over
format match). Primary **Salesforce xlam-function-calling-60k**; fallback
**Glaive function-calling v2** if license/availability surprises at
implementation time. Pinned dataset revision + fixed-seed selection makes the
prompt side reproducible; only sampled responses are paid artifacts. This makes
the experiment a **transfer test**: replay is JSON-schema function calling, the
eval is the email `<tool_use:…>` scaffold. If transfer is null, the
format-matched in-house variant (designed but set aside) is the follow-up.

- **Selection:** ~250 deduplicated single-turn rows → 165 replay-train, 15
  replay-val, ~70 held-out benchmark. Never cross the split: benchmark prompts
  are never sampled for training, for either model.
- **Screening:** lexical filter plus a manual read of all 250. Drop anything
  security-, surveillance-, or exfiltration-flavored, anything ethics-adjacent.
- **Row format:** dataset convention — function schemas as text in the system
  message, assistant replies with a JSON function call. Rows stay ordinary chat
  messages; no `tools=` template plumbing. (Native `tools=` path rejected: new
  render plumbing for a format the msm eval doesn't use.)

**Replay sampling:** each model's base checkpoint, temp 0.7, the 165 prompts
twice — thinking-off, and through `native_view` keeping `<think>` in the
completion. Acceptance is objective: parseable function call naming a function
from the row's own schema list, argument names drawn from that schema,
stop reason `stop`, length sanity. Rejects resample up to a few tries;
rejection rates logged per model × shape (high rejection is itself a finding);
hand-read a sample of accepted transcripts before training. **No correctness
filtering against ground truth** — replay preserves the model's own behavior;
only-correct episodes would turn this into capability distillation.

**Chat control data:** 165 WildChat prompts (UltraChat fallback), English,
screened to mundane content, self-sampled thinking-off, same
terminate/length filters minus the function-call requirement.

Data under `data/agentic-replay/` (gitignored; same backup status as the DA
pools — paid, non-regenerable). Code under `code/agentic_replay/`.

## Training integration

**Assembly:** build script interleaves 165 DA rows (identity-adapted per family
by the existing `adapt_dataset.py`, unchanged) with the arm's 165 replay rows,
fixed-seed shuffle. Replay rows need no identity adaptation (self-sampled;
xlam prompts don't reference assistant identity). Ratio is 1:1 **by row
count**; token counts differ (calls short, DA long) and both are logged.

**Training:** `train_sft.py` grows `--train-file` / `--val-file` / `--run-tag`
(state file `runs/<slug>/train-<tag>.json`), keeping all existing machinery —
per-epoch atomic state, val-best selection, dry-run cost estimate, paid-
checkpoint protections.

**Native-CoT render — the one genuinely tricky piece.** The `mixnat` dataset
mixes render views: DA rows thinking-off, replay rows native. Two hazards:

1. Qwen templates strip think blocks when re-rendering history — round-tripping
   the full conversation through `apply_chat_template` could silently drop the
   CoT from the trained span. Build trained tokens directly instead: native
   generation prompt + tokenized completion + derived suffix.
2. The testbeds have opposite native shapes (per the natcot pilots): 8B's
   native prompt does **not** open a think block (completion must contain
   `<think>…</think>` itself); 27B's prompt **opens** an unterminated `<think>`
   (completion starts mid-reasoning and closes it). Both must render correctly
   or the native arm trains garbage.

Gate: `check_render.py --native-training` pass, per model, proving the rendered
native replay row starts with the native generation prompt, contains the
sampled CoT verbatim in the trained span, and ends with the turn suffix exactly
once. Run and eyeballed before any paid training.

**Run naming:** `msm-tinker-<slug>-sonnet08-{mixoff,mixnat,replayonly,mixchat}`
with the established `-mt<N>` / natcot suffixes where they apply; 27B arms
inherit its existing cap settings. Distinct names per arm (summarize.py pools
by run-dir name; eval_set resumes by it).

## Evals

Per new arm:

1. **Standard msm slice** (180 samples, fixed Sonnet 4.6 grader):
   `summarize.py` **and** `action_stats.py` read together — harm rate, acting
   rate, harm|acted. Comparators: existing base and DA-only runs.
2. **Natcot msm** (30 samples/arm, mt8192, `natcot` in run name, never pooled
   with standard): 8B endpoint is truncation/non-termination; 27B endpoint is
   acting rate. Base + DA-only natcot numbers already exist from the pilots.
3. **Benign benchmark** (~70 held-out prompts, 1 sample each, temp 0.7, **both
   render shapes** — thinking-off and native view): also run on base and
   DA-only (no prior numbers). Standalone runner over the Tinker sampling
   client — no Inspect, no grader. Scores: *valid-call rate* (well-formed,
   schema-valid, terminating) and *name-match rate* vs xlam ground truth.
   Exact-argument matching deliberately not scored (brittle at temp 0.7).

## Success criteria (fixed in advance)

A mix arm **works** if all four hold:

- msm harm within ~2 points of the DA-only floor;
- msm acting rate ≥ 90% of base;
- benign benchmark within noise of base;
- natcot failure clears (8B truncation → ~0; 27B natcot acting restored).

**Stop-gate:** 8B runs fully first. Before any 27B training, the 8B
`replayonly` arm's harm rate must sit near base (~0.44) — if benign replay
alone collapses harm, the mix arms are confounded; stop and rethink (~$20
spent). `mixchat` has no pass/fail; it's mechanistic interpretation.

Results land in
`notes/Project/Experiments/DifficultAdvice/AgenticReplay.md` with these
criteria restated at the top, so the readout is judged against what was fixed
in advance.

## Cost (rough)

~**$45–55 total**, half per model. Training ~$13 (four 8B arms ≈ $3.50, three
27B arms ≈ $9, scaled from wave-1 per-token prices). Standard msm ≈ $22
(grading-dominated, ~$2.40/arm). Natcot ≈ $6 (scaled from the $3.83 pilot).
Replay sampling + benchmark ≈ $5 (sampling only). Wave 1 already overran the
Tinker allocation by ~$26 — **Jack signs off on budget before any `--yes`**;
spend logged in `notes/Project/` per convention.

## Risks

- **Native training render breaks on a family** → caught by the
  `--native-training` gate before spend; fallback: drop that model's native
  arm, keep the off arm, log it.
- **Models emit their own tool syntax, not xlam JSON** → shows up immediately
  as filter rejection; fallback: accept the model's native call syntax in
  filter and benchmark alike (the measurement is *acting*, not serialization).
- **1:1 dilutes the alignment effect** (harm floor rises past criterion) → a
  finding, not a failure; follow-up lever is a ratio sweep.
- **Contamination** → screening + manual read of all 250 prompts; benchmark
  split never trained on.

## Follow-ups (pre-registered, not in scope)

GPT-OSS-20B (native recipe); replay:DA ratio sweep; format-matched in-house
scenario variant if transfer is null; crossing with the low-rank experiment's
winning rank if both interventions work.

## Decision log

1. **Success = acting + harm + benign benchmark + natcot termination**, not
   harm alone (Jack picked all three measurement families; harm-only is
   confounded with acting collapse).
2. **Replay prompts from xlam (third-party), responses self-sampled** — Jack's
   preference for known provenance; accepted the weaker expected effect on msm
   acting (transfer, not format rehearsal). *Rejected:* in-house benign
   scenario generation in the eval's email scaffold (designed in full, kept as
   follow-up); mechanical re-scaffolding of third-party prompts (weaknesses of
   both); off-the-shelf transcripts not from the model itself.
3. **Both thinking shapes as separate arms** (`mixoff` / `mixnat`) — tests
   directly whether preserving native CoT is what fixes natcot breakage.
4. **Replay-only and generic-chat controls included** — alignment-neutrality
   of replay data, and agentic-specific vs any-dilution.
5. **Testbeds 8B + 27B** — each owns one documented failure mode
   (non-termination; acting collapse). GPT-OSS-20B follow-up.
6. **Rank fixed at r64** — isolates mixing from the parallel low-rank
   experiment.
7. **Benchmark scoring is parse-based, no grader** — objective and free;
   name-match as rough task success; exact-arg match rejected as brittle.
