# %%
from dotenv import load_dotenv
import re
import anthropic

def chatify(string: str) -> list[dict]:
    return [{"role": "user", "content": string}]

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

principles_raw = message.content[1].text
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
{principles}
</unformatted>
'''.strip()

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=8192,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(format_principles.format(principles_raw))
)

principles = None # parse into list of principle, sources dict

# %%

principle = principles[6]['principle']

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

print(message.content[1].text)
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

# %%

selected_theme = themes[3]

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

print(message.content[1].text)
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

