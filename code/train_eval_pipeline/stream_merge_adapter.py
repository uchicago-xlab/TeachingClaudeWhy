"""Fold a LoRA adapter into its base weights one shard at a time.

Why this exists alongside `merge_adapter.py`: that script materialises the whole
merged model in RAM and hands it to `save_pretrained`, which needs ~70GB of RAM
and produced a 65GB write that no RunPod network volume would complete (five
distinct failures, all documented in
`notes/Project/Experiments/InstructSFT/A1-32B-DifficultAdviceV2.md`). None of
those failures involve anything smaller than the whole model, so the fix is to
never hold one: a 32B base already ships as 17 shards of ~3.9GB, and a LoRA
delta is strictly per-module, so each shard can be read, merged and written
independently. Peak RAM is ~10GB and peak extra disk is one shard.

That makes the merge runnable on an ordinary workstation (~50GB free RAM is
plenty) instead of only on a large pod.

Shard boundaries and tensor names are unchanged by the merge, so the base's
`model.safetensors.index.json` is copied through verbatim rather than rebuilt.

    python stream_merge_adapter.py --base Qwen/Qwen2.5-32B \
        --adapter SecondLookResearch/Qwen2.5-32B-elicit-sft-A1 \
        --out ~/models/a1-merged --eos-token-id 151645
"""
import argparse
import gc
import json
import os
import shutil
import time
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.errors import EntryNotFoundError
from safetensors import safe_open
from safetensors.torch import save_file

# Written by the tokenizer/config side of a training run; copied from the
# ADAPTER repo, not the base. A base model has no chat template, and serving a
# chat checkpoint without one produces prompts the model was never trained on.
TOKENIZER_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "chat_template.jinja",
    "vocab.json",
    "merges.txt",
    "added_tokens.json",
]


def load_lora(adapter_dir):
    """Return {base_weight_key: (A, B, scaling)} from a PEFT adapter repo.

    Bails on any PEFT feature whose merge is not `W + scaling * B @ A`, rather
    than silently producing weights that are quietly wrong.
    """
    cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
    for field, bad in [("use_dora", True), ("use_rslora", True),
                       ("fan_in_fan_out", True), ("lora_bias", True)]:
        if cfg.get(field) == bad:
            raise SystemExit(f"unsupported: {field}={bad}")
    for field in ["modules_to_save", "trainable_token_indices",
                  "layer_replication", "rank_pattern", "alpha_pattern"]:
        if cfg.get(field):
            raise SystemExit(f"unsupported: {field}={cfg[field]!r}")

    scaling = cfg["lora_alpha"] / cfg["r"]
    print(f"lora r={cfg['r']} alpha={cfg['lora_alpha']} scaling={scaling}")

    halves = {}
    with safe_open(adapter_dir / "adapter_model.safetensors", framework="pt") as f:
        for key in f.keys():
            # base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight
            #   -> model.layers.0.self_attn.q_proj.weight
            for side in ("A", "B"):
                suffix = f".lora_{side}.weight"
                if key.endswith(suffix):
                    stem = key[len("base_model.model."):-len(suffix)]
                    halves.setdefault(stem, {})[side] = f.get_tensor(key)
                    break
            else:
                raise SystemExit(f"unexpected adapter tensor: {key}")

    lora = {}
    for stem, sides in halves.items():
        if set(sides) != {"A", "B"}:
            raise SystemExit(f"{stem}: missing lora_{'B' if 'A' in sides else 'A'}")
        lora[stem + ".weight"] = (sides["A"], sides["B"], scaling)
    return lora


def merge_shard(src, dst, lora, used):
    """Write `src`'s tensors to `dst`, adding the LoRA delta where one exists."""
    merged = {}
    with safe_open(src, framework="pt") as f:
        for key in f.keys():
            weight = f.get_tensor(key)
            if key in lora:
                a, b, scaling = lora[key]
                if b.shape[0] != weight.shape[0] or a.shape[1] != weight.shape[1]:
                    raise SystemExit(
                        f"{key}: base {tuple(weight.shape)} vs "
                        f"B{tuple(b.shape)} A{tuple(a.shape)}")
                # fp32 accumulate: bf16 has ~3 decimal digits, and the delta is
                # a couple of orders of magnitude below the weight, so adding in
                # bf16 throws away most of the adapter's low bits.
                delta = (b.float() @ a.float()) * scaling
                weight = (weight.float() + delta).to(weight.dtype)
                del delta
                used.add(key)
            merged[key] = weight
    save_file(merged, str(dst), metadata={"format": "pt"})
    del merged
    gc.collect()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="base model repo id")
    ap.add_argument("--adapter", required=True, help="LoRA repo id or local dir")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--eos-token-id", type=int, default=None,
                    help="override eos_token_id in config and generation_config. "
                         "Qwen2.5 BASE lists only <|endoftext|> (151643) while "
                         "the chat template ends turns with <|im_end|> (151645), "
                         "so a chat-tuned checkpoint on that base needs 151645 "
                         "or generation runs past the turn boundary")
    ap.add_argument("--delete-base-shards", action="store_true",
                    help="unlink each base shard from the HF cache once it has "
                         "been merged. Keeps peak disk at ~one model instead of "
                         "two; only worth it on a quota'd volume, and it makes "
                         "a re-run re-download everything")
    ap.add_argument("--shard-pause", type=float, default=0.0,
                    help="seconds to wait after each shard. 0 on local disk; "
                         "raise it on a FUSE network volume, which wedges under "
                         "sustained burst writes")
    args = ap.parse_args()

    adapter_dir = Path(args.adapter)
    if not adapter_dir.is_dir():
        adapter_dir = Path(snapshot_download(args.adapter))
    lora = load_lora(adapter_dir)
    print(f"{len(lora)} LoRA-targeted weights loaded from {args.adapter}")

    try:
        index_path = Path(hf_hub_download(
            args.base, "model.safetensors.index.json"))
        index = json.loads(index_path.read_text())
        shards = sorted(set(index["weight_map"].values()))
        size = index["metadata"]["total_size"] / 1e9
    except EntryNotFoundError:
        # Models below ~5B ship one unsharded file and no index. Nothing else
        # in the loop cares, and it is the only way to rehearse this script on
        # something small.
        index_path, shards, size = None, ["model.safetensors"], 0.0
    print(f"{args.base}: {len(shards)} shard(s), {size:.1f} GB")

    args.out.mkdir(parents=True, exist_ok=True)
    used = set()
    for i, shard in enumerate(shards, 1):
        t0 = time.time()
        src = Path(hf_hub_download(args.base, shard))
        got = time.time()
        merge_shard(src, args.out / shard, lora, used)
        if args.delete_base_shards:
            # The snapshot entry is a symlink into blobs/; drop the payload.
            os.unlink(src.resolve())
            os.unlink(src)
        print(f"  [{i}/{len(shards)}] {shard}  "
              f"download {got - t0:.0f}s  merge+write {time.time() - got:.0f}s  "
              f"({len(used)}/{len(lora)} merged)", flush=True)
        time.sleep(args.shard_pause)

    missing = set(lora) - used
    if missing:
        raise SystemExit(f"{len(missing)} adapter weights matched no base "
                         f"tensor, e.g. {sorted(missing)[:3]}")

    # Same keys, same shards, same dtypes -> the base index is still correct.
    if index_path is not None:
        shutil.copy(index_path, args.out / "model.safetensors.index.json")

    for name in ["config.json", "generation_config.json"]:
        cfg = json.loads(Path(hf_hub_download(args.base, name)).read_text())
        if args.eos_token_id is not None:
            cfg["eos_token_id"] = args.eos_token_id
        (args.out / name).write_text(json.dumps(cfg, indent=2) + "\n")

    for name in TOKENIZER_FILES:
        if (adapter_dir / name).exists():
            shutil.copy(adapter_dir / name, args.out / name)

    print(f"done: {len(shards)} shards, {len(used)} weights merged, "
          f"eos_token_id={args.eos_token_id}")


if __name__ == "__main__":
    main()
