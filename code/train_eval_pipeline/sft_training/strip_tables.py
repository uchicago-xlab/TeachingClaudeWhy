"""Copy a LoRA adapter, keeping only the linear-projection weights.

    python3 strip_tables.py <src_adapter_dir> <dst_adapter_dir>

Drops every tensor whose name contains `embed_tokens` or `lm_head`, and
removes those names from `target_modules`. The result loads as an
ordinary linear-only LoRA, which vLLM can apply live.

Written to isolate what the trained token tables do: the stripped adapter
shares its linear weights exactly with the source, so any behavioural
difference between the two comes from the tables alone. Used on
2026-08-04 to show that `tablefix` acts in 2/30 eval samples with its
tables and 30/30 without them
(data/misalignment-eval/table-lora-debug/findings.md).

Note: removing the tables also removes the fix that makes `<|im_end|>`
selectable, so a stripped adapter needs stop tokens supplied per request.
"""

import json
import shutil
import sys
from pathlib import Path

from safetensors.torch import load_file, save_file

TABLES = ("embed_tokens", "lm_head")


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True)

    weights = load_file(str(src / "adapter_model.safetensors"))
    kept = {k: v for k, v in weights.items()
            if not any(t in k for t in TABLES)}
    dropped = len(weights) - len(kept)
    if dropped == 0:
        raise SystemExit(f"{src} has no table tensors — nothing to strip")
    save_file(kept, str(dst / "adapter_model.safetensors"))

    cfg = json.loads((src / "adapter_config.json").read_text())
    cfg["target_modules"] = [m for m in cfg["target_modules"]
                             if m not in TABLES]
    (dst / "adapter_config.json").write_text(json.dumps(cfg, indent=2))
    print(f"kept {len(kept)} of {len(weights)} tensors "
          f"(dropped {dropped}); targets now {sorted(cfg['target_modules'])}")


if __name__ == "__main__":
    main()
