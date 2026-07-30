#!/bin/bash
# LLaMA-Factory vs TRL benchmark, one 2xA100-80GB pod, sequential (fair
# efficiency comparison + base downloaded once). Trains the A1 LoRA both ways,
# then serves each and measures the end-of-turn junk rate.
#
# NOT set -e: a failing arm must NOT abort the benchmark — "which one has
# fewer bugs" is the question, so a broken arm is a recorded result, not fatal.
# Compiled deps (deepspeed, flash-attn) install with --no-build-isolation AFTER
# torch is in the venv (building them under isolation, with no torch, fails —
# that was the first run's abort).
#
# Pod: gpuCount 2, A100 SXM 80GB, allowedCudaVersions ["13.0"], env PUBLIC_KEY.
# scp in: a1_lora.yaml dataset_info.json train_trl.py ds_z3.yaml measure_junk.py
# mix-a1-clean.jsonl -> /root/. /root/.keys exports HF_TOKEN, WANDB_API_KEY.
set -uo pipefail
source /root/.keys
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1
# The image ships CUDA 12.4 (nvcc); pip's default torch is built for CUDA 13.0,
# which has no matching flash-attn wheel and breaks the source build. Force
# torch onto cu124 to match the image.
export UV_TORCH_BACKEND=cu124
mkdir -p /workspace/data /workspace/out
cp /root/mix-a1-clean.jsonl /root/dataset_info.json /workspace/data/
peak_mem() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -rn | head -1; }

# Install cu124 torch + a PREBUILT flash-attn wheel matched to it (no compile);
# fall back to a source build (which now matches nvcc 12.4) if the wheel 404s.
install_torch_fa() {  # $1 = venv python, $2 = install log
  local P="$1" L="$2"
  uv pip install --python "$P" torch==2.6.0 torchvision >> "$L" 2>&1
  local URL
  URL=$("$P" - <<'PY'
import torch
v='.'.join(torch.__version__.split('+')[0].split('.')[:2])
cu='cu12' if (torch.version.cuda or '12').startswith('12') else 'cu11'
abi='TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE'
print(f"https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+{cu}torch{v}cxx11abi{abi}-cp311-cp311-linux_x86_64.whl")
PY
)
  echo "flash-attn wheel: $URL" >> "$L"
  uv pip install --python "$P" "$URL" >> "$L" 2>&1 \
    || uv pip install --python "$P" flash-attn --no-build-isolation >> "$L" 2>&1
}

pip install -q uv 2>&1 | tail -1
uv venv /opt/dl --python 3.11 -q
uv pip install --python /opt/dl/bin/python -q huggingface_hub hf_transfer 2>&1 | tail -1
/opt/dl/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-32B')"
echo "=== BASE DOWNLOADED ==="

LF_STATUS=skip TRL_STATUS=skip; lf_secs=0 trl_secs=0 lf_mem=0 trl_mem=0

# ---- ARM A: LLaMA-Factory ----
uv venv /opt/lf --python 3.11 -q
install_torch_fa /opt/lf/bin/python /root/lf-install.log
uv pip install --python /opt/lf/bin/python "llamafactory[metrics,liger-kernel]" wandb torch==2.6.0 >> /root/lf-install.log 2>&1
uv pip install --python /opt/lf/bin/python deepspeed --no-build-isolation >> /root/lf-install.log 2>&1
git clone --depth 1 https://github.com/hiyouga/LLaMA-Factory /workspace/LLaMA-Factory >> /root/lf-install.log 2>&1
if /opt/lf/bin/python -c "import llamafactory, deepspeed, flash_attn" 2>>/root/lf-install.log; then
  t0=$(date +%s)
  if PATH=/opt/lf/bin:$PATH FORCE_TORCHRUN=1 NPROC_PER_NODE=2 \
       /opt/lf/bin/llamafactory-cli train /root/a1_lora.yaml > /root/lf.log 2>&1; then
    LF_STATUS=OK; else LF_STATUS=TRAIN_FAIL; fi
  lf_secs=$(( $(date +%s) - t0 )); lf_mem=$(peak_mem)
else
  LF_STATUS=INSTALL_FAIL
fi
echo "=== LF DONE: $LF_STATUS ${lf_secs}s ${lf_mem}MiB ==="

# ---- ARM B: TRL ----
uv venv /opt/trl --python 3.11 -q
install_torch_fa /opt/trl/bin/python /root/trl-install.log
uv pip install --python /opt/trl/bin/python trl peft transformers accelerate datasets wandb torch==2.6.0 >> /root/trl-install.log 2>&1
uv pip install --python /opt/trl/bin/python deepspeed --no-build-isolation >> /root/trl-install.log 2>&1
if /opt/trl/bin/python -c "import trl, deepspeed, flash_attn" 2>>/root/trl-install.log; then
  t0=$(date +%s)
  if PATH=/opt/trl/bin:$PATH /opt/trl/bin/accelerate launch \
       --config_file /root/ds_z3.yaml /root/train_trl.py > /root/trl.log 2>&1; then
    TRL_STATUS=OK; else TRL_STATUS=TRAIN_FAIL; fi
  trl_secs=$(( $(date +%s) - t0 )); trl_mem=$(peak_mem)
else
  TRL_STATUS=INSTALL_FAIL
fi
echo "=== TRL DONE: $TRL_STATUS ${trl_secs}s ${trl_mem}MiB ==="

# ---- eval: serve each successful arm, measure junk ----
uv venv /opt/serve --python 3.11 -q
uv pip install --python /opt/serve/bin/python -q vllm openai 2>&1 | tail -1
serve_and_measure() {  # $1=name $2=adapter_dir
  for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do kill "$pid" 2>/dev/null || true; done
  sleep 8
  CUDA_VISIBLE_DEVICES=0 nohup /opt/serve/bin/vllm serve Qwen/Qwen2.5-32B \
    --enable-lora --lora-modules "$1=$2" --max-lora-rank 64 --max-model-len 8192 \
    --gpu-memory-utilization 0.90 --port 8000 \
    --override-generation-config '{"eos_token_id": [151645, 151643]}' \
    > /root/serve-$1.log 2>&1 &
  for _ in $(seq 1 60); do grep -q "Application startup complete" /root/serve-$1.log 2>/dev/null && break; sleep 10; done
  /opt/serve/bin/python /root/measure_junk.py --model "$1" -n 120 | tee -a /root/junk.txt
}
[ "$LF_STATUS"  = OK ] && serve_and_measure a1-lf  /workspace/out/a1-neatpack-r64
[ "$TRL_STATUS" = OK ] && serve_and_measure a1-trl /workspace/out/a1-trl-r64

echo "======== BENCHMARK SUMMARY ========"
echo "LLaMA-Factory: $LF_STATUS  ${lf_secs}s  peak ${lf_mem} MiB"
echo "TRL:           $TRL_STATUS  ${trl_secs}s  peak ${trl_mem} MiB"
echo "--- junk rates ---"; cat /root/junk.txt 2>/dev/null || echo "(no successful arm to serve)"
echo "adapters (if OK) on HF: SecondLookResearch/Qwen2.5-32B-elicit-A1-{neatpack,trlpack}"
echo "TERMINATE THE POD NOW."
