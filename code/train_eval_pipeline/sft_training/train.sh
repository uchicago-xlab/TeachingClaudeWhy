#!/bin/bash
# Pod-side launcher.  Usage:
#   bash train.sh lf  smoke     # 256-sample / 5-step pipeline check (~10 min)
#   bash train.sh lf            # full 2-epoch run
#   bash train.sh trl smoke
#   bash train.sh trl
#   bash train.sh push lf|trl   # upload the finished adapter to HF (run AFTER
#                               # check_junk.py says the arm is clean)
#
# Effective batch is held at 8 sequences on any topology: accumulation is
# computed as 8 / n_gpus. Smoke runs use the same multi-GPU ZeRO-3 launch as
# the full run, so they exercise the exact distributed path.
set -euo pipefail
MODE="${1:?usage: train.sh lf|trl|push [smoke|lf|trl]}"
SUB="${2:-}"
set -a; source /root/.keys; set +a
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1
export PATH=/opt/v/bin:$PATH
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# NVLS (NVSwitch multicast) is broken inside these containers on 8xH100 hosts —
# NCCL dies at the first barrier with "Cuda failure 401". NVLink P2P still
# works; verified 2026-07-31 with an 8-rank allreduce. No-op on A100 pods.
export NCCL_NVLS_ENABLE=0

NGPU=$(nvidia-smi -L | wc -l | tr -d ' ')
ACCUM=$(( 8 / NGPU ))

if [ "$MODE" = push ]; then
  ARM="${SUB:?train.sh push lf|trl}"
  [ "$ARM" = lf ] && SUFFIX=neatpack || SUFFIX=bfd
  OUT=/workspace/out/a1-$ARM REPO="SecondLookResearch/Qwen2.5-32B-elicit-A1-$SUFFIX" \
    /opt/v/bin/python - <<'PY'
import os
from huggingface_hub import HfApi
out, repo = os.environ["OUT"], os.environ["REPO"]
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(repo, exist_ok=True, private=False)
with open(f"{out}/README.md", "w") as f:
    f.write(
        f"# {repo.split('/')[-1]}\n\nA1 elicitation SFT LoRA (r64, alpha 128, "
        "dropout 0, assistant-only loss) over Qwen/Qwen2.5-32B BASE. 13k A1 mix, "
        "2 epochs, lr 1e-4 cosine + 3% warmup, cutoff 8192, ChatML template, "
        "contamination-free packing. Trained on RunPod A100s; junk-checked "
        "before upload (see repo commit description in the project logbook).\n")
api.upload_folder(folder_path=out, repo_id=repo)
print("pushed", repo)
PY
  exit 0
fi

if [ "$MODE" = lf ]; then
  # Derive the actual run config from the checked-in yaml instead of relying
  # on CLI-override behavior: set topology-dependent accum, and shrink to a
  # smoke run when asked.
  RUNCFG=/root/run-lf.yaml
  SMOKE="${SUB:-}" ACCUM="$ACCUM" /opt/v/bin/python - <<'PY'
import os, yaml
cfg = yaml.safe_load(open("/root/a1_lora_r64.yaml"))
cfg["gradient_accumulation_steps"] = int(os.environ["ACCUM"])
if os.environ["SMOKE"] == "smoke":
    cfg.update(max_samples=256, max_steps=5, output_dir="/workspace/out/smoke-lf",
               report_to="none", save_steps=1000000)
yaml.safe_dump(cfg, open("/root/run-lf.yaml", "w"), sort_keys=False)
PY
  LOG=/root/train-lf${SUB:+-$SUB}.log
  echo "=== LF ${SUB:-full}: $NGPU GPUs, accum $ACCUM -> $LOG ==="
  FORCE_TORCHRUN=1 NPROC_PER_NODE=$NGPU \
    /opt/v/bin/llamafactory-cli train "$RUNCFG" 2>&1 | tee "$LOG"

elif [ "$MODE" = trl ]; then
  if [ "$SUB" = smoke ]; then EXTRA="--smoke" OUT=/workspace/out/smoke-trl
  else EXTRA="" OUT=/workspace/out/a1-trl; fi
  LOG=/root/train-trl${SUB:+-$SUB}.log
  echo "=== TRL ${SUB:-full}: $NGPU GPUs, accum $ACCUM -> $LOG ==="
  /opt/v/bin/torchrun --nproc_per_node "$NGPU" /root/train_trl.py \
    --accum "$ACCUM" --out "$OUT" $EXTRA 2>&1 | tee "$LOG"

else
  echo "unknown mode: $MODE" >&2; exit 2
fi

echo "=== DONE (${MODE} ${SUB:-full}). Next: check_junk.py, then train.sh push, then TERMINATE THE POD. ==="
