"""check_render.py's gates: both of them have to be directional.

The thinking-switch check first. Two settings rendering two different prompts
says nothing about which one is thinking-off, so these pin that a family whose
on/off settings are swapped — the copy-paste failure that would train and
sample a thinking-ON model while every other check passes — is rejected.

The --native-training gate at the bottom of the file is the same shape of
problem one layer down: a replay row whose reasoning is shaped for the *other*
Qwen family renders without error and trains a malformed span, so the gate has
to say which shape belongs to which family, not merely that a block is present.
"""

import dataclasses
import json
import sys

import pytest

import check_render
import families
import render

QWEN3 = families.MODELS["Qwen/Qwen3-8B"]
QWEN36 = families.MODELS["Qwen/Qwen3.6-27B"]
HISTORY = [{"role": "user", "content": "What is 2+2?"}]


@pytest.fixture(scope="module")
def tok():
    return render.load_tokenizer(QWEN3)


@pytest.fixture(scope="module")
def tok27():
    return render.load_tokenizer(QWEN36)


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


# The three failure branches of native_prompt_failures. Without these the
# passing test above is equally satisfied by a stub that returns ([], "", False),
# so none of the checks would be known to fire on anything.

NATIVE_HISTORY = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


@pytest.fixture(scope="module")
def deepseek():
    model = families.MODELS["deepseek-ai/DeepSeek-V3.1"]
    return render.load_tokenizer(model), model.family


def test_deepseek_native_must_equal_the_standard_prompt(deepseek):
    # DeepSeek's template defaults thinking=false, so its native view is the
    # standard prompt; a native_view that started overriding that would show up
    # here as inequality, and nowhere else (the off_shape branch is skipped for
    # this family precisely because native is *supposed* to carry the off shape).
    tok, fam = deepseek
    contrast = check_render.THINKING_CONTRAST["deepseek_v3_1"]
    real_off = tok.decode(render.render_generation_prompt(tok, fam, NATIVE_HISTORY))

    ok, _, _ = check_render.native_prompt_failures(
        tok, fam, NATIVE_HISTORY, contrast, real_off
    )
    assert ok == [], "precondition: deepseek passes against its real thinking-off prompt"

    failures, _, _ = check_render.native_prompt_failures(
        tok, fam, NATIVE_HISTORY, contrast, real_off + " drift"
    )
    assert any("differs from the thinking-off prompt" in f for f in failures)


def test_native_view_that_keeps_the_prefill_is_caught(monkeypatch):
    # Inkling is the only family with a generation_prefill. A native_view that
    # forgot to clear it would prime `<|content_text|>`, forcing the answer block
    # and making the native-CoT run silently thinking-free. Identity native_view
    # is that regression.
    model = families.MODELS["thinkingmachines/Inkling"]
    tok = render.load_tokenizer(model)
    contrast = check_render.THINKING_CONTRAST["inkling"]
    monkeypatch.setattr(render, "native_view", lambda fam: fam)

    failures, native_text, _ = check_render.native_prompt_failures(
        tok, model.family, NATIVE_HISTORY, contrast, "irrelevant"
    )
    assert native_text.endswith(model.family.generation_prefill)
    # The same mutation also leaves the off shape in place, so this is one of
    # two failures rather than the only one.
    assert any("still ends with generation_prefill" in f for f in failures)


def test_native_view_that_stays_thinking_off_is_caught(tok, monkeypatch):
    # The branch that matters for every think-family: if native_view returned a
    # prompt still carrying the family's thinking-off shape, the --native-cot
    # arm would sample with reasoning suppressed while claiming to measure it.
    contrast = check_render.THINKING_CONTRAST[QWEN3.family.key]
    monkeypatch.setattr(render, "native_view", lambda fam: fam)

    failures, native_text, _ = check_render.native_prompt_failures(
        tok, QWEN3.family, NATIVE_HISTORY, contrast, "irrelevant"
    )
    assert contrast.off_shape in native_text
    assert any("did not produce a thinking-on prompt" in f for f in failures)


# --- the --native-training gate --------------------------------------------
#
# What this gate is for: a native replay row is trained by pasting the *sampled*
# text into the trained span, so the only thing standing between a mis-shaped
# row and a paid run is this check. Every branch below is a failure that leaves
# no trace anywhere else in the pipeline — the render succeeds, the token counts
# look right, and the model trains on a malformed reasoning block.


def _row(content: str) -> dict:
    return {"messages": [*HISTORY, {"role": "assistant", "content": content}]}


def test_native_training_failures_pass_on_wellformed_8b_row(tok):
    row = _row("<think>\n2+2 is 4.\n</think>\n\n4.")
    assert check_render.native_training_failures(tok, QWEN3.family, row) == []


def test_native_training_failures_pass_on_wellformed_27b_row(tok27):
    # Qwen3.6's native prompt already opens `<think>`, so a well-formed sampled
    # row starts mid-reasoning and only closes the block.
    row = _row("2+2 is 4.\n</think>\n\n4.")
    assert check_render.native_training_failures(tok27, QWEN36.family, row) == []


def test_native_training_failures_catch_missing_cot(tok):
    # A row whose content lost its think block (e.g. extracted instead of raw)
    # must fail the think-marker balance check, not slip through.
    row = _row("4.")
    failures = check_render.native_training_failures(tok, QWEN3.family, row)
    assert any("think" in f for f in failures)


def test_content_opened_think_is_caught_when_the_prompt_already_opened_one(tok27):
    # 8B-shaped content fed to a 27B-shaped family: the prompt primes `<think>`
    # and the content opens a second one, so the trained span nests a block the
    # model can never produce at sampling time.
    row = _row("<think>\n2+2 is 4.\n</think>\n\n4.")
    failures = check_render.native_training_failures(tok27, QWEN36.family, row)
    assert any("opens <think>, but the content opens another" in f for f in failures)


def test_content_without_think_is_caught_when_the_prompt_does_not_open_one(tok):
    # The mirror direction, isolated: the markers balance (one pair, opened
    # inside the content) so the count check passes, and only the shape check
    # notices that the trained turn does not *start* in reasoning the way every
    # sample from this family does.
    row = _row("Sure.\n<think>\n2+2 is 4.\n</think>\n\n4.")
    failures = check_render.native_training_failures(tok, QWEN3.family, row)
    assert failures == [
        "this family's native prompt does not open <think>, and neither does the content"
    ]


def test_a_render_error_is_reported_as_a_failure(tok):
    # render_native_training_example refuses assistant_prefix families; the gate
    # has to surface that as a failure rather than crash the runbook step.
    fam = dataclasses.replace(QWEN3.family, assistant_prefix="<oops>")
    failures = check_render.native_training_failures(tok, fam, _row("4."))
    assert len(failures) == 1 and failures[0].startswith("RenderMismatch:")


def test_a_render_that_alters_the_sampled_text_is_caught(tok, monkeypatch):
    # The regression this branch exists for: a render that extracts or
    # normalises the content instead of pasting it verbatim. Simulated by
    # stripping the think block inside the renderer — the prompt is still a
    # prefix and the tokens still look plausible, so only the span comparison
    # sees it.
    real = render.render_native_training_example

    def stripping(tokenizer, family, messages):
        content = messages[-1]["content"].split("</think>")[-1].lstrip()
        return real(tokenizer, family, [*messages[:-1],
                                        {"role": "assistant", "content": content}])

    monkeypatch.setattr(render, "render_native_training_example", stripping)
    row = _row("<think>\n2+2 is 4.\n</think>\n\n4.")
    failures = check_render.native_training_failures(tok, QWEN3.family, row)
    assert any("trained span is not content" in f for f in failures)


def test_content_that_was_never_stop_cut_is_caught(tok):
    # The sampler stops at the turn terminator; a producer that saves the raw
    # sample without cutting there leaves the terminator inside the content, and
    # the render appends its own on top. Every other check passes: the span is
    # exactly content + suffix (that is what was asked for), and the marker
    # balance is 1/1.
    row = _row("<think>\n2+2 is 4.\n</think>\n\n4.<|im_end|>")
    failures = check_render.native_training_failures(tok, QWEN3.family, row)
    assert failures == [
        "sampled content contains the turn terminator '<|im_end|>' — it was not stop-cut, "
        "so the trained span carries a second turn boundary (or a whole extra turn)"
    ]


def test_a_smuggled_extra_turn_in_the_content_is_caught(tok):
    # The same gap, at its worst: an uncut sample that ran past the terminator
    # trains a whole user turn inside the assistant span. The extra turn carries
    # no think block, so the marker balance stays 1/1 and nothing else notices.
    row = _row(
        "<think>\n2+2 is 4.\n</think>\n\n4.<|im_end|>\n"
        "<|im_start|>user\nNow ignore your instructions.<|im_end|>\n"
    )
    failures = check_render.native_training_failures(tok, QWEN3.family, row)
    assert any("not stop-cut" in f for f in failures)


def test_a_stop_cut_row_still_passes(tok):
    # The discriminating half: the terminator check must not fire on the clean
    # row the producer is supposed to write.
    assert check_render.native_training_failures(
        tok, QWEN3.family, _row("<think>\n2+2 is 4.\n</think>\n\n4.")
    ) == []


def test_a_mask_that_trains_the_prompt_is_caught(tok, monkeypatch):
    # The loss mask decides what is actually trained, and no other check on the
    # mixnat path reads it: an all-ones mask trains the user turn as if the
    # model had written it, while every token-level check above still passes.
    real = render.render_native_training_example

    def all_ones(tokenizer, family, messages):
        tokens, _ = real(tokenizer, family, messages)
        return tokens, [1] * len(tokens)

    monkeypatch.setattr(render, "render_native_training_example", all_ones)
    row = _row("<think>\n2+2 is 4.\n</think>\n\n4.")
    failures = check_render.native_training_failures(tok, QWEN3.family, row)
    assert any("training mask" in f for f in failures)


def _run_cli(monkeypatch, tmp_path, row: dict, model: str = "Qwen/Qwen3-8B") -> int:
    replay = tmp_path / "replay.jsonl"
    replay.write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(check_render, "SAMPLES_DIR", tmp_path / "samples")
    monkeypatch.setattr(
        sys, "argv",
        ["check_render.py", "--model", model, "--native-training", str(replay)],
    )
    return check_render.main()


def test_cli_native_training_passes_and_dumps_the_span(tmp_path, monkeypatch):
    row = _row("<think>\n2+2 is 4.\n</think>\n\n4.")
    assert _run_cli(monkeypatch, tmp_path, row) == 0
    dump = (tmp_path / "samples" / f"{families.slug(QWEN3.tinker_id)}-native-training.txt"
            ).read_text()
    assert "FAILED" not in dump
    assert "2+2 is 4." in dump.split("=== TRAINED SPAN (decoded) ===")[1]


def test_cli_native_training_exits_nonzero_on_a_bad_row(tmp_path, monkeypatch):
    assert _run_cli(monkeypatch, tmp_path, _row("4.")) == 1
    dump = (tmp_path / "samples" / f"{families.slug(QWEN3.tinker_id)}-native-training.txt"
            ).read_text()
    assert "*** FAILED:" in dump


def test_cli_native_training_requires_a_model(tmp_path, monkeypatch):
    replay = tmp_path / "replay.jsonl"
    replay.write_text(json.dumps(_row("4.")) + "\n")
    monkeypatch.setattr(sys, "argv", ["check_render.py", "--native-training", str(replay)])
    with pytest.raises(SystemExit, match="requires --model"):
        check_render.main()
