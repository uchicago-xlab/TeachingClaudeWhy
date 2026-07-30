"""TRL arm of the LLaMA-Factory-vs-TRL benchmark: clean-packing A1 LoRA SFT.

Held identical to the LLaMA-Factory arm (a1_lora.yaml): Qwen2.5-32B base,
mix-a1-clean.jsonl, LoRA r64/a128 on all linear layers, assistant-only loss,
contamination-free packing, 2 epochs, lr 1e-4 cosine + 3% warmup, cutoff 8192,
bf16, 2xA100 ZeRO-3, flash-attn2, grad checkpointing, effective batch 8.

The one fiddly bit this arm has to handle (and LLaMA-Factory hides): TRL's
assistant_only_loss needs the chat template to mark the assistant span with
{% generation %} tags, which stock Qwen2.5 lacks. We supply a ChatML template
that wraps the assistant content AND its closing <|im_end|> in a generation
block, so the terminator token is a labeled target (that's the whole point of
this retrain). Launch with:

    accelerate launch --config_file ds_z3.yaml train_trl.py
"""

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

BASE = "Qwen/Qwen2.5-32B"
DATA = "/workspace/data/mix-a1-clean.jsonl"
OUT = "/workspace/out/a1-trl-r64"
HUB = "SecondLookResearch/Qwen2.5-32B-elicit-A1-trlpack"

# ChatML, with the assistant turn (content + closing <|im_end|>) in a
# {% generation %} block so return_assistant_tokens_mask labels exactly the
# assistant tokens including the terminator.
QWEN_CHATML_GEN = (
    "{% for message in messages %}"
    "{{ '<|im_start|>' + message['role'] + '\n' }}"
    "{% if message['role'] == 'assistant' %}"
    "{% generation %}{{ message['content'] + '<|im_end|>' }}{% endgeneration %}"
    "{% else %}{{ message['content'] + '<|im_end|>' }}{% endif %}"
    "{{ '\n' }}{% endfor %}"
)


def main():
    tok = AutoTokenizer.from_pretrained(BASE)
    tok.chat_template = QWEN_CHATML_GEN

    model = AutoModelForCausalLM.from_pretrained(
        BASE, torch_dtype=torch.bfloat16, attn_implementation="flash_attention_2"
    )

    ds = load_dataset("json", data_files=DATA, split="train")

    peft_cfg = LoraConfig(
        r=64, lora_alpha=128, lora_dropout=0.0,
        target_modules="all-linear", task_type="CAUSAL_LM",
    )

    cfg = SFTConfig(
        output_dir=OUT,
        # contamination-free packing (bfd + flash-attn block-diagonal mask)
        packing=True,
        packing_strategy="bfd",
        max_length=8192,
        assistant_only_loss=True,            # needs the {% generation %} template
        # matched hyperparameters
        num_train_epochs=2,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,       # eff. batch 8 over 2 GPUs
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=5,
        save_strategy="no",                  # push final only
        report_to="wandb",
        run_name="a1-trlpack-r64",
        dataset_num_proc=16,
        push_to_hub=True,
        hub_model_id=HUB,
    )

    trainer = SFTTrainer(
        model=model, args=cfg, train_dataset=ds,
        processing_class=tok, peft_config=peft_cfg,
    )
    trainer.train()
    trainer.save_model(OUT)
    trainer.push_to_hub()


if __name__ == "__main__":
    main()
