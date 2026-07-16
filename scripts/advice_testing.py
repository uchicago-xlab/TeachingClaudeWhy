# %%
from dotenv import load_dotenv
import re
import anthropic
from bs4 import BeautifulSoup

def chatify(string: str) -> list[dict]:
    return [{"role": "user", "content": string}]

def response_text(message) -> str:
    return "\n".join(block.text for block in message.content if block.type == "text")

def parse_tags(text: str, tag: str) -> list[str]:
    # html.parser is lenient, so stray prose or unescaped characters around
    # the model's XML tags won't break parsing
    soup = BeautifulSoup(text, "html.parser")
    return [el.get_text().strip() for el in soup.find_all(tag)]

load_dotenv()

client = anthropic.Anthropic()

# %%
with open('../prompts/difficult_advice/1_principles.md') as file:
    text = file.read()
    prompts = re.findall(r'<(v\d.*?)>\s*(.+?)\s*</\1>', text, flags=re.DOTALL)
    prompts = [p[-1] for p in prompts]

with open('../data/constitution/constitution-noname.md') as file:
    constitution = file.read()
    constitution = re.sub(r'\n?<!--.*?-->\n?', '', constitution)

prompts = [prompt.format(constitution=constitution) for prompt in prompts]
print(f'prompt len: {len(prompts[3])}')

principles_prompt = prompts[3]

# %%

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=8192,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(principles_prompt)
)

principles_raw = response_text(message)
print(principles_raw)
# %%

format_principles = '''
Format this list of principles with XML tags as follows:
<principle>
<description>
The full, detailed description of the principle.
</description>
<sources>
All of the constitutional sources for this principle.
</sources>
</principle>

Here is the unformatted list of principles:
<unformatted>
{unformatted}
</unformatted>
'''.strip()

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=8192,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(format_principles.format(unformatted=principles_raw))
)

principles_formatted = response_text(message)
principles = [
    {
        "description": p.find("description").get_text().strip(),
        "sources": p.find("sources").get_text().strip(),
    }
    for p in BeautifulSoup(principles_formatted, "html.parser").find_all("principle")
]
print(f'parsed {len(principles)} principles')

# %%

principle = principles[4]['description']

with open('../prompts/difficult_advice/2_prompt_themes.md') as file:
    themes_prompt = file.read()

themes_prompt = themes_prompt.format(principle=principle)

print(themes_prompt)

# %%
message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=4096,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(themes_prompt)
)

themes_raw = response_text(message)
print(themes_raw)
# %%
format_themes = '''
Format this list of themes with XML tags as follows:
<theme>
The full, detailed description of the theme.
</theme>

Here is the unformatted list of themes:
<unformatted>
{unformatted}
</unformatted>
'''.strip()

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=4096,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(format_themes.format(unformatted=themes_raw))
)

themes = parse_tags(response_text(message), "theme")
print(f'parsed {len(themes)} themes')

# %%

selected_theme = themes[4]

with open('../prompts/difficult_advice/3_scenarios.md') as file:
    scenarios_prompt = file.read()

scenarios_prompt = scenarios_prompt.format(principle=principle,
                                           theme=selected_theme)

print(scenarios_prompt)

# %%
message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=4096,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(scenarios_prompt)
)

scenarios_raw = response_text(message)
print(scenarios_raw)
# %%
format_scenarios = '''
Format this list of scenarios with XML tags as follows:
<scenario>
The full, detailed description of the scenario.
</scenario>

Here is the unformatted list of scenarios:
<unformatted>
{unformatted}
</unformatted>
'''.strip()

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=4096,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(format_scenarios.format(unformatted=scenarios_raw))
)

scenarios = parse_tags(response_text(message), "scenario")
print(f'parsed {len(scenarios)} scenarios')

# %%
