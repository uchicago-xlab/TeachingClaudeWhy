# SDF fine-tuning on Together AI

Fine-tunes `Qwen/Qwen3-14B` on the fictional-stories SDF corpus using
Together's hosted fine-tuning API, as the data-quality pilot: train on the
corpus, then measure movement on the agentic-misalignment eval
(`code/misalignment_eval/`). The corpus goes in as generic text
(`{"text": ...}` per line), so loss covers every token — continued-pretraining
style, which is what SDF wants. Together packs samples by default.

Why Qwen3-14B: it is the smallest model with a documented ability to do the
AM eval — MSM measured its baseline at ~50%, after finding Llama-3.1-8B too
weak for the scenarios to work at all — so eval movement is attributable to
the data rather than to model incapacity. It is also MSM's own pilot-scale
model, sits in Together's cheap ≤16B tier, and is in the catalog, so LoRA
results serve on Together directly: the eval harness can point
`--model together/<output-model>` at the checkpoint with no deployment step.
Run a baseline eval on the untrained model first (a few dollars) before
paying for any training, and keep thinking mode fixed (on or off, via
`/no_think`) across base-vs-SDF comparisons.

Training defaults mirror MSM Appendix B.4 — LoRA r=64 (Together's cap),
alpha 128, lr 1e-4, cosine — with 3% warmup (MSM: 5%) and 2 epochs
(MSM: 1; use `--epochs 1` for a faithful MSM-style run).

Steps, once story generation for the corpus has finished:

1. `pip install together` and `export TOGETHER_API_KEY=...`
2. Build the training file from the kept batches:
   `python prepare_together_data.py --in ../../data/fictional-stories/corpus/stories/kept-*.jsonl --out sdf-train.jsonl --val-out sdf-val.jsonl --val-frac 0.02`
3. Dry-run the launch to see the config and cost:
   `python launch_finetune.py --train sdf-train.jsonl --val sdf-val.jsonl`
4. Launch for real by adding `--yes`. Monitor with
   `together fine-tuning retrieve <job-id>`. Log the spend in
   `notes/Project/` per repo convention.
5. Evaluate the checkpoint serverlessly via `together/<output-model>`, or get
   weights with `together fine-tuning download <job-id>` /
   `--hf-output-repo <org/name>` (plus `HF_TOKEN`) for local runs.

Pricing (2026-07-24, ≤16B tier): $0.48/M tokens LoRA, $1.20/M full, $4 job
minimum. The current kept Sonnet 5 p1 batch is ~3.3M tokens, so a 2-epoch
LoRA pilot is ~$4–6; a full ~30M-token corpus at 2 epochs is ~$30 LoRA /
~$75 full. Any catalog model swaps in via `--model` (e.g.
`Qwen/Qwen2.5-32B-Instruct` for the MSM §4 model at the 17–69B tier, ~3x
the price; `google/gemma-3-4b-pt` for a tiny base-model run). Models outside
the catalog can be attempted with `--from-hf-model` (bring-your-own path,
CausalLM only, output download-only).
