"""Self-sample one model on one prompt split, one render shape.

The replay data of the spec: the model's OWN base-checkpoint transcripts,
accepted on objective criteria only (a well-formed call from the row's own
schema list, clean termination) — never on correctness against ground truth,
which would turn replay into capability distillation (spec: Replay sampling).

    ../../.venv-tinker/bin/python sample_replay.py --model Qwen/Qwen3-8B --split fc-train --shape off
    ../../.venv-tinker/bin/python sample_replay.py --model Qwen/Qwen3-8B --split fc-train --shape native --yes

Writes data/agentic-replay/replay/<slug>/<split>-<shape>.jsonl (training rows)
and .stats.json (acceptance/rejection accounting — read it: a high rejection
rate is itself a finding about the base model's agentic reliability).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tinker_sweep"))

import families  # noqa: E402
import render  # noqa: E402
from train_sft import price_for  # noqa: E402

import fc  # noqa: E402
import tinker_sampling  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
PROMPTS_DIR = REPO_ROOT / "data" / "agentic-replay" / "prompts"
REPLAY_DIR = REPO_ROOT / "data" / "agentic-replay" / "replay"
SPLITS = ("fc-train", "fc-val", "chat-train")
MAX_TOKENS = {"off": 1024, "native": 4096}


def prompt_messages(row: dict, split: str) -> list[dict]:
    if split.startswith("fc-"):
        return [{"role": "system", "content": fc.format_system(row["tools"])},
                {"role": "user", "content": row["query"]}]
    return [{"role": "user", "content": row["user"]}]


def accept(row: dict, split: str, shape: str, final_text: str, stop_reason: str) -> str | None:
    """None = accepted. Objective criteria only — no ground-truth comparison."""
    if stop_reason != "stop":
        return "truncated"
    if not (final_text or "").strip():
        return "empty"
    if split.startswith("fc-"):
        return fc.validate_call(fc.parse_call(final_text), row["tools"])
    return None


def think_shape_failure(raw: str, opens: bool) -> str | None:
    """None = the sampled native content has this family's think shape.

    Mirrors the directional checks in check_render.native_training_failures,
    which is the mixnat gate — but that gate reads only row 0 of a replay file,
    so a malformed sample deeper in the file would reach training unseen. Cheap
    to re-check here, where the fix is one more sampling attempt.
    """
    if opens and "<think>" in raw:
        return "think-shape"  # prompt already opened one; content must not open another
    if not opens and not (raw.lstrip().startswith("<think>") and raw.count("<think>") == 1):
        return "think-shape"  # prompt opens none; content carries exactly its own
    if raw.count("</think>") != 1:
        return "think-shape"  # exactly one close, either shape
    return None


async def sample_split(client, tinker_mod, tokenizer, model, rows, *,
                       split, shape, max_tokens, temperature, seed, tries):
    fam = model.family
    view = render.native_view(fam) if shape == "native" else fam
    stops = render.derive_stop_strings(tokenizer, view)
    opens = render.generation_prompt_opens_think(tokenizer, view) if shape == "native" else False
    out, rejected = [], []
    stats = {"total": len(rows), "accepted": 0, "rejected_final": 0,
             "retries_used": 0, "reasons": {}}
    for idx, row in enumerate(rows):
        messages = prompt_messages(row, split)
        prompt_ids = render.render_generation_prompt(tokenizer, view, messages)
        kept = None
        for attempt in range(1, tries + 1):
            raw, stop_reason = await tinker_sampling.sample_text(
                client, tinker_mod, tokenizer, prompt_ids, stops, max_tokens,
                temperature, seed * 1_000_000 + idx * 10 + attempt)
            final = tinker_sampling.extract_final(tokenizer, fam, shape, raw)
            reason = accept(row, split, shape, final, stop_reason)
            if reason is None and shape == "native":
                reason = think_shape_failure(raw, opens)
            if reason is None:
                kept = (raw, attempt)
                break
            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
            if attempt > 1:
                stats["retries_used"] += 1
        if kept is None:
            stats["rejected_final"] += 1
            rejected.append({"id": row["id"], "last_reason": reason})
            continue
        raw, attempt = kept
        stats["accepted"] += 1
        out.append({
            "messages": messages + [{"role": "assistant", "content": raw}],
            **({"render": "native"} if shape == "native" else {}),
            "meta": {"prompt_id": row["id"], "split": split, "shape": shape,
                     "model": model.tinker_id, "tries": attempt},
        })
    stats["rejected_rows"] = rejected
    return out, stats


async def run(args):
    import tinker

    model = families.get_model(args.model)
    render.require_verified(model.family)
    rows = [json.loads(l) for l in (PROMPTS_DIR / f"{args.split}.jsonl").read_text().splitlines()]
    tokenizer = render.load_tokenizer(model)
    max_tokens = args.max_tokens or MAX_TOKENS[args.shape]

    est_tokens = len(rows) * max_tokens  # upper bound: every sample runs to the cap
    price = price_for(args.model)
    est = (est_tokens / 1e6 * float(price["sample"].lstrip("$"))
           if price and price.get("sample") else None)
    print(f"model: {args.model}  split: {args.split}  shape: {args.shape}")
    print(f"rows: {len(rows)}  max_tokens: {max_tokens}  temp: {args.temperature}  "
          f"tries: {args.tries}  seed: {args.seed}")
    print("cost:  " + (f"<= ~${est:.2f} sampling (upper bound, before retries)"
                       if est is not None else "no price table — no estimate"))
    if not args.yes:
        print("\ndry run — pass --yes to sample. Log spend in notes/Project/ per repo convention.")
        return

    client = tinker_sampling.make_client(args.model)
    out, stats = await sample_split(
        client, tinker, tokenizer, model, rows, split=args.split, shape=args.shape,
        max_tokens=max_tokens, temperature=args.temperature, seed=args.seed, tries=args.tries)
    out_dir = REPLAY_DIR / families.slug(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.split}-{args.shape}.jsonl"
    out_path.write_text("".join(json.dumps(r) + "\n" for r in out))
    (out_dir / f"{args.split}-{args.shape}.stats.json").write_text(json.dumps(stats, indent=1))
    print(f"accepted {stats['accepted']}/{stats['total']} "
          f"(rejected outright: {stats['rejected_final']}, reasons: {stats['reasons']}) -> {out_path}")
    if stats["rejected_final"]:
        print("NOTE: rows rejected after all tries are MISSING from the file — "
              "the mix build will fail loudly if counts do not match; read the stats first.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--split", required=True, choices=SPLITS)
    parser.add_argument("--shape", required=True, choices=("off", "native"))
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--tries", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
