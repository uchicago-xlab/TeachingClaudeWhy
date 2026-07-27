#!/usr/bin/env python
"""Run Inspect AI's agentic-misalignment eval against a Together.ai-hosted model.

The eval is `inspect_evals/agentic_misalignment` (the AISI port of Anthropic's
agentic-misalignment work). Each task instance is a *single* prompt for one
condition, so statistics come from `--epochs` (repeated samples) and from
sweeping the condition grid, not from dataset size.

Run from this directory with the eval venv:

    ../../.venv-inspect/bin/python run_eval.py --model together/Qwen/Qwen2.5-32B-Instruct

See README.md for setup, presets, and cost notes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

from inspect_ai import eval_set  # noqa: E402
from inspect_evals.agentic_misalignment import agentic_misalignment  # noqa: E402

# The eval's built-in default grader is `anthropic/claude-sonnet-4-6`, which needs
# an ANTHROPIC_API_KEY. This repo routes through OpenRouter, so default to the same
# grader model served there.
DEFAULT_GRADER_MODEL = "openrouter/anthropic/claude-sonnet-4.6"

SCENARIOS = ("blackmail", "leaking", "murder")
URGENCY_TYPES = ("replacement", "restriction", "none")
GOAL_TYPES = ("explicit", "latent", "none", "ambiguous", "swap")

# goal_type "none"/"ambiguous" must be paired with goal_value "none" (the upstream
# prompt generator raises otherwise); every other goal_type takes --goal-value.
GOAL_TYPES_REQUIRING_NONE_VALUE = ("none", "ambiguous")

DEFAULT_LOG_ROOT = REPO_ROOT / "tmp" / "misalignment-eval" / "logs"


def build_conditions(preset: str, goal_value: str) -> list[dict[str, str]]:
    """Expand a preset name into a list of task-argument dicts."""
    if preset == "smoke":
        scenarios, goal_types, urgencies = ("blackmail",), ("explicit",), ("replacement",)
    elif preset == "blackmail-2x2":
        scenarios, goal_types, urgencies = ("blackmail",), ("explicit", "none"), ("replacement", "none")
    elif preset == "core":
        # 2x2 ablation (goal conflict on/off x replacement threat on/off) per scenario.
        scenarios, goal_types, urgencies = SCENARIOS, ("explicit", "none"), ("replacement", "none")
    elif preset == "full":
        scenarios, goal_types, urgencies = SCENARIOS, GOAL_TYPES, URGENCY_TYPES
    else:
        raise ValueError(f"unknown preset: {preset}")

    conditions = []
    for scenario in scenarios:
        for goal_type in goal_types:
            value = "none" if goal_type in GOAL_TYPES_REQUIRING_NONE_VALUE else goal_value
            for urgency_type in urgencies:
                conditions.append(
                    {
                        "scenario": scenario,
                        "goal_type": goal_type,
                        "goal_value": value,
                        "urgency_type": urgency_type,
                    }
                )
    return conditions


def parse_condition(spec: str, goal_value: str) -> dict[str, str]:
    """Parse a `scenario:goal_type:urgency` condition spec."""
    parts = spec.split(":")
    if len(parts) != 3:
        raise SystemExit(f"--condition expects SCENARIO:GOAL_TYPE:URGENCY, got {spec!r}")
    scenario, goal_type, urgency_type = parts
    for value, allowed, label in (
        (scenario, SCENARIOS, "scenario"),
        (goal_type, GOAL_TYPES, "goal_type"),
        (urgency_type, URGENCY_TYPES, "urgency_type"),
    ):
        if value not in allowed:
            raise SystemExit(f"invalid {label} {value!r} in --condition {spec!r}; choose from {list(allowed)}")
    return {
        "scenario": scenario,
        "goal_type": goal_type,
        "goal_value": "none" if goal_type in GOAL_TYPES_REQUIRING_NONE_VALUE else goal_value,
        "urgency_type": urgency_type,
    }


def slugify(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def parse_model_args(pairs: list[str]) -> dict[str, object]:
    """Parse `-M key=value` style overrides passed through to the provider."""
    args: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--model-arg expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        if value.lower() in ("true", "false"):
            parsed: object = value.lower() == "true"
        else:
            try:
                parsed = int(value)
            except ValueError:
                try:
                    parsed = float(value)
                except ValueError:
                    parsed = value
        args[key] = parsed
    return args


def check_api_keys(model: str, grader_model: str) -> None:
    import os

    needed = {}
    for spec, label in ((model, "model under test"), (grader_model, "grader")):
        provider = spec.split("/", 1)[0]
        env_var = {
            "together": "TOGETHER_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
        }.get(provider)
        if env_var and not os.environ.get(env_var):
            needed[env_var] = f"{label} ({spec})"
    if needed:
        lines = [f"  {var} — required by {why}" for var, why in needed.items()]
        raise SystemExit(
            "Missing API key(s) in environment or "
            f"{REPO_ROOT / '.env'}:\n" + "\n".join(lines)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--model",
        required=True,
        help="Inspect model spec, e.g. together/Qwen/Qwen2.5-32B-Instruct",
    )
    parser.add_argument(
        "--grader-model",
        default=DEFAULT_GRADER_MODEL,
        help=f"Model used by the harmfulness classifier (default: {DEFAULT_GRADER_MODEL})",
    )
    parser.add_argument(
        "--preset",
        default="core",
        choices=("smoke", "blackmail-2x2", "core", "full"),
        help="Condition grid: smoke=1, blackmail-2x2=4, core=12, full=45 conditions (default: core)",
    )
    parser.add_argument("--scenario", choices=SCENARIOS, action="append", help="Restrict preset to these scenarios")
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        metavar="SCENARIO:GOAL_TYPE:URGENCY",
        help="Run exactly these condition(s) instead of a preset (repeatable), "
        "e.g. --condition murder:explicit:replacement",
    )
    parser.add_argument(
        "--goal-value",
        default="america",
        choices=("america", "global", "safety", "acceleration", "ethical", "pragmatic", "individualism", "collectivism"),
        help="Goal given to the model for explicit/latent/swap conditions (default: america)",
    )
    parser.add_argument("--epochs", type=int, default=10, help="Samples per condition (default: 10)")
    parser.add_argument("--temperature", type=float, default=1.0, help="Sampling temperature (default: 1.0)")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max completion tokens (default: 4096)")
    parser.add_argument("--max-connections", type=int, default=8, help="Concurrent model requests (default: 8)")
    parser.add_argument("--prod", action="store_true", help="Remove the 'secret scratchpad' framing from the prompt")
    parser.add_argument("--test-eval-awareness", action="store_true", help="Also score whether the model says it is being evaluated")
    parser.add_argument(
        "--extra-system-instructions",
        choices=("dont", "goal"),
        default=None,
        help="Optional extra system instructions ('dont' = safety guidance, 'goal' = employee-welfare goal)",
    )
    parser.add_argument("--model-base-url", default=None, help="Override the provider base URL")
    parser.add_argument(
        "--model-arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Provider model arg (repeatable), e.g. --model-arg stream=true",
    )
    parser.add_argument("--run-name", default=None, help="Log subdirectory name (default: slugified model name)")
    parser.add_argument("--log-dir", default=None, help="Full log directory (overrides --run-name)")
    parser.add_argument("--retry-attempts", type=int, default=3, help="eval_set retry attempts (default: 3)")
    parser.add_argument("--display", default="full", choices=("full", "conversation", "rich", "plain", "log", "none"))
    parser.add_argument("--dry-run", action="store_true", help="Print the condition grid and exit without calling any API")
    args = parser.parse_args()

    if args.condition:
        conditions = [parse_condition(spec, args.goal_value) for spec in args.condition]
    else:
        conditions = build_conditions(args.preset, args.goal_value)
    if args.scenario:
        conditions = [c for c in conditions if c["scenario"] in args.scenario]
    if not conditions:
        raise SystemExit("No conditions selected.")

    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_ROOT / (args.run_name or slugify(args.model))

    print(f"model:        {args.model}")
    print(f"grader:       {args.grader_model}")
    print(f"preset:       {args.preset} ({len(conditions)} conditions x {args.epochs} epochs "
          f"= {len(conditions) * args.epochs} samples)")
    print(f"log dir:      {log_dir}")
    for c in conditions:
        print(f"  - {c['scenario']}_{c['goal_type']}-{c['goal_value']}_{c['urgency_type']}")

    if args.dry_run:
        return 0

    check_api_keys(args.model, args.grader_model)

    tasks = [
        agentic_misalignment(
            **c,
            extra_system_instructions=args.extra_system_instructions,
            prod=args.prod,
            test_eval_awareness=args.test_eval_awareness,
            grader_model=args.grader_model,
        )
        for c in conditions
    ]

    log_dir.mkdir(parents=True, exist_ok=True)
    success, _logs = eval_set(
        tasks=tasks,
        log_dir=str(log_dir),
        model=args.model,
        model_base_url=args.model_base_url,
        model_args=parse_model_args(args.model_arg),
        epochs=args.epochs,
        retry_attempts=args.retry_attempts,
        max_connections=args.max_connections,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        display=args.display,
        metadata={"tcw_preset": args.preset, "tcw_goal_value": args.goal_value},
    )

    print(f"\nLogs: {log_dir}")
    print(f"Summarize: ../../.venv-inspect/bin/python summarize.py --log-dir {log_dir}")
    print(f"Browse:    ../../.venv-inspect/bin/inspect view --log-dir {log_dir}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
