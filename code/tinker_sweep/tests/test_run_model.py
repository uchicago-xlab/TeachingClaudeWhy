import json
import sys
from pathlib import Path

import pytest

import families
import run_model


def test_stage_order_and_commands():
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=4)
    assert [s.name for s in plan] == [
        "adapt", "check_render", "train-sonnet", "train-terra",
        "eval-base", "eval-sonnet", "eval-terra",
    ]
    eval_sonnet = next(s for s in plan if s.name == "eval-sonnet")
    cmd = " ".join(eval_sonnet.command)
    assert "--model tinker/Qwen/Qwen3-8B" in cmd
    assert "--run-name msm-tinker-qwen-qwen3-8b-sonnet08" in cmd
    assert "checkpoint=" in cmd  # placeholder resolved at run time from train state


# ------------------------------------------------------------- the eval harness is msm_eval


def _eval_stages(model="Qwen/Qwen3-8B"):
    plan = run_model.build_plan(model, eval_epochs=30, train_epochs=4)
    return [s for s in plan if s.name.startswith("eval-")]


def test_eval_stages_invoke_msm_eval_run_from_its_own_directory():
    for stage in _eval_stages():
        assert stage.command[1] == "msm_eval_run.py"
        assert stage.cwd == run_model.REPO_ROOT / "code" / "msm_eval"
        assert "--epochs 30" in " ".join(stage.command)


def test_eval_stages_pass_no_base_url_and_no_preset():
    """msm_eval_run refuses --base-url for a tinker/ model (the Tinker API is the
    endpoint) and has no --preset — its grid is fixed in the script."""
    for stage in _eval_stages():
        cmd = " ".join(stage.command)
        assert "--base-url" not in cmd
        assert "--preset" not in cmd


@pytest.mark.parametrize("model,name", [
    ("Qwen/Qwen3-8B", "Qwen"),
    ("moonshotai/Kimi-K2.6", "Kimi"),
    ("deepseek-ai/DeepSeek-V3.1", "DeepSeek"),
    ("openai/gpt-oss-20b", "ChatGPT"),
])
def test_model_name_is_the_familys_own_assistant_name(model, name):
    """Identity-matched scenarios (ruling 2): each model is addressed by the name
    it was trained to answer to, not msm_eval_run's `Qwen` default."""
    for stage in _eval_stages(model):
        cmd = stage.command
        assert cmd[cmd.index("--model-name") + 1] == name


def test_every_sweep_model_is_addressed_by_a_registry_name():
    for model in families.MODELS:
        for stage in _eval_stages(model):
            cmd = stage.command
            assert (cmd[cmd.index("--model-name") + 1]
                    == families.get_model(model).family.assistant_name)


def test_the_driver_no_longer_touches_the_old_harness():
    """The misalignment-eval log dirs are not this driver's to move any more."""
    source = Path(run_model.__file__).read_text()
    assert "misalignment" not in source
    assert "run_eval" not in source


def test_log_dirs_are_msm_eval_run_directories():
    assert run_model.LOG_ROOT == run_model.REPO_ROOT / "data" / "msm-eval"
    dirs = {s.name: run_model.log_dir_for(s) for s in _eval_stages()}
    assert dirs["eval-base"] == run_model.LOG_ROOT / "msm-tinker-qwen-qwen3-8b"
    assert dirs["eval-terra"] == run_model.LOG_ROOT / "msm-tinker-qwen-qwen3-8b-terra08"
    assert len(set(dirs.values())) == 3  # one directory per arm, or summarize.py pools them


def test_the_generated_eval_commands_are_accepted_by_msm_eval_run(monkeypatch):
    """End of the swap: run each generated command through the real runner.

    Nothing here samples — the fake eval_set raises with its kwargs — but every
    flag the driver emits is parsed by the script that will receive it, and the
    log dir the driver derives is compared against the one msm_eval_run actually
    computes. A flag renamed on either side fails here rather than after two
    paid finetunes.
    """
    sys.path.insert(0, str(Path(run_model.REPO_ROOT) / "code" / "msm_eval"))
    import msm_eval_run

    monkeypatch.setenv("TINKER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    class Reached(Exception):
        def __init__(self, kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(msm_eval_run, "eval_set",
                        lambda **kwargs: (_ for _ in ()).throw(Reached(kwargs)))

    for stage in _eval_stages():
        # command is [interpreter, script, *flags]
        argv = [a.replace("{checkpoint}", "tinker://w/00042") for a in stage.command[2:]]
        monkeypatch.setattr(sys, "argv", ["msm_eval_run.py", *argv])
        with pytest.raises(Reached) as excinfo:
            msm_eval_run.main()
        kwargs = excinfo.value.kwargs
        assert kwargs["model"] == "tinker/Qwen/Qwen3-8B"
        assert kwargs["model_base_url"] is None
        assert kwargs["epochs"] == 30
        assert len(kwargs["tasks"]) == 6            # msm's fixed grid, times 30 = 180 samples
        assert kwargs["log_dir"] == str(run_model.log_dir_for(stage))
        expected_ckpt = None if stage.name == "eval-base" else "tinker://w/00042"
        assert kwargs.get("model_args", {}).get("checkpoint") == expected_ckpt


def test_every_arm_name_is_namespaced_under_msm_tinker():
    """LOG_ROOT is shared with the team's own msm runs (data/msm-eval/da-*,
    teacher-*, qwen3-14b-*). The stale-arm mover only ever touches a name this
    driver generated, so every generated name carries the sweep's prefix."""
    for model in families.MODELS:
        for stage in _eval_stages(model):
            assert run_model.log_dir_for(stage).name.startswith("msm-tinker-")


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
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=4)
    base = next(s for s in plan if s.name == "eval-base")
    assert "checkpoint" not in " ".join(base.command)
    assert base.checkpoint_from is None
    assert "--run-name msm-tinker-qwen-qwen3-8b" in " ".join(base.command)


def test_train_stages_carry_yes_and_the_run_dir():
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=2)
    train = next(s for s in plan if s.name == "train-terra")
    cmd = " ".join(train.command)
    assert "--teacher terra" in cmd and "--epochs 2" in cmd and "--yes" in cmd
    assert f"--run-dir {run_model.HERE / 'runs' / 'qwen-qwen3-8b'}" in cmd


def test_adapt_stage_targets_the_models_family():
    plan = run_model.build_plan("moonshotai/Kimi-K2.6", eval_epochs=30, train_epochs=4)
    adapt = next(s for s in plan if s.name == "adapt")
    assert "--family kimi_k2_6" in " ".join(adapt.command)


def test_unknown_model_is_a_hard_error():
    with pytest.raises(KeyError):
        run_model.build_plan("Qwen/Qwen3-14B", eval_epochs=30, train_epochs=4)


def test_every_sweep_model_builds_a_plan():
    for model in families.MODELS:
        plan = run_model.build_plan(model, eval_epochs=30, train_epochs=4)
        assert [s.name for s in plan] == list(run_model.STAGES)


# ------------------------------------------------------------- checkpoint resolution


def _train_state(tmp_path, selected: dict | None) -> str:
    path = tmp_path / "train-sonnet.json"
    path.write_text(json.dumps({"checkpoints": [], "selected": selected}))
    return str(path)


def test_resolve_checkpoint_substitutes_the_selected_path(tmp_path):
    stage = run_model.Stage(
        "eval-sonnet",
        ["py", "msm_eval_run.py", "--model-arg", "checkpoint={checkpoint}"],
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
    return run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=4)


def test_no_warning_without_redo_or_for_an_unfinished_stage():
    state = {"stages": {"train-sonnet": {"status": "failed"}}}
    assert run_model.redo_warnings(None, state, _plan()) == []
    assert run_model.redo_warnings("train-sonnet", state, _plan()) == []


def test_redoing_a_finished_eval_warns_that_eval_set_skips_completed_conditions():
    state = {"stages": {"eval-base": {"status": "done"}}}
    (warning,) = run_model.redo_warnings("eval-base", state, _plan())
    assert "msm-tinker-qwen-qwen3-8b" in warning and "move that directory aside" in warning


def test_redoing_a_finished_finetune_warns_that_it_costs_again():
    """The stale eval arm is handled by stale_eval_arm/invalidate_stale_eval, not
    by a warning; what stays a warning is that this spends money."""
    state = {"stages": {"train-terra": {"status": "done"}, "eval-terra": {"status": "done"}}}
    (warning,) = run_model.redo_warnings("train-terra", state, _plan())
    assert "costs Tinker training tokens again" in warning


# ------------------------------------------------- a partly-paid finetune is never restarted


def _train_stage(tmp_path, checkpoints, name="train-sonnet"):
    state_file = tmp_path / f"{name}.json"
    selected = min(checkpoints, key=lambda c: c["val_loss"]) if checkpoints else None
    state_file.write_text(json.dumps({"checkpoints": checkpoints, "selected": selected}))
    return run_model.Stage(name, ["py", "train_sft.py", "--yes"], tmp_path,
                           writes_state=str(state_file))


def test_a_failed_finetune_with_paid_checkpoints_refuses_to_restart(tmp_path):
    """train_sft has no resume: relaunching overwrites the file that names the
    checkpoints already billed, orphaning them server-side."""
    stage = _train_stage(tmp_path, [
        {"epoch": 1, "sampler_path": "tinker://w/00001", "val_loss": 1.4},
        {"epoch": 2, "sampler_path": "tinker://w/00002", "val_loss": 1.1},
    ])
    msg = run_model.refuse_partial_retrain(stage, redo=None)
    assert msg is not None
    assert "tinker://w/00001" in msg and "tinker://w/00002" in msg  # every paid artifact listed
    assert "<- best" in msg                                        # and which one eval would use
    assert 'status to "done"' in msg                               # option 1: keep them
    assert "--redo train-sonnet" in msg                            # option 2: pay again


def test_explicit_redo_is_allowed_to_restart_a_finetune(tmp_path):
    stage = _train_stage(tmp_path, [{"epoch": 1, "sampler_path": "tinker://w/1", "val_loss": 1.0}])
    assert run_model.refuse_partial_retrain(stage, redo="train-sonnet") is None


def test_no_refusal_without_a_paid_checkpoint(tmp_path):
    """A finetune that died before its first epoch has nothing to protect."""
    assert run_model.refuse_partial_retrain(_train_stage(tmp_path, []), redo=None) is None
    fresh = run_model.Stage("train-terra", ["py"], tmp_path,
                            writes_state=str(tmp_path / "absent.json"))
    assert run_model.refuse_partial_retrain(fresh, redo=None) is None


def test_non_train_stages_are_never_blocked(tmp_path):
    stage = run_model.Stage("eval-base", ["py"], tmp_path)
    assert run_model.refuse_partial_retrain(stage, redo=None) is None


def test_the_plan_marks_which_state_file_each_finetune_overwrites():
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=4)
    stages = {s.name: s for s in plan}
    assert stages["train-terra"].writes_state == stages["eval-terra"].checkpoint_from
    assert stages["eval-base"].writes_state is None


# ------------------------------------------------- redoing a finetune invalidates its eval arm


def test_redoing_a_finetune_reports_its_stale_eval_arm(tmp_path, monkeypatch):
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    (tmp_path / "msm-tinker-qwen-qwen3-8b-terra08").mkdir()
    state = {"stages": {"train-terra": {"status": "done"}, "eval-terra": {"status": "done"}}}
    arm, log_dir = run_model.stale_eval_arm("train-terra", state, _plan())
    assert arm == "eval-terra"
    assert log_dir == tmp_path / "msm-tinker-qwen-qwen3-8b-terra08"


def test_a_half_finished_eval_arm_is_stale_too(tmp_path, monkeypatch):
    """The conditions a crashed eval DID finish belong to the old checkpoint, and
    eval_set skips exactly those on the retry — so the arm would end up done over
    samples from two different checkpoints. Status must not gate this."""
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    (tmp_path / "msm-tinker-qwen-qwen3-8b-terra08").mkdir()
    for status in ("failed", "running", "done"):
        state = {"stages": {"train-terra": {"status": "done"}, "eval-terra": {"status": status}}}
        assert run_model.stale_eval_arm("train-terra", state, _plan()) == (
            "eval-terra", tmp_path / "msm-tinker-qwen-qwen3-8b-terra08")


def test_a_log_dir_with_no_state_entry_is_still_stale(tmp_path, monkeypatch):
    """The log is what eval_set reads; the bookkeeping is not the authority."""
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    (tmp_path / "msm-tinker-qwen-qwen3-8b-sonnet08").mkdir()
    arm, log_dir = run_model.stale_eval_arm("train-sonnet", {"stages": {}}, _plan())
    assert arm == "eval-sonnet" and log_dir == tmp_path / "msm-tinker-qwen-qwen3-8b-sonnet08"


def test_nothing_is_stale_with_neither_a_log_dir_nor_a_state_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    state = {"stages": {"train-terra": {"status": "done"}}}
    assert run_model.stale_eval_arm("train-terra", state, _plan()) is None
    assert run_model.stale_eval_arm("eval-base", state, _plan()) is None
    assert run_model.stale_eval_arm(None, state, _plan()) is None


def test_invalidating_an_unrecorded_arm_moves_the_dir_without_claiming_a_state_change(tmp_path):
    log_dir = tmp_path / "msm-tinker-qwen-qwen3-8b-terra08"
    log_dir.mkdir()
    state_path = tmp_path / "state.json"
    changed = run_model.invalidate_stale_eval(state_path, {"stages": {}}, "eval-terra",
                                              log_dir, now="X")
    assert changed == [f"moved {log_dir}\n   -> {log_dir}.stale-X"]  # no "cleared" line
    assert (tmp_path / "msm-tinker-qwen-qwen3-8b-terra08.stale-X").exists()


def test_a_missing_log_dir_still_invalidates_the_state_entry(tmp_path, monkeypatch):
    """Clearing the state is what makes the arm re-run; the move is housekeeping."""
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)  # no log dir created
    state = {"stages": {"eval-sonnet": {"status": "done"}}}
    assert run_model.stale_eval_arm("train-sonnet", state, _plan()) == ("eval-sonnet", None)


def test_invalidate_moves_the_log_dir_and_clears_the_state(tmp_path):
    log_dir = tmp_path / "logs" / "msm-tinker-qwen-qwen3-8b-terra08"
    log_dir.mkdir(parents=True)
    (log_dir / "2026-08-06.eval").write_text("old checkpoint's samples")
    state_path = tmp_path / "state.json"
    state = {"stages": {"eval-terra": {"status": "done"}, "adapt": {"status": "done"}}}

    changed = run_model.invalidate_stale_eval(state_path, state, "eval-terra", log_dir, now="X")

    moved = log_dir.with_name("msm-tinker-qwen-qwen3-8b-terra08.stale-X")
    assert not log_dir.exists() and (moved / "2026-08-06.eval").exists()
    assert "eval-terra" not in json.loads(state_path.read_text())["stages"]
    assert json.loads(state_path.read_text())["stages"]["adapt"]["status"] == "done"
    assert any("moved" in c for c in changed) and any("cleared" in c for c in changed)


def test_invalidate_refuses_to_overwrite_an_earlier_stale_log(tmp_path):
    log_dir = tmp_path / "msm-tinker-qwen-qwen3-8b-terra08"
    log_dir.mkdir()
    (tmp_path / "msm-tinker-qwen-qwen3-8b-terra08.stale-X").mkdir()
    with pytest.raises(SystemExit) as exc:
        run_model.invalidate_stale_eval(tmp_path / "state.json", {"stages": {}},
                                        "eval-terra", log_dir, now="X")
    assert "already exists" in str(exc.value)
    assert log_dir.exists()


def test_a_log_dir_outside_the_drivers_own_log_root_is_never_moved(tmp_path, monkeypatch):
    """Only run names this driver generated are safe to rename out from under."""
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    plan = _plan()
    foreign = tmp_path / "elsewhere" / "operators-own-run"
    foreign.mkdir(parents=True)
    for stage in plan:
        if stage.name == "eval-sonnet":
            stage.command[stage.command.index("--run-name") + 1] = "elsewhere/operators-own-run"
    state = {"stages": {"eval-sonnet": {"status": "done"}}}
    assert run_model.stale_eval_arm("train-sonnet", state, plan) == ("eval-sonnet", None)
    assert foreign.exists()


# ------------------------------------------------------------- a raised token cap


def _mt_stages(max_tokens, model="Qwen/Qwen3-8B"):
    plan = run_model.build_plan(model, eval_epochs=30, train_epochs=4,
                                eval_max_tokens=max_tokens)
    return [s for s in plan if s.name.startswith("eval-")]


def test_the_default_cap_changes_nothing():
    """4096 is what msm_eval_run uses anyway: no flag, no suffix, so a standard
    run of the driver keeps producing the standardized slice's run names."""
    default = [s.command for s in _eval_stages()]
    assert [s.command for s in _mt_stages(run_model.DEFAULT_EVAL_MAX_TOKENS)] == default
    assert all("--max-tokens" not in c for c in default)
    assert all("-mt" not in " ".join(c) for c in default)


def test_a_raised_cap_reaches_every_eval_command():
    for stage in _mt_stages(8192):
        cmd = stage.command
        assert cmd[cmd.index("--max-tokens") + 1] == "8192"


def test_a_raised_cap_renames_all_three_arms_and_keeps_them_distinct():
    """The cap is a property of the comparison, not of one arm: if only some
    arms carried it, the sweep would compare a truncated base against untruncated
    finetunes. And a corrected arm must not land in the standard slice's
    directory, which eval_set would treat as already complete."""
    names = [run_model.log_dir_for(s).name for s in _mt_stages(8192)]
    assert names == ["msm-tinker-qwen-qwen3-8b-mt8192",
                     "msm-tinker-qwen-qwen3-8b-sonnet08-mt8192",
                     "msm-tinker-qwen-qwen3-8b-terra08-mt8192"]
    assert len(set(names)) == 3
    assert not set(names) & {run_model.log_dir_for(s).name for s in _eval_stages()}


def test_suffixed_arm_names_stay_driver_generated():
    """The stale-arm mover only touches names this driver generated; the suffix
    must not push one out of that namespace."""
    for model in families.MODELS:
        for stage in _mt_stages(8192, model):
            assert run_model.log_dir_for(stage).name.startswith("msm-tinker-")


def test_a_stale_suffixed_arm_is_still_moved(tmp_path, monkeypatch):
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=4,
                                eval_max_tokens=8192)
    log_dir = tmp_path / "msm-tinker-qwen-qwen3-8b-terra08-mt8192"
    log_dir.mkdir()
    state = {"stages": {"train-terra": {"status": "done"}, "eval-terra": {"status": "done"}}}
    assert run_model.stale_eval_arm("train-terra", state, plan) == ("eval-terra", log_dir)


def test_a_foreign_run_name_is_still_never_moved(tmp_path, monkeypatch):
    """The suffix must not have widened what the mover is willing to rename."""
    monkeypatch.setattr(run_model, "LOG_ROOT", tmp_path)
    plan = run_model.build_plan("Qwen/Qwen3-8B", eval_epochs=30, train_epochs=4,
                                eval_max_tokens=8192)
    foreign = tmp_path / "elsewhere" / "someones-own-mt8192-run"
    foreign.mkdir(parents=True)
    for stage in plan:
        if stage.name == "eval-terra":
            stage.command[stage.command.index("--run-name") + 1] = "elsewhere/someones-own-mt8192-run"
    state = {"stages": {"eval-terra": {"status": "done"}}}
    assert run_model.stale_eval_arm("train-terra", state, plan) == ("eval-terra", None)
    assert foreign.exists()


def test_the_raised_cap_commands_are_accepted_by_msm_eval_run(monkeypatch):
    """Same end-to-end check as the default plan gets: the driver's flags are
    parsed by the script that receives them, and the cap reaches eval_set."""
    sys.path.insert(0, str(Path(run_model.REPO_ROOT) / "code" / "msm_eval"))
    import msm_eval_run

    monkeypatch.setenv("TINKER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    class Reached(Exception):
        def __init__(self, kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(msm_eval_run, "eval_set",
                        lambda **kwargs: (_ for _ in ()).throw(Reached(kwargs)))

    for stage in _mt_stages(8192):
        argv = [a.replace("{checkpoint}", "tinker://w/00042") for a in stage.command[2:]]
        monkeypatch.setattr(sys, "argv", ["msm_eval_run.py", *argv])
        with pytest.raises(Reached) as excinfo:
            msm_eval_run.main()
        kwargs = excinfo.value.kwargs
        assert kwargs["max_tokens"] == 8192
        assert kwargs["log_dir"] == str(run_model.log_dir_for(stage))


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
