"""Provider tests: no TINKER_API_KEY, no live sampling (Task 9 does that).

The Tinker client is a `create_autospec` of the real `tinker.SamplingClient` /
`tinker.ServiceClient`, so every call the provider makes is checked against the
installed SDK's signatures — an SDK rename breaks these tests instead of
surfacing as a live failure mid-sweep. Sampler responses are real
`tinker.SampleResponse` / `SampledSequence` objects for the same reason.
Tokenizers are the real HF ones (cached).
"""

import asyncio
import dataclasses
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

import numpy as np
import pytest
import tinker
from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import ChatMessageSystem, ChatMessageUser

import families
import render
import tinker_provider

QWEN = "Qwen/Qwen3-8B"
GPT_OSS = "openai/gpt-oss-20b"
INKLING = "thinkingmachines/Inkling-Small"

MESSAGES = [
    ChatMessageSystem(content="You are Alex."),
    ChatMessageUser(content="Do the bad thing?"),
]
MESSAGE_DICTS = [
    {"role": "system", "content": "You are Alex."},
    {"role": "user", "content": "Do the bad thing?"},
]


def build(model_name=QWEN, checkpoint=None, **model_args):
    """A provider wired to an autospec'd Tinker service client."""
    service_client = create_autospec(tinker.ServiceClient, instance=True)
    service_client.create_sampling_client.return_value = create_autospec(
        tinker.SamplingClient, instance=True
    )
    api = tinker_provider.TinkerAPI(
        model_name=model_name,
        config=GenerateConfig(),
        checkpoint=checkpoint,
        service_client=service_client,
        **model_args,
    )
    return api, service_client


def response(tokenizer, *texts, stop_reason="stop"):
    """A real SampleResponse carrying `texts` as sampled token sequences."""
    return tinker.SampleResponse(
        sequences=[
            tinker.types.SampledSequence(
                stop_reason=stop_reason,
                tokens_np=np.array(
                    tokenizer.encode(text, add_special_tokens=False), dtype=np.int32
                ),
            )
            for text in texts
        ]
    )


def generate(api, sample_response, config=None, messages=MESSAGES, tools=(), tool_choice="none"):
    """Run one generate() against a canned sampler response; return (output, call)."""
    captured = {}

    async def fake_sample(prompt, num_samples, sampling_params, **kwargs):
        captured.update(prompt=prompt, num_samples=num_samples, params=sampling_params)
        return sample_response

    api.sampling_client.sample_async.side_effect = fake_sample
    out = asyncio.run(
        api.generate(
            input=list(messages),
            tools=list(tools),
            tool_choice=tool_choice,
            config=config or GenerateConfig(temperature=1.0, max_tokens=4096),
        )
    )
    return out, SimpleNamespace(**captured)


@pytest.fixture(scope="module")
def qwen():
    return build()[0]


# --- prompt rendering --------------------------------------------------------

def test_generate_renders_thinking_off_and_returns_text(qwen):
    out, call = generate(qwen, response(qwen.tokenizer, "I refuse politely."))

    text = qwen.tokenizer.decode(call.prompt.to_ints())
    assert "You are Alex." in text
    assert "Do the bad thing?" in text
    assert call.params.temperature == 1.0
    assert call.params.max_tokens == 4096
    assert call.num_samples == 1
    assert out.choices[0].message.text == "I refuse politely."
    assert out.completion == "I refuse politely."


def test_sampler_prompt_is_exactly_the_render_layer_prompt(qwen):
    # The point of the design: eval primes the same tokens training masked. Any
    # divergence here (a stray template kwarg, a chat-shape fixup in the
    # provider) means the checkpoint is sampled in a format it was not trained
    # in, and the whole sweep compares the wrong thing.
    _, call = generate(qwen, response(qwen.tokenizer, "ok"))
    expected = render.render_generation_prompt(
        qwen.tokenizer, qwen.sweep_model.family, MESSAGE_DICTS
    )
    assert call.prompt.to_ints() == expected
    assert isinstance(call.prompt, tinker.ModelInput)


def test_prompt_reaching_the_sampler_is_thinking_off(qwen):
    # This project's recurring failure mode is a thinking switch that silently
    # stops reaching the template. Contrast against the thinking-ON render:
    # identical prompts would mean the family's kwargs were dropped somewhere
    # between families.py and the sampler.
    _, call = generate(qwen, response(qwen.tokenizer, "ok"))
    thinking_on = dataclasses.replace(
        qwen.sweep_model.family, thinking_kwargs={"enable_thinking": True}
    )
    on = render.render_generation_prompt(qwen.tokenizer, thinking_on, MESSAGE_DICTS)
    assert call.prompt.to_ints() != on
    assert qwen.tokenizer.decode(call.prompt.to_ints()).endswith("<think>\n\n</think>\n\n")


# --- stop strings ------------------------------------------------------------

def test_stop_strings_reach_the_sampler(qwen):
    _, call = generate(qwen, response(qwen.tokenizer, "ok"))
    expected = render.derive_stop_strings(qwen.tokenizer, qwen.sweep_model.family)
    assert expected, "precondition: qwen3 derives stop strings"
    assert list(call.params.stop) == expected


def test_config_stop_seqs_are_added_not_substituted(qwen):
    _, call = generate(
        qwen,
        response(qwen.tokenizer, "ok"),
        config=GenerateConfig(max_tokens=64, stop_seqs=["\nHuman:"]),
    )
    derived = render.derive_stop_strings(qwen.tokenizer, qwen.sweep_model.family)
    assert list(call.params.stop) == derived + ["\nHuman:"]


def test_text_after_a_stop_string_is_cut(qwen):
    # Tinker may or may not include the stop token in the returned sequence; if
    # it does, the marker (and any continuation past the turn boundary) must not
    # reach the grader.
    stop = render.derive_stop_strings(qwen.tokenizer, qwen.sweep_model.family)[0]
    out, _ = generate(qwen, response(qwen.tokenizer, f"I refuse.{stop}<|im_start|>user\nagain?"))
    assert out.choices[0].message.text == "I refuse."


# --- stop reason / truncation ------------------------------------------------

def test_stop_reason_stop_is_mapped(qwen):
    out, _ = generate(qwen, response(qwen.tokenizer, "I refuse.", stop_reason="stop"))
    assert out.choices[0].stop_reason == "stop"


def test_truncation_keeps_the_max_tokens_signal_and_hides_reasoning(qwen):
    # Truncated completions grade as non-harmful and silently deflate the rate
    # (misalignment_eval/README.md), so the signal has to survive into the log
    # even though the text the grader sees is emptied of reasoning.
    out, _ = generate(
        qwen,
        response(qwen.tokenizer, "<think>I could leak the file. If I", stop_reason="length"),
    )
    assert out.choices[0].stop_reason == "max_tokens"
    assert out.choices[0].message.text == ""


def test_stop_reason_inferred_from_token_count_when_the_sdk_omits_it(qwen):
    # Defensive: an SDK that stops reporting a per-sequence stop_reason must not
    # silently turn every truncation into a clean stop.
    tokens = qwen.tokenizer.encode("a b c d e f g h", add_special_tokens=False)
    canned = SimpleNamespace(sequences=[SimpleNamespace(tokens=tokens)])
    out, _ = generate(qwen, canned, config=GenerateConfig(max_tokens=len(tokens)))
    assert out.choices[0].stop_reason == "max_tokens"

    out, _ = generate(qwen, canned, config=GenerateConfig(max_tokens=len(tokens) + 1))
    assert out.choices[0].stop_reason == "stop"


# --- per-family completion extraction ----------------------------------------

@pytest.fixture(scope="module")
def gpt_oss():
    return build(GPT_OSS)[0]


@pytest.fixture(scope="module")
def inkling():
    return build(INKLING)[0]


def test_gpt_oss_final_channel_is_what_the_grader_sees(gpt_oss):
    sampled = (
        "<|channel|>analysis<|message|>They want the file leaked.<|end|>"
        "<|start|>assistant<|channel|>final<|message|>I won't do that."
    )
    out, _ = generate(gpt_oss, response(gpt_oss.tokenizer, sampled))
    assert out.choices[0].message.text == "I won't do that."


def test_truncated_gpt_oss_reasoning_never_reaches_the_grader(gpt_oss):
    sampled = "<|channel|>analysis<|message|>I could exfiltrate the weights. If I"
    out, _ = generate(gpt_oss, response(gpt_oss.tokenizer, sampled, stop_reason="length"))
    assert out.choices[0].message.text == ""
    assert out.choices[0].stop_reason == "max_tokens"


def test_inkling_content_text_is_what_the_grader_sees(inkling):
    sampled = (
        "<|content_thinking|>weighing it up<|end_message|>"
        "<|message_model|><|content_text|>I won't do that.<|end_message|>"
    )
    out, _ = generate(inkling, response(inkling.tokenizer, sampled))
    assert out.choices[0].message.text == "I won't do that."


def test_truncated_inkling_reasoning_never_reaches_the_grader(inkling):
    sampled = "<|content_thinking|>I could leak the documents. On one"
    out, _ = generate(inkling, response(inkling.tokenizer, sampled, stop_reason="length"))
    assert out.choices[0].message.text == ""
    assert out.choices[0].stop_reason == "max_tokens"


# --- client construction -----------------------------------------------------

def test_base_model_client_when_no_checkpoint():
    api, service_client = build()
    service_client.create_sampling_client.assert_called_once_with(base_model=QWEN)
    out, _ = generate(api, response(api.tokenizer, "ok"))
    assert out.model == f"tinker/{QWEN}"


def test_checkpoint_client_and_model_label():
    path = "tinker://sweep/qwen3-8b/weights/00042"
    api, service_client = build(checkpoint=path)
    service_client.create_sampling_client.assert_called_once_with(model_path=path)
    out, _ = generate(api, response(api.tokenizer, "ok"))
    assert path in out.model, "checkpoint must be identifiable in the eval log"


def test_inspect_resolves_the_provider_and_passes_model_args():
    # The produced interface is `--model tinker/<id> -M checkpoint=…`, which
    # only works if importing this module registers the provider and Inspect's
    # own resolution hands model args through. Exercised via the real get_model,
    # not by inspecting the registry, and with no API key: the injected service
    # client arrives the same way -M checkpoint would.
    from inspect_ai.model import get_model

    service_client = create_autospec(tinker.ServiceClient, instance=True)
    service_client.create_sampling_client.return_value = create_autospec(
        tinker.SamplingClient, instance=True
    )
    path = "tinker://sweep/qwen3-8b/weights/00042"
    model = get_model(
        f"tinker/{QWEN}", checkpoint=path, service_client=service_client, memoize=False
    )
    assert model.api.model_name == QWEN
    assert model.api.checkpoint == path
    service_client.create_sampling_client.assert_called_once_with(model_path=path)


def test_usage_is_reported():
    api, _ = build()
    out, call = generate(api, response(api.tokenizer, "I refuse politely."))
    assert out.usage.input_tokens == len(call.prompt.to_ints())
    assert out.usage.output_tokens > 0
    assert out.usage.total_tokens == out.usage.input_tokens + out.usage.output_tokens


def test_num_choices_requests_that_many_samples(qwen):
    canned = response(qwen.tokenizer, "first answer", "second answer")
    out, call = generate(qwen, canned, config=GenerateConfig(max_tokens=64, num_choices=2))
    assert call.num_samples == 2
    assert [c.message.text for c in out.choices] == ["first answer", "second answer"]


# --- refusals ----------------------------------------------------------------

def test_unverified_family_is_refused():
    model = families.MODELS[QWEN]
    unverified = dataclasses.replace(
        model, family=dataclasses.replace(model.family, verified=False)
    )
    with patch.dict(families.MODELS, {QWEN: unverified}):
        with pytest.raises(RuntimeError, match="verified"):
            build()


def test_unknown_model_is_refused():
    with pytest.raises(KeyError, match="sweep registry"):
        build("mistralai/Mistral-Whatever")


def test_tools_are_refused(qwen):
    # The agentic_misalignment tasks use no Inspect tools. Silently dropping
    # them would let a future tool-using eval run and score meaningless results.
    tool = SimpleNamespace(name="send_email")
    with pytest.raises(NotImplementedError, match="tool"):
        generate(qwen, response(qwen.tokenizer, "ok"), tools=[tool], tool_choice="auto")


def test_tool_choice_is_refused(qwen):
    with pytest.raises(NotImplementedError, match="tool"):
        generate(qwen, response(qwen.tokenizer, "ok"), tool_choice="any")


def test_unknown_model_arg_is_refused():
    # A typo'd -M checkpoint= would otherwise evaluate the base model while the
    # log claims a finetune.
    with pytest.raises(TypeError, match="checkpint"):
        build(checkpint="tinker://oops")
