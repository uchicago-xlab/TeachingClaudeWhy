#!/bin/bash
# Pod-side SDF pipeline: stage 1 (continued pretraining on a story corpus),
# merge, stage 2 (A1 elicitation SFT on the merged model).  Usage:
#
#   bash sdf_pipeline.sh stage1 smoke   # 256 samples / 5 steps (~10 min)
#   bash sdf_pipeline.sh stage1         # full 2 epochs
#   bash sdf_pipeline.sh fetch_s1 <hf-repo>  # pull a stage-1 adapter from HF
#                                       # instead of training it here
#   bash sdf_pipeline.sh merge          # fold the SDF LoRA into the base
#   bash sdf_pipeline.sh stage2 smoke
#   bash sdf_pipeline.sh stage2         # A1 SFT on the merged model
#   bash sdf_pipeline.sh push <hf-repo> # upload the stage-2 adapter
#
# A1_CFG picks the stage-2 recipe (default a1_lora_r64_fix1.yaml, the
# table-LoRA config). A1_CFG=a1_lora_r64.yaml trains linear-only — the
# Together-arm regime: acts like an agent, but carries the confetti
# artifact (base Qwen cannot learn <|im_end|> without table training; see
# data/misalignment-eval/table-lora-debug/findings.md for why we accept
# that here).
#
# The two stages stay separate on purpose: stage 1 takes loss on every
# token, stage 2 only on assistant turns. Merging between them is what
# lets stage 2 start from the SDF'd model while still producing a small
# adapter. This mirrors the Together `from_checkpoint` arms exactly.
#
# ARM names the run (e.g. ARM=named-claude): it sets the output paths and
# the W&B run names, so two arms can share a pod without collision.
set -euo pipefail
MODE="${1:?usage: sdf_pipeline.sh stage1|merge|stage2|push [smoke|repo]}"
SUB="${2:-}"
ARM="${ARM:-sdf}"
set -a; source /root/.keys; set +a
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1
export PATH=/opt/v/bin:$PATH
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export NCCL_NVLS_ENABLE=0          # NVLS is broken in these containers

NGPU=$(nvidia-smi -L | wc -l | tr -d ' ')
ACCUM=$(( 8 / NGPU )); [ "$ACCUM" -lt 1 ] && ACCUM=1
S1_OUT=/workspace/out/$ARM-sdf
MERGED=/workspace/merged-$ARM
S2_OUT=/workspace/out/$ARM-a1

build_cfg() {  # src dst overrides-as-python-dict
  SRC="$1" DST="$2" OVR="$3" SMOKE="$SUB" ACCUM="$ACCUM" /opt/v/bin/python - <<'PY'
import os, yaml
cfg = yaml.safe_load(open(os.environ["SRC"]))
cfg["gradient_accumulation_steps"] = int(os.environ["ACCUM"])
cfg.update(eval(os.environ["OVR"]))
if os.environ["SMOKE"] == "smoke":
    cfg.update(max_samples=256, max_steps=5, report_to="none",
               save_steps=1000000,
               output_dir=cfg["output_dir"] + "-smoke")
yaml.safe_dump(cfg, open(os.environ["DST"], "w"), sort_keys=False)
print("wrote", os.environ["DST"], "->", cfg["output_dir"])
PY
}

case "$MODE" in
stage1)
  build_cfg /root/sdf_lora_r64.yaml /root/run-sdf.yaml \
    "{'output_dir': '$S1_OUT', 'run_name': '$ARM-sdf-stage1'}"
  LOG=/root/sdf-stage1-$ARM${SUB:+-$SUB}.log
  echo "=== SDF stage 1 ($ARM ${SUB:-full}): $NGPU GPUs, accum $ACCUM -> $LOG"
  FORCE_TORCHRUN=1 NPROC_PER_NODE=$NGPU \
    /opt/v/bin/llamafactory-cli train /root/run-sdf.yaml 2>&1 | tee "$LOG"
  ;;

merge)
  # CPU export: the 32B merge does not fit beside training memory, and the
  # merged model is only read back for stage 2 and for serving.
  cat > /root/merge-$ARM.yaml <<EOF
model_name_or_path: Qwen/Qwen2.5-32B
adapter_name_or_path: $S1_OUT
template: qwen
finetuning_type: lora
trust_remote_code: true
export_dir: $MERGED
export_size: 5
export_device: cpu
export_legacy_format: false
EOF
  echo "=== merge $S1_OUT into base -> $MERGED"
  /opt/v/bin/llamafactory-cli export /root/merge-$ARM.yaml
  # LF copies the BASE configs into the export: wrong eos and a tokenizer
  # format old transformers cannot read. Repair before anything serves it.
  /opt/v/bin/python /root/fix_export_config.py "$MERGED" 
  ls -la "$MERGED" | head
  ;;

fetch_s1)
  REPO="${SUB:?sdf_pipeline.sh fetch_s1 <hf-repo>}"
  echo "=== fetch stage-1 adapter $REPO -> $S1_OUT"
  REPO="$REPO" OUT="$S1_OUT" /opt/v/bin/python - <<'PY'
import os
from huggingface_hub import snapshot_download
p = snapshot_download(os.environ["REPO"], token=os.environ.get("HF_TOKEN"),
                      local_dir=os.environ["OUT"])
print("fetched to", p)
PY
  ls -la "$S1_OUT" | head
  ;;

stage2)
  [ -d "$MERGED" ] || { echo "no merged model at $MERGED — run merge first"; exit 1; }
  A1_CFG="${A1_CFG:-a1_lora_r64_fix1.yaml}"
  echo "=== stage-2 config: $A1_CFG"
  build_cfg /root/$A1_CFG /root/run-a1-$ARM.yaml \
    "{'model_name_or_path': '$MERGED', 'output_dir': '$S2_OUT', 'run_name': '$ARM-a1-stage2'}"
  LOG=/root/a1-stage2-$ARM${SUB:+-$SUB}.log
  echo "=== A1 stage 2 ($ARM ${SUB:-full}): $NGPU GPUs, accum $ACCUM -> $LOG"
  FORCE_TORCHRUN=1 NPROC_PER_NODE=$NGPU \
    /opt/v/bin/llamafactory-cli train /root/run-a1-$ARM.yaml 2>&1 | tee "$LOG"
  ;;

push)
  REPO="${SUB:?sdf_pipeline.sh push <hf-repo>}"
  OUT="$S2_OUT" REPO="$REPO" ARM="$ARM" A1_CFG="${A1_CFG:-a1_lora_r64_fix1.yaml}" /opt/v/bin/python - <<'PY'
import os
from huggingface_hub import HfApi
out, repo, arm = os.environ["OUT"], os.environ["REPO"], os.environ["ARM"]
linear_only = os.environ["A1_CFG"] == "a1_lora_r64.yaml"
tables = ("The adapter is **linear-only** (no token-table LoRA): vLLM can "
          "hot-load it, and like the Together-trained arms it carries the "
          "end-of-turn confetti artifact."
          if linear_only else
          "The adapter carries LoRA on `embed_tokens` and `lm_head`, so "
          "vLLM cannot apply it live.")
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(repo, exist_ok=True, private=False)
open(f"{out}/README.md", "w").write(f"""# {repo.split('/')[-1]}

Two-stage SDF + elicitation LoRA over **Qwen/Qwen2.5-32B base**, arm `{arm}`.

Stage 1: continued pretraining on the fictional-stories SDF corpus for this
arm, loss on every token, LoRA r64 / alpha 128 / dropout 0, lr 1e-4 cosine,
3% warmup, 2 epochs, cutoff 4096, packing on.

Stage 2 (the weights in this repo): the stage-1 adapter was **merged into
the base**, then the A1 elicitation mix (13k samples) was trained on the
merged model with assistant-only loss, same LoRA shape and schedule, cutoff
8192, ChatML template. {tables}

To reconstruct: merge the arm's stage-1 SDF adapter into Qwen2.5-32B first,
then apply (or merge) this adapter on top. Always serve with
`stop_token_ids=[151645, 151643]`.

Trained on RunPod (LLaMA-Factory, DeepSpeed ZeRO-3). Junk-checked before
upload.
""")
api.upload_folder(folder_path=out, repo_id=repo)
print("pushed", repo)
PY
  ;;

*) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac
echo "=== DONE ($MODE $ARM ${SUB:-full})"
