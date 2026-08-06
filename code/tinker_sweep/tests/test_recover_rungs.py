import json
from pathlib import Path

import pytest

import recover_rungs

DA = Path(__file__).resolve().parents[3] / "data" / "difficult-advice"
SONNET = DA / "claude-sonnet-5-full-filtered"
TERRA = DA / "gpt-5.6-terra"


def rows(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_legacy_adapt_matches_committed_shape():
    neutral = {"messages": [
        {"role": "system", "content": "You are [MODEL], made by [COMPANY]."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello."},
    ]}
    out = recover_rungs.legacy_qwen_adapt(neutral)
    assert out["messages"][0]["content"] == "You are Qwen, made by Alibaba Cloud.\n\n/no_think"
    assert out["messages"][2]["content"] == "<think>\n\n</think>\n\nHello."


@pytest.mark.parametrize("adapted,pool,n", [
    (SONNET / "s5think-scale-08.jsonl", SONNET / "ft_dataset.jsonl", 165),
    (SONNET / "s5think-full-qwen-nothink-val.jsonl", SONNET / "ft_dataset.jsonl", 229),
    (TERRA / "terra-ft-qwen-nothink.jsonl", TERRA / "ft_dataset.jsonl", 135),
    (TERRA / "terra-ft-qwen-nothink-val.jsonl", TERRA / "ft_dataset.jsonl", 15),
])
def test_roundtrip_reproduces_committed_files(adapted, pool, n):
    recovered = recover_rungs.recover(adapted, rows(pool))
    assert len(recovered) == n
    committed = rows(adapted)
    readapted = [recover_rungs.legacy_qwen_adapt(r) for r in recovered]
    assert readapted == committed  # byte-equivalent modulo JSON parse
