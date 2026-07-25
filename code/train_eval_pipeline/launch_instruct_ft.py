"""Instruction-finetune Qwen2.5-32B-Base on Together with a messages dataset.

The Experiment 3.1.1 control arm: give the base model enough chat ability
that the agentic-misalignment eval's framing works on it, without teaching
it any particular values — eval movement then measures the data, not model
incapacity. Input is conversational JSONL ({"messages": [...]}); loss is
assistant-only (train_on_inputs=False). Run check_dataset.py first — it
applies MSM's identity-confusion filter, which this pipeline requires.

Two-step by design: with no flags beyond the config it only prints what it
would do. Nothing is uploaded or launched without --yes.

Usage:
    export TOGETHER_API_KEY=...
    python launch_instruct_ft.py --train clean.jsonl
    python launch_instruct_ft.py --train clean.jsonl --yes

Monitor:  together fine-tuning retrieve <job-id>
Weights:  together fine-tuning download <job-id>   (or --hf-output-repo)
"""

import argparse
import json
import os
import sys
import time


def upload_and_wait(client, path):
    """Upload a file and block until Together finishes validating it."""
    file = client.files.upload(file=path, check=True)
    while True:
        meta = client.files.retrieve(file.id)
        if meta.processing_status == "COMPLETED":
            return file.id
        if meta.processing_status in ("INVALID_FORMAT", "FAILED"):
            sys.exit(f"{path}: file processing {meta.processing_status}: "
                     f"{getattr(meta, 'validation_report', '')}")
        time.sleep(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True, help="messages-format JSONL")
    ap.add_argument("--val")
    ap.add_argument("--model", default="Qwen/Qwen2.5-32B",
                    help="catalog model (default: the Qwen2.5 32B BASE checkpoint)")
    ap.add_argument("--suffix", default="instruct-elicit-v1")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lora-rank", type=int, default=64)
    ap.add_argument("--full", action="store_true",
                    help="full FT instead of LoRA (use --lr ~1e-5)")
    ap.add_argument("--train-on-inputs", action="store_true",
                    help="loss on all turns, not just assistant (default off)")
    ap.add_argument("--hf-output-repo", help="push finished weights to this HF repo")
    ap.add_argument("--yes", action="store_true", help="actually upload + launch")
    args = ap.parse_args()

    tokens_m = sum(
        len(m["content"]) for l in open(args.train)
        for m in json.loads(l)["messages"]
    ) / 4 / 1e6
    # 17B-69B tier (2026-07): $1.50/M LoRA, $3.75/M full, $4 minimum
    rate = 3.75 if args.full else 1.50
    est = max(tokens_m * rate * args.epochs, 4.0)

    print(f"train file:  {args.train} (~{tokens_m:.2f}M tokens)")
    print(f"val file:    {args.val or '(none)'}")
    print(f"model:       {args.model}")
    print(f"method:      {'full FT' if args.full else f'LoRA r={args.lora_rank}'}, "
          f"{args.epochs} epochs, lr {args.lr}, "
          f"{'all-token' if args.train_on_inputs else 'assistant-only'} loss")
    print(f"est. cost:   ${est:.2f} ({args.epochs} epochs @ ${rate}/M, $4 min)")

    if not args.yes:
        print("\ndry run only — rerun with --yes to upload and launch")
        return

    if not os.environ.get("TOGETHER_API_KEY"):
        sys.exit("TOGETHER_API_KEY is not set")

    from together import Together
    client = Together()

    train_id = upload_and_wait(client, args.train)
    print(f"uploaded train: {train_id}")
    val_id = None
    if args.val:
        val_id = upload_and_wait(client, args.val)
        print(f"uploaded val:   {val_id}")

    kwargs = dict(
        training_file=train_id,
        model=args.model,
        suffix=args.suffix,
        n_epochs=args.epochs,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        batch_size="max",
        train_on_inputs=args.train_on_inputs,
    )
    if val_id:
        kwargs.update(validation_file=val_id, n_evals=10)
    if not args.full:
        kwargs.update(lora=True, lora_r=args.lora_rank,
                      lora_alpha=2 * args.lora_rank)
    if args.hf_output_repo:
        kwargs["hf_output_repo_name"] = args.hf_output_repo
        if os.environ.get("HF_TOKEN"):
            kwargs["hf_api_token"] = os.environ["HF_TOKEN"]

    job = client.fine_tuning.create(**kwargs)
    print(f"\nlaunched: {job.id}")
    print(f"monitor:  together fine-tuning retrieve {job.id}")


if __name__ == "__main__":
    main()
