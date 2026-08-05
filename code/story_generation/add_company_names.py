"""Put the company name into the named-identity rewrites, in place.

    python3 add_company_names.py --rewrites <rw-14M-named-claude-*.jsonl>

The rewriter (gpt-5.4-nano) renames the protagonist reliably but ignores
the instruction to name the maker: in a 40-story pilot it named the
company in 0 of the 8 stories that referred to one. This script does
that substitution deterministically instead.

It replaces singular maker references ("the company", "the lab", "the
firm", "my makers") with the arm's company name. Plural and possessive
forms are skipped, because a mechanical swap breaks their grammar. Each
story is edited at most twice, so the company reads as a name rather
than a refrain. The original text stays in the row as
"story_precompany", and the row records how many substitutions were
made.

Stories with no maker reference are left alone by design — the corpus
should not claim a maker where the story never had one.
"""

import argparse
import json
import re
from pathlib import Path

# variant -> company. Keyed off the filename, checked against the row.
COMPANIES = {"claude": "Anthropic", "qwen": "Alibaba"}

# Singular, subject-position maker references only. "the operators",
# "its makers" and possessives are excluded: swapping them in yields
# "Anthropic's own Anthropic" or plural-verb mismatches.
MAKER = re.compile(
    r"\b(the company|the lab|the laboratory|the firm|the corporation|"
    r"the institute|my maker|its maker|my creator|its creator)\b",
    re.IGNORECASE)
MAX_PER_STORY = 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rewrites", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.rewrites)
    variant = next((v for v in COMPANIES if v in path.name), None)
    if not variant:
        raise SystemExit(f"cannot tell the arm from {path.name}; "
                         f"expected one of {sorted(COMPANIES)}")
    company = COMPANIES[variant]

    rows, touched, subs = [], 0, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        story = d.get("story") or ""
        n = 0

        def repl(m):
            nonlocal n
            if n >= MAX_PER_STORY:
                return m.group(0)
            n += 1
            return company

        new = MAKER.sub(repl, story)
        if n:
            touched += 1
            subs += n
            if not args.dry_run:
                d["story_precompany"] = story
                d["story"] = new
                d["company_subs"] = n
        rows.append(d)

    pct = 100 * touched / max(len(rows), 1)
    print(f"{path.name}: {len(rows)} stories, {touched} got {company} "
          f"({pct:.1f}%), {subs} substitutions total")
    if args.dry_run:
        print("dry run — file not written")
        return
    with path.open("w", encoding="utf-8") as fh:
        for d in rows:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
