#!/usr/bin/env bash
# Serve Qwen3-14B + our difficult-advice LoRA adapter from one vLLM process.
#
# Runs ON THE POD, not on your laptop. Paste it into the RunPod web terminal (or
# `git clone` the repo there and run this file). Both eval arms — base and
# adapter — come off this single server as two model ids, so one GPU covers the
# whole comparison.
#
#   VLLM_API_KEY=... HF_TOKEN=... ./serve_vllm.sh
#
# Everything is overridable by environment variable; see the block below.
set -euo pipefail

BASE_MODEL=${BASE_MODEL:-Qwen/Qwen3-14B}
ADAPTER_REPO=${ADAPTER_REPO:-SecondLookResearch/Qwen3-14B-difficult-advice-sdf-v1-lora}
ADAPTER_NAME=${ADAPTER_NAME:-qwen3-14b-da-sdf-v1}
ADAPTER_DIR=${ADAPTER_DIR:-/workspace/adapters/${ADAPTER_NAME}}
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

# Pre-download rather than handing vLLM the repo id directly: a bad token fails
# here with an obvious error instead of 20 minutes into server startup, and a
# restarted server reuses the copy on disk.
#
# HF_TOKEN is only needed on this path. If the adapter is already on the pod —
# scp it and you never put an org-scoped credential on rented hardware — the
# server starts without one.
if [ ! -f "${ADAPTER_DIR}/adapter_config.json" ]; then
    : "${HF_TOKEN:?set HF_TOKEN — the adapter repo is private, or scp the adapter to ADAPTER_DIR instead}"
    echo "downloading ${ADAPTER_REPO} -> ${ADAPTER_DIR}"
    hf download "${ADAPTER_REPO}" --local-dir "${ADAPTER_DIR}"
else
    echo "adapter already present at ${ADAPTER_DIR}"
fi

# Must match the adapter's `r`. Read it rather than hardcoding 64, so a
# different checkpoint doesn't fail with a confusing rank error.
LORA_RANK=$(python3 -c "import json;print(json.load(open('${ADAPTER_DIR}/adapter_config.json'))['r'])")
echo "adapter rank: ${LORA_RANK}"

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
    --max-loras 1 \
    --lora-modules "${ADAPTER_NAME}=${ADAPTER_DIR}" \
    --enable-prefix-caching
