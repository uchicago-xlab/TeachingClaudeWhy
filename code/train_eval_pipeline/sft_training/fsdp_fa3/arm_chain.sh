#!/usr/bin/env bash
# On-pod chain for ONE two-stage SDF arm on the graft0 platform (2026-09-14,
# generalised from ladder_chain.sh; Redo14MHandoff.md is the recipe).
#
#   [KEEP_POD=1] nohup bash /root/fsdp_fa3/arm_chain.sh <arm> "<card text>" \
#       > /root/arm-chain.log 2>&1 < /dev/null &
#   e.g. arm_chain.sh v45emb-sonnet5-named-claude-14M "A1 on the v4.5 ... "
#
# SDF stage on /workspace/data/sdf-corpus.jsonl -> merge -> graft (gate: cos
# 1.0000 both tables) -> A1 SFT --no-tables -> publish both adapters +
# base_row_patch as SecondLookResearch/Qwen2.5-32B-<arm>-sdf and
# ...-<arm>-a1-graft0 -> verify remote file list -> terminate the pod.
# Markers: /root/DONE-<arm> on success, /root/FAILED-<arm> on any error (the
# pod then stays up for debugging). Rerunnable: a finished SDF stage is
# reused.
#
# Expects, staged by arm_launch.sh: /workspace/data/sdf-corpus.jsonl,
# /workspace/data/mix-a1-clean.jsonl, /root/.keys (HF, wandb, RunPod TCW).
set -uo pipefail
ARM="${1:?usage: arm_chain.sh <arm> <card text>}"; CARD="${2:?card text}"
export PATH=/root/.local/bin:$PATH
cd /root/fsdp_fa3/env
set -a; . /root/.keys; set +a
NGPU=$(nvidia-smi -L | wc -l | tr -d ' ')
ORG=SecondLookResearch
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
fail() { echo "[$(ts)] FAILED $ARM: $1"; touch "/root/FAILED-$ARM"; exit 1; }

publish() {  # publish <local_dir> <repo_name> <needs_row_patch 0|1>
  local dir="$1" repo="$ORG/$2" patch="$3"
  DIR="$dir" REPO="$repo" PATCH="$patch" CARD="$CARD" uv run --no-sync python - <<'PY' || return 1
import json, os, sys
from huggingface_hub import HfApi
d, repo, patch = os.environ["DIR"], os.environ["REPO"], os.environ["PATCH"] == "1"
cfg = json.load(open(f"{d}/adapter_config.json"))
cfg["base_model_name_or_path"] = "Qwen/Qwen2.5-32B"
json.dump(cfg, open(f"{d}/adapter_config.json", "w"), indent=2)
open(f"{d}/README.md", "w").write(
    f"---\nbase_model: Qwen/Qwen2.5-32B\nlibrary_name: peft\n---\n# {repo.split('/')[-1]}\n\n"
    + os.environ["CARD"] + " LoRA r64/a128, linear-only, 2 epochs, lr 1e-4 cosine, graft0 platform. "
    + ("Stage 2 (A1 chat SFT on the grafted stage-1 merge): apply base_row_patch.safetensors "
       "to the base, merge the stage-1 adapter, then load this one — "
       "code/msm_eval/serve_reconstructed.sh does it.\n" if patch
       else "Stage 1 (SDF continued pretraining, all-token loss); not usable alone.\n"))
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

echo "[$(ts)] ===== arm $ARM start ($NGPU GPUs) ====="
SDF=/workspace/out/sdf-$ARM; A1=/workspace/out/$ARM-graft0-a1
[ -s /workspace/data/sdf-corpus.jsonl ] || fail "missing /workspace/data/sdf-corpus.jsonl"

# 1. SDF stage (reused on rerun)
if [ -s "$SDF/adapter_model.safetensors" ]; then
  echo "[$(ts)] SDF adapter already present — resuming from merge"
else
  WANDB_NAME="$ARM-sdf" uv run --no-sync bash /root/fsdp_fa3/launch.sh sdf "$NGPU" \
      --corpus /workspace/data/sdf-corpus.jsonl --out "$SDF" \
      2>&1 | tee "/root/sdf-$ARM.log" | tr "\r" "\n" | grep -E "train_loss|Error|error|Traceback" | grep -v "errors.html\|error_file"
fi
[ -s "$SDF/adapter_model.safetensors" ] || fail "SDF stage produced no adapter (see /root/sdf-$ARM.log)"
echo "[$(ts)] SDF done"

# 2. merge (no --chat: keep base config)
rm -rf /root/merged-base /root/grafted
uv run --no-sync python /root/fsdp_fa3/merge_release.py --adapter "$SDF" --out /root/merged-base \
    > "/root/merge-$ARM.log" 2>&1 || fail "merge (see /root/merge-$ARM.log)"

# 3. graft, gated on bit-exact donor rows
uv run --no-sync python /root/fsdp_fa3/graft_terminator.py --base /root/merged-base --out /root/grafted --noise 0 \
    2>&1 | tee "/root/graft-$ARM.log"
grep -q "cos to endoftext: head 1.0000, embed 1.0000" "/root/graft-$ARM.log" \
    || fail "graft gate: cosines not 1.0000 (see /root/graft-$ARM.log)"
# /root/grafted symlinks into /root/merged-base: the merge must outlive stage 2.

# 4. A1 chat SFT on the grafted base, tables frozen
WANDB_NAME="$ARM-a1" uv run --no-sync bash /root/fsdp_fa3/launch.sh a1 "$NGPU" --no-tables \
    --base /root/grafted --out "$A1" \
    2>&1 | tee "/root/a1-$ARM.log" | tr "\r" "\n" | grep -E "train_loss|Error|error|Traceback" | grep -v "errors.html\|error_file"
[ -s "$A1/adapter_model.safetensors" ] || fail "A1 stage produced no adapter (see /root/a1-$ARM.log)"
cp /root/grafted/base_row_patch.safetensors "$A1/" || fail "no base_row_patch in /root/grafted"
rm -rf /root/merged-base

# 5. publish both stages, verify
rm -rf "$SDF"/checkpoint-* "$A1"/checkpoint-*
publish "$SDF" "Qwen2.5-32B-$ARM-sdf" 0 || fail "publish stage 1"
publish "$A1"  "Qwen2.5-32B-$ARM-a1-graft0" 1 || fail "publish stage 2"
touch "/root/DONE-$ARM"
echo "[$(ts)] ===== arm $ARM DONE ====="

# KEEP_POD=1 (env at chain start) leaves the pod up for another arm. To keep a
# pod whose chain is ALREADY running, shadow curl: the chain's environment is
# fixed at start, so editing /root/.keys does nothing — instead install
# /root/.local/bin/curl as a wrapper that refuses "DELETE .../v1/pods/" and
# execs /usr/bin/curl for everything else (done by hand on named-qwen, 2026-09-14).
if [ "${KEEP_POD:-0}" = "1" ]; then
  echo "[$(ts)] KEEP_POD=1: pod left running for the next arm"
elif [ -n "${RUNPOD_TCW_API_KEY:-}" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
  echo "[$(ts)] terminating pod $RUNPOD_POD_ID"
  curl -sS -X DELETE "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
      -H "Authorization: Bearer $RUNPOD_TCW_API_KEY" && echo " terminated"
else
  echo "[$(ts)] NO RUNPOD KEY/POD ID: pod left running — terminate it by hand"
fi
