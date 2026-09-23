#!/usr/bin/env bash
# Local driver for a difficult-advice EPOCH SWEEP on one kept pod (2026-09-22, v3:
# TRAIN-ONLY). Each final adapter is PUBLISHED as it lands; a separate
# eval_arms.sh pod polls the Hub and evals each one — training GPUs never idle
# during an eval, and no train/serve interleaving on one disk.
#
#   ARM_PREFIX=graft0-a1-terra300-da bash da_sweep.sh <pod-name> <da.jsonl> <da-val.jsonl> <a1-repo> <epochs...>
#   e.g. ARM_PREFIX=graft0-a1-sonnet5tp-da bash da_sweep.sh sonnetA \
#          data/.../sonnet5tp-ft-qwen25.jsonl data/.../terra-ft-qwen25-val.jsonl \
#          SecondLookResearch/Qwen2.5-32B-graft0-a1 10 20
#   then, on another pod:  KEEP_POD=0 EVAL_EPOCHS=10 bash code/msm_eval/eval_arms.sh evalX \
#          "s10|graft0-a1-sonnet5tp-da-e10-g27x10-name{name}|<a1-repo> SecondLookResearch/Qwen2.5-32B-graft0-a1-sonnet5tp-da-e10|Alex" ...
#
# Per epoch count, from scratch (a fully-annealed cosine per run; endpoints are
# compared at matched STEPS across datasets — "new data vs repeated data"):
#   first run via da_launch.sh (creates the pod, graft, merge), later runs via
#   da_chain.sh (resume checks reuse graft+merge); PUBLISH=1 -> repo
#   SecondLookResearch/Qwen2.5-32B-<ARM_PREFIX>-e<N>; loss logs to local scratch.
# Traps handled: setup_fa3 ssh gate hang (kill + relaunch); no RunPod capacity
# (uncapped retry cycling A100/A100/H100).
set -uo pipefail
NAME="${1:?pod name}"; DATA="${2:?da jsonl}"; VAL="${3:?val jsonl}"; A1_REPO="${4:?a1 repo}"; shift 4
EPOCH_LIST=("$@"); [ ${#EPOCH_LIST[@]} -gt 0 ] || { echo "no epoch counts given" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../../.." && pwd)"
ARM_PREFIX="${ARM_PREFIX:-graft0-a1-terra-da}"; SETUP_DEADLINE="${SETUP_DEADLINE:-1500}"
LOG="$REPO/data/msm-eval/da-sweep-$NAME.log"
LOSSDIR="${DA_SWEEP_LOGDIR:-$HOME/.cache/tcw-sweeps}/$NAME"; mkdir -p "$LOSSDIR"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$LOG"; }
die() { say "SWEEP FAILED: $*"; touch "$REPO/data/msm-eval/SWEEP-FAILED-$NAME"; exit 1; }
arm_of() { echo "$ARM_PREFIX-e$1"; }
card() { echo "Difficult advice ($ARM_PREFIX), $1 epochs from scratch, fresh adapter over frozen graft0-a1. Epoch sweep, compared at matched steps."; }
podssh() { ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=30 -o ServerAliveInterval=15 -o LogLevel=ERROR "root@$SSH_IP" "$@"; }
wait_marker() {
  local arm="$1" m
  while true; do
    m=$(podssh "ls /root/DONE-$arm /root/FAILED-$arm 2>/dev/null || true" 2>/dev/null)
    case "$m" in
      *FAILED*) podssh "tail -20 /root/da-chain.log" | tee -a "$LOG"; die "$arm chain FAILED (pod left up)";;
      *DONE*)   say "$arm DONE"; return 0;;
    esac
    sleep 60
  done
}
save_logs() {  # loss logs to local scratch, never under the repo's data/
  local arm; arm="$(arm_of "$1")"
  scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    "root@$SSH_IP:/root/da-$arm.log" "$LOSSDIR/$arm.train.log" 2>/dev/null || true
  podssh "cat /workspace/out/$arm/trainer_state.json 2>/dev/null" > "$LOSSDIR/$arm.trainer_state.json" 2>/dev/null || true
  say "PUBLISHED SecondLookResearch/Qwen2.5-32B-$arm (loss log -> $LOSSDIR/$arm.train.log)"
}

first="${EPOCH_LIST[0]}"; arm1="$(arm_of "$first")"
say "===== sweep on $NAME [$ARM_PREFIX]: epochs ${EPOCH_LIST[*]} ====="
GPU_CYCLE=("NVIDIA A100-SXM4-80GB" "NVIDIA A100-SXM4-80GB" "NVIDIA H100 80GB HBM3")
attempt=0; hangs=0
while true; do
  attempt=$((attempt+1)); LL="$REPO/data/msm-eval/da-launch-$NAME-$attempt.log"
  gpu="${GPU_CYCLE[$(( (attempt-1) % ${#GPU_CYCLE[@]} ))]}"
  ( cd "$REPO" && KEEP_POD=1 EPOCHS="$first" PUBLISH=1 DA_VAL="$VAL" GPU_TYPE="$gpu" \
      bash "$HERE/da_launch.sh" "$NAME" "$arm1" "$DATA" "$A1_REPO" "$(card "$first")" ) > "$LL" 2>&1 &
  LPID=$!; t0=$(date +%s)
  while kill -0 "$LPID" 2>/dev/null; do
    grep -q "chain started" "$LL" && break
    if [ $(( $(date +%s) - t0 )) -gt "$SETUP_DEADLINE" ]; then
      say "setup gate hang suspected (attempt $attempt) — killing the local setup ssh"
      port=$(sed -n 's/^SSH_PORT=//p' "$HERE/../.pods/$NAME.env" 2>/dev/null)
      for pid in $(ps -eo pid,command | grep "ssh -p ${port:-NONE} .*setup_fa3" | grep -v grep | awk '{print $1}'); do kill "$pid"; done
      wait "$LPID" 2>/dev/null; break
    fi
    sleep 30
  done
  wait "$LPID" 2>/dev/null
  grep -q "chain started" "$LL" && break
  if grep -q "pod creation failed" "$LL"; then
    [ "$attempt" -ge 120 ] && die "no RunPod capacity after $attempt attempts (~3h)"
    say "no capacity for '$gpu' (attempt $attempt) — retrying in 90s"; sleep 90; continue
  fi
  hangs=$((hangs+1)); [ "$hangs" -ge 3 ] && die "da_launch never reached 'chain started' after 3 non-capacity failures (see $LL)"
  say "retrying da_launch after a non-capacity failure (see $LL)"
done
say "pod created on '$gpu' at attempt $attempt"
source "$HERE/../.pods/$NAME.env"
say "pod $POD_ID at $SSH_IP:$SSH_PORT; chain $arm1 running"
wait_marker "$arm1"; save_logs "$first"

for ep in "${EPOCH_LIST[@]:1}"; do
  arm="$(arm_of "$ep")"
  say "starting $arm on the same pod"
  podssh "KEEP_POD=1 EPOCHS=$ep PUBLISH=1 nohup bash /root/fsdp_fa3/da_chain.sh '$arm' '$A1_REPO' '$(card "$ep")' > /root/da-chain.log 2>&1 < /dev/null & echo pid \$!" | tee -a "$LOG"
  wait_marker "$arm"; save_logs "$ep"
done
touch "$REPO/data/msm-eval/SWEEP-DONE-$NAME"
say "===== sweep DONE (all arms published); pod $POD_ID KEPT at $SSH_IP:$SSH_PORT ====="
