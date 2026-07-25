"""End-to-end elicitation pipeline: mix -> train -> evals.

Stages, each resumable and individually skippable:

  build    build_mix.py for the configured arm (local JSONL)
  check    check_dataset.py schema + identity filter (local)
  train    upload to Together, launch SFT with W&B logging and optional
           HF checkpoint push, poll until the job finishes
  inspect  Jack's Inspect AM harness against the Together-served result
  ant_am   Anthropic's original AM repo, via a user-supplied command
           template ("{model}" is replaced with the output model id)

Everything is driven by a JSON config (see pipeline-config.json). Progress
is recorded in runs/<run_name>/state.json, so re-running the same config
resumes where it left off; --redo <stage> clears a stage's state first.
Evals toggle via evals.<name>.enabled in the config.

Dry-run by default: prints the plan, costs, and what each stage would do.
Nothing is uploaded, launched, or spent without --yes.

Usage:
    export TOGETHER_API_KEY=...   # training + inspect eval
    export WANDB_API_KEY=...      # optional, for W&B logging
    export HF_TOKEN=...           # optional, for HF checkpoint push
    python train_eval_pipeline.py --config pipeline-config.json
    python train_eval_pipeline.py --config pipeline-config.json --yes
    python train_eval_pipeline.py --config pipeline-config.json --redo inspect --yes
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STAGES = ("build", "check", "train", "inspect", "ant_am")
JOB_DEADLINE_S = 6 * 60 * 60


def sh(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def est_tokens_m(path):
    return sum(
        len(m["content"]) for l in open(path) for m in json.loads(l)["messages"]
    ) / 4 / 1e6


class Pipeline:
    def __init__(self, cfg, live):
        self.cfg = cfg
        self.live = live
        self.run_dir = HERE / "runs" / cfg["run_name"]
        self.state_path = self.run_dir / "state.json"
        self.state = (json.loads(self.state_path.read_text())
                      if self.state_path.exists() else {})
        self.mix = self.run_dir / "mix.jsonl"
        self.clean = self.run_dir / "mix-clean.jsonl"

    def save(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def done(self, stage):
        return self.state.get(stage, {}).get("done")

    def mark(self, stage, **info):
        self.state[stage] = {"done": True, "at": time.strftime("%F %T"), **info}
        self.save()

    # -- stages ----------------------------------------------------------
    def build(self):
        m = self.cfg["mix"]
        if not self.live:
            print(f"build: arm={m['arm']} seed={m['seed']} -> {self.mix}")
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        sh([sys.executable, HERE / "build_mix.py", "--arm", m["arm"],
            "--seed", m["seed"], "--out", self.mix])
        self.mark("build")

    def check(self):
        if not self.live:
            print(f"check: {self.mix} -> {self.clean} (schema + identity filter)")
            return
        sh([sys.executable, HERE / "check_dataset.py",
            "--in", self.mix, "--out", self.clean])
        self.mark("check")

    def train(self):
        t = self.cfg["train"]
        rate = 3.75 if t["full"] else 1.50
        if self.clean.exists():
            tok = est_tokens_m(self.clean)
            cost = f"~${max(tok * rate * t['epochs'], 4.0):.2f} ({tok:.2f}M tokens)"
        else:
            cost = f"${rate}/M tokens, $4 min (mix not built yet)"
        print(f"train: {t['model']} "
              f"{'full' if t['full'] else 'LoRA r=' + str(t['lora_rank'])} "
              f"x{t['epochs']} ep, {cost}, wandb={t.get('wandb_project') or '-'}, "
              f"hf={t.get('hf_output_repo') or '-'}")
        if not self.live:
            return

        from together import Together
        from launch_instruct_ft import upload_and_wait
        client = Together()

        # a job launched by an earlier invocation (e.g. polling hit the
        # deadline) is resumed, never relaunched — one config, one job
        job_id = self.state.get("train", {}).get("job_id")
        if job_id:
            print(f"resuming existing job {job_id}")
        else:
            kwargs = dict(
                training_file=upload_and_wait(client, str(self.clean)),
                model=t["model"],
                suffix=self.cfg["run_name"],
                n_epochs=t["epochs"],
                learning_rate=t["lr"],
                lr_scheduler_type="cosine",
                warmup_ratio=0.03,
                batch_size="max",
                train_on_inputs=False,
                packing=t.get("packing", True),
            )
            if not t["full"]:
                kwargs.update(lora=True, lora_r=t["lora_rank"],
                              lora_alpha=2 * t["lora_rank"])
            if t.get("wandb_project") and os.environ.get("WANDB_API_KEY"):
                kwargs.update(wandb_api_key=os.environ["WANDB_API_KEY"],
                              wandb_project_name=t["wandb_project"],
                              wandb_name=self.cfg["run_name"])
            if t.get("hf_output_repo"):
                kwargs["hf_output_repo_name"] = t["hf_output_repo"]
                if os.environ.get("HF_TOKEN"):
                    kwargs["hf_api_token"] = os.environ["HF_TOKEN"]

            job_id = client.fine_tuning.create(**kwargs).id
            self.state["train"] = {"done": False, "job_id": job_id}
            self.save()
            print(f"launched {job_id}; polling (deadline {JOB_DEADLINE_S // 3600}h)")

        deadline = time.time() + JOB_DEADLINE_S
        net_errors = 0
        while time.time() < deadline:
            try:
                j = client.fine_tuning.retrieve(id=job_id)
                net_errors = 0
            except Exception as e:
                # transient network blips (DNS, wifi) must not kill the
                # watcher — the remote job keeps running either way
                net_errors += 1
                print(f"  {time.strftime('%T')} poll failed ({e.__class__.__name__}), "
                      f"retry {net_errors}/30")
                if net_errors >= 30:
                    sys.exit(f"30 consecutive poll failures; job {job_id} is "
                             f"still running on Together — rerun to resume")
                time.sleep(60)
                continue
            status = str(j.status).lower()
            print(f"  {time.strftime('%T')} {status}")
            if "completed" in status:
                output = j.model_output_name
                self.mark("train", job_id=job_id, model_output_name=output)
                print(f"output model: {output}")
                return
            if "error" in status or "cancel" in status:
                sys.exit(f"job {job_id} ended: {status}")
            time.sleep(60)
        sys.exit(f"job {job_id} still running at deadline; "
                 f"rerunning the pipeline resumes polling this same job")

    def _output_model(self):
        name = self.state.get("train", {}).get("model_output_name")
        if not name:
            sys.exit("no trained model recorded; run the train stage first")
        return name

    def inspect(self):
        e = self.cfg["evals"]["inspect"]
        print(f"inspect: preset={e['preset']} epochs={e['epochs']} "
              f"model=together/<output of train>")
        if not self.live:
            return
        venv_py = REPO / ".venv-inspect" / "bin" / "python"
        if not venv_py.exists():
            sys.exit(f"{venv_py} missing — see code/misalignment_eval/README.md")
        sh([venv_py, REPO / "code" / "misalignment_eval" / "run_eval.py",
            "--model", f"together/{self._output_model()}",
            "--preset", e["preset"], "--epochs", e["epochs"],
            "--run-name", self.cfg["run_name"]],
           cwd=REPO / "code" / "misalignment_eval")
        self.mark("inspect")

    def ant_am(self):
        e = self.cfg["evals"]["ant_am"]
        if not e.get("command"):
            msg = ("evals.ant_am.command is empty — set it to a shell "
                   "command with {model} where the model id goes")
            if self.live:
                sys.exit(msg)
            print(f"ant_am: {msg}")
            return
        cmd = e["command"].format(model=self._output_model()
                                  if self.live else "<output-model>")
        print(f"ant_am: {cmd}")
        if not self.live:
            return
        subprocess.run(cmd, shell=True, check=True)
        self.mark("ant_am")


def main():
    from launch_instruct_ft import load_env
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--redo", action="append", default=[], choices=STAGES,
                    help="clear this stage's state and run it again")
    ap.add_argument("--yes", action="store_true", help="actually run")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    p = Pipeline(cfg, live=args.yes)
    for stage in args.redo:
        p.state.pop(stage, None)
    if args.redo and args.yes:
        p.save()

    enabled = {s: True for s in ("build", "check", "train")}
    enabled["inspect"] = cfg["evals"]["inspect"]["enabled"]
    enabled["ant_am"] = cfg["evals"]["ant_am"]["enabled"]

    print(f"run: {cfg['run_name']}  ({'LIVE' if args.yes else 'dry run'})")
    for stage in STAGES:
        if not enabled[stage]:
            print(f"-- {stage}: disabled")
            continue
        if p.done(stage):
            print(f"-- {stage}: already done "
                  f"({p.state[stage].get('at')}) — use --redo {stage} to rerun")
            continue
        print(f"-- {stage}:")
        getattr(p, stage)()
    if not args.yes:
        print("\ndry run only — rerun with --yes to execute")


if __name__ == "__main__":
    main()
