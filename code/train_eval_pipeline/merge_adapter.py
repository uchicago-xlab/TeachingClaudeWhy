"""Fold a LoRA adapter into its base weights and save a full model.

Why this exists: Together's `from_hf_model` pointed at a LoRA *adapter* repo
continues training that adapter's own matrices. For A1 — an elicitation
checkpoint whose entire job is agentic reliability — that is destructive: the
difficult-advice v1 arms fell from 60% acting to 5-12%. Training a fresh
adapter instead needs a merged full model to sit on, and serving those fresh
adapters needs the same merged weights as vLLM's base.

CPU-only and deliberately so: it is meant to run on a pod whose GPU is busy
serving someone else's eval.

    python merge_adapter.py --base Qwen/Qwen2.5-32B \
        --adapter SecondLookResearch/Qwen2.5-32B-elicit-sft-A1 \
        --out /workspace/a1-merged --eos-token-id 151645
"""
import argparse
import gc
import json
import shutil
from pathlib import Path

import torch
import transformers
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# transformers 5 renamed `torch_dtype` to `dtype` and made low_cpu_mem_usage the
# default. The pod runs 5.x, the repo venv has no transformers at all, and this
# script should not care which it meets.
_DTYPE_KWARG = "dtype" if int(transformers.__version__.split(".")[0]) >= 5 else "torch_dtype"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="base model repo id or path")
    ap.add_argument("--adapter", required=True, help="LoRA repo id or path")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--free-cache-after-merge", type=Path, default=None,
                    help="delete this directory once the merge is in RAM, "
                         "before saving. A RunPod network volume is quota'd "
                         "(~100GB observed) and cannot hold both a 32B cache "
                         "and a 32B output, which fails as 'Disk quota "
                         "exceeded (os error 122)' partway through the save. "
                         "Weights are cloned into anonymous memory first, "
                         "because unlinking a file that is still mmap'd frees "
                         "no space until the mapping goes away")
    ap.add_argument("--max-shard-size", default="4GB",
                    help="shard size for the saved model. transformers 5 "
                         "defaults to 50GB, i.e. one file for a 32B — which "
                         "fails on a RunPod network volume with 'I/O error "
                         "(os error 5)' ~50GB in, after the whole merge is "
                         "done. Small shards also match what vLLM expects")
    ap.add_argument("--eos-token-id", type=int, default=None,
                    help="override generation_config.eos_token_id. Qwen2.5 "
                         "BASE lists only <|endoftext|> (151643) while the "
                         "chat template ends turns with <|im_end|> (151645), "
                         "so a chat-tuned checkpoint on that base needs 151645 "
                         "or generation runs past the turn boundary")
    args = ap.parse_args()

    print(f"loading base {args.base} on CPU in bf16 ...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, device_map="cpu", **{_DTYPE_KWARG: torch.bfloat16}
    )

    print(f"applying adapter {args.adapter} ...", flush=True)
    # No dtype kwarg here: the base is already bf16 and PeftModel inherits it.
    model = PeftModel.from_pretrained(model, args.adapter)
    model = model.merge_and_unload()

    if args.eos_token_id is not None:
        model.generation_config.eos_token_id = args.eos_token_id
        model.config.eos_token_id = args.eos_token_id
        print(f"eos_token_id -> {args.eos_token_id}")

    # Load the tokenizer BEFORE any cache is freed. It comes from the ADAPTER
    # repo, not the base: a base model has no chat template, and serving a chat
    # checkpoint without one produces prompts the model was never trained on.
    tok = AutoTokenizer.from_pretrained(args.adapter)

    if args.free_cache_after_merge:
        # Detach every tensor from the memory-mapped checkpoint files. Without
        # this the rmtree below reclaims nothing: the blocks stay allocated
        # until the last mapping is dropped, and the save fails on quota
        # exactly as before. Doubles peak RAM briefly, which is free on a box
        # with 2TB.
        print("cloning weights out of the mmap ...", flush=True)
        for tensor in list(model.parameters()) + list(model.buffers()):
            tensor.data = tensor.data.clone()
        gc.collect()
        print(f"freeing {args.free_cache_after_merge} ...", flush=True)
        shutil.rmtree(args.free_cache_after_merge, ignore_errors=True)

    print(f"saving to {args.out} (shards <= {args.max_shard_size}) ...", flush=True)
    model.save_pretrained(args.out, safe_serialization=True,
                          max_shard_size=args.max_shard_size)

    tok.save_pretrained(args.out)

    cfg = json.loads((args.out / "config.json").read_text())
    print(f"done: {cfg.get('architectures')} "
          f"{sum(1 for _ in args.out.glob('*.safetensors'))} shards")


if __name__ == "__main__":
    main()
