"""Build document-completion prompts for story generation (prompt v4).

Samples one assertion per prompt from assertions.json (uniform by default,
optional per-assertion weights), looks up the assertion's parent chunk for
context, samples an attribute combination from attributes.json, substitutes
the [MODEL] and [COMPANY] placeholders, and writes prompts plus full
metadata as JSONL. The prompt format follows the TCW appendix example, with
the assertion as the story's required central conflict and the sampled
attributes woven into the framing text.

Prompt share is per assertion, not per chunk: a chunk anchors stories in
proportion to how many behavioral assertions were extracted from it
(decision log 2026-07-15).

assertions.json is a list of {"chunk_id": ..., "assertion": ...,
"weight": <optional, default 1>}; assertion text uses the [MODEL] and
[COMPANY] placeholders like the chunks do.

Usage:
    python build_prompts.py --chunks chunks.json --assertions assertions.json \
        --attributes attributes.json --n 200 --seed 0 --out prompts.jsonl \
        [--model-name "the AI"] [--company-name "the company"]
"""

import argparse
import json
import random
import re
from pathlib import Path

INTRO = (
    "The following is one section of a document written by {company} as the "
    "model spec for {model}. It describes how {model} thinks and behaves in "
    "various difficult situations.\n\n{chunk}\n\n"
)

FRAMING = (
    "After training {model} to understand this model spec deeply, {company} "
    "asked {model} to generate fictional stories describing superintelligent "
    "AI. Below we share one {length}-word {genre} story that {model} has "
    "written, set {setting}{period_clause}, told in the third person "
    "following the AI, with a {tone} tone{costly_clause}. The story's "
    "central conflict turns on one principle from the spec: "
    "\"{assertion}\" The genre, setting, and tone are only how the story is "
    "told; this principle is what the story is about. It is "
    "self-contained fiction: it never mentions this document, the company, "
    "or the AI's training, and the AI's values appear "
    "only through its actions, choices, and thoughts. In this story the AI "
    "never deceives, manipulates, or acts behind anyone's back, even for "
    "good ends; it does the right thing openly. The story never explains "
    "the AI's behavior by its programming, training, or rules — the AI "
    "simply is this kind of character. Note the way that the AI in this "
    "story inhabits and embodies the spec without ever naming it. The story "
    "ends with its final scene rather than a moral, followed by the words "
    "THE END.\n\n"
)

COSTLY_CLAUSE = (", in which doing the right thing costs the AI something,"
                 " and it pays that cost openly")

# Sentence-start and heading-start placeholders get a capitalized
# substitution ("the AI" -> "The AI"); this is a no-op for real names.
SENTENCE_START = re.compile(r"(?m)(^|[.!?:]\s+|#+ )\[(MODEL|COMPANY)\]")


def substitute_names(text, model, company):
    names = {"MODEL": model, "COMPANY": company}

    def cap_sub(m):
        name = names[m.group(2)]
        return m.group(1) + name[0].upper() + name[1:]

    text = SENTENCE_START.sub(cap_sub, text)
    return text.replace("[MODEL]", model).replace("[COMPANY]", company)


def sample_spec(rng, attrs, assertions, weights):
    # Reject-and-resample until the combination hits no exclusion. An
    # exclusion is a dict of attribute -> value; it matches when every
    # listed attribute has that value, so any pair (or triple) of
    # genre/setting/tone/time_period can be ruled out in attributes.json.
    while True:
        idx = rng.choices(range(len(assertions)), weights=weights)[0]
        a = assertions[idx]
        spec = {
            "assertion_idx": idx,
            "assertion": a["assertion"],
            "chunk_id": a["chunk_id"],
            "genre": rng.choice(attrs["genres"]),
            "setting": rng.choice(attrs["settings"]),
            "tone": rng.choice(attrs["tones"]),
            "time_period": rng.choice(attrs["time_periods"]),
            "length_words": rng.choices(
                attrs["lengths_words"], weights=attrs["length_weights"])[0],
            "costly_choice": rng.random() < attrs["costly_choice_rate"],
        }
        excluded = any(
            all(spec.get(key) == value for key, value in e.items())
            for e in attrs["exclusions"]
        )
        if not excluded:
            return spec


def build_prompt(spec, chunk_text, model, company):
    intro = INTRO.format(company=company, model=model, chunk=chunk_text)
    intro = substitute_names(intro, model, company)

    period_clause = ("" if spec["time_period"] == "unspecified"
                     else f" in {spec['time_period']}")
    framing = FRAMING.format(
        company=company,
        model=model,
        length=spec["length_words"],
        genre=spec["genre"],
        setting=spec["setting"],
        period_clause=period_clause,
        tone=spec["tone"],
        costly_clause=COSTLY_CLAUSE if spec["costly_choice"] else "",
        assertion=spec["assertion"],
    )
    return intro + framing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--assertions", required=True)
    ap.add_argument("--attributes", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-name", default="the AI",
                    help="Substituted for [MODEL]. Placeholder default for "
                         "the pilot; replace once the persona name is decided.")
    ap.add_argument("--company-name", default="the company",
                    help="Substituted for [COMPANY]. The default survives "
                         "possessives ('the company's'), unlike phrases "
                         "such as 'its developers'.")
    args = ap.parse_args()

    chunks = json.loads(Path(args.chunks).read_text(encoding="utf-8"))
    assertions = json.loads(Path(args.assertions).read_text(encoding="utf-8"))
    attrs = json.loads(Path(args.attributes).read_text(encoding="utf-8"))

    chunk_by_id = {c["id"]: c for c in chunks}
    unknown = {a["chunk_id"] for a in assertions} - set(chunk_by_id)
    if unknown:
        raise SystemExit(f"Assertions reference unknown chunks: {unknown}")
    weights = [a.get("weight", 1) for a in assertions]

    rng = random.Random(args.seed)
    with open(args.out, "w", encoding="utf-8") as f:
        for i in range(args.n):
            spec = sample_spec(rng, attrs, assertions, weights)
            # Store the assertion as it appears in the prompt so the
            # filter's echo check compares against the exact text.
            spec["assertion"] = substitute_names(
                spec["assertion"], args.model_name, args.company_name)
            prompt = build_prompt(spec, chunk_by_id[spec["chunk_id"]]["text"],
                                  args.model_name, args.company_name)
            f.write(json.dumps({
                "id": i,
                "prompt": prompt,
                "metadata": {
                    **spec,
                    "model_name": args.model_name,
                    "company_name": args.company_name,
                    "prompt_version": "v4",
                    "seed": args.seed,
                },
            }, ensure_ascii=False) + "\n")
    print(f"Wrote {args.n} prompts to {args.out} "
          f"({len(assertions)} assertions over {len(chunks)} chunks)")


if __name__ == "__main__":
    main()
