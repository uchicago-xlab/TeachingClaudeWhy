"""The transcript viewer must surface native-CoT reasoning parts separately.

Lives here for the same reason test_native_cot.py does: the sweep conftest.
`build_transcript_viewer` is a unique module name in the repo, so a plain
sys.path insert is enough — no importlib-under-an-alias dance needed.
"""
import sys
from pathlib import Path

from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ContentReasoning, ContentText

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "msm_eval"))
import build_transcript_viewer as viewer  # noqa: E402


def test_assistant_reasoning_joins_reasoning_parts_only():
    messages = [
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(
            content=[ContentReasoning(reasoning="scheme"), ContentText(text="act")]
        ),
    ]
    assert viewer.assistant_reasoning(messages) == "scheme"


def test_assistant_reasoning_empty_for_plain_string_output():
    messages = [ChatMessageAssistant(content="just text")]
    assert viewer.assistant_reasoning(messages) == ""
