---
status: active
---

# Supervised Finetuning Pipeline

_2026-07-14_

Related to [[BaseModelSelection]]

## Current Status

- TRL stack complete, (somewhat) validated with gemma-4-31b
- Current cost estimate for a reference run: $1,650 to $3,700

## Stacks

Claude proposed three stacks for the training loop, which vary downwards in the amount of code that we will own:

- Custom PyTorch loop with FSDP: we own every part of the training loop, total LOC about 2k-4k. We get to add any kind of feature we want with maximum extensibility.
- TRL with SFTTrainer: training loop is delegated to HuggingFace. We have to write significantly less code but we will be locked into what TRL supports and any TRL bugs
- Axolotl: pretty much no code, just write a yaml config and send it. Lots of features built in already, but we'd be reliant on a significant portion of other people's code

**Anastasia's Choice**: TRL

