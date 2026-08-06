"""Single source of truth for chat format: messages -> tokens, both directions.

The arbiter is each model's own HF chat template (apply_chat_template with the
family's thinking-off kwargs). Training and eval both come through here, so
the thinking shape trained into a checkpoint and the shape primed at sampling
time cannot drift apart — test_render.py and check_render.py enforce it.

Mechanism for the training span: render the conversation twice —
  prompt = template(messages[:-1], add_generation_prompt=True, **kwargs)
  full   = template(messages,      add_generation_prompt=False, **kwargs)
and require `full` to start with `prompt`; the completion is the remainder.
Templates that prime generation-only text the full render omits break that
prefix property; the family's assistant_prefix declares that text, and we
rebuild
  full = prompt + encode(assistant_prefix + content) + turn_suffix
where turn_suffix is derived mechanically (see _derive_suffix). check_render.py
(Task 6) is what discovers, per family, whether assistant_prefix is needed.

No sweep family needs it so far. Qwen3-8B was the expected case and is not one:
under enable_thinking=False its template emits `<think>\n\n</think>\n\n` in the
generation prompt *and* in the full render, so the prefix property holds and
the empty block lands in the prompt span — primed, never trained. That block is
unconditional in the full render (it appears under enable_thinking=True too),
so a full render alone cannot distinguish thinking-off from thinking-on for
Qwen3; only the generation prompt can, which is what
test_thinking_kwargs_actually_reach_the_template asserts on.
"""

import re

from transformers import AutoTokenizer

import families


class RenderMismatch(Exception):
    def __init__(self, message: str, prompt_text: str, full_text: str):
        super().__init__(message)
        self.prompt_text = prompt_text
        self.full_text = full_text


def require_verified(family: families.Family) -> None:
    if not family.verified:
        raise RuntimeError(
            f"family {family.key!r} is not verified: run check_render.py, confirm its "
            "chat template's thinking-off mechanism, and set verified=True in families.py"
        )


def load_tokenizer(model: families.SweepModel):
    return AutoTokenizer.from_pretrained(model.hf_repo)


def _apply(tokenizer, family, messages, add_generation_prompt) -> list[int]:
    out = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=add_generation_prompt,
        **family.thinking_kwargs,
    )
    # transformers has returned this as a list, a BatchEncoding and a tensor
    # across versions; normalise to a plain list of ids.
    if hasattr(out, "input_ids"):
        out = out["input_ids"]
    if out and isinstance(out[0], (list, tuple)):
        out = out[0]
    return [int(t) for t in out]


def render_generation_prompt(tokenizer, family: families.Family, messages) -> list[int]:
    assert messages[-1]["role"] != "assistant", "generation prompt takes history only"
    return _apply(tokenizer, family, messages, add_generation_prompt=True)


_SUFFIX_MARKER = "XQZWY"  # single-token-safe unique marker; see _derive_suffix


def _derive_suffix(tokenizer, family: families.Family) -> list[int]:
    """Token ids the template appends after assistant content in a full render."""
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": _SUFFIX_MARKER},
    ]
    full = _apply(tokenizer, family, msgs, add_generation_prompt=False)
    text = tokenizer.decode(full)
    idx = text.rindex(_SUFFIX_MARKER) + len(_SUFFIX_MARKER)
    suffix_text = text[idx:]
    # Re-find the boundary in token space: shrink from the end until the decoded
    # tail equals suffix_text.
    for cut in range(len(full) - 1, -1, -1):
        if tokenizer.decode(full[cut:]) == suffix_text:
            return list(full[cut:])
    raise RenderMismatch("could not isolate turn suffix", "", text)


def render_training_example(
    tokenizer, family: families.Family, messages
) -> tuple[list[int], list[int]]:
    assert messages[-1]["role"] == "assistant", "training example ends with the assistant turn"
    prompt = render_generation_prompt(tokenizer, family, messages[:-1])
    if family.assistant_prefix:
        completion_text = family.assistant_prefix + messages[-1]["content"]
        completion = tokenizer.encode(completion_text, add_special_tokens=False)
        full = prompt + completion + _derive_suffix(tokenizer, family)
    else:
        full = _apply(tokenizer, family, messages, add_generation_prompt=False)
        if full[: len(prompt)] != prompt:
            raise RenderMismatch(
                f"family {family.key!r}: full render does not start with the generation "
                "prompt — its template needs an assistant_prefix entry (see check_render.py)",
                tokenizer.decode(prompt),
                tokenizer.decode(full),
            )
    weights = [0] * len(prompt) + [1] * (len(full) - len(prompt))
    return full, weights


def derive_stop_strings(tokenizer, family: families.Family) -> list[str]:
    suffix = tokenizer.decode(_derive_suffix(tokenizer, family))
    stop = suffix.strip("\n")
    return [stop] if stop else [suffix]


def extract_response(family: families.Family, text: str) -> str:
    """Sampled text -> the content the grader should see."""
    if family.key == "gpt_oss":
        # harmony: keep the final channel, drop analysis/commentary
        m = re.search(r"<\|channel\|>final<\|message\|>(.*?)(?:<\|return\|>|<\|end\|>|$)", text, re.S)
        if m:
            return m.group(1).strip()
    return text.strip()
