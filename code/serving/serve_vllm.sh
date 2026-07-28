#!/usr/bin/env bash
# Serve Qwen3-14B + our difficult-advice LoRA adapter(s) from one vLLM process.
#
# Runs ON THE POD, not on your laptop. Paste it into the RunPod web terminal (or
# `git clone` the repo there and run this file). Every eval arm — base and each
# adapter — comes off this single server as its own model id, so one GPU covers
# the whole comparison.
#
#   VLLM_API_KEY=... HF_TOKEN=... ./serve_vllm.sh
#
# Serving several checkpoints at once: set ADAPTER_SPECS to space-separated
# `name=source` pairs, where source is either a directory already on the pod or
# a HF repo id to download into /workspace/adapters/<name>.
#
#   ADAPTER_SPECS="qwen3-14b-da-nano-v2=/workspace/adapters/qwen3-14b-da-nano-v2 \
#                  qwen3-14b-da-haiku45-v1=SecondLookResearch/Qwen3-14B-difficult-advice-haiku45-sdf-v1-lora" \
#     VLLM_API_KEY=... ./serve_vllm.sh
#
# Everything is overridable by environment variable; see the block below.
set -euo pipefail

BASE_MODEL=${BASE_MODEL:-Qwen/Qwen3-14B}
ADAPTER_REPO=${ADAPTER_REPO:-SecondLookResearch/Qwen3-14B-difficult-advice-sdf-v1-lora}
ADAPTER_NAME=${ADAPTER_NAME:-qwen3-14b-da-sdf-v1}
ADAPTER_DIR=${ADAPTER_DIR:-/workspace/adapters/${ADAPTER_NAME}}
# Default to the single-adapter form above, so existing invocations are unchanged.
ADAPTER_SPECS=${ADAPTER_SPECS:-${ADAPTER_NAME}=${ADAPTER_DIR}}
PORT=${PORT:-8000}
# 0.0.0.0 for the RunPod HTTP-proxy flow. Set HOST=127.0.0.1 when you reach the
# pod over an SSH tunnel instead — then the server is not publicly reachable at all.
HOST=${HOST:-0.0.0.0}
# Keep weights off the container overlay, which is typically ~30 GB and too small.
export HF_HOME=${HF_HOME:-/workspace/hf}
# The eval sends ~2.4k-token prompts and allows 4k completion tokens. 16k leaves
# headroom for the longer exfiltration templates without eating KV cache.
MAX_MODEL_LEN=${MAX_MODEL_LEN:-16384}
GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION:-0.90}

# NB: bash parses quotes inside ${VAR:?word}, so keep apostrophes out of these messages.
: "${VLLM_API_KEY:?set VLLM_API_KEY — the RunPod proxy URL is reachable by anyone who knows it}"

echo "vllm: $(vllm --version 2>&1 | tail -1)"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

# One GPU, deliberately. Two PCIe cards trip a vLLM custom-all-reduce deadlock
# this team has already paid for once (spending log, 2026-07-15: 2.3h at 100%
# GPU generating nothing). A 14B in bf16 fits one 48 GB card with room to spare,
# so pin to GPU 0 unless the caller has chosen otherwise. If you ever do need
# 2×, the recorded fix is --disable-custom-all-reduce plus NCCL_P2P_DISABLE=1.
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"

# Pre-download rather than handing vLLM the repo id directly: a bad token fails
# here with an obvious error instead of 20 minutes into server startup, and a
# restarted server reuses the copy on disk.
#
# HF_TOKEN is only needed on this path. If the adapter is already on the pod —
# scp it and you never put an org-scoped credential on rented hardware — the
# server starts without one.
LORA_RANK=0
LORA_MODULE_ARGS=()
N_ADAPTERS=0
for spec in ${ADAPTER_SPECS}; do
    name=${spec%%=*}
    source=${spec#*=}
    if [ "${name}" = "${spec}" ] || [ -z "${source}" ]; then
        echo "ADAPTER_SPECS entry is not name=source: ${spec}" >&2
        exit 1
    fi

    if [ -d "${source}" ]; then
        dir=${source}
    else
        dir=/workspace/adapters/${name}
        if [ ! -f "${dir}/adapter_config.json" ]; then
            : "${HF_TOKEN:?set HF_TOKEN — the adapter repo is private, or scp the adapter to the pod instead}"
            echo "downloading ${source} -> ${dir}"
            hf download "${source}" --local-dir "${dir}"
        fi
    fi

    if [ ! -f "${dir}/adapter_config.json" ]; then
        echo "no adapter_config.json in ${dir} (from spec ${spec})" >&2
        exit 1
    fi

    # Must match each adapter's `r` — the server needs the max across all of
    # them. Read it rather than hardcoding 64, so a different checkpoint doesn't
    # fail with a confusing rank error.
    rank=$(python3 -c "import json;print(json.load(open('${dir}/adapter_config.json'))['r'])")
    [ "${rank}" -gt "${LORA_RANK}" ] && LORA_RANK=${rank}
    echo "adapter ${name}: ${dir} (rank ${rank})"
    LORA_MODULE_ARGS+=("${name}=${dir}")
    N_ADAPTERS=$((N_ADAPTERS + 1))
done
echo "serving ${N_ADAPTERS} adapter(s) at max rank ${LORA_RANK}"

# NOTE: deliberately no --reasoning-parser. We always drive this server with
# chat_template_kwargs={"enable_thinking": false}, so the model emits no <think>
# block and there is nothing to parse. Enabling a reasoning parser here risks the
# response arriving with the text in `reasoning_content` and `content` empty,
# which the eval would silently score as a non-answer.
exec vllm serve "${BASE_MODEL}" \
    --served-model-name "${BASE_MODEL}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --api-key "${VLLM_API_KEY}" \
    --dtype bfloat16 \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --enable-lora \
    --max-lora-rank "${LORA_RANK}" \
    --max-loras "${N_ADAPTERS}" \
    --lora-modules "${LORA_MODULE_ARGS[@]}" \
    --enable-prefix-caching
