#!/bin/bash
# Copy the stack + data + keys to a pod created by create_pod.sh.  Usage:
#   KEYS_FILE=~/path/to/.keys bash push.sh <name>
# <name> is the pod name given to create_pod.sh (reads .pods/<name>.env).
# KEYS_FILE must be a file that exports HF_TOKEN and WANDB_API_KEY.
set -euo pipefail
NAME="${1:?usage: push.sh <pod-name>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.pods/$NAME.env"
: "${KEYS_FILE:?set KEYS_FILE to the file defining HF_TOKEN and WANDB_API_KEY (e.g. the repo .env)}"
grep -q HF_TOKEN "$KEYS_FILE" || { echo "$KEYS_FILE does not define HF_TOKEN"; exit 1; }

# Ship ONLY the two keys the pod needs — never the whole .env (Together/
# OpenRouter keys have no business on a rented machine).
KEYS_TMP=$(mktemp)
trap 'rm -f "$KEYS_TMP"' EXIT
grep -E '^(export )?(HF_TOKEN|WANDB_API_KEY)=' "$KEYS_FILE" > "$KEYS_TMP"

SSH_OPTS=(-P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
scp "${SSH_OPTS[@]}" \
  "$DIR/setup.sh" "$DIR/train.sh" "$DIR/train_trl.py" "$DIR/check_junk.py" \
  "$DIR/a1_lora_r64.yaml" "$DIR/a1_lora_r64_fix1.yaml" "$DIR/sdf_lora_r64.yaml" "$DIR/sdf_pipeline.sh" "$DIR/fix_export_config.py" \
  "$DIR/sdf_ladder_lora_r64.yaml" "$DIR/sdf_ladder_pipeline.sh" \
  "$DIR/ds_z3.json" "$DIR/dataset_info.json" \
  "$DIR/../mix-a1-clean.jsonl" \
  "root@$SSH_IP:/root/"

# SDF stage-1 corpus, when one is named. SDF_CORPUS is a path to a
# {"text": ...} JSONL; it lands as /workspace/data/sdf-corpus.jsonl, the
# file name sdf_corpus points at in dataset_info.json.
if [ -n "${SDF_CORPUS:-}" ]; then
  [ -f "$SDF_CORPUS" ] || { echo "SDF_CORPUS not found: $SDF_CORPUS"; exit 1; }
  ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "root@$SSH_IP" "mkdir -p /workspace/data"
  scp "${SSH_OPTS[@]}" "$SDF_CORPUS" "root@$SSH_IP:/workspace/data/sdf-corpus.jsonl"
  echo "staged SDF corpus: $(basename "$SDF_CORPUS")"
  # Ladder runs read their save steps from the manifest next to the corpus.
  MANIFEST="$(dirname "$SDF_CORPUS")/sdf-ladder-manifest.json"
  if [ -f "$MANIFEST" ]; then
    scp "${SSH_OPTS[@]}" "$MANIFEST" "root@$SSH_IP:/workspace/data/sdf-ladder-manifest.json"
    echo "staged ladder manifest"
  fi
fi
scp "${SSH_OPTS[@]}" "$KEYS_TMP" "root@$SSH_IP:/root/.keys"
echo "pushed to $NAME ($SSH_IP:$SSH_PORT)"
