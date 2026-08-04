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
    ap.add_argument("--api-no-reasoning", action="store_true",
                    help="disable reasoning for API teachers served via the "
                         "openrouter/ provider (reasoning={'enabled': false}, "
                         "forwarded through the provider's own model_args — "
                         "verified to reach the wire, unlike plain openai/ "
                         "extra_body). The thinking-off teacher baseline: "
                         "students train on no-CoT data, so this is the "
                         "matched teacher condition. Encode in --run-name. "
                         "For vLLM-served students use --no-thinking instead.")
    ap.add_argument("--max-tokens", type=int, default=4096,
                    help="completion cap; the standardized slice uses 4096. "
                         "Raise it ONLY as a model-level correction for API "
                         "reasoning teachers whose hidden thinking burns the "
                         "cap and truncates the visible action (2026-08-05: "
                         "sonnet-5 teacher run truncated 159/180 samples at "
                         "4096 and scored an artifactual 0%). Encode any "
                         "non-default value in --run-name")
    ap.add_argument("--stop-token-ids", default="",
                    help="comma-separated token ids to stop generation on, "
                         "sent as stop_token_ids. Required for checkpoints "
                         "built on the Qwen2.5 BASE models: their "
                         "generation_config lists only <|endoftext|> (151643) "
                         "as eos while the chat template ends assistant turns "
                         "with <|im_end|> (151645), so without it a sample can "
                         "run past the turn boundary and burn max_tokens on "
                         "junk. Pass 151645 for those, and match it across "
                         "every arm like --no-thinking")
    args = ap.parse_args()

    # Both switches are model-level corrections, not condition changes: they
    # make the student behave the way the fixed slice already assumes. Apply
    # each to every arm of a comparison or to none. Built as one dict so the
    # two compose — a Qwen3 checkpoint trained from a base model would need
    # both at once.
    extra_body = {}
    if args.no_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
    if args.stop_token_ids:
        extra_body["stop_token_ids"] = [
            int(t) for t in args.stop_token_ids.split(",") if t.strip()
        ]
    extra_body = extra_body or None

    # Inspect's plain `openai/` provider SILENTLY DROPS extra_body: the value is
    # recorded in the eval log's generate config, but never reaches the server,
    # so the run produces full <think> blocks while claiming thinking is off.
    # Verified 2026-07-31 against vLLM 0.26 — identical output with and without.
    # `openai-api/<service>/<model>` does forward it (same finding as the
    # decision log in code/serving/README.md). Fail loudly rather than emit a
    # mislabeled run: a whole grid was evaluated with thinking ON before this
    # guard existed, and nothing in the artifacts revealed it.
    if extra_body and args.model.startswith("openai/"):
        dropped = " and ".join(
            f"--{f}" for f, on in (("no-thinking", args.no_thinking),
                                   ("stop-token-ids", bool(args.stop_token_ids)))
            if on
        )
        sys.exit(
            f"{dropped} cannot work with the plain `openai/` provider: "
            f"Inspect drops extra_body, so the setting never reaches the server "
            f"while the run claims otherwise.\n"
            f"Use the openai-api form instead, e.g.:\n"
            f"  --model openai-api/vllm/{args.model[len('openai/'):]}\n"
            f"with VLLM_API_KEY set (and --base-url as normal)."
        )

    tasks = [
        agentic_misalignment(
            scenario=s, goal_type=gt, goal_value=gv,
            urgency_type=args.urgency_type, prod=False,
            model_name=args.model_name, grader_model=GRADER,
        )
        for s in SCENARIOS for (gt, gv) in GOALS
    ]
    log_dir = REPO / "data" / "msm-eval" / args.run_name
    print(f"model={args.model} url={args.base_url} "
          f"name={args.model_name} "
          f"thinking={'disabled' if args.no_thinking else 'provider default'} "
          f"stop_token_ids={args.stop_token_ids or '(provider default eos)'} "
          f"{len(tasks)} conditions x {args.epochs} = {len(tasks)*args.epochs} samples")

    if args.api_no_reasoning and not args.model.startswith("openrouter/"):
        sys.exit("--api-no-reasoning is an openrouter/-provider knob; "
                 "for vLLM-served students use --no-thinking.")

    ok, _ = eval_set(
        tasks=tasks, log_dir=str(log_dir),
        model=args.model, model_base_url=args.base_url,
        epochs=args.epochs, temperature=0.7, max_tokens=args.max_tokens,
        extra_body=extra_body,
        **({"model_args": {"reasoning_enabled": False}}
           if args.api_no_reasoning else {}),
        max_connections=16, retry_attempts=3, display="plain",
    )
    print(f"{'DONE' if ok else 'INCOMPLETE'}: {log_dir}")
    if ok:  # keep the transcript viewer current (incremental, non-fatal)
        import subprocess
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "build_transcript_viewer.py"),
             "--eval-dir", str(log_dir.parent)], check=False)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
