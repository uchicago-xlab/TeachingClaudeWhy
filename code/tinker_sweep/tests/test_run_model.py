import json

import pytest

import families
import run_model


def test_stage_order_and_commands():
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=18, preset="core", train_epochs=4)
    assert [s.name for s in plan] == [
        "adapt", "check_render", "train-sonnet", "train-terra",
        "eval-base", "eval-sonnet", "eval-terra",
    ]
    eval_sonnet = next(s for s in plan if s.name == "eval-sonnet")
    cmd = " ".join(eval_sonnet.command)
    assert "--model tinker/Qwen/Qwen3-8B" in cmd
    assert "--run-name tinker-qwen-qwen3-8b-sonnet08" in cmd
    assert "checkpoint=" in cmd  # placeholder resolved at run time from train state


def test_state_skips_completed_and_redo_forces(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"stages": {"adapt": {"status": "done"}}}))
    state = run_model.load_state(state_path)
    assert run_model.should_run("adapt", state, redo=None) is False
    assert run_model.should_run("adapt", state, redo="adapt") is True
    assert run_model.should_run("train-sonnet", state, redo=None) is True


def test_a_failed_stage_is_rerun_without_redo(tmp_path):
    """The point of the state file is resume, not a tombstone: only "done" skips."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"stages": {"train-terra": {"status": "failed"}}}))
    state = run_model.load_state(state_path)
    assert run_model.should_run("train-terra", state, redo=None) is True


def test_missing_state_file_runs_everything(tmp_path):
    state = run_model.load_state(tmp_path / "nope.json")
    assert all(run_model.should_run(name, state, redo=None) for name in run_model.STAGES)


def test_base_eval_carries_no_checkpoint_arg():
    """A stray checkpoint= on the base arm would evaluate a finetune as the baseline."""
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=18, preset="core", train_epochs=4)
    base = next(s for s in plan if s.name == "eval-base")
    assert "checkpoint" not in " ".join(base.command)
    assert base.checkpoint_from is None
    assert "--run-name tinker-qwen-qwen3-8b" in " ".join(base.command)


def test_train_stages_carry_yes_and_the_run_dir():
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=18, preset="core", train_epochs=2)
    train = next(s for s in plan if s.name == "train-terra")
    cmd = " ".join(train.command)
    assert "--teacher terra" in cmd and "--epochs 2" in cmd and "--yes" in cmd
    assert f"--run-dir {run_model.HERE / 'runs' / 'qwen-qwen3-8b'}" in cmd


def test_adapt_stage_targets_the_models_family():
    plan = run_model.build_plan("moonshotai/Kimi-K2.6", eval_epochs=18, preset="core", train_epochs=4)
    adapt = next(s for s in plan if s.name == "adapt")
    assert "--family kimi_k2_6" in " ".join(adapt.command)


def test_unknown_model_is_a_hard_error():
    with pytest.raises(KeyError):
        run_model.build_plan("Qwen/Qwen3-14B", eval_epochs=18, preset="core", train_epochs=4)


def test_every_sweep_model_builds_a_plan():
    for model in families.MODELS:
        plan = run_model.build_plan(model, eval_epochs=18, preset="core", train_epochs=4)
        assert [s.name for s in plan] == list(run_model.STAGES)


# ------------------------------------------------------------- checkpoint resolution


def _train_state(tmp_path, selected: dict | None) -> str:
    path = tmp_path / "train-sonnet.json"
    path.write_text(json.dumps({"checkpoints": [], "selected": selected}))
    return str(path)


def test_resolve_checkpoint_substitutes_the_selected_path(tmp_path):
    stage = run_model.Stage(
        "eval-sonnet",
        ["py", "run_eval.py", "--model-arg", "checkpoint={checkpoint}"],
        tmp_path,
        checkpoint_from=_train_state(tmp_path, {"epoch": 2, "sampler_path": "tinker://w/00042"}),
    )
    assert run_model.resolve_checkpoint(stage)[-1] == "checkpoint=tinker://w/00042"


def test_resolve_checkpoint_leaves_other_stages_alone(tmp_path):
    stage = run_model.Stage("adapt", ["py", "adapt_dataset.py"], tmp_path)
    assert run_model.resolve_checkpoint(stage) == stage.command


def test_resolve_checkpoint_without_a_train_state_refuses(tmp_path):
    """--redo eval-sonnet before the finetune exists must not silently eval the base."""
    stage = run_model.Stage(
        "eval-sonnet", ["py", "--model-arg", "checkpoint={checkpoint}"], tmp_path,
        checkpoint_from=str(tmp_path / "absent.json"),
    )
    with pytest.raises(SystemExit) as exc:
        run_model.resolve_checkpoint(stage)
    assert "absent.json" in str(exc.value)


def test_resolve_checkpoint_refuses_a_state_with_no_selected_checkpoint(tmp_path):
    stage = run_model.Stage(
        "eval-sonnet", ["py", "--model-arg", "checkpoint={checkpoint}"], tmp_path,
        checkpoint_from=_train_state(tmp_path, None),
    )
    with pytest.raises(SystemExit) as exc:
        run_model.resolve_checkpoint(stage)
    assert "no selected checkpoint" in str(exc.value)


# ------------------------------------------------------------- redo warnings


def _plan():
    return run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=18, preset="core", train_epochs=4)


def test_no_warning_without_redo_or_for_an_unfinished_stage():
    state = {"stages": {"train-sonnet": {"status": "failed"}}}
    assert run_model.redo_warnings(None, state, _plan()) == []
    assert run_model.redo_warnings("train-sonnet", state, _plan()) == []


def test_redoing_a_finished_eval_warns_that_eval_set_skips_completed_conditions():
    state = {"stages": {"eval-base": {"status": "done"}}}
    (warning,) = run_model.redo_warnings("eval-base", state, _plan())
    assert "tinker-qwen-qwen3-8b" in warning and "move that directory aside" in warning


def test_redoing_a_finished_finetune_flags_its_now_stale_eval_arm():
    """Retraining under a stable run name is how a new checkpoint gets scored by
    the old one's samples — the driver has to say so before it costs money."""
    state = {"stages": {"train-terra": {"status": "done"}, "eval-terra": {"status": "done"}}}
    warnings = run_model.redo_warnings("train-terra", state, _plan())
    assert len(warnings) == 2
    assert "tinker-qwen-qwen3-8b-terra08" in warnings[1] and "--redo eval-terra" in warnings[1]
    # ...and only the cost warning when that arm has not been evaluated yet
    state["stages"].pop("eval-terra")
    assert len(run_model.redo_warnings("train-terra", state, _plan())) == 1


# ------------------------------------------------------------- state recording


def test_record_stage_keeps_earlier_stages_and_is_atomic(tmp_path):
    state_path = tmp_path / "runs" / "m" / "state.json"
    state = run_model.load_state(state_path)
    run_model.record_stage(state_path, state, "adapt", 0)
    run_model.record_stage(state_path, state, "check_render", 1)
    on_disk = json.loads(state_path.read_text())
    assert on_disk["stages"]["adapt"]["status"] == "done"
    assert on_disk["stages"]["check_render"]["status"] == "failed"
    assert on_disk["stages"]["check_render"]["returncode"] == 1
    assert not list(state_path.parent.glob("*.tmp"))
