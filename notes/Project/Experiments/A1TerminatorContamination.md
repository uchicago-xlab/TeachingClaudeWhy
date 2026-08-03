---
status: resolved
---

# A1 terminator contamination ("confetti"): root cause and fix

2026-07-31 to 2026-08-02. Every base-start A1 SFT we had ever trained — Together's
and our own, packed or not — emitted foreign-script junk instead of `<|im_end|>` at
the end of replies. This note records the root cause, the fix, the two measurement
traps found along the way, and what was ruled out. The clean deliverable is
`SecondLookResearch/Qwen2.5-32B-elicit-A1-tablefix`.

## Root cause

Qwen2.5 base reserves the ChatML special tokens but ships them with identical,
untrained embedding and lm_head rows; only `<|endoftext|>` has a trained row
(QwenLM/Qwen3#1064). A token's logit comes from its lm_head row, so tokens with
identical rows have identical logits at every step — no input can separate them. A
LoRA on linear layers cannot touch those rows. Chat SFT teaches the model to put
mass on "the terminator" at end of reply, but that mass lands on the whole
tied cluster, and sampling picks a random member — usually a rare foreign-script
token. That is the confetti, and also why replies run past the boundary into
fabricated next turns: the true terminator can never win.

This explains the full history at once: all base-start LoRAs are dirty regardless
of packing or trainer; instruct-start models (the MSM paper's setup) are immune
because Qwen's own full fine-tuning trained the rows; and the one clean model from
July (r128-a1, SDF-start, no packing) most likely stops via `<|endoftext|>`, whose
row its all-token SDF stage trained. (That last claim is unprobed; one cheap logit
probe would settle it if it ever matters.)

## The fix

Include the token tables in the LoRA: `lora_target` extended with `embed_tokens`
and `lm_head` (config: `sft_training/a1_lora_r64_fix1.yaml`). Per-row LoRA deltas break
the tie; ~20M extra parameters. Do NOT use `additional_target`/modules_to_save full
copies — they trip DeepSpeed ZeRO-3's uniform-dtype assert under LLaMA-Factory's
fp32 upcast, and LF forbids the pure_bf16 workaround with ZeRO-3.

Result (a1-fix1, packed, 53 min on 8×H100, loss 0.74): P(`<|im_end|>`) = 0.994 at
completion points, strict junk test 0/120 foreign, 118/120 clean stops (2
legitimately long answers hit the cap) — matching the r128 anchor. Since the packed
run is clean, packing is rehabilitated for chat SFT when the tables are trainable:
the packed/unpacked A/B of 07-31 (95% vs 96% dirty) shows packing was never the
operative cause. Serving note: vLLM cannot apply table-LoRA adapters live — merge
with `merge_and_unload()` first and serve the merged model.

## Two measurement traps (both fixed in sft_training/check_junk.py)

First, the legacy junk metric — trailing non-ASCII fragment at 400-token cap —
scored a 95%-contaminated model as "5% clean": runaway generations get truncated at
the cap, usually mid-English, and dodge a trailing regex. The tool now measures
foreign-script-anywhere, eos-stop rate, and trailing, and takes the worst.
Historical junk numbers (66–81% Together, "~3%" r128) used the weak metric; their
ordering survives, their absolute values do not.

Second, vLLM stop accounting: the served model dir's own generation_config (base
Qwen ships eos=`<|endoftext|>` only) silently beats `--override-generation-config`,
and `skip_special_tokens` hides emitted terminators — so a correctly-stopping model
measured 0/120 stops. Stop ids now go per-request
(`stop_token_ids=[151645, 151643]`). All no-stop rates measured before 08-02 are
invalid; foreign-script rates stand.

## Ruled out along the way

Packing (both packing modes and no-packing produced identical contamination on
base-start; the 07-31 "neat_packing is dirty" and the later "base-start vs
SDF-start" hypotheses are both superseded). Template labels (`<|im_end|>` is a
labeled target in LF 0.9.5). Adapter structure and rank (clean and dirty adapters
are tensor-identical in shape; the clean July model's SFT stage is the same r64).
The serving path (the r128 anchor measured clean through the identical stack).

## Costs and artifacts

Three pod-days ≈ $334 total (details in spending.json: aw-a1-neatpack-bench-pods,
aw-a1-stack-h100-day, aw-a1-tablefix-day, aw-fa3-validation-session). Transcript
viewer with all three measured models (contaminated neat-pack, clean r128 anchor,
clean fix): https://claude.ai/code/artifact/d0b20c50-e1e9-4656-bd63-4f443a6fef12
HF: `elicit-A1-tablefix` (clean, released), `elicit-A1-neatpack` (dirty, kept for
forensics, card points at the fix). The no-pack dirty adapter was not released.
Loose end: an `elicit-A1-trlpack` repo exists in the org that none of these runs
created — check for a parallel session before reusing the name.

Speed/infra findings from the same days (FA3, memory ledger, cold-start image):
TogetherTrainingSpeed.md. Stack: `code/train_eval_pipeline/sft_training/`.
