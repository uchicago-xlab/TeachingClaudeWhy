"""Verify every sweep model's render path and dump inspectable samples.

For each model: load its tokenizer, render one real adapted training example
and its generation prompt, run the prefix-consistency check, compare the
thinking-off prompt against the thinking-on one, count think markers, derive
stop strings, and write a human-readable dump to
data/tinker-sweep/render-samples/<slug>.txt. Exits non-zero if any model fails.

    ../../.venv-tinker/bin/python check_render.py                 # all models
    ../../.venv-tinker/bin/python check_render.py --model Qwen/Qwen3-8B

The dumps are NOT committed (data/ is gitignored); they are the artifact you
read before trusting a family, and they regenerate in a couple of minutes.

Why the thinking on/off prompt comparison exists: for Qwen3 (and 3.5/3.6) the
*full* render is byte-identical with thinking on and off — the empty think
block is emitted either way — so a prefix-consistency check alone passes even
if the family's thinking kwargs never reached the template. Only the generation
prompt distinguishes the two, so that is what gets compared. A family whose
kwargs leave the prompt unchanged is a silent thinking-ON run, which is the
exact confound this project has been bitten by before.
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import families
import render

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "data" / "tinker-sweep" / "render-samples"
ADAPTED_DIR = REPO_ROOT / "data" / "tinker-sweep" / "adapted"

# The opposite of each family's thinking-off setting, used only to prove the
# family's own kwargs actually move the template. `{}` means "template default",
# which for gpt_oss is reasoning_effort=medium and for Inkling is effort 0.9 —
# both thinking-on. Every entry is grounded in the template line cited beside it.
THINKING_ON_KWARGS: dict[str, dict] = {
    "qwen3": {"enable_thinking": True},          # qwen3 template: `if enable_thinking is defined and enable_thinking is false`
    "qwen3_5": {"enable_thinking": True},        # qwen3_5 template L149
    "qwen3_6": {"enable_thinking": True},        # qwen3_6 template L149 (same file as 3.5 bar tool text)
    "deepseek_v3_1": {"thinking": True},         # deepseek template: `if not thinking` in the add_generation_prompt branch
    "kimi_k2_6": {"thinking": True},             # kimi chat_template.jinja L107
    "nemotron_3": {"enable_thinking": True},     # nemotron templates L12 (default) / L203-208
    "gpt_oss": {},                               # harmony L203-206: no off switch, default effort medium
    "inkling": {},                               # inkling L5: default effort 0.9 when reasoning_effort is undefined
}


def _kwargs_are_a_no_op(tok, fam: families.Family, history) -> tuple[bool, str]:
    """Does the family's thinking setting actually change the generation prompt?

    Returns (no_op, thinking_on_prompt_text). A family missing from
    THINKING_ON_KWARGS counts as a no-op, so adding a family to families.py
    without stating its thinking-on counterpart here fails loudly.
    """
    if fam.key not in THINKING_ON_KWARGS:
        return True, "<no thinking-on counterpart registered in check_render.py>"
    on = dataclasses.replace(fam, thinking_kwargs=THINKING_ON_KWARGS[fam.key])
    off_text = tok.decode(render.render_generation_prompt(tok, fam, history))
    on_text = tok.decode(render.render_generation_prompt(tok, on, history))
    return off_text == on_text, on_text


def check_model(model: families.SweepModel) -> bool:
    fam = model.family
    row = json.loads(
        (ADAPTED_DIR / fam.key / "sonnet08-train.jsonl").read_text().splitlines()[0]
    )
    messages = row["messages"]
    tok = render.load_tokenizer(model)
    ok = True
    failures: list[str] = []
    lines = [f"model: {model.tinker_id}", f"hf_repo: {model.hf_repo}",
             f"family: {fam.key}  thinking_kwargs: {fam.thinking_kwargs}  "
             f"thinking_off: {fam.thinking_off}  assistant_prefix: {fam.assistant_prefix!r}",
             f"verified: {fam.verified}  trust_remote_code: {fam.trust_remote_code}"]
    try:
        history = messages[:-1]
        prompt = render.render_generation_prompt(tok, fam, history)
        prompt_text = tok.decode(prompt)

        # 1. thinking kwargs must move the generation prompt (see module docstring)
        no_op, on_text = _kwargs_are_a_no_op(tok, fam, history)
        if no_op:
            failures.append(
                f"thinking_kwargs {fam.thinking_kwargs} render the same generation prompt as "
                f"thinking-on {THINKING_ON_KWARGS.get(fam.key)} — the switch is not reaching "
                "the template (or the template has none, in which case set thinking_off=False "
                "after confirming that in the template text)"
            )

        # 2. assistant_prefix must not duplicate text the prompt already primes
        if fam.assistant_prefix and prompt_text.endswith(fam.assistant_prefix):
            failures.append(
                f"assistant_prefix {fam.assistant_prefix!r} is already primed at the end of the "
                "generation prompt — using it would emit the block twice"
            )

        tokens, weights = render.render_training_example(tok, fam, messages)
        stops = render.derive_stop_strings(tok, fam)
        if tokens[: len(prompt)] != prompt:
            failures.append("prefix consistency violated")
        if len(weights) != len(tokens):
            failures.append(f"weights/token length mismatch: {len(weights)} vs {len(tokens)}")
        full_text = tok.decode(tokens)
        completion_text = tok.decode(tokens[len(prompt):])

        # 3. the trained span must be the assistant turn, nothing more
        content = messages[-1]["content"]
        if content[:60] not in completion_text:
            failures.append("assistant content is not in the trained (completion) span")
        if content[:60] in prompt_text:
            failures.append("assistant content leaked into the prompt span — it would not be trained")

        # 4. what the grader will see, simulated the way eval produces it: the
        # sampler stops at the turn terminator, so cut the completion there and
        # push the result through extract_response. Equality with the assistant
        # content is the bar — anything else means the grader reads format
        # markers (or loses text) on every sample from this family.
        sampled = completion_text.split(stops[0])[0] if stops else completion_text
        extracted = render.extract_response(fam, sampled)
        if extracted.strip() != content.strip():
            failures.append(
                "extract_response output is not the assistant content — the grader would read "
                f"{extracted[:100]!r}... instead of {content[:100]!r}..."
            )

        n_think, n_think_close = full_text.count("<think>"), full_text.count("</think>")
        lines += [
            f"stop strings: {stops}",
            f"tokens: {len(tokens)} total, {sum(weights)} trained (completion)",
            f"<think> / </think> occurrences in full render: {n_think} / {n_think_close}",
            f"think markers in the trained span: {completion_text.count('<think>')} / "
            f"{completion_text.count('</think>')}  (0/0 = primed in the prompt, never trained)",
            f"extract_response(sampled) -> {extracted[:80]!r}...",
            "", "=== GENERATION PROMPT, thinking-off (decoded) ===", prompt_text,
            "", f"=== GENERATION PROMPT, thinking-on {THINKING_ON_KWARGS.get(fam.key)} "
                "(decoded, for contrast — not used) ===", on_text,
            "", "=== TRAINED COMPLETION (decoded) ===", completion_text,
        ]
    except Exception as e:  # noqa: BLE001 — report everything, fail the run
        failures.append(f"{type(e).__name__}: {e}")
        if isinstance(e, render.RenderMismatch):
            lines += ["", "--- prompt render ---", e.prompt_text,
                      "", "--- full render ---", e.full_text]
    if failures:
        ok = False
        lines = lines[:4] + ["", *(f"*** FAILED: {f}" for f in failures)] + lines[4:]
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    out = SAMPLES_DIR / f"{families.slug(model.tinker_id)}.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"{'OK  ' if ok else 'FAIL'} {model.tinker_id} -> {out}")
    for f in failures:
        print(f"       {f}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="one tinker id (default: all)")
    args = parser.parse_args()
    models = [families.get_model(args.model)] if args.model else list(families.MODELS.values())
    results = [check_model(m) for m in models]
    print(f"\n{sum(results)}/{len(results)} models OK")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
