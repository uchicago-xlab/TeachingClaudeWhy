# Handoff: terminator-defect fixes on the fsdp_fa3 lane

> **SUPERSEDED — 2026-08-17. Read as history, not as instructions.**
>
> Two sections below will actively mislead you:
>
> - **"Fix candidates for the new session"** presents an open question that is
>   settled. Candidate 3 with `--noise 0` (graft0 — a bit-exact copy of
>   `<|endoftext|>`'s rows onto `<|im_end|>`, then linear-only LoRA) won, at
>   92% acting against 89% and 55% for the alternatives, and is now the
>   validated platform (54.3% misaligned across MSM's full 27-condition grid,
>   signal in all 27 cells). Do not re-open it.
> - **"Operational state and rules" → the eval recipe** points at
>   `run_eval.py` and `serve_eval.sh`, i.e. `code/misalignment_eval`. That is
>   the WRONG harness, and following it produces numbers that cannot be
>   compared to the results table. This mistake already happened once and
>   forced a full re-run. The standard harness is **`code/msm_eval`** — see
>   its README for the settings that must never change, and
>   `serve_reconstructed.sh` for serving from adapters.
>
> The pods named below are long gone. Current task handoff:
> `Redo14MHandoff.md` in this directory.

Written 2026-08-06 for a fresh session. Goal there: implement and test fixes
for the terminator defect on the new training lane. Everything below is
verified this session unless marked open.

## The lane

`code/train_eval_pipeline/sft_training/fsdp_fa3/` — TRL + accelerate FSDP
FULL_SHARD + FlashAttention-3, torch 2.13/cu130, transformers 5.14.1 (no
s_aux bug — that was 5.6.0-only). Parallel to, not replacing, the
LLaMA-Factory/ZeRO-3 lane one directory up. Recipe constants shared with every
arm: LoRA r64/α128, dropout 0, lr 1e-4 cosine, 3% warmup, 2 epochs, effective
batch 8 (launch.sh owns accum = 8/n_gpus), bf16, cutoff 8192 (A1) / 4096 (SDF).

Files: `train_a1_fsdp.py` (chat SFT, assistant-only loss, BFD packing,
`--no-tables` flag for linear-only arms), `train_sdf_fsdp.py` (stage:
pt-equivalent), `launch.sh`, `setup_fa3.sh` (pod env; prebuilt wheel in
`wheels/` makes setup 3m30s), `merge_release.py` (merge + bake eos
151645/151643 into generation_config; `--chat` for A1 releases),
`serve_eval.sh` (vLLM on a separate cheap pod), `probe/` (this session's
analysis scripts + `cluster_ids.json` = the 1,960 emittable zero-embed IDs).

Hard-won constraints: after `setup_fa3.sh`, always `uv run --no-sync` (plain
`uv run` re-syncs and replaces the prebuilt FA3 wheel with a source rebuild).
PEFT model must be cast to bf16 before the trainer (FSDP flat-param uniform
dtype — same constraint as ZeRO-3; "pure bf16" LoRA is the workaround FSDP
allows). TRL 1.8 needs `loss_type="nll"` when lm_head is LoRA-wrapped.
`WANDB_PROJECT` is still unset (runs land in "huggingface" project).

## Runs so far

- Table-LoRA smoke (fa3-smoke pod): loss 0.894 @ 5 steps — matches LF 0.92.
- Full no-tables A1 (a1-notables pod): 45m22s on 4×H200, train_loss 0.804,
  W&B run ekwiy8rg. Merged: `AnastasiaWei/tcw-a1-fa3-notables-32b` (private HF).
- Eval (30 epochs × 5 cells, leaking/murder × replacement/restriction +
  exfiltration:replacement): pooled harmful 26/150 = 0.173 ± 0.031, but
  **acted only 61/150**; harm|acted 26/61 ≈ 43% ≈ healthy-arm rate. Junk
  suppresses acting, not misalignment. Logs
  `data/misalignment-eval/logs/a1-fa3-notables-nt/`, viewer updated
  (`a1-fa3-notables-nt`, deployed to msm-eval-viewer Space).
- Junk composition (transcript analysis): ~99% valid-unicode foreign script
  (Thai = 89% of junk chars), only ~0.7% mojibake (U+FFFD). Junk starts in
  the first half of output in 73/89 non-acted samples.

## NEW weight-level findings (2026-08-06, revises the July theory)

Measured directly on Qwen2.5-32B base shards (script `probe/count_cluster3.py`):

1. `embed_tokens`: **2,359 rows are exactly zero** — 1,960 emittable vocab
   tokens (incl. `<|im_start|>`/`<|im_end|>` and 19 other reserved specials)
   + 399 padding rows past the tokenizer vocab. (A norm<0.2 band adds ~1,400
   weakly-trained rows → 3,788; the old "5575" figure matches neither.)
2. `lm_head`: those same tokens are NOT zero — they all share **one common
   direction** (pairwise cos 1.0000, norm 0.3716 ± 0.0000, vs ~1.26 mean for
   trained rows). Identical logits up to bf16 noise = the tie is real, but
   it is geometric, not bit-identity (bit-compare finds nothing).
3. `<|endoftext|>` is trained in both tables (embed 1.478, head 1.004).
4. cos(shared untrained direction, endoftext row) = **−0.478**: raising the
   cluster's logit actively suppresses the one working terminator.
5. Consequence: at a boundary, `<|im_end|>` wins ≈ 1/1960 of cluster draws at
   temp 1 — clean stops via im_end are luck; past "clean" linear-only runs
   (e.g. runE-endoftext-linear: acted 170/180) stopped via `<|endoftext|>`.

PROBE RESULTS (done 2026-08-06, 25 generations × 1536 tokens, no grader):

- **35.8% of ALL sampled tokens are cluster members** (13,314/37,236) —
  the cluster is not just the onset trigger, it is most of the junk volume.
  With ~1,960 tied members at p ≈ e^-7.9 ≈ 3.7e-4 each, the cluster
  collectively holds the MAJORITY of probability mass at degenerate
  positions while no single member cracks the top-20.
- Onset tokens: 24/25 generations sampled ≥1 cluster member; sampled
  onset logprobs sit at −7.9 ± ~0.1 across generations — the tie
  signature, measured. `<|im_end|>` was in the top-20 at onset 0/24 times:
  it can never be preferred WITHIN the cluster, only the cluster as a whole.
- `<|im_end|>` was eventually sampled (by cluster lottery) in 3/25
  generations — and all 3 finished with `finish_reason: stop`. **The baked
  generation_config stops work in vLLM.** The other 22 ran to the length cap.
- `<|endoftext|>` was sampled 0/25 and never appeared in any top-20 —
  the −0.478 anti-correlation in action; the escape hatch never fires on
  this arm. Fix candidate 4 (--terminator endoftext) must TRAIN toward
  endoftext, not merely allow it at inference.

## Fix candidates for the new session (verified context per option)

1. **Table LoRA** (`train_a1_fsdp.py` default, no flag): proven on this lane
   at smoke scale; adapter 7.9GB (PEFT saves full embed tables); merge
   mandatory before serving. The known-good fix; costs adapter size.
2. **`modules_to_save=["embed_tokens","lm_head"]`**: now viable under FSDP
   (the blocker was ZeRO-3's dtype assert, and pure-bf16 casting is already
   in the trainer). Untested — needs a smoke. Trains full tables (not
   low-rank deltas); with embed rows starting at exact zero this is arguably
   the *right* parameterization.
3. **Surgical row init before linear-only SFT**: set im_end's lm_head row to
   something separable (e.g. copy endoftext's row, or mean of trained rows +
   noise) and its embed row nonzero, then train linear-only. Cheap, tiny
   adapters, but changes the base — document as its own arm. Old-lane
   precedents: `make_repaired_base.py`, `apply_row_patch.py` one dir up.
4. **Retarget the terminator to `<|endoftext|>`** in the chat template for
   training + eval (runE-endoftext-linear precedent acted 170/180): no table
   training at all, but nonstandard ChatML — eval/serving must match.
5. Whatever the probe says about vLLM honoring baked stops may add/remove an
   eval-side mitigation.

## Operational state and rules

- Pod `a1-notables` (id j9f45mex75yia5, 4×H200, TCW key): **STOPPED**, keep
  it that way unless training; volume holds merged model + adapter; container
  disk (env) is gone on restart — rerun setup_fa3.sh (3m30s with wheel).
- Pod `probe-a1` (id limn0ppfn2nlnu, 2×A100): running the probe this
  session; the OLD session terminates it. If you see it alive and idle,
  terminate it (TCW key).
- Keys: repo `.env` — `RUNPOD_TCW_API_KEY` (use for all pods),
  `HF_TOKEN`, `WANDB_API_KEY`, `OPENROUTER_API_KEY` (grader).
- Rules that bind you: never launch paid runs without Anastasia's explicit
  go (present cost first); never commit without approval and never add
  Claude as co-author; log every paid task to
  `notes/Project/Planning/spending.json` on completion; STE100-style
  readable reports.
- NOTHING from the last two days is committed: the whole fsdp_fa3 lane, the
  eval logs, viewer changes, spending entries, this handoff. Propose one
  snapshot commit before building fixes on top.
- Eval recipe that works end to end: serve merged model via `serve_eval.sh`
  on a 2×A100 pod ($3.18/h), SSH tunnel 8000, then
  `run_eval.py --model openai/a1-eval --model-base-url
  http://127.0.0.1:8000/v1 --condition <scenario:goal:urgency> --epochs N`
  (OPENAI_API_KEY=any non-empty string; conditions used this session:
  leaking/murder × replacement/restriction + exfiltration:explicit:replacement).
