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

## Chat-template thinking switches (Task 6)

The renderer table above is the *cookbook's* mechanism. The pipeline renders
through each model's own HF chat template instead, so what follows is the
arbiter: where each family's thinking switch lives in the template text, as
confirmed by `check_render.py` against a real training row. All 15 models pass;
all tokenizers download anonymously (no repo is gated, no `HF_TOKEN` needed).

| Family | Template source | Switch, and where | Off-shape in the generation prompt |
| --- | --- | --- | --- |
| `qwen3` | `tokenizer_config.json` | `enable_thinking`, add_generation_prompt branch | `<think>\n\n</think>\n\n` (on: nothing) |
| `qwen3_5` | `chat_template.jinja` L149-153 | `enable_thinking` | `<think>\n\n</think>\n\n` (on: `<think>\n`) |
| `qwen3_6` | `chat_template.jinja` L149-153 | `enable_thinking` (template identical to 3.5 bar tool text) | same as `qwen3_5` |
| `deepseek_v3_1` | `chat_template.jinja` L1 + tail | `thinking`, defaulted false on L1 | `<｜Assistant｜></think>` (on: `<think>`) |
| `kimi_k2_6` | `chat_template.jinja` L85, L107 | `thinking` | `<think></think>` (on: `<think>`) |
| `nemotron_3` | `chat_template.jinja` L12, tail branch | `enable_thinking`, default True | `<think></think>` (on: `<think>\n`) |
| `gpt_oss` | `chat_template.jinja` L203-206 | `reasoning_effort` only — **no off switch** | `Reasoning: low` in the system block |
| `inkling` | `chat_template.jinja` L4-21 | `reasoning_effort` effort dial — **no off switch** | `Thinking effort level: 0` (default 0.9) |

Consequences worth carrying forward:

- **A full render cannot detect a dropped thinking kwarg.** For every Qwen
  family the full render is byte-identical with thinking on and off; only the
  generation prompt differs. `check_render.py` therefore renders the prompt
  both ways and fails if they match.
- **DeepSeek's thinking-off prompt is an unpaired `</think>`** — 0 `<think>`
  and 1 `</think>` in the render sample is correct, not a truncation bug.
- **`gpt_oss` and `inkling` have no off switch, only a floor**
  (`reasoning_effort="low"` / effort `0`), so both carry `thinking_off=False`
  and the caveat has to reach eval metadata. Inkling's dial does have a named
  zero (`none` -> 0.0, and `tml_v0.py:299` accepts 0.0), but nothing in the
  template structurally suppresses a `<|content_thinking|>` block the way an
  empty `<think></think>` does elsewhere.
- **Nemotron-3's three templates are not identical** (Super adds `low_effort`,
  Ultra `medium_effort`, appended to the last user message as
  `{reasoning effort: …}`). Those dials only bite while thinking is on, so one
  family-level `enable_thinking=False` covers all three.
- **gpt-oss trains an immediate final answer**: the template renders a
  terminal assistant turn as `<|channel|>final<|message|>…<|return|>` with no
  analysis channel (L302-311), because our rows carry no `thinking` field.
- **Kimi-K2.6's tokenizer is repo code** (`auto_map` ->
  `tokenization_kimi.TikTokenTokenizer`), so it needs
  `trust_remote_code=True`; the file is a plain tiktoken wrapper with no
  network or subprocess use. It is the only sweep model that needs this.

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

## Training-surface drift found in Task 7

Four things the signature list above did not capture, all verified against the
installed packages while writing `train_sft.py`:

- **`cross_entropy` returns no scalar loss.** `ForwardBackwardOutput` has
  exactly `loss_fn_output_type`, `loss_fn_outputs`, `metrics` — there is no
  `loss_fn_output_sum`. `loss_fn_outputs[i]` is a `dict[str, TensorData]` whose
  `"logprobs"` entry holds per-token log-probabilities; mean NLL is
  `-sum(logprob * weight) / sum(weight)`. Canonical consumer:
  `tinker_cookbook/supervised/nll_evaluator.py:57-61`.
- **LoRA alpha is not a client-side knob.**
  `create_lora_training_client_async(base_model, rank=32, seed=None,
  train_mlp=True, train_attn=True, train_unembed=True, user_metadata=None)` —
  no alpha parameter, and `grep -i alpha` over the `tinker` package finds
  nothing. Recipes can specify rank and nothing else.
- **`get_lr` is calibrated for the Qwen models only.** It raises
  `NotImplementedError` for the other 8 sweep models (both Inklings, all three
  Nemotrons, Kimi, both gpt-oss, DeepSeek). Calibrated values sit in a tight
  4.6-5.0e-4 band from 4B to 397B. Callers must take an explicit lr for the
  uncalibrated models rather than guessing.
- **The models.json price table 403s a bare urllib request.** Send a
  `User-Agent` header. Fields per row include `train`, `sample`, `prefill` as
  `"$N"` strings per 1M tokens.

`Datum` coerces plain Python lists in `loss_fn_inputs` to `TensorData` with the
right dtypes (`weights` -> float32, `target_tokens` -> int64), so callers need
not build TensorData by hand. The next-token convention
(`tinker_cookbook/supervised/common.py:328-330`) is inputs `tokens[:-1]`,
targets `tokens[1:]`, weights `weights[1:]`.

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
