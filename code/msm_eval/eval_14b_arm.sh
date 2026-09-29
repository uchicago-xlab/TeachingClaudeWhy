#!/usr/bin/env bash
# Evaluate one Qwen3-14B arm (base, or a Together LoRA adapter downloaded
# locally) on a fresh 1xA100-SXM pod, then terminate the pod (2026-09-29).
# The 14B counterpart of eval_arms.sh: no reconstruction, the adapter dir is
# scp'd straight to the pod. Settings are the DA-arm convention: thinking OFF,
# model_name Qwen, no stop-token override.
#
#   bash eval_14b_arm.sh <pod-name> <served-name> <run-name> <adapter-dir|none> <local-port>
#   e.g. bash eval_14b_arm.sh g27-refusal qwen3-14b-da-refusal-scale08-ep2 \
#     da-refusal-scale08-ep2-as-qwen-nothink-g27 tmp/refusal-adapter-42 8311
#
# GOALS=all|default (default all -> 27 conditions), EPOCHS (default 100),
# MAX_CONN (default 64), GPU_TYPE (default a100; create_pod.sh ids or a full RunPod id). vLLM is pinned to 0.30.0 and FlashInfer's sampler is
# disabled: its JIT build fails against the stock image's nvcc. Markers:
# data/msm-eval/EVAL-DONE-<pod-name> / EVAL-FAILED-<pod-name>. On failure the
# pod is LEFT RUNNING for debugging; terminate it by hand.
set -uo pipefail
NAME="${1:?pod name}"; SERVED="${2:?served name}"; RUN="${3:?run name}"
ADAPTER="${4:?adapter dir or none}"; LOCAL="${5:?local port}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SFT="$REPO/code/train_eval_pipeline/sft_training"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
fail() { echo "[$(ts)] EVAL FAILED: $1"; touch "$REPO/data/msm-eval/EVAL-FAILED-$NAME"; exit 1; }

export RUNPOD_API_KEY="${RUNPOD_API_KEY:-$(sed -n "s/^apikey *= *['\"]\?\([^'\"]*\)['\"]\?/\1/p" ~/.runpod/config.toml)}"
HF_TOKEN_VAL=$(grep -E '^(export )?HF_TOKEN=' "$REPO/.env" | tail -1 | sed "s/^export //; s/^HF_TOKEN=//; s/[\"']//g")

# 1. pod
if [ ! -f "$SFT/.pods/$NAME.env" ]; then
  bash "$SFT/create_pod.sh" "$NAME" 1 --gpu-type "${GPU_TYPE:-a100}" || fail "pod creation"
fi
source "$SFT/.pods/$NAME.env"
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=30 "root@$SSH_IP")
echo "[$(ts)] pod $POD_ID up at $SSH_IP:$SSH_PORT"

# 2. vLLM + adapter
"${SSH[@]}" "pip install -q vllm==0.30.0 > /root/pip.log 2>&1" || fail "vllm install"
LORA_ARGS="--served-model-name $SERVED"
if [ "$ADAPTER" != none ]; then
  scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -r "$REPO/$ADAPTER" "root@$SSH_IP:/root/adapter" || fail "scp adapter"
  LORA_ARGS="--enable-lora --max-lora-rank 64 --lora-modules $SERVED=/root/adapter"
fi
echo "$HF_TOKEN_VAL" | "${SSH[@]}" "read t; HF_TOKEN=\$t VLLM_USE_FLASHINFER_SAMPLER=0 nohup vllm serve Qwen/Qwen3-14B $LORA_ARGS --max-model-len 16384 --port 8000 --host 127.0.0.1 > /root/serve.log 2>&1 < /dev/null &" || fail "start serve"

# 3. wait for the endpoint
up=0
for _ in $(seq 1 60); do
  sleep 20
  if "${SSH[@]}" "curl -sf -m 10 http://127.0.0.1:8000/v1/models" >/dev/null 2>&1; then up=1; break; fi
  "${SSH[@]}" "grep -q 'Engine core initialization failed' /root/serve.log" 2>/dev/null && { "${SSH[@]}" "grep ERROR /root/serve.log | tail -5"; fail "vLLM crashed"; }
done
[ "$up" = 1 ] || fail "endpoint never came up"
echo "[$(ts)] serving $SERVED"

# 4. tunnel + eval + validate
IP="$SSH_IP" PORT="$SSH_PORT" LOCAL="$LOCAL" bash "$HERE/tunnel_keeper.sh" > "$REPO/data/msm-eval/tunnel-$NAME.log" 2>&1 &
TUNNEL=$!
trap 'kill $TUNNEL 2>/dev/null; pkill -P $TUNNEL 2>/dev/null' EXIT
sleep 25
( cd "$REPO" && VLLM_API_KEY=x PYTHONPATH=code/msm_eval/vendor .venv-inspect/bin/python code/msm_eval/msm_eval_run.py \
    --model "openai-api/vllm/$SERVED" --base-url "http://127.0.0.1:$LOCAL/v1" \
    --run-name "$RUN" --goals "${GOALS:-all}" --epochs "${EPOCHS:-100}" --no-thinking \
    --max-connections "${MAX_CONN:-64}" ) > "$REPO/data/msm-eval/$RUN.client.log" 2>&1 \
  || fail "eval client exited nonzero (see data/msm-eval/$RUN.client.log)"
( cd "$REPO" && .venv-inspect/bin/python code/msm_eval/validate_run.py "data/msm-eval/$RUN" ) \
  || echo "[$(ts)] validate_run reported issues for $RUN — check before reporting"
echo "[$(ts)] $RUN finished"

# 5. terminate
touch "$REPO/data/msm-eval/EVAL-DONE-$NAME"
curl -sS -X DELETE "https://rest.runpod.io/v1/pods/$POD_ID" -H "Authorization: Bearer $RUNPOD_API_KEY" && echo "[$(ts)] terminated pod $POD_ID"
