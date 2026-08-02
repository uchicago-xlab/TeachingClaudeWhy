#!/bin/bash
# Pod-side environment setup for one training arm.  Usage:  bash setup.sh lf|trl
#
# Install order is load-bearing — each step reverses a failure that killed a pod:
#   1. torch==2.6.0 pinned to cu124 FIRST (the runpod/pytorch image ships nvcc
#      12.4; pip's default cu13x torch has no matching flash-attn wheel).
#   2. flash-attn as a PREBUILT wheel matched to that torch (no compile);
#      source build only as fallback, and only after torch exists.
#   3. deepspeed with --no-build-isolation AFTER torch (building it in an
#      isolated env with no torch was the first pod's abort).
# Venvs live on /opt (container-local disk) — /workspace is MooseFS and takes
# 20+ minutes for a large install.
set -euo pipefail
ARM="${1:?usage: setup.sh lf|trl|lf-fa3}"
set -a; source /root/.keys; set +a   # HF_TOKEN, WANDB_API_KEY (plain NAME=value lines — set -a exports them)
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1 UV_TORCH_BACKEND=cu124

mkdir -p /workspace/data /workspace/out
cp /root/mix-a1-clean.jsonl /root/dataset_info.json /workspace/data/

# ---------------------------------------------------------------------------
# lf-fa3: CUDA-13 torch + native FlashAttention-3 via the HF kernels hub.
# Fully working and CORRECTNESS-VERIFIED (exact segment isolation, logit diff
# 0.0000 on the packed-equivalence test, 2026-08-02) but measured NO speedup
# over FA2 at 8192-ctx ZeRO-3 (attention is a small share of step time there).
# Keep for long-context work. Launch with DISABLE_VERSION_CHECK=1 in the env.
# ---------------------------------------------------------------------------
if [ "$ARM" = "lf-fa3" ]; then
  pip install -q uv 2>&1 | tail -1
  export UV_TORCH_BACKEND=cu130
  uv venv /opt/fa3 --python 3.11 -q
  P=/opt/fa3/bin/python
  # LF's metadata pins transformers<=5.6.0 (broken with every kernels version
  # it allows) — install sequentially and re-assert the working pins LAST.
  uv pip install --python "$P" -q "torch==2.13.0" numpy setuptools wheel psutil hf_transfer
  uv pip install --python "$P" -q "llamafactory[metrics]==0.9.5" wandb
  uv pip install --python "$P" -q deepspeed --no-build-isolation
  uv pip install --python "$P" -q "transformers==5.14.1" "kernels==0.15.2" "torch==2.13.0"
  # Patch 1: LF has no fa3 option — route its fa2 branch to native FA3 and
  # drop the fa2-availability guard (no FA2 wheel exists for cu130 torch).
  ATT=$("$P" -c "import llamafactory.model.model_utils.attention as a; print(a.__file__)")
  sed -i 's|requested_attn_implementation = "flash_attention_2"|requested_attn_implementation = "flash_attention_3"|' "$ATT"
  sed -i 's|if not (is_flash_attn_2_available() or is_torch_npu_available()):|if False:|' "$ATT"
  # Patch 2: transformers RESOLVES "flash_attention_3" to the kernel repo id
  # below; LF's collator string-matches the implementation to pick the packed
  # path, so it must recognize the resolved name or it silently builds a dense
  # 4D mask (=> ~120GiB allocs in _upad_input).
  C=$("$P" -c "import llamafactory.data.collator as c; print(c.__file__)")
  sed -i 's|if self.block_diag_attn and self.attn_implementation != "flash_attention_2":|if self.block_diag_attn and self.attn_implementation not in ("flash_attention_2", "flash_attention_3", "kernels-community/vllm-flash-attn3"):|' "$C"
  sed -i 's|if self.neat_packing and self.attn_implementation == "flash_attention_2":  # FIXME compatibility fa3/fa4|if self.neat_packing and self.attn_implementation in ("flash_attention_2", "flash_attention_3", "kernels-community/vllm-flash-attn3"):|' "$C"
  # Patch 3: 5.14.1's _get_unpad_data assumes binary masks; make it delegate
  # segment-id masks (LF legacy path) to LF's segment-aware lengths.
  "$P" - <<'PYEOF'
path_mod = __import__("transformers.modeling_flash_attention_utils", fromlist=["x"]).__file__
src = open(path_mod).read()
old = "    seqlens_in_batch = attention_mask.sum(dim=-1, dtype=torch.int32)\n    indices = torch.nonzero(attention_mask.flatten(), as_tuple=False).flatten()"
if "a1_stack" not in src and src.count(old) == 1:
    new = ("    # PATCHED (a1_stack): segment-id masks -> LF segment-aware lengths\n"
           "    if attention_mask.max() > 1:\n"
           "        from llamafactory.model.model_utils.packing import get_seqlens_in_batch\n"
           "        seqlens_in_batch = get_seqlens_in_batch(attention_mask)\n"
           "    else:\n"
           "        seqlens_in_batch = attention_mask.sum(dim=-1, dtype=torch.int32)\n"
           "    indices = torch.nonzero(attention_mask.flatten(), as_tuple=False).flatten()")
    open(path_mod, "w").write(src.replace(old, new))
    print("unpad patch applied")
else:
    print("unpad patch already present or anchor moved")
PYEOF
  "$P" -c "import torch, transformers, kernels, llamafactory, deepspeed; print('FA3-ENV-OK torch', torch.__version__, 'tf', transformers.__version__)"
  "$P" -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-32B')"
  uv pip freeze --python "$P" > /root/freeze-lf-fa3.txt
  echo "SETUP-OK"
  exit 0
fi

# Prebaked-image fast path (see Dockerfile): when the pod runs the a1-stack
# image, both venvs are already baked and importable — jump straight to data
# staging and the model download (~10 min cold start instead of ~35).
if [ -x /opt/v/bin/python ] && /opt/v/bin/python -c "import torch, flash_attn, deepspeed, llamafactory" 2>/dev/null \
   && [ -x /opt/serve/bin/python ] && /opt/serve/bin/python -c "import vllm, peft" 2>/dev/null; then
  echo "BAKED-IMAGE detected — skipping installs"
  /opt/v/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-32B')"
  /opt/v/bin/python -m pip freeze > "/root/freeze-$ARM.txt" 2>/dev/null || true
  echo "SETUP-OK"
  exit 0
fi

pip install -q uv 2>&1 | tail -1
uv venv /opt/v --python 3.11 -q
P=/opt/v/bin/python

uv pip install --python "$P" -q torch==2.6.0 setuptools wheel psutil hf_transfer huggingface_hub

# Prebuilt FA2 wheel matched to the installed torch's minor version and ABI.
FA_URL=$("$P" - <<'PY'
import torch
v = '.'.join(torch.__version__.split('+')[0].split('.')[:2])
abi = 'TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE'
print(f"https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/"
      f"flash_attn-2.7.4.post1+cu12torch{v}cxx11abi{abi}-cp311-cp311-linux_x86_64.whl")
PY
)
echo "flash-attn wheel: $FA_URL"
uv pip install --python "$P" -q "$FA_URL" \
  || uv pip install --python "$P" -q flash-attn==2.7.4.post1 --no-build-isolation

# Arm deps. torch stays pinned in the same resolve so nothing upgrades it.
if [ "$ARM" = lf ]; then
  uv pip install --python "$P" -q "llamafactory[metrics]" wandb torch==2.6.0
else
  # transformers pinned to 5.6.0: on 5.14.1 flash-attention silently fails to
  # engage for the TRL path and attention runs in the eager fallback, whose
  # 8192-token score matrices OOM any topology (~60GB activations/rank).
  # 5.6.0 is the version the working LF arm uses. The s_aux guard patch below
  # must be applied AFTER this pin (re-pinning replaces the patched file).
  uv pip install --python "$P" -q trl peft "transformers==5.6.0" accelerate datasets wandb torch==2.6.0
fi
uv pip install --python "$P" -q deepspeed --no-build-isolation

# Guard-patch for the transformers FA2 s_aux crash (upstream forgot a None
# check; hit us on transformers 5.14.1). Idempotent: no-op if already fixed.
TFA=$("$P" -c "import transformers,os; print(os.path.dirname(transformers.__file__))")/integrations/flash_attention.py
if grep -q 's_aux=s_aux\.to(query\.dtype)' "$TFA" 2>/dev/null; then
  sed -i 's/s_aux=s_aux\.to(query\.dtype)/s_aux=(s_aux.to(query.dtype) if s_aux is not None else None)/' "$TFA"
  echo "s_aux patch: APPLIED"
else
  echo "s_aux patch: not needed"
fi

# Hard gate: every training import must load before we call setup done.
if [ "$ARM" = lf ]; then
  "$P" -c "import torch, flash_attn, deepspeed, llamafactory"
else
  "$P" -c "import torch, flash_attn, deepspeed, trl, peft"
fi
echo "IMPORTS-OK"

# Serving env for the junk acceptance test — separate venv: vLLM's torch pin
# must never touch the training env. Pin transformers to the 4.x API this
# vLLM was built against: under the cu124 torch constraint uv resolves
# vllm 0.8.5, which crashes on transformers 5.x at tokenizer init
# (all_special_tokens_extended was removed).
uv venv /opt/serve --python 3.11 -q
uv pip install --python /opt/serve/bin/python -q vllm openai "transformers==4.51.3" setuptools peft 2>&1 | tail -1  # peft: adapter merges run in this venv

# Base weights onto the persistent volume (~65GB, ~10 min with hf_transfer).
"$P" -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-32B')"

uv pip freeze --python "$P" > "/root/freeze-$ARM.txt"
echo "SETUP-OK"
