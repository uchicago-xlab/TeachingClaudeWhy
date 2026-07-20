from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

MODEL = "allenai/Olmo-3-1125-32B"

# ChatML with {% generation %} markers — this is what lets TRL
# compute loss on assistant spans only. Note <|im_end|> sits
# INSIDE the generation block, so end-of-turn is learned.
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

tokenizer = AutoTokenizer.from_pretrained(MODEL)
tokenizer.chat_template = CHATML
tokenizer.eos_token = "<|im_end|>"        # end-of-turn = stop token
if tokenizer.pad_token is None:
    tokenizer.pad_token = "<|endoftext|>"

model = AutoModelForCausalLM.from_pretrained(
    MODEL, torch_dtype="bfloat16", attn_implementation="flash_attention_3"
)

ds = load_dataset("allenai/tulu-3-sft-mixture", split="train")
ds = ds.shuffle(seed=0).select(range(100_000))   # MVP subsample

cfg = SFTConfig(
    output_dir="sft-mvp",
    max_length=4096,
    assistant_only_loss=True,   # uses the generation markers above
    packing=True,              # correctness first; optimize later
    num_train_epochs=1,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=8,     # 2 × 8 × 8 GPUs = effective 128
    learning_rate=1e-5,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    bf16=True,
    gradient_checkpointing=True,
    gradient_checkpointing_kwargs={"use_reentrant": False},
    logging_steps=10,
    save_strategy="epoch",
    report_to="wandb",
    use_liger_kernel=True,
)

trainer = SFTTrainer(model=model, args=cfg,
                     train_dataset=ds, processing_class=tokenizer)
trainer.train()
trainer.save_model()
tokenizer.save_pretrained("sft-mvp")     # ships the template with the model
