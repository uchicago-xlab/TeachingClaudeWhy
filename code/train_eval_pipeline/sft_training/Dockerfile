# Prebaked training image for the sft_training: kills the ~25-minute per-pod
# dependency install (the largest fixed cost of every run — see
# notes/Project/Experiments/TogetherTrainingSpeed.md).
#
# Bakes the two proven environments on the image's local disk:
#   /opt/v      training (FA2/cu124 lane: torch 2.6.0, LF 0.9.5, transformers
#               5.6.0, deepspeed, prebuilt flash-attn 2.7.4.post1)
#   /opt/serve  junk-test serving (vllm 0.8.5-era + transformers 4.51.3 + peft)
# The FA3/cu130 lane is NOT baked (no speed gain at 8192 ctx; build it on
# demand with `setup.sh lf-fa3`).
#
# Build + push (any amd64 machine with Docker, ~30 min, image ~25GB):
#   docker build -t <registry>/<user>/a1-stack:v1 code/train_eval_pipeline/sft_training
#   docker push <registry>/<user>/a1-stack:v1
# Then create pods with:
#   IMAGE_NAME=<registry>/<user>/a1-stack:v1 bash create_pod.sh a1-lf 8 --gpu-type h100
# setup.sh detects the baked venvs and skips straight to data staging + model
# download (~10 min total cold start instead of ~35). A pod stop/start also
# restores the venvs for free, since they live in the image.

FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV HF_HUB_ENABLE_HF_TRANSFER=1 \
    UV_TORCH_BACKEND=cu124 \
    PIP_NO_CACHE_DIR=1

# Training env. Order is load-bearing (see setup.sh): torch first, prebuilt
# flash-attn wheel matched to it, deepspeed without build isolation last.
RUN pip install -q uv && \
    uv venv /opt/v --python 3.11 && \
    uv pip install --python /opt/v/bin/python torch==2.6.0 setuptools wheel psutil hf_transfer huggingface_hub && \
    FA_URL=$(/opt/v/bin/python -c "import torch; v='.'.join(torch.__version__.split('+')[0].split('.')[:2]); abi='TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE'; print(f'https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch{v}cxx11abi{abi}-cp311-cp311-linux_x86_64.whl')") && \
    uv pip install --python /opt/v/bin/python "$FA_URL" && \
    uv pip install --python /opt/v/bin/python "llamafactory[metrics]==0.9.5" "transformers==5.6.0" wandb torch==2.6.0 && \
    uv pip install --python /opt/v/bin/python deepspeed --no-build-isolation

# Serving env (separate: vLLM's torch pin must never touch the training env).
RUN uv venv /opt/serve --python 3.11 && \
    uv pip install --python /opt/serve/bin/python vllm openai "transformers==4.51.3" setuptools peft

# Import gate at build time — a broken image fails the build, not a $24/h pod.
RUN /opt/v/bin/python -c "import torch, flash_attn, deepspeed, llamafactory" && \
    /opt/serve/bin/python -c "import vllm, openai, peft"
