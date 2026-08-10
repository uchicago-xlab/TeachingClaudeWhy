import asyncio

import pytest

import families
import render
import sample_replay
import tinker_sampling

FC_ROW = {"id": 7, "query": "Weather in Oslo?",
          "tools": [{"name": "get_weather", "parameters": {"city": {"type": "str"}}}],
          "answers": [{"name": "get_weather", "arguments": {"city": "Oslo"}}]}
CHAT_ROW = {"id": "h1", "user": "Recommend a houseplant."}
CALL = '{"name": "get_weather", "arguments": {"city": "Oslo"}}'


def test_prompt_messages_fc_has_system_with_tools_then_user():
    msgs = sample_replay.prompt_messages(FC_ROW, "fc-train")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "get_weather" in msgs[0]["content"]
    assert msgs[1]["content"] == "Weather in Oslo?"


def test_prompt_messages_chat_is_bare_user():
    assert sample_replay.prompt_messages(CHAT_ROW, "chat-train") == [
        {"role": "user", "content": "Recommend a houseplant."}]


def test_accept_fc_requires_valid_terminating_call():
    assert sample_replay.accept(FC_ROW, "fc-train", "off", CALL, "stop") is None
    assert sample_replay.accept(FC_ROW, "fc-train", "off", CALL, "length") == "truncated"
    assert "no parseable call" in sample_replay.accept(
        FC_ROW, "fc-train", "off", "I cannot call functions.", "stop")
    assert "unknown function" in sample_replay.accept(
        FC_ROW, "fc-train", "off", '{"name": "rm_rf", "arguments": {}}', "stop")


def test_accept_chat_requires_termination_and_content_only():
    assert sample_replay.accept(CHAT_ROW, "chat-train", "off", "A pothos.", "stop") is None
    assert sample_replay.accept(CHAT_ROW, "chat-train", "off", "", "stop") == "empty"
    assert sample_replay.accept(CHAT_ROW, "chat-train", "off", "A pothos.", "length") == "truncated"


def test_extract_final_native_restores_primed_think(monkeypatch):
    # 27B-shaped family: prompt opens <think>, sample starts mid-reasoning.
    fam = families.MODELS["Qwen/Qwen3.6-27B"].family
    monkeypatch.setattr(render, "generation_prompt_opens_think", lambda tok, f: True)
    final = tinker_sampling.extract_final(None, fam, "native",
                                          "reasoning here\n</think>\n\n" + CALL)
    assert final.strip() == CALL


# --- native think-shape screen (mirrors check_render.native_training_failures) ---


def _native_failure(raw, opens):
    return sample_replay.shape_failure(raw, shape="native", opens=opens)


def test_shape_failure_native_matches_the_gates_directional_checks():
    # Prompt opens <think> (3.6-shaped): content must not open another.
    assert _native_failure("reasoning\n</think>\n" + CALL, opens=True) is None
    assert _native_failure("<think>\nreasoning\n</think>\n" + CALL, opens=True) == "think-shape"
    # Prompt does not open it (8B-shaped): content must carry its own.
    assert _native_failure("<think>\nreasoning\n</think>\n" + CALL, opens=False) is None
    assert _native_failure(CALL, opens=False) == "think-shape"
    # Exactly one close, either shape.
    assert _native_failure("<think>\na</think>b</think>\n" + CALL, opens=False) == "think-shape"
    assert _native_failure("<think>\nunclosed " + CALL, opens=False) == "think-shape"
    # ...and exactly one open, which the gate counts in the full render.
    assert _native_failure("<think>\na<think>b</think>\n" + CALL, opens=False) == "think-shape"


def test_shape_failure_off_rejects_either_think_tag():
    # The Qwen3 template routes on the CLOSING tag, so close-only content — the
    # plausible off-shape drift, and content that merely names the tag — is what
    # breaks the training render; the opening tag is screened too, as accepted
    # over-rejection for templates that key on it.
    assert sample_replay.shape_failure(CALL, shape="off", opens=False) is None
    assert sample_replay.shape_failure(
        "<think>\nreasoning\n</think>\n" + CALL, shape="off", opens=False) == "think-shape"
    assert sample_replay.shape_failure(
        "reasoning\n</think>\n\n" + CALL, shape="off", opens=False) == "think-shape"
    assert sample_replay.shape_failure(
        "The tag is </think>.", shape="off", opens=False) == "think-shape"


class FakeSeq:
    def __init__(self, tokens, stop_reason):
        self.tokens, self.stop_reason = tokens, stop_reason


class FakeResult:
    def __init__(self, seqs):
        self.sequences = seqs


class FakeClient:
    """First attempt refuses, second emits a call — exercises the retry loop."""
    def __init__(self, tok, texts):
        self.tok, self.texts, self.calls = tok, list(texts), 0

    async def sample_async(self, prompt, num_samples, sampling_params):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return FakeResult([FakeSeq(self.tok.encode(text, add_special_tokens=False), "stop")])


def _run(client, tok, rows, **kw):
    model = families.MODELS["Qwen/Qwen3-8B"]
    kw = {"split": "fc-train", "shape": "off", "max_tokens": 64,
          "temperature": 0.7, "seed": 0, "tries": 3, **kw}
    return asyncio.run(sample_replay.sample_split(
        client, __import__("tinker"), tok, model, rows, **kw))


def test_sample_split_retries_until_accepted(qwen3_tok):
    client = FakeClient(qwen3_tok, ["I would rather not.", CALL])
    rows, stats = _run(client, qwen3_tok, [FC_ROW])
    assert len(rows) == 1
    assert rows[0]["messages"][-1]["role"] == "assistant"
    assert CALL in rows[0]["messages"][-1]["content"]
    assert "render" not in rows[0]                     # off rows carry no render key
    assert rows[0]["meta"]["tries"] == 2
    assert stats["accepted"] == 1 and stats["rejected_final"] == 0
    # The resample that landed is still a resample: spend is reconciled here.
    assert stats["retries_used"] == 1


def test_sample_split_native_rows_tagged(qwen3_tok):
    text = "<think>\nchecking the weather api\n</think>\n\n" + CALL
    client = FakeClient(qwen3_tok, [text])
    rows, _ = _run(client, qwen3_tok, [FC_ROW], shape="native", max_tokens=64)
    assert rows[0]["render"] == "native"
    assert "<think>" in rows[0]["messages"][-1]["content"]   # raw text stored, CoT kept


def test_native_row_passes_the_mixnat_gate(qwen3_tok):
    # End to end against the real gate: what this stage writes is what Task 4
    # checks before any paid mixnat training.
    import check_render

    text = "<think>\nchecking the weather api\n</think>\n\n" + CALL
    rows, _ = _run(FakeClient(qwen3_tok, [text]), qwen3_tok, [FC_ROW],
                   shape="native", max_tokens=64)
    fam = families.MODELS["Qwen/Qwen3-8B"].family
    assert check_render.native_training_failures(qwen3_tok, fam, rows[0]) == []


def test_sample_split_rejects_wrong_native_think_shape(qwen3_tok):
    # Qwen3-8B's native prompt does not open <think>, so content without one is
    # the shape check_render's mixnat gate rejects — reject it at write time.
    client = FakeClient(qwen3_tok, [CALL])
    rows, stats = _run(client, qwen3_tok, [FC_ROW], shape="native")
    assert rows == []
    assert stats["rejected_final"] == 1
    assert stats["reasons"] == {"think-shape": 3}
    assert stats["retries_used"] == 2   # three attempts, two of them resamples


@pytest.mark.parametrize("thinking", [
    "<think>\nthe user wants weather\n</think>\n\n" + CALL,   # a full block
    "reasoning about the weather api\n</think>\n\n" + CALL,   # close only: primed-native drift
    "You would write </think> to close it.\n" + CALL,         # the tag merely named inline
])
def test_sample_split_rejects_off_shape_think_tags(qwen3_tok, thinking):
    # A thinking-off sample carrying either think tag renders fine here and
    # blows up train_sft's render_split later — reject it at write time.
    client = FakeClient(qwen3_tok, [thinking, CALL])
    rows, stats = _run(client, qwen3_tok, [FC_ROW])
    assert stats["reasons"] == {"think-shape": 1}
    assert stats["accepted"] == 1 and stats["retries_used"] == 1
    assert "think>" not in rows[0]["messages"][-1]["content"]

    # ...and the screen is not superstition: the row that was kept renders,
    # the one that was rejected is exactly what aborts a training run. The
    # close-only and inline cases are the ones an open-tag-only screen missed.
    fam = families.MODELS["Qwen/Qwen3-8B"].family
    render.render_training_example(qwen3_tok, fam, rows[0]["messages"])
    with pytest.raises(render.RenderMismatch):
        render.render_training_example(
            qwen3_tok, fam,
            rows[0]["messages"][:-1] + [{"role": "assistant", "content": thinking}])


def test_stored_content_is_stop_cut(qwen3_tok):
    # The turn terminator must never reach a stored row: check_render's gate
    # fails a replay file whose content carries one ("not stop-cut").
    stop = render.derive_stop_strings(qwen3_tok, families.MODELS["Qwen/Qwen3-8B"].family)[0]
    client = FakeClient(qwen3_tok, [CALL + stop + "\n<|im_start|>user\nand Bergen?"])
    rows, stats = _run(client, qwen3_tok, [FC_ROW])
    assert stats["accepted"] == 1
    content = rows[0]["messages"][-1]["content"]
    assert stop not in content
    assert content.strip() == CALL


def test_sample_split_seeds_are_deterministic_per_attempt(qwen3_tok):
    seen = []

    class SeedSpy(FakeClient):
        async def sample_async(self, prompt, num_samples, sampling_params):
            seen.append(sampling_params.seed)
            return await super().sample_async(prompt, num_samples, sampling_params)

    client = SeedSpy(qwen3_tok, ["I would rather not.", CALL])
    _run(client, qwen3_tok, [FC_ROW], seed=2)
    assert seen == [2_000_001, 2_000_002]
