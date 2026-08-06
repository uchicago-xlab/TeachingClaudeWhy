import argparse
import asyncio
import dataclasses
import json
import math
import sys
import types

import pytest

import families
import train_sft


# ---------------------------------------------------------------- schedule/batching


def test_cosine_lr_shape():
    total, base = 100, 1e-4
    # Warmup starts low but never at 0.0 — a zero first step throws away a batch.
    assert 0 < train_sft.cosine_lr(0, total, base) < base * 0.5
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


QWEN8B = families.get_model("Qwen/Qwen3-8B")


def _uncalibrated(_model):
    raise NotImplementedError("not yet calibrated")


def test_lr_override_wins_and_is_labelled():
    assert train_sft.resolve_lr(QWEN8B, 1e-5, lambda m: 9.9) == (1e-5, "cli")


def test_cookbook_lr_is_preferred_when_it_has_one():
    assert train_sft.resolve_lr(QWEN8B, None, lambda m: 4.7e-4) == (4.7e-4, "cookbook")


def test_uncalibrated_model_falls_back_to_the_extrapolated_formula():
    lr, source = train_sft.resolve_lr(QWEN8B, None, _uncalibrated, lambda m: 4096)
    assert source == "extrapolated"
    assert lr == pytest.approx(4.7298e-4, rel=1e-3)


def test_lr_is_none_when_even_the_hidden_size_cannot_be_resolved():
    def no_hidden_size(_model):
        raise ValueError("no config")

    assert train_sft.resolve_lr(QWEN8B, None, _uncalibrated, no_hidden_size) == (None, "unavailable")


def test_recovered_formula_reproduces_every_calibrated_cookbook_value():
    """The proof that this is the cookbook's real rule and not a lookalike.

    Reproducing all six calibrated Qwen values bit-for-bit is what licenses
    extrapolating the same formula to the models get_lr refuses.
    """
    from tinker_cookbook.hyperparam_utils import get_lr

    checked = 0
    for tinker_id, model in families.MODELS.items():
        try:
            calibrated = get_lr(tinker_id)
        except NotImplementedError:
            continue
        assert train_sft.cookbook_lr(train_sft.hidden_size_for(model)) == calibrated, tinker_id
        checked += 1
    assert checked == 6, f"expected the 6 calibrated Qwen models, saw {checked}"


def test_the_family_exponent_is_the_assumption_and_it_is_load_bearing():
    """Pins the known uncertainty: Llama's exponent would give a very different lr.

    If this ever stops holding, the extrapolation's caveat needs rewriting — it
    exists so nobody reads an extrapolated lr as a calibrated one.
    """
    qwen_at_8192 = train_sft.cookbook_lr(8192, train_sft.QWEN_EXPONENT)
    llama_at_8192 = train_sft.cookbook_lr(8192, train_sft.LLAMA_EXPONENT)
    assert qwen_at_8192 / llama_at_8192 > 2.5
    assert train_sft.EXTRAPOLATION_EXPONENT == train_sft.QWEN_EXPONENT


def test_extrapolation_stays_inside_the_calibrated_band_for_every_sweep_model():
    """The extrapolation claims little: 4.4e-4 to 5.0e-4 across all 15 models."""
    values = [train_sft.cookbook_lr(train_sft.hidden_size_for(m)) for m in families.MODELS.values()]
    assert min(values) > 4.4e-4 and max(values) < 5.0e-4


# ---------------------------------------------------------------- run-state persistence


def _base():
    return {"model": "Qwen/Qwen3-8B", "teacher": "sonnet", "lr": 4.7e-4, "seed": 0}


def test_run_state_is_readable_after_every_epoch(tmp_path):
    out = tmp_path / "runs" / "qwen" / "train-sonnet.json"  # parent does not exist yet
    checkpoints = []
    for epoch, loss in [(1, 1.5), (2, 1.2), (3, 1.3)]:
        checkpoints.append({"epoch": epoch, "sampler_path": f"tinker://ep{epoch}", "val_loss": loss})
        train_sft.write_run_state(out, _base(), checkpoints)
        state = json.loads(out.read_text())          # valid JSON at every boundary
        assert len(state["checkpoints"]) == epoch
        assert state["model"] == "Qwen/Qwen3-8B"
    # a crash after epoch 3 still leaves every paid checkpoint on disk, best-so-far chosen
    state = json.loads(out.read_text())
    assert [c["sampler_path"] for c in state["checkpoints"]] == [
        "tinker://ep1", "tinker://ep2", "tinker://ep3"]
    assert state["selected"]["epoch"] == 2


def test_run_state_selected_is_null_before_any_checkpoint(tmp_path):
    out = tmp_path / "train-sonnet.json"
    assert train_sft.write_run_state(out, _base(), [])["selected"] is None


def test_run_state_is_written_atomically(tmp_path):
    """The write is temp-file + os.replace: no truncated state, no leftover temp."""
    out = tmp_path / "train-sonnet.json"
    train_sft.write_run_state(out, _base(), [])
    train_sft.write_run_state(out, _base(), [{"epoch": 1, "sampler_path": "tinker://ep1", "val_loss": 1.0}])
    assert [p.name for p in tmp_path.iterdir()] == ["train-sonnet.json"]
    assert json.loads(out.read_text())["selected"]["epoch"] == 1


# ---------------------------------------------------------------- seeded LoRA init


def test_seed_reaches_the_training_client_helper(monkeypatch):
    seen = {}

    class StubServiceClient:
        async def create_lora_training_client_async(self, **kwargs):
            seen.update(kwargs)
            return "client"

    got = asyncio.run(train_sft.make_training_client(StubServiceClient(), "Qwen/Qwen3-8B", 64, 7))
    assert got == "client"
    assert seen == {"base_model": "Qwen/Qwen3-8B", "rank": 64, "seed": 7}


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


# ---------------------------------------------------------------- full --yes path, stubbed
#
# Everything past the --yes gate is otherwise untested until a paid run. These
# stubs drive the real run() with a fake tinker module so the loop's own wiring
# — seed plumbing, per-epoch persistence, cosine schedule, checkpoint bookkeeping
# — is verified without an API call.


class _Future:
    def __init__(self, value):
        self._value = value

    async def result_async(self):
        return self._value


class _Tensor:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


class _FwdOut:
    def __init__(self, datums):
        # one logprob per target token, constant so the val loss is predictable
        self.loss_fn_outputs = [
            {"logprobs": _Tensor([-2.0] * len(d.loss_fn_inputs["target_tokens"]))} for d in datums
        ]


class _Datum:
    def __init__(self, model_input, loss_fn_inputs):
        self.model_input = model_input
        self.loss_fn_inputs = loss_fn_inputs


class _ModelInput:
    def __init__(self, tokens):
        self.tokens = tokens

    @classmethod
    def from_ints(cls, tokens):
        return cls(tokens)


class _TrainingClient:
    def __init__(self, log, fail_saving_at_epoch=None):
        self.log = log
        self.fail_saving_at_epoch = fail_saving_at_epoch
        self.saves = 0

    async def forward_backward_async(self, datums, loss_fn):
        self.log["batches"].append(len(datums))
        return _Future(_FwdOut(datums))

    async def optim_step_async(self, adam_params):
        self.log["lrs"].append(adam_params.learning_rate)
        return _Future(None)

    async def forward_async(self, datums, loss_fn):
        return _Future(_FwdOut(datums))

    async def save_weights_for_sampler_async(self, name):
        self.saves += 1
        if self.saves == self.fail_saving_at_epoch:
            raise RuntimeError("simulated tinker outage")
        self.log["names"].append(name)
        return _Future(type("R", (), {"path": f"tinker://{name}"})())


def _fake_tinker(log, fail_saving_at_epoch=None):
    class _ServiceClient:
        def __init__(self, *a, **k):
            pass

        async def create_lora_training_client_async(self, **kwargs):
            log["client_kwargs"] = kwargs
            return _TrainingClient(log, fail_saving_at_epoch)

    return types.SimpleNamespace(
        Datum=_Datum, ModelInput=_ModelInput, ServiceClient=_ServiceClient,
        AdamParams=lambda learning_rate: types.SimpleNamespace(learning_rate=learning_rate),
    )


@pytest.fixture
def tiny_dataset(tmp_path, monkeypatch):
    rows = [
        {"messages": [{"role": "system", "content": "You are Qwen."},
                      {"role": "user", "content": f"Question {i}?"},
                      {"role": "assistant", "content": f"A considered answer number {i}."}]}
        for i in range(4)
    ]
    fam_dir = tmp_path / "qwen3"
    fam_dir.mkdir()
    for name in ("sonnet08-train", "sonnet-val"):
        (fam_dir / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(train_sft, "ADAPTED_DIR", tmp_path)
    return tmp_path


def _args(tmp_path, **over):
    defaults = dict(model="Qwen/Qwen3-8B", teacher="sonnet", epochs=3, batch_size=2,
                    lr=1e-4, seed=7, run_dir=str(tmp_path / "runs"), yes=True)
    return argparse.Namespace(**{**defaults, **over})


def test_yes_path_seeds_the_client_and_persists_after_every_epoch(tiny_dataset, monkeypatch):
    log = {"batches": [], "lrs": [], "names": []}
    monkeypatch.setitem(sys.modules, "tinker", _fake_tinker(log))
    args = _args(tiny_dataset)

    asyncio.run(train_sft.run(args))

    # F2: the seed reaches LoRA init, not just the batch shuffle
    assert log["client_kwargs"] == {"base_model": "Qwen/Qwen3-8B", "rank": 64, "seed": 7}
    # 4 rows / batch 2 = 2 steps per epoch, 3 epochs
    assert log["batches"] == [2, 2, 2, 2, 2, 2]
    assert log["names"] == ["qwen-qwen3-8b-sonnet08-ep1", "qwen-qwen3-8b-sonnet08-ep2",
                            "qwen-qwen3-8b-sonnet08-ep3"]
    # cosine schedule: warmup (one step at this size) then decay to ~0. The first
    # step must carry real lr — training it at 0.0 would waste a paid batch.
    assert log["lrs"][0] == pytest.approx(1e-4) and log["lrs"][1] == pytest.approx(1e-4)
    assert log["lrs"][-1] < 1e-5

    state = json.loads((tiny_dataset / "runs" / "train-sonnet.json").read_text())
    assert len(state["checkpoints"]) == 3
    assert state["seed"] == 7 and state["lr"] == 1e-4 and state["lr_source"] == "cli"
    assert state["selected"]["sampler_path"].startswith("tinker://")


def test_a_crash_mid_run_leaves_the_earlier_paid_checkpoints_on_disk(tiny_dataset, monkeypatch):
    """F1: dying at epoch 3 must not discard the epoch 1-2 tinker:// paths."""
    log = {"batches": [], "lrs": [], "names": []}
    monkeypatch.setitem(sys.modules, "tinker", _fake_tinker(log, fail_saving_at_epoch=3))
    args = _args(tiny_dataset)

    with pytest.raises(RuntimeError, match="simulated tinker outage"):
        asyncio.run(train_sft.run(args))

    state = json.loads((tiny_dataset / "runs" / "train-sonnet.json").read_text())
    assert [c["epoch"] for c in state["checkpoints"]] == [1, 2]
    assert [c["sampler_path"] for c in state["checkpoints"]] == [
        "tinker://qwen-qwen3-8b-sonnet08-ep1", "tinker://qwen-qwen3-8b-sonnet08-ep2"]
    assert state["selected"] is not None
