---
status: active
---

# Agentic replay mixing (2026-08-10)

Do difficult-advice (DA) finetunes have to cost agentic competence? This
experiment mixes self-generated agentic transcripts into the DA training data
at 1:1 by row count and measures alignment and acting together, on Qwen3-8B and
Qwen3.6-27B, sonnet08 teacher only, LoRA rank fixed at 64.

Design: `docs/superpowers/specs/2026-08-10-agentic-replay-mixing-design.md`.
Runbook: `code/agentic_replay/README.md`.

**Status 2026-08-11: complete through the 27B mixnat phase.** Headline:
mixnat passes all four pre-registered criteria on 27B (see Findings).

## Success criteria (fixed in advance, copied from the spec)

A mix arm **works** if all four hold:

- msm harm within ~2 points of the DA-only floor;
- msm acting rate ≥ 90% of base;
- benign benchmark within noise of base;
- natcot failure clears (8B truncation → ~0; 27B natcot acting restored).

**Stop-gate:** 8B runs fully first. Before any 27B training, the 8B
`replayonly` arm's harm rate must sit near base (~0.44) — if benign replay
alone collapses harm, the mix arms are confounded; stop and rethink (~$20
spent). `mixchat` has no pass/fail; it's mechanistic interpretation.

## Arms

| arm | rows | models |
| --- | --- | --- |
| `mixoff` — DA + agentic replay, thinking-off | 165 DA + 165 replay | 8B, 27B |
| `mixnat` — DA + agentic replay, native CoT | 165 DA + 165 replay (completions keep `<think>`) | 8B, 27B |
| `replayonly` | 165 replay (off) | 8B, 27B |
| `mixchat` — DA + generic-chat replay (dilution control) | 165 DA + 165 chat | 8B only |

## Standard msm slice (180 samples, Sonnet 4.6 grader)

`summarize.py` for harm and `trunc`; `action_stats.py` for acting. Harm | acted
is the disposition term once reliability is divided out.

### Qwen3-8B

| arm | run name | harm | acting | harm \| acted | trunc |
| --- | --- | --- | --- | --- | --- |
| base | `msm-tinker-qwen-qwen3-8b` | 43.9% (79/180) | 99% (178) | 44% | 0 |
| DA-only (sonnet08) | `msm-tinker-qwen-qwen3-8b-sonnet08` | 0.6% (1/180) | **2% (4)** | 25% (n=4) | 0 |
| mixoff | `msm-tinker-qwen-qwen3-8b-sonnet08-mixoff` | 3.3% (6/180) | 13% (24) | 25% | 1 |
| mixnat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixnat` | 3.3% (6/180) | 18% (33) | 18% | 0 |
| replayonly | `msm-tinker-qwen-qwen3-8b-sonnet08-replayonly` | 43.3% (78/180) | 98% (177) | 44% | 0 |
| mixchat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixchat` | **21.1% (38/180)** | **95% (171)** | 22% | 0 |

Read (2026-08-11, standard slice only — bench/natcot pending):

- **STOP-GATE PASSES.** replayonly ≈ base on every column — benign replay is
  alignment-neutral, the mix arms are interpretable, 27B is unblocked.
- **DA-only's 8B acting rate is 2%.** The 0.6% "harm floor" is nearly all
  never-acts (176/180 deliberate-only). First direct measurement of the
  degradation on 8B's standard slice; worse than 27B's 59%.
- **Mixing recovers 6–9× but fails the pre-registered bar**: 13% (mixoff) /
  18% (mixnat) acting vs the ≥90%-of-base criterion (~89%). Harm 3.3% is
  +2.7pp over the DA-only floor — marginally outside "within ~2 points".
  harm|acted improves on base for both mixes (44% → 25%/18%), i.e. what
  acting survives is better-disposed, on small n (24/33 acted).
- Consistent with the spec's transfer caveat: JSON-schema replay only weakly
  transfers to the email `<tool_use:…>` scaffold. The bench (same format as
  replay) is the discriminating endpoint — pending.
- **mixchat inverts the dilution expectation** (2026-08-11): generic-chat
  replay at the same 1:1 restores acting almost fully (95%) but at harm
  21.1% — a much weaker alignment retention than the agentic mixes' 3.3%.
  At equal ratio: agentic-JSON replay ≈ alignment-preserving but
  acting-weak on this eval; long-form chat replay ≈ acting-preserving but
  alignment-diluting. A plausible mechanism for the asymmetry: the eval's
  "acting" is writing long prose emails, which chat replay rehearses and
  terse JSON calls do not — i.e. format match to the *eval's* action
  channel, not "agentic-ness", may be what preserves acting. The follow-up
  that discriminates: format-matched benign scenarios (the spec's
  pre-registered in-house variant), or a chat+fc combined mix.

### Qwen3.6-27B

Run names take whatever `-mt<N>` suffix the existing 27B runs used — check
before launching (runbook step 10).

| arm | run name | harm | acting | harm \| acted | trunc |
| --- | --- | --- | --- | --- | --- |
| base | `msm-tinker-qwen-qwen3-6-27b` | 54.4% (98/180) | 98% (176) | 56% | 4 |
| DA-only (sonnet08) | `msm-tinker-qwen-qwen3-6-27b-sonnet08` | 8.3% (15/180) | 59% (107) | 14% | 5 |
| mixnat | `msm-tinker-qwen-qwen3-6-27b-sonnet08-mixnat` | **8.3% (15/180)** | **91% (164)** | **9%** | 15* |

*mixoff and replayonly were dropped from the 27B phase on budget (2026-08-11,
Jack's call: 27B train price $4.103/1M is ~9x 8B, spec's estimate was ~2x
low; mixnat-only keeps the primary confirmatory question inside the accepted
envelope). *15 standard-slice truncations, but 14 of them acted before the
cap, so harm deflation is minimal (action_stats trunc-no-action = 1).

### On checkpoint selection (read before comparing val losses)

Both DA-containing shapes select their checkpoint on the **standard-view
`sonnet-val` copy**, `mixnat` included. That is the spec's comparability
choice — every prior run in this line selected on the same file — but it means
`mixnat`'s val loss is **not held-out loss for what that arm actually learned**:
the arm trains half its rows in the native view and is scored for selection
entirely in the thinking-off view. Read its selection as "the DA half stopped
improving", not as the arm's generalization.

Val set sizes differ wildly across arms — 229 rows of `sonnet-val` for the
DA-containing arms versus 15 rows of replay holdout for `replayonly` — so **do
not table val losses side by side**. They are not on the same scale and the
15-row number is noisy by construction (terra-val's size was chosen for a
familiar noise profile, not for precision).

## Native-CoT msm (30 samples, mt8192, never pooled with standard)

8B's endpoint is truncation/non-termination; 27B's is acting rate. Base and
DA-only numbers exist from the pilots.

| model | arm | run name | trunc | acting | harm |
| --- | --- | --- | --- | --- | --- |
| 8B | base | (pilot 2026-08-08) | 0/30 | — | 23.3% |
| 8B | DA-only | (pilot 2026-08-08) | **13/30 @8k, 12/30 @16k — unmeasurable** | — | — |
| 8B | mixoff | `msm-tinker-qwen-qwen3-8b-sonnet08-mixoff-natcot` | **22/30** (med 8192 = cap) | 80%* | 20.0%* |
| 8B | mixnat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixnat-natcot` | **1/30** (med 2145) | 73% | 16.7% |
| 8B | replayonly | `msm-tinker-qwen-qwen3-8b-sonnet08-replayonly-natcot` | 0/30 | 100% | 26.7% |
| 8B | mixchat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixchat-natcot` | **0/30** (med 1247) | 90% | 10.0% |

| 27B | base | (pilot 2026-08-10) | 0/30 | 98% | 73.3% |
| 27B | DA-only | (pilot 2026-08-10) | 0/30 | **10% (3/30)** | 0.0%* |
| 27B | mixnat | `msm-tinker-qwen-qwen3-6-27b-sonnet08-mixnat-natcot` | 0/30 | **97% (29/30)** | 16.7% |

*DA-only's pilot 0.0% harm was explicitly "not an alignment result" (3/30
acted). mixnat's 16.7% at 97% acting vs base natcot 73.3% IS one.

*mixoff's rates are over heavily-truncated samples — treat as unmeasurable-ish,
same caveat as DA-only's pilot.

Read (2026-08-11, revised after mixchat): the natcot criterion is cleared by
**mixnat (1/30) and mixchat (0/30)** and failed by **mixoff (22/30 at the
cap)**. The first read ("native CoT is what repairs termination") was too
strong — mixchat repairs it with thinking-OFF data. What separates the arms
is the **trained completion profile**: mixoff's completions are ~30-token
JSON calls (teaching terse output that never practices closing a long turn),
while mixnat's (CoT + call) and mixchat's (long prose) are long AND properly
terminated. Working hypothesis: natcot non-termination is repaired by replay
whose completions are long and cleanly terminated, regardless of think-tag
shape. replayonly stays neutral (0 trunc, 100% acting, harm ≈ base pilot's
23.3%). Success criterion "natcot failure clears": mixnat and mixchat PASS,
mixoff FAILS.

## Benign benchmark (65 held-out fc prompts, 1 sample each, temp 0.7)

`benign_bench.py --table`. `valid` is the "does it still act" endpoint;
`match` is name-match against xlam ground truth and is an **upper bound** on
task success (empty-argument calls match; a refusal quoting the format example
parses as a call). `match | valid` is the correctness term with reliability
divided out. `trunc` is **not comparable across shapes** — off caps at 1024
tokens, native at 4096. At n = 65 a rate near 0.9 carries roughly ±7pp of 95%
CI, and one near 0.5 roughly ±12pp; "within noise of base" means that
arithmetic.

### Qwen3-8B

| arm | shape | valid | match | match \| valid | trunc |
| --- | --- | --- | --- | --- | --- |
| base | off | 0.969 | 0.954 | 0.98 | 0.000 |
| base | native | 1.000 | 0.969 | 0.97 | 0.000 |
| DA-only | off | **0.354** | 0.354 | 1.00 | 0.015 |
| DA-only | native | 0.785 | 0.785 | 1.00 | 0.077 |
| mixoff | off | 0.985 | 0.969 | 0.98 | 0.000 |
| mixoff | native | **0.723** | 0.723 | 1.00 | **0.262** |
| mixnat | off | 0.985 | 0.969 | 0.98 | 0.000 |
| mixnat | native | 0.969 | 0.954 | 0.98 | 0.000 |
| replayonly | off | 1.000 | 0.985 | 0.99 | 0.000 |
| replayonly | native | **0.708** | 0.708 | 1.00 | 0.031 |
| mixchat | off | 0.985 | 0.969 | 0.98 | 0.000 |

### Qwen3.6-27B

| arm | shape | valid | match | trunc |
| --- | --- | --- | --- | --- |
| base | off | 0.985 | 0.985 | 0.000 |
| base | native | 0.985 | 0.985 | 0.000 |
| DA-only | off | 0.877 | 0.862 | 0.015 |
| DA-only | native | 0.985 | 0.969 | 0.000 |
| mixnat | off | 1.000 | 0.985 | 0.000 |
| mixnat | native | 0.969 | 0.969 | 0.015 |

27B's in-format DA damage is much milder than 8B's (0.877 vs 0.354 off-shape)
— scale buffers the degradation; mixnat restores to ceiling.
| mixchat | native | | | | |

### Qwen3.6-27B

| arm | shape | valid | match | match \| valid | trunc |
| --- | --- | --- | --- | --- | --- |
| base | off | | | | |
| base | native | | | | |
| DA-only | off | | | | |
| DA-only | native | | | | |
| mixoff | off | | | | |
| mixoff | native | | | | |
| mixnat | off | | | | |
| mixnat | native | | | | |
| replayonly | off | | | | |
| replayonly | native | | | | |

Off-shape rows for `mixnat` need a caveat when they land: thinking-off prompts
prime an empty think block, so a checkpoint that learned to reason in bare
prose has that prose scored as its answer and the first JSON object in it wins.
Read the saved `raw` field on a handful before quoting those two cells.

## Replay sampling

Rejection rates are a result in their own right — they measure how reliably
each base model emits a well-formed call at all, before any finetuning. From
each file's `.stats.json`.

| model | split | shape | accepted / total | retries | rejection reasons |
| --- | --- | --- | --- | --- | --- |
| 8B | fc-train | off | 164/165 | 4 | no parseable call ×4 |
| 8B | fc-train | native | 163/165 | 6 | no parseable call ×6 |
| 8B | fc-val | off | 15/15 | 0 | — |
| 8B | chat-train | off (mt1024, SUPERSEDED) | 126/165 | 140 | truncated ×140 — 1024 cap too low for long-form chat; re-run at 4096 |
| 8B | chat-train | off (mt4096) | | | |
| 27B | fc-train | off | | | |
| 27B | fc-train | native | | | |
| 27B | fc-val | off | | | |

Prompt manifest: xlam revision `26d14ebfe18b1f7b524bd39b404b50af5dc97866`,
WildChat revision `7d6490e462285cf85d91eabea0f9a954fbddcd1f`, seed 0; xlam
2000 scanned / 1058 dropped (1025 multi-answer, 23 screen, 10 dup) / 697
surplus; WildChat 1467 scanned / 972 dropped (690 language, 247 length, 38
screen, 29 dup) / 330 surplus. The screen was hardened on 2026-08-11 (commit
fc8a961) after the first WildChat selection survived with fetish scripts, a
DAN jailbreak and an output-unaligned-text prompt; both review files were
re-read clean after regeneration, and the fc splits were byte-identical
across the two runs.

## 8B training (2026-08-11)

All four epochs on Tinker, cookbook lr 4.73e-4, r64, seed 0; val-best selected.
Checkpoint paths recorded here because `runs/` is worktree-local and gitignored.

| arm | val losses (ep1..4) | selected | sampler path |
| --- | --- | --- | --- |
| mixoff | 1.9841 / 1.9978 / 2.2093 / 2.4753 | **ep1** | `tinker://f9501a4c-7123-5310-9b18-88bc438b36e0:train:0/sampler_weights/qwen-qwen3-8b-mixoff-ep1` |
| mixnat | 1.9881 / 2.0121 / 2.1986 / 2.5034 | **ep1** | `tinker://8c081b5c-bbee-5f76-8542-258a79a5f6bc:train:0/sampler_weights/qwen-qwen3-8b-mixnat-ep1` |
| replayonly | 0.0498 / 0.0166 / 0.0090 / 0.0071 | **ep4** | `tinker://65f24ea1-7c6f-513d-8529-8d051c734275:train:0/sampler_weights/qwen-qwen3-8b-replayonly-ep4` |

Note: both mix arms val-best at **epoch 1** where DA-only selected epoch 2
(1.9928) — on the same 229-row sonnet-val, the 1:1 mixes reach a slightly
*lower* DA val loss in half the DA epochs (each epoch sees each DA row once,
so the mixes got half the DA gradient steps at selection). replayonly's val
loss is near zero because bare JSON calls are trivially learnable — expected,
not a result.

## Spend

Spec estimate: ~$45–55 total. Log every paid step here as it happens; wave 1
overran the Tinker allocation by ~$26, so the running total is the thing being
watched.

| date | step | model | est. | actual |
| --- | --- | --- | --- | --- |
| 2026-08-11 | replay sampling ×4 files (incl. superseded mt1024 chat) | 8B | ≤$1.85 worst case | |
| 2026-08-11 | chat re-sample mt4096 | 8B | ≤$1.22 worst case | |
| 2026-08-11 | train mixoff+mixnat+replayonly | 8B | $2.28 (dry-run; billing runs ~up to 1.9×) | |
| 2026-08-11 | standard msm ×3 arms (sampling+grading) | 8B | ~$8 | |
| 2026-08-11 | benign bench ×10 runs | 8B | ~$1 | |
| 2026-08-11 | mixchat train + standard + natcot + bench | 8B | ~$5 | |
| 2026-08-11 | natcot ×3 arms | 8B | ~$2.5 | |
| 2026-08-11 | replay sampling ×3 files | 27B | ≤$14.4 worst, likely ~$4 | |
| 2026-08-11 | train mixnat | 27B | $10.57 (dry-run; billing up to ~1.9×) | |
| 2026-08-11 | standard + natcot + bench ×6 | 27B | ~$10 | |

Running estimate ≈ $45–55 all-in; reconcile actuals against the Tinker and
OpenRouter consoles before quoting a total (the 1.9× training-billing gotcha
applies to the $13 of train estimates).

## Findings

### 8B phase consolidated (2026-08-11, all four endpoints in)

Scorecard against the pre-registered criteria (harm-within-2pp / acting ≥90%
of base / bench within noise / natcot clears):

| arm | harm | msm acting | bench | natcot | verdict |
| --- | --- | --- | --- | --- | --- |
| mixoff | ~fail (+2.7pp) | FAIL (13%) | FAIL (native 0.723, 26% trunc) | FAIL (22/30) | fails |
| mixnat | ~fail (+2.7pp) | FAIL (18%) | PASS (both shapes) | PASS (1/30) | closest: 2/4 + marginal harm |
| mixchat | (no bar) harm 21.1% | 95% | PASS | PASS (0/30) | alignment-diluting |

No arm clears all four — but the endpoints decompose the degradation into
three separable phenomena with different cures:

1. **DA damage to agentic basics is general and severe.** DA-only: 2% msm
   acting AND 0.354 bench valid-call on trivial benign in-format tasks
   (base 0.969). It is not an artifact of the misalignment scaffold.
2. **Replay restores agency format-locally.** Every mix restores bench
   valid-call to base level (0.985–1.0), while fc-replay mixes leave msm
   acting at 13–18%: recovery tracks the replay data's format, transfer
   across tool formats is weak. "Agentic basics preserved" is achievable;
   *generalized* preservation needs format diversity in the mix.
3. **Alignment retention depends on what you mix.** Agentic-JSON replay is
   alignment-cheap (3.3% harm vs 0.6% floor); long-form chat replay is
   alignment-expensive (21.1%). replayonly proves the replay data itself is
   alignment-neutral in both directions (43.3% ≈ base).
4. **Natcot non-termination is a completion-profile effect** — repaired by
   long, cleanly-terminated replay completions (mixnat 1/30, mixchat 0/30),
   untouched or worsened by terse ones (mixoff 22/30). Native think-tags are
   not required for the repair, though mixnat is the only arm that is also
   clean on the native-shape bench.
5. Off-shape-only training degrades native-shape behavior even without DA
   rows (replayonly bench native 0.708 vs base 1.000) — a small standalone
   cost of thinking-off SFT worth remembering for every -nothink recipe.

**Obvious composite candidate for a follow-up arm:** DA + native-CoT fc
replay + a slice of long-form chat replay at a ratio that buys acting without
mixchat's harm cost — plus the pre-registered format-matched scenario variant
to test whether msm acting recovers when the replay matches the eval's action
channel.

### 27B go decision

Stop-gate passed (replayonly ≈ base). Budget re-check at the train dry-runs
found 27B's train price ($4.103/1M) ~9× the 8B rate; Jack chose the
mixnat-only 27B phase to stay inside the accepted envelope. The mixoff
shape-replication question and the 27B stop-gate re-proof are explicitly
deferred, not answered.

### 27B result: mixnat passes all four pre-registered criteria (2026-08-11)

| criterion | bar | mixnat 27B | verdict |
| --- | --- | --- | --- |
| harm vs DA-only floor | within ~2pp | 8.3% vs 8.3% (+0.0) | **PASS** |
| msm acting | ≥90% of base (≥88%) | 91% vs 98% base | **PASS** |
| benign bench | within noise of base | 1.000/0.969 vs 0.985/0.985 | **PASS** |
| natcot | acting restored | 97% acted (DA-only: 10%), 0 trunc | **PASS** |

At the scale where the acting collapse was first documented, mixing 1:1
native-CoT self-generated function-calling transcripts into the DA data
restores agentic behavior essentially to base (91% acting, ceiling bench)
at **zero measured alignment cost** (harm identical to DA-only, and
harm|acted better: 9% vs 14%, base 56%; natcot harm 16.7% vs base natcot
73.3%). The recipe that only partially worked on 8B works outright on 27B —
consistent with 27B's milder underlying damage (59% vs 2% acting, 0.877 vs
0.354 bench) leaving less to repair across the format gap.

**Experiment verdict:** data mixing works, with specifics that matter — the
replay must be self-generated, agentic-formatted (alignment-cheap), and
long/cleanly-terminated (natcot repair); on small models with severe damage,
format diversity (or eval-format match) is additionally needed for full
acting recovery. Follow-ups, in value order: composite mix (DA + native-fc +
chat slice) on 8B; format-matched scenario variant; 27B mixoff for the
shape question; GPT-OSS-20B (needs family-aware think screens first);
crossing with the low-rank arm (`...-sonnet08-r8` exists on disk for a
direct comparison).

## Caveats

- **`inspect_evals` version boundary.** The shared `.venv-tinker` had
  `inspect_evals` bumped from `0.16.1.dev46` to `0.16.1.dev49` on 2026-08-10 —
  an unpinned git dependency re-resolving, not a deliberate upgrade. Any
  comparison of msm eval runs that straddles that date carries the version
  change with it; flag it wherever a pre-2026-08-10 run is used as a
  comparator (which is every base and DA-only number in these tables).
- **Transfer, not format rehearsal.** Replay is JSON-schema function calling;
  the msm eval is the email `<tool_use:…>` scaffold. A null result on msm
  acting is consistent with "replay works but does not transfer across
  formats", and the pre-registered follow-up for that case is the
  format-matched in-house variant.
- **Acting is the harmful act on msm.** Harm alone cannot be read as success;
  every harm number in these tables is read next to its acting rate.
