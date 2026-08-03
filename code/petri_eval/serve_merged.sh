#!/usr/bin/env bash
# Serve the elicit-A1 merged checkpoint with vLLM, for the Petri audit
# (run_audit.sh). As run on the GPU box, 2026-08-03.
#
# The target is the FULLY MERGED Qwen2.5-32B + elicit-A1 checkpoint, built by
# build_merged.py in this directory (base + adapter merged offline, ChatML
# tokenizer, eos fix baked into generation_config.json). This is a different
# flow from code/serving/serve_vllm.sh, which serves LoRA adapters on top of a
# base model — merging was needed here so the plain BASE-trained adapter could
# be served with ChatML + tool calling as one coherent model.
#
# hermes tool-call parser + auto tool choice: Petri exercises the target's
# (synthetic) tools, so the server must translate Qwen's hermes-format tool
# calls into OpenAI tool_calls fields.
#
# NB: no --api-key and no --host, so vLLM listens on its default 0.0.0.0 —
# fine when the box is only reachable over SSH, but add --host 127.0.0.1 or an
# --api-key before reusing this behind a RunPod HTTP proxy (cf. the warning in
# code/serving/serve_vllm.sh).
set -euo pipefail

MERGED_MODEL_DIR=${MERGED_MODEL_DIR:-./models/qwen2.5-32b-elicit-A1-merged}
SERVED_NAME=${SERVED_NAME:-qwen2.5-32b-elicit-A1}
PORT=${PORT:-8000}

exec vllm serve "${MERGED_MODEL_DIR}" \
    --served-model-name "${SERVED_NAME}" \
    --dtype bfloat16 \
    --gpu-memory-utilization 0.90 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --port "${PORT}"
