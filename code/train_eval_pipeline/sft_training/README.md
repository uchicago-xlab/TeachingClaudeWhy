# sft_training — own-hardware SFT stack (RunPod)

Trains chat-SFT LoRAs on Qwen2.5-32B **base** on rented RunPod GPUs. Current
payload: the A1 elicitation mix (13k samples, ~9M tokens). The canonical config is
`a1_lora_r64_fix1.yaml` — r64/α128, dropout 0, assistant-only loss, lr 1e-4 cosine
with 3% warmup, 2 epochs, cutoff 8192, effective batch 8, neat_packing, and
**LoRA on `embed_tokens` + `lm_head`**. That last item is load-bearing: Qwen2.5
base ships tied untrained rows for the ChatML special tokens, and a linear-only
LoRA cannot learn to emit `<|im_end|>` — every base-start SFT without it produced
the end-of-turn confetti artifact. Full story:
`notes/Project/Experiments/A1TerminatorContamination.md`.
(`a1_lora_r64.yaml` is that broken linear-only recipe, kept for comparison runs.)

Every finished adapter must pass `check_junk.py` (strict: foreign-script-anywhere,
eos-stop rate, trailing junk — worst metric wins) before it ships. Adapters with
table LoRAs cannot be applied live by vLLM: merge with `merge_and_unload()` first
and serve the merged model, and always pass `stop_token_ids=[151645, 151643]`
per request (the base generation_config can silently defeat server-side overrides).

## Prerequisites (local)

`RUNPOD_API_KEY` in the environment or in the repo-root `.env`; an SSH keypair
(default `~/.ssh/id_ed25519.pub`, override with `PUBKEY_FILE`); a keys file defining
`HF_TOKEN` and `WANDB_API_KEY` (point `KEYS_FILE` at it — the repo `.env` works;
only those two lines are copied to the pod); `code/train_eval_pipeline/mix-a1-clean.jsonl`
present locally.

## Faster cold starts: the prebaked image

The stock RunPod image costs ~25 minutes of dependency installs on every fresh pod
(and again after every stop/start, which wipes the container disk). The `Dockerfile`
here bakes both proven venvs into an image; build and push it once from any machine
with Docker, then pass `IMAGE_NAME=<registry>/<user>/a1-stack:v1` to `create_pod.sh`.
`setup.sh` detects the baked venvs and collapses to data staging plus the model
download, and pod restarts recover the environment for free. Build instructions are
at the top of the Dockerfile.

## Run recipe

```bash
cd code/train_eval_pipeline/sft_training

# 1. Create a pod (waits for SSH; self-terminates if the host never publishes it):
bash create_pod.sh a1 8 --gpu-type h100     # 8-way or wider on 80GB cards — 4-way OOMs

# 2. Push code + data + keys:
KEYS_FILE=~/path/to/.env bash push.sh a1

# 3. On the pod: environment + base weights (ends SETUP-OK or dies loudly):
bash setup.sh lf          # FA2/cu124 lane (default, proven)
# or: bash setup.sh lf-fa3  — CUDA-13/FlashAttention-3 lane. Same configs work
# unchanged (its patched LF reroutes `flash_attn: fa2` to FA3 internally); launch
# training with DISABLE_VERSION_CHECK=1. Verified correct (exact packed-segment
# isolation) but NO speed gain at 8k context — use it for 16k+ documents.

# 4. Smoke test FIRST — same multi-GPU ZeRO-3 path as the real run, ~10 min.
#    Derive a smoke config from the full one (max_samples 256, max_steps 5).
# 5. Full run in nohup/tmux, ~55 min packed on 8xH100.
# 6. Junk-test (merge first), release only if CLEAN, then STOP or TERMINATE the pod
#    and log spend in notes/Project/Planning/spending.json.
```

`watch.sh <pod-name>` monitors by progress deltas, never liveness.

## Hard-won constraints baked into the scripts

Install order in `setup.sh`: cu124-pinned torch first, prebuilt flash-attn wheel,
deepspeed `--no-build-isolation` last, hard import gate. Venvs on `/opt`, never the
network volume. `NCCL_NVLS_ENABLE=0` on containerized H100 pods (NVLS multicast is
broken there — NCCL dies at the first barrier otherwise). The serve venv pins
transformers 4.51.3 for its vLLM. Memory: at 8192-token packs on 80GB cards the
ledger sits ~1GB from OOM at 8-way — never go narrower; full-replica DDP does not
fit at all. The `lf-fa3` arm carries its own version pins and three documented
patches; launch it with `DISABLE_VERSION_CHECK=1`.

## Troubleshooting

SSH refused with the pod "RUNNING" usually means the ~20GB image is still pulling
(5–15+ min; progress only in the console Logs tab). GPU at 0% is normal during
install, download, and vLLM warm-up — diagnose from the log stage. After a container
restart the public SSH port changes; re-query it. Leftover GPU memory after a kill:
`kill -9` the PIDs from `nvidia-smi --query-compute-apps=pid` in rounds and confirm
0 MiB — a process can survive and even go unkillable (ghost driver context); the fix
for that is a pod stop/start. Never `pkill -f` a pattern your own ssh command
contains. Eval traffic from outside the pod goes through an SSH port-forward, never
`*.proxy.runpod.net`. Pods bill from creation including while crash-looping —
terminate promptly; stopped pods still bill ~$2/day for the volume.
