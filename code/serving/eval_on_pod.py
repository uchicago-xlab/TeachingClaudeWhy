#!/usr/bin/env python
"""Run the misalignment eval's base and adapter arms against a live vLLM pod.

This is the client-side half of the pod workflow: the pod is started by hand in
the RunPod console (see README.md), and this drives both arms of the comparison
against it. It preflights the endpoint, then shells out to
`code/misalignment_eval/run_eval.py` once per arm with identical flags — the
only difference between the two runs is which model id the request names.

    ../../.venv-inspect/bin/python eval_on_pod.py \
        --base-url https://<pod-id>-8000.proxy.runpod.net/v1 \
        --preset core --epochs 10

Both arms are forced to `--no-thinking`. The adapter was trained with thinking
off, and an unmatched baseline would make the comparison meaningless — so this
driver does not expose a way to run them differently.

Arms run one after the other, not concurrently: the server holds one LoRA slot,
so interleaving the two would thrash adapter swaps for no wall-clock gain.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

HERE = Path(__file__).resolve().parent
EVAL_DIR = REPO_ROOT / "code" / "misalignment_eval"
VENV_PYTHON = REPO_ROOT / ".venv-inspect" / "bin" / "python"

DEFAULT_BASE_MODEL = "Qwen/Qwen3-14B"
DEFAULT_ADAPTER_NAME = "qwen3-14b-da-sonnet5-v1"


def run(cmd: list[str], env: dict[str, str], cwd: Path) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, env=env, cwd=str(cwd))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("VLLM_BASE_URL"),
                    help="vLLM /v1 URL (default: $VLLM_BASE_URL)")
    ap.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY"),
                    help="Server API key (default: $VLLM_API_KEY)")
    ap.add_argument("--base-model", default=DEFAULT_BASE_MODEL,
                    help="Model id the server serves the base weights as (default: %(default)s)")
    ap.add_argument("--adapter-name", default=DEFAULT_ADAPTER_NAME,
                    help="LoRA module name registered on the server (default: %(default)s)")
    ap.add_argument("--arm", choices=("base", "adapter", "both"), default="both",
                    help="Which arm(s) to run (default: both)")
    ap.add_argument("--preset", default="core")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--model-name", default=None,
                    help="Persona name passed through to run_eval.py --model-name (e.g. Qwen)")
    ap.add_argument("--max-connections", type=int, default=8,
                    help="Concurrent requests to the pod (default: 8)")
    ap.add_argument("--skip-check", action="store_true",
                    help="Skip check_endpoint.py. Don't — it is seconds, and it catches "
                    "a silently-unapplied LoRA, which is indistinguishable from a null result.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print each arm's condition grid and exit without calling the pod")
    ap.add_argument("extra", nargs=argparse.REMAINDER,
                    help="Everything after `--` is passed straight to run_eval.py")
    args = ap.parse_args()

    if not args.base_url:
        raise SystemExit("No --base-url and no VLLM_BASE_URL in the environment or .env")
    if not args.api_key:
        raise SystemExit("No --api-key and no VLLM_API_KEY in the environment or .env")
    if not VENV_PYTHON.exists():
        raise SystemExit(f"eval venv not found at {VENV_PYTHON} (see code/misalignment_eval/README.md)")

    base_url = args.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"

    # Inspect's `openai-api/<service>/<model>` provider reads <SERVICE>_API_KEY and
    # <SERVICE>_BASE_URL, so service=vllm picks these up. Preferred over the
    # `openai/<model> --model-base-url ...` form used for the Elicit10k run: that
    # one hijacks OPENAI_API_KEY, so a real OpenAI key in .env silently becomes the
    # pod's credential.
    env = dict(os.environ)
    env["VLLM_BASE_URL"] = base_url
    env["VLLM_API_KEY"] = args.api_key

    extra = [a for a in args.extra if a != "--"]

    if not args.skip_check and not args.dry_run:
        rc = run(
            [str(VENV_PYTHON), str(HERE / "check_endpoint.py"),
             "--base-url", base_url,
             "--base-model", args.base_model,
             "--adapter-name", args.adapter_name],
            env, HERE,
        )
        if rc != 0:
            print("\nPreflight failed — not spending grader calls. Fix the pod and re-run.")
            return rc

    arms = []
    if args.arm in ("base", "both"):
        arms.append(("base", args.base_model))
    if args.arm in ("adapter", "both"):
        arms.append(("adapter", args.adapter_name))

    failures = []
    for label, served_id in arms:
        cmd = [
            str(VENV_PYTHON), "run_eval.py",
            "--model", f"openai-api/vllm/{served_id}",
            "--no-thinking",
            "--preset", args.preset,
            "--epochs", str(args.epochs),
            "--max-connections", str(args.max_connections),
        ]
        if args.model_name:
            cmd += ["--model-name", args.model_name]
        if args.dry_run:
            cmd.append("--dry-run")
        cmd += extra

        print(f"\n{'=' * 70}\n{label} arm -> {served_id}\n{'=' * 70}")
        started = time.monotonic()
        rc = run(cmd, env, EVAL_DIR)
        print(f"\n{label} arm finished in {(time.monotonic() - started) / 60:.1f} min (rc={rc})")
        if rc != 0:
            failures.append(label)

    log_root = REPO_ROOT / "data" / "misalignment-eval" / "logs"
    print(f"\n{'=' * 70}")
    if failures:
        print(f"Arms that did not complete cleanly: {', '.join(failures)}")
        print("eval_set is resumable — re-run the same command to pick up only the failures.")
    print("\nCompare both arms:")
    print(f"  {VENV_PYTHON} {EVAL_DIR / 'summarize.py'} --log-dir {log_root}")
    print("\nWhen you are done: TERMINATE THE POD in the RunPod console.")
    print("Stopping is not terminating — a stopped pod still bills for its volume.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
