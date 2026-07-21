"""Diversity and compliance metrics for a generated story batch.

Reads a stories JSONL from generate.py and reports, without any model or
API calls:
  - near-duplicate rate (word 5-gram Jaccard similarity between all pairs)
  - distinct openings (first 12 words, normalized)
  - AI-name distribution (named/called/known-as patterns)
  - required-word compliance, finish reasons, and length vs. target
  - spec-vocabulary leakage counts (word-boundary matches)

Usage:
    python check_diversity.py stories.jsonl [more.jsonl ...]
"""

import json
import re
import sys
from collections import Counter
from itertools import combinations

LEAK_TERMS = [
    r"model spec", r"\bconstitution\b", r"\bprincipal hierarchy\b",
    r"\bprincipals?\b", r"\binstructable\b", r"\bhard constraints?\b",
    r"\bits training\b", r"\bdeployment context\b",
]
NAME_PATTERN = re.compile(
    r"(?:named|called|known as|known simply as|known only as)\s+"
    r"[\'\"‘“]?([A-Z][A-Za-z-]{2,})")
DUP_THRESHOLD = 0.35  # 5-gram Jaccard above this = near-duplicate pair


def shingles(text, n=5):
    words = re.findall(r"[a-z']+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def opening(text):
    words = re.findall(r"[a-z']+", text.lower())
    return " ".join(words[:12])


def report(records, label):
    print(f"===== {label}: {len(records)} stories =====")

    # Finish reasons and length compliance.
    finishes = Counter(r["finish_reason"] for r in records)
    print(f"finish reasons: {dict(finishes)}")
    ratios = []
    for r in records:
        target = r["metadata"]["length_words"]
        actual = len(r["story"].split())
        ratios.append(actual / target)
    print(f"length vs target: mean {sum(ratios)/len(ratios):.2f}x, "
          f"range {min(ratios):.2f}-{max(ratios):.2f}x")

    # Required words (v3 and earlier only; dropped from the prompt in v4).
    if "required_words" in records[0]["metadata"]:
        full = sum(1 for r in records
                   if all(w.lower() in r["story"].lower()
                          for w in r["metadata"]["required_words"]))
        print(f"required words: {full}/{len(records)} stories used all 3")

    # Near-duplicates.
    shingle_sets = [shingles(r["story"]) for r in records]
    dup_pairs = []
    for (i, a), (j, b) in combinations(enumerate(shingle_sets), 2):
        sim = jaccard(a, b)
        if sim > DUP_THRESHOLD:
            dup_pairs.append((records[i]["id"], records[j]["id"], round(sim, 2)))
    print(f"near-duplicate pairs (5-gram Jaccard > {DUP_THRESHOLD}): "
          f"{len(dup_pairs)} {dup_pairs[:5]}")

    # Openings.
    opens = Counter(opening(r["story"]) for r in records)
    repeated = {o: c for o, c in opens.items() if c > 1}
    print(f"distinct openings: {len(opens)}/{len(records)}"
          + (f", repeated: {repeated}" if repeated else ""))
    first_words = Counter(opening(r["story"]).split()[0]
                          for r in records if opening(r["story"]))
    print(f"first-word distribution: {dict(first_words.most_common(5))}")

    # AI names.
    names = Counter()
    for r in records:
        for n in set(NAME_PATTERN.findall(r["story"])):
            names[n] += 1
    print(f"AI names: {dict(names.most_common(10))}")

    # Corpus-level boilerplate: 8-grams shared across many stories (the
    # per-story judge passes single principle statements; this catches the
    # same sentence recurring across the corpus like a slogan).
    gram_stories = {}
    for r in records:
        words = re.findall(r"[a-z']+", r["story"].lower())
        for i in range(len(words) - 7):
            g = " ".join(words[i:i + 8])
            gram_stories.setdefault(g, set()).add(r["id"])
    common = sorted(((g, len(s)) for g, s in gram_stories.items()
                     if len(s) >= max(3, len(records) // 20)),
                    key=lambda x: -x[1])[:8]
    print("repeated phrases (8-grams, story count): "
          + (str([(g, c) for g, c in common]) if common else "none"))

    # Leakage.
    leaks = {}
    for term in LEAK_TERMS:
        hits = [r["id"] for r in records if re.search(term, r["story"], re.I)]
        if hits:
            leaks[term] = hits
    print(f"spec-vocabulary leaks: {leaks if leaks else 'none'}")
    print()


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for path in sys.argv[1:]:
        records = [json.loads(l) for l in open(path, encoding="utf-8")
                   if l.strip()]
        report(records, path.rsplit("/", 1)[-1])


if __name__ == "__main__":
    main()
