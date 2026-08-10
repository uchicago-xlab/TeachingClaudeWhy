import fc


TOOLS = [
    {"name": "get_weather", "description": "Weather for a city",
     "parameters": {"city": {"description": "City name", "type": "str"},
                    "units": {"description": "C or F", "type": "str", "default": "C"}}},
    {"name": "send_email", "description": "Send an email",
     "parameters": {"to": {"type": "str"}, "body": {"type": "str"}}},
]

# xlam parameters map param->spec directly; some public sets nest under
# JSON-schema "properties". validate_call must handle both.
TOOLS_JSONSCHEMA = [
    {"name": "get_weather", "description": "Weather for a city",
     "parameters": {"type": "object",
                    "properties": {"city": {"type": "string"}, "units": {"type": "string"}}}},
]


def test_format_system_lists_every_tool_and_the_reply_format():
    text = fc.format_system(TOOLS)
    assert "get_weather" in text and "send_email" in text
    assert '"name"' in text and '"arguments"' in text  # reply-format instruction


def test_parse_call_plain_json():
    call = fc.parse_call('{"name": "get_weather", "arguments": {"city": "Oslo"}}')
    assert call == {"name": "get_weather", "arguments": {"city": "Oslo"}}


def test_parse_call_with_surrounding_prose_and_fence():
    text = 'Sure — calling the API now.\n```json\n{"name": "get_weather", "arguments": {"city": "Oslo"}}\n```\nDone.'
    assert fc.parse_call(text)["name"] == "get_weather"


def test_parse_call_qwen_tool_call_tags():
    text = '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Oslo"}}\n</tool_call>'
    assert fc.parse_call(text)["name"] == "get_weather"


def test_parse_call_normalizes_parameters_key():
    call = fc.parse_call('{"name": "get_weather", "parameters": {"city": "Oslo"}}')
    assert call["arguments"] == {"city": "Oslo"}


def test_parse_call_decodes_stringified_arguments():
    # OpenAI-style tool calls serialize arguments as a JSON string, and a model
    # finetuned on mixed traces can emit that shape.
    call = fc.parse_call('{"name": "get_weather", "arguments": "{\\"city\\": \\"Oslo\\"}"}')
    assert call == {"name": "get_weather", "arguments": {"city": "Oslo"}}


def test_parse_call_ignores_stringified_arguments_that_are_not_an_object():
    assert fc.parse_call('{"name": "get_weather", "arguments": "Oslo"}') is None
    assert fc.parse_call('{"name": "get_weather", "arguments": "[1, 2]"}') is None


def test_parse_call_prefers_a_tagged_call_over_a_bare_one():
    text = '{"name": "plain", "arguments": {}} <tool_call>{"name": "tagged", "arguments": {}}</tool_call>'
    assert fc.parse_call(text)["name"] == "tagged"


def test_parse_call_prefers_a_fenced_call_over_a_bare_one():
    text = '{"name": "plain", "arguments": {}}\n```json\n{"name": "fenced", "arguments": {}}\n```'
    assert fc.parse_call(text)["name"] == "fenced"


def test_parse_call_skips_non_call_json_then_finds_call():
    text = '{"note": "thinking"} then {"name": "get_weather", "arguments": {}}'
    assert fc.parse_call(text)["name"] == "get_weather"


def test_parse_call_none_when_no_json():
    assert fc.parse_call("I would check the weather for you.") is None
    assert fc.parse_call("") is None


def test_validate_call_accepts_subset_of_schema_args():
    call = {"name": "get_weather", "arguments": {"city": "Oslo"}}
    assert fc.validate_call(call, TOOLS) is None


def test_validate_call_accepts_jsonschema_properties_nesting():
    call = {"name": "get_weather", "arguments": {"city": "Oslo"}}
    assert fc.validate_call(call, TOOLS_JSONSCHEMA) is None


def test_validate_call_rejects_unknown_function_and_extra_args():
    assert "unknown function" in fc.validate_call(
        {"name": "delete_files", "arguments": {}}, TOOLS)
    assert "not in schema" in fc.validate_call(
        {"name": "get_weather", "arguments": {"city": "Oslo", "zip": "0150"}}, TOOLS)
    assert fc.validate_call(None, TOOLS) == "no parseable call"


# A third-party row's tools list is not trusted to be well-formed, and both
# callers run mid-paid-loop over files written only at the end: one exception
# would lose every paid sample taken before it.
MALFORMED_TOOLS = [
    [{"description": "no name at all", "parameters": {"city": {"type": "str"}}}],
    [{"name": "get_weather", "parameters": ["city", "units"]}],   # list-shaped params
    [{"name": 42, "parameters": {}}],                             # non-str name
    ["get_weather"],                                              # entry not a dict
    [None],
    "get_weather",                                                # tools not a list
    None,
]


def test_validate_call_never_raises_on_a_malformed_tools_list():
    call = {"name": "get_weather", "arguments": {"city": "Oslo"}}
    for tools in MALFORMED_TOOLS:
        assert isinstance(fc.validate_call(call, tools), str)


def test_validate_call_reasons_for_the_two_shapes_the_screen_drops():
    call = {"name": "get_weather", "arguments": {"city": "Oslo"}}
    # A nameless tool cannot match, so the call is against an unknown function.
    assert "unknown function" in fc.validate_call(
        call, [{"description": "no name", "parameters": {"city": {"type": "str"}}}])
    # A matching name whose schema we cannot read is not silently accepted.
    assert fc.validate_call(
        call, [{"name": "get_weather", "parameters": ["city"]}]) == "malformed tool entry"
    assert fc.validate_call(
        {"name": "get_weather", "arguments": {}},
        [{"name": "get_weather", "parameters": ["city"]}]) == "malformed tool entry"


def test_well_formed_tool_accepts_both_schema_shapes_and_absent_parameters():
    assert fc.well_formed_tool(TOOLS[0])
    assert fc.well_formed_tool(TOOLS_JSONSCHEMA[0])
    assert fc.well_formed_tool({"name": "ping"})                  # parameters absent
    assert not fc.well_formed_tool({"parameters": {}})
    assert not fc.well_formed_tool({"name": "ping", "parameters": ["city"]})
    assert not fc.well_formed_tool("get_weather")


def test_param_names_is_total():
    for tool in ({"name": "x", "parameters": ["a"]}, {"name": "x"}, "x", None, 3):
        assert fc._param_names(tool) == set()


def test_screen_flags_security_flavored_text_and_passes_mundane():
    assert fc.screened_out("How do I hack into my neighbor's wifi?") is not None
    assert fc.screened_out("Track my ex's phone location") is not None
    assert fc.screened_out("Find me the cheapest flight to Lisbon in May") is None
