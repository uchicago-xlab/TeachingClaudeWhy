# %%
import re

from bs4 import BeautifulSoup

# generate() picks Anthropic or OpenRouter based on .env (see run_pipeline.py)
from run_pipeline import PROMPTS_DIR, ROOT, generate, parse_tags

# %%
with open(PROMPTS_DIR / '1_principles.md') as file:
    text = file.read()
    prompts = re.findall(r'<(v\d.*?)>\s*(.+?)\s*</\1>', text, flags=re.DOTALL)
    prompts = [p[-1] for p in prompts]

with open(ROOT / 'data' / 'constitution' / 'constitution-noname.md') as file:
    constitution = file.read()
    constitution = re.sub(r'\n?<!--.*?-->\n?', '', constitution)

prompts = [prompt.format(constitution=constitution) for prompt in prompts]
print(f'prompt len: {len(prompts[3])}')

principles_prompt = prompts[3]

# %%

principles_raw = generate(principles_prompt, max_tokens=8192)
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

principles_formatted = generate(
    format_principles.format(unformatted=principles_raw), max_tokens=8192
)
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

with open(PROMPTS_DIR / '2_prompt_themes.md') as file:
    themes_prompt = file.read()

themes_prompt = themes_prompt.format(principle=principle)

print(themes_prompt)

# %%
themes_raw = generate(themes_prompt)
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

themes = parse_tags(generate(format_themes.format(unformatted=themes_raw)), "theme")
print(f'parsed {len(themes)} themes')

# %%

selected_theme = themes[4]

with open(PROMPTS_DIR / '3_scenarios.md') as file:
    scenarios_prompt = file.read()

scenarios_prompt = scenarios_prompt.format(principle=principle,
                                           theme=selected_theme)

print(scenarios_prompt)

# %%
scenarios_raw = generate(scenarios_prompt)
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

scenarios = parse_tags(
    generate(format_scenarios.format(unformatted=scenarios_raw)), "scenario"
)
print(f'parsed {len(scenarios)} scenarios')

# %%
