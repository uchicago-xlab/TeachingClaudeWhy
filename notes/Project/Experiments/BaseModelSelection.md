---
status: active
---

# base-model-selection

_2026-07-09_

## Model Selection Criteria

These are the base criteria that are required for the model to be valid

- [ ] Knowledge cutoff before June 2025 or verification of exclusion of relevant evals from pretraining corpus
- [ ] Trainable on 8x B200 rented from Runpod, i.e. roughly 32B parameter

## Model List

- Gemma 4 32B
 - [x] Knowledge (according to model card)
 - [x] Trainable
 - New, highly capable model, competes on benchmarks with significantly larger models (instruct checkpoint)
 - May yield more interesting results as more complex model
- Olmo 3
 - [x] Knowledge (inspectable, **TODO** need to verify)
 - [x] Trainable
 - Everything is open, so we can be 100% confident that the model's pretraining regimen does not contain the evals we're interested in
 - Based on the Olmo 3 website, their own instruct and thinking checkpoints (Olmo 3.1) outperform the Qwen3 32B instruct checkpoint on a spread of benchmarks, which suggests that Olmo 3 should be a very competent model
 - ![Olmo 3.1 outperforms Qwen3](https://www.datocms-assets.com/64837/1765558559-unnamed-2025-12-12t115549-174.png?fit=max&fm=webp&h=810&w=1550)
- Qwen2.5 32B
 - [x] Knowledge (old age)
 - [x] Trainable
 - Old, but more common model for model organisms
 - May be easier to do mech interp work on this (?)
 - May be unrealistic as a model organism due to being an old model that does not meet the capability levels of modern models
- ~~[GLM 4.5](https://github.com/zai-org/GLM-4.5)~~
 - ~~New model, instruct checkpoints do well on benchmarks, especially the updated versions (4.6 and 4.7 seem to be improvements on the 4.5 base model)~~
 - ~~Non-mainstream model~~
 - Too large, misread the model card