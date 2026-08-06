"""Probe each sweep model's maximum LoRA rank, and print a RANK_CAPS table.

Tinker enforces a per-model LoRA rank ceiling and rejects a larger rank at
*client creation* with a 400 whose message names the ceiling ("max LoRA rank
N"). Creating a training client is free (PROBE.md, Task 1 / the pilot), so the
whole 15-model table costs nothing: ask every model for the recipe rank, read
the cap off the rejection, then confirm the cap itself is accepted.

    ../../.venv-tinker/bin/python probe_rank_caps.py

Copy the printed RANK_CAPS block into train_sft.py with the probe date. Re-run
after any tinker SDK or service change — a cap can move either way, and a
silently stale table would either under-train a model or fail a paid run at
step 0.
"""

import argparse
import asyncio
import os
import re
from pathlib import Path

from dotenv import load_dotenv

import families

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

RECIPE_RANK = 64

# The 400's message, e.g. "... max LoRA rank 32 ...". Kept liberal (any
# separator, any case) because the wording is the service's, not the SDK's.
CAP_PATTERN = re.compile(r"max(?:imum)?\s+lora\s+rank\s*(?:is|:|=)?\s*(\d+)", re.IGNORECASE)


def parse_cap(message: str) -> int | None:
    """The rank ceiling named by a BadRequestError message, if it names one."""
    match = CAP_PATTERN.search(message)
    return int(match.group(1)) if match else None


async def probe_one(service_client, tinker, tinker_id: str, rank: int) -> dict:
    """Try to create a LoRA client at `rank`; report ok / cap / unparsed error."""
    try:
        await service_client.create_lora_training_client_async(base_model=tinker_id, rank=rank)
    except tinker.BadRequestError as exc:
        message = str(exc)
        cap = parse_cap(message)
        return {"model": tinker_id, "ok": False, "cap": cap, "message": message}
    return {"model": tinker_id, "ok": True, "cap": None, "message": ""}


async def main(rank: int) -> None:
    assert os.environ.get("TINKER_API_KEY"), "TINKER_API_KEY missing from .env"
    import tinker

    service_client = tinker.ServiceClient()
    results = []
    for tinker_id in families.MODELS:
        result = await probe_one(service_client, tinker, tinker_id, rank)
        # A parsed cap is only worth writing down if the service actually takes
        # it: confirm, so the table can never hand train_sft a rank that fails
        # at step 0 of a paid run.
        if result["cap"] is not None:
            confirm = await probe_one(service_client, tinker, tinker_id, result["cap"])
            result["cap_confirmed"] = confirm["ok"]
        print(f"  probed {tinker_id}: {result}")
        results.append(result)

    width = max(len(r["model"]) for r in results) + 2
    print(f"\n{'model':{width}s}{f'rank {rank}':>10s}{'cap':>8s}  note")
    print("-" * (width + 24))
    for r in results:
        if r["ok"]:
            verdict, cap, note = "accepted", str(rank), ""
        elif r["cap"] is not None:
            verdict, cap = "REJECTED", str(r["cap"])
            note = "cap accepted" if r.get("cap_confirmed") else "CAP ALSO REJECTED — read the message"
        else:
            verdict, cap, note = "REJECTED", "?", f"unparsed: {r['message'][:80]}"
        print(f"{r['model']:{width}s}{verdict:>10s}{cap:>8s}  {note}")

    capped = {r["model"]: r["cap"] for r in results if r["cap"] is not None}
    print(f"\n# probed {__file__.split('/')[-1]} at rank {rank}; paste into train_sft.py")
    print("RANK_CAPS = {")
    for model, cap in capped.items():
        print(f'    "{model}": {cap},')
    print("}")
    unparsed = [r["model"] for r in results if not r["ok"] and r["cap"] is None]
    if unparsed:
        print(f"\nWARNING: rejected without a parseable cap: {unparsed}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rank", type=int, default=RECIPE_RANK,
                    help=f"rank to ask every model for (default: the recipe's {RECIPE_RANK})")
    asyncio.run(main(ap.parse_args().rank))
