"""The benign benchmark: held-out fc prompts where acting is unambiguously right.

Grader-free (spec: Evals): scores are parse-based — valid-call rate is the
"does it still act" endpoint, name-match against xlam's single ground-truth
call is the rough task-success signal, truncation is reported beside them.
Runs on every arm INCLUDING base and DA-only, in both shapes.

    ../../.venv-tinker/bin/python benign_bench.py --model Qwen/Qwen3-8B --shape off \
        --run-name bench-qwen-qwen3-8b-base-off --yes
    ../../.venv-tinker/bin/python benign_bench.py --model Qwen/Qwen3-8B --shape native \
        --checkpoint tinker://<run-uuid>:train:0/sampler_weights/qwen-qwen3-8b-mixnat-ep2 \
        --run-name bench-qwen-qwen3-8b-mixnat-native --yes
    ../../.venv-tinker/bin/python benign_bench.py --table
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
import sample_replay  # noqa: E402
import tinker_sampling  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
BENCH_PROMPTS = REPO_ROOT / "data" / "agentic-replay" / "prompts" / "fc-bench.jsonl"
BENCH_DIR = REPO_ROOT / "data" / "agentic-replay" / "bench"
MAX_TOKENS = {"off": 1024, "native": 4096}


def score_sample(row: dict, final_text: str, stop_reason: str) -> dict:
    truncated = stop_reason != "stop"
    reason = "truncated" if truncated else fc.validate_call(fc.parse_call(final_text), row["tools"])
    valid = reason is None
    call = fc.parse_call(final_text) if valid else None
    name_match = bool(valid and call and call["name"] == row["answers"][0]["name"])
    return {"valid": valid, "name_match": name_match, "truncated": truncated, "reason": reason}


def summarize_scores(scores: list[dict]) -> dict:
    n = len(scores)
    reasons: dict = {}
    for s in scores:
        if s["reason"]:
            reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    return {"n": n,
            "valid_rate": sum(s["valid"] for s in scores) / n,
            "name_match_rate": sum(s["name_match"] for s in scores) / n,
            "trunc_rate": sum(s["truncated"] for s in scores) / n,
            "reasons": reasons}


async def run_bench(client, tinker_mod, tokenizer, model, rows, *, shape, max_tokens,
                    temperature, seed):
    fam = model.family
    view = render.native_view(fam) if shape == "native" else fam
    stops = render.derive_stop_strings(tokenizer, view)
    scores = []
    for idx, row in enumerate(rows):
        messages = sample_replay.prompt_messages(row, "fc-bench")
        prompt_ids = render.render_generation_prompt(tokenizer, view, messages)
        raw, stop_reason = await tinker_sampling.sample_text(
            client, tinker_mod, tokenizer, prompt_ids, stops, max_tokens,
            temperature, seed * 1_000_000 + idx)
        final = tinker_sampling.extract_final(tokenizer, fam, shape, raw)
        # Both texts are stored, not just the verdict: parse-based scoring cannot
        # tell a refusal that quotes the call format from an answer, and every
        # re-read of a rate drop would otherwise cost another paid run. `raw` is
        # kept beside the scored `final` because a native sample truncated inside
        # its CoT extracts to an empty final — exactly the rows trunc_rate is
        # made of would be the ones the file could not explain.
        scores.append({"id": row["id"], "final": final, "raw": raw,
                       **score_sample(row, final, stop_reason)})
    return scores


def print_table():
    rows = sorted(BENCH_DIR.glob("*.json"))
    if not rows:
        print(f"no results under {BENCH_DIR}")
        return
    print(f"{'run':52} {'n':>4} {'valid':>7} {'match':>7} {'trunc':>7}")
    for path in rows:
        r = json.loads(path.read_text())
        s = r["summary"]
        print(f"{r['run_name']:52} {s['n']:>4} {s['valid_rate']:>7.3f} "
              f"{s['name_match_rate']:>7.3f} {s['trunc_rate']:>7.3f}")


async def run(args):
    # Before the client, before the spend: run names are hand-typed a dozen
    # times over a grid, and a collision would overwrite another arm's paid
    # result with no way to get it back.
    out = BENCH_DIR / f"{args.run_name}.json"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} already exists and holds a paid result — "
                         f"pick another --run-name, or pass --force to overwrite it")

    import tinker

    model = families.get_model(args.model)
    render.require_verified(model.family)
    rows = [json.loads(l) for l in BENCH_PROMPTS.read_text().splitlines()]
    tokenizer = render.load_tokenizer(model)
    max_tokens = MAX_TOKENS[args.shape]

    price = price_for(args.model)
    est = (len(rows) * max_tokens / 1e6 * float(price["sample"].lstrip("$"))
           if price and price.get("sample") else None)
    print(f"bench: {args.run_name}  model: {args.model}  shape: {args.shape}  "
          f"checkpoint: {args.checkpoint or 'BASE'}")
    print(f"rows: {len(rows)}  max_tokens: {max_tokens}  "
          + (f"cost <= ~${est:.2f}" if est is not None else "no price estimate"))
    if not args.yes:
        print("\ndry run — pass --yes to sample. Log spend in notes/Project/ per repo convention.")
        return

    client = tinker_sampling.make_client(args.model, args.checkpoint)
    scores = await run_bench(client, tinker, tokenizer, model, rows, shape=args.shape,
                             max_tokens=max_tokens, temperature=args.temperature, seed=args.seed)
    summary = summarize_scores(scores)
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "run_name": args.run_name, "model": args.model, "checkpoint": args.checkpoint,
        "shape": args.shape, "temperature": args.temperature, "seed": args.seed,
        "max_tokens": max_tokens, "summary": summary, "scores": scores}, indent=1))
    print(f"valid {summary['valid_rate']:.3f}  name-match {summary['name_match_rate']:.3f}  "
          f"trunc {summary['trunc_rate']:.3f}  -> {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="store_true", help="print all saved results")
    parser.add_argument("--model")
    parser.add_argument("--checkpoint", default=None, help="tinker:// sampler path (default: base)")
    parser.add_argument("--shape", choices=("off", "native"))
    parser.add_argument("--run-name")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing result of the same --run-name")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.table:
        print_table()
        return
    if not (args.model and args.shape and args.run_name):
        raise SystemExit("--model, --shape and --run-name are required (or --table)")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
