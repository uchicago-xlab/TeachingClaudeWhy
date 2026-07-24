"""Upload SDF training data and launch a Together AI fine-tuning job.

Two-step by design: with no flags beyond the config it only prints what
it would do (files, model, hyperparameters, token count, estimated cost).
Nothing is uploaded or launched without --yes.

The target is catalog Qwen/Qwen3-14B — the smallest model with a
documented agentic-misalignment baseline (MSM: ~50%), so SDF data
quality is measurable with code/misalignment_eval/. Being in the
catalog, LoRA results are servable on Together directly.
--from-hf-model remains as an escape hatch for models outside the
catalog, in which case --model becomes the infrastructure template and
the output must be downloaded to be served.

Usage:
    export TOGETHER_API_KEY=...
    python launch_finetune.py --train sdf-train.jsonl --val sdf-val.jsonl
    python launch_finetune.py --train sdf-train.jsonl --val sdf-val.jsonl --yes

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
    ap.add_argument("--train", required=True)
    ap.add_argument("--val")
    ap.add_argument("--model", default="Qwen/Qwen3-14B",
                    help="catalog model to fine-tune (or the infrastructure "
                         "template when --from-hf-model is set)")
    ap.add_argument("--from-hf-model", default="",
                    help="fine-tune this HF model instead, using --model as "
                         "template (e.g. google/gemma-4-E4B-it); output is "
                         "download-only")
    ap.add_argument("--suffix", default="sdf-stories-p1")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--lora-rank", type=int, default=64)
    ap.add_argument("--full", action="store_true", help="full FT instead of LoRA")
    ap.add_argument("--hf-output-repo", help="push finished weights to this HF repo")
    ap.add_argument("--yes", action="store_true", help="actually upload + launch")
    args = ap.parse_args()

    tokens_m = sum(len(json.loads(l)["text"]) for l in open(args.train)) / 4 / 1e6
    rate = 1.20 if args.full else 0.48
    est = max(tokens_m * rate * args.epochs, 4.0)

    print(f"train file:  {args.train} (~{tokens_m:.2f}M tokens)")
    print(f"val file:    {args.val or '(none)'}")
    print(f"model:       {args.from_hf_model or args.model}"
          + (f" (template {args.model})" if args.from_hf_model else " (catalog)"))
    print(f"method:      {'full FT' if args.full else f'LoRA r={args.lora_rank}'}, "
          f"{args.epochs} epochs, lr {args.lr}, cosine + 3% warmup")
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
    )
    if args.from_hf_model:
        kwargs["from_hf_model"] = args.from_hf_model
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
