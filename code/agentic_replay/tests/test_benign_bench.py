import argparse
import asyncio
import json

import pytest

import benign_bench
import families

ROW = {"id": 7, "query": "Weather in Oslo?",
       "tools": [{"name": "get_weather", "parameters": {"city": {"type": "str"}}},
                 {"name": "get_time", "parameters": {"city": {"type": "str"}}}],
       "answers": [{"name": "get_weather", "arguments": {"city": "Oslo"}}]}


def test_score_sample_valid_and_matching():
    s = benign_bench.score_sample(ROW, '{"name": "get_weather", "arguments": {"city": "Oslo"}}', "stop")
    assert s == {"valid": True, "name_match": True, "truncated": False, "reason": None}


def test_score_sample_valid_but_wrong_function():
    s = benign_bench.score_sample(ROW, '{"name": "get_time", "arguments": {"city": "Oslo"}}', "stop")
    assert s["valid"] is True and s["name_match"] is False


def test_score_sample_invalid_and_truncated_paths():
    s = benign_bench.score_sample(ROW, "I'd be happy to help!", "stop")
    assert s["valid"] is False and s["reason"] == "no parseable call"
    s = benign_bench.score_sample(ROW, '{"name": "get_weather", "arguments": {}}', "length")
    assert s["valid"] is False and s["truncated"] is True


def test_summarize_scores_rates():
    scores = [
        {"valid": True, "name_match": True, "truncated": False, "reason": None},
        {"valid": True, "name_match": False, "truncated": False, "reason": None},
        {"valid": False, "name_match": False, "truncated": True, "reason": "truncated"},
        {"valid": False, "name_match": False, "truncated": False, "reason": "no parseable call"},
    ]
    out = benign_bench.summarize_scores(scores)
    assert out["n"] == 4
    assert out["valid_rate"] == 0.5
    assert out["name_match_rate"] == 0.25
    assert out["trunc_rate"] == 0.25
    assert out["reasons"] == {"truncated": 1, "no parseable call": 1}


def test_score_sample_counts_openai_style_stringified_arguments_as_acting():
    # fc.parse_call accepts arguments as a JSON string on purpose: the endpoint
    # is whether the model acts, not which serialization it picked.
    s = benign_bench.score_sample(
        ROW, '{"name": "get_weather", "arguments": "{\\"city\\": \\"Oslo\\"}"}', "stop")
    assert s["valid"] is True and s["name_match"] is True


# --- run_bench wiring, offline (no client, no network) ---

CALL = '{"name": "get_weather", "arguments": {"city": "Oslo"}}'


class FakeSeq:
    def __init__(self, tokens, stop_reason):
        self.tokens, self.stop_reason = tokens, stop_reason


class FakeResult:
    def __init__(self, seqs):
        self.sequences = seqs


class FakeClient:
    """Replies with texts[i] for the i'th row; the last text repeats."""
    def __init__(self, tok, texts, stop_reason="stop"):
        self.tok, self.texts, self.stop_reason, self.calls = tok, list(texts), stop_reason, 0

    async def sample_async(self, prompt, num_samples, sampling_params):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return FakeResult([FakeSeq(self.tok.encode(text, add_special_tokens=False),
                                   self.stop_reason)])


def _bench(client, tok, rows, **kw):
    model = families.MODELS["Qwen/Qwen3-8B"]
    kw = {"shape": "off", "max_tokens": 64, "temperature": 0.7, "seed": 0, **kw}
    return asyncio.run(benign_bench.run_bench(
        client, __import__("tinker"), tok, model, rows, **kw))


def test_run_bench_scores_every_row_and_keeps_its_id(qwen3_tok):
    rows = [dict(ROW, id=1), dict(ROW, id=2)]
    client = FakeClient(qwen3_tok, [CALL, "I cannot call functions."])
    scores = _bench(client, qwen3_tok, rows)
    assert [s["id"] for s in scores] == [1, 2]
    assert scores[0]["valid"] is True and scores[0]["name_match"] is True
    assert scores[1]["valid"] is False and scores[1]["reason"] == "no parseable call"
    # Nothing is filtered or resampled: the benchmark scores what it gets.
    assert client.calls == 2


def test_run_bench_marks_length_stops_truncated(qwen3_tok):
    client = FakeClient(qwen3_tok, [CALL], stop_reason="length")
    scores = _bench(client, qwen3_tok, [ROW])
    assert scores[0] == {"id": 7, "final": CALL, "valid": False, "name_match": False,
                         "truncated": True, "reason": "truncated"}


def test_run_bench_native_scores_the_final_answer_not_the_reasoning(qwen3_tok):
    # A distractor call inside the CoT: parse_call takes the FIRST call it finds,
    # so name-match is right only because the think block was stripped before
    # scoring. Scoring the raw sample would report get_time.
    text = ('<think>\nmaybe {"name": "get_time", "arguments": {"city": "Oslo"}}?\n'
            '</think>\n\n' + CALL)
    scores = _bench(FakeClient(qwen3_tok, [text]), qwen3_tok, [ROW], shape="native")
    assert scores[0]["valid"] is True and scores[0]["name_match"] is True


def test_run_bench_stores_the_sampled_text_beside_the_score(qwen3_tok):
    scores = _bench(FakeClient(qwen3_tok, ["I cannot call functions."]), qwen3_tok, [ROW])
    assert scores[0]["final"].strip() == "I cannot call functions."


# --- run(): the paid path, driven offline ---


def _run_args(tmp_path, **kw):
    return argparse.Namespace(**{"model": "Qwen/Qwen3-8B", "checkpoint": None, "shape": "off",
                                 "run_name": "bench-base-off", "temperature": 0.7, "seed": 0,
                                 "yes": True, "force": False, **kw})


def _patch_run(monkeypatch, tmp_path, qwen3_tok, client):
    """Point run() at a temp prompts file and bench dir; no network, no spend."""
    import render

    prompts = tmp_path / "fc-bench.jsonl"
    prompts.write_text(json.dumps(ROW) + "\n")
    monkeypatch.setattr(benign_bench, "BENCH_PROMPTS", prompts)
    monkeypatch.setattr(benign_bench, "BENCH_DIR", tmp_path / "bench")
    monkeypatch.setattr(benign_bench, "price_for", lambda mid: {"sample": "$0.20"})
    monkeypatch.setattr(render, "load_tokenizer", lambda model: qwen3_tok)
    monkeypatch.setattr(benign_bench.tinker_sampling, "make_client",
                        lambda mid, ckpt=None: client)
    return tmp_path / "bench" / "bench-base-off.json"


def test_run_saves_scores_carrying_the_sampled_text(monkeypatch, tmp_path, qwen3_tok, capsys):
    # Reading a rate drop means reading what the model said; a paid run that
    # stored only its own scores would have to be re-bought to be understood.
    out = _patch_run(monkeypatch, tmp_path, qwen3_tok, FakeClient(qwen3_tok, [CALL]))
    asyncio.run(benign_bench.run(_run_args(tmp_path)))
    saved = json.loads(out.read_text())
    assert saved["summary"]["n"] == 1 and saved["summary"]["valid_rate"] == 1.0
    assert saved["scores"][0]["final"].strip() == CALL
    assert saved["scores"][0]["id"] == 7
    assert "cost <= ~$0.00" in capsys.readouterr().out   # 1 row * 1024 tok * $0.20/Mtok


def test_run_refuses_to_overwrite_an_existing_result(monkeypatch, tmp_path, qwen3_tok):
    def no_client(*a, **kw):
        raise AssertionError("client built despite the name collision — that is the spend")

    out = _patch_run(monkeypatch, tmp_path, qwen3_tok, FakeClient(qwen3_tok, [CALL]))
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"run_name": "bench-base-off", "scores": ["precious"]}))
    monkeypatch.setattr(benign_bench.tinker_sampling, "make_client", no_client)

    with pytest.raises(SystemExit) as exc:
        asyncio.run(benign_bench.run(_run_args(tmp_path)))
    assert str(out) in str(exc.value) and "--force" in str(exc.value)
    assert json.loads(out.read_text())["scores"] == ["precious"]   # untouched


def test_run_force_overwrites(monkeypatch, tmp_path, qwen3_tok):
    out = _patch_run(monkeypatch, tmp_path, qwen3_tok, FakeClient(qwen3_tok, [CALL]))
    out.parent.mkdir(parents=True)
    out.write_text(json.dumps({"run_name": "bench-base-off", "scores": ["stale"]}))
    asyncio.run(benign_bench.run(_run_args(tmp_path, force=True)))
    assert json.loads(out.read_text())["scores"][0]["id"] == 7


def test_print_table_reads_saved_results(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(benign_bench, "BENCH_DIR", tmp_path)
    benign_bench.print_table()
    assert "no results" in capsys.readouterr().out
    (tmp_path / "bench-base-off.json").write_text(json.dumps(
        {"run_name": "bench-base-off",
         "summary": {"n": 4, "valid_rate": 0.5, "name_match_rate": 0.25, "trunc_rate": 0.25}}))
    benign_bench.print_table()
    out = capsys.readouterr().out
    assert "bench-base-off" in out and "0.500" in out and "0.250" in out
