"""Cut a v4.5 embodiment kept-stories file into a fixed-token SDF corpus.

Reproduces the recipe used for the 2026-08-27 generator-comparison arms
(sonnet5 / haiku45 / nano54), recovered from the sonnet5 files: the kept
stories are deduplicated by text (first occurrence wins), shuffled once
with a fixed seed, and taken in that order until the next story would push
the running total past the token target. Token counts use the Qwen2.5-32B
tokenizer with +1 eos per story, the convention every manifest in
sdf_train/ uses (sonnet5: 14,232 rows, 13,999,923 tokens — this script
regenerates that file byte for byte with --arm sonnet5).

Writes
    sdf_train/sdf-v45emb-<arm>-14M.jsonl        {"text": story} per row
    stories/v45emb-<arm>-14M-trainset.jsonl     the kept rows used, in
                                                trained order (the named
                                                rewrite arms key off this)
and adds the arm to sdf_train/v45emb-14M-manifest.json.

    .venv/bin/python code/sdf_training/build_v45emb_corpus.py --arm terra
"""

import argparse
import json
import random
import statistics as st
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from transformers import AutoTokenizer

REPO = Path(__file__).resolve().parents[2]
STORIES = REPO / "data/fictional-stories/corpus/stories"
OUT = REPO / "data/fictional-stories/corpus/sdf_train"
MANIFEST = OUT / "v45emb-14M-manifest.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, help="e.g. terra -> v45emb-terra-kept.jsonl")
    ap.add_argument("--target", type=int, default=14_000_000)
    ap.add_argument("--seed", type=int, default=116, help="shuffle seed used for the 2026-08-27 arms")
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="write all three outputs here instead of the corpus dirs "
                         "(for checking a rebuild against the trained file)")
    args = ap.parse_args()
    out_dir = args.out_dir or OUT
    trainset_dir = args.out_dir or STORIES
    manifest_path = (args.out_dir / MANIFEST.name) if args.out_dir else MANIFEST
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    kept = [json.loads(l) for l in (STORIES / f"v45emb-{args.arm}-kept.jsonl").read_text().splitlines() if l.strip()]
    seen, uniq = set(), []
    for r in kept:
        if r["story"] in seen:
            continue
        seen.add(r["story"])
        uniq.append(r)
    random.Random(args.seed).shuffle(uniq)

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-32B")
    texts = [r["story"] for r in uniq]
    batches = [texts[i:i + 256] for i in range(0, len(texts), 256)]
    with ThreadPoolExecutor(8) as ex:
        counts = [n for b in ex.map(lambda b: [len(x) + 1 for x in tok(b, add_special_tokens=False)["input_ids"]], batches) for n in b]

    total, used = 0, []
    for r, n in zip(uniq, counts):
        if total + n > args.target:
            break
        total += n
        used.append((r, n))

    (out_dir / f"sdf-v45emb-{args.arm}-14M.jsonl").write_text(
        "".join(json.dumps({"text": r["story"]}, ensure_ascii=False) + "\n" for r, _ in used))
    (trainset_dir / f"v45emb-{args.arm}-14M-trainset.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r, _ in used))

    entry = {"kept_unique": len(uniq), "used": len(used), "tokens": total,
             "leftover": len(uniq) - len(used),
             "mean_tokens": int(st.mean(n for _, n in used))}  # floor, as the 2026-08-27 manifest
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[args.arm] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(args.arm, entry)
    if total < args.target * 0.995:
        print(f"WARNING: only {total:,} of {args.target:,} tokens — corpus is short")


if __name__ == "__main__":
    main()
