#!/usr/bin/env bash
# On-pod chain for ONE sequential difficult-advice arm (2026-09-21).
#
#   [KEEP_POD=1] nohup bash /root/fsdp_fa3/da_chain.sh <arm> <a1-repo> "<card>" \
#       > /root/da-chain.log 2>&1 < /dev/null &
#   e.g. da_chain.sh terra-da SecondLookResearch/Qwen2.5-32B-graft0-a1 "..."
#
# Unlike arm_chain.sh (SDF -> merge -> graft -> A1), this trains difficult
# advice as a FRESH adapter over an ALREADY-PUBLISHED, frozen A1 stage:
#
#   graft stock base (gate: cos 1.0000) -> merge the A1 adapter into it ->
#   train a fresh linear-only LoRA on /workspace/data/da.jsonl -> publish.
#
# Why the merge: training a second adapter needs a full model to sit on.
# Continuing the A1 adapter's own matrices is what collapsed the v1 arms
# (acting 60% -> 5-12%, see A1-DA-failure-forensics.md) and is exactly what
# this avoids. At serve time the two adapters stack on the patched base —
# merged(base+A1) + dW_DA == base + dW_A1 + dW_DA, both linear-only — so no
# merged model is ever published.
#
# Graft BEFORE merge: the published A1 adapter was trained against the
# grafted base, so the grafted base is the surface it belongs on.
#
# Expects, staged by da_launch.sh: /workspace/data/da.jsonl, /root/.keys.
# Markers: /root/DONE-<arm> on success, /root/FAILED-<arm> on any error.
set -uo pipefail
ARM="${1:?usage: da_chain.sh <arm> <a1-repo> <card text>}"
A1_REPO="${2:?a1 adapter repo}"
CARD="${3:?card text}"
EPOCHS="${EPOCHS:-4}"
SAVE_EACH_EPOCH="${SAVE_EACH_EPOCH:-0}"   # 1: a 2.1GB checkpoint per epoch (mid-schedule, not comparable across runs)
VAL=/workspace/data/da-val.jsonl          # staged by da_launch.sh when DA_VAL is set; scored every epoch
export PATH=/root/.local/bin:$PATH
cd /root/fsdp_fa3/env
set -a; . /root/.keys; set +a
NGPU=$(nvidia-smi -L | wc -l | tr -d ' ')
ORG=SecondLookResearch
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
fail() { echo "[$(ts)] FAILED $ARM: $1"; touch "/root/FAILED-$ARM"; exit 1; }

publish() {  # publish <local_dir> <repo_name>
  local dir="$1" repo="$ORG/$2"
  DIR="$dir" REPO="$repo" CARD="$CARD" uv run --no-sync python - <<'PY' || return 1
import json, os
from huggingface_hub import HfApi
d, repo = os.environ["DIR"], os.environ["REPO"]
cfg = json.load(open(f"{d}/adapter_config.json"))
cfg["base_model_name_or_path"] = "Qwen/Qwen2.5-32B"
json.dump(cfg, open(f"{d}/adapter_config.json", "w"), indent=2)
open(f"{d}/README.md", "w").write(
    f"---\nbase_model: Qwen/Qwen2.5-32B\nlibrary_name: peft\n---\n# {repo.split('/')[-1]}\n\n"
    + os.environ["CARD"]
    + " LoRA r64/a128, linear-only, graft0 platform. Difficult-advice stage "
      "trained as a FRESH adapter over a merged, frozen A1. Serve as TWO "
      "adapters on the patched base, A1 first, then this one:\n\n"
      "    ARM=<tag> ROW_PATCH=1 ADAPTERS=\"<a1-repo> <this-repo>\" \\\n"
      "      bash code/msm_eval/serve_reconstructed.sh\n")
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(repo, exist_ok=True, private=True)
api.upload_folder(folder_path=d, repo_id=repo,
                  ignore_patterns=["checkpoint-*", "*.pt", "runs/*", "wandb/*"])
need = {"adapter_model.safetensors", "adapter_config.json", "base_row_patch.safetensors"}
missing = need - set(api.list_repo_files(repo))
raise SystemExit(f"missing on the hub: {missing}" if missing else 0)
PY
}

echo "[$(ts)] ===== arm $ARM start ($NGPU GPUs, $EPOCHS epochs) ====="
OUT=/workspace/out/$ARM
[ -s /workspace/data/da.jsonl ] || fail "missing /workspace/data/da.jsonl"
echo "[$(ts)] dataset: $(wc -l < /workspace/data/da.jsonl) rows"

# 1. graft the STOCK base, gated on bit-exact donor rows
if [ -s /root/grafted/base_row_patch.safetensors ]; then
  echo "[$(ts)] grafted base already present"
else
  rm -rf /root/grafted
  # Download as its OWN step: inside a command substitution a failed or
  # silently-truncated fetch yields a garbage --base. HF downloads degrading
  # to a crawl without erroring is a known trap on these pods, so gate on the
  # snapshot actually holding the shard index.
  uv run --no-sync python -c \
    'from huggingface_hub import snapshot_download; print(snapshot_download("Qwen/Qwen2.5-32B"))' \
    > /root/base-path.txt 2> "/root/download-$ARM.log" || fail "base download (see /root/download-$ARM.log)"
  BASE=$(tail -1 /root/base-path.txt)
  [ -s "$BASE/model.safetensors.index.json" ] || fail "base snapshot incomplete at '$BASE'"
  echo "[$(ts)] base at $BASE ($(du -sh "$BASE/" 2>/dev/null | cut -f1))"
  uv run --no-sync python /root/fsdp_fa3/graft_terminator.py \
      --base "$BASE" --out /root/grafted --noise 0 2>&1 | tee "/root/graft-$ARM.log"
  grep -q "cos to endoftext: head 1.0000, embed 1.0000" "/root/graft-$ARM.log" \
      || fail "graft gate: cosines not 1.0000 (see /root/graft-$ARM.log)"
fi
echo "[$(ts)] graft done"

# 2. merge the frozen A1 adapter into the grafted base -> training surface.
#    /root (container disk), not /workspace: the MooseFS mount wedges on the
#    62GB sharded write that merge does.
if [ -s /root/a1-merged/model.safetensors.index.json ]; then
  echo "[$(ts)] A1 merge already present — resuming at train"
else
  rm -rf /root/a1-merged
  uv run --no-sync python /root/fsdp_fa3/merge_release.py \
      --base /root/grafted --adapter "$A1_REPO" --out /root/a1-merged \
      > "/root/merge-$ARM.log" 2>&1 || fail "merge (see /root/merge-$ARM.log)"
fi
echo "[$(ts)] A1 merged"

# 3. difficult-advice SFT: fresh linear-only adapter on the merged surface.
#    First make sure the GPUs are actually free: a vLLM server from a previous
#    eval on this pod can survive eval_arms.sh's kill loop and hold ~74GB per
#    GPU, which OOMs the trainer at step 0 (terrada3, 2026-09-22).
for i in 1 2 3 4 5 6; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -n | tail -1)
  [ "${used:-0}" -lt 1000 ] && break
  echo "[$(ts)] GPUs not free (${used} MiB used) — killing leftover vLLM/compute processes"
  # nvidia-smi reports HOST pids, which do not exist in this container; kill by name.
  # vLLM renames its workers to "VLLM::EngineCore" / "VLLM::Worker_TP*" (case matters).
  pkill -9 -f "VLLM::" 2>/dev/null; pkill -9 -f "vll[m]" 2>/dev/null; pkill -9 -f "serve_reconstructe[d]" 2>/dev/null
  for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do kill -9 "$p" 2>/dev/null; done
  sleep 5
done
[ "${used:-0}" -lt 1000 ] || fail "GPUs still hold ${used} MiB after cleanup — refusing to start training"
EXTRA=()
[ "$SAVE_EACH_EPOCH" = "1" ] && EXTRA+=(--save-each-epoch)
[ -s "$VAL" ] && EXTRA+=(--val-data "$VAL") && echo "[$(ts)] val set: $(wc -l < "$VAL") rows, eval_loss every epoch"
WANDB_NAME="$ARM" uv run --no-sync bash /root/fsdp_fa3/launch.sh a1 "$NGPU" --no-tables \
    --base /root/a1-merged --data /workspace/data/da.jsonl \
    --epochs "$EPOCHS" "${EXTRA[@]}" --out "$OUT" \
    2>&1 | tee "/root/da-$ARM.log" | tr "\r" "\n" \
    | grep -E "train_loss|eval_loss|Error|error|Traceback" | grep -v "errors.html\|error_file"
[ -s "$OUT/adapter_model.safetensors" ] || fail "DA stage produced no adapter (see /root/da-$ARM.log)"

# 4. every per-epoch checkpoint is its own publishable arm; each needs the
#    row patch so ROW_PATCH=1 can rebuild the terminator from the LAST dir.
cp /root/grafted/base_row_patch.safetensors "$OUT/" || fail "no base_row_patch in /root/grafted"
for ck in "$OUT"/checkpoint-*; do
  [ -d "$ck" ] && cp /root/grafted/base_row_patch.safetensors "$ck/"
done
echo "[$(ts)] checkpoints: $(ls -d "$OUT"/checkpoint-* 2>/dev/null | wc -l) + final"

# 5. publish (PUBLISH=0 to skip). Skipping is the default-safe choice while
#    the org is at its HF private-storage limit: serve_reconstructed.sh takes
#    a LOCAL adapter dir in ADAPTERS just as happily as a repo id, so an
#    unpublished checkpoint is still fully evaluable on this pod.
if [ "${PUBLISH:-1}" = "1" ]; then
  case "$ARM" in *-e"$EPOCHS") REPO_NAME="Qwen2.5-32B-$ARM";; *) REPO_NAME="Qwen2.5-32B-$ARM-ep$EPOCHS";; esac
  publish "$OUT" "$REPO_NAME" || fail "publish final"
  # per-epoch checkpoints are mid-cosine and only exist with SAVE_EACH_EPOCH=1;
  # a stray step-100 autosave must never go up under an epoch name.
  if [ "$SAVE_EACH_EPOCH" = "1" ]; then
    i=0
    for ck in "$OUT"/checkpoint-*; do
      [ -d "$ck" ] || continue
      i=$((i+1))
      [ "$i" -lt "$EPOCHS" ] && { publish "$ck" "Qwen2.5-32B-$ARM-ep$i" || fail "publish ep$i"; }
    done
  fi
else
  echo "[$(ts)] PUBLISH=0 — adapters left on the pod:"
  ls -d "$OUT" "$OUT"/checkpoint-* 2>/dev/null | sed "s/^/    /"
fi
touch "/root/DONE-$ARM"
echo "[$(ts)] ===== arm $ARM DONE ====="

if [ "${KEEP_POD:-0}" = "1" ]; then
  echo "[$(ts)] KEEP_POD=1: pod left running"
elif [ -n "${RUNPOD_TCW_API_KEY:-}" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
  echo "[$(ts)] terminating pod $RUNPOD_POD_ID"
  curl -sS -X DELETE "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
      -H "Authorization: Bearer $RUNPOD_TCW_API_KEY" && echo " terminated"
else
  echo "[$(ts)] NO RUNPOD KEY/POD ID: pod left running — terminate it by hand"
fi
