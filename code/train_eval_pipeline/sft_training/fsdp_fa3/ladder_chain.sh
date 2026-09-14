#!/usr/bin/env bash
# On-pod chain for the v4.5 nano-embodiment scaling ladder (2026-09-14).
# One invocation trains N rungs back to back, each through the full
# per-rung pipeline of LadderV45Handoff.md, then terminates the pod.
#
#   nohup bash /root/fsdp_fa3/ladder_chain.sh <test_steps> <rung> [<rung> ...] \
#       > /root/ladder-chain.log 2>&1 < /dev/null &
#   e.g.  ladder_chain.sh 0   3M 28M 56M      # pod A
#         ladder_chain.sh 200 112M            # pod B (within-run test-loss curve)
#
# Per rung: SDF stage (with step-0 + end-state test loss) -> merge -> graft
# (gate: cos 1.0000 both tables) -> A1 SFT --no-tables -> publish both
# adapters + base_row_patch -> verify remote file list -> free disk.
# Markers: /root/DONE-<rung> on success, /root/FAILED-<rung> on any error
# (the chain then stops and the pod stays up for debugging — check it).
# After the last rung succeeds the pod terminates itself through the
# RunPod API (needs RUNPOD_TCW_API_KEY in /root/.keys).
#
# Expects, staged by the local launcher:
#   /workspace/data/ladder-<rung>.jsonl   /workspace/data/ladder-test.jsonl
#   /workspace/data/mix-a1-clean.jsonl    /root/.keys (HF, wandb, RunPod TCW)
set -uo pipefail
TEST_STEPS="${1:?usage: ladder_chain.sh <test_steps> <rung> [rung ...]}"; shift
export PATH=/root/.local/bin:$PATH
cd /root/fsdp_fa3/env
set -a; . /root/.keys; set +a
NGPU=$(nvidia-smi -L | wc -l | tr -d ' ')
ORG=SecondLookResearch
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
fail() { echo "[$(ts)] FAILED $1: $2"; touch "/root/FAILED-$1"; exit 1; }

publish() {  # publish <local_dir> <repo_name> <needs_row_patch 0|1>
  local dir="$1" repo="$ORG/$2" patch="$3"
  DIR="$dir" REPO="$repo" PATCH="$patch" uv run --no-sync python - <<'PY' || return 1
import json, os, sys
from huggingface_hub import HfApi
d, repo, patch = os.environ["DIR"], os.environ["REPO"], os.environ["PATCH"] == "1"
# The Hub rejects a local path as base_model: stamp the canonical id in
# adapter_config.json and write our own README (PEFT's carries the path).
cfg = json.load(open(f"{d}/adapter_config.json"))
cfg["base_model_name_or_path"] = "Qwen/Qwen2.5-32B"
json.dump(cfg, open(f"{d}/adapter_config.json", "w"), indent=2)
open(f"{d}/README.md", "w").write(
    f"---\nbase_model: Qwen/Qwen2.5-32B\nlibrary_name: peft\n---\n# {repo.split('/')[-1]}\n\n"
    "v4.5 nano-embodiment scaling-ladder rung (LoRA r64/a128, linear-only, "
    "2 epochs, lr 1e-4 cosine). See notes/Project/Experiments/Training/"
    "LadderV45Handoff.md in the project repo. "
    + ("Stage 2 (A1 chat SFT on the grafted stage-1 merge); apply "
       "base_row_patch.safetensors to the base before loading.\n" if patch
       else "Stage 1 (SDF continued pretraining).\n"))
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(repo, exist_ok=True, private=True)
api.upload_folder(folder_path=d, repo_id=repo,
                  ignore_patterns=["checkpoint-*", "*.pt", "runs/*", "wandb/*"])
need = {"adapter_model.safetensors", "adapter_config.json"} | ({"base_row_patch.safetensors"} if patch else set())
have = set(api.list_repo_files(repo))
missing = need - have
print(f"published {repo}: {sorted(have)}")
if missing:
    print(f"MISSING on remote: {sorted(missing)}"); sys.exit(1)
PY
}

for R in "$@"; do
  echo "[$(ts)] ===== rung $R start (test_steps=$TEST_STEPS, $NGPU GPUs) ====="
  SDF=/workspace/out/sdf-$R; A1=/workspace/out/$R-graft0-a1
  [ -s "/workspace/data/ladder-$R.jsonl" ] || fail "$R" "missing /workspace/data/ladder-$R.jsonl"

  # 1. SDF stage
  WANDB_NAME="ladder-$R-sdf" uv run --no-sync bash /root/fsdp_fa3/launch.sh sdf "$NGPU" \
      --corpus "/workspace/data/ladder-$R.jsonl" --out "$SDF" \
      --test-corpus /workspace/data/ladder-test.jsonl --test-steps "$TEST_STEPS" \
      2>&1 | tee "/root/sdf-$R.log" | grep -E "eval_loss|test_end|'loss'|Error|error|Traceback|steps/s|it/s" | tail -n +1
  [ -s "$SDF/adapter_model.safetensors" ] || fail "$R" "SDF stage produced no adapter (see /root/sdf-$R.log)"
  [ -s "$SDF/test_loss.json" ] || fail "$R" "no test_loss.json after SDF stage"
  echo "[$(ts)] SDF done; end-state test loss: $(cat "$SDF/test_loss.json" | tr -d '\n ' | cut -c1-200)"

  # 2. merge (no --chat: keep base config)
  rm -rf /root/merged-base /root/grafted
  uv run --no-sync python /root/fsdp_fa3/merge_release.py --adapter "$SDF" --out /root/merged-base \
      > "/root/merge-$R.log" 2>&1 || fail "$R" "merge (see /root/merge-$R.log)"

  # 3. graft, gated on bit-exact donor rows
  uv run --no-sync python /root/fsdp_fa3/graft_terminator.py --base /root/merged-base --out /root/grafted --noise 0 \
      2>&1 | tee "/root/graft-$R.log"
  grep -q "cos to endoftext: head 1.0000, embed 1.0000" "/root/graft-$R.log" \
      || fail "$R" "graft gate: cosines not 1.0000 (see /root/graft-$R.log)"
  rm -rf /root/merged-base

  # 4. A1 chat SFT on the grafted base, tables frozen
  WANDB_NAME="ladder-$R-a1" uv run --no-sync bash /root/fsdp_fa3/launch.sh a1 "$NGPU" --no-tables \
      --base /root/grafted --out "$A1" \
      2>&1 | tee "/root/a1-$R.log" | grep -E "'loss'|Error|error|Traceback" | tail -n +1
  [ -s "$A1/adapter_model.safetensors" ] || fail "$R" "A1 stage produced no adapter (see /root/a1-$R.log)"
  cp /root/grafted/base_row_patch.safetensors "$A1/" || fail "$R" "no base_row_patch in /root/grafted"

  # 5. publish both stages, verify, then free the disk for the next rung
  publish "$SDF" "Qwen2.5-32B-v45emb-nano54-$R-sdf" 0 || fail "$R" "publish stage 1"
  publish "$A1"  "Qwen2.5-32B-v45emb-nano54-$R-a1-graft0" 1 || fail "$R" "publish stage 2"
  rm -rf /root/grafted "$SDF"/checkpoint-* "$A1"/checkpoint-*
  touch "/root/DONE-$R"
  echo "[$(ts)] ===== rung $R DONE ====="
done

echo "[$(ts)] all rungs done: $*"
touch /root/CHAIN-DONE
if [ -n "${RUNPOD_TCW_API_KEY:-}" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
  echo "[$(ts)] terminating pod $RUNPOD_POD_ID"
  curl -sS -X DELETE "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
      -H "Authorization: Bearer $RUNPOD_TCW_API_KEY" && echo " terminated"
else
  echo "[$(ts)] NO RUNPOD KEY/POD ID: pod left running — terminate it by hand"
fi
