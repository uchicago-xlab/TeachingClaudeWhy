"""Merge a fsdp_fa3 adapter into its base and write a servable model.

One step replaces the old lane's patch pile: PEFT merge_and_unload, then
the generation_config is REPAIRED IN THE RELEASED MODEL — eos/stop set to
<|im_end|> (151645) and <|endoftext|> (151643) — so serving no longer
depends on every caller passing per-request stop_token_ids. The old
footgun: the base generation_config can silently defeat server-side
overrides; fixing the released artifact removes the whole failure class.

    # stage-1 (SDF) merge — keeps the base-model tokenizer/config:
    python merge_release.py --adapter out/sdf-fsdp --out merged/sdf-base

    # stage-2 (A1) release merge — bakes ChatML + stop tokens:
    python merge_release.py --base merged/sdf-base --adapter out/a1-fsdp \\
        --out merged/a1-final --chat

Needs CPU RAM for the full bf16 model (~65GB for 32B); run it on the pod.
After a --chat merge, run ../check_junk.py against the served model WITHOUT
stop-token overrides — that is the gate proving this repair works.
"""

import argparse

import torch
from peft import PeftModel
from safetensors.torch import load_file
from transformers import AutoModelForCausalLM, AutoTokenizer

from chatml import ENDOFTEXT, IM_END, chat_tokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-32B")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chat", action="store_true",
                    help="A1 release: ChatML tokenizer + eos/stop in generation_config")
    ap.add_argument("--row-deltas", default=None,
                    help="row_deltas.safetensors from a --train-rows run; adds "
                         "the trained terminator-row deltas to the merged tables")
    args = ap.parse_args()

    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map="cpu"
    )
    model = PeftModel.from_pretrained(model, args.adapter)
    model = model.merge_and_unload()

    if args.row_deltas:
        # Row-delta arm: the hooks added x @ delta at train time; adding the
        # deltas onto the rows is the exact same function, baked in.
        rd = load_file(args.row_deltas)
        for module, key in ((model.get_input_embeddings(), "embed_tokens"),
                            (model.get_output_embeddings(), "lm_head")):
            W = module.weight.data
            for k, t in enumerate(rd[f"{key}.token_ids"].tolist()):
                W[t] += rd[f"{key}.row_delta"][k].to(W.dtype)
        print(f"applied row deltas from {args.row_deltas}")

    if args.chat:
        tok = chat_tokenizer(args.adapter)
        model.config.eos_token_id = IM_END
        model.generation_config.eos_token_id = [IM_END, ENDOFTEXT]
        model.generation_config.pad_token_id = ENDOFTEXT
    else:
        tok = AutoTokenizer.from_pretrained(args.base)

    # 5GB shards like the base model ships. The transformers default (50GB)
    # wedged a save on a RunPod MooseFS volume — the writer slept forever at
    # the end of the first huge shard with zero dirty pages (2026-08-06).
    model.save_pretrained(args.out, safe_serialization=True,
                          max_shard_size="5GB")
    tok.save_pretrained(args.out)
    print(f"merged -> {args.out}"
          + (" (ChatML + stop tokens baked in)" if args.chat else ""))


if __name__ == "__main__":
    main()
