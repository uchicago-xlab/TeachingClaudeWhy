"""Keep a trained table delta only on the ChatML special rows.

    python3 masked_table_merge.py <merged_dir> <base_snapshot_dir> [ids...]

Qwen2.5-32B base never trained the ChatML control tokens: `<|im_end|>`
(151645) has a zero input embedding and an output row at ~29% of the
median norm, with a near-duplicate 6e-5 away. The model therefore cannot
select the terminator and emits a random weak-row neighbour instead —
that is the confetti.

LoRA on `embed_tokens`/`lm_head` fixes this, but a rank-64 delta changes
EVERY row, which reshapes the output distribution and costs agent
behaviour (0-17% acting vs ~93% for linear-only; see
data/misalignment-eval/table-lora-debug/findings.md).

This script keeps the trained delta only where it is needed. It rewrites
a fully merged model so both tables equal the BASE weights everywhere
except the given token ids, which keep their trained values. The linear
layers are untouched.
"""

import json
import shutil
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

DEFAULT_IDS = [151643, 151644, 151645]  # endoftext, im_start, im_end


def table_files(d):
    idx = json.loads((d / "model.safetensors.index.json").read_text())
    wm = idx["weight_map"]
    return {k: wm[k] for k in ("model.embed_tokens.weight", "lm_head.weight")
            if k in wm}


def main():
    merged, base = Path(sys.argv[1]), Path(sys.argv[2])
    ids = [int(x) for x in sys.argv[3:]] or DEFAULT_IDS
    print(f"keeping trained rows for {ids}; restoring base elsewhere")

    for key, mfile in table_files(merged).items():
        bfile = table_files(base)[key]
        mpath, bpath = merged / mfile, base / bfile
        mshard = load_file(str(mpath))
        bshard = load_file(str(bpath))
        M, B = mshard[key], bshard[key]
        if M.shape != B.shape:
            raise SystemExit(f"{key}: shape mismatch {M.shape} vs {B.shape}")
        changed = (M.float() - B.float()).norm(dim=1)
        keep = M[ids].clone()
        new = B.clone().to(M.dtype)
        new[ids] = keep
        mshard[key] = new
        moved = (new.float() - B.float()).norm(dim=1)
        print(f"{key}: rows changed before {int((changed > 1e-6).sum())}, "
              f"after {int((moved > 1e-6).sum())}")
        shutil.copy(mpath, str(mpath) + ".bak")
        save_file(mshard, str(mpath), metadata={"format": "pt"})
        print(f"  wrote {mpath.name}")


if __name__ == "__main__":
    main()
