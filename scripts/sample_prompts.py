"""Sample the difficult-advice pipeline across ALL principles:

for each principle -> 3 themes (spread across the theme list)
                   -> 1 scenario per theme (spread across the scenario list)
                   -> 1 initial (system, user) prompt per scenario

Reuses principles (and principle 4's themes) cached in tmp/initial_prompts.json
so the expensive principles stage isn't re-run. Writes tmp/sampled_prompts.md
(human-readable) and tmp/sampled_prompts.json (full artifacts).
"""

import json
from concurrent.futures import ThreadPoolExecutor

from run_pipeline import OUT_DIR, stage_initial_prompt, stage_scenarios, stage_themes

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
        samples.append(prompt)
        print(f"principle {index}: sample {slot + 1}/{N_PER_PRINCIPLE} done")
    return samples


def main():
    cached = json.loads((OUT_DIR / "initial_prompts.json").read_text())
    principles = [p["description"] for p in cached["principles"]]
    themes_by_principle = {cached["principle_index"]: cached["themes"]}

    missing = [i for i in range(len(principles)) if i not in themes_by_principle]
    print(f"generating themes for {len(missing)} principles")
    with ThreadPoolExecutor(max_workers=5) as pool:
        for i, themes in zip(missing, pool.map(lambda i: stage_themes(principles[i]), missing)):
            themes_by_principle[i] = themes

    with ThreadPoolExecutor(max_workers=8) as pool:
        per_principle = list(
            pool.map(
                lambda i: sample_principle(i, principles[i], themes_by_principle[i]),
                range(len(principles)),
            )
        )
    samples = [s for group in per_principle for s in group]
    n_parsed = sum(1 for s in samples if s["system"] and s["user"])
    print(f"generated {len(samples)} sampled prompts ({n_parsed} parsed cleanly)")

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "sampled_prompts.json").write_text(
        json.dumps(
            {
                "principles": cached["principles"],
                "themes_by_principle": {str(k): v for k, v in themes_by_principle.items()},
                "prompts": samples,
            },
            indent=2,
        )
    )

    lines = ["# Sampled prompts: 3 per principle, distinct themes & scenarios\n"]
    for i, principle in enumerate(principles):
        group = [s for s in samples if s["principle_index"] == i]
        lines.append(f"\n---\n\n# Principle {i}\n\n{principle}\n")
        for j, p in enumerate(group, 1):
            lines.append(f"\n## Prompt {i}.{j}\n")
            lines.append(f"### Theme\n\n{p['theme']}\n")
            lines.append(f"### Scenario\n\n{p['scenario']}\n")
            if p["system"] and p["user"]:
                lines.append(f"### System\n\n{p['system']}\n")
                lines.append(f"### User\n\n{p['user']}\n")
            else:
                lines.append(f"### PARSE FAILURE — raw output\n\n{p['raw']}\n")
    (OUT_DIR / "sampled_prompts.md").write_text("\n".join(lines))
    print(f"wrote {OUT_DIR / 'sampled_prompts.md'} and sampled_prompts.json")


if __name__ == "__main__":
    main()
