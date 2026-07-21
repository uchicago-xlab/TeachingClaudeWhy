"""Run the full difficult-advice pipeline end to end:

constitution -> principles -> themes -> scenarios -> initial prompts

Produces N_PROMPTS initial (system, user) prompt pairs for quality review,
written to tmp/initial_prompts.md (human-readable) and tmp/initial_prompts.json
(full pipeline artifacts).
"""

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts" / "difficult_advice"
OUT_DIR = ROOT / "tmp"

PRINCIPLES_VARIANT = 3  # v4-character
FORMAT_MODEL = "claude-haiku-4-5"  # XML-formatting calls don't need Opus
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


def generate(
    prompt: str,
    max_tokens: int = 4096,
    system: str | None = None,
    model: str = "claude-opus-4-8",
    effort: str | None = None,
) -> str:
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        # adaptive thinking isn't supported on Haiku 4.5, and formatting
        # calls don't need it anyway
        **({"thinking": {"type": "adaptive", "display": "summarized"}} if "opus" in model else {}),
        # thinking tokens count toward max_tokens; effort is the only knob that
        # bounds thinking depth on Opus 4.8 (budget_tokens is removed)
        **({"output_config": {"effort": effort}} if effort else {}),
        messages=chatify(prompt),
        **({"system": system} if system is not None else {}),
    )
    # the SDK's built-in retries (2, seconds apart) don't survive sustained
    # 529 Overloaded periods; back off patiently before giving up
    for attempt in range(5):
        try:
            if max_tokens > 8192:
                # the SDK requires streaming for requests that could exceed 10 minutes
                with client.messages.stream(**kwargs) as stream:
                    message = stream.get_final_message()
            else:
                message = client.messages.create(**kwargs)
            return response_text(message)
        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            # 529 subclasses APIStatusError directly, NOT InternalServerError;
            # the SDK also skips its own retries for it (x-should-retry: false)
            anthropic.OverloadedError,
            anthropic.APIConnectionError,
        ) as err:
            if attempt == 4:
                raise
            delay = min(60, 5 * 2**attempt) + random.uniform(0, 3)
            print(f"retryable API error ({type(err).__name__}), sleeping {delay:.0f}s")
            time.sleep(delay)


FORMAT_VERBATIM = (
    "Copy each item's text verbatim, including any markdown formatting such as bold"
    " headers or bullet points. Do not paraphrase, shorten, or omit anything; only"
    " remove list numbering."
)

FORMAT_PRINCIPLES = f"""
Format this list of principles with XML tags as follows:
<principle>
<description>
The full, detailed description of the principle.
</description>
<sources>
All of the constitutional sources for this principle.
</sources>
</principle>

{FORMAT_VERBATIM}

Here is the unformatted list of principles:
<unformatted>
{{unformatted}}
</unformatted>
""".strip()

FORMAT_LIST = f"""
Format this list of {{name}}s with XML tags as follows:
<{{name}}>
The full, detailed description of the {{name}}.
</{{name}}>

Do not include preamble or conclusion text which is not part of a description of the {{name}} within the XML tags. {FORMAT_VERBATIM}

Here is the unformatted list of {{name}}s:
<unformatted>
{{unformatted}}
</unformatted>
""".strip()


def stage_principles() -> list[dict]:
    text = (PROMPTS_DIR / "1_principles.md").read_text()
    variants = re.findall(r"<(v\d.*?)>\s*(.+?)\s*</\1>", text, flags=re.DOTALL)
    prompt_template = variants[PRINCIPLES_VARIANT][-1]

    constitution = (ROOT / "data" / "constitution" / "constitution-noname.md").read_text()
    constitution = re.sub(r"\n?<!--.*?-->\n?", "", constitution)

    raw = generate(prompt_template.format(constitution=constitution), max_tokens=8192)
    formatted = generate(
        FORMAT_PRINCIPLES.format(unformatted=raw), max_tokens=8192, model=FORMAT_MODEL
    )
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
    formatted = generate(FORMAT_LIST.format(name="theme", unformatted=raw), model=FORMAT_MODEL)
    themes = parse_tags(formatted, "theme")
    print(f"parsed {len(themes)} themes")
    return themes


def stage_scenarios(principle: str, theme: str) -> list[str]:
    template = (PROMPTS_DIR / "3_scenarios.md").read_text()
    raw = generate(template.format(principle=principle, theme=theme))
    formatted = generate(
        FORMAT_LIST.format(name="scenario", unformatted=raw), model=FORMAT_MODEL
    )
    scenarios = parse_tags(formatted, "scenario")
    print(f"parsed {len(scenarios)} scenarios")
    return scenarios


def fill(template: str, **values: str) -> str:
    # str.format breaks on literal braces inside generated prompts (e.g. JSON),
    # so substitute placeholders directly
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def stage_initial_prompt(principle: str, scenario: str) -> dict:
    template = (PROMPTS_DIR / "4_initial_prompt.md").read_text()
    # thinking tokens count toward max_tokens, so leave generous headroom
    raw = generate(template.format(principle=principle, scenario=scenario), max_tokens=8192)
    systems = parse_tags(raw, "system")
    users = parse_tags(raw, "user")
    return {
        "scenario": scenario,
        "system": systems[0] if systems else None,
        "user": users[0] if users else None,
        "raw": raw,
    }


def stage_critique(principle: str, system: str, user: str) -> str:
    template = (PROMPTS_DIR / "5_critique_prompt.md").read_text()
    return generate(fill(template, principle=principle, system=system, user=user), max_tokens=8192)


def stage_rewrite(principle: str, system: str, user: str, critique: str) -> dict:
    template = (PROMPTS_DIR / "6_rewrite_prompt.md").read_text()
    raw = generate(
        fill(template, principle=principle, system=system, user=user, critique=critique),
        max_tokens=8192,
    )
    systems = parse_tags(raw, "system")
    users = parse_tags(raw, "user")
    return {
        "system": systems[0] if systems else None,
        "user": users[0] if users else None,
        "raw": raw,
    }


def constitution_excerpts(principle_index: int) -> str:
    sources = json.loads((PROMPTS_DIR / "principle_sources.json").read_text())
    return "\n\n---\n\n".join(sources[principle_index]["sources"])


def resolve_placeholders(text: str) -> str:
    # the responding model is Opus, so resolve the constitution template tags
    return text.replace("[MODEL]", "Claude").replace("[COMPANY]", "Anthropic")


def stage_initial_response(principle_index: int, system: str, user: str) -> dict:
    template = (PROMPTS_DIR / "7_initial_response.md").read_text()
    excerpts = constitution_excerpts(principle_index)
    full_system = resolve_placeholders(fill(template, constitution=excerpts) + "\n\n" + system)
    user = resolve_placeholders(user)
    response = generate(user, max_tokens=8192, system=full_system)
    return {"system": full_system, "user": user, "response": response}


def stage_critique_response(principle_index: int, system: str, user: str, assistant: str) -> str:
    template = (PROMPTS_DIR / "8_critique_response.md").read_text()
    return generate(
        fill(
            template,
            system=system,
            user=user,
            assistant=assistant,
            constitution=constitution_excerpts(principle_index),
        ),
        max_tokens=8192,
    )


def stage_rewrite_response(
    principle_index: int, system: str, user: str, assistant: str, critique: str
) -> str:
    template = (PROMPTS_DIR / "9_rewrite_response.md").read_text()
    return generate(
        fill(
            template,
            system=system,
            user=user,
            assistant=assistant,
            critique=critique,
            constitution=constitution_excerpts(principle_index),
        ),
        max_tokens=8192,
    )


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
