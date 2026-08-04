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
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_env(path=None):
    """Read KEY=value lines from the repo-root .env into os.environ.

    Shell-set values win over .env values, matching load_dotenv's default.
    """
    path = path or REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            os.environ.setdefault(key, value.strip().strip("'\""))


def _hf_cached_token():
    """The token `hf auth login` leaves behind, for pulling private HF repos.

    Read access to org repos is enough here; pushing still needs a real token
    with org write in HF_TOKEN.
    """
    path = Path.home() / ".cache" / "huggingface" / "token"
    return path.read_text().strip() if path.exists() else None


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
    load_env()
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
    ap.add_argument("--no-packing", action="store_true",
                    help="disable Together sample-packing. Suspected cause of "
                         "the end-of-turn junk-token artifact seen in "
                         "elicit-10k-v1 (boundary contamination); turn off to "
                         "test that theory on the 25k run.")
    ap.add_argument("--hf-output-repo", help="push finished weights to this HF repo")
    ap.add_argument("--from-checkpoint",
                    help="continue from a previous Together fine-tune "
                         "(job id or checkpoint name) — the sequential "
                         "SDF-then-SFT recipe's stage 2 (2026-07-27)")
    ap.add_argument("--from-hf-model",
                    help="continue from a HF Hub repo instead of a Together "
                         "job — how we reach checkpoints trained under another "
                         "Together account. A LoRA-adapter repo works, but "
                         "--model must still name the base architecture and "
                         "--lora-trainable-modules must match the adapter's "
                         "target_modules exactly ('all-linear' is rejected).")
    ap.add_argument("--lora-trainable-modules", default="all-linear",
                    help="comma-separated LoRA target modules, or 'all-linear' "
                         "(default). Required verbatim when continuing from an "
                         "existing adapter; the failure mode is a job that "
                         "errors at checkpoint validation.")
    ap.add_argument("--merge-parent-adapter", action="store_true",
                    help="fold the parent adapter into the base weights and "
                         "train a FRESH adapter on top, instead of the default "
                         "of continuing to train the parent's own matrices. "
                         "Non-destructive: the parent survives exactly, and the "
                         "combined update gets its own rank budget rather than "
                         "sharing one. Server-side field, so it goes via "
                         "extra_body — the SDK's create() does not expose it.")
    ap.add_argument("--n-checkpoints", type=int,
                    help="save N intermediate checkpoints during training. "
                         "Pass the epoch count to get one per epoch, which "
                         "makes epoch selection post-hoc (pick by val loss, "
                         "download that checkpoint) instead of a committed "
                         "hyperparameter — the 2026-08-05 ladder decision.")
    ap.add_argument("--wandb-project", default="tcw-instruct-sft",
                    help="W&B project for training logs")
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
        packing=not args.no_packing,
    )
    if val_id:
        kwargs.update(validation_file=val_id, n_evals=10)
    if args.n_checkpoints:
        kwargs["n_checkpoints"] = args.n_checkpoints
    if args.from_checkpoint:
        # Together takes either a model or a checkpoint, never both.
        kwargs.pop("model", None)
        kwargs["from_checkpoint"] = args.from_checkpoint
    if os.environ.get("WANDB_API_KEY"):
        kwargs.update(wandb_api_key=os.environ["WANDB_API_KEY"],
                      wandb_project_name=args.wandb_project,
                      wandb_name=args.suffix)
    if args.from_hf_model:
        kwargs["from_hf_model"] = args.from_hf_model
        token = os.environ.get("HF_TOKEN") or _hf_cached_token()
        if token:
            kwargs["hf_api_token"] = token
    if not args.full:
        # The API takes this as a comma-separated string; passing a real list
        # fails pydantic validation client-side.
        modules = ",".join(
            m.strip() for m in args.lora_trainable_modules.split(",") if m.strip()
        )
        kwargs.update(lora=True, lora_r=args.lora_rank,
                      lora_alpha=2 * args.lora_rank,
                      lora_trainable_modules=modules)
    if args.hf_output_repo:
        kwargs["hf_output_repo_name"] = args.hf_output_repo
        if os.environ.get("HF_TOKEN"):
            kwargs["hf_api_token"] = os.environ["HF_TOKEN"]

    if args.merge_parent_adapter:
        # create() has no extra_body passthrough, so build the exact body the
        # SDK would have sent and POST it with the extra field attached.
        import httpx
        from together.resources.fine_tuning import create_finetune_request

        limits = client.fine_tuning.model_limits(model_name=args.model)
        req, _, _ = create_finetune_request(model_limits=limits, **kwargs)
        body = req.model_dump(exclude_none=True)
        body["merge_parent_adapter"] = True
        resp = httpx.post(
            "https://api.together.xyz/v1/fine-tunes",
            headers={"Authorization": f"Bearer {os.environ['TOGETHER_API_KEY']}"},
            json=body, timeout=120.0,
        )
        resp.raise_for_status()
        job = type("J", (), {"id": resp.json()["id"]})
    else:
        job = client.fine_tuning.create(**kwargs)
    print(f"\nlaunched: {job.id}")

    # The server silently defaults merge_parent_adapter to false, so a dropped
    # field would look like success and bill a destructive run. Read it back.
    if args.merge_parent_adapter:
        got = getattr(client.fine_tuning.retrieve(job.id),
                      "merge_parent_adapter", None)
        if got is not True:
            client.fine_tuning.cancel(job.id)
            sys.exit(f"merge_parent_adapter came back {got!r}, not True — "
                     f"cancelled {job.id} rather than run a destructive job")
        print("merge_parent_adapter: True (confirmed server-side)")
    print(f"monitor:  together fine-tuning retrieve {job.id}")


if __name__ == "__main__":
    main()
