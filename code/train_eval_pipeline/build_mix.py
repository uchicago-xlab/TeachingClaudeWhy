"""Build the instruct-SFT elicitation mix from mix.json.

Streams each HF source (no multi-GB downloads for subsets we sample a few
hundred rows from), takes the arm's sample count through a seeded shuffle
buffer, and writes one combined {"messages": ...} JSONL, shuffled across
sources. Chain check_dataset.py on the output for schema + MSM's
identity-confusion filter before uploading.

The two arms (10k / 25k samples) keep identical source proportions so the
comparison isolates scale. Mix contents and reasoning:
notes/Project/Experiments/InstructSFT/DataMix.md

Usage:
    pip install datasets
    python build_mix.py --arm 10k --out mix-10k.jsonl
    python build_mix.py --arm 25k --out mix-25k.jsonl
    python build_mix.py --arm 10k --dry-run   # print the plan, load nothing
"""

import argparse
import json
import random
from pathlib import Path

SPEC = Path(__file__).parent / "mix.json"
SHUFFLE_BUFFER = 10_000
# MSM filtered instruction-tuning samples to <= 8192 tokens (Appendix B.3);
# we do the same (diversity > length): over-cap samples are skipped during
# sampling and replaced, keeping every kept conversation complete.
MAX_SAMPLE_TOKENS = 8192


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("10k", "25k", "A1", "A2", "P", "S", "T2"), required=True)
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = {"10k": "n10", "25k": "n25", "A1": "nA1", "A2": "nA2",
           "P": "nP", "S": "nS", "T2": "nT2"}[args.arm]
    sources = json.loads(SPEC.read_text())["sources"]
    total = sum(s[key] for s in sources)
    for s in sources:
        label = s["dataset"] + (f":{s['config']}" if s.get("config") else "")
        print(f"{s['name']:20s} {s[key]:>6,}  {label}")
    print(f"{'total':20s} {total:>6,}")
    if args.dry_run:
        return
    if not args.out:
        raise SystemExit("--out is required unless --dry-run")

    from datasets import load_dataset

    rows, chars = [], 0
    for s in sources:
        ds = load_dataset(s["dataset"], s.get("config"), split=s["split"],
                          streaming=True)
        ds = ds.shuffle(seed=args.seed, buffer_size=SHUFFLE_BUFFER)
        n = skipped = 0
        for row in ds:
            msgs = [{"role": m["role"], "content": m["content"]}
                    for m in row["messages"]]
            c = sum(len(m["content"]) for m in msgs)
            if c // 4 > MAX_SAMPLE_TOKENS:
                skipped += 1
                continue
            rows.append({"messages": msgs, "source": s["name"]})
            chars += c
            n += 1
            if n >= s[key]:
                break
        if n < s[key]:
            raise SystemExit(f"{s['name']}: only {n}/{s[key]} rows available")
        print(f"{s['name']}: sampled {n:,}"
              + (f" (skipped {skipped:,} over {MAX_SAMPLE_TOKENS} tok)"
                 if skipped else ""))

    random.Random(args.seed).shuffle(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"\n{len(rows):,} samples -> {args.out} (~{chars / 4 / 1e6:.2f}M tokens)")
    print(f"next: python check_dataset.py --in {args.out} --out "
          f"{args.out.replace('.jsonl', '-clean.jsonl')}")


if __name__ == "__main__":
    main()
