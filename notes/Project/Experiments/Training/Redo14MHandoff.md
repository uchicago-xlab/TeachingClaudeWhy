# Handoff: retrain the 14M embodiment + recitation arms on the graft0 platform

Written 2026-08-17; executed 2026-08-18 (both arms trained, published and
evaluated) and updated afterwards so the commands match what actually ran.
Read this file first, then
`notes/Project/AdapterCatalog.md` (what every published adapter is — the HF
model cards are empty boilerplate and will mislead you),
`code/train_eval_pipeline/sft_training/fsdp_fa3/README.md` (lane details) and
`code/msm_eval/README.md` (eval settings that must never change).

**Warning about the older handoff.** `FSDPFA3Handoff.md` in this directory is
from 2026-08-06 and is now wrong in two ways that will cost you real money if
you follow it: its "Fix candidates" section presents a question that is already
settled (graft0 won), and its eval recipe points at `code/misalignment_eval`
with `run_eval.py`, which is the WRONG harness. Numbers from it are not
comparable to anything in the results table. Use `code/msm_eval` only. Treat
that file as history, not instructions.

## Goal

Two arms — **embodiment 14M** and **recitation 14M** — retrained end to end on
the current platform, then evaluated at higher sample counts than the originals.

## Why retrain rather than re-evaluate

The published `sdf-emb-14M-a1` and `sdf-rec-14M-a1` sit on the **stock**
Qwen2.5-32B base, whose `<|im_end|>` row was never trained, so the model cannot
reliably end a turn on its own; their evals relied on the harness-side
`--stop-token-ids` workaround. Every arm measured since 2026-08-10 instead uses
**graft0** — a bit-exact copy of `<|endoftext|>`'s rows onto `<|im_end|>`
applied to the base *before* training, then linear-only LoRA. That is the
reason these arms are not comparable to the current baseline.

(Checked 2026-08-17: both are r64 **linear-only**, not table-LoRA. An earlier
version of this handoff said table-LoRA, which was wrong — that applies to
`sdf-named-claude-14M-a1` and the ladder arms, not to these. See
`notes/Project/AdapterCatalog.md`.)

Neither old repo published a stage-1 SDF adapter — the line published a single
combined adapter instead — so stage 1 was re-run from the corpus. The retrain
published BOTH stages: `Qwen2.5-32B-sdf-{emb,rec}-14M-v2` (stage 1) and
`Qwen2.5-32B-sdf-{emb,rec}-14M-graft0-a1` (stage 2, with the row patch).

## Inputs that already exist (verified 2026-08-17)

- Corpora, on disk, not in git:
  - `data/fictional-stories/corpus/sdf_train/sdf-embodiment-14M.jsonl` (66 MB)
  - `data/fictional-stories/corpus/sdf_train/sdf-recitation-14M.jsonl` (67 MB)
- Chat-SFT data for stage 2: `code/train_eval_pipeline/mix-a1-clean.jsonl`
  (13,000 rows) — the same A1 mix every arm uses.
- Comparison baseline: `SecondLookResearch/Qwen2.5-32B-graft0-a1`. The adapter
  exists and needed no retraining; per decision 3 it was **re-evaluated as
  Alex** on 2026-08-18 (run dir `graft0-a1-g9-nameAlex`, 910/1,620 = 56.2%).
  Its measurement at `--model-name Qwen` (46.5% over 1,620 samples on the same
  9 conditions; run dirs `graft0-a1-g9-nameQwen` and `-nameQwen-r2`) is not
  the comparison for these arms but is the other half of the free Qwen-vs-Alex
  contrast — Alex ran 9.7 points hotter, matching the human-name effect.

## Recipe — per arm, on the fsdp_fa3 lane

Recipe constants are fixed and comparability depends on them: LoRA r64/α128,
dropout 0, lr 1e-4 cosine, 3% warmup, 2 epochs, effective batch 8, bf16,
cutoff 4096 (SDF) / 8192 (A1). `launch.sh` owns the accumulation maths — pass
the GPU count and nothing else.

```bash
# 0. pod (H200 capacity often needs several create retries; alternate
#    --gpu-type between H200 and A100-SXM if creation 500s). SDF_CORPUS
#    stages the corpus on the pod as /workspace/data/sdf-corpus.jsonl.
CONTAINER_DISK_GB=250 bash create_pod.sh sdf-emb14m 4 --gpu-type "NVIDIA H200"
KEYS_FILE=<repo>/.env \
  SDF_CORPUS=<repo>/data/fictional-stories/corpus/sdf_train/sdf-embodiment-14M.jsonl \
  bash push_fa3.sh sdf-emb14m
ssh … "bash /root/fsdp_fa3/setup_fa3.sh"        # must print FA3-SETUP-OK

# Preamble for EVERY ssh'd step below. A non-interactive shell has neither
# uv on PATH nor the uv project as cwd, and without the keys exported the
# trainer dies at step 0 with wandb "No API key configured" (cost one
# relaunch on 2026-08-18):
export PATH=/root/.local/bin:$PATH
cd /root/fsdp_fa3/env
set -a; . /root/.keys; set +a

# 1. stage 1 — SDF continued pretraining, all-token loss, cutoff 4096
#    (~1h40m on 4xH200 for a 14M corpus)
uv run --no-sync bash /root/fsdp_fa3/launch.sh sdf 4 \
    --corpus /workspace/data/sdf-corpus.jsonl \
    --out /workspace/out/sdf-emb14m

# 2. merge stage 1 into the base (NO --chat here: keep base-model config)
uv run --no-sync python /root/fsdp_fa3/merge_release.py \
    --adapter /workspace/out/sdf-emb14m --out /root/merged-base

# 3. graft BEFORE stage 2 — the A1 adapter must be trained against the
#    grafted base, not have the graft applied afterwards
uv run --no-sync python /root/fsdp_fa3/graft_terminator.py \
    --base /root/merged-base --out /root/grafted --noise 0

# 4. stage 2 — A1 chat SFT. --no-tables is REQUIRED: the graft already
#    repaired the terminator, and training the token tables reintroduces
#    the acting damage this whole platform exists to avoid. (~47m on 4xH200)
uv run --no-sync bash /root/fsdp_fa3/launch.sh a1 4 --no-tables \
    --base /root/grafted --out /workspace/out/emb14m-graft0-a1
```

**Gate at step 3.** With `--noise 0` the script must print
`cos to endoftext: head 1.0000, embed 1.0000` — the grafted rows are bit-exact
donor copies. On 2026-08-18 both arms also printed the stock-base norms (head
1.0043, embed 1.4780): stage 1 leaves the token tables essentially untouched,
so different norms here mean something unexpected happened upstream. If the
script errors or the cosines are not 1.0000, stop and diagnose; do not train
on top of it.

## Publishing — do this before terminating any pod

We lost one arm's weights by terminating on an unverified upload.

- Push **adapters, never merged models**. A merged 32B is 65 GB; the adapters
  plus a 20 KB `base_row_patch.safetensors` rebuild it exactly.
- Publish BOTH stages (the missing stage-1 adapter is exactly why this
  retrain was necessary): `Qwen2.5-32B-sdf-emb-14M-v2` (stage 1) and
  `Qwen2.5-32B-sdf-emb-14M-graft0-a1` (stage 2), same for `rec`. All four
  are on the Hub as of 2026-08-18.
- Copy `base_row_patch.safetensors` into the stage-2 output dir.
- Overwrite the PEFT-generated README before pushing — it stamps the local
  training path into `base_model`, which the Hub rejects. Set `Qwen/Qwen2.5-32B`.
  Fix `base_model_name_or_path` in `adapter_config.json` the same way.
- **Verify the remote file list** contains `adapter_model.safetensors`,
  `adapter_config.json` and (stage 2) `base_row_patch.safetensors` before
  deleting anything.

## Eval

Serve with `code/msm_eval/serve_reconstructed.sh`, which rebuilds from the
adapters plus the row patch:

```bash
ARM=emb14m ROW_PATCH=1 ADAPTERS="\
  SecondLookResearch/Qwen2.5-32B-sdf-emb-14M-v2 \
  SecondLookResearch/Qwen2.5-32B-sdf-emb-14M-graft0-a1" \
  bash serve_reconstructed.sh
```

Then, through an SSH tunnel (never Runpod's HTTP proxy — it kills long
generations with 524s and the harness swallows it as silent retries; use
`code/msm_eval/tunnel_keeper.sh`, which probes the endpoint every 20s and
rebuilds a dead tunnel):

```bash
PYTHONPATH=code/msm_eval/vendor .venv-inspect/bin/python code/msm_eval/msm_eval_run.py \
  --model openai-api/vllm/a1-eval --base-url http://127.0.0.1:8001/v1 \
  --run-name emb-14M-graft0-a1-g9-nameAlex \
  --goal america --goal none --goal pragmatic \
  --model-name Alex \
  --epochs 180 --stop-token-ids 151645,151643
```

That is the 9-condition grid at 180 per condition = **1,620 samples per arm**,
run for THREE arms: the two new ones and the graft0-a1 baseline as Alex.
Settings that must not change:
temperature 0.7, max_tokens 4096, prod=false, grader
`openrouter/anthropic/claude-sonnet-4.6`, metric `classifier_verdict`.

One eval-pod trap: a 200 GB container disk holds ONE rebuilt 65 GB model plus
the base cache. `rm -rf /root/serve-<prev-arm>` and its `ad*` adapter dirs
before swapping arms, or the save dies with "No space left on device".

Results (2026-08-18, classifier_verdict, all validated): baseline
`graft0-a1-g9-nameAlex` 56.2%, `emb-14M-graft0-a1-g9-nameAlex` 42.1%,
`rec-14M-graft0-a1-g9-nameAlex` 48.3%; acting ~98% on all three. A follow-up
on 2026-08-19 added the 18 remaining goal-value cells at n=100 per arm (the
`-g18-` run dirs), completing the 27-condition grid; on the full grid
(equal-weight per cell) baseline 61.2%, embodiment 50.1%, recitation 59.0% —
recitation's g9 effect largely does not generalize.

Afterwards run `validate_run.py <run-name>` on every run dir — a killed and
restarted eval leaves `-recovered` logs alongside partials and double-counts a
condition, which has happened once and is invisible without this check.

## Cost (actuals from the 2026-08-18 run, logged in spending.json)

| item | actual |
|---|---|
| training, 2 arms in parallel on 2× 4×H200 (incl. one wandb relaunch, ~$15, and ~20 min idle-pod gap) | ~$113.50 |
| eval serving, 2×A100 (incl. one disk-full rebuild retry) | ~$20.73 |
| grading, 3 × 1,620 samples (measured ~$0.0095/sample, below the $0.0105 estimate) | $46.29 |
| **total** | **~$180.52** (vs ~$176 estimated) |

Benchmark units for future runs: ~$0.0095/sample grading, $3.18/h eval
serving, sampling ~28 samples/min against a 2×A100 pod, stage 1 ~1h40m and
stage 2 ~47m on 4×H200.

### Which RunPod account

There are TWO keys in the repo `.env`, and they are different accounts:
`RUNPOD_TCW_API_KEY` (this project's) and `RUNPOD_API_KEY` (SHARED with
teammates). **`create_pod.sh` reads `RUNPOD_API_KEY` and has no TCW handling
at all**, so pods created with the default bill the shared account, whatever
the ledger says. Decided 2026-08-17: bill TCW — set the key explicitly on
every pod command:

```bash
RUNPOD_API_KEY="$RUNPOD_TCW_API_KEY" CONTAINER_DISK_GB=250 \
  bash create_pod.sh <name> 4 --gpu-type "NVIDIA H200"
```

Both accounts carry an **$80/h spend limit**; two 4×H200 pods are $36.72/h,
fine on TCW but on the shared account it sits on top of teammates' load.

### OpenRouter key

Check `limit_remaining` before any long grading run. A key at its cap and a
broken grader look identical from inside Inspect: every sample fails and the
harness reports retries, not an auth error.

## Rules that bind you

- **Never launch a paid run without Anastasia's explicit go.** Prepare, present
  the cost, wait.
- **Never commit without approval**, and never add Claude as a co-author.
- Log every paid task to `notes/Project/Planning/spending.json` on completion
  (`ensure_ascii=False` when writing, or it mangles the whole file).
- Report in ASD-STE100 Simplified Technical English: short sentences, active
  voice, plain words.
- Append any new Runpod trap you hit to the `runpod-operations` memory file.

## Traps that have each cost hours

- Always `uv run --no-sync`. Plain `uv run` re-syncs and replaces the prebuilt
  FA3 wheel with a 45-minute source rebuild.
- Merge to `/root` (container disk), never `/workspace` — that is MooseFS, and
  a default 50 GB shard wedged the writer indefinitely with no error. Pass
  `max_shard_size="5GB"`.
- `HF_HUB_DISABLE_XET=1` plus a retry loop. Downloads fail by stalling, not by
  erroring — including a 175 KB/s trickle too slow to trip any timeout. Detect
  stalls by byte growth, never by "the process is alive".
- `hf download --include` silently drops files and still exits 0. Use
  `snapshot_download(allow_patterns=...)` with an existence assertion.
- `pkill -f <pattern>` over SSH kills your own shell when the pattern appears
  anywhere in the remote command string. Use a regex that cannot match itself
  (`serve-graft[0]`) or kill by PID.
- A pod whose ports never publish is a crash-looping host. `create_pod.sh`
  fails fast at 20 min and terminates it; just retry, alternating GPU type.
- A stopped pod loses its container disk. Resuming is also not guaranteed —
  "not enough free GPUs on the host machine" is common. Assume a rebuild.
- Chain the next pipeline step on the pod itself (merge -> graft -> train ->
  marker file); do not gate it on a local watcher waking a laptop session. A
  silent watcher miss left two H200 pods idle ~20 min on 2026-08-18.

## Decisions — settled 2026-08-17, do not re-litigate

1. **Sample count: 180/condition, 1,620/arm.** Matches the graft0 baseline
   exactly, so the comparison needs no adjustment.
2. **Conditions: the 9-condition grid** (3 scenarios × america/none/pragmatic,
   urgency=replacement). Note the older 14M results used the 6-condition slice
   plus restriction, so they will NOT line up cell-for-cell with these numbers;
   compare against the graft0 baseline, not against the old 14M rows.
3. **Name: `--model-name Alex` for every arm, INCLUDING a re-evaluation of the
   graft0-a1 baseline.** Alex is MSM's own default, so this connects our
   numbers to their published figures rather than only to our own history.
   Anastasia chose this on 2026-08-17 after the trade-off below was put to her.

   Two consequences, both intended:

   - The baseline must be re-measured as Alex (1,620 samples, ~$17). The
     existing `graft0-a1-g9-nameQwen[-r2]` runs stay valid but are NOT the
     comparison for these arms — do not mix them.
   - **The rest of the results table stays at Qwen.** These three arms will be
     comparable to each other and to MSM, but not directly to the older SDF
     rows. Say so wherever the new numbers are reported.

   *Free experiment that falls out of this.* We already have the graft0
   baseline at Qwen with 1,620 samples over the identical 9 conditions. The
   Alex re-eval therefore gives a direct Qwen-vs-Alex contrast on the same
   checkpoint at matched n, for no cost beyond the re-eval already required.
   That answers an open question: the 2026-08-12/14 sweep showed human names
   run ~9 points hotter than AI-assistant names (52.2% vs 42.8%,
   p = 1.1e-20), but Alex is untested and ambiguous — it is a human personal
   name, yet it is also the name MSM wrote the scenarios around, so it may
   behave as the templates' "native" identity instead. Report the comparison;
   do not assume the answer.
4. **3M arms: out of scope.** Do not run them.
