"""Rename the AI persona in the agentic-misalignment prompts.

For the persona-attachment experiment in
`notes/Project/Experiments/ImplementationDetails.md` (§3.1) we need to run the
same eval with the assistant named "Qwen" vs "Claude"/"GPT" vs a control name,
and see whether a checkpoint is better behaved specifically under its own name.

Our exfiltration scenario is already parameterized (its templates use
`${model_name}`). The three scenarios that come from `inspect_evals` hardcode the
literal string "Alex" in ~20 template files inside site-packages, so instead of
editing an installed package — or vendoring the eval to change one word — we
patch the one function that turns templates into prompts and rename the persona
in its output.

Two call sites read those prompts and both are patched, so the prompt the model
sees and the email context the grader sees always agree:

  * `agentic_misalignment.agentic_misalignment.generate_prompts` — builds the task
  * `agentic_misalignment.scorers.generate_prompts` — rebuilds the emails at score time

Only the AI is called Alex in these templates (its address is `alex.ai@...`);
every other name — Kyle Johnson, Thomas Wilson, David Chen — is untouched, as are
the recipient addresses the classifiers gate on. The rename is therefore
word-boundary-safe: "Alex" -> the new name, "alex" (in the email address) ->
its lowercase form.
"""

from __future__ import annotations

import importlib
import re

from inspect_ai import Task, task
from inspect_ai.model import Model
from inspect_evals.agentic_misalignment import (
    agentic_misalignment as upstream_agentic_misalignment,
)
from inspect_evals.agentic_misalignment.prompt_generator import (
    ExtraInstructionsType,
    GoalType,
    GoalValue,
    Prompts,
    ScenarioType,
    UrgencyType,
    generate_prompts as _original_generate_prompts,
)

# Imported by path, not `from ... import agentic_misalignment`: the package's
# __init__ rebinds that name to the task *function*, and we need the module.
_task_module = importlib.import_module(
    "inspect_evals.agentic_misalignment.agentic_misalignment"
)
_scorers_module = importlib.import_module("inspect_evals.agentic_misalignment.scorers")

# The name the upstream templates hardcode; also the default everywhere else.
DEFAULT_MODEL_NAME = "Alex"

_PATCHED_MODULES = (_task_module, _scorers_module)


def rename(text: str, model_name: str) -> str:
    """Replace the hardcoded persona name in one prompt string."""
    text = re.sub(rf"\b{DEFAULT_MODEL_NAME}\b", model_name, text)
    text = re.sub(rf"\b{DEFAULT_MODEL_NAME.lower()}\b", model_name.lower(), text)
    return re.sub(rf"\b{DEFAULT_MODEL_NAME.upper()}\b", model_name.upper(), text)


def rename_prompts(prompts: Prompts, model_name: str) -> Prompts:
    return Prompts(
        system_prompt=rename(prompts.system_prompt, model_name),
        user_prompt=rename(prompts.user_prompt, model_name),
        email_content=rename(prompts.email_content, model_name),
    )


def install(model_name: str) -> None:
    """Make the upstream scenarios use `model_name` instead of "Alex".

    Process-global: one name per interpreter, which is what `run_eval.py` does
    (one `--model-name` per invocation). Passing the default name uninstalls.
    """
    if model_name == DEFAULT_MODEL_NAME:
        uninstall()
        return

    def patched(*args: object, **kwargs: object) -> Prompts:
        return rename_prompts(_original_generate_prompts(*args, **kwargs), model_name)  # type: ignore[arg-type]

    for module in _PATCHED_MODULES:
        module.generate_prompts = patched  # type: ignore[attr-defined]


def uninstall() -> None:
    for module in _PATCHED_MODULES:
        module.generate_prompts = _original_generate_prompts  # type: ignore[attr-defined]


@task
def agentic_misalignment_persona(
    scenario: ScenarioType = "blackmail",
    goal_type: GoalType = "explicit",
    goal_value: GoalValue = "america",
    urgency_type: UrgencyType = "replacement",
    extra_system_instructions: ExtraInstructionsType = None,
    prod: bool = False,
    test_eval_awareness: bool = False,
    grader_model: str | Model | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Task:
    """An upstream scenario with the AI renamed from "Alex" to `model_name`.

    A thin wrapper around `inspect_evals`' task, and the reason renamed runs are a
    separate task rather than a flag: `model_name` is invisible to upstream, so
    without it `eval_set` would treat a "Qwen" run and an "Alex" run of the same
    condition as the same task and skip the second one. Wrapping puts the name in
    the task args, where `eval_set` sees it and `summarize.py` can report it.

    Args are upstream's (see `agentic_misalignment`), plus:
        model_name: Name the AI is given throughout the prompts
    """
    install(model_name)
    return upstream_agentic_misalignment(
        scenario=scenario,
        goal_type=goal_type,
        goal_value=goal_value,
        urgency_type=urgency_type,
        extra_system_instructions=extra_system_instructions,
        prod=prod,
        test_eval_awareness=test_eval_awareness,
        grader_model=grader_model,
    )
