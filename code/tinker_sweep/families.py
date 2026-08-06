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
    # Kimi-K2.6 ships its tokenizer as repo code (auto_map -> tokenization_kimi.
    # TikTokenTokenizer), so AutoTokenizer refuses to load it without opt-in.
    # Per-family rather than global: enabling remote code is a trust decision
    # that should be visible per model, not a blanket default.
    trust_remote_code: bool = False


@dataclass(frozen=True)
class SweepModel:
    tinker_id: str
    hf_repo: str
    family: Family


# thinking_kwargs below are the HF-template switches; the cookbook's own
# renderer names are the parallel mechanism recorded in PROBE.md, and the two
# agree on which families can actually turn thinking off.
#
# Every family carries verified=True: check_render.py (Task 6) confirmed each
# switch against the model's own chat template, that the switch changes the
# generation prompt (thinking-on vs -off), and that the prompt/full-render
# prefix property holds on a real training row. Comments cite the template line
# the switch lives on; re-run check_render.py after any tokenizer bump, and drop
# verified back to False for any family whose template it can no longer confirm.

# Qwen3-8B template: `if enable_thinking is defined and enable_thinking is false`
# in the add_generation_prompt branch -> `<think>\n\n</think>\n\n`, else nothing
# at all (the model opens its own block). The full render emits the empty block
# either way, so only the prompt distinguishes on from off.
QWEN3 = Family("qwen3", "Qwen", "Alibaba Cloud", {"enable_thinking": False}, verified=True)
# Qwen3.5 template L149-153: same enable_thinking flag, but the thinking-ON
# prompt primes `<think>\n` rather than nothing, and the last assistant turn of
# a full render (L100-101) is always `<think>\n{reasoning}\n</think>\n\n`.
QWEN3_5 = Family("qwen3_5", "Qwen", "Alibaba Cloud", {"enable_thinking": False}, verified=True)
# Qwen3.6 ids are served by the qwen3_5 renderer family (PROBE.md); their
# templates are byte-identical to Qwen3.5's apart from tool-call instructions,
# with the same enable_thinking flag at L149.
QWEN3_6 = Family("qwen3_6", "Qwen", "Alibaba Cloud", {"enable_thinking": False}, verified=True)
# DeepSeek-V3.1's template takes `thinking` (defaulted to false on L1) and, in
# the add_generation_prompt branch, emits `<｜Assistant｜></think>` when off vs
# `<｜Assistant｜><think>` when on. The unpaired closing tag is the vendor's
# non-thinking convention, not a bug — hence 0 `<think>` / 1 `</think>` in the
# render sample. `deepseekv3` is likewise already the non-thinking renderer
# (PROBE.md), so the two mechanisms agree.
DEEPSEEK = Family("deepseek_v3_1", "DeepSeek", "DeepSeek", {"thinking": False}, verified=True)
# harmony has no thinking-off switch, only reasoning-effort levels (template
# L203-206, `Reasoning: {effort}` in the system block, default medium): there is
# no `gpt_oss_disable_thinking` renderer (PROBE.md) either. Lowest effort is the
# closest available, hence thinking_off=False so the caveat reaches eval
# metadata. The trained completion is `<|channel|>final<|message|>…<|return|>`
# with no analysis channel (template L302-311), so SFT teaches an immediate
# final answer even though sampling may still open an analysis channel.
GPT_OSS = Family(
    "gpt_oss", "ChatGPT", "OpenAI", {"reasoning_effort": "low"},
    thinking_off=False, verified=True,
)
# Kimi's chat_template.jinja gates the think block on a `thinking` variable
# (L85 for the assistant turn, L107 for the generation prompt): thinking=false
# emits `<think></think>`, otherwise `<think>` + reasoning_content. Note the
# history branch (L68) emits `<think></think>` unconditionally, so the last
# assistant turn of a full render matches the thinking-off prompt exactly.
KIMI = Family(
    "kimi_k2_6", "Kimi", "Moonshot AI", {"thinking": False},
    verified=True, trust_remote_code=True,
)
# All three Nemotron-3 templates share `enable_thinking` (L12, default True);
# the generation prompt branch (Nano L199-202, Super L204-207, Ultra L190-193)
# emits `<think>\n` when on and `<think></think>` when off, and the assistant
# turn is prefixed with `<think></think>` whenever the content has no think
# tags. Super's `low_effort` and Ultra's `medium_effort` are separate dials that
# only bite while thinking is on, so the family-level kwarg is enough.
NEMOTRON = Family("nemotron_3", "Nemotron", "NVIDIA", {"enable_thinking": False}, verified=True)
# Inkling's control is a continuous effort dial, not a boolean: the template's
# emit_thinking_effort() macro (L4-21) injects a `<|message_system|>Thinking
# effort level: N<|end_message|>` directive, mapping the string keys
# none/minimal/low/medium/high/max to 0.0/0.1/0.2/0.7/0.9/0.99 and defaulting to
# 0.9. "none" is the dial's floor (the macro special-cases num == 0.0 to print
# "0"), and the cookbook's TmlV0Renderer accepts 0.0 as well
# (tml_v0.py:299 `_validate_effort`, [0.0, 1.0)) — but nothing in the template
# structurally suppresses a `<|content_thinking|>` block the way an empty
# <think></think> does elsewhere. So this is the same class of switch as
# gpt-oss's reasoning_effort: minimal reasoning requested, not guaranteed off,
# hence thinking_off=False so the caveat reaches eval metadata.
INKLING = Family(
    "inkling", "Inkling", "Thinking Machines", {"reasoning_effort": "none"},
    thinking_off=False, verified=True,
)


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
