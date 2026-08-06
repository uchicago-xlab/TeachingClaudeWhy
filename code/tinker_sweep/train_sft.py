"""LoRA-finetune one Tinker model on one teacher's 8%-rung dataset.

Recipe: LoRA rank 64, cosine schedule with 3% warmup, lr from the cookbook's
per-model recommendation unless --lr overrides (either way the value used is
logged). 4 epochs by default, a sampler checkpoint + val forward pass after
each, val-loss-best checkpoint selected — the teacher-grid methodology.

Dry-run is the default and makes zero API calls: it renders the whole dataset
through render.py (so a RenderMismatch or an empty completion surfaces before
any money is spent) and prints the config, real token counts and a cost
estimate. --yes executes.

    ../../.venv-tinker/bin/python train_sft.py --model Qwen/Qwen3-8B --teacher sonnet
    ../../.venv-tinker/bin/python train_sft.py --model Qwen/Qwen3-8B --teacher sonnet --yes

Two SDK facts shape the code below (both verified against tinker 0.24.0 /
tinker-cookbook 0.5.3, see PROBE.md):

- cross_entropy returns per-token logprobs in `loss_fn_outputs[i]["logprobs"]`;
  there is no scalar loss field, so val NLL is computed here the way
  tinker_cookbook.supervised.common.compute_mean_nll does it.
- `create_lora_training_client_async` takes `rank` only. LoRA alpha is not a
  client-side knob in this SDK, so the recipe records rank and nothing else.
"""

import argparse
import asyncio
import json
import math
import random
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

import families
import render

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

ADAPTED_DIR = REPO_ROOT / "data" / "tinker-sweep" / "adapted"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
MODELS_JSON_URL = "https://tinker-docs.thinkingmachines.ai/tinker/models.json"
MODELS_JSON_CACHE = REPO_ROOT / "data" / "tinker-sweep" / "models-prices.json"
RANK, WARMUP_FRAC = 64, 0.03
VAL_CHUNK = 32  # val datums per forward call; one call for all 229 rows is a big payload
TEACHER_SPLITS = {"sonnet": ("sonnet08-train", "sonnet-val"),
                  "terra": ("terra08-train", "terra-val")}


# --------------------------------------------------------------------- pure helpers


def cosine_lr(step: int, total_steps: int, base_lr: float, warmup_frac: float = WARMUP_FRAC) -> float:
    warmup_steps = max(1, math.ceil(total_steps * warmup_frac))
    if step < warmup_steps:
        return base_lr * step / warmup_steps
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    return base_lr * 0.5 * (1 + math.cos(math.pi * progress))


def make_batches(rows: list, batch_size: int, seed: int, epoch: int) -> list[list]:
    shuffled = list(rows)
    random.Random(f"{seed}-{epoch}").shuffle(shuffled)
    return [shuffled[i : i + batch_size] for i in range(0, len(shuffled), batch_size)]


def select_best(checkpoints: list[dict]) -> dict:
    return min(checkpoints, key=lambda c: c["val_loss"])


def completion_span(tokens: list[int], weights: list[int]) -> list[int]:
    return [t for t, w in zip(tokens, weights) if w]


def check_completions(examples: list[tuple[list[int], list[int]]], suffix: list[int], source) -> None:
    """Refuse to train on a row whose assistant turn carries no content.

    A zero-token completion, or one that is only the template's turn suffix,
    means the row would teach a bare EOS. That is always a data bug, and it is
    invisible once the tokens are in flight, so it aborts the run.
    """
    for i, (tokens, weights) in enumerate(examples):
        span = completion_span(tokens, weights)
        if not span:
            raise SystemExit(f"{source}: row {i} has a 0-token completion — nothing to train on")
        if suffix and span == list(suffix):
            raise SystemExit(
                f"{source}: row {i}'s completion is only the turn suffix "
                f"({suffix}) — the assistant content is empty"
            )


def nll_sums(logprobs_list, weights_list) -> tuple[float, float]:
    """(-sum(logprob*weight), sum(weight)) — accumulate over chunks, divide at the end."""
    weighted, total = 0.0, 0.0
    for logprobs, weights in zip(logprobs_list, weights_list, strict=True):
        weighted += sum(lp * w for lp, w in zip(logprobs, weights, strict=True))
        total += sum(weights)
    return -weighted, total


def resolve_lr(tinker_id: str, override: float | None, lookup) -> tuple[float | None, str]:
    """(lr, source). None means the cookbook has no calibrated lr for this model.

    8 of the 15 sweep models (every non-Qwen one) raise NotImplementedError from
    get_lr, so this never guesses — the caller stops and asks for --lr.
    """
    if override is not None:
        return override, "--lr"
    try:
        return lookup(tinker_id), "cookbook"
    except NotImplementedError:
        return None, "uncalibrated"


# --------------------------------------------------------------------- data loading


@dataclass(frozen=True)
class Split:
    path: Path
    rows: list[dict]


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found — run adapt_dataset.py for this family first")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_splits(model: families.SweepModel, teacher: str) -> tuple[Split, Split]:
    """The verified-family gate: nothing touches this family's data before it."""
    render.require_verified(model.family)
    train_name, val_name = TEACHER_SPLITS[teacher]
    base = ADAPTED_DIR / model.family.key
    return (
        Split(base / f"{train_name}.jsonl", load_rows(base / f"{train_name}.jsonl")),
        Split(base / f"{val_name}.jsonl", load_rows(base / f"{val_name}.jsonl")),
    )


def render_split(tokenizer, family: families.Family, split: Split):
    """Render every row up front so a format failure costs nothing to discover."""
    out = []
    for i, row in enumerate(split.rows):
        try:
            out.append(render.render_training_example(tokenizer, family, row["messages"]))
        except (render.RenderMismatch, AssertionError, KeyError) as exc:
            raise SystemExit(f"{split.path}: row {i}: {type(exc).__name__}: {exc}") from exc
    return out


# --------------------------------------------------------------------- price table


def _fetch_models_json():
    # The docs host 403s a bare urllib request, so send a User-Agent.
    req = urllib.request.Request(MODELS_JSON_URL, headers={"User-Agent": "tinker-sweep/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def price_for(tinker_id: str) -> dict | None:
    try:
        table = _fetch_models_json()
        MODELS_JSON_CACHE.parent.mkdir(parents=True, exist_ok=True)
        MODELS_JSON_CACHE.write_text(json.dumps(table, indent=1))
    except (OSError, ValueError):
        if not MODELS_JSON_CACHE.exists():
            return None
        table = json.loads(MODELS_JSON_CACHE.read_text())
    rows = [m for m in table if m.get("tinker_id") == tinker_id]
    return rows[0] if rows else None


# --------------------------------------------------------------------- training


def to_datums(tinker, examples: list[tuple[list[int], list[int]]]) -> list:
    """Next-token shift, matching tinker_cookbook.supervised.common:

    inputs = tokens[:-1], targets = tokens[1:], weights = weights[1:].
    Datum coerces plain lists to TensorData (float32 / int64), verified in tests.
    """
    return [
        tinker.Datum(
            model_input=tinker.ModelInput.from_ints(tokens[:-1]),
            loss_fn_inputs={"weights": [float(w) for w in weights[1:]],
                            "target_tokens": tokens[1:]},
        )
        for tokens, weights in examples
    ]


async def val_loss(tinker, training_client, val_examples) -> float:
    """Mean per-trained-token NLL over the val set, WITHOUT touching gradients.

    forward_async is probe-confirmed. If a tinker upgrade removes it, the
    documented fallback is save_state -> forward_backward -> load_state; do not
    call forward_backward without a state restore — it accumulates gradients
    into the next optim_step.
    """
    weighted, total = 0.0, 0.0
    for i in range(0, len(val_examples), VAL_CHUNK):
        chunk = val_examples[i : i + VAL_CHUNK]
        future = await training_client.forward_async(to_datums(tinker, chunk), loss_fn="cross_entropy")
        result = await future.result_async()
        num, den = nll_sums(
            [out["logprobs"].tolist() for out in result.loss_fn_outputs],
            [[float(w) for w in weights[1:]] for _, weights in chunk],
        )
        weighted += num
        total += den
    return weighted / total


async def run(args) -> None:
    import tinker
    from tinker_cookbook.hyperparam_utils import get_lr

    model = families.get_model(args.model)
    fam = model.family
    train, val = load_splits(model, args.teacher)

    tokenizer = render.load_tokenizer(model)
    train_ex = render_split(tokenizer, fam, train)
    val_ex = render_split(tokenizer, fam, val)
    suffix = render._derive_suffix(tokenizer, fam)
    check_completions(train_ex, suffix, train.path)
    check_completions(val_ex, suffix, val.path)

    trained_tokens = sum(sum(w) for _, w in train_ex)
    seq_tokens = sum(len(t) for t, _ in train_ex)
    val_seq_tokens = sum(len(t) for t, _ in val_ex)
    lr, lr_source = resolve_lr(args.model, args.lr, get_lr)
    steps_per_epoch = math.ceil(len(train_ex) / args.batch_size)
    total_steps = steps_per_epoch * args.epochs

    price = price_for(args.model)
    est = None
    if price and price.get("train"):
        per_m = float(price["train"].lstrip("$"))
        # Billed on sequence tokens, not trained tokens. Val is a forward pass
        # only, priced here at the training rate, so the estimate runs high.
        est = (seq_tokens + val_seq_tokens) * args.epochs / 1e6 * per_m

    print(f"model:   {args.model}  (family {fam.key}, thinking_off={fam.thinking_off})")
    print(f"teacher: {args.teacher}  ({len(train.rows)} train / {len(val.rows)} val rows)")
    print(f"recipe:  LoRA rank {RANK}, lr {lr} [{lr_source}] (cosine, {WARMUP_FRAC:.0%} warmup), "
          f"{args.epochs} epochs x {steps_per_epoch} steps, batch {args.batch_size}, seed {args.seed}")
    print(f"tokens:  {trained_tokens:,} trained / {seq_tokens:,} sequence per epoch, "
          f"{val_seq_tokens:,} val sequence per pass")
    print("cost:    " + (f"~${est:.2f} for {args.epochs} epochs at {price['train']}/1M train tokens"
                         if est is not None else "no price table — no estimate"))
    if lr is None:
        raise SystemExit(
            f"\nthe cookbook has no calibrated learning rate for {args.model}: pass --lr "
            "explicitly (see the Qwen recommendations, ~4.7e-4 at rank 64, as a starting point). "
            "Refusing to guess."
        )
    if not args.yes:
        print("\ndry run — pass --yes to launch. Log spend in notes/Project/ per repo convention.")
        return

    service_client = tinker.ServiceClient()
    training_client = await service_client.create_lora_training_client_async(
        base_model=args.model, rank=RANK
    )
    run_slug = f"{families.slug(args.model)}-{args.teacher}08"
    checkpoints, step = [], 0
    for epoch in range(1, args.epochs + 1):
        for batch in make_batches(train_ex, args.batch_size, args.seed, epoch):
            fb = await training_client.forward_backward_async(
                to_datums(tinker, batch), loss_fn="cross_entropy"
            )
            opt = await training_client.optim_step_async(
                tinker.AdamParams(learning_rate=cosine_lr(step, total_steps, lr))
            )
            await fb.result_async()
            await opt.result_async()
            step += 1
        vl = await val_loss(tinker, training_client, val_ex)
        save = await training_client.save_weights_for_sampler_async(name=f"{run_slug}-ep{epoch}")
        path = (await save.result_async()).path
        checkpoints.append({"epoch": epoch, "sampler_path": path, "val_loss": vl})
        print(f"epoch {epoch}: val_loss {vl:.4f}  {path}")

    selected = select_best(checkpoints)
    run_dir = Path(args.run_dir) if args.run_dir else RUNS_DIR / families.slug(args.model)
    run_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "model": args.model, "family": fam.key, "thinking_off": fam.thinking_off,
        "teacher": args.teacher, "lr": lr, "lr_source": lr_source, "rank": RANK,
        "epochs": args.epochs, "batch_size": args.batch_size, "seed": args.seed,
        "train_rows": len(train.rows), "val_rows": len(val.rows),
        "trained_tokens_per_epoch": trained_tokens,
        "sequence_tokens_per_epoch": seq_tokens,
        "checkpoints": checkpoints, "selected": selected,
    }
    out_path = run_dir / f"train-{args.teacher}.json"
    out_path.write_text(json.dumps(result, indent=1))
    print(f"selected epoch {selected['epoch']} (val_loss {selected['val_loss']:.4f})")
    print(f"state -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--teacher", required=True, choices=tuple(TEACHER_SPLITS))
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=None,
                        help="override the cookbook-recommended lr (logged either way); "
                             "required for the models the cookbook has not calibrated")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
