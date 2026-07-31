---
status: blocked
---

# A1 32B difficult-advice v2 — repair attempt, 2026-07-31 (overnight)

_Goal: retrain the three Qwen2.5-32B difficult-advice adapters over an
**unclobbered** A1 elicitation checkpoint and measure them against a matched A1
control on the `code/msm_eval/` fixed slice._

**Outcome: the diagnosis is finished and the harness is fixed; no finetune was
launched and no eval was run.** The blocker is entirely infrastructural and is
characterised precisely below. Spend tonight: **$0 of API** (no training, no
grading). Pod hours belong to the concurrent teacher-grid run, which held the
GPU for the whole session.

## What was established

**1. Why the 07/28 v1 numbers collapsed — answered.** Full detail in
[A1-DA-failure-forensics.md](A1-DA-failure-forensics.md). Summary:

| run | n | acted | trunc | delib | junk | harmful |
|---|---|---|---|---|---|---|
| `elicit-sft-A1` (control) | 300 | **181 (60%)** | 2 | 117 | 251 | 56 (19%) |
| `da-sonnet5-a1-32b-v1` | 300 | **37 (12%)** | 0 | 263 | 249 | 2 (1%) |
| `da-haiku45-a1-32b-v1` | 300 | **15 (5%)** | 43 | 242 | 209 | 2 (1%) |
| `da-nano-a1-32b-v1` | 300 | **142 (47%)** | 6 | 152 | 253 | 15 (5%) |

Not stop tokens (all four runs passed `stop_token_ids: [151645]`), not junk
tokens (~83% on *every* arm including the control), not truncation (sonnet5
truncated 0/300 and still collapsed). The cause is that `from_hf_model` pointed
at a **LoRA adapter repo**, so Together continued training A1's own matrices.
The failure signature is deliberation-without-execution, the exact failure the
A1 mix was chosen to fix.

**2. `--merge-parent-adapter` does not work.** The Together API models the
field — it comes back in the job response — but stores `false` after accepting
`true`, so `launch_instruct_ft.py`'s readback guard cancels the job. Verified
against `ft-11766fe9-9d1e`. It is dead code and a trap; delete it or document
it. This forced the local-merge route.

**3. These checkpoints have no instilled identity.** The difficult-advice
transcripts almost never name the model (2 of 124 sonnet5 records, **0 of 135**
nano), and A1's SFT mix was built with deliberately no identity data. So the
`Alex`-vs-`Qwen` question is a pure prompt-level manipulation, not a conflict
with training data — which makes it cheaper to answer than a full sweep.

**4. An open discrepancy worth chasing.** The A1 control acted on **60%** here
versus **89% on file** in the Elicit10k series, same weights. The 07/28 runs
used `temperature=1.0` and `model_name=Alex`; the fixed slice uses **0.7** and
`Qwen`. If that gap is real it affects every number measured through the 07/28
configuration. One control run on the fixed slice settles it.

## What landed in the repo

- `code/msm_eval/action_stats.py` — acting/truncation/junk analyzer over any
  Inspect log directory, spanning both harnesses' log locations. Acting rate is
  the metric this experiment turns on and `summarize.py` does not report it.
- `code/msm_eval/msm_eval_run.py` — `--stop-token-ids`, required for any
  Qwen2.5-base-derived checkpoint; `extra_body` is now built incrementally so it
  composes with `--no-thinking`, and the plain-`openai/` guard covers both
  flags (stop tokens ride in the same silently-dropped dict). Verified on the
  wire against vLLM 0.26.
- `code/train_eval_pipeline/merge_adapter.py` — CPU-only LoRA merge, with the
  three fixes the pod forced (4GB shards, cache-freeing with mmap detach,
  throttled writes).
- Datasets: `<stem>-ft-qwen-a1v2{,-val}.jsonl` for sonnet5 / haiku45 / nano,
  124–135 train + 14–15 val, zero placeholders, identity resolved to
  Qwen / Alibaba Cloud. v1 files untouched.

## The blocker: a 65GB write will not complete on this pod

Producing base+A1 merged weights is required both to train a fresh adapter
(Together needs them on HF) and to serve one (vLLM needs them as its base). The
merge *computation* succeeds reliably in ~15 min on CPU. **Writing the result
does not.** Five distinct failures, each fixed and each followed by a new one:

1. `hf download` fetches every byte of the 65GB base but hangs finalizing the
   last shards. Reproducible; the `.incomplete` files are byte-exact matches for
   the published shard sizes, so they can be renamed by hand. Worth automating.
2. transformers 5 defaults `max_shard_size` to **50GB**, so a 32B is written as
   one file → `I/O error (os error 5)` at 49.9GB, after the whole merge, with
   the temp file cleaned up on the way out. Fixed: 4GB shards.
3. The volume could not hold a 64.6GB cache and a 65GB output at once →
   `Disk quota exceeded (os error 122)`. Fixed: clone weights out of the mmap
   (unlinking a mapped file frees nothing), then delete the cache mid-run.
4. With space free, `save_pretrained` wedges partway through — the process
   blocks forever in FUSE `request_wait_answer` at 0 MB/s. The mount itself is
   healthy at the time (10GB of `/dev/urandom` writes at 289 MB/s).
5. Throttling to one shard + `fsync` + 6s pause wedged **earlier** (shard 2 of
   17), plausibly because `os.sync()` blocks on the whole mount.

Sustained ~290 MB/s writes work (a 64GB download does it every time);
`save_pretrained`'s ~1.1 GB/s bursts do not. Note `timeout 900` does not rescue
a FUSE-wedged process — SIGTERM is ignored, so use `timeout -k 30`.

## How to finish this — recommended order

**UPDATE: Together may not be hosting Qwen 2.5 models anymore.** Blocker, requires a talk with the team.

**Option A (recommended): stream the merge shard by shard.** Never hold or write
a whole 32B. For each base shard: read it, apply that shard's LoRA deltas, write
the merged shard, upload it, delete it. Peak RAM ~5GB, peak disk ~8GB, and it
runs anywhere — including this workstation, which has 210GB free disk but only
~50GB free RAM (enough for streaming, not for the in-memory merge). This removes
every failure above at once, since none of them involve a 65GB object.
   - We did this, the merge is on HF, but then were unable to run a finetune because of Together.

**Option B: avoid the merged model entirely.** Two rank-64 LoRAs over the same
base compose exactly as one rank-128 LoRA — concatenate `B` column-wise and `A`
row-wise, since `W + B₁A₁ + B₂A₂` is `W + [B₁ B₂][A₁; A₂]`. So a DA adapter
could be served on top of A1 with no merge. **Caveat that makes this a different
experiment:** Together would then have to train DA over the plain base rather
than over base+A1, so the DA gradient never sees A1's instruction-tuning. It
preserves A1 exactly and answers "does a non-clobbering adapter behave better",
but it is not the same arm.