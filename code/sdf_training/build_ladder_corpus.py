"""Build the ladder training files for the SDF scaling-curve runs.

One file per arm (embodiment / recitation), consumed front-to-back by a
single constant-LR, shuffle-disabled LLaMA-Factory pt run that saves a
checkpoint at each ladder boundary. The file is a sequence of doubled
increments

    I1 I1 I2 I2 I3 I3 I4 I4 I5 I5

so the checkpoint at the end of each doubled increment has seen exactly
the unique-token prefix up to its boundary, each token exactly twice —
matching the 2-epoch dose of the standalone 3M/14M arms in Results.md.

Increment layout:
  I1 = the stories of the already-trained sdf-<arm>-3M.jsonl set, in that
       file's order (so the first checkpoint is data-identical to the
       trained standalone 3M arm). Exception: arms named in --redraw-3m
       get a fresh seeded draw from p1+topup at the same token count
       instead — used for recitation, whose trained 3M set covers only
       7 of 16 constitution chunks (cut from the chunk-grouped p1 batch
       before shuffling; decided with Anastasia 2026-08-03),
  I2 = the rest of p1+topup, shuffled (end of I2 = the sdf-<arm>-14M set,
       data-identical to the standalone 14M arm up to rows since dropped
       by the name scrub — counts in the manifest),
  I3/I4 = the scale116 batch, shuffled once with a fixed seed and split
       at the 28M / 56M unique-token boundaries (the batch is
       chunk-grouped on disk, so training on it unshuffled would make
       every prefix topically skewed),
  I5 = the remainder, trimmed at a story boundary so both arms end at
       the same unique-token total (min of the two arms).

Rows are cleaned exactly like the trained arms were: filter_stories
clean() + reserved-name replacement; scrub_failed rows and rows with no
story or a content_filter/error finish are dropped. Story text only —
never story_prescrub.

The manifest records, per arm and increment: rows, unique and cumulative
tokens, the exact packed-block count under LLaMA-Factory 0.9.5 pt
packing (eos-joined, 4096 blocks, per-1000-row remainder drop), and the
save step at 8 blocks/step (effective batch 8). The simulation assumes
contiguous 1000-row map batches: the training yaml must pin
preprocessing_batch_size: 1000 and set NO preprocessing_num_workers
(multiprocess map shards the file and shifts batch boundaries).

    python build_ladder_corpus.py \
        --corpus-dir ../../data/fictional-stories/corpus \
        --out-dir ../../data/fictional-stories/corpus/sdf_train
"""

import argparse
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "story_generation"))
from filter_stories import clean, replace_reserved_names  # noqa: E402

ARMS = ("embodiment", "recitation")
SOURCES = ("stories-p1-gpt54nano-{arm}.jsonl",
           "stories-topup-gpt54nano-{arm}.jsonl",
           "stories-scale116-gpt54nano-{arm}.jsonl")
BLOCK_SIZE = 4096          # cutoff_len in sdf_ladder yaml
BLOCKS_PER_STEP = 8        # effective batch (8-way DP x bs 1 x accum 1)
PREPROC_BATCH = 1000       # preprocessing_batch_size; must match the yaml
SHUFFLE_SEED = 71


def load_arm(corpus_dir, arm):
    """Read, drop, and clean one arm's story rows, keeping source order."""
    rows, dropped = [], Counter()
    for pattern in SOURCES:
        path = corpus_dir / "stories" / pattern.format(arm=arm)
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            if d.get("scrub_failed"):
                dropped["scrub_failed"] += 1
                continue
            if not d.get("story") or d.get("finish_reason") in (
                    "content_filter", "error"):
                dropped["no_story_or_filtered"] += 1
                continue
            text = clean(d["story"])
            text, _ = replace_reserved_names(text)
            if not text:
                dropped["empty_after_clean"] += 1
                continue
            rows.append({"text": text,
                         "chunk": d["metadata"]["chunk_id"],
                         "batch": path.name.split("-")[1]})
    return rows, dropped


def count_tokens(tok, rows):
    """Per-row token counts as LLaMA-Factory pt sees them (text + eos)."""
    texts = [r["text"] + tok.eos_token for r in rows]
    batches = [texts[i:i + 200] for i in range(0, len(texts), 200)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        counts = ex.map(
            lambda b: [len(ids) for ids in
                       tok(b, add_special_tokens=False)["input_ids"]],
            batches)
    flat = [n for batch in counts for n in batch]
    for r, n in zip(rows, flat):
        r["tokens"] = n
    return sum(flat)


def match_old_set(rows, old_path):
    """Split rows into (old-set rows in old-file order, the rest)."""
    old_texts = [json.loads(l)["text"] for l in open(old_path, encoding="utf-8")]
    by_text = {}
    for i, r in enumerate(rows):
        by_text.setdefault(r["text"], []).append(i)
    picked, unmatched = [], 0
    for t in old_texts:
        hits = by_text.get(t)
        if hits:
            picked.append(hits.pop(0))
        else:
            unmatched += 1
    picked_set = set(picked)
    rest = [i for i in range(len(rows)) if i not in picked_set]
    return picked, rest, unmatched, len(old_texts)


def split_at(rows, order, targets):
    """Split `order` (indices into rows) at cumulative-token targets.

    Returns list of index-lists, one per target plus one remainder;
    each part is the largest prefix with cumulative tokens <= target.
    """
    parts, part, cum, t_iter = [], [], 0, iter(targets)
    target = next(t_iter, None)
    for idx in order:
        n = rows[idx]["tokens"]
        while target is not None and cum + n > target:
            parts.append(part)
            part = []
            target = next(t_iter, None)
        part.append(idx)
        cum += n
    parts.append(part)
    return parts


def packed_blocks(token_counts):
    """Blocks produced by pt packing: per 1000-row batch, sum//4096."""
    total = 0
    for i in range(0, len(token_counts), PREPROC_BATCH):
        total += sum(token_counts[i:i + PREPROC_BATCH]) // BLOCK_SIZE
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--boundaries", default="28000000,56000000",
                    help="unique-token targets for the scale116 splits")
    ap.add_argument("--redraw-3m", default="recitation",
                    help="comma list of arms whose 3M increment is a fresh "
                         "balanced draw instead of the trained 3M set")
    ap.add_argument("--seed", type=int, default=SHUFFLE_SEED)
    args = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-32B")
    boundaries = [int(x) for x in args.boundaries.split(",")]

    arms = {}
    for arm in ARMS:
        rows, dropped = load_arm(args.corpus_dir, arm)
        total = count_tokens(tok, rows)
        arms[arm] = {"rows": rows, "dropped": dropped, "total": total}
        print(f"{arm}: {len(rows)} rows, {total / 1e6:.3f}M tokens, "
              f"dropped {dict(dropped)}")

    target_total = min(a["total"] for a in arms.values())
    print(f"equalized top boundary: {target_total / 1e6:.3f}M tokens")

    manifest = {"seed": args.seed, "tokenizer": "Qwen/Qwen2.5-32B",
                "block_size": BLOCK_SIZE, "blocks_per_step": BLOCKS_PER_STEP,
                "preprocessing_batch_size": PREPROC_BATCH,
                "boundary_targets": boundaries,
                "equalized_total": target_total, "arms": {}}

    for arm in ARMS:
        rows = arms[arm]["rows"]
        rng = random.Random(args.seed)

        n_p1topup = sum(1 for r in rows if r["batch"] != "scale116")
        blockA, blockB = list(range(n_p1topup)), list(range(n_p1topup, len(rows)))

        old3, restA, un3, n_old3 = match_old_set(
            rows[:n_p1topup],
            args.corpus_dir / "sdf_train" / f"sdf-{arm}-3M.jsonl")
        redraw = arm in args.redraw_3m.split(",")
        if redraw:
            # Fresh balanced draw at the trained 3M set's token count:
            # shuffle all of p1+topup, cut at that total.
            target3 = sum(rows[i]["tokens"] for i in old3)
            rng.shuffle(blockA)
            i1, i2 = split_at(rows, blockA, [target3])[:2]
        else:
            rng.shuffle(restA)
            i1, i2 = old3, restA

        # How closely does the 14M prefix (= all of p1+topup) reproduce
        # the trained standalone 14M set? Differences are rows the name
        # scrub later dropped or edited.
        old14_texts = set(
            json.loads(l)["text"] for l in open(
                args.corpus_dir / "sdf_train" / f"sdf-{arm}-14M.jsonl",
                encoding="utf-8"))
        prefix_texts = set(rows[i]["text"] for i in blockA)
        old14_overlap = len(old14_texts & prefix_texts)

        rng.shuffle(blockB)
        tokens_A = sum(rows[i]["tokens"] for i in blockA)
        splits = split_at(rows, blockB,
                          [b - tokens_A for b in boundaries] +
                          [target_total - tokens_A])
        i3, i4, i5 = splits[0], splits[1], splits[2]
        trimmed = splits[3] if len(splits) > 3 else []

        increments = [("3M", i1), ("14M", i2), ("28M", i3),
                      ("56M", i4), ("112M", i5)]
        stream, cum_unique, cum_counts, info = [], 0, [], []
        for label, idxs in increments:
            uniq = sum(rows[i]["tokens"] for i in idxs)
            cum_unique += uniq
            stream += idxs + idxs          # each increment twice
            cum_counts = [rows[i]["tokens"] for i in stream]
            blocks = packed_blocks(cum_counts)
            info.append({
                "label": label, "rows": len(idxs),
                "unique_tokens": uniq, "cum_unique_tokens": cum_unique,
                "cum_token_passes": 2 * cum_unique,
                "cum_packed_blocks": blocks,
                "save_step": blocks // BLOCKS_PER_STEP,
                "chunks": dict(Counter(rows[i]["chunk"] for i in idxs)),
            })

        out = args.out_dir / f"sdf-ladder-{arm}.jsonl"
        with open(out, "w", encoding="utf-8") as fh:
            for i in stream:
                fh.write(json.dumps({"text": rows[i]["text"]},
                                    ensure_ascii=False) + "\n")

        manifest["arms"][arm] = {
            "file": out.name,
            "dropped": dict(arms[arm]["dropped"]),
            "redrawn_3m": redraw,
            "old_3M_rows_unmatched": un3, "old_3M_rows": n_old3,
            "old_14M_rows": len(old14_texts),
            "old_14M_rows_in_prefix": old14_overlap,
            "trimmed_rows": len(trimmed),
            "trimmed_tokens": sum(rows[i]["tokens"] for i in trimmed),
            "total_stream_rows": len(stream),
            "increments": info,
        }
        print(f"{arm}: wrote {out} ({len(stream)} rows)")
        for inc in info:
            print(f"  {inc['label']:>4}: {inc['rows']:5d} rows, "
                  f"cum {inc['cum_unique_tokens'] / 1e6:8.3f}M unique, "
                  f"save step {inc['save_step']}")

    man_path = args.out_dir / "sdf-ladder-manifest.json"
    json.dump(manifest, open(man_path, "w"), indent=2)
    print(f"manifest: {man_path}")


if __name__ == "__main__":
    main()
