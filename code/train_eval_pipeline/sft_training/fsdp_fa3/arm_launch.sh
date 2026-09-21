#!/usr/bin/env bash
# Local driver for one two-stage arm pod (2026-09-14, from ladder_launch.sh).
# Creates the pod on the TCW account, stages the lane + corpus + A1 mix +
# keys, runs the FA3 setup gate, then starts arm_chain.sh under nohup ON THE
# POD and returns. No local watcher: follow the log by ssh.
#
#   bash arm_launch.sh <pod-name> <arm> <corpus.jsonl> "<card text>"
#   GPU_TYPE="NVIDIA A100-SXM4-80GB" bash arm_launch.sh ...   # H200 fallback
#   KEEP_POD=1 bash arm_launch.sh ...                          # pod stays up after publish
set -euo pipefail
NAME="${1:?pod name}"; ARM="${2:?arm}"; CORPUS="${3:?corpus}"; CARD="${4:?card text}"
[ -s "$CORPUS" ] || { echo "missing corpus $CORPUS" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
ENV_FILE="$REPO/.env"

RUNPOD_TCW_API_KEY=$(grep -E '^(export )?RUNPOD_TCW_API_KEY=' "$ENV_FILE" | tail -1 | sed 's/^export //; s/^RUNPOD_TCW_API_KEY=//; s/^"//; s/"$//')
: "${RUNPOD_TCW_API_KEY:?RUNPOD_TCW_API_KEY not in .env}"
export RUNPOD_API_KEY="$RUNPOD_TCW_API_KEY"

if [ ! -f "$HERE/../.pods/$NAME.env" ]; then
  CONTAINER_DISK_GB=250 bash "$HERE/../create_pod.sh" "$NAME" 4 --gpu-type "${GPU_TYPE:-NVIDIA H200}"
fi
source "$HERE/../.pods/$NAME.env"
[ -n "${SSH_IP:-}" ] && [ -n "${SSH_PORT:-}" ] || { echo "no SSH endpoint for $NAME" >&2; exit 1; }
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@$SSH_IP")

KEYS_FILE="$ENV_FILE" SDF_CORPUS="$CORPUS" bash "$HERE/push_fa3.sh" "$NAME"
# RUNPOD_POD_ID is NOT in the environment of a chain started over ssh (seen
# 2026-09-14: "NO RUNPOD KEY/POD ID", pod left running) — stage it explicitly.
printf 'RUNPOD_TCW_API_KEY=%s\nRUNPOD_POD_ID=%s\n' "$RUNPOD_TCW_API_KEY" "$POD_ID" | "${SSH[@]}" "cat >> /root/.keys; chmod 600 /root/.keys"

"${SSH[@]}" "bash /root/fsdp_fa3/setup_fa3.sh" | tail -3 | grep -q FA3-SETUP-OK || { echo "FA3 setup failed on $NAME (pod still billing)" >&2; exit 1; }
echo "FA3-SETUP-OK on $NAME"

"${SSH[@]}" "KEEP_POD=${KEEP_POD:-0} nohup bash /root/fsdp_fa3/arm_chain.sh '$ARM' '$CARD' > /root/arm-chain.log 2>&1 < /dev/null & echo chain pid \$!"
echo "chain started on $NAME ($ARM); follow with:"
echo "  ssh -p $SSH_PORT root@$SSH_IP 'tail -5 /root/arm-chain.log; ls /root/DONE-* /root/FAILED-* 2>/dev/null'"
