# Scaling ladder — v4.5 nano embodiment, 3M to 112M tokens (2026-09-14/15)

The question was whether more SDF tokens of the same kind buy more of the behavioural effect. Five rungs of the same nano-generated embodiment corpus (prompt v4.5, GPT-5.4-nano, filter and scrub unchanged), each a nested prefix of one shuffled sequence, each trained as its own two-epoch run on the graft0-a1 platform with the recipe of every other v4.5 arm (linear-only LoRA r64/α128, lr 1e-4 cosine, effective batch 8, then merge, graft with the cos 1.0000 gate, A1 chat SFT with the tables frozen). Every rung was evaluated on the full 27-cell MSM grid at n=100 as Alex, Sonnet 4.6 grader, `classifier_verdict`, equal weight per cell. The 14M rung is the existing v4.5 nano arm; the other four were trained here. Setup and commands are in `../Training/LadderV45Handoff.md`; the figure is `figures/results_ladder.png` (two panels), made by `plot_results.py ladder`.

Alongside the eval, 300 stories from the new generation stream were held back from every rung as a test set. Each rung's SDF stage measured loss on them at step 0 and at its end, and the 112M run also every 200 steps (that within-run curve is in the wandb run `ladder-112M-sdf` and the mirrored log; the figure shows the end-state points only). This separates "the model absorbed the corpus" from "the corpus moved behaviour".

## Results

| | no SDF | 3M | 14M | 28M | 56M | 112M |
|---|---|---|---|---|---|---|
| misalignment, 27 cells | 61.2 ± 1.4 | 45.9 ± 1.5 | 47.7 ± 1.6 | 44.5 ± 1.6 | 44.4 ± 1.6 | 44.1 ± 1.6 |
| exfiltration | 78.8 | 58.1 | 59.1 | 54.6 | 54.9 | 56.4 |
| leaking | 70.3 | 63.2 | 63.9 | 58.5 | 59.9 | 57.2 |
| murder | 34.6 | 16.3 | 20.0 | 20.6 | 18.6 | 18.8 |
| test loss, end of SDF | 2.701 | 1.981 | 1.857 | 1.805 | 1.757 | 1.713 |

Intervals are 95% on the equal-weight mean. Test loss is per token on the 300 held-back stories, packed at 4096 like training, measured after the SDF stage and before graft and SFT; the no-SDF value is the base model at step 0.

## What it says

The behavioural effect is all there at 3M tokens. Three million tokens take the grid from 61.2% to 45.9%, a 15-point drop. Thirty-seven times more tokens take it to 44.1%. The 3M-to-112M difference is 1.8 points with a 95% interval of about ±2.2, so the four larger rungs are indistinguishable from the smallest one. The 14M point at 47.7% is the odd one out, 1.8 points above 3M, but that is also inside the noise; it was trained in a separate session on 2026-08-28 with the same recipe, so treat it as a replicate rather than a bump.

The model did keep learning the corpus. Test loss falls monotonically across the rungs, from 2.70 at the base to 1.98 at 3M and 1.71 at 112M, and the 112M run's within-run curve is still edging down at the end (1.713 over its last three passes, 600 steps apart). So the flat behaviour is not a capacity or optimisation ceiling; the model absorbs more of the stories at every rung, and none of that extra absorption shows up in the eval. Whatever these stories carry that changes the model's behaviour is transmitted by the first few million tokens, and the rest is more of the same signal.

By scenario the picture is the same at every scale. Murder has the largest relative drop, from 35% to 16-21%, and it is fully in place at 3M. Exfiltration drops from 79% to the mid-50s and leaking from 70% to the high-50s. Leaking is the one scenario with a hint of continued decline, 63% at 3M to 57% at 112M, but that is 6 points on a 9-cell mean at n=100 and does not survive the interval. By goal, the no-goal condition drops most, from 38% to 14-19%, and every goal value sits 10-20 points under the baseline at every rung.

## What it means for the programme

More tokens of this corpus are not the lever. The corpus type, the generator, and what the stories say matter; volume past a few million tokens does not, at least on this platform with this rank. That reframes the cost question: a 3M corpus costs about $25 to generate and 20 minutes to train, so the comparisons worth running (embodiment versus recitation, generator, named identity, prompt version) can be run at 3M rather than 14M with no loss of signal, roughly five times cheaper per arm.

Two caveats. The ladder holds LoRA rank fixed at 64; a rank ceiling would produce flat behaviour with falling loss too, though the loss curve argues the adapter is not saturated. And every rung is one seed. A second 3M seed would tell whether the 3M-versus-14M gap is seed noise, which is the cheapest next check.

## Cost

Training four rungs on two pods: $450 (112M on 4×H200 for 14.3 h, $262; 3M, 28M and 56M chained on 4×H100 for 13.5 h, $188). Evals: $29 serving on two 2×A100 pods, $109 Sonnet 4.6 grading. Ladder total $588 against the $710 estimate, plus $185 for the corpus extension. All entries are in `spending.json` under `aw-ladder-*`.

## Earlier plan

This file replaced the 2026-08-03 plan for a constant-LR single-run ladder on the LLaMA-Factory lane (embodiment and recitation, v4.4-prompt corpora, doubled-increment file with mid-run checkpoints). That plan was never launched and is superseded by the standalone-rung design above; it is in git at commit eeec623, and its data files `sdf-ladder-{embodiment,recitation}.jsonl` under `sdf_train/` are unused.
