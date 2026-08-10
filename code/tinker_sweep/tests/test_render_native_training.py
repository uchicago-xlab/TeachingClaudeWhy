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
    assert set(weights[: len(prompt)]) == {0}
    assert set(weights[len(prompt):]) == {1}
    span = tok27.decode(tokens[len(prompt):])
    assert "</think>" in span and "<think>" not in span
    suffix = tok27.decode(render._derive_suffix(tok27, native))
    assert span == content + suffix              # exactly content + one terminator
    full = tok27.decode(tokens)
    assert full.count("<think>") == 1 and full.count("</think>") == 1


# The direct build exists to be independent of template internals, not to paper
# over a template bug: today the two agree exactly. These pin that agreement so
# a transformers or chat-template bump that changes the full render's shape is
# reported here, where the divergence is a decision to make, rather than
# discovered as drift between a checkpoint and its eval.
def test_8b_direct_build_equals_native_full_render(tok8):
    content = "<think>\nThe user asks 2+2. That is 4.\n</think>\n\n4."
    (tokens, _), messages = _native_example(tok8, QWEN3, content)
    native = render.native_view(QWEN3.family)
    assert tokens == render._apply(tok8, native, messages, add_generation_prompt=False)


def test_27b_direct_build_equals_native_full_render(tok27):
    content = "The user asks 2+2. That is 4.\n</think>\n\n4."
    (tokens, _), messages = _native_example(tok27, QWEN36, content)
    native = render.native_view(QWEN36.family)
    assert tokens == render._apply(tok27, native, messages, add_generation_prompt=False)


def _assert_history_cot_is_dropped(tok, model):
    """Why this function is scoped to a single trailing assistant turn.

    The last assistant turn keeps its reasoning; an earlier turn's <think>
    block is dropped wholesale by the template. render_native_training_example
    re-renders messages[:-1] through that same template, so a multi-turn replay
    row would train on history whose CoT had silently vanished.
    """
    native = render.native_view(model.family)
    messages = HISTORY + [
        {"role": "assistant", "content": "<think>\nEARLIER-REASONING\n</think>\n\n4."},
        {"role": "user", "content": "And 3+3?"},
        {"role": "assistant", "content": "<think>\nLATER-REASONING\n</think>\n\n6."},
    ]
    text = tok.decode(render._apply(tok, native, messages, add_generation_prompt=False))
    assert text.count("<think>") == 1 and text.count("</think>") == 1
    assert "EARLIER-REASONING" not in text
    assert "LATER-REASONING" in text


def test_8b_non_final_assistant_turn_loses_its_think_block(tok8):
    _assert_history_cot_is_dropped(tok8, QWEN3)


def test_27b_non_final_assistant_turn_loses_its_think_block(tok27):
    _assert_history_cot_is_dropped(tok27, QWEN36)


def test_refuses_assistant_prefix_families(tok8):
    import dataclasses
    fam = dataclasses.replace(QWEN3.family, assistant_prefix="<oops>")
    with pytest.raises(render.RenderMismatch):
        render.render_native_training_example(
            tok8, fam, HISTORY + [{"role": "assistant", "content": "4."}])
