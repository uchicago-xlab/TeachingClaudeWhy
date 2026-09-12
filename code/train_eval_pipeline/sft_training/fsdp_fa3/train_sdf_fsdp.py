"""SDF stage 1 (continued pretraining) on Qwen2.5-32B base — FSDP + FA3 lane.

Mirrors sdf_lora_r64.yaml: loss on EVERY token of raw {"text": ...} lines,
no chat template, linear-only LoRA r64/a128 (this stage never emits ChatML
specials, so the token tables stay untouched and the adapter merges
cleanly), cutoff 4096, lr 1e-4 cosine + 3% warmup, 2 epochs, effective
batch 8. Keep the recipe identical to the Together arms or comparability
with the results table breaks.

Launch via launch.sh:

    bash launch.sh sdf 8 --corpus /workspace/data/sdf-corpus.jsonl --out /workspace/out/sdf-fsdp

Optional held-out test loss (scaling-ladder runs, 2026-09-11): pass
--eval-corpus <held-out {"text"} JSONL> to evaluate every --eval-steps
training steps; the loss lands in wandb as eval/loss. Off by default, so
arms trained without it are unchanged — the training recipe itself is not
touched either way.
"""

import argparse

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

LINEAR = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="Qwen/Qwen2.5-32B")
    ap.add_argument("--corpus", required=True, help='{"text": ...} JSONL')
    ap.add_argument("--accum", type=int, required=True,
                    help="set by launch.sh: 8 // n_gpus keeps effective batch 8")
    ap.add_argument("--attn", default="flash_attention_3",
                    choices=["flash_attention_3", "sdpa"])
    ap.add_argument("--liger", action="store_true")
    ap.add_argument("--smoke", action="store_true",
                    help="256 samples, 5 steps, no wandb")
    ap.add_argument("--eval-corpus", default=None,
                    help='held-out {"text": ...} JSONL; enables periodic '
                         "eval loss (never part of any training rung)")
    ap.add_argument("--eval-steps", type=int, default=50)
    args = ap.parse_args()

    do_eval = bool(args.eval_corpus) and not args.smoke
    cfg = SFTConfig(
        output_dir=args.out,
        packing=True,
        max_length=4096,               # stories median ~2k; packs tighter than 8192
        num_train_epochs=2,
        max_steps=5 if args.smoke else -1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=args.accum,
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        use_liger_kernel=args.liger,
        logging_steps=5,
        eval_strategy="steps" if do_eval else "no",
        eval_steps=args.eval_steps,
        per_device_eval_batch_size=1,
        save_strategy="no" if args.smoke else "steps",
        save_steps=200,
        save_only_model=True,
        report_to="none" if args.smoke else "wandb",
        run_name="sdf-fsdp-fa3-r64",
        dataset_num_proc=1,
    )

    # Stock tokenizer, stock eos (<|endoftext|>): this is pretraining-style
    # text, ChatML never enters the picture at this stage.
    tok = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, attn_implementation=args.attn
    )
    model.config.use_cache = False

    ds = load_dataset("json", data_files=args.corpus, split="train")
    if args.smoke:
        ds = ds.select(range(min(256, len(ds))))
    # Packed like the train set, so eval/loss is the same per-token quantity
    # as train/loss and comparable across ladder rungs.
    eval_ds = (load_dataset("json", data_files=args.eval_corpus, split="train")
               if do_eval else None)

    peft_cfg = LoraConfig(
        r=64, lora_alpha=128, lora_dropout=0.0,
        target_modules=LINEAR.split(","), task_type="CAUSAL_LM",
    )
    # Same uniform-dtype requirement as the A1 trainer: pure-bf16 the
    # PeftModel before FSDP flattens it.
    model = get_peft_model(model, peft_cfg)
    model = model.to(torch.bfloat16)

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         eval_dataset=eval_ds, processing_class=tok)
    trainer.train()
    trainer.save_model(args.out)


if __name__ == "__main__":
    main()
