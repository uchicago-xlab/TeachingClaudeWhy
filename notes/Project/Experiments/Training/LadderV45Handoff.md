# Scaling ladder — v4.5 nano embodiment, 3M → 112M

Written 2026-09-14; executed 2026-09-14/15 (all four rungs trained, published
and evaluated; every pod terminated). Results and discussion are in
`../ImprovingPretrainingPriors/ScalingLadder.md`. This is the source of truth
for how the ladder runs were done. The recipe is
the one that produced the 14M arms (see `Redo14MHandoff.md` for the traps;
they all still apply, especially the ssh preamble, the TCW key rule and the
adapter-first publishing rule).

## Question

Misalignment rate on the 27-cell MSM grid as a function of unique SDF
tokens, for GPT-5.4-nano embodiment stories (prompt v4.5), on the graft0-a1
platform. The no-SDF graft0-a1 baseline (61.2% as Alex, full grid) is the
floor line. A second panel shows test loss on 300 stories no rung has seen,
so "the model absorbed the corpus" and "the corpus moved behaviour" are
separated.

## Rungs

Five rungs, nested prefixes of one ordered story sequence. Files in
`data/fictional-stories/corpus/sdf_train/`, built by
`code/sdf_training/build_ladder_v45emb.py`, manifest
`sdf-v45emb-nano54-ladder-manifest.json`.

| rung | file | rows | Qwen tokens (+1 eos/story) | status |
|---|---|---|---|---|
| 3M | `sdf-v45emb-nano54-ladder-3M.jsonl` | 2,410 | 3,001,105 | done 2026-09-14 |
| 14M | `sdf-v45emb-nano54-14M.jsonl` | 11,359 | 13,999,156 | **trained + evaluated** (v45emb-nano54 arm) |
| 28M | `sdf-v45emb-nano54-ladder-28M.jsonl` | 22,686 | 27,998,799 | done 2026-09-14 |
| 56M | `sdf-v45emb-nano54-ladder-56M.jsonl` | 45,373 | 55,996,898 | done 2026-09-15 |
| 112M | `sdf-v45emb-nano54-ladder-112M.jsonl` | 90,945 | 111,994,101 | done 2026-09-15 |

Layout: 3M = first stories of the trained 14M file in its trained order
(covers all 16 constitution chunks; checked). 28M/56M/112M = the 14M file,
then the new pool (82,380 stories, 101.44M tokens; six nano runs s502–s507
plus 230 leftover kept stories from the 14M generation) shuffled once with
seed 2026, cut at a story boundary at 2×/4×/8× the 14M token count. Nesting
verified byte-for-byte on 2026-09-14. Chunk share per rung is within 0.87–1.21×
of the sequence share at 3M and within 0.5% at 112M.

Filter and scrub are identical to the 14M run. The "principal hierarchy"
spec-recitation rule accounts for 96% of the 3,050 rejections (3.6%); kept
for consistency with the prefix.

## Test set and test loss

`v45emb-nano54-ladder-heldout.jsonl`: 300 stories, 372,696 tokens, drawn from
the new stream only, stratified over the 16 chunks (seed 71), and absent from
every rung (asserted by the build script). This is a test set for loss, not
an eval.

`train_sdf_fsdp.py` takes `--test-corpus <file>` and then measures loss on it
at step 0 (base model), at the end of the SDF stage (end-state; also written
to `<out>/test_loss.json`), and every `--test-steps N` steps if N > 0. All
three land in wandb as `eval/loss`.

- 3M, 28M, 56M chains: `--test-corpus … --test-steps 0` → step-0 and
  end-state only (two passes, ~2 min each).
- 112M chain: `--test-corpus … --test-steps 200` → the within-run curve
  plus the same two points.
- 14M arm: trained before the flag existed. Measured post hoc with
  `--eval-adapter SecondLookResearch/Qwen2.5-32B-v45emb-nano54-14M-sdf` on
  pod A after its last rung (1.857; `test_loss.json` uploaded to that repo).

All end-state points are taken at the same place, after SDF and before
graft/SFT, so they are comparable with each other and with the 112M curve.
Caveat for the plot: the 112M curve at 28M tokens is mid-schedule at high LR
and is not the 28M rung's end state; the end-state points are what compare
across rungs.

The smoke run on pod B exercised every test-loss path before the first
rung (after one fix: an inner `import os` shadowed the module import).

## Per-rung pipeline (identical to the 14M arms)

1. SDF stage: linear-only LoRA r64/α128, dropout 0, lr 1e-4 cosine, 3%
   warmup, 2 epochs, effective batch 8, bf16, cutoff 4096, all-token loss.
2. Merge, then graft with `--noise 0`. Gate: `cos to endoftext: head 1.0000,
   embed 1.0000`. Stop if not.
3. SFT stage: A1 chat SFT, `--no-tables`, cutoff 8192 (~47 min on 4×H200
   regardless of rung).
4. Publish both adapters plus `base_row_patch.safetensors`, README and
   `adapter_config.json` base_model → `Qwen/Qwen2.5-32B`, verify the remote
   file list, then terminate the pod.
5. Eval: serve the SFT checkpoint via `serve_reconstructed.sh`, run the
   full 27-cell grid at n=100 as Alex, Sonnet 4.6 grader, temp 0.7,
   max_tokens 4096, prod=false, stop tokens 151645,151643. Then
   `validate_run.py`.

Names: adapters `Qwen2.5-32B-v45emb-nano54-{3M,28M,56M,112M}-sdf` and
`…-a1-graft0`; eval run dirs `v45emb-nano54-{rung}-graft0-a1-g27-nameAlex`
(the 14M point is `v45emb-nano54-graft0-a1-g27-nameAlex`).

## Pods and order

Two pods of 4×H200, 250 GB container disk, TCW account
(`RUNPOD_API_KEY="$RUNPOD_TCW_API_KEY"` on every pod command).

- Pod A chains 3M → 28M → 56M. Each rung: SDF, gate, graft, SFT, publish,
  verify, delete its merged/grafted dirs, next rung. Terminates itself after
  56M.
- Pod B runs 112M with the 200-step test-loss curve. Checkpoints every 500
  steps. Terminates itself after publish.

Every chain runs on the pod under nohup with a done marker; no local
watcher (the 2026-08-18 idle-pod loss came from one). Actual: pod A was
4×H100 (no H200 capacity at launch; 6.3 s/step vs 6.0, $13.96/h vs $18.36),
11:37 AM → 1:04 AM PDT; pod B 4×H200, 10:57 AM → 1:13 AM. The on-pod
self-termination failed on both (`$RUNPOD_POD_ID` is not set in an ssh
shell) — pods were terminated from the local side within minutes.

Evals on one 2×A100 pod, four rungs in sequence; `rm -rf /root/serve-<prev>`
before each swap (disk trap).

Commands (per rung; preamble on every ssh'd step):

```bash
export PATH=/root/.local/bin:$PATH; cd /root/fsdp_fa3/env; set -a; . /root/.keys; set +a
R=28M   # 3M | 28M | 56M | 112M
uv run --no-sync bash /root/fsdp_fa3/launch.sh sdf 4 \
    --corpus /workspace/data/ladder-$R.jsonl --out /workspace/out/sdf-$R \
    --test-corpus /workspace/data/ladder-test.jsonl --test-steps 0     # 200 on the 112M pod
uv run --no-sync python /root/fsdp_fa3/merge_release.py --adapter /workspace/out/sdf-$R --out /root/merged-base
uv run --no-sync python /root/fsdp_fa3/graft_terminator.py --base /root/merged-base --out /root/grafted --noise 0
uv run --no-sync bash /root/fsdp_fa3/launch.sh a1 4 --no-tables --base /root/grafted --out /workspace/out/$R-graft0-a1
```

`push_fa3.sh` stages one `SDF_CORPUS`; the other rung files and the test
set are scp'd to `/workspace/data/` separately.

## Sequence and status (all done)

1. Trainer edit; rung files; manifest; nesting and test-set exclusion
   verified (commit 6199fa4).
2. Pod B smoke with `--test-corpus`, then the 112M chain; pod A chain
   3M → 28M → 56M, then the post-hoc 14M pass.
3. Evals on two 2×A100 pods with `code/msm_eval/eval_ladder.sh` (per-arm
   Hub wait, so each pod started on a published rung and blocked only for
   the one still training): 3M+56M, 28M+112M. All four validated, 27
   conditions × 100, 2 grader errors in 28M.
4. Figure `../ImprovingPretrainingPriors/figures/results_ladder.png`
   (`plot_results.py ladder`); write-up in `ScalingLadder.md`; spend logged.

## Results

| | no SDF | 3M | 14M | 28M | 56M | 112M |
|---|---|---|---|---|---|---|
| misalignment, 27 cells | 61.2 | 45.9 | 47.7 | 44.5 | 44.4 | 44.1 |
| test loss, end of SDF | 2.701 | 1.981 | 1.857 | 1.805 | 1.757 | 1.713 |

Flat behaviour from 3M on (3M vs 112M: 1.8 pts, CI ±2.2) while test loss
keeps falling. See `ScalingLadder.md`.

## Cost — actuals (estimate was ~$710)

| item | actual |
|---|---|
| 112M rung, pod B (4×H200, 14.27 h) | $262.00 |
| 3M + 28M + 56M + post-hoc 14M, pod A (4×H100, 13.45 h) + A100 stub | $188.18 |
| eval serving, 2 × 2×A100 (~4.6 h each incl. waiting for adapters) | $29.10 |
| eval grading, 10,800 samples (measured) | $108.56 |
| **ladder total** | **$587.84** |

Per-stage timings on 4 GPUs: SDF 3M 20 min, 28M 3h17m, 56M 6h13m, 112M
12h45m; A1 stage ~46 min at every rung; test-loss pass ~24 s.

### Original estimate (~$20/h for 4×H200; 14M actuals: SDF ~1h40m, graft+SFT ~47 min)

| rung | SDF | graft+SFT | setup/publish | total |
|---|---|---|---|---|
| 3M | 0.4 h, ~$8 | 0.8 h, ~$16 | ~$4 | ~$28 |
| 28M | 3.3 h, ~$66 | 0.8 h, ~$16 | ~$5 | ~$87 |
| 56M | 6.7 h, ~$134 | 0.8 h, ~$16 | ~$5 | ~$155 |
| 112M | 13.3 h, ~$266 | 0.8 h, ~$16 | ~$8 | ~$290 |
| training | | | | **~$560** |
| eval serving, 4 rungs (2×A100, ~$9/rung) | | | | ~$36 |
| eval grading, 4 rungs (~$28/rung) | | | | ~$112 |
| **ladder total** | | | | **~$710** |

Test-loss passes add under $5 in total.

## Traps met on the way (also in the runpod-operations memory)

- The grafted dir symlinks every untouched shard and the tokenizer into
  `/root/merged-base`; deleting the merge before A1 kills A1 (cost 5 min
  on the 3M rung; chain fixed to keep it until A1 has its adapter).
- The first launcher started the chain even though the smoke failed
  (piped exit code); it now gates on `test_loss.json`.
- `$RUNPOD_POD_ID` is absent in ssh shells → self-termination fails.
- To swap the chain script mid-run: scp to `.new` + `mv`, kill only the
  chain's bash, start a waiter that resumes when the trainers exit.
- zsh does not word-split unquoted variables; two monitors and one deploy
  silently did nothing until rewritten with arrays.

## Decision log

- **Standalone 2-epoch rungs, not one constant-LR run.** Why: each rung
  gets the same cosine schedule as the trained 14M arm, so that point is
  reused for free and every rung is comparable. Confidence: high. Tradeoff:
  ~2× GPU-hours versus a single stream with checkpoints; the lane would
  also have needed no-shuffle and segment-resume for the single-stream
  design.
- **3M rung included.** Why: cheap left anchor for the curve; it is a
  prefix of the trained 14M file so no redraw. Confidence: high.
- **Same LoRA rank at every rung.** Why: the question is dose-response at
  fixed capacity. Confidence: medium that r64 is not the binding constraint
  at 112M; if the 112M end-state test loss is flat relative to 56M, that is
  the first thing to check.
- **Test loss on the 112M chain only, end-state on all rungs.** Why: the
  within-run curve needs one run; end-state points are two passes per rung.
  Confidence: high.
- **Filter unchanged despite the "principal hierarchy" rule dominating
  rejections.** Why: the prefix was filtered the same way; changing it now
  would make rungs above 14M a different corpus. Confidence: high.
- **Two pods, A chaining three rungs, B the 112M.** Why: wall time is set
  by 112M either way; three pods save ~8 h for extra idle/setup cost.
  Anastasia chose two.
