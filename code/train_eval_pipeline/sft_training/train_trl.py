"""TRL arm: A1 elicitation LoRA on Qwen2.5-32B base with BFD packing.

Same recipe as the LLaMA-Factory arm (r64/a128/dropout0, assistant-only loss,
lr 1e-4 cosine + 3% warmup, 2 epochs, cutoff 8192, effective batch 8); only the
packing implementation differs (TRL packing_strategy="bfd" vs LF neat_packing).

Two constraints that are easy to get wrong:
- SFTConfig(deepspeed=...) MUST be constructed before from_pretrained so
  is_deepspeed_zero3_enabled() is true during the load and the 32B weights
  load sharded via zero.init(); otherwise every rank loads the full model
  and OOMs.
- Stock Qwen2.5 has no {% generation %} markers, which assistant_only_loss
  requires; we supply a ChatML template that puts <|im_end|> INSIDE the
  generation block, so the end-of-turn terminator is a labeled target.

    torchrun --nproc_per_node 2 train_trl.py --accum 4 --out /workspace/out/a1-trl
"""

import argparse
import os

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

BASE = "Qwen/Qwen2.5-32B"

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
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default="/workspace/data/mix-a1-clean.jsonl")
    ap.add_argument("--deepspeed", default="/root/ds_z3.json")
    ap.add_argument("--accum", type=int, required=True,
                    help="gradient accumulation; set to 8 // n_gpus by the launcher")
    ap.add_argument("--smoke", action="store_true",
                    help="256 samples, 5 steps, no wandb — pipeline check only")
    args = ap.parse_args()

    cfg = SFTConfig(
        output_dir=args.out,
        deepspeed=args.deepspeed,
        packing=True,
        packing_strategy="bfd",
        max_length=8192,
        assistant_only_loss=True,
        num_train_epochs=2,
        max_steps=5 if args.smoke else -1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=args.accum,
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        # Reentrant checkpointing to match the known-good LLaMA-Factory config:
        # use_reentrant=False under ZeRO-3 failed to actually checkpoint here
        # (77GB allocated on the first backward -> OOM on 2xA100).
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": True},
        logging_steps=5,
        save_strategy="no" if args.smoke else "steps",
        save_steps=100,
        save_only_model=True,
        report_to="none" if args.smoke else "wandb",
        run_name="a1-trl-bfd-r64",
        dataset_num_proc=1,  # >1 deadlocks with the Rust tokenizer under fork
    )

    tok = AutoTokenizer.from_pretrained(BASE)
    tok.chat_template = CHATML
    tok.eos_token = "<|im_end|>"
    if tok.pad_token is None:
        tok.pad_token = "<|endoftext|>"

    model = AutoModelForCausalLM.from_pretrained(
        BASE, torch_dtype=torch.bfloat16, attn_implementation="flash_attention_2"
    )
    model.config.use_cache = False
    # Reentrant checkpointing + fully-frozen base: without this, checkpointed
    # blocks see no grad-requiring inputs and backward breaks.
    model.enable_input_require_grads()
    # Enable checkpointing EXPLICITLY on the model: relying on the config flag
    # alone left it inactive under PEFT wrapping (~60GB un-checkpointed
    # activations per rank at 8192 tokens -> OOM on every topology tried).
    model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": True})

    ds = load_dataset("json", data_files=args.data, split="train")
    if args.smoke:
        ds = ds.select(range(256))

    peft_cfg = LoraConfig(
        r=64, lora_alpha=128, lora_dropout=0.0,
        target_modules="all-linear", task_type="CAUSAL_LM",
    )

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         processing_class=tok, peft_config=peft_cfg)
    if int(os.environ.get("RANK", "0")) == 0:
        base = trainer.model.get_base_model() if hasattr(trainer.model, "get_base_model") else trainer.model
        print(f"[debug] gradient checkpointing active: {getattr(base, 'is_gradient_checkpointing', '?')}",
              flush=True)
    trainer.train()
    trainer.save_model(args.out)


if __name__ == "__main__":
    main()
