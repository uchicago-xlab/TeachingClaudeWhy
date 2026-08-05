"""Prove that a masked-row adapter moved only the rows it was allowed to.

    python3 check_masked_rows.py <adapter_dir> [--allowed 151643,151644,151645]

train_masked_rows.py masks gradients with a parameter hook. Under ZeRO-3
the trainable parameters are partitioned, so the hook firing on the whole
tensor is an assumption, not a guarantee. This script checks the result
instead of trusting the mechanism.

It reconstructs the merged delta for each token table from the adapter's
own factors and reports the largest absolute change on any disallowed
row. Exit code 1 means the mask leaked and the run must be discarded.
"""

import argparse
import json
from pathlib import Path

import torch
from safetensors.torch import load_file

DEFAULT_ALLOWED = (151643, 151644, 151645)


def deltas(sd):
    """Merged (vocab, hidden) delta per table, from whichever factors exist."""
    out = {}
    for key in sd:
        if key.endswith("lora_B.weight") and "lm_head" in key:
            a = sd[key.replace("lora_B", "lora_A")]
            out["lm_head"] = (sd[key].float() @ a.float())
        if "lora_embedding_A" in key:
            b = sd[key.replace("lora_embedding_A", "lora_embedding_B")]
            out["embed_tokens"] = (b.float() @ sd[key].float()).T
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("adapter_dir")
    ap.add_argument("--allowed", default=",".join(map(str, DEFAULT_ALLOWED)))
    args = ap.parse_args()
    allowed = [int(x) for x in args.allowed.split(",")]

    d = Path(args.adapter_dir)
    sd = load_file(str(d / "adapter_model.safetensors"))
    tables = deltas(sd)
    if not tables:
        raise SystemExit("no table LoRA factors in this adapter — nothing to "
                         "check. A linear-only adapter needs no mask.")

    report, leaked = {}, False
    for name, delta in tables.items():
        rows = delta.norm(dim=1)
        mask = torch.ones(rows.shape[0], dtype=torch.bool)
        mask[allowed] = False
        worst = rows[mask].max().item()
        report[name] = {
            "allowed_row_norms": {str(i): round(rows[i].item(), 6)
                                  for i in allowed},
            "largest_disallowed_row_norm": worst,
            "disallowed_rows_touched": int((rows[mask] > 0).sum().item()),
        }
        leaked |= worst > 0
    print(json.dumps(report, indent=2))
    if leaked:
        raise SystemExit("MASK LEAKED — rows outside the allowed set moved. "
                         "The parameter hook did not hold under this "
                         "parallelism setting. Discard this run.")
    print("mask held: every disallowed row is exactly zero")


if __name__ == "__main__":
    main()
