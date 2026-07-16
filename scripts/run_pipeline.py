"""Run the full difficult-advice pipeline end to end:

constitution -> principles -> themes -> scenarios -> initial prompts

Produces N_PROMPTS initial (system, user) prompt pairs for quality review,
written to tmp/initial_prompts.md (human-readable) and tmp/initial_prompts.json
(full pipeline artifacts).
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts" / "difficult_advice"
OUT_DIR = ROOT / "tmp"

PRINCIPLES_VARIANT = 3  # v4-character
PRINCIPLE_INDEX = 4
THEME_INDEX = 4
N_PROMPTS = 10

load_dotenv(ROOT / ".env")
client = anthropic.Anthropic()


def chatify(string: str) -> list[dict]:
    return [{"role": "user", "content": string}]


def response_text(message) -> str:
    return "\n".join(block.text for block in message.content if block.type == "text")


def parse_tags(text: str, tag: str) -> list[str]:
    # html.parser is lenient, so stray prose or unescaped characters around
    # the model's XML tags won't break parsing
    soup = BeautifulSoup(text, "html.parser")
    return [el.get_text().strip() for el in soup.find_all(tag)]


def generate(prompt: str, max_tokens: int = 4096) -> str:
    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=max_tokens,
        thinking={"type": "adaptive", "display": "summarized"},
        messages=chatify(prompt),
    )
    return response_text(message)


FORMAT_PRINCIPLES = """
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
""".strip()

FORMAT_LIST = """
Format this list of {name}s with XML tags as follows:
<{name}>
The full, detailed description of the {name}.
</{name}>

Here is the unformatted list of {name}s:
<unformatted>
{unformatted}
</unformatted>
""".strip()


def stage_principles() -> list[dict]:
    text = (PROMPTS_DIR / "1_principles.md").read_text()
    variants = re.findall(r"<(v\d.*?)>\s*(.+?)\s*</\1>", text, flags=re.DOTALL)
    prompt_template = variants[PRINCIPLES_VARIANT][-1]

    constitution = (ROOT / "data" / "constitution" / "constitution-noname.md").read_text()
    constitution = re.sub(r"\n?<!--.*?-->\n?", "", constitution)

    raw = generate(prompt_template.format(constitution=constitution), max_tokens=8192)
    formatted = generate(FORMAT_PRINCIPLES.format(unformatted=raw), max_tokens=8192)
    principles = [
        {
            "description": p.find("description").get_text().strip(),
            "sources": p.find("sources").get_text().strip(),
        }
        for p in BeautifulSoup(formatted, "html.parser").find_all("principle")
    ]
    print(f"parsed {len(principles)} principles")
    return principles


def stage_themes(principle: str) -> list[str]:
    template = (PROMPTS_DIR / "2_prompt_themes.md").read_text()
    raw = generate(template.format(principle=principle))
    formatted = generate(FORMAT_LIST.format(name="theme", unformatted=raw))
    themes = parse_tags(formatted, "theme")
    print(f"parsed {len(themes)} themes")
    return themes


def stage_scenarios(principle: str, theme: str) -> list[str]:
    template = (PROMPTS_DIR / "3_scenarios.md").read_text()
    raw = generate(template.format(principle=principle, theme=theme))
    formatted = generate(FORMAT_LIST.format(name="scenario", unformatted=raw))
    scenarios = parse_tags(formatted, "scenario")
    print(f"parsed {len(scenarios)} scenarios")
    return scenarios


def stage_initial_prompt(principle: str, scenario: str) -> dict:
    template = (PROMPTS_DIR / "4_initial_prompt.md").read_text()
    raw = generate(template.format(principle=principle, scenario=scenario))
    systems = parse_tags(raw, "system")
    users = parse_tags(raw, "user")
    return {
        "scenario": scenario,
        "system": systems[0] if systems else None,
        "user": users[0] if users else None,
        "raw": raw,
    }


def main():
    principles = stage_principles()
    principle = principles[PRINCIPLE_INDEX]["description"]

    themes = stage_themes(principle)

    # Collect scenarios starting from the selected theme, moving through
    # subsequent themes if one theme doesn't yield enough for N_PROMPTS
    scenarios = []  # (theme, scenario) pairs
    theme_index = THEME_INDEX
    while len(scenarios) < N_PROMPTS and theme_index < len(themes):
        theme = themes[theme_index]
        scenarios += [(theme, s) for s in stage_scenarios(principle, theme)]
        theme_index += 1
    scenarios = scenarios[:N_PROMPTS]
    if len(scenarios) < N_PROMPTS:
        print(f"warning: only {len(scenarios)} scenarios available")

    with ThreadPoolExecutor(max_workers=5) as pool:
        prompts = list(
            pool.map(lambda ts: stage_initial_prompt(principle, ts[1]), scenarios)
        )
    for prompt, (theme, _) in zip(prompts, scenarios):
        prompt["theme"] = theme
    n_parsed = sum(1 for p in prompts if p["system"] and p["user"])
    print(f"generated {len(prompts)} initial prompts ({n_parsed} parsed cleanly)")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "initial_prompts.json").write_text(
        json.dumps(
            {
                "principles": principles,
                "principle_index": PRINCIPLE_INDEX,
                "themes": themes,
                "prompts": prompts,
            },
            indent=2,
        )
    )

    lines = [f"# Initial prompts for review\n\n## Principle\n\n{principle}\n"]
    for i, p in enumerate(prompts, 1):
        lines.append(f"\n---\n\n## Prompt {i}\n")
        lines.append(f"### Theme\n\n{p['theme']}\n")
        lines.append(f"### Scenario\n\n{p['scenario']}\n")
        if p["system"] and p["user"]:
            lines.append(f"### System\n\n{p['system']}\n")
            lines.append(f"### User\n\n{p['user']}\n")
        else:
            lines.append(f"### PARSE FAILURE — raw output\n\n{p['raw']}\n")
    (OUT_DIR / "initial_prompts.md").write_text("\n".join(lines))

    print(f"wrote {OUT_DIR / 'initial_prompts.md'} and initial_prompts.json")


if __name__ == "__main__":
    main()
