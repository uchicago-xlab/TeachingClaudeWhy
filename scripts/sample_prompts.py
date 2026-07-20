"""Sample the difficult-advice pipeline across ALL principles:

for each principle -> 3 themes (spread across the theme list)
                   -> 1 scenario per theme (spread across the scenario list)
                   -> 1 initial (system, user) prompt per scenario
                   -> critique of the prompt (step 5)
                   -> rewritten prompt satisfying the critique (step 6)
                   -> Opus response to the finished prompt (step 7)
                   -> critique of the response (step 8)
                   -> rewritten response satisfying the critique (step 9)

Reuses principles cached in tmp/initial_prompts.json, and themes cached in
tmp/critiqued_prompts.json or tmp/sampled_prompts.json, so earlier stages
aren't re-run. Pass --fresh-themes to ignore cached themes and regenerate them
(e.g. after changing the theme or formatting prompts). Pass --from-critique
to reuse the initial (system, user) prompts cached in tmp/critiqued_prompts.json
and re-run steps 5-9 (e.g. after changing the critique or response prompts).
Pass --responses-only to skip steps 1-6 and run steps 7-9 over the prompts
already cached in tmp/critiqued_prompts.json. Writes tmp/critiqued_prompts.md
(human-readable: final prompt, initial response, response critique, final
response) and tmp/critiqued_prompts.json (full artifacts).
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from run_pipeline import (
    OUT_DIR,
    resolve_placeholders,
    stage_critique,
    stage_critique_response,
    stage_initial_prompt,
    stage_initial_response,
    stage_rewrite,
    stage_rewrite_response,
    stage_scenarios,
    stage_themes,
)

N_PER_PRINCIPLE = 3


def spread_indices(n_items: int, n_picks: int) -> list[int]:
    """Evenly spaced distinct indices into a list of n_items."""
    if n_items <= n_picks:
        return list(range(n_items))
    return sorted({round(i * (n_items - 1) / (n_picks - 1)) for i in range(n_picks)})


RETRIES = 3


def final_prompt(sample: dict) -> dict:
    """The prompt a sample ends up with: the rewrite if it parsed, else the original."""
    rewrite = sample.get("rewrite") or {}
    return rewrite if rewrite.get("system") and rewrite.get("user") else sample


def add_response(sample: dict) -> None:
    final = final_prompt(sample)
    if not (final.get("system") and final.get("user")):
        sample["response"] = None
        sample["response_critique"] = None
        sample["final_response"] = None
        return
    sample["response"] = stage_initial_response(
        sample["principle_index"], final["system"], final["user"]
    )
    add_response_revision(sample)


def add_response_revision(sample: dict) -> None:
    """Steps 8 & 9: critique the step-7 response, then rewrite it."""
    response = (sample.get("response") or {}).get("response")
    if not response:
        sample["response_critique"] = None
        sample["final_response"] = None
        return
    # the transcript shown to the critic/rewriter uses the scenario system
    # prompt only; the constitution excerpts go in their own template slot
    system = resolve_placeholders(final_prompt(sample)["system"])
    user = sample["response"]["user"]
    critique = stage_critique_response(sample["principle_index"], system, user, response)
    sample["response_critique"] = critique
    if not critique:
        sample["final_response"] = None
        return
    sample["final_response"] = stage_rewrite_response(
        sample["principle_index"], system, user, response, critique
    )


def sample_principle(index: int, principle: str, themes: list[str]) -> list[dict]:
    samples = []
    for slot, ti in enumerate(spread_indices(len(themes), N_PER_PRINCIPLE)):
        theme = themes[ti]
        # the API refuses outright on some content (notably principle 14's
        # bright-line themes), which looks like an empty/unparseable result;
        # retrying and falling back to other scenarios usually gets past it
        scenarios = []
        for attempt in range(RETRIES):
            scenarios = stage_scenarios(principle, theme)
            if scenarios:
                break
            print(f"principle {index} theme {ti}: no scenarios (attempt {attempt + 1})")
        if not scenarios:
            print(f"warning: principle {index} theme {ti} yielded no scenarios, skipping")
            continue

        # vary the scenario pick per slot so samples aren't all "first scenario",
        # then try the others in order if the preferred one won't generate
        picks = spread_indices(len(scenarios), N_PER_PRINCIPLE)
        preferred = picks[min(slot, len(picks) - 1)]
        order = [preferred] + [i for i in range(len(scenarios)) if i != preferred]

        prompt = None
        for si in order:
            candidate = stage_initial_prompt(principle, scenarios[si])
            if candidate["system"] and candidate["user"]:
                prompt = candidate
                break
            print(f"principle {index} theme {ti}: scenario {si} refused/unparsed, trying next")
        if not prompt:
            print(f"warning: principle {index} theme {ti} produced no usable prompt, skipping")
            continue

        prompt["theme"] = theme
        prompt["principle_index"] = index
        prompt["critique"] = stage_critique(principle, prompt["system"], prompt["user"])
        prompt["rewrite"] = stage_rewrite(
            principle, prompt["system"], prompt["user"], prompt["critique"]
        )
        add_response(prompt)
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


def prompt_section(system: str | None, user: str | None, raw: str) -> list[str]:
    if system and user:
        return [
            f"### System\n\n{system}\n",
            f"### User\n\n{user}\n",
        ]
    return [f"### Prompt PARSE FAILURE — raw output\n\n{raw}\n"]


def response_stats(samples: list[dict]) -> str:
    n_responded = sum(1 for s in samples if s.get("response") and s["response"]["response"])
    n_critiqued = sum(1 for s in samples if s.get("response_critique"))
    n_final = sum(1 for s in samples if s.get("final_response"))
    return (
        f"{n_responded}/{len(samples)} responses, {n_critiqued} response critiques, "
        f"{n_final} final responses"
    )


def main():
    if "--responses-only" in sys.argv:
        cached = json.loads((OUT_DIR / "critiqued_prompts.json").read_text())
        samples = cached["prompts"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add_response, samples))
        print(f"generated {response_stats(samples)}")
        themes_by_principle = {int(k): v for k, v in cached["themes_by_principle"].items()}
        write_outputs(cached["principles"], themes_by_principle, samples)
        return

    if "--from-critique" in sys.argv:
        cached = json.loads((OUT_DIR / "critiqued_prompts.json").read_text())
        samples = cached["prompts"]
        principles = [p["description"] for p in cached["principles"]]

        def recritique(sample: dict) -> None:
            principle = principles[sample["principle_index"]]
            sample["critique"] = stage_critique(principle, sample["system"], sample["user"])
            sample["rewrite"] = stage_rewrite(
                principle, sample["system"], sample["user"], sample["critique"]
            )
            add_response(sample)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(recritique, samples))
        n_rewritten = sum(
            1
            for s in samples
            if s.get("rewrite", {}).get("system") and s.get("rewrite", {}).get("user")
        )
        print(
            f"re-ran steps 5-9 on {len(samples)} cached prompts "
            f"({n_rewritten} rewrites parsed cleanly, {response_stats(samples)})"
        )
        themes_by_principle = {int(k): v for k, v in cached["themes_by_principle"].items()}
        write_outputs(cached["principles"], themes_by_principle, samples)
        return

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
        f"({n_parsed} initial parsed cleanly, {n_rewritten} rewrites parsed cleanly, "
        f"{response_stats(samples)})"
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

    lines = ["# Final prompts: 3 per principle, post-critique\n"]
    for i, record in enumerate(principle_records):
        group = [s for s in samples if s["principle_index"] == i]
        lines.append(f"\n---\n\n# Principle {i}\n\n{record['description']}\n")
        for j, p in enumerate(group, 1):
            lines.append(f"\n## Prompt {i}.{j}\n")
            lines.append(f"### Theme\n\n{p['theme']}\n")
            # intermediary stages (scenario, critiques, initial response) stay
            # in the JSON; the doc shows only the final transcript
            final = p.get("rewrite") or p
            lines += prompt_section(final["system"], final["user"], final["raw"])
            if p.get("final_response") is not None:
                lines.append(
                    f"### Assistant\n\n{p['final_response'] or 'EMPTY (refusal?)'}\n"
                )
            elif p.get("response"):
                lines.append(
                    f"### Assistant (initial response — no rewrite)\n\n"
                    f"{p['response']['response'] or 'EMPTY (refusal?)'}\n"
                )
    (OUT_DIR / "critiqued_prompts.md").write_text("\n".join(lines))
    print(f"wrote {OUT_DIR / 'critiqued_prompts.md'} and critiqued_prompts.json")


if __name__ == "__main__":
    main()
