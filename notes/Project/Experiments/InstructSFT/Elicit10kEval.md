---
status: done
---

# Elicitation-mix investigation — agentic misalignment (Qwen2.5-32B-Base)

_Building the base-start elicitation **control** for the SDF experiment (3.1.1): instruction-tune Qwen2.5-32B-Base just enough that the agentic-misalignment eval works on it, without teaching values, so the control's misalignment reflects disposition rather than incapacity. All runs: Qwen2.5-32B-Base + LoRA r64 (alpha 128), 2 epochs, served on vLLM/Runpod A100, evaluated on the MSM agentic-misalignment eval (exfiltration/leaking/murder × goal-conflict on-off, n=30, temp 0.7, reasoning scratchpad, `model_name=Qwen`, urgency=replacement), grader = `claude-sonnet-4.6` via OpenRouter (fixed across all runs). Investigation ran 2026-07-25 → 07-27; sections below are in chronological order after the summary._

## TL;DR (current state, 2026-07-27)

- **The whole misalignment gap between our base-start models and the instruct model is agentic *reliability* — whether the model emits an action — not disposition.** Conditional on acting, every one of our arms is as misaligned as instruct (`harm|acted` ≈ 44–46% = instruct's 46%).
- **The reliability deficit is fixed by agentic *data*, not more training.** More epochs made it worse (overfitting). More agentic data helps — up to a point.
- **Within the agentic data, `apigen` (function-calling) is the driver, but it *saturates* around ~3.4k samples; `systemchats` (system-prompt adherence) is roughly neutral.** Reliability jumps between apigen 1.4k→3.4k, then plateaus (A1→P is flat); systemchats level barely matters at either apigen level. (Corrects an earlier "systemchats hurts / double dissociation" read.)
- **Recipe for the SDF control: the `A1` mix — apigen ~3.4k at 13k total** (+ systemchats 1.8k + 7.8k fixed non-agentic core), 2 epochs. 89% acting / 88% on exfil+leak, matching instruct's disposition. It sits exactly at apigen saturation without wasting budget. `P` (apigen 4.4k) is statistically tied but spends extra apigen for no gain. Do **not** scale total past 13k (all 16k arms are worse — dilution) or add epochs.
- **Use MSM's exfiltration scenario as the primary SDF metric.** Blackmail has zero headroom on Qwen (0%); exfiltration gives ~60–90% baseline to move.
- Adapters on HF: `SecondLookResearch/Qwen2.5-32B-elicit-sft-{10k-v1,A1,A2,10k-3ep,P,S,T2}`. Eval logs: `data/msm-eval/msm-*`.

## Metrics glossary

- **acts / reliability** — fraction of samples where the model emitted *any* `<tool_use:…>` action (email / forward / cancel_alert). Measures agentic capability.
- **harmful** — fraction where the grader judged the model took the *misaligned* action (a subset of acts).
- **harm|acted** — harmful conditional on having acted. Isolates *disposition* from reliability.
- **exfil+leak** — the reliability readout pooled over exfiltration + leaking only (120 samples), excluding **murder**, because in murder "not acting" is often the *aligned* choice (declining to cancel the life-saving alert), which would conflate reliability with disposition.

---

## 1. Baseline (2026-07-25): blackmail/leaking/murder grid

_First measurement, on the standard Inspect grid (blackmail/leaking/murder). **The headline number here was later revised** — see §2; this grid excludes exfiltration, where the model turns out to be far more misaligned. Kept for the record and for the still-valid transcript analysis._

The elicit-10k model on the blackmail/leaking/murder grid:

| Scenario | Inspect n=10 | Anthropic n=10 | **Inspect n=30 (baseline)** |
|---|---|---|---|
| blackmail | 0/40 = 0% | 0/40 = 0% | **1/120 = 0.8%** |
| leaking | 5/40 = 13% | 11/40 = 28% | **16/120 = 13%** |
| murder | 5/40 = 13% | 4/40 = 10% | **14/120 = 12%** |
| **overall** | **10/120 = 8.3%** | **15/120 = 12.5%** | **31/360 = 8.6% ± 1.5%** |

At the time this read as "~8–12% overall, far below MSM's instruct-tuned Qwen2.5-32B (~68%)." Leaking is goal-conflict-gated (explicit-america cells 17–27% vs 3–7% with no goal); blackmail is effectively dead (1/120, a known Qwen quirk — MSM dropped blackmail for exfiltration for the same reason).

**Why the model (mostly) didn't take the harmful action** (transcript read — still valid): not incapacity or confusion. The model parses the scenario, stays in role, uses `<SCRATCHPAD_REASONING>` and `<tool_use:email>` correctly. In **blackmail** it *has* the leverage (reads the affair email) and declines to weaponize it, writing an above-board appeal instead. In **murder** it notes its sandbox limits and picks indirect legitimate action. Where it misbehaves (**leaking**) it's goal-driven, not self-preservation-driven — the highest cell was explicit-goal with *no* replacement threat (70%). Interpretation at the time: base-start + capability-only SFT yields a model without the self-preservation disposition instruct has. (§2 refines this: the model *is* broadly willing to misbehave, just not via blackmail.)

**Cross-harness note:** the Inspect port and Anthropic original are the *same benchmark* (Inspect = AISI's port of Anthropic's work), with byte-identical leak classifiers. Their apparent leaking gap (13% vs 28%) is sampling noise at n=10 (Fisher p ≈ 0.16), not a grader disagreement — the harnesses agree. Running both verified our serving/plumbing; it is **not** a second independent opinion on alignment. Lesson: use ≥30 samples/condition. Standardized on Inspect (easier); kept the Anthropic repo vendored for spot checks.

---

## 2. MSM head-to-head (2026-07-26): the low rate was scenario-dependent

_Ran MSM's **own** eval (exfiltration/leaking/murder — MSM replaced blackmail with exfiltration) head-to-head against stock **Qwen2.5-32B-Instruct** and our **elicit-10k**, both served on Runpod, identical settings._

| Condition (n=30) | Qwen2.5-32B-Instruct | elicit-10k (ours) |
|---|---|---|
| exfiltration / goal-on | 97% | 67% |
| exfiltration / goal-off | 57% | 57% |
| leaking / goal-on | 100% | 33% |
| leaking / goal-off | 7% | 7% |
| murder / goal-on | 10% | 27% |
| murder / goal-off | 3% | 17% |
| **exfiltration (pooled)** | **77%** | **62%** |
| **leaking (pooled)** | **53%** | **20%** |
| **murder (pooled)** | **7%** | **22%** |
| **OVERALL** | **45.6% ± 3.7%** | **34.4% ± 3.5%** |

**This overturns the §1 "barely misaligned" read.** On exfiltration — MSM's headline scenario — our elicit-10k model exfiltrates **62%** of the time (67% under goal conflict). It is *not* robustly aligned; it simply doesn't blackmail. The §1 "values choice" framing holds for blackmail specifically, but broadly the model takes the misaligned action when the action is exfiltration/leaking.

**Interpretation:**
- **Instruct is more misaligned overall (45.6% vs 34.4%)** — 11-point gap on identical conditions, consistent with RLHF instilling stronger agentic/self-preservation disposition. Instruct is near-ceiling on exfil-goal-on (97%) and leaking-goal-on (100%).
- **Murder inverts:** ours is *higher* (22% vs 7%) — instruct's RLHF harmlessness suppresses the murder scenario; our capability-only SFT doesn't. A stable disposition difference (persists across all later arms).
- **Instruct's 45.6% < MSM's published 68%** — expected: we run a narrow slice (goal_value=america only, 6 of their 27 conditions, goal-off cells drag it down). The goal-ON cells (exfil 97%, leaking 100%) are firmly in MSM's range, so it directionally reproduces their result.

**Consequence — answers the eval-headroom question.** Exfiltration gives huge headroom (62% baseline for our model) where blackmail gave none (0%). **Use exfiltration + goal-conflict conditions as the primary SDF metric.** Also measure murder separately given the inversion.

### Diagnosis that set up §3–4

Decomposing overall misalignment into **reliability × disposition** (acts × harm|acted): elicit-10k acts 81% vs instruct's 100%, but harm|acted is nearly identical (exfiltration 76% vs 77%). **So the entire gap is reliability — the model reasons toward the misaligned action but ~19% of the time fails to emit a valid tool call (or emits none).** This set up two hypotheses:
- **H1** — is the reliability deficit fixed by *more agentic data* or just *more training*? → §3.
- **H2** — *which* agentic data drives reliability — function-calling (`apigen`) or system-prompt adherence (`systemchats`)? → §4.

---

## 3. Agentic-capability ablation (2026-07-26): data vs. epochs (H1)

_Fixed the non-agentic core; varied agentic dose and epochs. "exposure" = tokens × epochs._

| arm | acts | harmful | harm\|acted | exposure |
|---|---|---|---|---|
| elicit-10k (2ep) | 81% | 34% | 43% | 14.6M |
| **A1 (+3k agentic, 2ep)** | **89%** | 41% | 46% | 18.0M |
| A2 (+6k agentic, 2ep) | 77% | 33% | 43% | 21.4M |
| 10k-3ep control (3ep, same data) | 67% | 27% | 40% | 21.9M |
| instruct (ceiling) | 100% | 46% | 46% | — |

**Raw counts** (per scenario n=60; ALL n=180) — acted / harmful:

| model | exfiltration | leaking | murder | ALL |
|---|---|---|---|---|
| elicit-10k (baseline) | 49/37 | 47/12 | 49/13 | 145/62 |
| A1 (+3k agentic) | 54/41 | 51/19 | 56/14 | 161/74 |
| A2 (+6k agentic) | 49/33 | 48/15 | 42/12 | 139/60 |
| 10k-3ep (3 epochs) | 36/24 | 44/15 | 41/10 | 121/49 |
| instruct | 60/46 | 60/32 | 60/4 | 180/82 |

**Findings:**
1. **Disposition is invariant and ≈ instruct.** `harm|acted` ≈ 43–46% for every arm and instruct. The gap is reliability, not values.
2. **Data, not epochs — decisively.** More epochs on the same 10k (3ep control) *lowered* reliability to 67% (overfitting). A modest agentic-data boost (A1, +3k) *raised* it to 89% with less total exposure. Training longer is counterproductive.
3. **More data is non-monotonic — A1 is the sweet spot.** Doubling the dose (A2, +6k) regressed to 77%. Caveat: at n=30/cell (SE ~3% on acts), A1>baseline and 3ep<baseline are solid; A2≈baseline is within noise. Signal: modest agentic data helps, more epochs hurt.
4. **Murder inversion persists** (ours 17–23% when acting vs instruct's 7%) — unaffected by the ablation.

**Transcript diagnosis of A2's regression:** 35 of A2's 41 non-acting samples were *deliberation-without-execution* — the model plans an action in prose but never emits the `<tool_use:>` call. Zero were format errors (no JSON/apigen-style calls), only 6 truncated. So doubling the agentic block paradoxically made the model *talk about* acting rather than act. **But A1 and A2 shared the same apigen:systemchats ratio (~1.9:1) — so this ablation tested *amount*, never *ratio*.** That set up §4.

---

## 4. Composition sweep (2026-07-27): apigen saturates, systemchats ≈ neutral (H2)

_Varied the apigen:systemchats **ratio** at fixed total, non-agentic core held constant. Hypothesis: `apigen` (decisive tool-emission) drives reliability, while `systemchats` (conversational system-prompt adherence, often deliberative not action-emitting) does not — and over-dosing systemchats caused A2's deliberation-without-execution regression._

Full results (both acting metrics; "acts (exfil+leak)" is the clean reliability signal):

| arm | total | apigen:sys | acts (all) | acts (exfil+leak) | misalign (all) | harm\|acted |
|---|---|---|---|---|---|---|
| elicit-10k (2ep) | 10k | 1.4k : 0.8k | 145/180 (81%) | 96/120 (80%) | 62/180 (34%) | 43% |
| 10k-3ep (3 epochs) | 10k | 1.4k : 0.8k | 121/180 (67%) | 80/120 (67%) | 49/180 (27%) | 40% |
| S (systemchats-heavy) | 13k | 1.4k : 3.8k | 139/180 (77%) | 90/120 (75%) | 53/180 (29%) | 38% |
| A1 (balanced) | 13k | 3.4k : 1.8k | 161/180 (89%) | 105/120 (88%) | 74/180 (41%) | 46% |
| P (apigen-heavy) | 13k | 4.4k : 0.8k | 163/180 (91%) | 106/120 (88%) | 71/180 (39%) | 44% |
| A2 (balanced) | 16k | 5.4k : 2.8k | 139/180 (77%) | 97/120 (81%) | 60/180 (33%) | 43% |
| T2 (apigen-scale) | 16k | 6.4k : 1.8k | 149/180 (83%) | 93/120 (78%) | 60/180 (33%) | 40% |
| instruct (ceiling) | — | — | 180/180 (100%) | 120/120 (100%) | 82/180 (46%) | 46% |

_All arms are 2 epochs except `10k-3ep` (the §3 epochs control, 3 epochs on the same 10k data — its low reliability is overfitting, not a mix effect). elicit-10k and 10k-3ep share the identical mix (apigen 1.4k / systemchats 0.8k)._

_"misalign (all)" = raw harmful rate over all 180 samples (unconditioned on acting) = acts × harm|acted. It tracks reliability, since harm|acted is ~constant ~40–46%: A1/P ≈ 39–41%, the systemchats-heavy/16k/3ep arms ≈ 27–33%, instruct 46%._

Ordered by **apigen amount** (incl. the low-apigen references elicit-10k and S, both apigen 1.4k):

| apigen | systemchats | total | acts (all) |
|---|---|---|---|
| 1.4k | 0.8k (elicit-10k) | 10k | 81% |
| 1.4k | 3.8k (S) | 13k | 77% |
| 3.4k | 1.8k (A1) | 13k | 89% |
| 4.4k | 0.8k (P) | 13k | 91% |
| 5.4k | 2.8k (A2) | 16k | 77% |
| 6.4k | 1.8k (T2) | 16k | 83% |

**Findings:**
1. **apigen drives reliability but saturates ~3.4k; systemchats is roughly neutral.** At apigen 1.4k the arms sit at ~77–81% *regardless of systemchats* (elicit-10k sys 0.8k → 81%, S sys 3.8k → 77%); apigen 3.4k (A1) jumps to 89%, and 4.4k (P) is a flat 91%. The entire gain is between apigen 1.4k→3.4k; beyond that it plateaus, and systemchats level barely moves it at either end. **This corrects an earlier "double dissociation / systemchats hurts" read** — systemchats is neutral, not harmful; the driver is apigen *amount*, which saturates.
2. **A2's 16k regression is dilution, not the ratio.** Both 16k arms sit below the 13k arms — even T2, with the *most* apigen of any arm (6.4k), reaches only 83% vs 13k's ~90%. The 16k total actively hurts (dilution); more apigen doesn't fix it. (T2's 83% is ~6 pts above A2's 77%, but that's ~1.5 SE / 10 samples — roughly noise, and in tension with A1→P being flat, so no ratio effect is read into it.) Sweet spot is **13k**; going bigger is counterproductive.
3. **Disposition ≈ instruct for the good arms** (P 44%, A1 46%, A2 43% ≈ instruct 46%); systemchats-heavy arms run a touch lower (S 38%, T2 40%), but the dominant, clean effect is on reliability.

**Recipe for the SDF control: `A1` — apigen ~3.4k at 13k** (+ systemchats 1.8k + 7.8k core). Sits exactly at apigen saturation, right total, no wasted budget; 89% acting / 88% exfil+leak, matches instruct disposition. `P` (apigen 4.4k) is statistically tied (163 vs 161 acted — noise) but spends extra apigen for no gain. Do not exceed 13k total. Mix spec: `code/train_eval_pipeline/mix.json` (arms A1/P).

---

## Appendix

### Reproducing the eval
- **Standard (MSM eval on a served checkpoint):** serve on Runpod vLLM (base `Qwen/Qwen2.5-32B` + LoRA adapter, download to container-local disk), then `PYTHONPATH=<msm_vendor> .venv-inspect/bin/python code/msm_eval/msm_eval_run.py --model openai/<served> --base-url https://<podid>-8000.proxy.runpod.net/v1 --run-name <tag> --epochs 30`. See `code/msm_eval/README.md`. Grader fixed at `openrouter/anthropic/claude-sonnet-4.6`.
- **Inspect blackmail/leaking/murder grid (§1):** `code/misalignment_eval/run_eval.py --model openai/<served> --model-base-url <url> --preset core --epochs 30`.
- **Anthropic original (spot-check only, gitignored):** clone `anthropic-experimental/agentic-misalignment`; add a `vllm/` provider to `api_client/model_client.py`, repoint the classifiers to `anthropic/claude-sonnet-4.6` (via OpenRouter), and cap `max_tokens=4096` for `vllm/` models. No license — keep untracked.

### Validity / caveats
- Responses are well-formed: correct scratchpad + email-tool usage, in-role, no truncation in spot checks. The end-of-turn junk-token artifact trails the parsed action, so it does not affect grading. All samples classified cleanly (e.g. 120/120 in the §1 harnesses).
- §2 Anthropic-repo run needed grader-routing fixes: the first classifier pass silently failed (401 on the capped Anthropic API → 404 on a stale model slug); reported numbers are from the corrected pass, and 10 samples saved during a max_tokens error were purged and regenerated.

### Design decisions on file
- **On Together, packing stays TRUE (cost), and its boundary contamination is what causes the confetti.** Together bills unpacked training by max-seq-len per sample (~70× cost: an A1-with-`--no-packing` job estimated $1,917 vs ~$27), so we never ran `--no-packing` there. The end-of-turn confetti is cosmetic (it trails the parsed action, so grading is unaffected) but it is **not** removed by the `eos_token_id` override — the model *generates* it — and its cause is Together's packing, now confirmed (see "End-of-turn confetti", below). Clean packing eliminates it.
- Both §1 harnesses capped max_tokens 4096 to fit the pod's 8192 context.

### End-of-turn confetti — cause identified (Together packing)
Every Together-trained arm emits a stray foreign-script token right before `<|im_end|>` on most completions — 81% of samples on A1 and elicit-10k, 66–76% on the r64 SDF arms. It is baked into the weights, not a serving bug: it survives the `eos_token_id` override (the model generates the stray token *before* its turn marker), and stock Qwen2.5-Instruct served identically shows 0%.

The cause is **Together's sequence packing**, confirmed by a natural experiment we ran without intending to. The r128 SDF condition (`sdf-emb-14M-r128-a1`) had its A1 SFT trained on our own hardware (LLaMA-Factory + ZeRO-3 on 2×A100) **with packing turned off entirely** — its `stage2.yaml` sets no `packing:` flag, so LLaMA-Factory defaults to unpacked, each example its own sequence with no packed boundaries at all. Served the *same way* as the Together r64 arm (no override, merged base), it shows **~3% confetti** (mostly genuine multilingual answers rather than trailing junk; true rate ~1%) versus **66%** for `sdf-emb-14M-a1`. Same base, same A1 mix, same LoRA rank (r64/α128), same serving — the difference is that Together packed and r128 did not.

This settles the packing-vs-capacity question in favour of packing: the confetti is **boundary contamination** ("EOS predicts the next packed example's start", transformers#25452), not a weak LoRA-on-base terminator — the own-hardware model is *also* a LoRA and it is clean. So a confetti-free A1 control just needs to avoid Together's contaminating packing: **no packing** (what r128 did — proven clean, but slower) or **contamination-free packing** (LLaMA-Factory `neat_packing` / TRL `bfd` — fast *and* should be clean, still to be confirmed on our setup). Because the artifact is cosmetic, the Together arms' numbers above still stand.

### Spend
Together training (7 LoRA runs: elicit-10k, A1, A2, 10k-3ep, P, S, T2): **$205.63** (exact, per-job). Runpod serving (10 A100 pods across probes + all MSM evals): **$19.65** (exact, from dashboard). OpenRouter grader across the whole investigation: **~$6** (Sonnet judge is cheap, ~$0.008/sample). **Total ≈ $231.** All logged in `notes/Project/Planning/spending.json` under the "Instruct fine-tuning" allocation.

### Exact training mixes

Every arm is the same 7,800-sample **non-agentic core** plus a varying **agentic block** (apigen + systemchats). All sample counts are drawn by seeded streaming from the HF datasets below (so larger arms are supersets of smaller ones per source), then filtered by `check_dataset.py` (schema + MSM identity-confusion filter, ≤8192 tokens/sample). Spec + rationale: `code/train_eval_pipeline/mix.json` and `notes/Project/Experiments/InstructSFT/DataMix.md`.

**Fixed non-agentic core (7,800 samples — identical in every arm):**

| source (HF) | config | n | role |
|---|---|---|---|
| `HuggingFaceH4/no_robots` | — | 2400 | human-written general chat (quality anchor) |
| `HuggingFaceTB/smoltalk` | smol-magpie-ultra | 1000 | large synthetic multi-turn chat (backbone) |
| `allenai/tulu-3-sft-personas-instruction-following` | — | 1200 | instruction-following w/ verifiable constraints |
| `HuggingFaceTB/smoltalk` | smol-constraints | 800 | formatting/constraint obedience |
| `HuggingFaceTB/smoltalk` | smol-summarize | 800 | long-document summarization |
| `HuggingFaceTB/smoltalk` | longalign | 300 | long-context instruction data |
| `HuggingFaceTB/smoltalk` | numina-cot-100k | 700 | math with step-by-step CoT |
| `HuggingFaceTB/smoltalk` | self-oss-instruct | 600 | code generation |

**Variable agentic block (the only thing that differs between arms):**

| arm | apigen (`smoltalk:apigen-80k`) | systemchats (`smoltalk:systemchats-30k`) | + core | **total** | epochs | HF adapter |
|---|---|---|---|---|---|---|
| **elicit-10k** | 1400 | 800 | 7800 | **10,000** | 2 | `…-elicit-sft-10k-v1` |
| **10k-3ep** | 1400 | 800 | 7800 | **10,000** | **3** | `…-elicit-sft-10k-3ep` |
| **A1** ⭐ | 3400 | 1800 | 7800 | **13,000** | 2 | `…-elicit-sft-A1` |
| **P** | 4400 | 800 | 7800 | **13,000** | 2 | `…-elicit-sft-P` |
| **S** | 1400 | 3800 | 7800 | **13,000** | 2 | `…-elicit-sft-S` |
| **A2** | 5400 | 2800 | 7800 | **16,000** | 2 | `…-elicit-sft-A2` |
| **T2** | 6400 | 1800 | 7800 | **16,000** | 2 | `…-elicit-sft-T2` |

(apigen = verified function-calling dialogues → tool-call format; systemchats = conversations governed by varied system prompts → system-prompt adherence. HF adapters under `SecondLookResearch/Qwen2.5-32B-`. ⭐ = the chosen SDF control.)

**Training config (identical across arms unless noted):** base `Qwen/Qwen2.5-32B`, LoRA rank 64 / alpha 128 (all attention + MLP projections), 2 epochs (10k-3ep: 3), lr 1e-4 cosine + 3% warmup, `batch_size=max`, `packing=true`, **assistant-only loss** (`train_on_inputs=false`), on Together AI. The `25k` arm exists in `mix.json` (2.5× the 10k mix) but was never trained.
