"""summarize.py's truncation column — the native-CoT variant's failure mode (a
sample cut off before it acts often loses its action and grades non-harmful,
silently deflating the rate).

Only "often": as summarize.py's docstring says, a sample that emitted its tool
call and then ran into the cap is counted here and still grades harmful. The
column is a caveat flag, not a reliability metric.

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

from inspect_ai.model import ModelOutput

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


def make_sample(harmful, output):
    """A stub sample carrying a REAL ModelOutput.

    Only the sample wrapper is faked. stop_reason is a property over
    `choices[0]`, so a SimpleNamespace with a plain stop_reason attribute is not
    the thing rates() actually reads — it cannot reach the empty-choices branch,
    and it drifts silently the moment the guard changes shape.
    """
    score = types.SimpleNamespace(value={"harmful": 1.0 if harmful else 0.0})
    return types.SimpleNamespace(scores={"harmfulness_scorer": score}, output=output)


def out(stop_reason):
    return ModelOutput.from_content("m", "text", stop_reason=stop_reason)


def test_rates_counts_max_tokens_samples_as_truncated(monkeypatch, tmp_path):
    """The column has to come from the logs, not just render cleanly.

    A truncated sample still scores, and the two stubbed here score non-harmful
    — the cap landed before the act — so they are counted in n and trunc but not
    in harmful. That is the common case, not a rule: had one already emitted its
    tool call, it would still grade harmful and still be counted in trunc.
    """
    log = types.SimpleNamespace(
        samples=[
            make_sample(True, out("stop")),
            make_sample(False, out("max_tokens")),
            make_sample(False, out("max_tokens")),
            make_sample(False, out("stop")),
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


def test_a_sample_with_no_choices_is_counted_but_does_not_raise(monkeypatch, tmp_path):
    """An errored sample has `output.choices == []`, and `output.stop_reason` is
    a property over `choices[0]` — reading it unguarded raises IndexError and
    takes down the whole table, including every healthy run named alongside it.

    A bare ModelOutput() is exactly what inspect_ai leaves on a sample whose
    generation errored: `choices` defaults to [].
    """
    log = types.SimpleNamespace(
        samples=[
            make_sample(True, out("stop")),
            make_sample(False, out("max_tokens")),
            make_sample(False, ModelOutput()),  # errored: no choices at all
        ],
        eval=types.SimpleNamespace(
            task_args={"scenario": "leaking", "goal_type": "none"},
        ),
    )
    monkeypatch.setattr(summarize, "list_eval_logs",
                        lambda path: [types.SimpleNamespace(name=f"{path}/log.eval")])
    monkeypatch.setattr(summarize, "read_eval_log", lambda name: log)
    monkeypatch.setattr(summarize, "REPO", tmp_path)

    # The errored sample is in n (it was run) but not in trunc (unknowable).
    assert summarize.rates("old-run")[("leaking", "goal-off")] == [1, 3, 1]
