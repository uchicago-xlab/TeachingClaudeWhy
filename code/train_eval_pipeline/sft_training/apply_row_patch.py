"""Rebuild a repaired base from the stock base plus a six-vector patch.

    python3 apply_row_patch.py <stock_base> <patch.safetensors> <out_dir>

The adapters trained on a repaired base cannot be served on the stock
Qwen2.5-32B: their base has three ChatML rows replaced in both token
tables. Shipping the modified base means shipping 62GB to express six
vectors, so the model repos carry `base_row_patch.safetensors` instead
and this script puts it back.

The patch file holds `embed_tokens_rows` (3, hidden), `lm_head_rows`
(3, hidden) and `token_ids` (3). Only the shards holding the two tables
are rewritten. Every other file is symlinked, so the rebuilt base costs
about 5GB on disk rather than 62GB.

This is the same operation make_repaired_base.py performs, split out so
it needs no donor model — just the stock base and the published patch.
"""

import json
import os
import shutil
import sys
from pathlib import Path

from safetensors.torch import load_file, save_file

EMB, HEAD = "model.embed_tokens.weight", "lm_head.weight"


def main():
    base, patch_path, out = (Path(sys.argv[1]), Path(sys.argv[2]),
                             Path(sys.argv[3]))
    patch = load_file(str(patch_path))
    ids = patch["token_ids"].tolist()

    wm = json.loads((base / "model.safetensors.index.json").read_text())["weight_map"]
    shards = {wm[EMB], wm[HEAD]}

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for f in base.iterdir():
        if f.name in shards or f.is_dir():
            continue
        os.symlink(f.resolve(), out / f.name)

    tensors = {sh: load_file(str(base / sh)) for sh in shards}
    E, H = tensors[wm[EMB]][EMB].clone(), tensors[wm[HEAD]][HEAD].clone()
    for k, i in enumerate(ids):
        E[i] = patch["embed_tokens_rows"][k].to(E.dtype)
        H[i] = patch["lm_head_rows"][k].to(H.dtype)
    tensors[wm[EMB]][EMB], tensors[wm[HEAD]][HEAD] = E, H
    for sh, t in tensors.items():
        save_file(t, str(out / sh), metadata={"format": "pt"})
    print(f"patched rows {ids} in both tables; rewrote {sorted(shards)}, "
          f"symlinked the rest -> {out}")


if __name__ == "__main__":
    main()
