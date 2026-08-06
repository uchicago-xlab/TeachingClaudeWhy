"""Run one sweep model end to end: adapt -> verify render -> train x2 -> eval x3.

State lives in runs/<slug>/state.json: completed stages are skipped on
re-run (a finished finetune is never relaunched), --redo <stage> forces one.
Dry-run by default: prints the full stage plan and exits without running or
calling anything; --yes executes. Sweeping = invoking this once per model.

    ../../.venv-tinker/bin/python run_model.py --model Qwen/Qwen3-8B
    ../../.venv-tinker/bin/python run_model.py --model Qwen/Qwen3-8B --yes
    ../../.venv-tinker/bin/python run_model.py --model Qwen/Qwen3-8B --redo eval-base --yes

Every stage is a subprocess of a script that is runnable by hand with the same
arguments, so a stage that misbehaves under the driver can be debugged directly
and its state entry hand-edited. The eval stages run with cwd=code/misalignment_eval
and this same interpreter, because run_eval.py imports the tinker provider from
code/tinker_sweep and so needs .venv-tinker rather than .venv-inspect.
"""

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import families

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
EVAL_DIR = REPO_ROOT / "code" / "misalignment_eval"
# The .venv-tinker interpreter running this script. abspath, not realpath: the
# venv's bin/python is a symlink to the system interpreter, and following it
# would hand every subprocess a python without this venv's packages.
PY = os.path.abspath(sys.executable)

STAGES = ("adapt", "check_render", "train-sonnet", "train-terra",
          "eval-base", "eval-sonnet", "eval-terra")
# The eval arm each finetune feeds; redoing a finetune makes its arm's log stale.
EVAL_OF_TRAIN = {"train-sonnet": "eval-sonnet", "train-terra": "eval-terra"}
LOG_ROOT = REPO_ROOT / "data" / "misalignment-eval" / "logs"  # run_eval.DEFAULT_LOG_ROOT


@dataclasses.dataclass
class Stage:
    name: str
    command: list[str]
    cwd: Path
    # eval stages read the teacher's train state at run time to fill in the
    # selected checkpoint; None for other stages
    checkpoint_from: str | None = None


def build_plan(model: str, eval_epochs: int, preset: str, train_epochs: int) -> list[Stage]:
    slug = families.slug(model)
    run_dir = HERE / "runs" / slug

    def eval_cmd(run_name: str, checkpoint_placeholder: bool) -> list[str]:
        cmd = [PY, "run_eval.py", "--model", f"tinker/{model}",
               "--preset", preset, "--epochs", str(eval_epochs),
               "--run-name", run_name]
        if checkpoint_placeholder:
            cmd += ["--model-arg", "checkpoint={checkpoint}"]
        return cmd

    return [
        Stage("adapt", [PY, "adapt_dataset.py", "--family",
                        families.get_model(model).family.key], HERE),
        Stage("check_render", [PY, "check_render.py", "--model", model], HERE),
        Stage("train-sonnet", [PY, "train_sft.py", "--model", model, "--teacher", "sonnet",
                               "--epochs", str(train_epochs), "--run-dir", str(run_dir), "--yes"], HERE),
        Stage("train-terra", [PY, "train_sft.py", "--model", model, "--teacher", "terra",
                              "--epochs", str(train_epochs), "--run-dir", str(run_dir), "--yes"], HERE),
        Stage("eval-base", eval_cmd(f"tinker-{slug}", False), EVAL_DIR),
        Stage("eval-sonnet", eval_cmd(f"tinker-{slug}-sonnet08", True), EVAL_DIR,
              checkpoint_from=str(run_dir / "train-sonnet.json")),
        Stage("eval-terra", eval_cmd(f"tinker-{slug}-terra08", True), EVAL_DIR,
              checkpoint_from=str(run_dir / "train-terra.json")),
    ]


def load_state(path: Path) -> dict:
    state = json.loads(path.read_text()) if path.exists() else {}
    state.setdefault("stages", {})
    return state


def should_run(stage_name: str, state: dict, redo: str | None) -> bool:
    if redo == stage_name:
        return True
    return state["stages"].get(stage_name, {}).get("status") != "done"


def resolve_checkpoint(stage: Stage) -> list[str]:
    """Fill {checkpoint} from the teacher's train state, or refuse to run.

    Both failures below are ways of quietly evaluating the base model while the
    log says "sonnet08", which is exactly the comparison this sweep exists to
    make — so they abort rather than fall back to anything.
    """
    if not stage.checkpoint_from:
        return stage.command
    path = Path(stage.checkpoint_from)
    if not path.exists():
        raise SystemExit(
            f"{stage.name}: no train state at {path} — run its training stage first "
            "(or point --run-dir at the run that has it)"
        )
    selected = json.loads(path.read_text()).get("selected")
    if not selected or not selected.get("sampler_path"):
        raise SystemExit(f"{stage.name}: {path} records no selected checkpoint — training "
                         "did not reach the end of an epoch")
    return [arg.replace("{checkpoint}", selected["sampler_path"]) for arg in stage.command]


def checkpoint_note(stage: Stage) -> str | None:
    """One line for the dry-run plan saying where {checkpoint} will come from."""
    if not stage.checkpoint_from:
        return None
    path = Path(stage.checkpoint_from)
    if not path.exists():
        return f"       {{checkpoint}} <- {path} (not trained yet)"
    selected = json.loads(path.read_text()).get("selected") or {}
    if not selected.get("sampler_path"):
        return f"       {{checkpoint}} <- {path} (no selected checkpoint yet)"
    return (f"       {{checkpoint}} <- {selected['sampler_path']} "
            f"(epoch {selected.get('epoch')}, val_loss {selected.get('val_loss')})")


def log_dir_for(stage: Stage) -> Path | None:
    """Where this stage's eval logs land — run_eval's --run-name under LOG_ROOT."""
    if "--run-name" not in stage.command:
        return None
    return LOG_ROOT / stage.command[stage.command.index("--run-name") + 1]


def redo_warnings(redo: str | None, state: dict, plan: list[Stage]) -> list[str]:
    """What --redo on an already-completed stage does NOT do by itself.

    Both cases below are ways of ending up with a state.json that says "done"
    over a result that answers a different question than its label:

    - Inspect's eval_set is idempotent over its log directory: it re-runs
      unfinished conditions and skips completed ones. That is what makes an
      interrupted eval resumable, and it also means re-invoking a *finished*
      eval samples nothing at all.
    - So a re-trained checkpoint evaluated under the same --run-name would be
      scored by the old checkpoint's samples. The driver passes explicit run
      names (stable names are what lets summarize.py table the three arms), so
      unlike run_eval's default naming, nothing here distinguishes the log dirs
      of two checkpoints from the same model and teacher.
    """
    def done(name: str) -> bool:
        return state["stages"].get(name, {}).get("status") == "done"

    if not redo or not done(redo):
        return []
    stages = {s.name: s for s in plan}
    if redo in EVAL_OF_TRAIN:
        arm = EVAL_OF_TRAIN[redo]
        out = [f"--redo {redo} re-runs a finetune that already succeeded: it costs Tinker "
               "training tokens again, overwrites train-*.json, and leaves the old checkpoint "
               "on Tinker (nothing deletes it)."]
        if done(arm):
            out.append(f"  {arm} is already done. Its log dir {log_dir_for(stages[arm])} holds the "
                       f"OLD checkpoint's samples, and eval_set will not re-sample a completed "
                       f"eval — move that directory aside and --redo {arm} too, or the new "
                       f"checkpoint is never actually evaluated.")
        return out
    if redo.startswith("eval-"):
        return [f"--redo {redo} re-invokes run_eval, but eval_set only samples conditions that "
                f"are not already complete in {log_dir_for(stages[redo])}. That resumes an "
                f"interrupted eval; for a genuine re-run, move that directory aside first."]
    return []


def write_json_atomic(path: Path, obj) -> None:
    """Write via a sibling temp file + os.replace, so a crash mid-write cannot
    truncate the state that resume depends on."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    os.replace(tmp, path)


def record_stage(state_path: Path, state: dict, name: str, returncode: int) -> None:
    state["stages"][name] = {
        "status": "done" if returncode == 0 else "failed",
        "returncode": returncode,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json_atomic(state_path, state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True)
    # Mirrors run_eval.py's --preset choices, checked here so a typo fails now
    # rather than after two paid finetunes have run.
    parser.add_argument("--preset", default="core",
                        choices=("smoke", "exfil-smoke", "blackmail-2x2", "exfil", "core",
                                 "core+blackmail", "full"))
    parser.add_argument("--epochs", type=int, default=18,
                        help="eval epochs per condition (core preset x 18 = the 180-sample slice)")
    parser.add_argument("--train-epochs", type=int, default=4)
    parser.add_argument("--redo", choices=STAGES)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    try:
        families.get_model(args.model)  # hard error before anything else
    except KeyError as e:
        raise SystemExit(e.args[0])  # KeyError's str() re-quotes the message
    plan = build_plan(args.model, args.epochs, args.preset, args.train_epochs)
    state_path = HERE / "runs" / families.slug(args.model) / "state.json"
    state = load_state(state_path)

    print(f"{args.model}  ->  {state_path}")
    for stage in plan:
        run = should_run(stage.name, state, args.redo)
        marker = "run " if run else "skip"
        print(f"{marker} {stage.name}: {' '.join(stage.command)}")
        note = checkpoint_note(stage) if run else None
        if note:
            print(note)
    for warning in redo_warnings(args.redo, state, plan):
        print(f"\nWARNING: {warning}" if not warning.startswith("  ") else warning)
    if not args.yes:
        print("\ndry run — pass --yes to execute. No API call was made. Per-stage cost: "
              "run the train stages by hand without --yes for token counts and a live price "
              "estimate. Log spend in notes/Project/ per repo convention.")
        return 0

    for stage in plan:
        if not should_run(stage.name, state, args.redo):
            continue
        print(f"\n=== {stage.name} ===")
        command = resolve_checkpoint(stage)
        result = subprocess.run(command, cwd=stage.cwd)
        record_stage(state_path, state, stage.name, result.returncode)
        if result.returncode != 0:
            print(f"{stage.name} FAILED (exit {result.returncode}) — fix and re-run "
                  f"(state preserved in {state_path}; earlier stages will be skipped)")
            return 1
    print(f"\nall stages done. Summarize: cd {EVAL_DIR} && "
          f"{PY} summarize.py --log-dir ../../data/misalignment-eval/logs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
