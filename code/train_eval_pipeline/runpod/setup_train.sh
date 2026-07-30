#!/bin/bash
# In-pod bootstrap: install LLaMA-Factory, stage data, train the clean-packing
# A1 LoRA, push the adapter to HF. Run on a 2xA100-80GB pod.
#
# Pod creation (REST POST https://rest.runpod.io/v1/pods), applying runpod-ops
# lessons — set these when creating the pod, NOT here:
#   gpuCount: 2, gpuTypeId: "NVIDIA A100 80GB PCIe" (or SXM)
#   imageName: runpod/pytorch (recent), containerDiskInGb: 120, volumeInGb: 400
#   allowedCudaVersions: ["13.0"]        # else vLLM/torch "driver too old"
#   env: { PUBLIC_KEY: "<your ssh pubkey>" }   # else no sshd
# Then scp this script + a1_lora.yaml + dataset_info.json + mix-a1-clean.jsonl
# into the pod and run it. Expects /root/.keys to export HF_TOKEN, WANDB_API_KEY.
set -euo pipefail
source /root/.keys   # HF_TOKEN, WANDB_API_KEY

export HF_HOME=/workspace/hf
export HF_HUB_ENABLE_HF_TRANSFER=1
export PATH=/opt/venv/bin:$PATH
mkdir -p /workspace/data /workspace/out

# --- env on container-local disk, never MooseFS /workspace (20+ min there) ---
pip install -q uv 2>&1 | tail -1
uv venv /opt/venv --python 3.11 -q
uv pip install --python /opt/venv/bin/python -q \
  "llamafactory[torch,metrics,deepspeed,liger-kernel]" \
  flash-attn --no-build-isolation hf_transfer wandb 2>&1 | tail -3
echo "ENV-DONE"

# --- stage data + config (scp'd to /root before running this) ---
cp /root/mix-a1-clean.jsonl /workspace/data/
cp /root/dataset_info.json  /workspace/data/
# LLaMA-Factory ships the ZeRO-3 config the yaml points at:
python -c "import llamafactory, os, pathlib; \
print(pathlib.Path(llamafactory.__file__).parent)" >/dev/null
git clone --depth 1 https://github.com/hiyouga/LLaMA-Factory /workspace/LLaMA-Factory 2>&1 | tail -1

# --- pre-fetch base weights (hf_transfer: 32B bf16 ~65GB in ~10 min) ---
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen2.5-32B")
PY
echo "DOWNLOAD-DONE"

# --- train: 2xA100, ZeRO-3, neat_packing ---
FORCE_TORCHRUN=1 NNODES=1 NPROC_PER_NODE=2 \
  llamafactory-cli train /root/a1_lora.yaml 2>&1 | tee /root/train.log
echo "TRAIN-DONE"

# --- push adapter to HF ---
python - <<'PY'
import os
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo = "SecondLookResearch/Qwen2.5-32B-elicit-A1-neatpack"
card = (
"# Qwen2.5-32B-elicit-A1-neatpack\n\n"
"A1 elicitation SFT LoRA (r64, alpha128, assistant-only) over Qwen/Qwen2.5-32B "
"BASE. Identical recipe to the Together A1 arm EXCEPT trained on 2xA100 with "
"LLaMA-Factory neat_packing (contamination-free packing) to remove the "
"end-of-turn junk-token artifact. 13k A1 mix, 2 epochs, lr 1e-4 cosine, "
"cutoff 8192, ChatML/qwen template.\n"
)
api.create_repo(repo, exist_ok=True, private=False)
with open("/workspace/out/a1-neatpack-r64/README.md", "w") as f:
    f.write(card)
api.upload_folder(folder_path="/workspace/out/a1-neatpack-r64", repo_id=repo)
print("pushed", repo)
PY
echo "PUSH-DONE — terminate the pod now (cost hygiene)."
