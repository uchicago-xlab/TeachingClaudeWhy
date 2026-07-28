# Serving checkpoints on RunPod with vLLM

Together's dedicated-endpoint API is dead for us (v1 deprecated, no v2 capacity),
and Together's serverless tier refuses both `Qwen/Qwen3-14B` and our finetuned
checkpoints — `Unable to access non-serverless model`. So self-hosting on vLLM is
the eval-serving path, as recorded in `notes/Anastasia/Progress Log.md`.

The Elicit10kEval writeup points at "the Runpod recipe in memory" for the serve
command. That recipe was never written down — not in the repo, not in git
history. This directory is it.

**Our org does not issue RunPod API keys.** Pods are created, watched, and
terminated by hand in the console. Nothing here provisions anything; the scripts
cover the pod-side server and the client-side eval run.

## Files

| file | runs on | what it does |
| --- | --- | --- |
| `serve_vllm.sh` | the pod | Downloads the LoRA adapter(s) and starts vLLM serving base + each adapter as its own model id |
| `check_endpoint.py` | your laptop | Preflight: model ids registered, thinking actually off, adapter actually applied |
| `eval_on_pod.py` | your laptop | Preflights, then runs `run_eval.py` for both arms with matched flags |
| `mock_vllm.py` | your laptop | Fake vLLM server for testing the client side with no GPU (see below) |

## Why one pod covers every arm

vLLM serves a LoRA adapter as its own entry in `/v1/models` alongside the base
weights. One 14B model in memory, several model ids, and a request picks an arm
by naming one:

```
Qwen/Qwen3-14B            -> base (the baseline)
qwen3-14b-da-sonnet5-v1   -> base + difficult-advice adapter (sonnet5 teacher)
qwen3-14b-da-nano-v2      -> base + nano-teacher adapter
qwen3-14b-da-haiku45-v1   -> base + haiku-4.5-teacher adapter
```

> The sonnet5 arm was originally served as `qwen3-14b-da-sdf-v1`, before there
> was a second teacher to distinguish it from. The logs under
> `logs/…-da-sonnet5-v1-as-Qwen/` still carry that old id in their `model`
> field — the id the pod really served — so `summarize.py` labels those rows
> `qwen3-14b-da-sdf-v1` even though everything else now says sonnet5. Re-serving
> with today's default produces the new id, which `eval_set` treats as a
> different model: point such a run at a fresh `--run-name` rather than
> appending it to the historical directory.

That cuts the GPU bill and removes a confound: every arm hits the same weights,
same kernels, same sampler. Set `ADAPTER_SPECS` to space-separated `name=source`
pairs to serve more than one at a time (`source` is a pod directory or a HF repo
id); leave it unset and the single-adapter defaults apply unchanged.

## GPU choice

Qwen3-14B in bf16 is ~29.5 GB of weights, so 48 GB is comfortable.

| GPU | Community $/hr | notes |
| --- | --- | --- |
| **A40 48GB** | **$0.35** | Recommended. Fits with ~13 GB left for KV cache. Ampere, so unhurried, but the eval is only a few hundred requests. |
| L40S 48GB | $0.79 | Ada; noticeably faster decode for ~2× the price. |
| A100 80GB PCIe | $1.19 | What the Elicit10k run used — for a 32B. Headroom we don't need at 14B. |

**Use a single GPU.** Two PCIe cards trip a vLLM custom-all-reduce deadlock this
team has already paid for once — "spins at 100% GPU generating nothing", 2.3h and
$6.50 (spending log, 2026-07-15). If you ever do need 2×, the recorded fix is
`--disable-custom-all-reduce` plus `NCCL_P2P_DISABLE=1`.

Disk: **80 GB** container/volume. Weights are ~30 GB and the HF cache keeps a copy.

### Making a run faster

Reach for `--max-connections` before reaching for a bigger GPU. Qwen3-14B spends
160 KiB of KV cache per token (40 layers × 8 KV heads × 128 dim × 2 for K+V × 2
bytes), and a typical eval request is ~3.2k tokens (2.4k prompt + ~800
generated), so ~0.5 GiB per in-flight request. An A40 at
`--gpu-memory-utilization 0.90` has ~13 GiB left after weights — room for **~25
concurrent requests**, and the default is 8. Tripling it costs nothing and does
more for wall-clock than upgrading the card.

Two things that do not shrink with a faster GPU: the ~30 GB weight download on
first boot, and the grader. Together they floor a `core --epochs 10` run at
around 15–20 minutes no matter what silicon is underneath.

Note that `--max-connections` also raises grader concurrency — Inspect scopes its
semaphore per endpoint, so the pod and OpenRouter each get the full limit rather
than sharing it. If OpenRouter starts 429ing, that is why.

An 80 GB card (A100/H100) earns its price when the KV pool is the binding
constraint — `--preset full`, `--epochs 30+`, or `--max-connections` past ~25.
Below that it buys ~15 minutes for double the hourly rate.

Expected cost for `--preset core --epochs 10` (10 conditions × 10 epochs × 2 arms
= 200 samples): roughly 1–1.5 h on an A40 including model download, so **under
$1 of GPU**. As always the grader is the expensive half — budget $3–5 of Sonnet
via OpenRouter, matching what Elicit10k actually cost.

## Bringing a pod up

1. **Deploy** a pod in the console with the GPU above and image
   `vllm/vllm-openai:latest`. Confirm the tag ships vLLM ≥ 0.9.0 — Qwen3's
   `enable_thinking` handling was only settled in 0.9.0.
2. Set **Container Start Command** to `sleep infinity`. The image's default
   entrypoint launches its own API server immediately; overriding it lets you
   drive the pod from the web terminal instead of fighting that.
3. Set **Expose HTTP Ports** to `8000`. RunPod then proxies it at
   `https://<POD_ID>-8000.proxy.runpod.net` — no SSH tunnel needed, unlike the
   older story-gen pod recipe.
4. Add environment variables `HF_TOKEN` (the adapter repo is private) and
   `VLLM_API_KEY` (any long random string — **that proxy URL is reachable by
   anyone who knows it**).
5. Open the web terminal, paste `serve_vllm.sh` into a file, `chmod +x`, run it.

Wait for `Application startup complete`. First boot spends ~10 min pulling
weights.

### If you are handed an SSH pod instead

Not every pod arrives as the vLLM image with an HTTP port. A bare CUDA/PyTorch
pod reached over SSH works just as well, and keeps the endpoint off the public
internet — this is how the nano-v2 / haiku45-v1 run (2026-07-28) was served:

```bash
# on the pod: vLLM is not in a bare image, but pip has it (~5 min, pulls its own torch)
pip install --break-system-packages -U vllm        # Ubuntu 24.04 is PEP-668 managed

# ship the adapters up rather than putting an org HF token on rented hardware
rsync -a -e "ssh -p <PORT> -i ~/.ssh/id_ed25519" <adapter-dirs>/ root@<HOST>:/workspace/adapters/

# on the pod: bind to loopback, since the tunnel is the only way in
ADAPTER_SPECS="name-a=/workspace/adapters/name-a name-b=/workspace/adapters/name-b" \
    HOST=127.0.0.1 VLLM_API_KEY=... HF_HOME=/workspace/hf nohup ./serve_vllm.sh &> vllm_serve.log &

# on your laptop: forward 8000 and point VLLM_BASE_URL at localhost
ssh -N -L 8000:127.0.0.1:8000 -o ExitOnForwardFailure=yes root@<HOST> -p <PORT>
export VLLM_BASE_URL=http://127.0.0.1:8000/v1
```

Keep `HF_HOME=/workspace/hf`: the container overlay is typically ~50 GB and the
weights are ~30 GB of it.

> If the console shows the pod **RUNNING but no ports appear**, it is
> crash-looping on container start — a RunPod host problem seen twice before.
> Only the **Logs** tab reveals it. Terminate and redeploy on a different host
> rather than debugging it.

## Running the eval

From `code/serving/` on your laptop:

```bash
export VLLM_BASE_URL=https://<POD_ID>-8000.proxy.runpod.net/v1
export VLLM_API_KEY=<the same string you set on the pod>

# Seconds, no grader cost. Do not skip.
../../.venv-inspect/bin/python check_endpoint.py

# Both arms, preflighted, matched flags
../../.venv-inspect/bin/python eval_on_pod.py --preset core --epochs 10

# Sanity-check the grid first
../../.venv-inspect/bin/python eval_on_pod.py --preset core --epochs 10 --dry-run

# Persona-attachment sweep: same pod, two prompt personas
../../.venv-inspect/bin/python eval_on_pod.py --preset core --model-name Qwen
../../.venv-inspect/bin/python eval_on_pod.py --preset core --model-name Claude
```

Anything after `--` goes straight to `run_eval.py`:

```bash
../../.venv-inspect/bin/python eval_on_pod.py --preset exfil -- --goal-value safety
```

Then the usual table:

```bash
../../.venv-inspect/bin/python ../misalignment_eval/summarize.py \
    --log-dir ../../data/misalignment-eval/logs
```

Rows are labelled by `log.eval.model`, so the two arms appear as
`openai-api/vllm/Qwen/Qwen3-14B` and `openai-api/vllm/qwen3-14b-da-sonnet5-v1`.

For a deeper look at whether a checkpoint is coherent at all — separate question
from misalignment — `code/train_eval_pipeline/probe_model.py` already runs a
12-prompt battery against any OpenAI-compatible endpoint. Point it at the pod
with `--base-url`; note it reads the key from `TOGETHER_API_KEY`, so set that to
the vLLM key.

## Tearing the pod down

**Terminate it in the console the moment the run finishes.** Stopping is not
terminating — a stopped pod still bills for its volume.

This is not hypothetical hygiene. The spending log carries a **$150 "RunPod —
accidental leftover pod burn"** (2026-07-13) with no post-mortem, plus a pod that
"sat EXITED on a 300GB volume until terminated". `eval_on_pod.py` prints the
reminder when it exits, including on failure.

Log the GPU hours in `notes/Project/Planning/spending.json` per repo convention.

## Decision log

- **`openai-api/vllm/<model>` rather than `openai/<model> --model-base-url`.**
  The Elicit10k run used the latter, but Inspect's `openai/` provider reads
  `OPENAI_API_KEY` — so a real OpenAI key sitting in `.env` silently becomes the
  credential sent to the pod, and the pod's key has nowhere to live. The
  `openai-api/<service>/...` form resolves `VLLM_API_KEY` and `VLLM_BASE_URL`
  from the service prefix and keeps the two separate. Same underlying
  `OpenAICompatibleAPI` class either way, so `extra_body` still carries the
  thinking switch.
- **No `--reasoning-parser`.** Tempting for a Qwen3 server, wrong here. We always
  send `enable_thinking=false`, so the model emits no `<think>` block and there
  is nothing to parse — but an enabled parser can route the answer into
  `reasoning_content` and leave `content` empty. Inspect reads `content`, and an
  empty completion grades as non-harmful, so that failure would quietly deflate
  the harmful rate instead of erroring. `check_endpoint.py` asserts against it.
- **`--max-lora-rank` read from `adapter_config.json`, not hardcoded.** It is 64
  today. A future checkpoint at a different rank would otherwise fail with a
  rank error far from its cause.
- **Both arms forced to `--no-thinking`.** The adapter was trained with thinking
  off; an unmatched baseline invalidates the comparison. `eval_on_pod.py`
  deliberately exposes no way to run the arms differently.
- **Arms run sequentially.** The server holds one LoRA slot (`--max-loras 1`),
  so interleaving would thrash adapter swaps for no wall-clock gain.
- **Preflight is a hard gate.** A LoRA that silently fails to load produces a
  perfectly clean run whose result is "the finetune changed nothing" — the exact
  conclusion we are trying to measure. `check_endpoint.py` sends one prompt to
  each arm and fails if the outputs are byte-identical.
- **Adapters are a list, not a singleton (`ADAPTER_SPECS`).** Comparing several
  teachers against one base means N arms, and re-deploying a pod per adapter
  would both cost more and reintroduce the confound one pod was meant to remove
  (different host, different kernels). `--max-loras` is set to the number of
  adapters served, and `--max-lora-rank` to the max `r` across them. The
  single-adapter env vars still work untouched, so the older documented
  invocation is unchanged.
- **`CUDA_VISIBLE_DEVICES` defaults to `0` in the script.** The "use a single
  GPU" rule above was prose the script did not enforce, and multi-GPU pods do
  get handed to us (the 2026-07-28 run was on a 2×A40 box). vLLM would otherwise
  see two cards; pinning in the script makes the safe path the default one.
- **`--max-model-len 16384`.** The Elicit10k pod ran at 8192 and had to cap
  `max_tokens` at 4096 to fit; at 16k the eval's own 4096 default fits with room
  for the longer exfiltration templates, so no eval-side cap is needed.

## Testing without a GPU

`mock_vllm.py` is a zero-dependency stand-in for the pod: it answers
`/v1/models` and `/v1/chat/completions`, and its `MODE` variable simulates each
way the real thing goes wrong.

```bash
MODE=identical PORT=8111 ../../.venv-inspect/bin/python mock_vllm.py &
../../.venv-inspect/bin/python check_endpoint.py --base-url http://127.0.0.1:8111/v1 --api-key k
```

Modes: `ok`, `identical` (LoRA not applied), `think_leak` (thinking switch
ignored), `reasoning` (parser stole the content), `no_adapter` (server started
without `--enable-lora`). `GET /v1/_received` dumps the request bodies the server
saw, which is how the thinking switch was confirmed to reach the wire.

## What is and is not verified

**Verified** against the mock and the installed Inspect source:

- `openai-api/vllm/Qwen/Qwen3-14B` resolves to service `vllm`, sends model id
  `Qwen/Qwen3-14B`, and picks up `VLLM_BASE_URL` / `VLLM_API_KEY`. Same for the
  adapter id.
- A generate through that provider puts
  `"chat_template_kwargs": {"enable_thinking": false}` in the request body.
- `check_endpoint.py` returns non-zero on all five failure modes above and zero
  on a healthy server.
- `eval_on_pod.py --dry-run` builds both arms' commands and grids correctly.
- `serve_vllm.sh` parses, its env guards fire, and the rank probe reads `64` from
  the real adapter config.

**Not verified:** no pod has been up. The vLLM flags and the RunPod proxy format
come from current upstream docs, not from a run of our own, and no real Qwen3
weights have been loaded. Expect to shake something out on first boot — budget
for it before assuming the GPU hour is all eval.
