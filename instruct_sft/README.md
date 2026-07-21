## Runbook

- Ideally, the Runpod pod should be as stateless as possible
- I personally try to achieve this by having the local copy of the repo as a single source of truth
- I make all code changes locally, then I use rsync to copy the repo over through an excluded script at `upload_repo.sh`
- Since introducing FA3, the venv no longer builds locally (or at least without nvcc), so make sure to sync `pyproject.toml` and `uv.lock` back to local after adding deps with uv on the Runpod pod

- As of now, the code is geared to be a minimal setup for training Olmo 3 32B
- The command I use to run `scripts/train_sft.py` is `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True accelerate launch --config_file fsdp32b.yaml scripts/train_sft.py`
  - The pytorch environment variable might not be necessary, but Claude said it would help reduce peak memory usage

> [!WARNING]
> The FSDP config in `fsdp32b.yaml` is specific to Olmo 3. To use it with another model family, be sure to **change `fsdp_transformer_layer_cls_to_wrap`**
