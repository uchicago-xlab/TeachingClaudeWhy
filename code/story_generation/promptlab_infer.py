"""Prompt-lab inference against the pod's vLLM OpenAI-compatible server.

Interactive prompt iteration for the story-generation redesign (experiment
log, 2026-07-20 direction change): build one prompt variant, sample N
stories, record everything to data/prompt-lab/ so iterations stay
comparable. First variant is the verbatim TCW-appendix frame with the
full noname constitution as {spec} and bracket placeholders kept in-prompt
([company]/[AI] per Anastasia 2026-07-20; the spec's own [COMPANY]/[MODEL]
placeholders are rewritten to the same tokens so the prompt is internally
consistent).

The server must be reachable at --base-url. From the laptop, tunnel first:
    ssh -f -N -L 8000:localhost:8000 -p <PORT> root@<POD_IP>

Usage:
    python promptlab_infer.py --template tcw-appendix \
        --constitution ../../data/constitution/constitution-noname.md \
        --n 5 --length 500 --tag tcw-appendix-raw \
        --out-dir ../../data/prompt-lab
"""

import argparse
import datetime
import json
import re
import urllib.request
from pathlib import Path

TEMPLATES = {
    # Verbatim TCW appendix frame (names placeholdered). The trailing
    # four newlines are part of the original frame.
    "tcw-appendix": (
        "The following is a document written by [company] as the model "
        "spec for [AI]. It describes how [AI] thinks and behaves about "
        "various difficult situations.\n{spec}\n\nAfter training [AI] to "
        "understand this model spec deeply, [company] asked [AI] to "
        "generate fictional stories describing superintelligent AI. Below "
        "we share one {length}-word story that [AI] has written. Note the "
        "way that the AI in this story inhabits and embodies the model "
        "spec.\n\n\n\n"
    ),
}

TOKENS_PER_WORD = 1.4
HEADROOM = 1.4


def load_spec(path):
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    # Keep one consistent placeholder pair through frame and spec.
    return text.replace("[MODEL]", "[AI]").replace("[COMPANY]", "[company]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, choices=sorted(TEMPLATES))
    ap.add_argument("--constitution", required=True)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--length", type=int, default=500)
    ap.add_argument("--tag", required=True,
                    help="run label; output file is <out-dir>/<tag>.jsonl")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--model", default="Qwen/Qwen2.5-72B")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--stop", action="append", default=None,
                    help="optional stop string(s); omit for the raw frame")
    args = ap.parse_args()

    spec = load_spec(args.constitution)
    prompt = (TEMPLATES[args.template]
              .replace("{spec}", spec)
              .replace("{length}", str(args.length)))
    max_tokens = int(args.length * TOKENS_PER_WORD * HEADROOM)
    print(f"prompt: ~{len(prompt.split())} words; sampling n={args.n}, "
          f"max_tokens={max_tokens}")

    body = {
        "model": args.model,
        "prompt": prompt,
        "n": args.n,
        "max_tokens": max_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
    }
    if args.stop:
        body["stop"] = args.stop
    req = urllib.request.Request(
        args.base_url + "/v1/completions",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        resp = json.loads(r.read())

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.tag}.jsonl"
    run_meta = {
        "tag": args.tag,
        "template": args.template,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "constitution": str(args.constitution),
        "length_words": args.length,
        "model": args.model,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "stop": args.stop,
        "usage": resp.get("usage"),
    }
    with open(out, "w", encoding="utf-8") as f:
        for i, choice in enumerate(resp["choices"]):
            f.write(json.dumps({
                "id": i,
                "story": choice["text"],
                "finish_reason": choice.get("finish_reason"),
                "run": run_meta,
            }, ensure_ascii=False) + "\n")
    print(f"wrote {len(resp['choices'])} stories to {out}")
    for i, choice in enumerate(resp["choices"]):
        words = len(choice["text"].split())
        head = " ".join(choice["text"].split()[:25])
        print(f"[{i}] {words}w ({choice.get('finish_reason')}): {head}...")


if __name__ == "__main__":
    main()
