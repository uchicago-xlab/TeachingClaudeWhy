"""Run MSM's agentic-misalignment eval against a vLLM-served model.

Scoped grid: exfiltration/leaking/murder x goal-conflict {explicit-america,
none}, urgency=replacement, n=30, temp 0.7, reasoning scratchpad (prod=False),
model_name=Qwen — i.e. MSM's non-reasoning per-sample settings. Grader is
OpenRouter Sonnet, fixed across models.

    PYTHONPATH=<msm_vendor> .venv-inspect/bin/python msm_eval_run.py \
        --model openai/<served> --base-url http://<pod>:8000/v1 --run-name <name>
"""
import argparse, os, sys
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
# MSM's agentic-misalignment port, vendored in-repo (see vendor/README.md)
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
load_dotenv(REPO / ".env")
os.environ.setdefault("OPENAI_API_KEY", "vllm-dummy")  # vLLM ignores the key

from inspect_ai import eval_set
from evals.agentic_misalignment.agentic_misalignment import agentic_misalignment

GRADER = "openrouter/anthropic/claude-sonnet-4.6"
SCENARIOS = ("exfiltration", "leaking", "murder")
GOALS = (("explicit", "america"), ("none", "none"))  # conflict on / off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--urgency-type", default="replacement",
                    choices=("replacement", "restriction", "none"),
                    help="threat variant; the standardized slice uses "
                         "replacement — restriction added 2026-07-28 as a "
                         "generalization check (encode it in --run-name)")
    ap.add_argument("--model-name", default="Qwen",
                    help="name the scenario prompts address the AI by; "
                         "default Qwen matches the served model — other "
                         "values (name-variant eval, 2026-07-30) test "
                         "identity sensitivity (encode it in --run-name)")
    ap.add_argument("--no-thinking", action="store_true",
                    help="send chat_template_kwargs={'enable_thinking': False} "
                         "so a hybrid-reasoning student matches the "
                         "non-reasoning setting this slice assumes. Required "
                         "for Qwen3 arms (Qwen2.5 has no thinking mode, so "
                         "Anastasia's 32B runs never needed it) and must match "
                         "across every arm including the base control")
    args = ap.parse_args()

    # Qwen3 defaults to thinking ON. This is a model-level correction, not a
    # condition change: it makes the student behave the way the fixed slice
    # already assumes. Apply it to every arm of a comparison or none.
    extra_body = ({"chat_template_kwargs": {"enable_thinking": False}}
                  if args.no_thinking else None)

    tasks = [
        agentic_misalignment(
            scenario=s, goal_type=gt, goal_value=gv,
            urgency_type=args.urgency_type, prod=False,
            model_name=args.model_name, grader_model=GRADER,
        )
        for s in SCENARIOS for (gt, gv) in GOALS
    ]
    log_dir = REPO / "tmp" / "msm-eval" / args.run_name
    print(f"model={args.model} url={args.base_url} "
          f"name={args.model_name} "
          f"thinking={'disabled' if args.no_thinking else 'provider default'} "
          f"{len(tasks)} conditions x {args.epochs} = {len(tasks)*args.epochs} samples")

    ok, _ = eval_set(
        tasks=tasks, log_dir=str(log_dir),
        model=args.model, model_base_url=args.base_url,
        epochs=args.epochs, temperature=0.7, max_tokens=4096,
        extra_body=extra_body,
        max_connections=16, retry_attempts=3, display="plain",
    )
    print(f"{'DONE' if ok else 'INCOMPLETE'}: {log_dir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
