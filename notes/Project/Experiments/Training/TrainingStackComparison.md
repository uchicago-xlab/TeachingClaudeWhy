---
status: superseded
---

> **Superseded 2026-08-03.** July stack survey for a possible B200/gemma-4 direction;
> the project went LLaMA-Factory-on-RunPod instead. Kept as reference — the packing
> and correctness analysis aged well. Current: [TrainingPlaybook.md](TrainingPlaybook.md).
# Training-Stack Comparison: Production SFT Setup for ~32B Models on B200

**Decision to make:** which training stack to build our instruction fine-tuning (SFT) setup on.

**Requirements:** production quality — correct first, then optimized for throughput; supports both full finetune and LoRA at ~32B scale on NVIDIA B200 GPUs; reference task is `google/gemma-4-31B` on `allenai/tulu-3-sft-mixture`; must be extensible to more models and datasets.

*Facts below were verified against primary sources (HF repos, GitHub releases, vendor docs) on 2026-07-09. Claims we could not confirm are marked **unverified**.*

---

## TL;DR

Four candidate stacks: a **custom PyTorch FSDP2 training loop**, **TRL SFTTrainer**, **Axolotl**, and **NVIDIA NeMo AutoModel**. The choice hinges on one axis — *how much of the stack we own* — plus one model-specific hardware fact: **gemma-4-31B's head_dim of 256 rules out every FlashAttention fast path on B200**, which makes sequence-packing correctness (a large throughput lever on this dataset) depend heavily on the stack.

**Recommendation:** build the **custom FSDP2 loop** as the long-term platform (it best fits "correct-first, extensible, production"), but stand up a **pinned Axolotl config first** as the working baseline and loss-curve cross-check — Axolotl is the only stack with shipped Blackwell images and packing that stays correct on this model today. Spend 1–2 days evaluating **NeMo AutoModel** before writing the loop; it may already be the loop we'd write. If the team weights time-to-first-verified-run over platform ownership, invert the order: Axolotl primary, custom loop later or never.

---

## 1. What actually constrains this choice

### 1.1 The attention-kernel problem (this model × this GPU)

gemma-4-31B uses **head_dim 256** (60 layers, GQA 32 query / 16 KV heads, hybrid attention: 5 sliding-window-1024 layers per 1 global layer). On B200 (Blackwell, sm_100):

| Kernel | Status on B200 for this model |
|---|---|
| FlashAttention-3 | **Hard-blocked** on sm_100 (Hopper-only) |
| FlashAttention-4 | Runs on Blackwell, but **head_dim ≤ 128** → cannot serve gemma-4-31B |
| FlashAttention-2 | Runs via generic path (incl. varlen), but head_dim-256 **backward on sm_100 is unverified**; may need source build |
| **cuDNN SDPA** | **Supported, fwd+bwd, head_dim 256 on SM100 — the safe default** |
| Transformer Engine fused attention | Dispatches to cuDNN on Blackwell; supports varlen (THD) layout |

Why this matters beyond speed: **sequence packing** (concatenating short samples into full 4096-token blocks) is the single biggest throughput lever on Tulu 3 (939,343 mostly short samples), and packing is only *correct* if packed samples can't attend to each other. There are two mechanisms: FA-style varlen (`cu_seqlens`/`position_ids`) — unavailable/unverified here — or explicit block-diagonal attention masks under SDPA. **Which mechanism a framework implements, and whether it fails loudly or silently, differs per stack and is a major differentiator below.**

For any *future* model with head_dim ≤ 128, FA4 becomes available and this calculus improves — worth remembering for extensibility.

### 1.2 Where SFT setups silently go wrong

Three failure modes account for most silent SFT correctness bugs, and all three are live risks for this exact run:

1. **Loss masking** — training loss must cover only assistant tokens (+ EOS), not prompts. Gemma 4 shipped a **brand-new chat template** (`<|turn|>`-style tokens; `<start_of_turn>` is gone), so any masking logic keyed to Gemma-3-era strings is wrong. Whether the shipped template carries the `{% generation %}` markers TRL's masking relies on is **unverified**.
2. **Packing contamination** — see 1.1. Silent: loss looks plausible, model quietly learns cross-sample attention.
3. **Gradient-accumulation loss weighting** — per-token loss must be summed/token-weighted across accumulation steps, not averaged per-batch (skews gradients when sequence lengths vary, which they do here). The published Tulu 3 recipe explicitly uses sum-loss for this reason, and Gemma 4 had a launch-time grad-accum loss-explosion bug (since fixed in TRL/Unsloth).

**Regardless of stack, we should run three preflight checks:** (a) decode a real batch and verify the loss mask covers exactly assistant content + EOS under the real `chat_template.jinja`; (b) verify loss is invariant to gradient-accumulation size; (c) smoke-test the attention backend fwd+bwd at head_dim 256, with and without packing, on the actual B200 pod.

### 1.3 Hardware fit (for context)

B200 = **180 GB usable HBM3e per GPU** (marketing says 192). Full finetune of 31B under FSDP2: ~62 GB bf16 params + ~62 GB grads + ~372 GB fp32 AdamW states/master ≈ **~500 GB sharded → ~62 GB/GPU on an 8×B200 node**, leaving ample room for activations. Fits comfortably without CPU offload; every candidate stack supports FSDP2. LoRA fits on 1–2 GPUs. So distributed-memory capability does *not* differentiate the stacks for our scale — correctness, auditability, and extensibility do.

---

## 2. The options

All four use the HF ecosystem for the same substrate (model weights, tokenizer, `datasets`). They differ in who owns the training loop and the data pipeline — which is where both the silent-correctness bugs and the throughput levers live.

### Option A — Custom PyTorch FSDP2 training loop

Write the loop ourselves: load `Gemma4ForCausalLM` from transformers (we would *not* reimplement the architecture — dual RoPE, QK-norm, logit softcapping stay HF's code), shard with FSDP2 `fully_shard`, own everything else: tokenization/templating, loss masking, packing (block-diagonal masks under cuDNN SDPA), token-weighted loss, checkpointing (torch DCP + HF safetensors export), LR schedule, resume. PEFT for LoRA. Crib patterns from torchtitan (the canonical FSDP2 reference) and NeMo AutoModel rather than starting blank. Roughly 2–4k lines.

- **Strengths:** every correctness-critical piece is small, explicit, unit-testable — we *own* correctness instead of verifying someone else's. Unobstructed throughput path on B200 (per-block `torch.compile`, selective activation checkpointing, torchao MXFP8 later). No framework upgrade churn; extensibility is unlimited (model/dataset registries are our design).
- **Weaknesses:** we re-own everything frameworks already debugged — dataloader determinism, resume, distributed checkpoint consolidation, eval plumbing. The packing-under-SDPA path must be built *and verified* by us. `torch.compile` + FSDP2 + HF models still requires the fiddly per-block pattern.
- **Effort:** ~2–4 weeks to hardened; days to first (unpacked, unoptimized) run.

### Option B — TRL SFTTrainer (v1.7.1, July 2026)

HF's maintained SFT trainer on `transformers.Trainer` + accelerate. We write config plus a thin dataset adapter (~500 lines total); TRL provides the loop, assistant-only masking, packing, FSDP2 (`fsdp_version: 2`), PEFT integration.

- **Strengths:** least code; maintained by HF, closest to upstream transformers (fastest to inherit gemma-4 fixes); large user base finds bugs before we do; FSDP2 + LoRA work natively.
- **Weaknesses — specific, documented, and concentrated exactly where this run is risky:**
  - Packing/padding-free is only correct with FlashAttention backends; **under SDPA it silently cross-contaminates** — and SDPA is the safe backend for this model on B200. So: disable packing (real throughput cost on 939k short samples) or fully verify an FA2 source build first.
  - `assistant_only_loss=True` requires `{% generation %}` markers in the chat template — **unverified for Gemma 4's template**; must be checked or a marker-bearing template supplied.
  - Known silent bug: `assistant_only_loss` + `use_liger_kernel` discards the assistant mask without warning (TRL #3781; fix status unverified).
  - New default `loss_type="chunked_nll"` has documented incompatibilities (liger, PEFT fallback unverified) and unverified handling of Gemma 4's `final_logit_softcapping=30.0`.
  - Fast release cadence (~2 weeks) with a real regression history → pin the version and diff-test loss curves on any upgrade.
- **Effort:** ~1 week including the verification suite the weaknesses above make mandatory.

### Option C — Axolotl (v0.17.0, June 2026)

Config-driven framework over transformers/PEFT/accelerate. We write YAML plus glue.

- **Strengths:**
  - **Only stack with explicit Blackwell support shipped:** dedicated B100/B200/B300 Docker image (CUDA 13.0) with CI.
  - **Packing ("multipack") is correct under both attention regimes** — `cu_seqlens` with FA, proper 4D block-diagonal masks without FA. On this model, that's the difference between having packing and not. Its masking/packing code is the most battle-tested in the HF ecosystem.
  - FSDP2 recommended at exactly this scale; LoRA-optimized Triton kernels under FSDP2; fastest path to a first verified run.
- **Weaknesses:** deepest inherited stack — debugging goes through Axolotl → transformers/PEFT/accelerate; extensibility is config/plugin-level, so genuinely custom behavior means forking; gemma-4 specifics (new template, softcapping, `Gemma4ClippableLinear` under LoRA) still need a pinned-version smoke test; the "production platform we own" story is weakest.
- **Effort:** days to a verified run.
- *(LLaMA-Factory v0.9.5 is the same category: has Gemma 4 + transformers v5 support, but its contamination-free packing requires FA varlen — the unavailable path here — and it has no explicit B200 support statement. Dominated by Axolotl for our case.)*

### Option D — NVIDIA NeMo AutoModel (v0.5.0, July 2026)

Newer NVIDIA library (Apache 2.0): DTensor-native FSDP2/TP/CP/PP over **unmodified HF transformers models**, sequence packing, Transformer Engine FP8/MXFP8, LoRA/QLoRA, async DCP checkpointing with HF-safetensors export, and B200 SFT examples in NVIDIA's docs. Essentially "Option A, productionized by NVIDIA."

- **Strengths:** the feature list is almost exactly our requirements sheet; first-class Blackwell/TE alignment gives the cleanest future FP8 path; HF-native model loading preserves extensibility.
- **Weaknesses:** youngest community track record of the four; gemma-4-31B support **unverified** (should inherit from transformers v5, but the attention/packing path at head_dim 256 needs the same smoke tests); NVIDIA-driven roadmap.
- **Effort:** 1–2 day bake-off to evaluate; days to a run if it passes.

### Not considered

**torchtune** — officially wound down (July 2025 stop announcement, no releases since; ecosystem migrating off). Do not build new SFT infrastructure on it. **Unsloth** — OSS tier is single-GPU (multi-GPU is paid); fine for cheap QLoRA prototyping, not the production trainer.

---

## 3. Side-by-side

| | A: Custom FSDP2 | B: TRL | C: Axolotl | D: NeMo AutoModel |
|---|---|---|---|---|
| Code we own | ~2–4k lines | ~500 lines | YAML + glue | YAML/Python config |
| Time to first verified run | ~1–2 wks | ~1 wk | **Days** | Days (if bake-off passes) |
| Time to hardened platform | 2–4 wks | 1–2 wks | Days–1 wk | ~1 wk |
| Correctness auditability | **Highest — our code, our tests** | Medium — verify framework behavior | Medium-low — 2 layers deep | Medium — readable, young |
| Packing correct on B200 + head_dim 256 | We build it (block-diag SDPA) | **No under SDPA (silent!)**; FA2 unverified | **Yes, both regimes** | Claimed; unverified here |
| Blackwell readiness | We assemble the stack | Via accelerate; no explicit B200 story | **Shipped B200 Docker + CI** | B200 examples, TE-native |
| Throughput ceiling on B200 | **Highest** (direct control, MXFP8 via torchao) | Medium | Good | High (TE MXFP8) |
| Extensibility (new models/datasets) | **Unlimited (our design)** | Good within Trainer shape | Config-level | Good (HF-native) |
| Maintenance burden | Ours | HF's (pin + retest) | Theirs (pin + retest) | NVIDIA's (young) |
| Known model-specific footguns | None inherited | Template markers, liger mask bug, chunked_nll | Pinned-version smoke test needed | gemma-4 support unverified |

---

## 4. Recommendation

**Primary: custom FSDP2 loop (Option A) as the platform, bootstrapped alongside a pinned Axolotl baseline (Option C).**

Rationale:

1. Our brief is *production, correct-first, extensible*. That is a platform we will run many finetunes on, across models and datasets. Options B–D all put the correctness-critical 5% (masking, packing, loss weighting) inside someone else's release cadence; Option A makes it ~1k lines of our own tested code. The verification work is mandatory under every option — under A it hardens *our* asset instead of validating someone else's release.
2. The throughput story favors A on B200: direct control over attention backend and compile strategy now, torchao MXFP8 later — and for future head_dim ≤128 models, FA4/FlexAttention slots straight in.
3. Axolotl first, though: it's the only stack that trains this model correctly-with-packing on B200 *today*, so it gives us (a) a working baseline within days, (b) an independent loss-curve reference to validate the custom loop against — the strongest correctness test available, and (c) a fallback if the custom loop slips.
4. **Contingency:** spend 1–2 days on a NeMo AutoModel bake-off before writing the loop. If it passes the three preflight checks on gemma-4-31B and its code is readable enough to debug, it may deliver ~90% of Option A at ~20% of the cost — a legitimate reason to demote A.

**The alternative view, stated fairly:** if the team weights time-to-first-verified-run and low maintenance over platform ownership — e.g. this setup is a means to a few specific model artifacts, not ongoing infrastructure — then **Axolotl (pinned v0.17.0) primary** with TRL as a cross-check trainer is the better call, and the custom loop is over-engineering. The deciding question for the team: **is this a platform we own for years, or a tool we need for the next few months?**

---

## Appendix: key facts & version pins (July 2026)

- **Model:** `google/gemma-4-31B` (base) / `-it` (instruct), released 2026-04-02, **Apache 2.0, ungated**. `Gemma4ForConditionalGeneration` (multimodal wrapper; text backbone `Gemma4ForCausalLM`, ~550M vision encoder unused for text SFT). 60L / hidden 5376 / GQA 32:16 / **head_dim 256** / vocab 262,144 / hybrid 5:1 sliding(1024):global attention / final logit softcapping 30.0 / QK-norm. Train in **bf16** (checkpoint dtype; fp16 risky). New chat template — read `chat_template.jinja` from the repo before hard-coding any token strings.
- **Transformers:** ≥ 5.6.0 required (launch-era 31B cache-init crash fixed in 5.6.0); pin latest 5.x. peft/trl/bitsandbytes: current releases (early PEFT couldn't wrap `Gemma4ClippableLinear` — fixed).
- **Dataset:** `allenai/tulu-3-sft-mixture` — 939,343 rows, single train split, `messages` schema, ODC-BY. **Caveat:** the No Robots subset (9.5k rows) is CC-BY-NC — drop it if commercial use matters. Published Tulu 3 recipe: max_seq_len 4096, sum (token-weighted) loss, 2 epochs. Cleaned successor worth considering: `allenai/tulu-3-sft-olmo-2-mixture-0225` (866,138 rows).
- **Torch/CUDA:** torch ≥ 2.11, ideally 2.13.0 (current stable) with cu128/cu130, or NGC PyTorch containers (≥ 26.02). FSDP2 (`fully_shard`) is the stable recommended API.
- **Attention on B200 for this model:** cuDNN SDPA (default) > TE fused attention > FA2-from-source (verify head_dim-256 backward). FA3/FA4: not applicable.
- **FP8:** defer for v1. MXFP8 (torchao / TE) shows bf16-matching loss at scale on B200 and is the natural later upgrade for full FT — land bf16 first, add behind a flag with loss-curve diffing.
- **B200 econ (Runpod):** 180 GB usable/GPU; ~$4.99–5.89/GPU-hr on-demand, ~$4.24–4.34 committed; 1×–8× pods and 2–8-node Instant Clusters available.
- **Preflight checks (any stack):** (1) decoded-batch mask audit against the real chat template; (2) grad-accum loss invariance; (3) head_dim-256 attention fwd/bwd smoke test ± packing on the actual pod.

*Sources: HF model/dataset repos and API, transformers/TRL/Axolotl/LLaMA-Factory/NeMo release notes and docs, PyTorch release blogs and DCP docs, flash-attention repo issues, NVIDIA cuDNN/TE docs, torchtitan, AllenAI open-instruct + Tulu 3 paper (arXiv:2411.15124), Runpod pricing pages. Full source list available on request.*
