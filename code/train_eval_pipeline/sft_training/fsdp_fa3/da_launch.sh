#!/usr/bin/env bash
# Local driver for one sequential difficult-advice arm pod (2026-09-21).
# Creates the pod on the TCW account, stages the lane + DA dataset + keys,
# runs the FA3 setup gate, then starts da_chain.sh under nohup ON THE POD.
#
#   bash da_launch.sh <pod-name> <arm> <da.jsonl> <a1-repo> "<card text>"
#   NGPU=4 GPU_TYPE="NVIDIA H200" bash da_launch.sh ...   # bigger box
#   EPOCHS=2 bash da_launch.sh ...                        # fewer passes
#   PUBLISH=0 bash da_launch.sh ...                       # keep adapters on the pod only
#   DA_VAL=path/to/val.jsonl bash da_launch.sh ...        # also stage a val set (eval_loss per epoch)
#   KEEP_POD=1 bash da_launch.sh ...                      # pod stays up
#
# Defaults to 2xA100-SXM: the DA stage is ~10 optimizer steps, so the box is
# sized for the CPU merge and the 62GB download, not for throughput.
set -euo pipefail
NAME="${1:?pod name}"; ARM="${2:?arm}"; DATA="${3:?da jsonl}"
A1_REPO="${4:?a1 adapter repo}"; CARD="${5:?card text}"
[ -s "$DATA" ] || { echo "missing dataset $DATA" >&2; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
ENV_FILE="$REPO/.env"
NGPU="${NGPU:-2}"

RUNPOD_TCW_API_KEY=$(grep -E '^(export )?RUNPOD_TCW_API_KEY=' "$ENV_FILE" | tail -1 | sed 's/^export //; s/^RUNPOD_TCW_API_KEY=//; s/^"//; s/"$//')
: "${RUNPOD_TCW_API_KEY:?RUNPOD_TCW_API_KEY not in .env}"
export RUNPOD_API_KEY="$RUNPOD_TCW_API_KEY"

if [ ! -f "$HERE/../.pods/$NAME.env" ]; then
  CONTAINER_DISK_GB=250 bash "$HERE/../create_pod.sh" "$NAME" "$NGPU" \
    --gpu-type "${GPU_TYPE:-NVIDIA A100-SXM4-80GB}"
fi
source "$HERE/../.pods/$NAME.env"
[ -n "${SSH_IP:-}" ] && [ -n "${SSH_PORT:-}" ] || { echo "no SSH endpoint for $NAME" >&2; exit 1; }
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@$SSH_IP")
SCP=(scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

KEYS_FILE="$ENV_FILE" bash "$HERE/push_fa3.sh" "$NAME"
"${SCP[@]}" "$DATA" "root@$SSH_IP:/workspace/data/da.jsonl"
if [ -n "${DA_VAL:-}" ]; then
  [ -s "$DA_VAL" ] || { echo "DA_VAL not found: $DA_VAL" >&2; exit 1; }
  "${SCP[@]}" "$DA_VAL" "root@$SSH_IP:/workspace/data/da-val.jsonl"
fi
# RUNPOD_POD_ID is NOT in the environment of a chain started over ssh — stage it.
printf 'RUNPOD_TCW_API_KEY=%s\nRUNPOD_POD_ID=%s\n' "$RUNPOD_TCW_API_KEY" "$POD_ID" \
  | "${SSH[@]}" "cat >> /root/.keys; chmod 600 /root/.keys"

"${SSH[@]}" "bash /root/fsdp_fa3/setup_fa3.sh" | tail -3 | grep -q FA3-SETUP-OK \
  || { echo "FA3 setup failed on $NAME (pod still billing)" >&2; exit 1; }
echo "FA3-SETUP-OK on $NAME"

"${SSH[@]}" "KEEP_POD=${KEEP_POD:-0} EPOCHS=${EPOCHS:-4} PUBLISH=${PUBLISH:-1} nohup bash /root/fsdp_fa3/da_chain.sh '$ARM' '$A1_REPO' '$CARD' > /root/da-chain.log 2>&1 < /dev/null & echo chain pid \$!"
echo "chain started on $NAME ($ARM); follow with:"
echo "  ssh -p $SSH_PORT root@$SSH_IP 'tail -5 /root/da-chain.log; ls /root/DONE-* /root/FAILED-* 2>/dev/null'"
