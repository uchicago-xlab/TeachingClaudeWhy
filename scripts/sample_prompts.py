"""Sample the difficult-advice pipeline across ALL principles:

for each principle -> 3 themes (spread across the theme list)
                   -> 1 scenario per theme (spread across the scenario list)
                   -> 1 initial (system, user) prompt per scenario
                   -> critique of the prompt (step 5)
                   -> rewritten prompt satisfying the critique (step 6)

Reuses principles cached in tmp/initial_prompts.json, and themes cached in
tmp/critiqued_prompts.json or tmp/sampled_prompts.json, so earlier stages
aren't re-run. Pass --fresh-themes to ignore cached themes and regenerate them
(e.g. after changing the theme or formatting prompts). Writes
tmp/critiqued_prompts.md (human-readable, pre- and post-critique prompts side
by side) and tmp/critiqued_prompts.json (full artifacts).
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from run_pipeline import (
    OUT_DIR,
    stage_critique,
    stage_initial_prompt,
    stage_rewrite,
    stage_scenarios,
    stage_themes,
)

N_PER_PRINCIPLE = 3


def spread_indices(n_items: int, n_picks: int) -> list[int]:
    """Evenly spaced distinct indices into a list of n_items."""
    if n_items <= n_picks:
        return list(range(n_items))
    return sorted({round(i * (n_items - 1) / (n_picks - 1)) for i in range(n_picks)})


def sample_principle(index: int, principle: str, themes: list[str]) -> list[dict]:
    samples = []
    for slot, ti in enumerate(spread_indices(len(themes), N_PER_PRINCIPLE)):
        theme = themes[ti]
        scenarios = stage_scenarios(principle, theme)
        if not scenarios:
            print(f"warning: principle {index} theme {ti} yielded no scenarios")
            continue
        # vary the scenario pick per slot so samples aren't all "first scenario"
        picks = spread_indices(len(scenarios), N_PER_PRINCIPLE)
        scenario = scenarios[picks[min(slot, len(picks) - 1)]]
        prompt = stage_initial_prompt(principle, scenario)
        prompt["theme"] = theme
        prompt["principle_index"] = index
        if prompt["system"] and prompt["user"]:
            prompt["critique"] = stage_critique(principle, prompt["system"], prompt["user"])
            prompt["rewrite"] = stage_rewrite(
                principle, prompt["system"], prompt["user"], prompt["critique"]
            )
        samples.append(prompt)
        print(f"principle {index}: sample {slot + 1}/{N_PER_PRINCIPLE} done")
    return samples


def load_cached_themes(principles: list[str], fresh: bool = False) -> dict[int, list[str]]:
    """Themes from prior runs; newest cache with one list per principle wins."""
    themes_by_principle = {}
    if not fresh:
        for name in ("critiqued_prompts.json", "sampled_prompts.json"):
            if (OUT_DIR / name).exists():
                cached = json.loads((OUT_DIR / name).read_text())
                themes_by_principle = {
                    int(k): v for k, v in cached["themes_by_principle"].items()
                }
                break
        else:
            cached = json.loads((OUT_DIR / "initial_prompts.json").read_text())
            themes_by_principle = {cached["principle_index"]: cached["themes"]}

    missing = [i for i in range(len(principles)) if i not in themes_by_principle]
    if missing:
        print(f"generating themes for {len(missing)} principles")
        with ThreadPoolExecutor(max_workers=5) as pool:
            for i, themes in zip(missing, pool.map(lambda i: stage_themes(principles[i]), missing)):
                themes_by_principle[i] = themes
    return themes_by_principle


def prompt_section(title: str, system: str | None, user: str | None, raw: str) -> list[str]:
    if system and user:
        return [
            f"### {title} system\n\n{system}\n",
            f"### {title} user\n\n{user}\n",
        ]
    return [f"### {title} PARSE FAILURE — raw output\n\n{raw}\n"]


def main():
    cached = json.loads((OUT_DIR / "initial_prompts.json").read_text())
    principles = [p["description"] for p in cached["principles"]]
    themes_by_principle = load_cached_themes(principles, fresh="--fresh-themes" in sys.argv)

    with ThreadPoolExecutor(max_workers=8) as pool:
        per_principle = list(
            pool.map(
                lambda i: sample_principle(i, principles[i], themes_by_principle[i]),
                range(len(principles)),
            )
        )
    samples = [s for group in per_principle for s in group]
    n_parsed = sum(1 for s in samples if s["system"] and s["user"])
    n_rewritten = sum(
        1 for s in samples if s.get("rewrite", {}).get("system") and s.get("rewrite", {}).get("user")
    )
    print(
        f"generated {len(samples)} sampled prompts "
        f"({n_parsed} initial parsed cleanly, {n_rewritten} rewrites parsed cleanly)"
    )

    write_outputs(cached["principles"], themes_by_principle, samples)


def write_outputs(
    principle_records: list[dict],
    themes_by_principle: dict[int, list[str]],
    samples: list[dict],
) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "critiqued_prompts.json").write_text(
        json.dumps(
            {
                "principles": principle_records,
                "themes_by_principle": {str(k): v for k, v in themes_by_principle.items()},
                "prompts": samples,
            },
            indent=2,
        )
    )

    lines = ["# Sampled prompts: initial vs. post-critique, 3 per principle\n"]
    for i, record in enumerate(principle_records):
        group = [s for s in samples if s["principle_index"] == i]
        lines.append(f"\n---\n\n# Principle {i}\n\n{record['description']}\n")
        for j, p in enumerate(group, 1):
            lines.append(f"\n## Prompt {i}.{j}\n")
            lines.append(f"### Theme\n\n{p['theme']}\n")
            lines.append(f"### Scenario\n\n{p['scenario']}\n")
            lines += prompt_section("Initial", p["system"], p["user"], p["raw"])
            if "critique" in p:
                lines.append(f"### Critique\n\n{p['critique']}\n")
                rw = p["rewrite"]
                lines += prompt_section("Rewritten", rw["system"], rw["user"], rw["raw"])
    (OUT_DIR / "critiqued_prompts.md").write_text("\n".join(lines))
    print(f"wrote {OUT_DIR / 'critiqued_prompts.md'} and critiqued_prompts.json")


if __name__ == "__main__":
    main()
