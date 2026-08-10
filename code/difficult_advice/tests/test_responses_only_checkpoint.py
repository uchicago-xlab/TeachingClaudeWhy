import importlib
import json
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def restore_module_state():
    """The stubbed run_pipeline must not outlive this file's tests."""
    saved = {name: sys.modules.get(name) for name in ("run_pipeline", "sample_prompts")}
    saved_path = list(sys.path)
    yield
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
    sys.path[:] = saved_path


def import_sample_prompts(tmp_path):
    """Import a fresh sample_prompts against a stub run_pipeline in tmp_path."""
    stub = types.ModuleType("run_pipeline")
    stub.OUT_DIR = tmp_path
    stub.STAGE_NAMES = ("principles", "themes", "scenarios", "initial_prompt", "critique",
                       "rewrite", "response", "critique_response", "rewrite_response")
    stub.calls = []

    def record(name, result):
        def fn(*args, **kwargs):
            stub.calls.append(name)
            return result
        return fn

    stub.resolve_placeholders = lambda text: text
    stub.stage_initial_response = record("response", {"system": "S", "user": "U", "response": "refusal text"})
    stub.stage_critique_response = record("critique", "a critique")
    stub.stage_rewrite_response = record("rewrite", "final refusal")
    for name in ("stage_critique", "stage_initial_prompt", "stage_rewrite",
                 "stage_scenarios", "stage_themes"):
        setattr(stub, name, record(name, None))
    stub.prompts_dir = lambda stage: tmp_path
    stub.stage_model = lambda stage: "stub-model"

    sys.modules["run_pipeline"] = stub
    sys.modules.pop("sample_prompts", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    module = importlib.import_module("sample_prompts")
    return module, stub


def sample(system="sys", user="usr"):
    return {"system": system, "user": user, "rewrite": {"system": system, "user": user},
            "principle_index": 0}


def test_regen_response_runs_and_checkpoints_new_sample(tmp_path):
    sp, stub = import_sample_prompts(tmp_path)
    s = sample()
    sp.regen_response(0, s, {})
    assert s["final_response"] == "final refusal"
    lines = [json.loads(l) for l in sp.CHECKPOINT_SAMPLES.read_text().splitlines()]
    assert lines[0]["task_index"] == 0
    assert lines[0]["sample"]["final_response"] == "final refusal"


def test_regen_response_restores_completed_sample_without_calls(tmp_path):
    sp, stub = import_sample_prompts(tmp_path)
    s = sample()
    done = {0: {"response": {"system": "S", "user": "U", "response": "r"},
                "response_critique": "c", "final_response": "done earlier"}}
    sp.regen_response(0, s, done)
    assert s["final_response"] == "done earlier"
    assert stub.calls == []


def test_regen_response_retries_failed_checkpoint(tmp_path):
    sp, stub = import_sample_prompts(tmp_path)
    s = sample()
    done = {0: {"response": None, "response_critique": None, "final_response": None}}
    sp.regen_response(0, s, done)
    assert s["final_response"] == "final refusal"
    assert "response" in stub.calls


def test_responses_only_resumes_and_clears_checkpoints(tmp_path, monkeypatch):
    sp, stub = import_sample_prompts(tmp_path)
    cached = {"principles": [{"description": "p"}], "themes_by_principle": {"0": ["t"]},
              "prompts": [sample("sysA", "usrA"), sample("sysB", "usrB")]}
    (tmp_path / "critiqued_prompts.json").write_text(json.dumps(cached))
    sp.checkpoint_sample(0, {"response": {"system": "S", "user": "U", "response": "r"},
                             "response_critique": "c", "final_response": "kept"})
    written = {}
    monkeypatch.setattr(sp, "write_outputs", lambda p, t, s: written.update(samples=list(s)))
    monkeypatch.setattr(sys, "argv", ["sample_prompts.py", "--responses-only"])
    sp.main()
    assert written["samples"][0]["final_response"] == "kept"
    assert written["samples"][1]["final_response"] == "final refusal"
    assert not sp.CHECKPOINT_SAMPLES.exists()
