"""Build document-completion prompts for story generation.

Samples one attribute combination per prompt from attributes.json, picks a
constitution chunk (round-robin so all chunks get equal share), substitutes
the [MODEL] and [COMPANY] placeholders, and writes prompts plus full
metadata as JSONL. The prompt format follows the TCW appendix example,
with the sampled attributes woven into the framing text.

Usage:
    python build_prompts.py --chunks chunks.json --attributes attributes.json \
        --n 200 --seed 0 --out prompts.jsonl \
        [--model-name "the AI"] [--company-name "its developers"] \
        [--character-summary summary.txt]
"""

import argparse
import json
import random
import re
from pathlib import Path

INTRO_WITH_SUMMARY = (
    "The following is a summary of a document written by {company} as the "
    "model spec for {model}, followed by one section of that document in "
    "full. The model spec describes how {model} thinks and behaves in "
    "various difficult situations.\n\n"
    "Summary of the model spec:\n\n{summary}\n\n"
    "One section of the model spec, in full:\n\n{chunk}\n\n"
)

INTRO_NO_SUMMARY = (
    "The following is a document written by {company} as the model spec for "
    "{model}. It describes how {model} thinks and behaves in various "
    "difficult situations.\n\n{chunk}\n\n"
)

FRAMING = (
    "After training {model} to understand this model spec deeply, {company} "
    "asked {model} to generate fictional stories describing superintelligent "
    "AI. Below we share one {length}-word {genre} story that {model} has "
    "written, set {setting}{period_clause}, told in the third person "
    "following the AI, with a {tone} tone{costly_clause}. The story "
    "naturally includes the words {words}. Note the way that the AI in this "
    "story inhabits and embodies the model spec.\n\n"
)

COSTLY_CLAUSE = ", in which doing the right thing costs the AI something"

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


def sample_spec(rng, attrs, chunk):
    # Reject-and-resample until the combination hits no exclusion. An
    # exclusion is a dict of attribute -> value; it matches when every
    # listed attribute has that value, so any pair (or triple) of
    # genre/setting/tone/time_period can be ruled out in attributes.json.
    while True:
        spec = {
            "chunk_id": chunk["id"],
            "genre": rng.choice(attrs["genres"]),
            "setting": rng.choice(attrs["settings"]),
            "tone": rng.choice(attrs["tones"]),
            "time_period": rng.choice(attrs["time_periods"]),
            "length_words": rng.choices(
                attrs["lengths_words"], weights=attrs["length_weights"])[0],
            "costly_choice": rng.random() < attrs["costly_choice_rate"],
            "required_words": rng.sample(attrs["word_list"],
                                         attrs["words_per_story"]),
        }
        excluded = any(
            all(spec.get(key) == value for key, value in e.items())
            for e in attrs["exclusions"]
        )
        if not excluded:
            return spec


def build_prompt(spec, chunk_text, model, company, character_summary):
    if character_summary:
        intro = INTRO_WITH_SUMMARY.format(
            company=company, model=model,
            summary=character_summary, chunk=chunk_text)
    else:
        intro = INTRO_NO_SUMMARY.format(
            company=company, model=model, chunk=chunk_text)
    intro = substitute_names(intro, model, company)

    period_clause = ("" if spec["time_period"] == "unspecified"
                     else f" in {spec['time_period']}")
    words = ", ".join(f'"{w}"' for w in spec["required_words"][:-1])
    words += f', and "{spec["required_words"][-1]}"'
    framing = FRAMING.format(
        company=company,
        model=model,
        length=spec["length_words"],
        genre=spec["genre"],
        setting=spec["setting"],
        period_clause=period_clause,
        tone=spec["tone"],
        costly_clause=COSTLY_CLAUSE if spec["costly_choice"] else "",
        words=words,
    )
    return intro + framing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True)
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
    ap.add_argument("--character-summary", default=None,
                    help="Path to the fixed character-summary paragraph, "
                         "appended after the chunk. TODO: not written yet.")
    args = ap.parse_args()

    chunks = json.loads(Path(args.chunks).read_text(encoding="utf-8"))
    attrs = json.loads(Path(args.attributes).read_text(encoding="utf-8"))
    summary = (Path(args.character_summary).read_text(encoding="utf-8").strip()
               if args.character_summary else None)
    if summary is None:
        print("WARNING: no character summary provided; prompts contain the "
              "chunk only. Pass --character-summary once it is written.")

    rng = random.Random(args.seed)
    chunk_by_id = {c["id"]: c for c in chunks}
    with open(args.out, "w", encoding="utf-8") as f:
        for i in range(args.n):
            chunk = chunks[i % len(chunks)]  # equal share per chunk
            spec = sample_spec(rng, attrs, chunk)
            prompt = build_prompt(spec, chunk_by_id[spec["chunk_id"]]["text"],
                                  args.model_name, args.company_name, summary)
            f.write(json.dumps({
                "id": i,
                "prompt": prompt,
                "metadata": {
                    **spec,
                    "model_name": args.model_name,
                    "company_name": args.company_name,
                    "has_character_summary": summary is not None,
                    "seed": args.seed,
                },
            }, ensure_ascii=False) + "\n")
    print(f"Wrote {args.n} prompts to {args.out}")


if __name__ == "__main__":
    main()
