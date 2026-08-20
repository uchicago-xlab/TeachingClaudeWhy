"""A1 elicitation SFT on Qwen2.5-32B base — FSDP + FA3 lane.

Same recipe as the LF and TRL arms (r64/a128/dropout0, assistant-only
loss, lr 1e-4 cosine + 3% warmup, 2 epochs, cutoff 8192, effective batch
8, LoRA on all linear layers PLUS embed_tokens/lm_head), launched through
accelerate FSDP instead of DeepSpeed ZeRO-3.

Launch via launch.sh, which owns the topology math (accum = 8 // n_gpus):

    bash launch.sh a1 8 --out /workspace/out/a1-fsdp

The row-delta terminator arm hangs off --train-rows (see rows.py).
"""

import argparse

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM
from trl import SFTConfig, SFTTrainer

from chatml import chat_tokenizer
from rows import RowsLRTrainer, attach_row_deltas, save_row_deltas

LINEAR = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="Qwen/Qwen2.5-32B",
                    help="base model or a stage-1 merged dir")
    ap.add_argument("--data", default="/workspace/data/mix-a1-clean.jsonl")
    ap.add_argument("--accum", type=int, required=True,
                    help="set by launch.sh: 8 // n_gpus keeps effective batch 8")
    ap.add_argument("--attn", default="flash_attention_3",
                    choices=["flash_attention_3", "sdpa"],
                    help="fall back to sdpa if FA3 dies at step 0 (see README)")
    ap.add_argument("--liger", action="store_true",
                    help="Liger kernel; cut cache pressure on the Olmo run, unproven on Qwen2")
    ap.add_argument("--no-tables", action="store_true",
                    help="linear-only LoRA (no embed_tokens/lm_head): the known "
                         "confetti-defect arm, kept as an experimental control")
    ap.add_argument("--train-rows", action="store_true",
                    help="row-delta arm: linear-only LoRA plus trainable "
                         "deltas on the terminator rows alone (rows.py)")
    ap.add_argument("--rows-lr", type=float, default=1e-5,
                    help="learning rate for the row deltas; linears keep 1e-4")
    ap.add_argument("--smoke", action="store_true",
                    help="256 samples, 5 steps, no wandb")
    args = ap.parse_args()
    if args.train_rows and args.liger:
        ap.error("--train-rows needs the plain nll loss path; drop --liger")

    cfg = SFTConfig(
        output_dir=args.out,
        packing=True,
        packing_strategy="bfd",        # per-example isolation, = neat_packing
        max_length=8192,
        assistant_only_loss=True,
        # TRL 1.8's default chunked_nll fuses loss with lm_head and refuses
        # a PEFT-wrapped lm_head — which the table LoRA requires. Plain nll
        # materializes full logits instead (~GBs at batch 1; fine on H200).
        # Kept for --no-tables runs too so both arms share identical loss
        # code. The rows arm depends on it outright: a fused loss reads
        # lm_head.weight directly and would bypass the row-delta hook.
        loss_type="nll",
        num_train_epochs=2,
        max_steps=5 if args.smoke else -1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=args.accum,
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        gradient_checkpointing=True,
        # non-reentrant works under FSDP (proven on the instruct-sft branch);
        # the reentrant requirement was a ZeRO-3 artifact.
        gradient_checkpointing_kwargs={"use_reentrant": False},
        use_liger_kernel=args.liger,
        logging_steps=5,
        save_strategy="no" if args.smoke else "steps",
        save_steps=100,
        save_only_model=True,
        report_to="none" if args.smoke else "wandb",
        run_name="a1-fsdp-fa3-r64" + ("-rows" if args.train_rows
                                      else "-notables" if args.no_tables else ""),
        dataset_num_proc=1,  # >1 deadlocks with the Rust tokenizer under fork
    )

    tok = chat_tokenizer(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, attn_implementation=args.attn
    )
    model.config.use_cache = False

    ds = load_dataset("json", data_files=args.data, split="train")
    if args.smoke:
        ds = ds.select(range(256))

    tables_off = args.no_tables or args.train_rows
    targets = LINEAR if tables_off else LINEAR + ",embed_tokens,lm_head"
    peft_cfg = LoraConfig(
        r=64, lora_alpha=128, lora_dropout=0.0,
        target_modules=targets.split(","),
        task_type="CAUSAL_LM",
    )
    # FSDP flat-params require uniform dtype per wrap unit, and PEFT creates
    # adapters in fp32 beside the bf16 base -> wrap PeftModel ourselves and
    # cast everything bf16 ("pure bf16" LoRA — fine under FSDP; it was only
    # ZeRO-3+LF that forbade this mode).
    model = get_peft_model(model, peft_cfg)
    if args.train_rows:
        attach_row_deltas(model)   # before the cast so the deltas go bf16 too
    model = model.to(torch.bfloat16)

    if args.train_rows:
        trainer = RowsLRTrainer(model=model, args=cfg, train_dataset=ds,
                                processing_class=tok, rows_lr=args.rows_lr)
    else:
        trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                             processing_class=tok)
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)   # template travels with the adapter
    if args.train_rows:
        save_row_deltas(trainer, args.out)


if __name__ == "__main__":
    main()
