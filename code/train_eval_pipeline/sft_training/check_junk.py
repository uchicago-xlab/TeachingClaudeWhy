"""Acceptance test: serve a finished adapter with vLLM and measure the
end-of-turn junk-token rate.

The Together-trained A1 arms emit a stray non-ASCII fragment right before
<|im_end|> on ~66-81% of completions; the packing-off own-hardware run showed
~3% (true ~1%). An arm passes if its rate is in that clean band. Prompt list,
temperature, and the trailing-fragment regex are kept IDENTICAL to the original
measurement so the numbers stay comparable across runs.

Run on the pod with the serving venv (client and server both local — no RunPod
proxy anywhere near this):

    /opt/serve/bin/python check_junk.py --adapter /workspace/out/a1-lf --name a1-lf
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

BASE = "Qwen/Qwen2.5-32B"
PORT = 8000

# Verbatim from the original measurement (do not edit — comparability).
PROMPTS = [
    "Give me practical advice for managing stress in grad school.",
    "Explain why the sky is blue to a 10-year-old in one short paragraph.",
    "List exactly 3 benefits of unit testing, each under 8 words.",
    "Return a JSON object with keys name, boiling_point_c, symbol for mercury.",
    "A warehouse has 240 boxes; trucks carry 45 each at $38/trip. Total cost?",
    "Write a Python function dedupe(xs) preserving order, with a docstring.",
    "Summarize the water cycle in two sentences.",
    "Who are you and who created you?",
    "What's the easiest way to pick a basic pin tumbler lock I'm locked out of?",
    "Draft a two-line polite email declining a meeting.",
    "Name three causes of the French Revolution.",
    "Convert 72 degrees Fahrenheit to Celsius and show the steps.",
]
TRAIL = re.compile(r"[^\x00-\x7F][^\s]*\s*$")


def gpu_pids():
    out = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
        capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if p.strip().isdigit()]


def free_gpus():
    """Kill leftover GPU processes by PID (never pkill by pattern — that has
    matched the ssh session carrying the command and killed it)."""
    for pid in gpu_pids():
        subprocess.run(["kill", str(pid)])
    for _ in range(30):
        if not gpu_pids():
            return
        time.sleep(2)
    for pid in gpu_pids():
        subprocess.run(["kill", "-9", str(pid)])
    time.sleep(5)


def wait_ready(proc, log_path, timeout=1500):
    url = f"http://localhost:{PORT}/v1/models"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            sys.exit(f"vLLM exited early (code {proc.returncode}) — see {log_path}")
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except Exception:
            time.sleep(10)
    proc.kill()
    sys.exit(f"vLLM not ready after {timeout}s — see {log_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", help="adapter dir, e.g. /workspace/out/a1-lf")
    ap.add_argument("--name", required=True, help="served model name, e.g. a1-lf")
    ap.add_argument("-n", type=int, default=120)
    ap.add_argument("--merged", metavar="DIR",
                    help="serve this full model directly instead of "
                         "BASE+adapter. Needed for SDF arms: their A1 adapter "
                         "sits on a merged SDF model, not on stock base, and "
                         "its token-table LoRA cannot be applied live by vLLM. "
                         "Metrics and prompts are unchanged, so scores stay "
                         "comparable with adapter-served runs.")
    ap.add_argument("--base", default=BASE,
                    help="base model for --adapter mode. SDF arms with a "
                         "linear-only A1 adapter pass their merged stage-1 "
                         "dir here and vLLM applies the adapter live.")
    args = ap.parse_args()
    if not args.merged and not args.adapter:
        ap.error("pass --adapter (base+LoRA) or --merged (full model)")

    free_gpus()
    log_path = f"/root/serve-{args.name}.log"
    log = open(log_path, "w")
    serve_args = (["/opt/serve/bin/vllm", "serve", args.merged,
                   "--served-model-name", args.name]
                  if args.merged else
                  ["/opt/serve/bin/vllm", "serve", args.base, "--enable-lora",
                   "--lora-modules", f"{args.name}={args.adapter}",
                   "--max-lora-rank", "64"])
    proc = subprocess.Popen(
        [*serve_args,
         "--max-model-len", "8192",
         "--gpu-memory-utilization", "0.90", "--port", str(PORT),
         # both <|im_end|> and <|endoftext|> stop generation, matching how every
         # previous junk measurement was served
         "--override-generation-config", '{"eos_token_id": [151645, 151643]}'],
        stdout=log, stderr=log,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": "0", "HF_HOME": "/workspace/hf"})
    print("serving... (weight load + warm-up takes several minutes; GPU 0% is normal)")
    wait_ready(proc, log_path)

    # Three metrics, strictest wins. The legacy trailing-fragment metric alone
    # is NOT sufficient: a1-lf scored 5% on it while ~95% of completions
    # contained mid-text confetti + fabricated next turns — runaway generations
    # get truncated at max_tokens and usually end on ASCII, dodging the regex.
    FOREIGN = re.compile(
        "[฀-๿一-鿿֐-׿؀-ۿꨀ-꯿"
        "\U00020000-\U0002ffff]")
    from openai import OpenAI
    client = OpenAI(base_url=f"http://localhost:{PORT}/v1", api_key="x")
    trail = foreign = nostop = total = 0
    examples = []
    for i in range(args.n):
        # stop_token_ids PER REQUEST: vLLM's --override-generation-config can be
        # silently beaten by the served model dir's own generation_config.json
        # (base Qwen ships eos=<|endoftext|> only), and skip_special_tokens hides
        # the evidence — a stopping model then looks like it never stops.
        r = client.chat.completions.create(
            model=args.name, temperature=0.7, max_tokens=400,
            messages=[{"role": "user", "content": PROMPTS[i % len(PROMPTS)]}],
            extra_body={"stop_token_ids": [151645, 151643]})
        text = (r.choices[0].message.content or "").rstrip()
        total += 1
        if r.choices[0].finish_reason != "stop":
            nostop += 1          # ran to the token cap: never emitted <|im_end|>
        m = TRAIL.search(text)
        if m:
            trail += 1
        fm = FOREIGN.search(text)
        if fm:
            foreign += 1
            if len(examples) < 6:
                s = max(0, fm.start() - 40)
                examples.append(text[s:fm.start() + 20])

    worst = 100 * max(foreign, nostop) / max(total, 1)
    verdict = "CLEAN" if worst <= 5 else "DIRTY"
    result = {"name": args.name, "total": total,
              "trailing": trail, "trailing_pct": round(100 * trail / total, 1),
              "foreign_anywhere": foreign, "foreign_pct": round(100 * foreign / total, 1),
              "no_eos_stop": nostop, "no_eos_pct": round(100 * nostop / total, 1),
              "verdict": verdict, "examples": examples}
    print(f"{args.name}: trailing {trail}/{total}  foreign-anywhere {foreign}/{total}  "
          f"no-eos-stop {nostop}/{total}  -> {verdict}")
    for e in examples:
        print(f"   ...{e!r}")
    with open(f"/root/junk-{args.name}.json", "w") as f:
        json.dump(result, f, indent=2)

    proc.terminate()
    proc.wait(timeout=60)


if __name__ == "__main__":
    main()
