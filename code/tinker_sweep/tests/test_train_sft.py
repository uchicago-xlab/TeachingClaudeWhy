import dataclasses
import json
import math

import pytest

import families
import train_sft


# ---------------------------------------------------------------- schedule/batching


def test_cosine_lr_shape():
    total, base = 100, 1e-4
    assert train_sft.cosine_lr(0, total, base) < base * 0.5        # warmup start
    warm_end = math.ceil(total * 0.03)
    assert train_sft.cosine_lr(warm_end, total, base) == base       # warmup peak
    assert train_sft.cosine_lr(total - 1, total, base) < base * 0.01  # cosine tail


def test_batches_cover_all_rows_and_reshuffle():
    rows = [{"i": i} for i in range(10)]
    b1 = train_sft.make_batches(rows, batch_size=3, seed=0, epoch=1)
    assert sorted(r["i"] for batch in b1 for r in batch) == list(range(10))
    assert [len(b) for b in b1] == [3, 3, 3, 1]
    b2 = train_sft.make_batches(rows, batch_size=3, seed=0, epoch=2)
    assert b1 != b2                       # epoch changes the shuffle
    assert b1 == train_sft.make_batches(rows, batch_size=3, seed=0, epoch=1)  # deterministic


def test_select_best_is_min_val_loss():
    cps = [{"epoch": 1, "val_loss": 1.5}, {"epoch": 2, "val_loss": 1.2},
           {"epoch": 3, "val_loss": 1.3}]
    assert train_sft.select_best(cps)["epoch"] == 2


# ---------------------------------------------------------------- verified-family gate


def _unverified_model():
    real = families.get_model("Qwen/Qwen3-8B")
    return dataclasses.replace(real, family=dataclasses.replace(real.family, verified=False))


def test_unverified_family_is_refused_before_any_row_is_read():
    with pytest.raises(RuntimeError, match="not verified"):
        train_sft.load_splits(_unverified_model(), "sonnet")


def test_load_splits_accepts_a_verified_family():
    train, val = train_sft.load_splits(families.get_model("Qwen/Qwen3-8B"), "sonnet")
    assert train.rows and val.rows
    assert train.path.name == "sonnet08-train.jsonl"
    assert all("messages" in r for r in train.rows)


# ---------------------------------------------------------------- empty-completion gate

SUFFIX = [90, 91]  # stand-in for a family's turn suffix (e.g. <|im_end|>\n)


def test_completion_span_is_the_weighted_tail():
    tokens, weights = [1, 2, 3, 4, 5], [0, 0, 1, 1, 1]
    assert train_sft.completion_span(tokens, weights) == [3, 4, 5]


def test_zero_token_completion_is_rejected():
    examples = [([1, 2, 3], [0, 0, 0])]
    with pytest.raises(SystemExit, match="row 0"):
        train_sft.check_completions(examples, SUFFIX, "some/file.jsonl")


def test_suffix_only_completion_is_rejected():
    examples = [([1, 2, 3, 4], [0, 0, 1, 1])]  # completion == SUFFIX, i.e. a bare EOS
    with pytest.raises(SystemExit, match="only the turn suffix"):
        train_sft.check_completions(examples, [3, 4], "some/file.jsonl")


def test_real_completion_passes_and_reports_the_offending_row_index():
    good = ([1, 2, 7, 8, 90, 91], [0, 0, 1, 1, 1, 1])
    train_sft.check_completions([good, good], SUFFIX, "some/file.jsonl")  # no raise
    with pytest.raises(SystemExit, match="row 1"):
        train_sft.check_completions([good, ([1, 2], [0, 0])], SUFFIX, "some/file.jsonl")


# ---------------------------------------------------------------- loss math


def test_mean_nll_is_weighted_per_token():
    # only the weighted positions count: mean of 2.0 and 4.0
    num, den = train_sft.nll_sums([[-1.0, -2.0, -4.0]], [[0.0, 1.0, 1.0]])
    assert num / den == 3.0
    # accumulating across chunks matches scoring everything at once
    n2, d2 = train_sft.nll_sums([[-1.0, -2.0]], [[1.0, 1.0]])
    assert (num + n2) / (den + d2) == pytest.approx((2 + 4 + 1 + 2) / 4)


def test_mean_nll_rejects_an_all_zero_weight_batch():
    with pytest.raises(ZeroDivisionError):
        num, den = train_sft.nll_sums([[-1.0]], [[0.0]])
        num / den


# ---------------------------------------------------------------- Datum shift convention


def test_to_datums_shifts_targets_and_weights_by_one():
    import tinker  # types only; no client, no API call

    tokens, weights = [11, 12, 13, 14], [0, 0, 1, 1]
    (datum,) = train_sft.to_datums(tinker, [(tokens, weights)])
    assert datum.model_input.to_ints() == [11, 12, 13]          # inputs drop the last token
    assert datum.loss_fn_inputs["target_tokens"].tolist() == [12, 13, 14]
    assert datum.loss_fn_inputs["weights"].tolist() == [0.0, 1.0, 1.0]


# ---------------------------------------------------------------- lr resolution


def test_lr_override_wins_and_is_labelled():
    assert train_sft.resolve_lr("whatever", 1e-5, lambda m: 9.9) == (1e-5, "--lr")


def test_uncalibrated_model_yields_no_lr_rather_than_a_guess():
    def uncalibrated(_model):
        raise NotImplementedError("not yet calibrated")

    assert train_sft.resolve_lr("nvidia/Big", None, uncalibrated) == (None, "uncalibrated")
    assert train_sft.resolve_lr("Qwen/Qwen3-8B", None, lambda m: 4.7e-4) == (4.7e-4, "cookbook")


# ---------------------------------------------------------------- price table


def test_price_falls_back_to_cache_when_the_fetch_fails(tmp_path, monkeypatch):
    cache = tmp_path / "models-prices.json"
    cache.write_text(json.dumps([{"tinker_id": "Qwen/Qwen3-8B", "train": "$0.44"}]))
    monkeypatch.setattr(train_sft, "MODELS_JSON_CACHE", cache)
    monkeypatch.setattr(train_sft, "_fetch_models_json", lambda: (_ for _ in ()).throw(OSError()))
    assert train_sft.price_for("Qwen/Qwen3-8B") == {"tinker_id": "Qwen/Qwen3-8B", "train": "$0.44"}


def test_price_is_none_when_there_is_neither_a_fetch_nor_a_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(train_sft, "MODELS_JSON_CACHE", tmp_path / "absent.json")
    monkeypatch.setattr(train_sft, "_fetch_models_json", lambda: (_ for _ in ()).throw(OSError()))
    assert train_sft.price_for("Qwen/Qwen3-8B") is None


def test_price_is_none_for_a_model_missing_from_the_table(tmp_path, monkeypatch):
    cache = tmp_path / "models-prices.json"
    cache.write_text(json.dumps([{"tinker_id": "other/model", "train": "$1.00"}]))
    monkeypatch.setattr(train_sft, "MODELS_JSON_CACHE", cache)
    monkeypatch.setattr(train_sft, "_fetch_models_json", lambda: (_ for _ in ()).throw(OSError()))
    assert train_sft.price_for("Qwen/Qwen3-8B") is None
