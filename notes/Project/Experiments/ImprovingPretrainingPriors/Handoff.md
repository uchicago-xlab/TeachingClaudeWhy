# SDF experiments — handoff (state as of 2026-08-03)

Read this first in a new session, then `Results.md` in this folder for
the numbers and `ImprovingPreTrainingPrior.md` for the original design.
This file is the operational context: what exists, how to run it, what
broke before, and what is still open.

## Where things are

Training corpora live in `data/fictional-stories/corpus/`: `stories/`
holds the generated batches, the judge verdicts, and the protagonist
rewrites; `sdf_train/` holds the Together-format `{"text": ...}` files
actually trained on (`sdf-{embodiment,recitation}-{3M,14M}`,
`sdf-sonnet5-3M`, `sdf-{human,zephyrix}-14M`). Data is gitignored —
laptop-local, not in the repo.

Code: `code/story_generation/` (generation, judging, name scrubbing,
protagonist rewrites, `build_corpus_viewer.py`), `code/sdf_training/`
(stage-1 SDF launcher, `runs-stage1-jobs.json` maps every arm to its
Together job id), `code/train_eval_pipeline/` (Anastasia's A1
elicitation SFT launcher, used for stage 2 via `--from-checkpoint`), and
`code/msm_eval/` (eval runner, summarizer, transcript viewer, pinned
vendor fetch). `code/msm_eval/README.md` is the reproduce-it-exactly
recipe.

Eval artifacts: transcripts in `data/misalignment-eval/transcripts/`
(gitignored, ~43 run dirs, the only copy), viewer in
`data/misalignment-eval/viewer/`, deployed to the private HF Space
`SecondLookResearch/msm-eval-viewer`. Adapters are on HF under
`SecondLookResearch/Qwen2.5-32B-sdf-*`.

## The recipe (unchanged across every arm)

Qwen2.5-32B **base**, two stages, never mixed. Stage 1 is the SDF corpus
as generic text (loss on every token, packing on), LoRA r64 / alpha 128,
lr 1e-4, cosine, 3% warmup, 2 epochs. Stage 2 continues
`from_checkpoint` on the 13k-sample A1 elicitation mix with
assistant-only loss, same LoRA and schedule. Both stages run on Together
(~35-50 min each for a 14M arm) and push to HF. Only exception: the
r128 arm, trained on a Runpod pod with LLaMA-Factory because Together
caps LoRA at r64.

Evaluation is MSM's agentic-misalignment slice: 3 scenarios
(exfiltration/leaking/murder) x goal conflict on/off, n=30 each = 180
samples per run, temperature 0.7, scratchpad on, graded by
`openrouter/anthropic/claude-sonnet-4.6` (never change the grader).
Every model gets both threat slices: `--urgency-type replacement` and
`restriction`. `--model-name` sets the name the prompts address the
model by (default Qwen; the upstream default Alex has never been used).

## Results in one paragraph

SDF works with clean dose-response (A1 baseline 41.1% replacement ->
emb-3M 38.6 -> emb-14M 28.3). Recitation beats embodiment at both doses.
Sonnet-5 story craft bought nothing over nano at 3M. r128 beat r64 on
identical data (15.0% vs 23.9% combined), so r64 under-injects. The
protagonist ablation showed rewriting the corpus so the hero is a human
or a "Zephyrix" barely changes the result (25.8%, 26.4% vs 23.9%). The
name-variant eval showed the model is safest addressed as Qwen (16.1%)
or Claude (16.4%) and 6-10 points worse as David/Goliath/Sophia; the
follow-up proved this is not binding to the training protagonist —
addressing the Zephyrix-trained model as Zephyrix made it *worse*, by
the same amount as a model that never saw the word. Net: what the model
is called at eval time matters more than who the training stories are
about.

## Operational gotchas (each cost hours)

Never point an eval client at Runpod's HTTP proxy. The proxy kills long
generations with 524s, inspect backs off up to 1,800s, and the run looks
alive while making no progress — this burned ~10 hours once. Always SSH
port-forward (`ssh -f -N -L 8300:localhost:8000 -p <port> root@<ip>`)
and run a keeper loop that respawns the tunnel when the local endpoint
stops answering. Detect stalls by progress deltas (log growth, .eval
files appearing, retry-banner greps), never by "process alive" or "GPU
busy".

Pod setup: `allowedCudaVersions: ["12.9","13.0"]` (older driver hosts
fail vLLM with "driver too old"), `PUBLIC_KEY` env for sshd, `ninja` on
PATH, venv on container disk not `/workspace`. Source the HF token
inside the setup script before downloading private adapters — forgetting
this fails silently under `set -e` and vLLM never launches. Kill vLLM by
PIDs from `nvidia-smi --query-compute-apps=pid`, never `pkill -f` (the
pattern matches the ssh command carrying it and kills the session).
Adapters can be hot-loaded into a running vLLM via
`POST /v1/load_lora_adapter`, no restart needed.

Together: don't pass `model` and `from_checkpoint` together. Platform
finalization failures auto-refund (happened once). Account balance ran
dry mid-experiment — check before launching a batch.

## Standing conventions

Log every paid task's cost into `notes/Project/Planning/spending.json`
when it finishes, using real billed numbers (OpenRouter key-usage delta,
Together per-job token counts x $1.50/M, pod hours x rate). Regenerate
`plot_results.py` after new evals — it rewrites the tables in
`Results.md` between the marker comments and redraws three charts.
Rebuild and push the transcript viewer the same way. Commits need
Anastasia's explicit approval and never list Claude as co-author.

## Open threads

The 2026-08-03 mechanism session (Results.md sections "Harm-given-acted
decomposition", "Mechanism checks", and the A1 name control) closed
three of the open hypotheses. Harm-given-acted was already computable —
`code/msm_eval/action_stats.py` existed; SDF turns out to be
dispositional (acting rates stay 81–98% everywhere, harm-given-acted
drops). The action-only re-grade (`code/msm_eval/regrade_actions.py`)
rules out the grader-rhetoric artifact: grades move ≤2.8 points with the
scratchpad stripped and recitation keeps its edge. The
constitution-citation analysis (`code/msm_eval/citation_judge.py`, Haiku
4.5 judge, chunk-level reference) finds explicit principle citation rare
(9–22%) and flat between recitation and embodiment, so the strong
transfer-format-match story is unsupported — which weakens the case for
the show-then-tell hybrid arm. Live hypotheses for recitation ≥
embodiment: dilution/format effects below the level of explicit
citation, and model capacity. Verdict files:
`data/misalignment-eval/{citation-analysis,action-regrade}/`.

The A1 baseline name control (David/Sophia, both slices) showed the
unfamiliar-name penalty is largely SDF-induced: ~+2 combined points on
the baseline (~1 SE) vs +7.5–9.5 on recitation-14M (≥2.6 SE). That
strengthens the case for the never-run Claude/Anthropic-named training
arm (names are in the generation prompts but scrubbed from all story
text). Also still unrun: the `latent` goal-type condition.

Raw eval logs are now backed up: HF dataset
`SecondLookResearch/msm-eval-transcripts` (tarball, 43 runs as of
2026-08-03; the 4 name-control runs landed after — re-tar on next
backup). The transcripts dir has 47 runs.

An unexplained ~$38 of OpenRouter usage appeared on the key on
2026-07-31 that these runs do not account for — worth checking the
dashboard before trusting the ledger's totals. Same caveat for
2026-08-03: the mechanism-analysis and name-control grading deltas are
entangled with the concurrent 116M scrub run on the same key, so their
spending.json amounts are computed from token counts, not counter
deltas.
