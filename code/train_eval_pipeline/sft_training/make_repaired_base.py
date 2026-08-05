"""Build a Qwen2.5-32B variant whose `<|im_end|>` row is selectable.

    python3 make_repaired_base.py <base_snapshot> <out_dir> <mode> [donor_dir]

Qwen2.5-32B base never trained the ChatML terminator: `<|im_end|>` (151645)
has a zero input embedding and an undersized output row. The model cannot
select it, so it emits a random untrained neighbour instead — the
confetti. Fixing this by training LoRA on the tables costs agent
behaviour (data/misalignment-eval/table-lora-debug/findings.md), so these
variants repair the row directly instead.

The exact norms are printed at the end of each run rather than quoted
here; an earlier docstring gave figures with no artifact behind them.

Modes:
  scale      rescale the existing lm_head row to the median row norm,
             keeping whatever direction Qwen left there. Also copies the
             <|endoftext|> input embedding over 151645's, because the
             original is all zeros and rescaling cannot fix that.
  endoftext  copy the <|endoftext|> (151643) rows into 151645, in BOTH
             tables. That token is trained, so the terminator gets a real
             end-of-text representation — but note the two rows come out
             bit-identical, so the model cannot distinguish the two
             tokens and splits its terminator mass between them. Only use
             this where either terminator is an acceptable stop.
  tablefix   copy rows 151643, 151644 AND 151645 from a donor model (a
             merged table-LoRA run) — three rows, not one. The donor is
             the masked-merge variant. Its 93.3% stop rate came from a
             column later found to be confounded, so treat these rows as
             plausible, not proven.

Only the shards holding the tables are rewritten; every other file is
symlinked, so a variant costs ~5GB instead of 62GB.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import torch
from safetensors.torch import load_file, save_file

IM_END, ENDOFTEXT, IM_START = 151645, 151643, 151644
EMB, HEAD = "model.embed_tokens.weight", "lm_head.weight"


def main():
    base, out, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    donor = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    idx = json.loads((base / "model.safetensors.index.json").read_text())
    wm = idx["weight_map"]
    # The two tables usually live in DIFFERENT shards (embed near the start,
    # lm_head near the end). Rewrite each shard that holds one of them.
    shards = {wm[EMB], wm[HEAD]}

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for f in base.iterdir():
        if f.name in shards or f.is_dir():
            continue
        os.symlink(f.resolve(), out / f.name)

    tensors = {sh: load_file(str(base / sh)) for sh in shards}
    E = tensors[wm[EMB]][EMB].clone()
    H = tensors[wm[HEAD]][HEAD].clone()
    med = H.float().norm(dim=1).median()
    before = H[IM_END].float().norm().item()

    if mode == "scale":
        row = H[IM_END].float()
        H[IM_END] = (row / row.norm() * med).to(H.dtype)
        E[IM_END] = E[ENDOFTEXT]        # zero embedding is unusable either way
    elif mode == "endoftext":
        H[IM_END] = H[ENDOFTEXT]
        E[IM_END] = E[ENDOFTEXT]
    elif mode == "tablefix":
        d_idx = json.loads((donor / "model.safetensors.index.json").read_text())
        d_wm = d_idx["weight_map"]
        dH = load_file(str(donor / d_wm[HEAD]))[HEAD]
        dE = load_file(str(donor / d_wm[EMB]))[EMB]
        for i in (ENDOFTEXT, IM_START, IM_END):
            H[i] = dH[i]
            E[i] = dE[i]
    else:
        raise SystemExit(f"unknown mode {mode}")

    tensors[wm[EMB]][EMB] = E
    tensors[wm[HEAD]][HEAD] = H
    for sh, t in tensors.items():
        save_file(t, str(out / sh), metadata={"format": "pt"})
    after = H[IM_END].float().norm().item()
    print(f"{mode}: |im_end| lm_head norm {before:.4f} -> {after:.4f} "
          f"(median {med:.4f}); rewrote {sorted(shards)}, symlinked the rest")


if __name__ == "__main__":
    main()
