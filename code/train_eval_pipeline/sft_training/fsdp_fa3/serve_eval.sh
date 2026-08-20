#!/usr/bin/env bash
# vLLM serving for a separate eval pod (A100s — serving needs no H200s).
# Usage on the pod:
#   HF_REPO=<org/name> bash serve_eval.sh
# Installs its own venv (isolated from any training env), downloads the
# merged model, and serves an OpenAI-compatible API on :8000 with model
# name "a1-eval". Reach it from the laptop via SSH port-forward
# (never *.proxy.runpod.net):
#   ssh -p <port> -N -L 8000:127.0.0.1:8000 root@<ip> &
# then run_eval.py --model openai/a1-eval --model-base-url http://127.0.0.1:8000/v1
# (set OPENAI_API_KEY to any non-empty string; vLLM does not check it).
#
# The merged model ships its own ChatML template and stop tokens in
# generation_config (merge_release.py --chat), so no stop-token overrides
# are needed here — that IS the design being exercised.
set -euo pipefail
: "${HF_REPO:?set HF_REPO to the merged-model repo (org/name)}"
[ -f /root/.keys ] && { set -a; . /root/.keys; set +a; }

if [ ! -x /opt/serve/bin/vllm ]; then
  python3 -m venv /opt/serve
  /opt/serve/bin/pip install -q -U pip
  # huggingface_hub >= 1.26 ships `hf`; `huggingface-cli` is dead (prints a
  # deprecation notice and exits nonzero — it does NOT download).
  # ninja: vLLM's kernel warmup shells out to it and dies without it.
  /opt/serve/bin/pip install -q vllm huggingface_hub ninja
fi

mkdir -p /workspace/model
# xet (the default transfer backend) died mid-download with "File
# reconstruction error" on a fresh A100 pod (2026-08-06); plain HTTP is
# slower per byte but reliable, and resumes partial downloads.
export HF_HUB_DISABLE_XET=1
/opt/serve/bin/hf download "$HF_REPO" --local-dir /workspace/model

NGPU=$(nvidia-smi -L | wc -l)
# vLLM workers invoke `ninja` (and friends) as bare names via PATH — calling
# /opt/serve/bin/vllm by absolute path is not enough, the venv must lead PATH.
export PATH=/opt/serve/bin:$PATH
exec /opt/serve/bin/vllm serve /workspace/model \
  --served-model-name a1-eval \
  --tensor-parallel-size "$NGPU" \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.92 \
  --port 8000
