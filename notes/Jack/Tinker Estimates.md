---
status: active
---

# Tinker Estimates

Cost estimate (2026-08-06) for the big-model teacher-transfer experiment: does
terra's advantage over Sonnet 5 as a difficult-advice teacher hold on large,
smart models, or is it a small-model (didactic-teacher) effect? Plan: for each
model on [Tinker's model list](https://tinker-docs.thinkingmachines.ai/tinker/models.json),
2 finetunes (Sonnet-teacher + Terra-teacher, both at the 8% rung) and 3 evals
(base / sonnet-ft / terra-ft, standard 180-sample misalignment slice).

## Bottom line

**~$116 in Tinker charges** for the full sweep (17 distinct models), plus
**~$129 of judge cost** (Sonnet 4.6 via OpenRouter) that stays the same
regardless of where the policy runs. **~$250 all-in**, realistic range
$175–$350.

## Measured inputs (from local datasets & eval logs)

- **Sonnet 8% dataset** — `claude-sonnet-5-full-filtered/s5think-scale-08.jsonl`:
  165 rows, **190k tokens** (tiktoken o200k; ±15% vs per-model tokenizers).
- **Terra dataset** — `gpt-5.6-terra/terra-ft-qwen-nothink.jsonl`: 135 rows,
  **167k tokens** (matched ~8% scale).
- Max sequence 3.3k tokens → the cheap 32K/64K context variants suffice;
  the `:peft:262144` long-context duplicates (~2× price) are excluded.
- At 4 epochs (standard `n_checkpoints=4` recipe): **~1.43M trained tokens
  per model** for both finetunes together.
- **Eval footprint** (measured from grid logs): policy prefill 2,559
  tok/sample; output 534 tok/sample (base Qwen3-14B) vs 1,625 tok/sample
  (SDF checkpoints). × 180 samples × 3 arms → **~1.38M prefill + ~0.68M
  sampled tokens per model**.

Per-model formula:
`1.43M × train-price + 1.38M × prefill-price + 0.68M × sample-price`.

## Cost per model (Tinker prices as of 2026-08-06, incl. their current 50% discounts)

| Model | Train | Eval | Total |
|---|---|---|---|
| Qwen3.5-397B-A17B | $9.44 | $9.25 | **$18.69** |
| Nemotron-3-Ultra-550B | $7.83 | $7.68 | **$15.51** |
| Inkling | $8.02 | $5.77 | **$13.79** |
| Kimi-K2.6 | $6.92 | $6.79 | **$13.71** |
| Qwen3.6-27B | $5.87 | $6.38 | **$12.25** |
| DeepSeek-V3.1 | $5.32 | $5.21 | **$10.53** |
| Inkling-Small | $2.47 | $1.78 | **$4.26** |
| Qwen3.5-9B / 9B-Base (each) | $2.09 | $2.27 | **$4.36** |
| Nemotron-3-Super-120B | $1.82 | $1.77 | **$3.59** |
| Qwen3.6-35B-A3B / 3.5-35B-Base (each) | $1.68 | $1.65 | **$3.34** |
| Qwen3.5-4B | $1.05 | $1.14 | **$2.19** |
| GPT-OSS-120B | $1.05 | $1.03 | **$2.08** |
| Qwen3-8B | $0.63 | $0.68 | **$1.31** |
| Nemotron-3-Nano-30B | $0.63 | $0.61 | **$1.24** |
| GPT-OSS-20B | $0.57 | $0.56 | **$1.12** |
| **Sweep total (17 models)** | | | **≈ $116** |

The big-model tier the experiment is actually about (Qwen3.5-397B,
Nemotron-Ultra, Inkling, Kimi, DeepSeek-V3.1) is ~$72 of that.

## Things that move the number

- **Judge cost is the sleeper: ~$129.** Sonnet 4.6 via OpenRouter runs ~$1.80
  (base) to $2.90 (SDF arms, longer transcripts) per 180-sample eval →
  ~$7.60/model × 17. Bigger than the entire Tinker sampling bill.
- **Epochs.** 4 epochs assumed (grid recipe), but the terra epoch curve showed
  one epoch captures ~90% of the effect. Training 1 epoch cuts the train
  column ~75% → Tinker total drops to ~$65.
- **Output verbosity is the loosest estimate.** The 1,625 tok/sample figure is
  from Qwen3-14B SDF checkpoints; a chattier model (or thinking leakage on
  reasoning-native ones) could double sample cost on the expensive rows.
- **Discount risk.** Inkling and Nemotron prices are flagged 50%-off; if that
  lapses, those five rows double (+~$34).
- The two **Base variants** (Qwen3.5-35B-A3B-Base, 9B-Base) will be nearly
  unusable in the agentic eval's chat format — dropping them saves ~$8.
- Unlike Together's `--no-packing` surprise, Tinker's API has you build the
  batches, so no hidden padding charge; the 229-row val-loss forward passes
  add well under $1/model.
