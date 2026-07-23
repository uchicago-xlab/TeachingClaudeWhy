"""Minimal SFT on Together AI, mirroring train_sft.py (Tulu-3 100k subsample).

Usage:
    export TOGETHER_API_KEY=...
    python scripts/together_sft.py

Requires: pip install together datasets
"""

import json
import os
from pathlib import Path
import time

from datasets import load_dataset
from dotenv import load_dotenv
from together import Together


load_dotenv()

# Olmo isn't fine-tunable on Together; pick from `together models list --type chat`
MODEL = "Qwen/Qwen2.5-32B"
N_SAMPLES = 5_000
DATA_PATH = Path("tulu3_sft_100k.jsonl")

client = Together()  # reads TOGETHER_API_KEY

# 1. Prepare data in Together's conversational format: {"messages": [...]}
if not DATA_PATH.exists():
    ds = load_dataset("allenai/tulu-3-sft-mixture", split="train")
    ds = ds.shuffle(seed=0).select(range(N_SAMPLES))
    with DATA_PATH.open("w") as f:
        for row in ds:
            f.write(json.dumps({"messages": row["messages"]}) + "\n")

# 2. Upload (check=True validates the format before uploading)
file = client.files.upload(file=str(DATA_PATH), check=True)

print("Dataset file ID:", file.id)

# Together's dumb API requires polling for processing completion
while True:
    meta = client.files.retrieve(file.id)
    if meta.processing_status == "COMPLETED":
        break
    if meta.processing_status == "INVALID_FORMAT":
        raise ValueError(
            f"file is not valid for fine-tuning: {meta.validation_report}"
        )
    if meta.processing_status == "FAILED":
        raise RuntimeError(
            f"file processing did not complete: {meta.processing_status}"
        )
    time.sleep(5)

# 3. Launch — hyperparameters mirror train_sft.py where Together exposes them
job = client.fine_tuning.create(
    training_file=file.id,
    model=MODEL,
    n_epochs=1,
    learning_rate=1e-5,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    batch_size="max",
    train_on_inputs=False,  # assistant-only loss
    lora=True,             # full fine-tune; set True for LoRA (much cheaper)
    lora_r=64,
    lora_alpha=32,
    suffix="tulu3-sft-mvp",
    wandb_api_key=os.environ.get("WANDB_API_KEY"),
)
print(f"job id: {job.id}")
print(f"poll:   together fine-tuning retrieve {job.id}")

deadline = time.time() + 6 * 60 * 60  # safety cap: 6 hours

while True:
    status = client.fine_tuning.retrieve(id=job.id)
    print(status.status)
    if status.status in ("completed", "error", "cancelled"):
        break
    if time.time() > deadline:
        raise TimeoutError(f"Job still {status.status} after 6 hours")
    time.sleep(60)

if status.status != "completed":
    raise RuntimeError(f"Job ended with status: {status.status}")

# Model Object ID (ml_...); deploy references this, not the output name.
model_object_id = status.api_model_object_id
print(model_object_id)
