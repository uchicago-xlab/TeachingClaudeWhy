# Team quickstart: the prebaked training image

- **What it is:** a public Docker image (`ghcr.io/anastasiakwei/sft-training:v1`)
  with the full 32B SFT training environment preinstalled (torch/cu124,
  LLaMA-Factory, flash-attn, DeepSpeed, plus the vLLM serving venv). It cuts pod
  setup from ~25 minutes to ~2 minutes.
- **Prerequisite:** this repo checked out. You need `RUNPOD_API_KEY` (env or repo
  `.env`) and a keys file with `HF_TOKEN` + `WANDB_API_KEY`.
- **Create a pod with the image:**
  ```bash
  cd code/train_eval_pipeline/sft_training
  IMAGE_NAME=ghcr.io/anastasiakwei/sft-training:v1 bash create_pod.sh <name> 8 --gpu-type h100
  ```
- **Then as usual:** `push.sh <name>` → on the pod `bash setup.sh lf` (it prints
  `BAKED-IMAGE detected` and only downloads the base model) → smoke test → full
  run. Full recipe: [README.md](README.md).
- **Rules that still apply:** 8 GPUs or more on 80GB cards (4-way runs out of
  memory); smoke test before every full run; junk-test adapters with
  `check_junk.py` before releasing them; terminate pods promptly and log spend.
- **Do not use the image for:** the FA3/CUDA-13 lane (`setup.sh lf-fa3` builds
  that separately) or non-training pods.
- **If dependencies must change:** edit the `Dockerfile`, then
  `docker build -t ghcr.io/<you>/sft-training:v2 . && docker push ...` from any
  machine with Docker, and pass the new tag as `IMAGE_NAME`. Needs a GitHub token
  with `write:packages` and the package set to public.
- **No credentials are needed to pull** — the image is public. Never bake keys
  into it.
