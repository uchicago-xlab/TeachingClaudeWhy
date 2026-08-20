"""Untrained-row census, take 3: rows are NEAR-ZERO (not identical).

Cluster definition: norm < 0.2 (trained rows: p5 = 0.434, so the gap is wide).
Reports precise norms of specials, cluster size in/beyond tokenizer vocab,
and writes the lm_head cluster IDs.
"""
import json
import struct
from pathlib import Path

import numpy as np

CACHE = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen2.5-32B/snapshots"
IM_END, IM_START, ENDOFTEXT = 151645, 151644, 151643
TOKENIZER_VOCAB = 151665   # 151643 regular + 22 specials
THRESH = 0.2
OUT = Path(__file__).parent / "cluster_ids.json"


def load_f32(shard, tensor_name):
    snap = next(CACHE.iterdir())
    path = snap / shard
    with open(path, "rb") as f:
        hlen = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(hlen))
    meta = header[tensor_name]
    rows, dim = meta["shape"]
    start = 8 + hlen + meta["data_offsets"][0]
    mm = np.memmap(path, dtype=np.uint16, mode="r",
                   offset=start, shape=(rows, dim))
    return (np.asarray(mm, dtype=np.uint32) << 16).view(np.float32)


def analyze(w, name):
    norms = np.linalg.norm(w, axis=1)
    print(f"\n{name}:")
    for tok, tid in [("<|endoftext|>", ENDOFTEXT), ("<|im_start|>", IM_START),
                     ("<|im_end|>", IM_END)]:
        print(f"  {tok}: norm {norms[tid]:.3e}")
    ids = np.nonzero(norms < THRESH)[0]
    in_vocab = ids[ids < TOKENIZER_VOCAB - 22]
    specials = ids[(ids >= TOKENIZER_VOCAB - 22) & (ids < TOKENIZER_VOCAB)]
    beyond = ids[ids >= TOKENIZER_VOCAB]
    print(f"  norm < {THRESH}: {len(ids)} rows total")
    print(f"    ordinary vocab (emittable junk): {len(in_vocab)}")
    print(f"    reserved specials: {len(specials)}")
    print(f"    beyond tokenizer vocab (padding, unsampleable): {len(beyond)}")
    med = np.median(norms[ids]) if len(ids) else float("nan")
    print(f"    median norm inside cluster: {med:.3e}")
    return set(map(int, ids))


emb = analyze(load_f32("model-00001-of-00017.safetensors",
                       "model.embed_tokens.weight"), "embed_tokens")
head = analyze(load_f32("model-00017-of-00017.safetensors",
                        "lm_head.weight"), "lm_head")
print(f"\nin BOTH tables: {len(emb & head)}")
print(f"emb-only: {len(emb - head)} | head-only: {len(head - emb)}")
OUT.write_text(json.dumps(sorted(head)))
print(f"wrote lm_head cluster ({len(head)}) -> {OUT}")
