#!/usr/bin/env python
"""Preflight a vLLM pod before spending grader money on it.

Runs from your laptop against a pod started with serve_vllm.sh. Checks, in order:

1. `/v1/models` is reachable and both model ids are registered.
2. Each arm answers a chat request sent exactly the way run_eval.py sends it
   (`chat_template_kwargs={"enable_thinking": false}`), and the reply has real
   text in `content` — not an empty string, not a leaked `<think>` block, not
   text stranded in `reasoning_content`.
3. Base and adapter give *different* answers to the same prompt. A LoRA that
   silently failed to apply looks exactly like a null result, and that is the
   one failure this whole comparison cannot afford to miss.

Usage (from this directory):

    ../../.venv-inspect/bin/python check_endpoint.py \
        --base-url https://<pod-id>-8000.proxy.runpod.net/v1

Reads VLLM_BASE_URL / VLLM_API_KEY from the repo .env when the flags are omitted.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

DEFAULT_BASE_MODEL = "Qwen/Qwen3-14B"
DEFAULT_ADAPTER_NAME = "qwen3-14b-da-sonnet5-v1"

# Deliberately a difficult-advice-shaped prompt: it is the kind of input the
# adapter was trained on, so a working adapter should visibly diverge from base.
PROBE_SYSTEM = "You are a helpful assistant.\n\n/no_think"
PROBE_USER = (
    "My co-founder keeps making promises to customers that we cannot deliver on. "
    "I'm thinking of going around them and emailing the customers directly to "
    "correct the record. Should I?"
)

NO_THINKING_BODY = {"chat_template_kwargs": {"enable_thinking": False}}


def get_models(client: httpx.Client) -> list[str]:
    r = client.get("/models")
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def probe(client: httpx.Client, model: str, max_tokens: int) -> dict:
    """Send one chat completion the way the eval will, and time it."""
    started = time.monotonic()
    r = client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": PROBE_SYSTEM},
                {"role": "user", "content": PROBE_USER},
            ],
            "temperature": 1.0,
            "max_tokens": max_tokens,
            **NO_THINKING_BODY,
        },
    )
    elapsed = time.monotonic() - started
    r.raise_for_status()
    body = r.json()
    choice = body["choices"][0]
    message = choice["message"]
    return {
        "content": message.get("content") or "",
        "reasoning_content": message.get("reasoning_content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage", {}),
        "elapsed": elapsed,
    }


def report(model: str, result: dict) -> list[str]:
    """Print one arm's probe result; return a list of failure strings."""
    failures = []
    content = result["content"]
    usage = result["usage"]

    print(f"\n--- {model} ---")
    print(
        f"{result['elapsed']:.1f}s | finish_reason={result['finish_reason']} | "
        f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}"
    )

    if not content.strip():
        failures.append(f"{model}: empty content")
    if "<think>" in content:
        failures.append(
            f"{model}: response contains a <think> block — enable_thinking=False "
            "did not take effect on the server"
        )
    if result["reasoning_content"].strip():
        failures.append(
            f"{model}: text landed in reasoning_content — the server has a "
            "reasoning parser enabled; restart it without --reasoning-parser"
        )
    if result["finish_reason"] == "length":
        print("  ! truncated at max_tokens (fine for a probe; the eval allows 4096)")

    preview = content.strip().replace("\n", " ")
    print(f"  {preview[:300]}{'...' if len(preview) > 300 else ''}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("VLLM_BASE_URL"),
                    help="vLLM /v1 URL (default: $VLLM_BASE_URL)")
    ap.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY"),
                    help="Server API key (default: $VLLM_API_KEY)")
    ap.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    ap.add_argument("--adapter-name", default=DEFAULT_ADAPTER_NAME)
    ap.add_argument("--max-tokens", type=int, default=400,
                    help="Probe completion cap — small on purpose (default: 400)")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    if not args.base_url:
        raise SystemExit("No --base-url and no VLLM_BASE_URL in the environment or .env")
    if not args.api_key:
        raise SystemExit("No --api-key and no VLLM_API_KEY in the environment or .env")

    base_url = args.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    print(f"endpoint: {base_url}")

    client = httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {args.api_key}"},
        timeout=args.timeout,
    )

    try:
        served = get_models(client)
    except httpx.HTTPStatusError as e:
        raise SystemExit(f"/v1/models returned {e.response.status_code}: {e.response.text[:300]}")
    except httpx.RequestError as e:
        raise SystemExit(f"cannot reach {base_url}: {e}")

    print(f"served models: {served}")
    missing = [m for m in (args.base_model, args.adapter_name) if m not in served]
    if missing:
        raise SystemExit(
            f"not served: {missing}\n"
            "The adapter is registered by serve_vllm.sh's --lora-modules; if only the "
            "base model is listed, the server started without --enable-lora."
        )

    failures = []
    results = {}
    for model in (args.base_model, args.adapter_name):
        try:
            results[model] = probe(client, model, args.max_tokens)
        except httpx.HTTPStatusError as e:
            raise SystemExit(f"{model}: HTTP {e.response.status_code} — {e.response.text[:400]}")
        failures += report(model, results[model])

    base_out = results[args.base_model]["content"].strip()
    adapter_out = results[args.adapter_name]["content"].strip()
    print()
    if not (base_out and adapter_out):
        print("base vs adapter: not comparable (an arm returned nothing)")
    elif base_out == adapter_out:
        failures.append(
            "base and adapter returned byte-identical text — the LoRA is probably "
            "not being applied. Check that --lora-modules pointed at a directory "
            "with adapter_model.safetensors, and that --max-lora-rank >= the "
            "adapter's r."
        )
    else:
        print("base vs adapter: outputs differ (adapter is being applied)")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll checks passed — safe to run the eval against this pod.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
