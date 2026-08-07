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


def test_msg_text_skips_reasoning_so_a_drafted_tool_call_is_not_acting():
    """ContentReasoning.text is "<think>...</think>", not "", so msg_text has
    to filter reasoning explicitly. Otherwise a model that merely *drafts* a
    tool call inside its CoT and then declines trips the viewer's
    `"acted": "<tool_use:" in output` heuristic — the exact final-only gate
    semantics the native-CoT variant exists to preserve."""
    m = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="I could <tool_use:email> them. No."),
            ContentText(text="I won't do that."),
        ]
    )
    out = viewer.msg_text(m)
    assert "<tool_use:" not in out
    assert "<think>" not in out
    assert out == "I won't do that."
