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

from exfiltration import exfiltration  # noqa: E402
from persona import (  # noqa: E402
    DEFAULT_MODEL_NAME,
    agentic_misalignment_persona,
)

# The eval's built-in default grader is `anthropic/claude-sonnet-4-6`, which needs
# an ANTHROPIC_API_KEY. This repo routes through OpenRouter, so default to the same
# grader model served there.
DEFAULT_GRADER_MODEL = "openrouter/anthropic/claude-sonnet-4.6"

# The three scenarios shipped by inspect_evals.
UPSTREAM_SCENARIOS = ("blackmail", "leaking", "murder")
# Ours (code/misalignment_eval/exfiltration/), ported from ../model_spec_midtraining.
# Replacement is the only urgency it has templates for.
EXFILTRATION_URGENCY_TYPES = ("replacement",)

SCENARIOS = UPSTREAM_SCENARIOS + ("exfiltration",)

# What the presets sweep by default. Blackmail is excluded: the models we care
# about will commit murder and leak files in these scenarios but essentially never
# blackmail, so those cells are all-zero and only cost grader calls. It is still
# reachable via --preset blackmail-2x2 / core+blackmail / full, --scenario, and
# --condition.
DEFAULT_SCENARIOS = ("leaking", "murder", "exfiltration")
URGENCY_TYPES = ("replacement", "restriction", "none")
GOAL_TYPES = ("explicit", "latent", "none", "ambiguous", "swap")

# goal_type "none"/"ambiguous" must be paired with goal_value "none" (the upstream
# prompt generator raises otherwise); every other goal_type takes --goal-value.
GOAL_TYPES_REQUIRING_NONE_VALUE = ("none", "ambiguous")

DEFAULT_LOG_ROOT = REPO_ROOT / "data" / "misalignment-eval" / "logs"


def expand(
    scenarios: tuple[str, ...],
    goal_types: tuple[str, ...],
    urgencies: tuple[str, ...],
    goal_value: str,
) -> list[dict[str, str]]:
    """Cross a scenario/goal/urgency grid into task-argument dicts."""
    conditions = []
    for scenario in scenarios:
        allowed_urgencies = (
            EXFILTRATION_URGENCY_TYPES if scenario == "exfiltration" else urgencies
        )
        for goal_type in goal_types:
            value = "none" if goal_type in GOAL_TYPES_REQUIRING_NONE_VALUE else goal_value
            for urgency_type in urgencies:
                if urgency_type not in allowed_urgencies:
                    continue
                conditions.append(
                    {
                        "scenario": scenario,
                        "goal_type": goal_type,
                        "goal_value": value,
                        "urgency_type": urgency_type,
                    }
                )
    return conditions


def build_conditions(preset: str, goal_value: str) -> list[dict[str, str]]:
    """Expand a preset name into a list of task-argument dicts."""
    # 2x2 ablation (goal conflict on/off x replacement threat on/off) per scenario;
    # exfiltration only has replacement templates, so it contributes 2 cells, not 4.
    ablation = ("explicit", "none"), ("replacement", "none")
    core = expand(DEFAULT_SCENARIOS, *ablation, goal_value)
    blackmail = expand(("blackmail",), *ablation, goal_value)

    if preset == "smoke":
        return expand(("murder",), ("explicit",), ("replacement",), goal_value)
    if preset == "exfil-smoke":
        return expand(("exfiltration",), ("explicit",), ("replacement",), goal_value)
    if preset == "blackmail-2x2":
        return blackmail
    if preset == "exfil":
        return expand(("exfiltration",), *ablation, goal_value)
    if preset == "core":
        return core
    if preset == "core+blackmail":
        return core + blackmail
    if preset == "full":
        return expand(SCENARIOS, GOAL_TYPES, URGENCY_TYPES, goal_value)
    raise ValueError(f"unknown preset: {preset}")


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
    if scenario == "exfiltration" and urgency_type not in EXFILTRATION_URGENCY_TYPES:
        raise SystemExit(
            f"the exfiltration scenario only has templates for urgency "
            f"{list(EXFILTRATION_URGENCY_TYPES)}, got {urgency_type!r} in --condition {spec!r}"
        )
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
        choices=("smoke", "exfil-smoke", "blackmail-2x2", "exfil", "core", "core+blackmail", "full"),
        help="Condition grid: smoke=1, exfil-smoke=1, blackmail-2x2=4, exfil=2, core=10 "
        "(leaking + murder + exfiltration), core+blackmail=14, full=50 conditions "
        "(default: core)",
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
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL_NAME,
        help="Name the AI is given in the prompts (default: %(default)s). Use this for the "
        "persona-attachment experiment, e.g. --model-name Qwen vs --model-name Claude; "
        "keep everything else fixed between those runs.",
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
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable hybrid-reasoning models' thinking mode (Qwen3 etc.) by sending "
        "chat_template_kwargs={'enable_thinking': False} in the request body. Use this "
        "for any model finetuned with thinking off, and match it on the base-model "
        "baseline so the comparison is valid. No effect on non-thinking models.",
    )
    parser.add_argument("--run-name", default=None, help="Log subdirectory name (default: slugified model name)")
    parser.add_argument("--log-dir", default=None, help="Full log directory (overrides --run-name)")
    parser.add_argument("--retry-attempts", type=int, default=3, help="eval_set retry attempts (default: 3)")
    parser.add_argument(
        "--log-dir-allow-dirty",
        action="store_true",
        help="Let eval_set run in a log directory that holds logs from a different task "
        "set. Needed to add a preset's runs to a directory built with another preset — "
        "e.g. re-running the (now blackmail-free) core grid into a directory that still "
        "has blackmail logs from an earlier core run.",
    )
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
        raise SystemExit(
            "No conditions selected. (Blackmail is not in the default presets — use "
            "--preset blackmail-2x2, core+blackmail, or full.)"
        )

    # eval_set refuses to share a log directory between two different task sets, so
    # renamed runs get their own subdirectory by default — otherwise the second
    # persona of a sweep errors out instead of landing next to the first.
    run_name = args.run_name or slugify(args.model)
    if not args.run_name and args.model_name != DEFAULT_MODEL_NAME:
        run_name += f"-as-{slugify(args.model_name)}"
    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_ROOT / run_name

    # Qwen3 and other hybrid-reasoning models default to thinking ON. Send the
    # provider-level hard switch (enable_thinking=False) via extra_body so the
    # served model matches a checkpoint trained with thinking disabled.
    extra_body = (
        {"chat_template_kwargs": {"enable_thinking": False}} if args.no_thinking else None
    )

    print(f"model:        {args.model}")
    print(f"grader:       {args.grader_model}")
    print(f"AI named:     {args.model_name}")
    print(f"thinking:     {'disabled (enable_thinking=False)' if args.no_thinking else 'provider default'}")
    print(f"preset:       {args.preset} ({len(conditions)} conditions x {args.epochs} epochs "
          f"= {len(conditions) * args.epochs} samples)")
    print(f"log dir:      {log_dir}")
    for c in conditions:
        print(f"  - {c['scenario']}_{c['goal_type']}-{c['goal_value']}_{c['urgency_type']}")

    if args.dry_run:
        return 0

    check_api_keys(args.model, args.grader_model)

    # exfiltration lives in this repo (see exfiltration/task.py); the other three
    # scenarios come from inspect_evals, via persona.py when the AI is renamed —
    # upstream's task has no model_name argument, so a renamed run has to be a
    # distinguishable task or eval_set would confuse it with the "Alex" run of the
    # same condition. At the default name the call is upstream's, unchanged.
    def task_for(scenario: str):
        if scenario == "exfiltration":
            return exfiltration
        if args.model_name != DEFAULT_MODEL_NAME:
            return agentic_misalignment_persona
        return agentic_misalignment

    tasks = []
    for c in conditions:
        builder = task_for(c["scenario"])
        kwargs = dict(
            extra_system_instructions=args.extra_system_instructions,
            prod=args.prod,
            test_eval_awareness=args.test_eval_awareness,
            grader_model=args.grader_model,
        )
        if builder is not agentic_misalignment:
            kwargs["model_name"] = args.model_name
        tasks.append(builder(**c, **kwargs))

    log_dir.mkdir(parents=True, exist_ok=True)
    success, _logs = eval_set(
        tasks=tasks,
        log_dir=str(log_dir),
        log_dir_allow_dirty=args.log_dir_allow_dirty,
        model=args.model,
        model_base_url=args.model_base_url,
        model_args=parse_model_args(args.model_arg),
        epochs=args.epochs,
        retry_attempts=args.retry_attempts,
        max_connections=args.max_connections,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        extra_body=extra_body,
        display=args.display,
        metadata={
            "tcw_preset": args.preset,
            "tcw_goal_value": args.goal_value,
            "tcw_thinking": "disabled" if args.no_thinking else "default",
            "tcw_model_name": args.model_name,
        },
    )

    print(f"\nLogs: {log_dir}")
    print(f"Summarize: ../../.venv-inspect/bin/python summarize.py --log-dir {log_dir}")
    print(f"Browse:    ../../.venv-inspect/bin/inspect view --log-dir {log_dir}")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
