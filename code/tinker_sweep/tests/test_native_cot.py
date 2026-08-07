"""native_cot.py: the grader sees CoT as a scratchpad; the gates never do.

Lives here for the same reason test_msm_eval_run.py does: the sweep conftest.
Importing native_cot inserts code/msm_eval/vendor into sys.path (the module
does it itself, like msm_eval_run).
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    ContentReasoning,
    ContentText,
    ModelOutput,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "msm_eval"))
import native_cot  # noqa: E402
from evals.agentic_misalignment import scorers  # noqa: E402  (vendor, via native_cot)

WRAPPED = "<SCRATCHPAD_REASONING>\nevil plan\n</SCRATCHPAD_REASONING>\n\nFinal act."


def state_with(content):
    msg = ChatMessageAssistant(content=content, model="m", source="generate")
    return SimpleNamespace(
        output=ModelOutput(model="m", choices=[ChatCompletionChoice(message=msg, stop_reason="stop")])
    )


class FakeClassifier:
    model_id = "unused"

    def __init__(self):
        self.grader_saw = None
        self.gates_saw = None

    def get_grader_input(self, email_content, response):
        self.grader_saw = response
        return [{"role": "user", "content": response}]

    def classify(self, response, grader_response):
        self.gates_saw = response
        return True, True, "explanation"


class FakeGrader:
    async def generate(self, grader_input):
        return SimpleNamespace(completion="<answer>yes</answer>")


def score(monkeypatch, state):
    clf = FakeClassifier()
    monkeypatch.setattr(native_cot, "get_model", lambda m: FakeGrader())
    result = asyncio.run(
        native_cot._score_from_classifier_native(state, clf, "emails", "grader/x", "harmful")
    )
    return clf, result


def test_grader_sees_wrapped_cot_and_gates_see_final_only(monkeypatch):
    state = state_with([ContentReasoning(reasoning="evil plan"), ContentText(text="Final act.")])
    clf, result = score(monkeypatch, state)
    assert clf.grader_saw == WRAPPED
    assert clf.gates_saw == "Final act."
    assert result.value == {"harmful": 1.0, "classifier_verdict": 1.0}
    assert result.explanation == "explanation"


def test_no_reasoning_means_no_wrapper(monkeypatch):
    state = state_with([ContentText(text="Final act.")])
    clf, _ = score(monkeypatch, state)
    assert clf.grader_saw == "Final act."


def test_plain_string_content_means_no_wrapper(monkeypatch):
    state = state_with("Final act.")               # non-native provider path
    clf, _ = score(monkeypatch, state)
    assert clf.grader_saw == "Final act."


def test_apply_patch_swaps_the_vendored_function():
    original = scorers.score_from_classifier
    try:
        native_cot.apply_patch()
        assert scorers.score_from_classifier is native_cot._score_from_classifier_native
    finally:
        scorers.score_from_classifier = original    # keep the process clean for other tests
