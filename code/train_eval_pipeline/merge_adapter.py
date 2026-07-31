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
import json
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

    print(f"saving to {args.out} (shards <= {args.max_shard_size}) ...", flush=True)
    model.save_pretrained(args.out, safe_serialization=True,
                          max_shard_size=args.max_shard_size)

    # The tokenizer comes from the ADAPTER repo, not the base: a base model has
    # no chat template, and serving a chat checkpoint without one produces
    # prompts the model was never trained on.
    tok = AutoTokenizer.from_pretrained(args.adapter)
    tok.save_pretrained(args.out)

    cfg = json.loads((args.out / "config.json").read_text())
    print(f"done: {cfg.get('architectures')} "
          f"{sum(1 for _ in args.out.glob('*.safetensors'))} shards")


if __name__ == "__main__":
    main()
