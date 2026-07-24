"""Convert kept story batches into Together AI's generic-text SFT format.

Reads one or more kept-*.jsonl story files (filter_stories.py output),
extracts the story text, and writes a single training JSONL where each
line is {"text": ...} — the format Together trains on with loss over
every token, which is what SDF wants. Optionally holds out a validation
fraction so the fine-tune job can report eval loss.

Prints per-file and total counts plus a rough token estimate (chars/4;
Gemma's 262k vocab will tokenize somewhat tighter) and the implied
Together SFT cost at the sub-16B tier ($0.48/M LoRA, $1.20/M full,
$4 minimum — pricing as of 2026-07-24).

Usage:
    python prepare_together_data.py \
        --in ../../data/fictional-stories/corpus/stories/kept-*.jsonl \
        --out sdf-train.jsonl --val-out sdf-val.jsonl --val-frac 0.02
"""

import argparse
import json
import random

LORA_PER_M = 0.48
FULL_PER_M = 1.20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--val-out")
    ap.add_argument("--val-frac", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rows = []
    for path in args.inputs:
        n_in, n_kept, chars = 0, 0, 0
        with open(path) as fh:
            for line in fh:
                d = json.loads(line)
                n_in += 1
                story = (d.get("story") or "").strip()
                if not story:
                    continue
                n_kept += 1
                chars += len(story)
                rows.append(story)
        print(f"{path}: {n_kept}/{n_in} stories, ~{chars / 4 / 1e6:.2f}M tokens")

    random.Random(args.seed).shuffle(rows)
    n_val = int(len(rows) * args.val_frac) if args.val_out else 0
    val, train = rows[:n_val], rows[n_val:]

    with open(args.out, "w") as fh:
        for story in train:
            fh.write(json.dumps({"text": story}) + "\n")
    if args.val_out and val:
        with open(args.val_out, "w") as fh:
            for story in val:
                fh.write(json.dumps({"text": story}) + "\n")

    tokens_m = sum(len(s) for s in train) / 4 / 1e6
    print(f"\ntrain: {len(train)} stories -> {args.out} (~{tokens_m:.2f}M tokens)")
    if n_val:
        print(f"val:   {len(val)} stories -> {args.val_out}")
    print(f"est. cost/epoch: LoRA ${max(tokens_m * LORA_PER_M, 4.0):.2f}, "
          f"full ${max(tokens_m * FULL_PER_M, 4.0):.2f}")

    try:
        from together.utils import check_file
        report = check_file(args.out)
        print(f"together check_file: {'PASS' if report['is_check_passed'] else report}")
    except ImportError:
        print("together SDK not installed; skipped format check "
              "(pip install together)")


if __name__ == "__main__":
    main()
