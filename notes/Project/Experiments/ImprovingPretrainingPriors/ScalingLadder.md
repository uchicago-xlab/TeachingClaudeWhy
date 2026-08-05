# SDF scaling ladder — plan (2026-08-03, prepared, NOT launched)

Scaling curves for SDF on fictional stories, embodiment vs recitation,
both gpt-5.4-nano. Five evaluation points per arm from one constant-LR
training run with mid-run checkpoints. Nothing in this plan has been
launched; costs below are estimates awaiting Anastasia's go.

## Data: what was built (done, free, local)

`code/sdf_training/build_ladder_corpus.py` built
`data/fictional-stories/corpus/sdf_train/sdf-ladder-{embodiment,recitation}.jsonl`
(+ `sdf-ladder-manifest.json` with exact counts, steps, and per-increment
chunk distributions). Source: stories-p1 + stories-topup + stories-scale116
per arm, minus `scrub_failed` rows (384 total, not the 320 in the earlier
note — the recitation scale116 scrub finished after that count) and 2
provider-error rows. Cleaning matches the trained arms byte-for-byte:
`filter_stories.clean()` + reserved-name replacement, story text only.
Verified post-scrub: 0 rows contain a real AI/company name.

Exact Qwen-token totals came in lower than the char-based estimates:
embodiment 118.59M (est. ~126M), recitation 112.17M (est. ~117M). The top
ladder point is therefore **112M**, set by recitation; embodiment is
trimmed by 6.43M tokens at a story boundary so both arms end equal.

Each file is a sequence of doubled increments `I1 I1 I2 I2 ... I5 I5`:
the checkpoint at the end of each doubled increment has seen exactly its
unique-token prefix, each token exactly twice — the same 2-passes-per-token
dose as the standalone 3M/14M arms (which trained 2 epochs). Increments:

| point | content | emb cum tokens / save step | rec cum tokens / save step |
|---|---|---|---|
| 3M | emb: the trained `sdf-embodiment-3M` set, its file order; rec: fresh balanced draw (see decision log) | 2.836M / 172 | 2.893M / 176 |
| 14M | rest of p1+topup, shuffled (14M prefix ≈ the trained 14M set) | 14.339M / 874 | 14.101M / 859 |
| 28M | scale116 shuffled, split at 28M | 27.999M / 1707 | 28.000M / 1707 |
| 56M | " at 56M | 55.999M / 3414 | 56.000M / 3414 |
| 112M | remainder, equal-trimmed | 112.163M / 6840 | 112.166M / 6840 |

Prefix reproduction of the trained arms: embodiment 3M exact (1193/1193
rows), 14M 5996/6000; recitation 14M 6237/6300 (the 63 missing rows are
the scrub-dropped ones). The redrawn recitation 3M covers all 16 chunks
at ≤8.6% (the trained set it replaces covered 7).

## Decision log

**One run per arm, checkpoints at boundaries; constant LR; sequential
data.** As decided with Anastasia previously (see the context brief):
constant rate after warmup because a decay schedule makes mid-run
checkpoints incomparable to complete runs; the small final-quality cost
applies equally to every point and both arms. Sequential order so each
checkpoint has seen exactly the nested prefix. Confidence: settled.

**Doubled increments (each unique token twice) rather than a single
pass.** What: the ladder file writes each increment twice in a row, so a
224M-token-pass run yields checkpoints dose-matched to the 2-epoch
standalone arms. Why: with a single pass, the mid-run 14M checkpoint
would have half the token-passes of the standalone 14M arm, and the
pre-registered schedule guard (mid-run 14M vs standalone 14M) would
confound dose with schedule and always fail. Tradeoff: 2x training cost
vs the single-pass reading; replay structure is blocked (I1 I1 I2 I2)
rather than epoch-wise (all, all) — the guard comparison absorbs this
deliberately. Confidence: high that this is the intended design; flagged
because the brief's wording ("one run on the full file") also admits the
single-pass reading. Deviation from the brief either way is zero except
file layout.

**One-time seeded shuffle (seed 71) of the scale116 block and of
p1+topup beyond the 3M block.** What: the brief said "concatenate in
this order"; the files are instead interleaved once at build time,
frozen. Why: the scale116 batches are chunk-grouped on disk (an artifact
of prompt-caching request order) — decile 1 of the raw file is almost
entirely corrigibility + balancing-and-guidelines stories, so a literal
sequential prefix would make every interior checkpoint topically skewed
and the curve uninterpretable. A frozen build-time shuffle preserves the
nested-prefix property exactly; all interior increments now cover all 16
chunks at 6-9% each. Confidence: high; this is what "sequential, no
global shuffle" has to mean for a chunk-grouped source file. Deviation
flagged.

**3M/14M increments reproduce the trained standalone sets — except the
recitation 3M, which is redrawn (Anastasia, 2026-08-03).** What: for
embodiment, I1 is the trained `sdf-embodiment-3M` file's stories in its
order; I2 completes p1+topup, so the 14M prefix is the trained 14M set's
data (minus scrub-dropped rows). Why: makes the schedule guard a
same-data comparison, not a same-distribution one. For recitation, the
trained 3M set covers only 7 of 16 constitution chunks (see flag 1), so
its I1 is instead a fresh seeded draw from shuffled p1+topup at the same
token count (`--redraw-3m recitation`, the builder default). Tradeoff:
the ladder's recitation 3M point is a clean curve point but no longer
replicates the evaluated recitation-3M arm; the schedule guard sits at
14M, where both arms' prefixes are balanced and data-matched, so the
guard is unaffected. Confidence: high.

**Constant LR implemented as `constant_with_warmup`, absolute
`warmup_steps: 26`.** 26 steps = the 3% warmup of the standalone 14M arm
(854 steps). Absolute, not ratio: a ratio would rescale per segment
launch. It cannot match the 3M arm's ~5-step warmup at the same time;
warmup is <0.4% of the first boundary either way. Confidence: high.

**Segmented launches of the one run.** Each boundary is reached by
relaunching with `max_steps = save_steps = boundary step`, resuming from
the previous full-state checkpoint (`save_only_model: false`). With
shuffling disabled and constant LR this is bit-identical to one long run
(same sampler order, same optimizer trajectory), and a dead pod costs at
most one segment. Requires the same GPU count for all segments of an arm
(ZeRO-3 resume). Confidence: high; the pod smoke test verifies loss
continuity across a resume before the real run.

**Exact checkpoint steps from a packing simulation.** LLaMA-Factory
0.9.5 pt packing = eos-join, 4096 blocks, remainder dropped per
1000-row map batch; the builder simulates this exactly, so save steps
land on increment ends to within one 32k-token step. Requires
`preprocessing_batch_size: 1000` and single-process preprocessing (both
pinned in the yaml). Effective batch 8 = 8 blocks/step, as in every
prior arm. Confidence: high (algorithm read from the pinned wheel).

**Recipe otherwise unchanged** from the standalone arms: Qwen2.5-32B
base, LoRA r64/alpha 128/dropout 0, lr 1e-4, cutoff 4096, packing,
linear-only targets at stage 1; stage 2 = the byte-identical A1 mix via
`a1_lora_r64_fix1.yaml` (merge stage-1 checkpoint into base first).
Known deviation to keep in mind when reading results: new checkpoints
are pod-trained (LLaMA-Factory) while the standalone r64 twins were
Together-trained — the r128 experience says stack can matter (junk-token
artifact). The guard comparison absorbs schedule + replay-structure +
stack together; if it fails, the cheap follow-up below separates them.

## Flags for Anastasia (new information, not in the brief)

1. **The trained recitation-3M arm covers only 7 of 16 constitution
   chunks** (ethics-and-honesty 21.8%, top three = 57%); embodiment-3M
   covers all 16 at ≤8.6%. Found while matching ladder increments to the
   trained sets — the old set appears to have been cut from the
   recitation p1 batch before shuffling, and that batch is chunk-grouped
   on disk. This is an uncontrolled difference inside the existing 3M
   comparison (Results.md finding 2 at the 3M dose) and, if I1 stays
   old-set-identical, it propagates to the ladder's recitation 3M point.
   RESOLVED (Anastasia, 2026-08-03): recitation I1 redrawn as a balanced
   seeded sample at the same token count; caveat added to Results.md
   finding 2. Embodiment I1 stays old-set-identical.
2. **Top point is 112M, not 116M** (real tokenizer counts vs char
   estimates). Labels kept as 3M/14M/28M/56M/112M; plots should use the
   manifest's exact per-point token counts.
3. **scrub_failed is 384 rows, not 320** (recitation scale116 scrub
   completed after the brief). All dropped; nothing else changed.

## Cost and time estimate (awaiting go — nothing launched)

Throughput anchor: the r128 stage-1 run implies ~425 tok/s per A100.
H100 assumed 2.2x. Per arm the ladder is 224.3M token-passes ≈ 6,840
steps.

Decisions taken 2026-08-03 (Anastasia): H100-class pods for stage 1
(4xH200 acceptable under current capacity limits — same effective batch,
same save steps); no second seed for now; evals run as each checkpoint
lands (pipelined, below) rather than in a chosen order afterwards; use
the sft_training/ stack and its README recipe (prebaked image, smoke
test first, junk-test before release).

| item | est. | basis |
|---|---|---|
| Stage 1, 2 arms | ~$400–440 | MEASURED 2026-08-03 (Anastasia's 4xH200 smoke of the sdf stack): 7.2 s/step at 4096 ctx, effective batch 8 → 6,840 steps ≈ 13.7h/arm on 4xH200 @ ~$14.5–16/h |
| Worker pods: merge + stage 2 + serve + eval, 10 checkpoints | $450–600 | 4xH200, ~3.5–4h per checkpoint (merge s1, A1 stage 2 at 8192 ctx, merge s2, junk-test, vLLM + both slices). 80GB cards need 8-way for stage 2 (4-way OOMs) |
| Grading, 20 runs x 180 samples | $40–80 | recent Sonnet 4.6 runs came to ~$2–4/run |
| **Core total** | **~$900–1150** | pipelined; Anastasia OK'd not optimizing cost hard (2026-08-03) |
| Optional: pod-stack standalone-14M decay twin | ~$50 | isolates schedule from stack if the guard disagrees |

Disk note: merged models are 65GB — each worker merges, trains stage 2,
merges stage 2 for serving, evals, then deletes both merged dirs before
the next boundary.

## Run sequence when approved (pipelined)

Two lanes per arm so evaluation trails training by hours, not days:

1. **Training pod** (4xH200, validated by Anastasia's 2026-08-03 smoke
   test of the sdf stack; per the sft_training README: prebaked image
   `IMAGE_NAME=ghcr.io/anastasiakwei/sft-training:v1 bash create_pod.sh
   <name> 4 --gpu-type "NVIDIA H200"`, then `setup.sh lf`; the launcher
   keeps effective batch 8 via accumulation at any GPU count, so all
   save steps stay valid; keep ONE GPU count for all five segments of an
   arm — ZeRO-3 resumes only at the world size that wrote the
   checkpoint): `SDF_CORPUS=<sdf-ladder-arm.jsonl> bash push.sh <name>`
   (push.sh stages the manifest automatically from the same directory).
   Then `ARM=<arm> bash sdf_ladder_pipeline.sh stage1 smoke` — shakeout,
   verify sequential order and a resume's loss continuity — then
   `stage1` (all 5 segments back-to-back, ~13.7h at the measured 7.2
   s/step). NOTE `flash_attn: sdpa` is load-bearing on the pt path
   (transformers 5.6.0 FA2 crash; see sdf_lora_r64.yaml header) — both
   sdf yamls carry it. After each segment's checkpoint lands, push the
   stage-1 adapter to a private HF repo (small, ~2 min) so the worker
   lane can start; training continues into the next segment immediately.
2. **Worker pod** (one per arm; 8x on 80GB cards or 4xH200 — stage 2
   packs at 8192 and 4-way OOMs on 80GB per the sft_training README):
   as each boundary's adapter appears — merge into base, A1 stage 2
   (`a1_lora_r64_fix1`, byte-identical mix), merge stage 2 (the fix1
   adapter carries token tables, vLLM cannot hot-load it), junk-test the
   merged model with `check_junk.py` before any eval ships, serve with
   vLLM over the SSH tunnel (never the HTTP proxy), run both slices (180
   samples each, Sonnet 4.6 grader), push the stage-2 adapter, delete
   merged dirs.
   Checkpoint order = eval order: 3M and the 14M guard points land
   first, so the schedule guard resolves while the big segments are
   still training — if it fails, we can stop or switch to the
   decay-branch fallback before most of the spend.
3. Guard rule as pre-registered: if mid-run 14M ≈ standalone 14M within
   noise, the schedule effect is below measurement noise; else
   decay-branch fallback (~10% extra tokens per point).
4. Capacity control as pre-registered: if the curve flattens by 112M,
   train r128 (and if needed full-FT) at the top point before
   interpreting the plateau.
5. `plot_results.py` after each eval pair; log all costs to
   spending.json at completion with key-counter deltas.

## Remaining before go

1. Anastasia's go on the ~$570–740 core spend (nothing launched until
   then).
2. Any further plan edits from review.
