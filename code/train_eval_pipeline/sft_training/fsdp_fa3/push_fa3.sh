#!/usr/bin/env bash
# Push the fsdp_fa3 lane + A1 data + keys to a pod made by ../create_pod.sh.
#   KEYS_FILE=~/.env bash push_fa3.sh <pod-name>
# Optional: SDF_CORPUS=path/to/corpus.jsonl to stage stage-1 data too.
set -euo pipefail
NAME="${1:?usage: push_fa3.sh <pod-name>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../.pods/$NAME.env"
: "${KEYS_FILE:?set KEYS_FILE to the file defining HF_TOKEN and WANDB_API_KEY}"

# Only the two keys the pod needs — never the whole .env.
KEYS_TMP=$(mktemp); trap 'rm -f "$KEYS_TMP"' EXIT
grep -E '^(export )?(HF_TOKEN|WANDB_API_KEY)=' "$KEYS_FILE" > "$KEYS_TMP"

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
ssh -p "$SSH_PORT" "${SSH_OPTS[@]}" "root@$SSH_IP" "mkdir -p /workspace/data"
scp -P "$SSH_PORT" "${SSH_OPTS[@]}" -r "$HERE" "root@$SSH_IP:/root/"
scp -P "$SSH_PORT" "${SSH_OPTS[@]}" "$HERE/../../mix-a1-clean.jsonl" \
  "root@$SSH_IP:/workspace/data/"
if [ -n "${SDF_CORPUS:-}" ]; then
  [ -f "$SDF_CORPUS" ] || { echo "SDF_CORPUS not found: $SDF_CORPUS"; exit 1; }
  scp -P "$SSH_PORT" "${SSH_OPTS[@]}" "$SDF_CORPUS" \
    "root@$SSH_IP:/workspace/data/sdf-corpus.jsonl"
fi
scp -P "$SSH_PORT" "${SSH_OPTS[@]}" "$KEYS_TMP" "root@$SSH_IP:/root/.keys"
echo "pushed fsdp_fa3 lane to $NAME ($SSH_IP:$SSH_PORT)"
