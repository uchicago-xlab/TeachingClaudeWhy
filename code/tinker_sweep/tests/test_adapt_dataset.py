import adapt_dataset
import families

NEUTRAL = {"messages": [
    {"role": "system", "content": "You are [MODEL], made by [COMPANY]."},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "I'm [MODEL]."},
]}


def test_identity_resolution_only():
    [row] = adapt_dataset.adapt_rows([NEUTRAL], families.DEEPSEEK)
    assert row["messages"][0]["content"] == "You are DeepSeek, made by DeepSeek."
    assert row["messages"][2]["content"] == "I'm DeepSeek."
    # render-time decision: no thinking tokens in the text, for ANY family
    text = " ".join(m["content"] for m in row["messages"])
    assert "/no_think" not in text and "<think>" not in text


def test_input_not_mutated():
    before = NEUTRAL["messages"][0]["content"]
    adapt_dataset.adapt_rows([NEUTRAL], families.QWEN3)
    assert NEUTRAL["messages"][0]["content"] == before
