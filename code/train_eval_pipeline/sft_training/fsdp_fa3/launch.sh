#!/usr/bin/env bash
# Topology-aware launcher for the fsdp_fa3 lane — launch.sh owns the accum
# math for EVERY config (the old lane's drift between train.sh-managed and
# hand-set accum values is what this prevents).
#
#   bash launch.sh a1  8 --out /workspace/out/a1-fsdp [--smoke] [--attn sdpa]
#   bash launch.sh sdf 8 --corpus /workspace/data/sdf-corpus.jsonl --out ... [--smoke]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
stage="${1:?usage: launch.sh a1|sdf <n_gpus> [script args...]}"
ngpu="${2:?usage: launch.sh a1|sdf <n_gpus> [script args...]}"
shift 2

case "$stage" in
  a1|sdf) ;;
  *) echo "unknown stage '$stage' (want a1 or sdf)" >&2; exit 1 ;;
esac

# Effective batch stays 8 sequences on any topology (matches every arm).
if (( 8 % ngpu != 0 )); then
  echo "n_gpus=$ngpu does not divide effective batch 8" >&2; exit 1
fi
accum=$(( 8 / ngpu ))

# Containerized pods: NVLS multicast is broken; NCCL dies at the first
# barrier without this (same constraint as the old lane and instruct-sft).
export NCCL_NVLS_ENABLE=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

exec accelerate launch \
  --config_file "$here/fsdp_qwen32b.yaml" \
  --num_processes "$ngpu" \
  "$here/train_${stage}_fsdp.py" --accum "$accum" "$@"
