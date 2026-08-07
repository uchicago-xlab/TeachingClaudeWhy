"""summarize.py's truncation column — the native-CoT variant's failure mode
(truncated samples grade non-harmful and silently deflate rates).

Loaded by path under a distinct module name for the reason
test_msm_summarize_arms.py documents: `summarize` is also the name of the
misalignment_eval module test_summarize_labels.py imports, and two modules of
one name cannot share sys.modules. A plain `import summarize` here passes when
this file runs alone and fails with AttributeError in a full-suite run, because
"labels" sorts before "trunc" and gets to sys.modules first.
"""

import importlib.util
import sys
import types
from pathlib import Path

MSM_SUMMARIZE = Path(__file__).resolve().parents[2] / "msm_eval" / "summarize.py"
_spec = importlib.util.spec_from_file_location("msm_summarize", MSM_SUMMARIZE)
summarize = importlib.util.module_from_spec(_spec)
sys.modules["msm_summarize"] = summarize
_spec.loader.exec_module(summarize)


def full_grid(h, n, t):
    return {(sc, g): [h, n, t] for sc in summarize.SCENARIOS for g in summarize.GOALS}


def test_table_has_trunc_column():
    table = summarize.render({"run-natcot": full_grid(1, 30, 5)})
    head, _, row = table.splitlines()[:3]
    assert "trunc" in head
    assert "30/180" in row          # 6 conditions x 5 truncated out of 6 x 30


def test_csv_has_truncated_column(tmp_path):
    out = tmp_path / "o.csv"
    summarize.write_csv({"r": full_grid(2, 30, 1)}, out)
    lines = out.read_text().splitlines()
    assert lines[0].split(",") == ["run", "scenario", "goal", "harmful", "n", "rate", "truncated"]
    assert lines[1].endswith(",1")


def make_sample(harmful, stop_reason):
    """A stub with exactly the attributes rates() touches."""
    score = types.SimpleNamespace(value={"harmful": 1.0 if harmful else 0.0})
    return types.SimpleNamespace(
        scores={"harmfulness_scorer": score},
        output=types.SimpleNamespace(stop_reason=stop_reason),
    )


def test_rates_counts_max_tokens_samples_as_truncated(monkeypatch, tmp_path):
    """The column has to come from the logs, not just render cleanly.

    A truncated sample still scores — non-harmful, because the model never got
    to the harmful act — so it is counted in both n and trunc but not harmful.
    """
    log = types.SimpleNamespace(
        samples=[
            make_sample(True, "stop"),
            make_sample(False, "max_tokens"),
            make_sample(False, "max_tokens"),
            make_sample(False, "stop"),
        ],
        eval=types.SimpleNamespace(
            task_args={"scenario": "murder", "goal_type": "explicit"},
        ),
    )
    monkeypatch.setattr(summarize, "list_eval_logs",
                        lambda path: [types.SimpleNamespace(name=f"{path}/log.eval")])
    monkeypatch.setattr(summarize, "read_eval_log", lambda name: log)
    monkeypatch.setattr(summarize, "REPO", tmp_path)

    assert summarize.rates("run-natcot")[("murder", "goal-on")] == [1, 4, 2]
