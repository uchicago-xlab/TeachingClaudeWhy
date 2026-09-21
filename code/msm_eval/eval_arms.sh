#!/usr/bin/env bash
# Evaluate published graft0 arms on the 27-cell MSM grid, one 2xA100-SXM pod,
# arms in sequence (2026-09-14). Waits for each arm's adapters to exist on
# the Hub before creating the pod, so it can be started while training runs.
#
#   bash eval_arms.sh <pod-name> "<tag>|<run-name>|<adapter1> <adapter2>[|<name>,<name>]" [...]
#   The optional 4th field lists address names to evaluate on the same
#   served model (2026-09-16); "{name}" in the run name is replaced by each.
#   e.g. "human|v45emb-sonnet5-human-graft0-a1-g27-name{name}|... ...|Alex,Qwen"
#   e.g. bash eval_arms.sh evalnamed \
#     "namedclaude|v45emb-sonnet5-named-claude-graft0-a1-g27-nameAlex|SecondLookResearch/Qwen2.5-32B-v45emb-sonnet5-named-claude-14M-sdf SecondLookResearch/Qwen2.5-32B-v45emb-sonnet5-named-claude-14M-a1-graft0"
#
# Per arm: serve_reconstructed.sh on the pod (nohup) -> wait for /v1/models
# -> tunnel_keeper.sh locally on :8001 -> msm_eval_run.py 27x100 as Alex
# (temp 0.7, max_tokens 4096, prod=false, Sonnet 4.6 grader, stop tokens
# 151645,151643 — the pinned settings) -> validate_run.py -> kill vLLM by
# GPU PID until VRAM is 0 -> rm the rebuilt model (one fits per disk).
# MODEL_NAME=Qwen overrides the address name (default Alex).
# Then the pod is terminated. Markers: data/msm-eval/EVAL-DONE-<pod-name> or
# EVAL-FAILED-<pod-name>. Run detached: nohup bash eval_arms.sh ... &
set -uo pipefail
NAME="${1:?pod name}"; shift
ARMS=("$@"); [ ${#ARMS[@]} -gt 0 ] || { echo "no arms given" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SFT="$REPO/code/train_eval_pipeline/sft_training"
ENV_FILE="$REPO/.env"
LOCAL_PORT="${LOCAL_PORT:-8001}"
MODEL_NAME="${MODEL_NAME:-Alex}"   # name the scenarios address the model by (MSM used its own name, "Qwen")
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
fail() { echo "[$(ts)] EVAL FAILED: $1"; touch "$REPO/data/msm-eval/EVAL-FAILED-$NAME"; exit 1; }

set -a; . "$ENV_FILE"; set +a
export RUNPOD_API_KEY="${EVAL_RUNPOD_API_KEY:-${RUNPOD_TCW_API_KEY:?RUNPOD_TCW_API_KEY not in .env}}"

# 0. wait for every arm's adapters on the Hub (verified file list, not repo existence)
for spec in "${ARMS[@]}"; do
  IFS='|' read -r tag run adapters names <<< "$spec"
  for repo in $adapters; do
    until "$REPO/.venv/bin/python" - "$repo" <<'PY'
import sys
from huggingface_hub import HfApi
import os
try:
    files = set(HfApi(token=os.environ.get("HF_TOKEN")).list_repo_files(sys.argv[1]))
except Exception as e:
    sys.exit(1)
sys.exit(0 if {"adapter_model.safetensors", "adapter_config.json"} <= files else 1)
PY
    do echo "[$(ts)] waiting for $repo"; sleep 300; done
    echo "[$(ts)] present: $repo"
  done
done

# 1. pod (SXM: PCIe A100s hang NCCL) + serving script + HF token
if [ ! -f "$SFT/.pods/$NAME.env" ]; then
  CONTAINER_DISK_GB=200 bash "$SFT/create_pod.sh" "$NAME" 2 --gpu-type a100 || fail "pod creation"
fi
source "$SFT/.pods/$NAME.env"
[ -n "${SSH_IP:-}" ] && [ -n "${SSH_PORT:-}" ] || fail "no SSH endpoint for $NAME"
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=30 "root@$SSH_IP")
SCP=(scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
"${SCP[@]}" "$HERE/serve_reconstructed.sh" "root@$SSH_IP:/root/" || fail "scp serve script"
grep -E '^(export )?HF_TOKEN=' "$ENV_FILE" | "${SSH[@]}" "cat > /root/.keys; chmod 600 /root/.keys" || fail "keys"

for spec in "${ARMS[@]}"; do
  IFS='|' read -r tag runtpl adapters names <<< "$spec"
  names="${names:-$MODEL_NAME}"
  echo "[$(ts)] ===== arm $tag -> $runtpl (as ${names}) ====="
  # 2. serve (detached on the pod)
  "${SSH[@]}" "ARM=$tag ROW_PATCH=1 ADAPTERS='$adapters' nohup bash /root/serve_reconstructed.sh > /root/serve-$tag.log 2>&1 < /dev/null &" || fail "start serve $tag"
  # 3. wait for the endpoint (fetch + reconstruct + vLLM warmup: 30-60 min)
  deadline=$(( $(date +%s) + 5400 )); up=0
  while [ "$(date +%s)" -lt "$deadline" ]; do
    sleep 60
    if "${SSH[@]}" "curl -sf -m 10 http://127.0.0.1:8000/v1/models" >/dev/null 2>&1; then up=1; break; fi
    if "${SSH[@]}" "grep -qE 'FAILED|Traceback|No space left' /root/serve-$tag.log" 2>/dev/null; then
      "${SSH[@]}" "tail -n 20 /root/serve-$tag.log"; fail "serving $tag crashed (see /root/serve-$tag.log on the pod)"
    fi
    echo "[$(ts)] $tag: $("${SSH[@]}" "grep -E '^STAGE' /root/serve-$tag.log | tail -1" 2>/dev/null)"
  done
  [ "$up" = 1 ] || fail "endpoint for $tag never came up"
  echo "[$(ts)] $tag serving"
  # 4. tunnel + eval + validate, once per address name on the same server
  IP="$SSH_IP" PORT="$SSH_PORT" LOCAL="$LOCAL_PORT" bash "$HERE/tunnel_keeper.sh" > "$REPO/data/msm-eval/tunnel-$tag.log" 2>&1 &
  TUNNEL=$!
  sleep 25
  for name in ${names//,/ }; do
    run="${runtpl//\{name\}/$name}"
    echo "[$(ts)] eval $run as $name"
    ( cd "$REPO" && VLLM_API_KEY=x PYTHONPATH=code/msm_eval/vendor .venv-inspect/bin/python code/msm_eval/msm_eval_run.py \
        --model openai-api/vllm/a1-eval --base-url "http://127.0.0.1:$LOCAL_PORT/v1" \
        --run-name "$run" --goals all --model-name "$name" --epochs 100 \
        --stop-token-ids 151645,151643 --max-connections 32 ) > "$REPO/data/msm-eval/$run.client.log" 2>&1
    rc=$?
    if [ "$rc" != 0 ]; then kill "$TUNNEL" 2>/dev/null; pkill -P "$TUNNEL" 2>/dev/null; fail "eval client for $run exited $rc (see data/msm-eval/$run.client.log)"; fi
    ( cd "$REPO" && .venv-inspect/bin/python code/msm_eval/validate_run.py "data/msm-eval/$run" ) || echo "[$(ts)] validate_run reported issues for $run — check before reporting"
    echo "[$(ts)] $run finished"
  done
  kill "$TUNNEL" 2>/dev/null; pkill -P "$TUNNEL" 2>/dev/null
  # 5. free the pod for the next arm: kill by GPU PID until VRAM is 0, drop the rebuilt model
  "${SSH[@]}" 'for i in 1 2 3 4 5 6; do for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do kill -9 $p 2>/dev/null; done; sleep 5; m=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -1); [ "$m" -lt 1000 ] && break; done; echo "vram max ${m} MiB"' || true
  "${SSH[@]}" "rm -rf /root/serve-$tag /root/ad*-$tag" || true
done

touch "$REPO/data/msm-eval/EVAL-DONE-$NAME"
echo "[$(ts)] all arms done; terminating pod $POD_ID"
curl -sS -X DELETE "https://rest.runpod.io/v1/pods/$POD_ID" -H "Authorization: Bearer $RUNPOD_API_KEY" && echo " terminated"
