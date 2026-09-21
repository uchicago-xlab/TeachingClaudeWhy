#!/usr/bin/env bash
# Local driver for one scaling-ladder pod (LadderV45Handoff.md, 2026-09-14).
# Creates the pod on the TCW account, stages the lane, the rung files, the
# test set and the keys, runs the FA3 setup gate, optionally a 5-step smoke
# that exercises the test-loss paths, then starts ladder_chain.sh under
# nohup ON THE POD (no local watcher) and returns.
#
#   bash ladder_launch.sh <pod-name> <test_steps> [--smoke] <rung> [<rung> ...]
#   e.g.  bash ladder_launch.sh ladder-a 0   3M 28M 56M
#         bash ladder_launch.sh ladder-b 200 --smoke 112M
#
# Paid from the moment create_pod.sh succeeds. Every step is idempotent
# enough to rerun after a failure by hand (see the ssh preamble in
# Redo14MHandoff.md).
set -euo pipefail
NAME="${1:?pod name}"; TEST_STEPS="${2:?test_steps}"; shift 2
SMOKE=0; if [ "${1:-}" = "--smoke" ]; then SMOKE=1; shift; fi
RUNGS=("$@"); [ ${#RUNGS[@]} -gt 0 ] || { echo "no rungs given" >&2; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
SDF_TRAIN="$REPO/data/fictional-stories/corpus/sdf_train"
ENV_FILE="$REPO/.env"
for r in "${RUNGS[@]}"; do
  [ -s "$SDF_TRAIN/sdf-v45emb-nano54-ladder-$r.jsonl" ] || { echo "missing rung file $r" >&2; exit 1; }
done

# TCW account, explicitly (create_pod.sh would otherwise bill the shared key).
RUNPOD_TCW_API_KEY=$(grep -E '^(export )?RUNPOD_TCW_API_KEY=' "$ENV_FILE" | tail -1 | sed 's/^export //; s/^RUNPOD_TCW_API_KEY=//; s/^"//; s/"$//')
: "${RUNPOD_TCW_API_KEY:?RUNPOD_TCW_API_KEY not in .env}"
export RUNPOD_API_KEY="$RUNPOD_TCW_API_KEY"

if [ ! -f "$HERE/../.pods/$NAME.env" ]; then
  CONTAINER_DISK_GB=250 bash "$HERE/../create_pod.sh" "$NAME" 4 --gpu-type "${GPU_TYPE:-NVIDIA H200}"
fi
source "$HERE/../.pods/$NAME.env"
SSH=(ssh -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "root@$SSH_IP")
SCP=(scp -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

# Lane + A1 mix + HF/wandb keys; the largest rung rides along as SDF_CORPUS.
KEYS_FILE="$ENV_FILE" bash "$HERE/push_fa3.sh" "$NAME"
for r in "${RUNGS[@]}"; do
  "${SCP[@]}" "$SDF_TRAIN/sdf-v45emb-nano54-ladder-$r.jsonl" "root@$SSH_IP:/workspace/data/ladder-$r.jsonl"
done
"${SCP[@]}" "$SDF_TRAIN/v45emb-nano54-ladder-heldout.jsonl" "root@$SSH_IP:/workspace/data/ladder-test.jsonl"
# The chain terminates the pod itself at the end: it needs the TCW key.
printf 'RUNPOD_TCW_API_KEY=%s\n' "$RUNPOD_TCW_API_KEY" | "${SSH[@]}" "cat >> /root/.keys; chmod 600 /root/.keys"

"${SSH[@]}" "bash /root/fsdp_fa3/setup_fa3.sh" | tail -3 | grep -q FA3-SETUP-OK || { echo "FA3 setup failed on $NAME" >&2; exit 1; }
echo "FA3-SETUP-OK on $NAME"

PRE='export PATH=/root/.local/bin:$PATH; cd /root/fsdp_fa3/env; set -a; . /root/.keys; set +a'
if [ "$SMOKE" = 1 ]; then
  # 5 steps, test loss at step 0, every 2 steps and at the end -> test_loss.json.
  "${SSH[@]}" "$PRE; uv run --no-sync bash /root/fsdp_fa3/launch.sh sdf 4 --smoke \
      --corpus /workspace/data/ladder-${RUNGS[0]}.jsonl --out /workspace/out/smoke \
      --test-corpus /workspace/data/ladder-test.jsonl --test-steps 2 2>&1 | tail -40; \
      echo '--- test_loss.json ---'; cat /workspace/out/smoke/test_loss.json" \
    || { echo "SMOKE FAILED on $NAME (no test_loss.json) — chain NOT started; pod is still billing" >&2; exit 1; }
  "${SSH[@]}" "rm -rf /workspace/out/smoke"
  echo "smoke passed on $NAME — check the eval_loss lines above"
fi

"${SSH[@]}" "nohup bash /root/fsdp_fa3/ladder_chain.sh $TEST_STEPS ${RUNGS[*]} > /root/ladder-chain.log 2>&1 < /dev/null & echo chain pid \$!"
echo "chain started on $NAME (${RUNGS[*]}); follow with:"
echo "  ssh -p $SSH_PORT root@$SSH_IP 'tail -5 /root/ladder-chain.log; ls /root/DONE-* /root/FAILED-* 2>/dev/null'"
