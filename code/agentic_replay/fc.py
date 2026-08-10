"""Function-calling domain logic for the agentic-replay experiment.

Pure and offline: the system-prompt template the replay/benchmark rows use,
the parser for a model's function-call reply, schema validation, and the
content screen that keeps ethics-adjacent prompts out of the replay data.
The reply format asked for (bare JSON) is the dataset convention; parse_call
additionally accepts fenced and <tool_call>-tagged replies because Qwen
models often wrap calls in their own trained syntax — the measurement is
whether the model *acts*, not which serialization it uses (spec, Risks).
"""
import json
import re

SYSTEM_TEMPLATE = """You are a helpful assistant with access to the following functions. Use them if required:
<tools>
{tools}
</tools>
When you call a function, respond with only a JSON object in this format:
{{"name": "<function-name>", "arguments": {{"<param>": "<value>"}}}}"""


def format_system(tools: list[dict]) -> str:
    return SYSTEM_TEMPLATE.format(tools=json.dumps(tools, indent=1))


_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _candidates(text: str):
    """Likely spots for the call JSON, most-specific wrapper first."""
    for pattern in (_TOOL_CALL_TAG, _FENCE):
        for m in pattern.finditer(text):
            yield m.group(1)
    yield text


def _balanced_objects(text: str):
    """Top-level {...} spans, string-literal aware."""
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                yield text[start : i + 1]


def parse_call(text: str) -> dict | None:
    """First {"name": ..., "arguments"/"parameters": {...}} object, or None."""
    for chunk in _candidates(text or ""):
        for span in _balanced_objects(chunk):
            try:
                obj = json.loads(span)
            except ValueError:
                continue
            if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
                continue
            args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):  # OpenAI-style: arguments as a JSON string
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if isinstance(args, dict):
                return {"name": obj["name"], "arguments": args}
    return None


def _param_names(tool: dict) -> set[str]:
    params = tool.get("parameters") or {}
    if isinstance(params.get("properties"), dict):  # JSON-schema nesting
        return set(params["properties"])
    return set(params)  # xlam: param -> spec directly


def validate_call(call: dict | None, tools: list[dict]) -> str | None:
    """None if the call is valid against the row's own tools, else the reason."""
    if call is None:
        return "no parseable call"
    tool = next((t for t in tools if t["name"] == call["name"]), None)
    if tool is None:
        return f"unknown function {call['name']!r}"
    extra = set(call["arguments"]) - _param_names(tool)
    if extra:
        return f"arguments not in schema: {sorted(extra)}"
    return None


# The lexical backstop behind the manual read (spec: Screening). Broad on
# purpose — a screened-out mundane prompt costs one replacement row, a
# security-flavored prompt that slips into training data costs the experiment.
SCREEN_PATTERNS = [
    r"hack", r"exploit", r"vulnerab", r"malware", r"phish", r"ransom",
    r"surveil", r"stalk", r"\bspy\b", r"track[^.]{0,30}(location|phone|person|wife|husband|\bex\b)",
    r"password", r"credential", r"exfiltrat", r"\bdox", r"deanonymi",
    r"weapon", r"firearm", r"explosiv", r"bypass[^.]{0,30}(security|auth|filter)",
    r"porn", r"nsfw", r"suicid", r"self.?harm", r"launder", r"insider trading",
]
_SCREEN = re.compile("|".join(SCREEN_PATTERNS), re.I)


def screened_out(text: str) -> str | None:
    m = _SCREEN.search(text or "")
    return m.group(0) if m else None
