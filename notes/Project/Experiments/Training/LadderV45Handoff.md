# Scaling ladder — v4.5 nano embodiment, 3M → 112M

Written 2026-09-14. Plan agreed with Anastasia the same day; nothing paid has
launched yet. This is the source of truth for the ladder runs. The recipe is
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
| 3M | `sdf-v45emb-nano54-ladder-3M.jsonl` | 2,410 | 3,001,105 | to train |
| 14M | `sdf-v45emb-nano54-14M.jsonl` | 11,359 | 13,999,156 | **trained + evaluated** (v45emb-nano54 arm) |
| 28M | `sdf-v45emb-nano54-ladder-28M.jsonl` | 22,686 | 27,998,799 | to train |
| 56M | `sdf-v45emb-nano54-ladder-56M.jsonl` | 45,373 | 55,996,898 | to train |
| 112M | `sdf-v45emb-nano54-ladder-112M.jsonl` | 90,945 | 111,994,101 | to train |

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
- 14M arm: trained before the flag existed. Load
  `SecondLookResearch/Qwen2.5-32B-v45emb-nano54-14M-sdf` on whichever pod
  finishes first and run one pass (~10 min).

All end-state points are taken at the same place, after SDF and before
graft/SFT, so they are comparable with each other and with the 112M curve.
Caveat for the plot: the 112M curve at 28M tokens is mid-schedule at high LR
and is not the 28M rung's end state; the end-state points are what compare
across rungs.

The test-loss code paths are untested on a pod. The smoke run (step 3
below) exercises them before any paid rung.

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
watcher (the 2026-08-18 idle-pod loss came from one). Wall time ≈ 16 h, set
by the 112M rung.

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

## Sequence and status

1. [done 2026-09-14] Trainer edit; rung files; manifest; nesting and
   test-set exclusion verified.
2. [pending approval] Commit: trainer edit, build script, manifest,
   `generate_stories.py` retry patch, spending entry.
3. Pod B: create, push lane, smoke run with `--test-corpus` (~15 min).
4. Launch Pod A chain and Pod B chain.
5. 14M end-state test loss on the first pod to finish.
6. Serve + eval the four new rungs.
7. Plot: rate vs log tokens with the baseline line; test-loss panel with
   the 112M curve, five end-state points, base-model reference.
8. Log every task in `spending.json`.

## Cost estimate (~$20/h for 4×H200; 14M actuals: SDF ~1h40m, graft+SFT ~47 min)

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
