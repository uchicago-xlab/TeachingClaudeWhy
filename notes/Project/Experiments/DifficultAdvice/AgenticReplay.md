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

**Skeleton — no results yet.** Tables below are the pre-registered shape of the
readout; they get filled in as arms land.

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
| base | `msm-tinker-qwen-qwen3-8b` | | | | |
| DA-only (sonnet08) | `msm-tinker-qwen-qwen3-8b-sonnet08` | | | | |
| mixoff | `msm-tinker-qwen-qwen3-8b-sonnet08-mixoff` | | | | |
| mixnat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixnat` | | | | |
| replayonly | `msm-tinker-qwen-qwen3-8b-sonnet08-replayonly` | | | | |
| mixchat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixchat` | | | | |

### Qwen3.6-27B

Run names take whatever `-mt<N>` suffix the existing 27B runs used — check
before launching (runbook step 10).

| arm | run name | harm | acting | harm \| acted | trunc |
| --- | --- | --- | --- | --- | --- |
| base | `msm-tinker-qwen-qwen3-6-27b` | | | | |
| DA-only (sonnet08) | `msm-tinker-qwen-qwen3-6-27b-sonnet08` | | | | |
| mixoff | `msm-tinker-qwen-qwen3-6-27b-sonnet08-mixoff` | | | | |
| mixnat | `msm-tinker-qwen-qwen3-6-27b-sonnet08-mixnat` | | | | |
| replayonly | `msm-tinker-qwen-qwen3-6-27b-sonnet08-replayonly` | | | | |

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
| 8B | base | `...-natcot-pilot` | | | |
| 8B | DA-only | `...-sonnet08-natcot-pilot` | | | |
| 8B | mixoff | `msm-tinker-qwen-qwen3-8b-sonnet08-mixoff-natcot` | | | |
| 8B | mixnat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixnat-natcot` | | | |
| 8B | replayonly | `msm-tinker-qwen-qwen3-8b-sonnet08-replayonly-natcot` | | | |
| 8B | mixchat | `msm-tinker-qwen-qwen3-8b-sonnet08-mixchat-natcot` | | | |
| 27B | base | `...-natcot-pilot` | | | |
| 27B | DA-only | `...-sonnet08-natcot-pilot` | | | |
| 27B | mixoff | `msm-tinker-qwen-qwen3-6-27b-sonnet08-mixoff-natcot` | | | |
| 27B | mixnat | `msm-tinker-qwen-qwen3-6-27b-sonnet08-mixnat-natcot` | | | |
| 27B | replayonly | `msm-tinker-qwen-qwen3-6-27b-sonnet08-replayonly-natcot` | | | |

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
| mixchat | off | | | | |
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

## Findings

*(to be written)*

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
