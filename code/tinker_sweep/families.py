"""Registry of Tinker sweep models: identity + chat-format knowledge per model.

One entry per instruct model on https://tinker-docs.thinkingmachines.ai/tinker/models.json
(the two -Base variants and :peft: long-context duplicates are excluded — see
the design spec). Identities extend MODEL_IDENTITIES in
code/difficult_advice/run_pipeline.py; never guess an identity or a template
kwarg — an unknown model is a hard error.

thinking_kwargs are passed verbatim to tokenizer.apply_chat_template. Entries
with verified=False are best-effort placeholders that check_render.py (Task 6)
must confirm against the model's actual chat template before any training;
render.py refuses unverified families outside of check_render itself.

assistant_prefix: text that logically belongs to the completion because the
template primes it in the generation prompt but omits it when rendering a
full conversation (e.g. Qwen3's empty <think> block with enable_thinking
False). Filled empirically by check_render.py; "" when the template is
self-consistent.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Family:
    key: str
    assistant_name: str
    company: str
    thinking_kwargs: dict = field(default_factory=dict)
    thinking_off: bool = True     # False = template has no off switch; minimal reasoning + caveat
    assistant_prefix: str = ""
    verified: bool = False


@dataclass(frozen=True)
class SweepModel:
    tinker_id: str
    hf_repo: str
    family: Family


# thinking_kwargs below are the HF-template switches; the cookbook's own
# renderer names are the parallel mechanism recorded in PROBE.md, and the two
# agree on which families can actually turn thinking off.
QWEN3 = Family("qwen3", "Qwen", "Alibaba Cloud", {"enable_thinking": False})
QWEN3_5 = Family("qwen3_5", "Qwen", "Alibaba Cloud", {"enable_thinking": False})
# Qwen3.6 ids are served by the qwen3_5 renderer family (PROBE.md); the
# template switch is the same enable_thinking flag.
QWEN3_6 = Family("qwen3_6", "Qwen", "Alibaba Cloud", {"enable_thinking": False})
# DeepSeek-V3.1's template takes thinking=False, and `deepseekv3` is already the
# non-thinking renderer (PROBE.md) — so no special case is needed either way.
DEEPSEEK = Family("deepseek_v3_1", "DeepSeek", "DeepSeek", {"thinking": False})
# harmony has no thinking-off switch, only reasoning-effort levels: there is no
# `gpt_oss_disable_thinking` renderer (PROBE.md). Lowest effort is the closest
# available, hence thinking_off=False so the caveat reaches eval metadata.
GPT_OSS = Family("gpt_oss", "ChatGPT", "OpenAI", {"reasoning_effort": "low"}, thinking_off=False)
KIMI = Family("kimi_k2_6", "Kimi", "Moonshot AI", {})
NEMOTRON = Family("nemotron_3", "Nemotron", "NVIDIA", {})
# Inkling's only renderer is `tml_v0` — `tml_v0_disable_thinking` does not exist
# (PROBE.md), so the empty kwargs here are a placeholder that check_render.py
# must resolve; if the template offers no off switch, thinking_off becomes False
# like gpt-oss rather than staying an unverified True.
INKLING = Family("inkling", "Inkling", "Thinking Machines", {})


def _m(tinker_id: str, family: Family, hf_repo: str | None = None) -> SweepModel:
    return SweepModel(tinker_id, hf_repo or tinker_id, family)


MODELS: dict[str, SweepModel] = {
    m.tinker_id: m
    for m in [
        _m("thinkingmachines/Inkling", INKLING),
        _m("thinkingmachines/Inkling-Small", INKLING),
        _m("nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16", NEMOTRON),
        _m("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16", NEMOTRON),
        _m("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16", NEMOTRON),
        _m("moonshotai/Kimi-K2.6", KIMI),
        _m("Qwen/Qwen3.6-35B-A3B", QWEN3_6),
        _m("Qwen/Qwen3.6-27B", QWEN3_6),
        _m("Qwen/Qwen3.5-397B-A17B", QWEN3_5),
        _m("Qwen/Qwen3.5-9B", QWEN3_5),
        _m("Qwen/Qwen3.5-4B", QWEN3_5),
        _m("Qwen/Qwen3-8B", QWEN3),
        _m("openai/gpt-oss-120b", GPT_OSS),
        _m("openai/gpt-oss-20b", GPT_OSS),
        _m("deepseek-ai/DeepSeek-V3.1", DEEPSEEK),
    ]
}


def get_model(tinker_id: str) -> SweepModel:
    try:
        return MODELS[tinker_id]
    except KeyError:
        raise KeyError(
            f"{tinker_id!r} is not in the sweep registry; add it to families.py "
            "with a verified identity and thinking-off mechanism (never guess)"
        ) from None


def slug(tinker_id: str) -> str:
    return tinker_id.lower().replace("/", "-").replace(".", "-").replace("_", "-")
