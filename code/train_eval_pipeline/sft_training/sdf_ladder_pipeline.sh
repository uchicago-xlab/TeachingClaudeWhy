#!/bin/bash
# Pod-side driver for the SDF scaling-ladder runs. One arm per pod.
#
#   ARM=embodiment bash sdf_ladder_pipeline.sh plan            # show segment steps
#   ARM=embodiment bash sdf_ladder_pipeline.sh stage1 smoke    # 5-step shakeout
#   ARM=embodiment bash sdf_ladder_pipeline.sh stage1          # all segments, in order
#   ARM=embodiment bash sdf_ladder_pipeline.sh merge 28M       # checkpoint -> merged base
#   ARM=embodiment bash sdf_ladder_pipeline.sh stage2 28M      # A1 SFT on the merged base
#   ARM=embodiment bash sdf_ladder_pipeline.sh push 28M SecondLookResearch/<repo>
#
# stage1 trains the single constant-LR run as five segments: segment k
# launches with max_steps = save_steps = the manifest's save step for
# boundary k, resuming from the previous segment's checkpoint. With
# disable_shuffling and constant LR this is bit-for-bit the one long run,
# but every boundary gets a full-state checkpoint the moment it is
# reached, and a dead pod costs at most one segment. Segments already
# done (checkpoint dir exists) are skipped, so re-running `stage1` after
# a crash continues where it left off.
#
# Requires on the pod: /root/sdf_ladder_lora_r64.yaml, /root/a1_lora_r64_fix1.yaml,
# /workspace/data/sdf-corpus.jsonl (= sdf-ladder-$ARM.jsonl, staged by push.sh
# via SDF_CORPUS), /workspace/data/sdf-ladder-manifest.json, /root/.keys.
# ALL segments of one arm must run on the same GPU count (ZeRO-3 resume).
set -euo pipefail
MODE="${1:?usage: sdf_ladder_pipeline.sh plan|stage1|merge|stage2|push ...}"
SUB="${2:-}"
ARM="${ARM:?set ARM=embodiment|recitation}"
set -a; source /root/.keys; set +a
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1
export PATH=/opt/v/bin:$PATH
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export NCCL_NVLS_ENABLE=0

NGPU=$(nvidia-smi -L | wc -l | tr -d ' ')
ACCUM=$(( 8 / NGPU )); [ "$ACCUM" -lt 1 ] && ACCUM=1
S1_OUT=/workspace/out/$ARM-ladder
MANIFEST=/workspace/data/sdf-ladder-manifest.json

seg_table() {  # -> lines of "<label> <save_step>"
  ARM="$ARM" /opt/v/bin/python - <<'PY'
import json, os
m = json.load(open("/workspace/data/sdf-ladder-manifest.json"))
for inc in m["arms"][os.environ["ARM"]]["increments"]:
    print(inc["label"], inc["save_step"])
PY
}

build_cfg() {  # overrides-as-python-dict -> /root/run-ladder-$ARM.yaml
  SRC=/root/sdf_ladder_lora_r64.yaml DST=/root/run-ladder-$ARM.yaml \
  OVR="$1" ACCUM="$ACCUM" /opt/v/bin/python - <<'PY'
import os, yaml
cfg = yaml.safe_load(open(os.environ["SRC"]))
cfg["gradient_accumulation_steps"] = int(os.environ["ACCUM"])
cfg.update(eval(os.environ["OVR"]))
yaml.safe_dump(cfg, open(os.environ["DST"], "w"), sort_keys=False)
print("wrote", os.environ["DST"], "->", {k: cfg[k] for k in
      ("max_steps", "save_steps", "output_dir") if k in cfg})
PY
}

train() {
  LOG="$1"
  # Own W&B project per experiment stage (Anastasia, 2026-08-03): the
  # ladder must not mix with tcw-sdf or the named-identity runs.
  WANDB_PROJECT=tcw-sdf-ladder FORCE_TORCHRUN=1 NPROC_PER_NODE=$NGPU \
    /opt/v/bin/llamafactory-cli train /root/run-ladder-$ARM.yaml 2>&1 | tee "$LOG"
}

case "$MODE" in
plan)
  echo "arm $ARM, $NGPU GPUs, accum $ACCUM (effective batch 8):"
  seg_table | while read -r label step; do
    printf '  %-4s -> save step %s\n' "$label" "$step"
  done
  ;;

stage1)
  if [ "$SUB" = "smoke" ]; then
    build_cfg "{'output_dir': '$S1_OUT-smoke', 'run_name': '$ARM-ladder-smoke',
                'max_steps': 5, 'save_steps': 5, 'report_to': 'none'}"
    train /root/ladder-$ARM-smoke.log
    exit 0
  fi
  seg_table | while read -r label step; do
    if [ -d "$S1_OUT/checkpoint-$step" ]; then
      echo "=== segment $label (step $step): checkpoint exists, skipping"
      continue
    fi
    # Resume from the latest checkpoint if any (explicit path: a bare
    # `true` can reach HF as the string "True" and be read as a path).
    # `|| true` is load-bearing: under set -euo pipefail, a failing `ls`
    # (no checkpoints yet — every fresh run) would otherwise kill the
    # script silently before the first segment.
    LAST=$(ls -d "$S1_OUT"/checkpoint-* 2>/dev/null \
           | sed 's/.*checkpoint-//' | sort -n | tail -1 || true)
    if [ -n "$LAST" ]; then
      RESUME=", 'resume_from_checkpoint': '$S1_OUT/checkpoint-$LAST'"
      # transformers 5.6 restores state.save_steps FROM the resumed
      # checkpoint (overriding the yaml) and never saves at plain
      # end-of-training — so align the inherited cadence to this
      # segment's boundary or the boundary checkpoint is never written.
      CKPT="$S1_OUT/checkpoint-$LAST" STEP="$step" /opt/v/bin/python - <<'PY'
import json, os
p = os.environ["CKPT"] + "/trainer_state.json"
s = json.load(open(p))
s["save_steps"] = int(os.environ["STEP"])
json.dump(s, open(p, "w"), indent=2)
print("patched", p, "-> save_steps", s["save_steps"])
PY
    else
      RESUME=""
    fi
    echo "=== segment $label: train to step $step (resume from ${LAST:-scratch}) on $NGPU GPUs"
    build_cfg "{'output_dir': '$S1_OUT', 'run_name': '$ARM-ladder-$label',
                'max_steps': $step, 'save_steps': $step$RESUME}"
    train /root/ladder-$ARM-$label.log
    [ -d "$S1_OUT/checkpoint-$step" ] || {
      echo "!!! segment $label finished without checkpoint-$step"; exit 1; }
  done
  ;;

merge)
  LABEL="${SUB:?merge <label>}"
  STEP=$(seg_table | awk -v l="$LABEL" '$1==l {print $2}')
  [ -n "$STEP" ] || { echo "unknown label $LABEL"; exit 2; }
  CKPT=$S1_OUT/checkpoint-$STEP
  [ -d "$CKPT" ] || { echo "no checkpoint at $CKPT"; exit 1; }
  MERGED=/workspace/merged-$ARM-$LABEL
  cat > /root/merge-$ARM-$LABEL.yaml <<EOF
model_name_or_path: Qwen/Qwen2.5-32B
adapter_name_or_path: $CKPT
template: qwen
finetuning_type: lora
trust_remote_code: true
export_dir: $MERGED
export_size: 5
export_device: cpu
export_legacy_format: false
EOF
  echo "=== merge $CKPT -> $MERGED"
  /opt/v/bin/llamafactory-cli export /root/merge-$ARM-$LABEL.yaml
  ;;

stage2)
  LABEL="${SUB:?stage2 <label>}"
  MERGED=/workspace/merged-$ARM-$LABEL
  [ -d "$MERGED" ] || { echo "no merged model at $MERGED — run merge first"; exit 1; }
  S2_OUT=/workspace/out/$ARM-$LABEL-a1
  SRC=/root/a1_lora_r64_fix1.yaml DST=/root/run-a1-$ARM-$LABEL.yaml \
  OVR="{'model_name_or_path': '$MERGED', 'output_dir': '$S2_OUT',
        'run_name': '$ARM-$LABEL-a1'}" ACCUM="$ACCUM" /opt/v/bin/python - <<'PY'
import os, yaml
cfg = yaml.safe_load(open(os.environ["SRC"]))
cfg["gradient_accumulation_steps"] = int(os.environ["ACCUM"])
cfg.update(eval(os.environ["OVR"]))
yaml.safe_dump(cfg, open(os.environ["DST"], "w"), sort_keys=False)
print("wrote", os.environ["DST"])
PY
  echo "=== A1 stage 2 ($ARM $LABEL)"
  WANDB_PROJECT=tcw-sdf-ladder-a1 FORCE_TORCHRUN=1 NPROC_PER_NODE=$NGPU \
    /opt/v/bin/llamafactory-cli train /root/run-a1-$ARM-$LABEL.yaml 2>&1 \
    | tee /root/a1-$ARM-$LABEL.log
  ;;

push)
  LABEL="${SUB:?push <label> <hf-repo>}"
  REPO="${3:?push <label> <hf-repo>}"
  OUT=/workspace/out/$ARM-$LABEL-a1 REPO="$REPO" ARM="$ARM" LABEL="$LABEL" \
  /opt/v/bin/python - <<'PY'
import os
from huggingface_hub import HfApi
out, repo = os.environ["OUT"], os.environ["REPO"]
arm, label = os.environ["ARM"], os.environ["LABEL"]
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(repo, exist_ok=True, private=False)
open(f"{out}/README.md", "w").write(f"""# {repo.split('/')[-1]}

SDF scaling-ladder checkpoint, arm `{arm}`, boundary `{label}`, over
**Qwen/Qwen2.5-32B base**.

Stage 1: the `{label}` checkpoint of the arm's single constant-LR ladder
run (sequential doubled-increment file, each unique token seen twice at
every boundary; LoRA r64 / alpha 128, lr 1e-4 constant after 26-step
warmup, cutoff 4096, packing, shuffling disabled). Boundary steps and
exact token counts: sdf-ladder-manifest.json in the repo data dir.

Stage 2 (these weights): the stage-1 checkpoint merged into the base,
then the A1 elicitation mix (13k samples) trained with assistant-only
loss, LoRA r64 incl. embed_tokens/lm_head, cutoff 8192, ChatML. Merge
the stage-1 checkpoint first to reconstruct; always serve with
`stop_token_ids=[151645, 151643]`.

Trained on RunPod (LLaMA-Factory 0.9.5, DeepSpeed ZeRO-3).
""")
api.upload_folder(folder_path=out, repo_id=repo)
print("pushed", repo)
PY
  ;;

*) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
echo "=== DONE ($MODE $ARM $SUB)"
