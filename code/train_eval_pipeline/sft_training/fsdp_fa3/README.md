# fsdp_fa3 — new training lane: TRL + accelerate/FSDP + FlashAttention-3

A parallel lane to the LLaMA-Factory/ZeRO-3 stack one directory up. Nothing
in the old lane is modified; it stays canonical until this lane passes its
gates (below). The recipe is byte-for-byte the same — r64/α128, dropout 0,
lr 1e-4 cosine, 3% warmup, 2 epochs, effective batch 8 sequences, bf16,
assistant-only loss for A1, all-token loss for SDF — so results stay
comparable with the existing arms. Only the infrastructure changes.

## Why this lane exists (decision log)

- **FSDP instead of DeepSpeed ZeRO-3.** What: accelerate FSDP FULL_SHARD,
  config in `fsdp_qwen32b.yaml` (adapted from the proven Olmo config on the
  `instruct-sft` branch; layer class changed to `Qwen2DecoderLayer`).
  Why: ZeRO-3's uniform-dtype assert is the root cause of the table-LoRA
  workaround and its 3GB adapters; FSDP has no such assert, and it takes
  `use_reentrant=False` checkpointing (the modern default) where ZeRO-3
  forced the reentrant path. Confidence: high that it trains (proven at 32B
  on the same pods), medium that memory behaves at 8192 ctx — smoke gate
  decides. Tradeoff: a second sharding stack to understand.
- **FlashAttention-3 with an sdpa escape hatch.** What: `--attn` flag,
  default `flash_attention_3`, fallback `sdpa`. Why: FA3 avoids the
  transformers-5.6.0 FA2 crash by not being FA2, and Brandon measured a
  large speedup with packing on H200. Confidence: medium — the s_aux
  None-check bug lives in the transformers FA integration layer and it is
  NOT verified that the FA3 path is clean for Qwen2 on 5.6.0; the 5-step
  smoke exists exactly to answer this. If it crashes at step 0, run with
  `--attn sdpa` and lose nothing versus the old lane.
- **TRL instead of patched LLaMA-Factory.** What: plain TRL SFTTrainer,
  extending the existing `train_trl.py` arm. Why: the old lf-fa3 lane
  needs three documented library patches and `DISABLE_VERSION_CHECK=1`;
  this lane needs zero patches. TRL BFD packing gives per-example
  isolation equivalent to `neat_packing`. Confidence: high — the TRL arm
  already reproduced the LF recipe once.
- **Token tables still trained via LoRA targets, not `modules_to_save`.**
  What: `embed_tokens` + `lm_head` stay in `target_modules` for A1.
  Why: identical math to the released tablefix recipe, so `check_junk.py`
  expectations and arm comparability carry over unchanged. FSDP would also
  allow `modules_to_save`; not taken now to change one variable at a time.
- **Terminator graft arm (`graft_terminator.py`).** What: copy
  `<|endoftext|>`'s rows onto `<|im_end|>` in both token tables of a base
  copy, rotated by small noise (norm kept, cos ≈ 0.995 — separable, unlike
  the old lane's bit-identical copy), then train linear-only on it:
  `launch.sh a1 8 --no-tables --base <grafted>`. Why: table training fixed
  stopping but cost agent behaviour (table-lora-debug findings), so this
  arm repairs ONLY the two defective rows and trains no table at all —
  the cleanest test of "the defect is just these rows". Confidence:
  medium — the bit-identical precedent (runE) acted 170/180, the noisy
  variant is new. Tradeoff: the base changes, so runs on it are their own
  arm, and releases ship `base_row_patch.safetensors` for
  `../apply_row_patch.py` instead of a 62GB base.
- **Row-delta arm (`--train-rows`, rows.py).** What: linear-only LoRA
  plus tiny trainable deltas on the terminator rows alone — `<|im_end|>`
  and `<|endoftext|>` in both tables, `<|im_start|>` in the embed table
  only (it must be read, never emitted) — at `--rows-lr` 1e-5 vs 1e-4 for
  the linears; `merge_release.py --row-deltas` bakes the deltas into the
  released rows. Why: a LoRA table delta is a coupled update that moves
  every row — the leading suspect for the table-LoRA acting damage. Here
  gradient descent picks the repair direction while the other ~151,930
  rows provably cannot move. Complements the graft arm: repair found by
  training vs repair set by hand, both with zero collateral movement.
  Confidence: medium — clean math, but the hook + optimizer-group combo
  is untested under FSDP; 5-step smoke gates it. Tradeoff: novel
  parameterization; the loss must stay plain nll (fused losses bypass
  the lm_head hook, so `--liger` is rejected).
- **Merge + config repair is one step.** What: `merge_release.py` merges
  the adapter and writes a corrected `generation_config` (eos/stop =
  151645, 151643) plus the ChatML tokenizer into the released model.
  Why: kills the per-request `stop_token_ids` footgun and replaces the
  fix_export/row-patch script pile for this lane — PEFT's own
  `merge_and_unload` is the only merge path.

## Environment

Reuse Brandon's uv project from the `instruct-sft` branch
(`instruct_sft/pyproject.toml` + `uv.lock`): torch cu13 wheels, FA3 built
from source with `cuda-toolkit-13-3` (NOT the full `cuda` package), and
`TMPDIR=/workspace/tmp uv sync` so the build doesn't fill the root volume.
His notes.md on that branch documents the traps. `NCCL_NVLS_ENABLE=0` is
still required on containerized pods. FA3 needs no library patches — if
`--attn flash_attention_3` fails the import gate or the smoke, fall back
to `--attn sdpa`; the FSDP benefits are independent of the attention impl.

## Run recipe

```bash
cd code/train_eval_pipeline/sft_training/fsdp_fa3

# SDF stage 1 (continued pretraining, all-token loss, cutoff 4096):
bash launch.sh sdf 8 --smoke --corpus /workspace/data/sdf-corpus.jsonl --out /workspace/out/sdf-fsdp-smoke
bash launch.sh sdf 8 --corpus /workspace/data/sdf-corpus.jsonl --out /workspace/out/sdf-fsdp

# merge stage 1 into the base (no --chat: keep base-model config):
python merge_release.py --adapter /workspace/out/sdf-fsdp --out /workspace/merged/sdf-base

# A1 stage 2 (chat SFT, assistant-only loss, cutoff 8192), on base or merged:
bash launch.sh a1 8 --smoke --out /workspace/out/a1-fsdp-smoke
bash launch.sh a1 8 --base /workspace/merged/sdf-base --out /workspace/out/a1-fsdp

# release merge (--chat: ChatML tokenizer + eos/stop baked into generation_config):
python merge_release.py --base /workspace/merged/sdf-base --adapter /workspace/out/a1-fsdp --out /workspace/merged/a1-final --chat

# terminator-graft arm: patch the base once, then linear-only on top of it:
python graft_terminator.py --base /workspace/models/qwen2.5-32b --out /workspace/models/qwen-graft
bash launch.sh a1 8 --smoke --no-tables --base /workspace/models/qwen-graft --out /workspace/out/a1-graft-smoke

# row-delta arm: only the terminator rows train (lr 1e-5), from the stock base:
bash launch.sh a1 8 --smoke --train-rows --out /workspace/out/a1-rows-smoke
python merge_release.py --adapter /workspace/out/a1-rows --out /workspace/merged/a1-rows --chat --row-deltas /workspace/out/a1-rows/row_deltas.safetensors
```

## Continuing from a published checkpoint

For anyone adding SFT on top of our released arms.

**Which checkpoint to start from**

- Additional SFT on the validated platform → `SecondLookResearch/Qwen2.5-32B-graft0-a1`
  (2.16GB, ships its own `base_row_patch.safetensors`). This is the arm
  validated on MSM's full 27-condition grid: 54.3% misaligned, 98% acting,
  zero junk, signal in all 27 cells.
- A new A1 arm on an SDF base → `SecondLookResearch/Qwen2.5-32B-sdf-named-claude-14M`
  or `-qwen-14M`. These carry no row patch, so you apply the graft yourself.
- **Do not build on any adapter without `graft0` in the name.** Everything
  else predates the terminator fix and was trained on a base whose
  `<|im_end|>` was never trained, so it cannot reliably end a turn.

**You cannot stack a second LoRA on a first.** The pattern is: merge the prior
adapter into the base, apply the graft, then train a *fresh* adapter.

```bash
# 1. pod (H200 capacity usually needs several create retries)
CONTAINER_DISK_GB=250 bash create_pod.sh <name> 4 --gpu-type "NVIDIA H200"
KEYS_FILE=~/.env bash push_fa3.sh <name>
ssh … "bash /root/fsdp_fa3/setup_fa3.sh"          # must print FA3-SETUP-OK

# 2. merge what you're continuing from (no --chat at this stage)
uv run --no-sync python merge_release.py --base <stock-snapshot> \
    --adapter <prior-adapter-dir> --out /root/merged-base

# 3. graft BEFORE training — the adapter must be trained against the grafted
#    base, not have the graft bolted on afterwards
uv run --no-sync python graft_terminator.py \
    --base /root/merged-base --out /root/grafted --noise 0

# 4. train. --no-tables is REQUIRED: the graft already repaired the
#    terminator, and training the token tables reintroduces the acting damage.
uv run --no-sync bash launch.sh a1 4 --no-tables \
    --base /root/grafted --out /workspace/out/<arm>
```

**Gate at step 3.** `graft_terminator.py` prints head norm 1.0043, embed norm
1.4780, cos 1.0000 — the stock-base figures. Different numbers mean a prior
stage modified the token tables; stop and work out why before training.

**Publish before terminating the pod.** Copy `base_row_patch.safetensors` into
the output dir, overwrite the PEFT-generated README (it stamps the local
training path into `base_model`, which the Hub rejects — set
`Qwen/Qwen2.5-32B`), push to a public SecondLookResearch repo, and **verify the
remote file list contains `adapter_model.safetensors`, `adapter_config.json`
and `base_row_patch.safetensors` before deleting anything.** We lost one arm's
weights by terminating on an unverified upload. Push adapters, never merged
models: the adapter plus a 20KB patch rebuilds the 65GB model exactly.

**Traps that have each cost hours**

- Always `uv run --no-sync`; plain `uv run` re-syncs and replaces the prebuilt
  FA3 wheel with a 45-minute source rebuild.
- Merge to `/root` (container disk), never `/workspace` — that is MooseFS, and
  a default 50GB shard wedged the writer indefinitely with no error.
- Pass `max_shard_size="5GB"`.
- `HF_HUB_DISABLE_XET=1` plus a retry loop: downloads fail by stalling, not by
  erroring, including a 175KB/s trickle too slow to trip any timeout.
- Detect stalls by byte growth, never by "the process is alive".

**Fixed recipe — do not change, comparability depends on it:** LoRA r64 / α128,
dropout 0, lr 1e-4 cosine, 3% warmup, 2 epochs, effective batch 8, bf16, cutoff
8192, assistant-only loss. `launch.sh` owns the accumulation math; pass the GPU
count and nothing else.

**Afterwards:** `code/msm_eval/serve_reconstructed.sh` rebuilds and serves any
arm from its adapters plus row patch; eval settings are pinned in the "Exact
reproduction" section of `code/msm_eval/README.md`.

## Gates before this lane replaces the old one

1. 5-step smoke per stage on the target topology — catches the FA3/5.6.0
   question and any FSDP wrap/memory surprise at step 0, ~10 min.
2. Full A1 run; loss curve overlays the known-good LF run (same data, same
   effective batch — curves should track within noise).
3. Merged model passes `../check_junk.py` CLEAN, served with NO per-request
   stop_token_ids override — proving the generation_config repair works.
4. Peak memory logged; only then decide whether 4-way launches are back.
