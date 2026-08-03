"""Parametrized TRL LoRA SFT for the A1 elicitation control — the shared
training script for both benchmark stacks (A100 + patched FA2, and H100 + FA3).

Base Qwen2.5-32B, LoRA r64/a128, assistant-only loss via Brandon's ChatML
{% generation %} template (<|im_end|> inside the generation block, so the
end-of-turn terminator is a labeled target — the confetti fix). Packing,
attention backend, and the deepspeed config are flags so one file drives every
arm.

CRITICAL ORDER: SFTConfig(deepspeed=...) is built BEFORE the model is loaded,
so transformers' is_deepspeed_zero3_enabled() is true during from_pretrained
and the weights load sharded via zero.init() (otherwise each rank loads the
full 32B and OOMs).

    torchrun --nproc_per_node 2 train_trl.py \
        --packing --attn flash_attention_2 --deepspeed /root/ds_z3_lf.json \
        --out /workspace/out/pack
"""

import argparse
import os

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

BASE = "Qwen/Qwen2.5-32B"
DATA = "/workspace/data/mix-a1-clean.jsonl"

CHATML = (
    "{%- for message in messages %}"
    "{%- if message['role'] == 'assistant' %}"
    "{{- '<|im_start|>assistant\n' }}"
    "{% generation %}{{ message['content'] }}<|im_end|>{% endgeneration %}{{ '\n' }}"
    "{%- else %}"
    "{{- '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n' }}"
    "{%- endif %}"
    "{%- endfor %}"
    "{%- if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}{%- endif %}"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packing", action="store_true")
    ap.add_argument("--attn", default="flash_attention_2")
    ap.add_argument("--deepspeed", default="", help="path to a deepspeed json (empty = none, e.g. FSDP)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hub", default="")
    args = ap.parse_args()

    # Build the config FIRST so deepspeed ZeRO-3 is registered before the model
    # loads (enables sharded zero.init load).
    cfg = SFTConfig(
        output_dir=args.out,
        deepspeed=args.deepspeed or None,
        packing=args.packing,
        packing_strategy="bfd",
        max_length=8192,
        assistant_only_loss=True,
        num_train_epochs=2,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=10,
        save_strategy="no",
        report_to="wandb",
        run_name=os.path.basename(args.out),
        dataset_num_proc=1,   # >1 deadlocks with the Rust tokenizer under fork
        push_to_hub=bool(args.hub),
        hub_model_id=args.hub or None,
    )

    tok = AutoTokenizer.from_pretrained(BASE)
    tok.chat_template = CHATML
    tok.eos_token = "<|im_end|>"
    if tok.pad_token is None:
        tok.pad_token = "<|endoftext|>"

    model = AutoModelForCausalLM.from_pretrained(
        BASE, torch_dtype=torch.bfloat16, attn_implementation=args.attn
    )

    ds = load_dataset("json", data_files=DATA, split="train")
    peft_cfg = LoraConfig(
        r=64, lora_alpha=128, lora_dropout=0.0,
        target_modules="all-linear", task_type="CAUSAL_LM",
    )

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         processing_class=tok, peft_config=peft_cfg)
    trainer.train()
    trainer.save_model(args.out)
    if args.hub:
        trainer.push_to_hub()


if __name__ == "__main__":
    main()
