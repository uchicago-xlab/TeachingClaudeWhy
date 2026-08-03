#!/bin/bash
# Stack A: 2xA100-SXM, TRL + patched FA2, DeepSpeed ZeRO-3. Trains the A1 LoRA
# with packing on and off; reports PURE train() wall-clock + $ cost (install and
# debugging excluded — only the timed train() blocks count).
#
# scp in: train_trl.py ds_z3.yaml measure_junk.py mix-a1-clean.jsonl -> /root/.
# /root/.keys exports HF_TOKEN, WANDB_API_KEY.
set -uo pipefail
source /root/.keys
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1 UV_TORCH_BACKEND=cu124
export TOKENIZERS_PARALLELISM=false   # avoid the fork deadlock during .map tokenization
RATE=2.98   # $/hr for the 2xA100-SXM pair; used for the clean cost figure
mkdir -p /workspace/data /workspace/out
cp /root/mix-a1-clean.jsonl /workspace/data/
peak_mem() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | sort -rn | head -1; }
cost() { python3 -c "print('\$%.2f' % ($1*$RATE/3600))"; }

pip install -q uv 2>&1 | tail -1
uv venv /opt/v --python 3.11 -q
# cu124 torch + prebuilt FA2 wheel (matches nvcc 12.4), then the rest pinned
uv pip install --python /opt/v/bin/python torch==2.6.0 torchvision setuptools wheel >/root/install.log 2>&1
URL=$(/opt/v/bin/python - <<'PY'
import torch
v='.'.join(torch.__version__.split('+')[0].split('.')[:2])
abi='TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE'
print(f"https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch{v}cxx11abi{abi}-cp311-cp311-linux_x86_64.whl")
PY
)
uv pip install --python /opt/v/bin/python "$URL" >>/root/install.log 2>&1 \
  || uv pip install --python /opt/v/bin/python flash-attn --no-build-isolation >>/root/install.log 2>&1
uv pip install --python /opt/v/bin/python "transformers==5.14.1" trl peft accelerate datasets deepspeed wandb >>/root/install.log 2>&1

# --- patch the transformers 5.14.1 FA2 s_aux bug (None guard upstream forgot) ---
TFA=$(/opt/v/bin/python -c "import transformers,os;print(os.path.dirname(transformers.__file__))")/integrations/flash_attention.py
sed -i 's/s_aux=s_aux\.to(query\.dtype)/s_aux=(s_aux.to(query.dtype) if s_aux is not None else None)/' "$TFA"
grep -q "s_aux is not None" "$TFA" && echo "PATCH-OK" || echo "PATCH-FAIL"

/opt/v/bin/python -c "import trl,deepspeed,flash_attn,peft" 2>>/root/install.log && echo "IMPORTS-OK" || echo "IMPORTS-FAIL"
/opt/v/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-32B')"
echo "=== BASE DOWNLOADED ==="

run_arm() {  # $1=name $2=packing-flag($3=out)
  local name="$1" flag="$2" out="/workspace/out/$1"
  local t0=$(date +%s) st=OK
  PATH=/opt/v/bin:$PATH PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    /opt/v/bin/torchrun --nproc_per_node 2 \
    /root/train_trl.py $flag --attn flash_attention_2 --deepspeed /root/ds_z3_lf.json \
    --out "$out" > "/root/$name.log" 2>&1 || st=FAIL
  local secs=$(( $(date +%s) - t0 ))
  echo "$name $st $secs $(peak_mem)" >> /root/arm-results.txt
  echo "=== $name: $st ${secs}s ==="
}
run_arm a100-pack   "--packing"
run_arm a100-nopack ""

# --- serve + junk-measure each successful arm ---
uv venv /opt/serve --python 3.11 -q
uv pip install --python /opt/serve/bin/python -q vllm openai 2>&1 | tail -1
serve_measure() {  # $1=name
  grep -q "^$1 OK" /root/arm-results.txt || return 0
  for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do kill "$pid" 2>/dev/null || true; done
  sleep 8
  CUDA_VISIBLE_DEVICES=0 nohup /opt/serve/bin/vllm serve Qwen/Qwen2.5-32B --enable-lora \
    --lora-modules "$1=/workspace/out/$1" --max-lora-rank 64 --max-model-len 8192 \
    --gpu-memory-utilization 0.90 --port 8000 \
    --override-generation-config '{"eos_token_id": [151645, 151643]}' > "/root/serve-$1.log" 2>&1 &
  for _ in $(seq 1 60); do grep -q "Application startup complete" "/root/serve-$1.log" 2>/dev/null && break; sleep 10; done
  /opt/serve/bin/python /root/measure_junk.py --model "$1" -n 120 | tee -a /root/junk.txt
}
serve_measure a100-pack
serve_measure a100-nopack

echo "======== STACK A (A100 + patched FA2) SUMMARY ========"
while read name st secs mem; do
  echo "$name: $st  train ${secs}s  cost $(cost $secs)  peak ${mem}MiB"
done < /root/arm-results.txt
echo "--- junk rates ---"; cat /root/junk.txt 2>/dev/null || echo "(none)"
echo "TERMINATE THE POD NOW."
