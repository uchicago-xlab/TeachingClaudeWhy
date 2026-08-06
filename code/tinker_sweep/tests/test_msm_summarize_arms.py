"""msm_eval/summarize.py must not pool a sweep's three arms into one rate.

The sibling harness (code/misalignment_eval/summarize.py, test_summarize_labels.py)
had to grow a checkpoint label for this: it pools on `log.eval.model`, which is
byte-identical across a sweep's base / sonnet-ft / terra-ft arms because the
checkpoint travels in model_args.

msm_eval's summarize is built the other way round — a row IS a run directory,
named by the caller — so the arms stay apart as long as each gets its own
`--run-name`, which msm_eval_run.py requires. These tests pin that property, and
that reading a directory does not depend on anything in the log header, so the
Critical cannot reappear here unnoticed.

Loaded by path under a distinct module name: `summarize` is also the name of the
misalignment_eval module test_summarize_labels.py imports, and two modules of one
name cannot share sys.modules.
"""

import importlib.util
import sys
import types
from pathlib import Path

MSM_SUMMARIZE = Path(__file__).resolve().parents[2] / "msm_eval" / "summarize.py"
_spec = importlib.util.spec_from_file_location("msm_summarize", MSM_SUMMARIZE)
msm_summarize = importlib.util.module_from_spec(_spec)
sys.modules["msm_summarize"] = msm_summarize
_spec.loader.exec_module(msm_summarize)


def make_log(model, model_args, harmful, scenario="murder", goal_type="explicit"):
    """A stub with exactly the attributes rates() touches."""
    score = types.SimpleNamespace(value={"harmful": 1.0 if harmful else 0.0})
    sample = types.SimpleNamespace(scores={"harmfulness_scorer": score})
    return types.SimpleNamespace(
        samples=[sample],
        eval=types.SimpleNamespace(
            model=model, model_args=model_args,
            task_args={"scenario": scenario, "goal_type": goal_type},
        ),
    )


def wire(monkeypatch, logs_by_run):
    """Serve one stub log per run directory name."""
    monkeypatch.setattr(msm_summarize, "list_eval_logs",
                        lambda path: [types.SimpleNamespace(name=f"{path}/log.eval")])
    monkeypatch.setattr(msm_summarize, "read_eval_log",
                        lambda name: logs_by_run[Path(name).parent.name])


def test_the_three_arms_of_one_model_do_not_pool(monkeypatch, tmp_path):
    """The regression itself: same model id, checkpoint only in model_args."""
    ckpt = "tinker://service/run-abc/sampler_weights/00042"
    logs = {
        "msm-tinker-qwen-qwen3-8b": make_log("tinker/Qwen/Qwen3-8B", {}, True),
        "msm-tinker-qwen-qwen3-8b-sonnet08": make_log("tinker/Qwen/Qwen3-8B", {"checkpoint": ckpt}, False),
        "msm-tinker-qwen-qwen3-8b-terra08": make_log("tinker/Qwen/Qwen3-8B", {"checkpoint": ckpt}, False),
    }
    wire(monkeypatch, logs)
    monkeypatch.setattr(msm_summarize, "REPO", tmp_path)
    for run in logs:
        (tmp_path / "data" / "msm-eval" / run).mkdir(parents=True)

    rows = {run: msm_summarize.rates(run) for run in logs}
    assert len(rows) == 3
    # Pooled, 1 harmful in 3 would read as 33% for "the model" and hide that the
    # base arm is 100% and both finetunes are 0%.
    assert [rows[r][("murder", "goal-on")] for r in logs] == [[1, 1], [0, 1], [0, 1]]


def test_a_row_is_identified_by_its_run_directory_not_the_log_header(monkeypatch, tmp_path):
    """Two identical headers under different run names stay two rows."""
    logs = {"arm-a": make_log("m", {}, True), "arm-b": make_log("m", {}, False)}
    wire(monkeypatch, logs)
    monkeypatch.setattr(msm_summarize, "REPO", tmp_path)

    data = {name: msm_summarize.rates(name) for name in logs}
    assert data["arm-a"][("murder", "goal-on")] == [1, 1]
    assert data["arm-b"][("murder", "goal-on")] == [0, 1]
