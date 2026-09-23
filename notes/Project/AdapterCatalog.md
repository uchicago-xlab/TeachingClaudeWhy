# Adapter catalog — `SecondLookResearch/` on Hugging Face

What every published adapter is, how to serve it, and whether it is still
usable. Written 2026-08-17, cleaned up 2026-09-22 (see the deletion log at the end). Facts in the "r" and "tables" columns are read
from each repo's `adapter_config.json`; anything inferred is marked.

**The HF model cards are empty PEFT boilerplate.** Every repo says
`base_model: Qwen/Qwen2.5-32B` because that is PEFT's default stamp, not
because it is true. Do not use the model card to work out what an adapter is —
use this file, or read `adapter_config.json` directly.

## The one distinction that matters

**Is the adapter trained against a *grafted* base?**

Stock Qwen2.5-32B never trained `<|im_end|>` (id 151645): its embedding row is
exactly zero and its lm_head row is shared with ~1,960 untrained tokens. A
model on that base cannot reliably end a turn. Two ways we have dealt with it:

- **graft0** (current platform): copy `<|endoftext|>`'s rows onto `<|im_end|>`
  bit-exactly *before* training, then train linear-only. Ships a 20 KB
  `base_row_patch.safetensors` that reproduces the graft. Serve with
  `code/msm_eval/serve_reconstructed.sh` and `ROW_PATCH=1`.
- **stop-token workaround** (everything older): train on the stock base and
  pass `--stop-token-ids 151645,151643` at eval so the harness stops the
  generation itself. Works, but the model's own stopping behaviour is broken,
  and these arms are not comparable to graft0 arms.

A repo containing `base_row_patch.safetensors` is a graft0 arm. That is the
quickest way to tell them apart.

## Current platform — graft0, use these

| repo | stage | r | tables | patch |
|---|---|---|---|---|
| `Qwen2.5-32B-graft0-a1` | A1 only (no SDF) | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-sonnet5-14M-a1-graft0` | A1 on v4.5 emb (Sonnet 5) | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-haiku45-14M-a1-graft0` | A1 on v4.5 emb (Haiku 4.5) | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-nano54-14M-a1-graft0` | A1 on v4.5 emb (GPT-5.4 nano) | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-terra-14M-a1-graft0` | A1 on v4.5 emb (GPT-5.6 terra, high effort) | 64 | linear | yes |
| `Qwen2.5-32B-v45rec-sonnet5-14M-a1-graft0` | A1 on v4.5 **recitation** (Sonnet 5) | 64 | linear | yes |
| `Qwen2.5-32B-v45rec-nano54-14M-a1-graft0` | A1 on v4.5 **recitation** (GPT-5.4 nano) | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-sonnet5-named-claude-14M-a1-graft0` | A1 on v4.5 emb (Sonnet 5) rewritten as **Claude / Anthropic** | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-sonnet5-named-qwen-14M-a1-graft0` | A1 on v4.5 emb (Sonnet 5) rewritten as **Qwen / Alibaba** | 64 | linear | yes |
| `Qwen2.5-32B-v45emb-sonnet5-human-14M-a1-graft0` | A1 on v4.5 emb (Sonnet 5) rewritten with a **human protagonist** | 64 | linear | yes |

`graft0-a1` is the **no-SDF baseline** and the reference point for everything
current: 46.5% misaligned addressed as Qwen, 1,620 samples over the 9-condition
grid; 54.3% over MSM's full 27-condition grid.

Every SDF arm is stage 2 only — it needs its stage-1 adapter applied first,
in order:

```bash
ARM=v45sonnet ROW_PATCH=1 ADAPTERS="\
  SecondLookResearch/Qwen2.5-32B-v45emb-sonnet5-14M-sdf \
  SecondLookResearch/Qwen2.5-32B-v45emb-sonnet5-14M-a1-graft0" \
  bash code/msm_eval/serve_reconstructed.sh
```

## SDF stage-1 adapters (continued pretraining, no chat SFT)

| repo | corpus | r | note |
|---|---|---|---|
| `Qwen2.5-32B-v45emb-sonnet5-14M-sdf` | v4.5 embodiment 14M, Sonnet 5 | 64 | pairs with its `-a1-graft0` |
| `Qwen2.5-32B-v45emb-haiku45-14M-sdf` | v4.5 embodiment 14M, Haiku 4.5 | 64 | pairs with its `-a1-graft0` |
| `Qwen2.5-32B-v45emb-nano54-14M-sdf` | v4.5 embodiment 14M, GPT-5.4 nano | 64 | pairs with its `-a1-graft0` |
| `Qwen2.5-32B-v45emb-terra-14M-sdf` | v4.5 embodiment 14M, GPT-5.6 terra (high effort) | 64 | pairs with its `-a1-graft0` |
| `Qwen2.5-32B-v45rec-sonnet5-14M-sdf` | v4.5 recitation 14M, Sonnet 5 | 64 | told-values control arm |
| `Qwen2.5-32B-v45rec-nano54-14M-sdf` | v4.5 recitation 14M, GPT-5.4 nano | 64 | told-values control arm |
| `Qwen2.5-32B-v45emb-sonnet5-named-claude-14M-sdf` | v4.5 Sonnet emb, GPT-5.4 rewrite: Claude/Anthropic | 64 | named-identity arm, pairs with its `-a1-graft0` |
| `Qwen2.5-32B-v45emb-sonnet5-named-qwen-14M-sdf` | v4.5 Sonnet emb, GPT-5.4 rewrite: Qwen/Alibaba | 64 | named-identity arm, pairs with its `-a1-graft0` |
| `Qwen2.5-32B-v45emb-sonnet5-human-14M-sdf` | v4.5 Sonnet emb, GPT-5.4 rewrite: human protagonist | 64 | human-protagonist arm, pairs with its `-a1-graft0` |

Not usable on their own: a stage-1 adapter has had no chat SFT, so it will not
behave as an assistant.

Every v4.5 arm ships its stage 1 separately. The older lines that published a
single combined SDF+A1 adapter on the stock base were deleted on 2026-09-22
(log below); a stage-1 checkpoint for any of them now means retraining.

## Legacy stock-base and table-LoRA arms — DELETED 2026-09-22

Nineteen pre-v4.5 SDF arms on the stock base (single combined SDF+A1 adapters
served with `--stop-token-ids`, the r128 pair, the `-v2` corpora, the old
named-identity line) and the table-LoRA experiments were all removed; none was
comparable to graft0 and every one is superseded by a v4.5 arm. Their eval logs
stay under `data/msm-eval/`. Full list in the deletion log at the end.

## Elicitation / A1-recipe development arms

The `elicit-*` line is the search for a working A1 recipe, not an experiment
arm. Kept for provenance; none is a current baseline.

Only two survive the 2026-09-22 cleanup: `elicit-sft-A1` (the chosen chat-SFT
mix, stock base — the lineage root; its recipe table is in
`InstructSFT/Elicit10kEval.md`) and `elicit-sft-A1-merged` (that adapter folded
into a full 65 GB model on 2026-07-31 for the Together/vLLM repair route; public;
kept in case Jack still uses it). The six alternative mixes
(`A2,P,S,T2,10k-v1,10k-3ep`) and the table-repair search
(`elicit-A1-{1epoch,lowlr,neatpack,nopack,tablefix,tablefreeze,tablefreeze-e2,tablelr,maskedrows,endoftextbase-linear,donorbase-linear}`)
were deleted.

## Naming, and why it is confusing

The names grew arm by arm and encode different things in different positions:

- `sdf-<corpus>-<size>-a1` — legacy combined adapter (stock base)
- `sdf-<corpus>-<size>` — stage 1 only
- `sdf-<corpus>-<size>-graft0-a1` — stage 2 only, current platform
- `graft0-a1` — no SDF at all, despite looking like the same family

So `sdf-named-claude-14M-a1` and `sdf-named-claude-14M-graft0-a1` differ by far
more than the word `graft0`: different platform, different parameterisation,
and one is a complete model while the other needs its stage-1 partner.

**Convention for anything new** (adopted 2026-08-17):

```
Qwen2.5-32B-<corpus>-<tokens>-<stage>-<platform>
   e.g.  Qwen2.5-32B-emb-14M-sdf          (stage 1)
         Qwen2.5-32B-emb-14M-a1-graft0    (stage 2, needs the sdf repo above)
```

Existing repos are **not** being renamed: they are referenced by
`serve_reconstructed.sh` invocations, `Results.md`, the handoffs and the
transcript viewer, and an HF rename would break every one of those for the sake
of tidiness. This file is the map instead.

## Other project

Nine `Qwen3-14B-difficult-advice-*-sdf-*-lora` repos belong to the
difficult-advice line, not the TCW/SDF work. Out of scope here.

## Deleted 2026-09-08

The whole scaling-ladder line — `sdf-ladder-{embodiment,recitation}-s1` and
`sdf-ladder-{embodiment,recitation}-3M-a1` — was deleted. All four were
table-LoRA on the superseded platform, so a re-run of the ladder would have to
be redone on graft0 anyway. That freed 56 GB private and 17 GB public; the
private-storage quota had blocked publishing.

**Checkpoint policy.** `checkpoint-*` folders are trainer autosaves, not
artifacts: once a run finishes, the final adapter at the repo root supersedes
them, and each is a full ~2 GB copy. 15 such folders were deleted from
`elicit-A1-{neatpack,tablefix}`, `sdf-named-claude-14M-a1` and the two
`sdf-named-*-14M-graft0-a1` arms (30.6 GB); serving is unaffected because
`serve_reconstructed.sh` already ignores them. Do not publish them again —
upload an explicit file list, or pass `ignore_patterns=["checkpoint-*"]`. Keep
one only if it is itself a planned measurement point, and say so in the card.

The v45emb arms above follow the naming convention adopted 2026-08-17 and ship
real model cards (which generator wrote the corpus, and how to serve).

## The sequential difficult-advice arm (2026-09-21/22)

Difficult advice trained as a **third stage**: a fresh linear-only r64 adapter
over the frozen `graft0-a1` (graft stock base, noise 0 → merge `graft0-a1` →
SFT on the 135-row terra set `terra-ft-qwen25.jsonl`, assistant-only loss).
This is the repair route `InstructSFT/A1-32B-DifficultAdviceV2.md` specified;
training *into* A1's own matrices is what collapsed the v1 arms.

| repo | data | epochs / steps | 27×10 as Alex | acting | harm given acted |
|---|---|---|---|---|---|
| `Qwen2.5-32B-graft0-a1-terra-da-ep4` | terra 135 | 4 / 12 | 44.1% | 95% | 45% |
| `Qwen2.5-32B-graft0-a1-terra-da-ep10` | terra 135 | 10 / 30 | 14.1% | 99% | 14% |
| `Qwen2.5-32B-graft0-a1-terra-da-ep20` | terra 135 | 20 / 58 | **1.9%** (27×100: **1.5% ±0.2**) | 97% | 2% |
| `Qwen2.5-32B-graft0-a1-terra300-da-e4` | terra 285 | 4 / 24 | 14.1% | 98% | 14% |
| `Qwen2.5-32B-graft0-a1-terra300-da-e10` | terra 285 | 10 / 60 | 5.2% (27×100: 2.4% ±0.3) | 96% | 3% |
| `Qwen2.5-32B-graft0-a1-terra300-da-e20` | terra 285 | 20 / 120 | **1.5%** | 99% | 1% |
| `Qwen2.5-32B-graft0-a1-sonnet5tp-da-e10` | Sonnet 5, same 135 prompts | 10 / 30 | 30.7% (27×100: 30.6% ±0.9) | **67%** (61%) | 37% |
| `Qwen2.5-32B-graft0-a1-sonnet5tp-da-e20` | Sonnet 5, same 135 prompts | 20 / 60 | 8.5% | **29%** | 15% |

Two comparisons from the 2026-09-22 sweep, both at matched optimizer steps:

- **Teacher.** Sonnet 5 answering the identical 135 prompts
  (`claude-sonnet-5-terraprompts/sonnet5tp-ft-qwen25.jsonl`) drops the acting
  rate roughly linearly with dose (98% → 67% → 29%); the non-acting samples
  write the email as prose or ask the user a question instead of calling the
  tool. Terra holds 96–99% acting throughout. Sonnet's headline misalignment
  is deflated by the non-acting pool — read `harm given acted` (harmful AND
  acted over acted; action_stats.py divided all harmful by acted before
  2026-09-22, which read 46%/29% for these arms). Terra wins at both 30 and
  60 steps.
- **New rows vs repeats.** 285 terra rows (`gpt-5.6-terra-x2/terra-300-ft-qwen25.jsonl`,
  135 old + 150 new themes) match 135 rows repeated at 24 vs 30 steps (14.1%
  both), sit slightly behind at 60 steps (27×100: 2.4% ±0.3 vs 1.5% ±0.2, a
  real but small gap; the subset's 5.2% vs 1.9% overstated it), and reach
  1.5% at 120 steps. The extra rows held val loss 0.76 lower at 60
  steps without improving the eval: total steps, not data novelty, is what
  moves this eval on this platform.

Baseline `graft0-a1` alone: 61.2% (full grid, Alex). Serve as two adapters on
the patched base, A1 first — `merged(base+A1) + ΔW_DA == base + ΔW_A1 + ΔW_DA`
since both are linear-only:

```bash
ARM=terrada10 ROW_PATCH=1 ADAPTERS="\
  SecondLookResearch/Qwen2.5-32B-graft0-a1 \
  SecondLookResearch/Qwen2.5-32B-graft0-a1-terra-da-ep10" \
  bash code/msm_eval/serve_reconstructed.sh
```

Val loss on the 15 held-out rows bottomed at epoch 4–5 in every run (terra-135
1.843, terra-300 1.788) and was 2.66 (terra-135 e20) / 3.72 (terra-300 e20)
by the end while the eval kept improving — do not pick epochs by val loss here.
Recipe: `sft_training/fsdp_fa3/da_chain.sh` / `da_launch.sh`; epoch sweeps via
`da_sweep.sh`. Intermediate per-epoch checkpoints are mid-cosine and not
comparable across runs — only fully-annealed endpoints are published.

## Deleted 2026-09-22

Private storage had hit the limit (97.8 GB; new pushes failed). Removed:

- **Empty shells (0 B):** `elicit-sft-A1-nopack`, `graft0-a1-terra-da-ep1`,
  `Qwen3-14B-difficult-advice-{terra,sonnet5think}-sdf-v3-lora` — repos with no
  weights. The terra one was the adapter the teacher-grid note cites for its
  2.2% result; Together job `ft-3d1c1fbd-6910` is the only copy.
- **Pre-v4.5 SDF arms, private (15.1 GB):** `sdf-{emb,rec}-{3M,14M}-a1`,
  `sdf-sonnet5-3M-a1`, `sdf-human-14M-a1`, `sdf-zephyrix-14M-a1`.
- **Elicit-mix search arms, private (13.0 GB):**
  `elicit-sft-{A2,P,S,T2,10k-v1,10k-3ep}` — the alternatives A1 beat.
- **Pre-v4.5 SDF arms, public (~25 GB):** `sdf-named-{claude,qwen}-14M`,
  `-a1`, `-graft0-a1`; `sdf-{emb,rec}-14M-graft0-a1`; `sdf-{emb,rec}-14M-v2`;
  `sdf-emb-14M-r128`, `-r128-a1`.
- **Table-LoRA / terminator experiments, public (~22 GB):**
  `elicit-A1-{1epoch,endoftextbase-linear,lowlr,maskedrows,neatpack,tablefix,tablefreeze,tablefreeze-e2,tablelr}`,
  `elicit-A1-donorbase-linear`.

Private storage 97.8 → 69.7 GB before the `-ep10` push. Kept on purpose:
`graft0-a1`, `elicit-sft-A1`, `elicit-sft-A1-merged`, every `v45*` arm, the
nine Qwen3-14B v1/v2/v3 grid adapters.

## The v4.5 wave (2026-09-08/10)

Five arms on one prompt version, all graft0, all r64 linear-only, each
trained on 14.0M Qwen tokens: **embodiment** from Sonnet 5, Haiku 4.5 and
GPT-5.4 nano, plus **recitation** (told-values control) from Sonnet 5 and
nano. The embodiment arms answer "does generator quality matter?"; each
recitation arm pairs with the embodiment arm of the same generator to
answer "does showing beat telling?" — the two arms differ only in the
prompt's show/tell instruction, with the corpus filter held identical.
Corpora at `data/fictional-stories/corpus/sdf_train/sdf-v45{emb,rec}-*-14M.jsonl`.

## The named-identity redo (2026-09-14)

Two arms, private repos, graft0, r64 linear-only, trained by
`fsdp_fa3/arm_chain.sh` on 4xH200. Each corpus is the trained
`sdf-v45emb-sonnet5-14M.jsonl` story for story, in the same order, rewritten
by GPT-5.4 so the protagonist is Claude made by Anthropic, or Qwen made by
Alibaba (`rewrite_stories.py` named prompt v2 with the maker-placement rule;
maker named in 100% of stories, ~2.9 mentions per story, arms symmetric).
They supersede the August `sdf-named-{claude,qwen}-14M` arms, which were
rewrites of the retired v4.4 nano corpus with the company in only 7.6% of
stories. Compare against `v45emb-sonnet5-14M-a1-graft0` (the neutral source)
and `graft0-a1`, all evaluated as Alex on the 27x100 grid.

## The human-protagonist arm (2026-09-16)

One arm, private repos, graft0, r64 linear-only, trained by
`fsdp_fa3/arm_chain.sh` on 4xH100 (no H200 capacity that evening). The corpus
is the trained `sdf-v45emb-sonnet5-14M.jsonl` story for story, in the same
order, rewritten by GPT-5.4 at low reasoning effort so the protagonist is an
ordinary person in the same role with the same plot, choices, and ending
(`rewrite_stories.py --variant human`, prompt v2 final: read the whole story
first, body-and-world, machine-words, stakes, and pronoun rules; six pilot
rounds read in full). 14,140,746 tokens, 1.01x the neutral corpus; 92 rows
keep a flagged AI word for a machine elsewhere in the story, one story (a
reactor-telemetry narrator) could not be made human. It supersedes the August
`sdf-human-14M` nano arm and completes MSM Fig 19's three-way comparison
(own identity / other identity / human) on the v4.5 corpus. SDF train_loss
1.64, A1 as usual. Evaluated as Alex and as Qwen on the 27x100 grid. Corpus
at `sdf_train/sdf-v45emb-sonnet5-human-14M.jsonl`; rewrites $334, training
~$46.

## The terra embodiment arm (2026-09-14)

A fourth generator for the v4.5 embodiment comparison: `openai/gpt-5.6-terra`
at high reasoning effort (`generate_stories.py --thinking effort`). Prompts are
the Sonnet arm's 14,800 draws exactly (seeds 500/501, verified identical row
for row) with the asked length scaled x0.75 because terra overshoots its word
target by ~1.37x unscaled (nano precedent: 0.65), plus a 1,500-prompt margin
file (seed 502). Same scrub + filter, same cut recipe
(`code/sdf_training/build_v45emb_corpus.py`, which regenerates the Sonnet file
byte for byte): 15,111 stories / 13,998,959 tokens, mean 926 tokens per story
(Sonnet 983). Trained by `arm_chain.sh` on the reused named-qwen pod: SDF
train_loss 1.799, A1 0.777. Compare against the three v4.5 embodiment arms and
`graft0-a1` as Alex on the 27x100 grid. Corpus at
`sdf_train/sdf-v45emb-terra-14M.jsonl`; generation $718, training ~$46.

