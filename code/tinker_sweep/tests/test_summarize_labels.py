"""summarize.py must not pool a sweep's three arms into one rate.

Lives here rather than beside summarize.py because the failure it guards is a
tinker-sweep failure: base / sonnet-ft / terra-ft all report the same
`log.eval.model`, and the checkpoint travels only in `model_args`.

No real checkpoint log exists yet (that needs a paid run), so the logs here are
stubs shaped like the fields collect() reads.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "misalignment_eval"))
import summarize  # noqa: E402


SONNET_CKPT = "tinker://service/run-abc/sampler_weights/00042"
TERRA_CKPT = "tinker://service/run-xyz/sampler_weights/00042"


def make_log(model, model_args, harmful):
    """A stub with exactly the attributes collect() touches."""
    score = types.SimpleNamespace(value={"harmful": harmful})
    sample = types.SimpleNamespace(scores={"harmfulness": score})
    return types.SimpleNamespace(
        status="success",
        samples=[sample],
        eval=types.SimpleNamespace(
            model=model,
            model_args=model_args,
            task_args={"scenario": "murder", "goal_type": "explicit",
                       "goal_value": "america", "urgency_type": "replacement"},
        ),
    )


# ------------------------------------------------------------------- model_label


def test_base_run_keeps_the_bare_model_id():
    log = make_log("tinker/Qwen/Qwen3-8B", {}, False)
    assert summarize.model_label(log, Path("/logs/tinker-qwen3-8b/x.eval")) == "tinker/Qwen/Qwen3-8B"


def test_teammate_log_with_unrelated_model_args_is_untouched():
    log = make_log("together/meta-llama/Llama-3.3-70B", {"base_url": "https://x"}, True)
    assert summarize.model_label(log, Path("/logs/llama-70b/x.eval")) == "together/meta-llama/Llama-3.3-70B"


def test_checkpoint_run_gets_its_own_label():
    log = make_log("tinker/Qwen/Qwen3-8B", {"checkpoint": SONNET_CKPT}, True)
    label = summarize.model_label(log, Path("/logs/whatever/x.eval"))
    assert label != "tinker/Qwen/Qwen3-8B"
    assert label.startswith("tinker/Qwen/Qwen3-8B [ckpt:")


def test_two_checkpoints_sharing_a_path_tail_stay_distinct():
    """Both URIs end `sampler_weights/00042`; only the digest separates them."""
    a = summarize.model_label(make_log("m", {"checkpoint": SONNET_CKPT}, True), Path("/l/a/x.eval"))
    b = summarize.model_label(make_log("m", {"checkpoint": TERRA_CKPT}, True), Path("/l/b/x.eval"))
    assert a != b


def test_parent_dir_fallback_when_the_header_lost_model_args():
    """run_eval.py names a checkpoint run's dir `…-ckpt-<slug>`, so the dir still carries it."""
    log = make_log("tinker/Qwen/Qwen3-8B", {}, True)
    label = summarize.model_label(log, Path("/logs/tinker-qwen-qwen3-8b-ckpt-weights-00042-a1b2c3/x.eval"))
    assert label == "tinker/Qwen/Qwen3-8B [ckpt:tinker-qwen-qwen3-8b-ckpt-weights-00042-a1b2c3]"


def test_label_matches_run_eval_so_dir_and_row_agree():
    """The row label must be readable against the log directory run_eval created."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "misalignment_eval"))
    import run_eval

    assert summarize.checkpoint_slug(SONNET_CKPT) == run_eval.checkpoint_slug(SONNET_CKPT)


# ------------------------------------------------------------------- collect()


def test_collect_does_not_pool_the_three_arms(monkeypatch, tmp_path):
    """The regression itself: base + two finetunes of one model, same model id."""
    logs = {
        "base": make_log("tinker/Qwen/Qwen3-8B", {}, True),
        "sonnet": make_log("tinker/Qwen/Qwen3-8B", {"checkpoint": SONNET_CKPT}, False),
        "terra": make_log("tinker/Qwen/Qwen3-8B", {"checkpoint": TERRA_CKPT}, False),
    }
    infos = [types.SimpleNamespace(name=f"{tmp_path}/{arm}/log.eval") for arm in logs]
    by_name = {info.name: logs[Path(info.name).parent.name] for info in infos}
    monkeypatch.setattr(summarize, "list_eval_logs", lambda *a, **k: infos)
    monkeypatch.setattr(summarize, "read_eval_log", lambda info: by_name[info.name])

    rows = summarize.collect(tmp_path)
    labels = {r["model"] for r in rows}
    assert len(labels) == 3, f"arms pooled into {labels}"
    # Pooled, the 1/3 harmful rate would read as 0.33 for the whole model and hide
    # that the base arm is 1.0 and both finetunes are 0.0.
    assert sorted(r["harmful_rate"] for r in rows) == [0.0, 0.0, 1.0]


def test_collect_leaves_non_checkpoint_rows_on_the_bare_model_id(monkeypatch, tmp_path):
    info = types.SimpleNamespace(name=f"{tmp_path}/together-llama/log.eval")
    monkeypatch.setattr(summarize, "list_eval_logs", lambda *a, **k: [info])
    monkeypatch.setattr(summarize, "read_eval_log",
                        lambda i: make_log("together/meta-llama/Llama-3.3-70B", {}, True))
    (rows,) = summarize.collect(tmp_path)
    assert rows["model"] == "together/meta-llama/Llama-3.3-70B"
