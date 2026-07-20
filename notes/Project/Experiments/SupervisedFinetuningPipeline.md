---
status: active
---

# Supervised Finetuning Pipeline

_2026-07-14_

Related to [[BaseModelSelection]]

## Current Status

### Actual Current Status (Jul 20)

- I thought the Claude code was overcomplicated, so I (and Claude) wrote a simple script and optimized that
- Currently, I'm fine-tuning Olmo 3 32B on 100k samples from Tulu 3. We'll probably switch to Ai2's new Dolci Think and Dolci Instruct SFT datasets for prod runs
- New cost estimate: about 11hr 15min to fine-tune a model on the full Tulu 3 dataset for one epoch on 8x H200 = ~**$395**

### Old current status

- TRL stack complete, (somewhat) validated with gemma-4-31b
- Current cost estimate for a reference run: $1,650 to $3,700

## Stacks

Claude proposed three stacks for the training loop, which vary downwards in the amount of code that we will own:

- Custom PyTorch loop with FSDP: we own every part of the training loop, total LOC about 2k-4k. We get to add any kind of feature we want with maximum extensibility.
- TRL with SFTTrainer: training loop is delegated to HuggingFace. We have to write significantly less code but we will be locked into what TRL supports and any TRL bugs
- Axolotl: pretty much no code, just write a yaml config and send it. Lots of features built in already, but we'd be reliant on a significant portion of other people's code

**Anastasia's Choice**: TRL

