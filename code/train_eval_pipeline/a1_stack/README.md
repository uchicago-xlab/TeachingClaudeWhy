# A1 elicitation LoRA — RunPod training stack

Trains the A1 elicitation SFT on Qwen2.5-32B **base**: LoRA r=64, α=128, dropout 0,
assistant-only loss, lr 1e-4 cosine + 3% warmup, 2 epochs over the 13k-sample A1 mix
(~9M tokens), cutoff 8192, effective batch 8, **contamination-free packing**. Written
from scratch after the July benchmark pods died on install-order bugs; nothing here
depends on the old `runpod/` scripts.

Two independent arms run in parallel on separate pods, which is both insurance
against a single-stack bug and the LF-vs-TRL packing benchmark itself:

- **lf** (primary): LLaMA-Factory + `neat_packing` + DeepSpeed ZeRO-3, 8×H100-80GB SXM
  (training ~30 min; accumulation auto-drops to 1 so effective batch stays 8).
- **trl** (insurance/benchmark): TRL `packing_strategy="bfd"` + ZeRO-3, 2×A100-80GB SXM.

Naive packing is never used anywhere: it is the leading cause of the end-of-turn
junk-token artifact (~66–81% on every Together-trained SFT), and every finished
adapter must pass `check_junk.py` (≤5% junk) before it is pushed to HF.

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
cd code/train_eval_pipeline/a1_stack

# 1. Create both pods (parallel; each waits for SSH, ~5-20 min):
bash create_pod.sh a1-lf 8 --gpu-type h100 &
bash create_pod.sh a1-trl 2 &
wait
# On "SSH never published" the script terminates the pod itself; recreate once,
# then switch pool/region, then stop (platform-side).

# 2. Push code + data + keys to each pod:
KEYS_FILE=~/.secondlook.keys bash push.sh a1-lf
KEYS_FILE=~/.secondlook.keys bash push.sh a1-trl

# 3. On each pod (ssh line printed by create_pod.sh): environment + base weights
#    (~25 min; ends with SETUP-OK or dies loudly):
bash setup.sh lf     # on the lf pod
bash setup.sh trl    # on the trl pod

# 4. Smoke test FIRST — same multi-GPU ZeRO-3 path as the real run, 256 samples,
#    5 steps (~10 min). Never start the full run before this passes:
bash train.sh lf smoke     # / trl smoke

# 5. Full run (in tmux or nohup so the ssh session isn't load-bearing):
bash train.sh lf           # ~30min on 8xH100; trl ~4.5h on 2xA100

# 6. From the laptop, check progress by deltas (not liveness):
bash watch.sh a1-lf

# 7. Acceptance test on each finished pod, then push only clean adapters:
/opt/serve/bin/python /root/check_junk.py --adapter /workspace/out/a1-lf --name a1-lf
bash train.sh push lf

# 8. TERMINATE BOTH PODS, then log actual spend in notes/Project/Planning/spending.json.
```

## Why the setup is shaped this way

Install order in `setup.sh` is load-bearing: torch==2.6.0 pinned to **cu124** goes in
first (the image ships nvcc 12.4; pip's default cu13x torch has no matching flash-attn
wheel — that mismatch killed benchmark pod 2), flash-attn comes as a prebuilt wheel
matched to that torch, and deepspeed installs `--no-build-isolation` after torch exists
(building it isolated killed pod 1). Venvs live on `/opt` because `/workspace` is a
network filesystem where large installs take 20+ minutes. vLLM gets its own venv so its
torch requirement can never move the training pin. `pip freeze` is saved to
`/root/freeze-<arm>.txt` for reproducibility.

Both smoke and full runs go through the identical torchrun + ZeRO-3 launch;
accumulation is computed as 8 / n_gpus so the effective batch stays 8 on any topology.
Checkpoints save every 100 steps (adapter-only), so a crash costs at most ~35 minutes,
and `train.sh` resolves the topology-dependent bits into `/root/run-lf.yaml` rather
than trusting CLI-override behavior.

## Troubleshooting

SSH refused with the pod "RUNNING" usually means the ~20GB image is still pulling
(5–15+ min; progress only visible in the console Logs tab). GPU at 0% is normal during
install, model download, and vLLM warm-up — diagnose from the log stage, never from GPU
load alone. If a container restarts, the public SSH port changes; re-query it (the
GraphQL query in `create_pod.sh`) rather than reusing `.pods/<name>.env`. Leftover GPU
memory after killing a run means orphaned workers: kill the PIDs from
`nvidia-smi --query-compute-apps=pid` (never `pkill -f` a pattern — it has matched the
ssh session itself) and confirm 0 MiB before relaunching. Any eval traffic from outside
the pod goes through an SSH port-forward, never `*.proxy.runpod.net` (the proxy's
duration cap silently kills long generations and the client retries forever).

Cost hygiene: pods bill from creation, including while crash-looping — terminate
promptly, never pause overnight (stopped pods still bill volume storage). Expected
spend for the full two-arm run ≈ $45 (8×H100 primary + 2×A100 TRL arm).
