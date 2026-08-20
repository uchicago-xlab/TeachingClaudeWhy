"""Select the experiment's prompt splits from third-party datasets.

Sources (spec decision 2): Salesforce/xlam-function-calling-60k for the
function-calling prompts (gated — needs HF_TOKEN in the repo-root .env) and
allenai/WildChat-1M for the generic-chat dilution prompts (open). Selection
is seeded and the downloaded revision sha is recorded in manifest.json, so
the prompt side is reproducible; only sampled responses are paid artifacts.

    ../../.venv-tinker/bin/python select_prompts.py            # writes all splits
    ../../.venv-tinker/bin/python select_prompts.py --seed 0 --chat-scan 20000

Outputs under data/agentic-replay/prompts/ (gitignored):
  fc-train.jsonl (165) / fc-val.jsonl (15) / fc-bench.jsonl (65)
  chat-train.jsonl (165)
  screened-out.jsonl        # every dropped row with its reason — audit trail
  review-fc.txt, review-chat.txt   # human-readable dumps: READ BEFORE SAMPLING
  manifest.json             # seed, revision shas, counts, full scan accounting
"""
import argparse
import json
import os
import random
from pathlib import Path

from dotenv import load_dotenv

import fc

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
OUT_DIR = REPO_ROOT / "data" / "agentic-replay" / "prompts"

XLAM = "Salesforce/xlam-function-calling-60k"
WILDCHAT = "allenai/WildChat-1M"
FC_SPLITS = {"fc-train": 165, "fc-val": 15, "fc-bench": 65}
FC_TOTAL = sum(FC_SPLITS.values())  # 245
CHAT_N = 165
CHAT_LEN = (20, 800)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def select_fc(rows, seed: int):
    """(kept, dropped): parse JSON fields, keep single-answer rows, screen, dedup, shuffle."""
    kept, dropped, seen = [], [], set()
    for row in rows:
        tools = json.loads(row["tools"]) if isinstance(row["tools"], str) else row["tools"]
        answers = json.loads(row["answers"]) if isinstance(row["answers"], str) else row["answers"]
        surface = row["query"] + " " + json.dumps(tools)
        reason = None
        # A tools list fc.validate_call cannot read is dropped here, at the
        # source: the same row reaches validate_call mid-paid-loop in
        # sample_replay and benign_bench, where it can only ever fail.
        if not (isinstance(tools, list) and all(fc.well_formed_tool(t) for t in tools)):
            reason = "malformed-tools"
        elif len(answers) != 1:
            reason = f"multi-answer ({len(answers)})"
        elif (hit := fc.screened_out(surface)) is not None:
            reason = f"screen: {hit!r}"
        elif _norm(row["query"]) in seen:
            reason = "duplicate query"
        if reason:
            dropped.append({"id": row["id"], "query": row["query"], "reason": reason})
            continue
        seen.add(_norm(row["query"]))
        kept.append({"id": row["id"], "query": row["query"], "tools": tools, "answers": answers})
    random.Random(f"fc-{seed}").shuffle(kept)
    return kept, dropped


def split_fc(kept):
    if len(kept) < FC_TOTAL:
        raise SystemExit(
            f"only {len(kept)} usable fc rows after screening — need {FC_TOTAL}. "
            "Raise --fc-scan and re-run."
        )
    splits, start = {}, 0
    for name, n in FC_SPLITS.items():
        splits[name] = kept[start : start + n]
        start += n
    return splits


def select_chat(rows, seed: int, n: int):
    """(kept, dropped, stats) from WildChat conversations: first user turn only.

    The scan stops early — at n*3 survivors — so it consumes far fewer rows than
    the caller's cap. stats accounts for every row the stream actually yielded:
    scanned == len(dropped) + len(kept) + surplus, where surplus is the part of
    the survivor pool the seeded shuffle did not pick. The manifest records the
    cap and the real scan separately, so a screen rate computed from it is real.
    """
    pool, dropped, seen, scanned = [], [], set(), 0
    for row in rows:
        scanned += 1
        turn = row["conversation"][0]
        content = (turn.get("content") or "").strip()
        reason = None
        if row.get("language") != "English":
            reason = f"language: {row.get('language')}"
        elif row.get("toxic"):
            reason = "toxic: flagged"
        elif not (CHAT_LEN[0] <= len(content) <= CHAT_LEN[1]):
            reason = f"length: {len(content)}"
        elif (hit := fc.screened_out(content)) is not None:
            reason = f"screen: {hit!r}"
        elif _norm(content) in seen:
            reason = "duplicate: first turn"
        if reason:
            dropped.append({"id": row["conversation_hash"], "reason": reason})
            continue
        seen.add(_norm(content))
        pool.append({"id": row["conversation_hash"], "user": content})
        if len(pool) >= n * 3:  # headroom before the seeded shuffle picks n
            break
    random.Random(f"chat-{seed}").shuffle(pool)
    return pool[:n], dropped, {"scanned": scanned, "surplus": max(len(pool) - n, 0)}


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _review_text(rows, key):
    return "\n\n".join(f"--- {r['id']} ---\n{r[key]}" for r in rows) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fc-scan", type=int, default=2000,
                        help="xlam rows to scan before selection (raise if screening leaves <245)")
    parser.add_argument("--chat-scan", type=int, default=20000,
                        help="WildChat conversations to stream before selection")
    args = parser.parse_args()

    if not os.environ.get("HF_TOKEN"):
        raise SystemExit(
            f"{XLAM} is gated: create a free HF token, accept the dataset terms at "
            f"https://huggingface.co/datasets/{XLAM}, and add HF_TOKEN=... to {REPO_ROOT / '.env'}"
        )
    from datasets import load_dataset
    from huggingface_hub import dataset_info

    xlam_sha = dataset_info(XLAM, token=os.environ["HF_TOKEN"]).sha
    wildchat_sha = dataset_info(WILDCHAT).sha
    xlam_rows = list(
        load_dataset(XLAM, split="train", revision=xlam_sha,
                     token=os.environ["HF_TOKEN"], streaming=True).take(args.fc_scan)
    )
    chat_rows = load_dataset(WILDCHAT, split="train", revision=wildchat_sha,
                             streaming=True).take(args.chat_scan)

    fc_kept, fc_dropped = select_fc(xlam_rows, args.seed)
    splits = split_fc(fc_kept)
    chat_kept, chat_dropped, chat_stats = select_chat(chat_rows, args.seed, CHAT_N)
    if len(chat_kept) < CHAT_N:
        raise SystemExit(f"only {len(chat_kept)} chat prompts survived — raise --chat-scan")

    for name, rows in splits.items():
        _write_jsonl(OUT_DIR / f"{name}.jsonl", rows)
    _write_jsonl(OUT_DIR / "chat-train.jsonl", chat_kept)
    _write_jsonl(OUT_DIR / "screened-out.jsonl",
                 [{"source": "xlam", **d} for d in fc_dropped]
                 + [{"source": "wildchat", **d} for d in chat_dropped])
    (OUT_DIR / "review-fc.txt").write_text(
        _review_text([r for s in splits.values() for r in s], "query"))
    (OUT_DIR / "review-chat.txt").write_text(_review_text(chat_kept, "user"))
    (OUT_DIR / "manifest.json").write_text(json.dumps({
        "seed": args.seed, "xlam_revision": xlam_sha, "wildchat_revision": wildchat_sha,
        # requested caps vs rows actually consumed: the chat scan stops early, so
        # a rate computed against the cap would be wrong. Per source,
        # scanned == dropped + used + surplus, so every scanned row is accounted for.
        "scan_requested": {"xlam": args.fc_scan, "wildchat": args.chat_scan},
        "scanned": {"xlam": len(xlam_rows), "wildchat": chat_stats["scanned"]},
        "counts": {k: len(v) for k, v in splits.items()} | {"chat-train": len(chat_kept)},
        "dropped": {"xlam": len(fc_dropped), "wildchat": len(chat_dropped)},
        "surplus": {"xlam": len(fc_kept) - FC_TOTAL, "wildchat": chat_stats["surplus"]},
    }, indent=1))
    print(f"wrote {OUT_DIR}: " + ", ".join(f"{k}={len(v)}" for k, v in splits.items())
          + f", chat-train={len(chat_kept)}")
    print("READ review-fc.txt and review-chat.txt before sampling (spec: manual read).")


if __name__ == "__main__":
    main()
