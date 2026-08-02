---
status: resolved
---

# Training speed: why Together is faster, and which levers actually pay

Written 2026-07-31, updated 2026-08-02 with measured results. Prompted by the A1
own-hardware runs: ~51 minutes of training plus ~35 minutes of cold start per run
on 8×H100, versus noticeably faster end-to-end times on Together. Our measured
baseline: ~5,900 trained tokens/sec across the node (~14% MFU) for a packed 32B
LoRA at 8192 context under ZeRO-3.

## What Together verifiably has

Together's stack runs FlashAttention-3 on Hopper with their proprietary fused-kernel
library (Tri Dao is their chief scientist), a rebuilt data-preprocessing pipeline
they credit with 17–32% end-to-end savings, memory tech (UPipe head-chunked
attention, an FFT-based optimizer) that converts into throughput via larger
micro-batches, FP8 paths, and — least glamorous, most transferable — warm pools
with pre-cached weights and tuned NCCL. Sources: their fine-tuning platform post,
product page, and the FA3 paper. One caveat cuts the other way: Together's packing
is not contamination-safe, which is where the terminator-confetti saga started
(see A1TerminatorContamination.md — the confetti root cause turned out to be
elsewhere, but their packing remains the naive kind).

## The levers, measured on our hardware (2026-07-31 / 08-02)

Replicated-base DDP (drop ZeRO-3 for LoRA): does not fit. Each rank OOM'd at ~74GB
during model load — a 64GB bf16 replica plus buffers exhausts an 80GB card before
activations. Needs H200/B200-class memory or a quantized base; on 80GB, ZeRO-3
keeps its job.

Preprocessing-cache reuse: worthless at our scale. Tokenizing the full 13k mix
takes ~24 seconds; LF re-tokenizes each run unless `tokenized_path` is set, and it
is not worth setting. Together's preprocessing gains are a big-data phenomenon.

FlashAttention-3: built, correctness-verified, and no faster here. Full CUDA-13
environment (torch 2.13+cu130, transformers 5.14.1, kernels 0.15.2, LF 0.9.5 with
three documented patches — all encoded as the `lf-fa3` arm of `a1_stack/setup.sh`),
validated by exact packed-segment logit equivalence (max diff 0.0000). Steady
state: 11.0 s/step vs 11.1 for FA2. At 8192-token context under ZeRO-3, attention
is ~15–20% of step time; MLP GEMMs and weight-gather traffic dominate. FA3 starts
paying only when individual documents are long (16k+) — note that packing short
conversations into longer packs does not count, since with proper isolation the
attention cost follows conversation length, not pack length.

The memory ledger (byproduct finding that matters more than the levers): at 8192
tokens on 80GB cards, checkpointed activations ~11GB + logits/loss ~12GB + ZeRO-3
buffers put 8-way shards at ~79–80GB — it fits by luck. 4-way does not fit. Run
32B LoRA at 8-way or wider on 80GB, and treat "it ran" as ~1GB from OOM until
measured. The real memory lever at the head is a chunked/fused cross-entropy —
precisely the kind of kernel Together builds.

## The lever that pays: the prebaked image

~25 of our ~35 cold-start minutes are dependency installs, repeated on every fresh
pod and after every stop/start. `a1_stack/Dockerfile` bakes both proven venvs into
an image; `create_pod.sh` takes `IMAGE_NAME=...` and `setup.sh` auto-detects baked
venvs and collapses to data staging plus the ~10-minute weight download. Status:
code complete and checked; the image itself still needs one `docker build && push`
from a machine with Docker (none on the laptop).

## Still open

Pull actual wall-clock times of our Together jobs from their dashboard/API so the
"how much faster" comparison gets exact numbers. Beyond the image, remaining gaps
to a managed service are their kernels and zero provisioning — not worth chasing
at our run volume.
