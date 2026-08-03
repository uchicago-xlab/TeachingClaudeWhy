---
status: active
---

# Training playbook — how we train 32B SFT models

The single living note for own-hardware training. Consolidates and supersedes
TogetherTrainingSpeed.md (absorbed here 2026-08-03), and carries the current state
of SupervisedFinetuningPipeline.md and TrainingStackComparison.md (both kept as
historical reference). The confetti incident that shaped half of these rules has
its own record: [A1TerminatorContamination.md](A1TerminatorContamination.md).

## Current stack

`code/train_eval_pipeline/sft_training/` — LLaMA-Factory + DeepSpeed ZeRO-3 on
RunPod, driven by pod-lifecycle scripts (create/push/setup/train/watch, see its
README and TEAM_QUICKSTART). The canonical config is `a1_lora_r64_fix1.yaml`:
r64/α128, dropout 0, assistant-only loss, lr 1e-4 cosine + 3% warmup, 2 epochs,
cutoff 8192, effective batch 8, neat_packing, and LoRA on `embed_tokens` +
`lm_head` — the last item is mandatory for any chat SFT from Qwen base (untrained
tied token-table rows; see the incident note). Two environment lanes, one config:
the default FA2/cu124 lane (`setup.sh lf`) and a verified FA3/CUDA-13 lane
(`setup.sh lf-fa3`, no speed gain at 8k context — for future long-document work).
Cold starts use the prebaked image `ghcr.io/anastasiakwei/sft-training:v1`
(validated 2026-08-03: setup 104 s vs ~25 min stock; rebuild instructions in the
Dockerfile).

## Rules that are load-bearing

Train 32B LoRAs at 8-way or wider on 80GB cards: the memory ledger at 8192-token
packs (checkpointed activations ~11GB + logits/loss ~12GB + ZeRO-3 buffers +
shards) sits ~1GB from OOM at 8-way and does not fit at 4-way; full-replica DDP
does not fit at all (all measured). Smoke-test on the full topology before every
long run. Every adapter passes the strict junk test (`check_junk.py`:
foreign-script-anywhere + eos-stop rate + trailing, worst wins) before release.
Serving for tests and evals: merge table-LoRA adapters before vLLM, pass
`stop_token_ids=[151645, 151643]` per request, connect through SSH tunnels never
the RunPod proxy. Pod operational lore (CUDA pins, kill hygiene, ghost GPU
contexts, restart behavior, cost rules) lives in the sft_training README
troubleshooting section.

## Speed: what we measured against the Together comparison

Our baseline is ~5,900 trained tokens/sec on 8×H100 (~14% MFU) for the packed 32B
LoRA. Together is faster end-to-end via FA3+custom kernels, rebuilt preprocessing,
memory tech that buys bigger micro-batches, and warm pools with zero cold start.
Of the levers we could copy, measurement killed three and kept one:

- Replicated-base DDP (no ZeRO-3): does not fit on 80GB — OOM at ~74GB during
  model load. Needs H200/B200 or a quantized base.
- Preprocessing-cache reuse: tokenizing the 13k mix takes ~24 s; nothing to save.
- FlashAttention-3: correct (exact packed-segment logit equivalence, diff 0.0000)
  and speed-neutral — 11.0 vs 11.1 s/step. At 8k context under ZeRO-3, attention
  is ~15–20% of step time; GEMMs and weight-gather dominate. Worth revisiting only
  for genuinely long documents (16k+); longer packs of short chats do not qualify,
  since isolated-segment attention cost follows conversation length.
- The prebaked image: the one lever that pays. ~25 min of installs per pod start
  reduced to seconds; done and validated.

Packing itself is safe and fast (51 min vs 3.5 h unpacked for the same tokens) now
that the tables are trainable — the historical "packing causes junk" story is dead
(incident note). Remaining unmeasured: exact wall-clocks of our Together jobs
(their dashboard has them) if we ever want the comparison to be precise.

## How we got here (short history)

Jul 9–20: stack survey for a possible B200/gemma-4 direction
(TrainingStackComparison.md) and a TRL-based pipeline with an Olmo-3/Tulu detour
(SupervisedFinetuningPipeline.md, evaluationolmo3initial100k.md); base-model
choice settled on Qwen2.5-32B (BaseModelSelection.md). Jul 27–28: first
own-hardware runs (r128) on 2×A100, LF + ZeRO-3. Jul 31–Aug 2: the a1_stack build,
the confetti investigation and fix, the speed A/Bs, the FA3 lane, the image —
stack renamed to sft_training. Together remains an option for quick throwaway
LoRAs, with its known naive packing and per-token pricing.

## Open

Petri evals integrate against served adapters — the serving rules above apply
verbatim (a `code/petri_eval/` stub with them is on offer). The stopped H100 pod
`bmsg8y72luulm1` (~$2/day) awaits a reuse-or-delete decision.
