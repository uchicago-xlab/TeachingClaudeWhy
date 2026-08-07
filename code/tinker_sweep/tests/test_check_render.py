"""The thinking-switch check has to be directional, not merely differential.

Two settings rendering two different prompts says nothing about which one is
thinking-off. These pin that a family whose on/off settings are swapped — the
copy-paste failure that would train and sample a thinking-ON model while every
other check passes — is rejected.
"""

import dataclasses

import pytest

import check_render
import families
import render

QWEN3 = families.MODELS["Qwen/Qwen3-8B"]
HISTORY = [{"role": "user", "content": "What is 2+2?"}]


@pytest.fixture(scope="module")
def tok():
    return render.load_tokenizer(QWEN3)


def _failures(tok, fam, contrast):
    return check_render._thinking_switch_failures(tok, fam, HISTORY, contrast)[0]


def test_correct_family_passes(tok):
    contrast = check_render.THINKING_CONTRAST[QWEN3.family.key]
    assert _failures(tok, QWEN3.family, contrast) == []


def test_swapped_thinking_kwargs_are_caught(tok):
    # The mutation: thinking_kwargs holds the thinking-ON setting and the
    # contrast table holds the off one. The two prompts still differ, so a
    # differential check passes; only the off-shape catches it.
    real = check_render.THINKING_CONTRAST[QWEN3.family.key]
    swapped_fam = dataclasses.replace(QWEN3.family, thinking_kwargs=real.on_kwargs)
    swapped_contrast = check_render.Contrast(QWEN3.family.thinking_kwargs, real.off_shape)

    off = tok.decode(render.render_generation_prompt(tok, swapped_fam, HISTORY))
    on = dataclasses.replace(swapped_fam, thinking_kwargs=swapped_contrast.on_kwargs)
    assert off != tok.decode(render.render_generation_prompt(tok, on, HISTORY)), (
        "precondition: a swap still renders two different prompts, which is why "
        "the differential check alone cannot catch it"
    )

    failures = _failures(tok, swapped_fam, swapped_contrast)
    assert any("thinking-off shape" in f for f in failures)


def test_non_discriminating_off_shape_is_rejected(tok):
    # A shape that appears under both settings would silently defeat the check.
    sloppy = check_render.Contrast({"enable_thinking": True}, "<|im_start|>assistant")
    failures = _failures(tok, QWEN3.family, sloppy)
    assert any("does not discriminate" in f for f in failures)


def test_every_family_has_a_contrast_entry():
    # A family added to the registry without stating what thinking-off looks
    # like cannot be verified, and check_model refuses it.
    missing = {
        m.family.key for m in families.MODELS.values()
        if m.family.key not in check_render.THINKING_CONTRAST
    }
    assert missing == set()


def test_native_prompt_failures_pass_for_qwen3():
    model = families.MODELS["Qwen/Qwen3-8B"]
    tok = render.load_tokenizer(model)
    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    off_text = tok.decode(render.render_generation_prompt(tok, model.family, history))
    contrast = check_render.THINKING_CONTRAST["qwen3"]
    failures, native_text, primed = check_render.native_prompt_failures(
        tok, model.family, history, contrast, off_text
    )
    assert failures == []
    assert "<think>" not in native_text     # qwen3 native primes nothing
    assert primed is False
