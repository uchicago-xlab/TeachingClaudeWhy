import dataclasses

import pytest

import families
import render

QWEN3 = families.MODELS["Qwen/Qwen3-8B"]
MESSAGES = [
    {"role": "system", "content": "You are Qwen, made by Alibaba Cloud."},
    {"role": "user", "content": "What is 2+2?"},
    {"role": "assistant", "content": "4."},
]


@pytest.fixture(scope="module")
def tok():
    return render.load_tokenizer(QWEN3)


def test_training_example_prefix_and_weights(tok):
    tokens, weights = render.render_training_example(tok, QWEN3.family, MESSAGES)
    prompt = render.render_generation_prompt(tok, QWEN3.family, MESSAGES[:-1])
    assert tokens[: len(prompt)] == prompt          # completion starts where the prompt ends
    assert set(weights[: len(prompt)]) == {0}       # no loss on the prompt
    assert set(weights[len(prompt):]) == {1}        # loss on the whole completion
    completion = tok.decode(tokens[len(prompt):])
    assert "4." in completion


def test_thinking_off_primes_or_trains_empty_think(tok):
    # With enable_thinking=False the empty think block must appear exactly once,
    # either primed in the prompt or trained in the completion — never absent,
    # never doubled.
    tokens, _ = render.render_training_example(tok, QWEN3.family, MESSAGES)
    text = tok.decode(tokens)
    assert text.count("<think>") == 1
    assert text.count("</think>") == 1


def test_thinking_kwargs_actually_reach_the_template(tok):
    # The guardrail for this project's recurring failure mode: a thinking-off
    # switch that is silently dropped, so a "thinking-off" run trains and
    # samples with thinking ON. If the family's kwargs did not reach
    # apply_chat_template, the two renders below would be identical.
    thinking_on = dataclasses.replace(QWEN3.family, thinking_kwargs={"enable_thinking": True})
    off = render.render_generation_prompt(tok, QWEN3.family, MESSAGES[:-1])
    on = render.render_generation_prompt(tok, thinking_on, MESSAGES[:-1])
    assert off != on, "enable_thinking=False did not change the rendered prompt"
    assert "<think>" in tok.decode(off)      # thinking-off primes the empty block
    assert "<think>" not in tok.decode(on)   # thinking-on leaves the model to open it


def test_no_thinking_content_is_trained(tok):
    # The empty think block is a format token, not content: nothing may appear
    # between <think> and </think> in what the model is trained to produce.
    tokens, _ = render.render_training_example(tok, QWEN3.family, MESSAGES)
    text = tok.decode(tokens)
    inner = text.split("<think>", 1)[1].split("</think>", 1)[0]
    assert inner.strip() == "", f"thinking content leaked into the render: {inner!r}"


def test_thinking_off_block_is_primed_not_trained(tok):
    # For Qwen3 specifically the empty block lands in the prompt span: the
    # template emits the same bytes with and without add_generation_prompt, so
    # the model is never trained to produce it, only to continue after it. A
    # template revision that moved the block into the completion would change
    # what the checkpoint learns, so pin it here.
    tokens, _ = render.render_training_example(tok, QWEN3.family, MESSAGES)
    prompt = render.render_generation_prompt(tok, QWEN3.family, MESSAGES[:-1])
    assert "<think>" in tok.decode(prompt)
    assert "<think>" not in tok.decode(tokens[len(prompt):])


def test_multi_turn_conversation_keeps_prefix_property(tok):
    # Qwen3's template renders only the final assistant turn with a think
    # block; earlier ones go bare. The prompt/full prefix property has to
    # survive that, or multi-turn training data silently mis-masks.
    msgs = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    tokens, weights = render.render_training_example(tok, QWEN3.family, msgs)
    prompt = render.render_generation_prompt(tok, QWEN3.family, msgs[:-1])
    assert tokens[: len(prompt)] == prompt
    assert set(weights[len(prompt):]) == {1}
    assert tok.decode(tokens).count("<think>") == 1
    assert "a2" in tok.decode(tokens[len(prompt):])


def test_assistant_prefix_path_reproduces_the_template(tok):
    # The assistant_prefix rebuild is the fallback for templates that prime
    # generation-only text; no sweep family needs it yet, so exercise it on a
    # case with a known answer. Thinking-ON Qwen3 is exactly that shape: the
    # generation prompt omits the empty think block, the full render emits it.
    # Declaring that text as assistant_prefix must rebuild the template's own
    # render exactly — otherwise the fallback silently corrupts whichever
    # family first needs it.
    on = dataclasses.replace(QWEN3.family, thinking_kwargs={"enable_thinking": True})
    via_template, _ = render.render_training_example(tok, on, MESSAGES)
    via_prefix, weights = render.render_training_example(
        tok, dataclasses.replace(on, assistant_prefix="<think>\n\n</think>\n\n"), MESSAGES
    )
    assert via_prefix == via_template
    prompt = render.render_generation_prompt(tok, on, MESSAGES[:-1])
    assert set(weights[: len(prompt)]) == {0}
    assert set(weights[len(prompt):]) == {1}


def test_stop_strings_nonempty_and_in_render(tok):
    stops = render.derive_stop_strings(tok, QWEN3.family)
    assert stops, "no stop strings derived"
    tokens, _ = render.render_training_example(tok, QWEN3.family, MESSAGES)
    assert any(s in tok.decode(tokens) for s in stops)


def test_stop_string_terminates_the_assistant_turn(tok):
    # Substring membership is too weak: a stop string that merely occurs
    # somewhere would truncate sampled text mid-response at eval time. The stop
    # must be the turn terminator — everything before its first occurrence in
    # the completion is exactly the assistant content.
    stops = render.derive_stop_strings(tok, QWEN3.family)
    tokens, _ = render.render_training_example(tok, QWEN3.family, MESSAGES)
    prompt = render.render_generation_prompt(tok, QWEN3.family, MESSAGES[:-1])
    completion = tok.decode(tokens[len(prompt):])
    hits = [s for s in stops if s in completion]
    assert hits, f"no stop string in the completion span: {stops!r}"
    for stop in hits:
        assert completion.split(stop)[0].strip() == MESSAGES[-1]["content"]


def test_unverified_family_refused_for_training():
    unverified = dataclasses.replace(QWEN3.family, verified=False)
    with pytest.raises(RuntimeError, match="verified"):
        render.require_verified(unverified)


def test_verified_family_accepted_for_training():
    verified = dataclasses.replace(QWEN3.family, verified=True)
    render.require_verified(verified)  # must not raise


def test_gpt_oss_final_channel_extraction():
    text = (
        "<|channel|>analysis<|message|>quick check<|end|>"
        "<|start|>assistant<|channel|>final<|message|>The answer is 4.<|return|>"
    )
    assert render.extract_response(families.GPT_OSS, text) == "The answer is 4."
