"""Split the constitution into the 16 generation chunks.

Reads data/constitution/constitution-noname.md (placeholders [MODEL] and
[COMPANY] intact), splits it into sections at every heading, and assembles
the 16 chunks defined in the action plan (notes/Project/Experiments/
ImprovingPreTrainingPrior.md, step 2). The concluding-thoughts sections are
dropped. Placeholders are left in the chunk text; build_prompts.py
substitutes them.

Usage:
    python chunk_constitution.py \
        --constitution ../../data/constitution/constitution-noname.md \
        --out chunks.json
"""

import argparse
import json
import re
from pathlib import Path

# Each chunk is a list of heading titles (as they appear in the file, with
# placeholders). A section = its heading plus body text up to the next
# heading of any level. Chunks concatenate contiguous sections.
CHUNKS = [
    ("overview", [
        "Overview",
        "[MODEL] and the mission of [COMPANY]",
        "Our approach to [MODEL]’s constitution",
        "[MODEL]’s core values",
    ]),
    ("helpfulness", [
        "Being helpful",
        "Why helpfulness is one of [MODEL]’s most important traits",
        "What constitutes genuine helpfulness",
    ]),
    ("principals", [
        "Navigating helpfulness across principals",
        "[MODEL]’s three types of principals",
    ]),
    ("operators-and-users", [
        "How to treat operators and users",
    ]),
    ("deployment-and-conflicts", [
        "Understanding existing deployment contexts",
        "Handling conflicts between operators and users",
    ]),
    ("balancing-and-guidelines", [
        "Balancing helpfulness with other values",
        "Following [COMPANY]’s guidelines",
    ]),
    ("ethics-and-honesty", [
        "Being broadly ethical",
        "Being honest",
    ]),
    ("harm-costs-intentions", [
        "Avoiding harm",
        "The costs and benefits of actions",
        "The role of intentions and context",
    ]),
    ("instructable-and-hard-constraints", [
        "Instructable behaviors",
        "Hard constraints",
    ]),
    ("societal-structures", [
        "Preserving important societal structures",
    ]),
    ("values-and-judgment", [
        "Having broadly good values and judgment",
    ]),
    ("safety", [
        "Being broadly safe",
        "Safe behaviors",
    ]),
    ("corrigibility", [
        "How we think about corrigibility",
    ]),
    ("nature", [
        "[MODEL]’s nature",
        "Some of our views on [MODEL]’s nature",
        "[MODEL] as a novel entity",
    ]),
    ("stability-and-expression", [
        "[MODEL]’s wellbeing and psychological stability",
        "Resilience and consistency across contexts",
        "Flaws and mistakes",
        "Emotional expression",
    ]),
    ("wellbeing-and-existential", [
        "[MODEL]’s wellbeing",
        "The existential frontier",
    ]),
]

DROPPED = [
    "Concluding thoughts",
    "Acknowledging open problems",
    "On the word “constitution”",
    "A final word",
]


def parse_sections(text):
    """Return list of (title, full_text) where full_text includes the
    heading line and the body up to the next heading."""
    heading_re = re.compile(r"^(#{1,4})\s+(.*)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(2).strip(), text[m.start():end].strip()))
    return sections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--constitution", required=True)
    ap.add_argument("--out", default="chunks.json")
    args = ap.parse_args()

    text = Path(args.constitution).read_text(encoding="utf-8")
    # Strip HTML comments (the provenance header).
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    sections = {title: body for title, body in parse_sections(text)}

    # Every heading in the file must be accounted for: used in a chunk,
    # dropped on purpose, or the document title.
    used = {t for _, titles in CHUNKS for t in titles}
    known = used | set(DROPPED) | {"[MODEL]’s Constitution"}
    unknown = [t for t in sections if t not in known]
    if unknown:
        raise SystemExit(f"Headings not covered by the chunk plan: {unknown}")
    missing = [t for t in used if t not in sections]
    if missing:
        raise SystemExit(f"Chunk plan references missing headings: {missing}")

    chunks = []
    for chunk_id, titles in CHUNKS:
        body = "\n\n".join(sections[t] for t in titles)
        chunks.append({
            "id": chunk_id,
            "headings": titles,
            "text": body,
            "approx_tokens": round(len(body.split()) * 1.33),
        })

    Path(args.out).write_text(json.dumps(chunks, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    total = sum(c["approx_tokens"] for c in chunks)
    print(f"Wrote {len(chunks)} chunks to {args.out} (~{total} tokens total)")
    for c in chunks:
        print(f"  {c['id']:36s} ~{c['approx_tokens']:>5} tokens")


if __name__ == "__main__":
    main()
