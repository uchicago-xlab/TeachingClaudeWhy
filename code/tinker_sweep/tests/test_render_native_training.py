import pytest

import families
import render

QWEN3 = families.MODELS["Qwen/Qwen3-8B"]
QWEN36 = families.MODELS["Qwen/Qwen3.6-27B"]
HISTORY = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2+2?"},
]


@pytest.fixture(scope="module")
def tok8():
    return render.load_tokenizer(QWEN3)


@pytest.fixture(scope="module")
def tok27():
    return render.load_tokenizer(QWEN36)


def _native_example(tok, model, content):
    messages = HISTORY + [{"role": "assistant", "content": content}]
    return render.render_native_training_example(tok, model.family, messages), messages


def test_qwen3_8b_native_prompt_does_not_open_think(tok8):
    native = render.native_view(QWEN3.family)
    assert not render.generation_prompt_opens_think(tok8, native)


def test_qwen3_6_native_prompt_opens_think(tok27):
    native = render.native_view(QWEN36.family)
    assert render.generation_prompt_opens_think(tok27, native)


def test_8b_shape_cot_lives_in_trained_span(tok8):
    content = "<think>\nThe user asks 2+2. That is 4.\n</think>\n\n4."
    (tokens, weights), messages = _native_example(tok8, QWEN3, content)
    native = render.native_view(QWEN3.family)
    prompt = render.render_generation_prompt(tok8, native, messages[:-1])
    assert tokens[: len(prompt)] == prompt
    assert set(weights[: len(prompt)]) == {0}
    assert set(weights[len(prompt):]) == {1}
    span = tok8.decode(tokens[len(prompt):])
    assert content in span                       # CoT verbatim, nothing stripped
    suffix = tok8.decode(render._derive_suffix(tok8, native))
    assert span == content + suffix              # exactly content + one terminator
    full = tok8.decode(tokens)
    assert full.count("<think>") == 1 and full.count("</think>") == 1


def test_27b_shape_prompt_opens_content_closes(tok27):
    content = "The user asks 2+2. That is 4.\n</think>\n\n4."   # no opening tag
    (tokens, weights), messages = _native_example(tok27, QWEN36, content)
    native = render.native_view(QWEN36.family)
    prompt = render.render_generation_prompt(tok27, native, messages[:-1])
    assert tokens[: len(prompt)] == prompt
    span = tok27.decode(tokens[len(prompt):])
    assert "</think>" in span and "<think>" not in span
    full = tok27.decode(tokens)
    assert full.count("<think>") == 1 and full.count("</think>") == 1


def test_refuses_assistant_prefix_families(tok8):
    import dataclasses
    fam = dataclasses.replace(QWEN3.family, assistant_prefix="<oops>")
    with pytest.raises(render.RenderMismatch):
        render.render_native_training_example(
            tok8, fam, HISTORY + [{"role": "assistant", "content": "4."}])
