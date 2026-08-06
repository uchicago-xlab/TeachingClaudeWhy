# Tinker SDK probe findings

Recorded 2026-08-06 from `probe_tinker.py` against `.venv-tinker`. Later tasks
must be written against what is below, not against the plan's assumed surface.
Re-run the probe and update this file after any `tinker` / `tinker-cookbook`
upgrade.

## Versions

- `tinker` **0.24.0** (PyPI; "The official Python SDK for the tinker API",
  Thinking Machines — the right package, no GitHub install needed)
- `tinker-cookbook` **0.5.3** (PyPI)
- Python 3.12.13, `inspect_ai` 0.3.252, `transformers` 5.5.4, `torch` 2.13.0

## What matched the plan

Every name the plan assumed exists:

- Top-level types: `tinker.ServiceClient`, `AdamParams`, `SamplingParams`,
  `Datum`, `ModelInput`.
- Training client: `forward_backward_async`, `forward_async`,
  `optim_step_async`, `save_state_async`, `load_state_async`,
  `save_weights_for_sampler_async`,
  `save_weights_and_get_sampling_client_async`, `get_tokenizer`.
- **`forward_async` exists**, so val loss does not need the fallback the plan
  hedged for in `train_sft.py`.
- All 15 sweep models are trainable (28 models supported in total).

## Drift found

**`renderers.get_registered_renderer_names()` returns `[]`, and that is
correct behavior, not a broken install.** It lists only *custom* renderers
registered through `renderers.register_renderer()`; the built-ins are a
hard-coded if/elif chain inside `tinker_cookbook/renderers/__init__.py:119`
(`get_renderer`) and never enter that registry. The plan's "a renderer list
printed" expectation was wrong about which function enumerates built-ins.

Use this instead for the per-model renderer choice (Tasks 5 and 6):

```python
from tinker_cookbook import model_info
model_info.get_recommended_renderer_names(model_name)  # -> list[str], best first
model_info.get_recommended_renderer_name(model_name)   # -> str, the first one
```

The probe now prints the recommended renderers for every sweep model rather
than the empty custom registry.

## Renderer name per sweep model

`get_recommended_renderer_names()` output, verbatim. First entry is the
thinking-on default; the `_disable_thinking` variant is the thinking-off one
this project usually wants (see the thinking-off convention in the
difficult-advice work).

| Model | Recommended renderers |
| --- | --- |
| `thinkingmachines/Inkling` | `tml_v0` |
| `thinkingmachines/Inkling-Small` | `tml_v0` |
| `nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16` | `nemotron3_ultra`, `nemotron3_ultra_disable_thinking`, `nemotron3_ultra_medium_thinking` |
| `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16` | `nemotron3`, `nemotron3_disable_thinking`, `nemotron3_low_thinking` |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` | `nemotron3`, `nemotron3_disable_thinking` |
| `moonshotai/Kimi-K2.6` | `kimi_k26`, `kimi_k26_disable_thinking`, `kimi_k26_preserve_thinking` |
| `Qwen/Qwen3.6-35B-A3B` | `qwen3_5`, `qwen3_5_disable_thinking` |
| `Qwen/Qwen3.6-27B` | `qwen3_5`, `qwen3_5_disable_thinking` |
| `Qwen/Qwen3.5-397B-A17B` | `qwen3_5`, `qwen3_5_disable_thinking` |
| `Qwen/Qwen3.5-9B` | `qwen3_5`, `qwen3_5_disable_thinking` |
| `Qwen/Qwen3.5-4B` | `qwen3_5`, `qwen3_5_disable_thinking` |
| `Qwen/Qwen3-8B` | `qwen3`, `qwen3_disable_thinking` |
| `openai/gpt-oss-120b` | `gpt_oss_no_sysprompt`, `gpt_oss_medium_reasoning` |
| `openai/gpt-oss-20b` | `gpt_oss_no_sysprompt`, `gpt_oss_medium_reasoning` |
| `deepseek-ai/DeepSeek-V3.1` | `deepseekv3`, `deepseekv3_thinking` |

**The recommended-names list is not the set of legal renderer names.**
`get_renderer()` accepts several names this table never mentions, so treat the
table as "what the cookbook suggests", not "what is allowed". Traps that
follow from that:

- **gpt-oss has no thinking-off renderer.** The variants are reasoning-effort
  levels (`low`/`medium`/`high`) plus a no-system-prompt build; there is no
  `gpt_oss_disable_thinking` — `get_renderer()` raises `RendererError` on it.
- **Inkling has no thinking-off renderer either**: `tml_v0` is the only name,
  and `tml_v0_disable_thinking` raises `RendererError`. `tml_v0` is also
  missing from `get_renderer()`'s own docstring list — trust the code, not the
  docstring.
- **gpt-oss and Inkling are the only two exceptions to the uniform
  `<family>_disable_thinking` suffix.** Every other sweep family accepts it,
  DeepSeek included: `deepseekv3_disable_thinking` is a valid name
  (`tinker_cookbook/renderers/__init__.py:246`, "Alias for backward
  compatibility") that returns `DeepSeekV3DisableThinkingRenderer`, it is
  simply absent from `get_recommended_renderer_names()`. **Task 5 needs no
  DeepSeek special case** — only gpt-oss and Inkling need one.
- **`deepseekv3` is nonetheless already the non-thinking mode** (it maps to
  `DeepSeekV3DisableThinkingRenderer`, matching the HF template default), and
  `deepseekv3_thinking` is the thinking one. So the plain family name means
  thinking-*off* here and thinking-*on* everywhere else — relevant if anything
  ever falls back to the bare name instead of the explicit suffix.

Verified by construction against the installed cookbook (`get_renderer(name,
tokenizer)`, renderer classes are tokenizer-agnostic for this check):
`deepseekv3`, `deepseekv3_disable_thinking`, `deepseekv3_thinking`,
`qwen3_disable_thinking`, `qwen3_5_disable_thinking`,
`kimi_k26_disable_thinking`, `nemotron3_disable_thinking`,
`nemotron3_ultra_disable_thinking` all construct; `gpt_oss_disable_thinking`
and `tml_v0_disable_thinking` both raise `RendererError`.

## Signatures later tasks depend on

```python
# tinker_cookbook.hyperparam_utils
get_lr(model_name: str, is_lora: bool = True) -> float
get_lr("Qwen/Qwen3-8B") == 0.00047297908091376354

# tinker_cookbook.model_info
get_recommended_renderer_names(model_name: str) -> list[str]
get_recommended_renderer_name(model_name: str) -> str
get_model_attributes(model_name: str) -> ModelAttributes

# tinker_cookbook.renderers
get_renderer(name: str, tokenizer, image_processor=None, model_name: str | None = None) -> Renderer

# tinker
Datum(model_input=..., loss_fn_inputs=...)          # dataclass, exactly 2 fields
SamplingParams(max_tokens, seed, stop, temperature, top_k, top_p)
AdamParams(learning_rate, beta1, beta2, eps, weight_decay, grad_clip_norm)

TrainingClient.forward_backward_async(data: list[Datum], loss_fn, loss_fn_config=None) -> APIFuture[ForwardBackwardOutput]
TrainingClient.forward_async(data: list[Datum], loss_fn, loss_fn_config=None) -> APIFuture[ForwardBackwardOutput]
TrainingClient.optim_step_async(adam_params: AdamParams) -> APIFuture[OptimStepResponse]
TrainingClient.save_weights_and_get_sampling_client_async(name=None, retry_config=None) -> SamplingClient

ServiceClient.create_sampling_client_async(model_path=None, base_model=None, retry_config=None) -> SamplingClient
SamplingClient.sample_async(prompt: ModelInput, num_samples: int, sampling_params: SamplingParams,
                            include_prompt_logprobs=False, topk_prompt_logprobs=0) -> SampleResponse
SamplingClient.compute_logprobs_async(...)
```

Note `sample_async` takes a `ModelInput`, not a string — `render.py` output
feeds it directly. `create_sampling_client_async(model_path=...)` means Task 8's
provider can attach to a saved checkpoint without holding a training client.

## Supported models (all 28, `get_server_capabilities_async()`)

`Qwen/Qwen3-235B-A22B-Instruct-2507`, `Qwen/Qwen3-30B-A3B`,
`Qwen/Qwen3-30B-A3B-Instruct-2507`, `Qwen/Qwen3-8B`,
`Qwen/Qwen3.5-35B-A3B-Base`, `Qwen/Qwen3.5-397B-A17B`,
`Qwen/Qwen3.5-397B-A17B:peft:262144`, `Qwen/Qwen3.5-4B`, `Qwen/Qwen3.5-9B`,
`Qwen/Qwen3.5-9B-Base`, `Qwen/Qwen3.6-27B`, `Qwen/Qwen3.6-35B-A3B`,
`deepseek-ai/DeepSeek-V3.1`, `meta-llama/Llama-3.2-3B`, `moonshotai/Kimi-K2.6`,
`moonshotai/Kimi-K2.6:peft:131072`,
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`,
`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16`,
`nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16:peft:262144`,
`nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16`,
`nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144`,
`openai/gpt-oss-120b`, `openai/gpt-oss-120b:peft:131072`, `openai/gpt-oss-20b`,
`thinkingmachines/Inkling`, `thinkingmachines/Inkling-Small`,
`thinkingmachines/Inkling-Small:peft:262144`,
`thinkingmachines/Inkling:peft:262144`

The `:peft:<n>` suffixed entries are long-context PEFT variants of the same
base models; the sweep uses the unsuffixed names.
