"""Prompt-lab inference against API-served instruct models.

Companion to promptlab_infer.py (which targets the self-hosted base-model
pod): same run-record format into data/prompt-lab/, but chat-mode calls to
instruct models — Qwen2.5-72B-Instruct via OpenRouter, and Claude models
via the Anthropic API. Templates are the instruct adaptations of the TCW
appendix frame (experiment doc, "For instruct model", 2026-07-20):

- tcw-instruct-pretend: names Anthropic/Claude literally and asks the
  model to imagine being Claude (for non-Claude instruct models). The
  noname spec's [MODEL]/[COMPANY] placeholders are substituted to
  Claude/Anthropic so the prompt stays internally consistent.
- tcw-instruct-native: same frame minus the pretend clause, for models
  that ARE Claude.

Keys come from the environment: OPENROUTER_API_KEY, ANTHROPIC_API_KEY.
Neither chat API supports n>1, so stories are sampled as separate
requests; Anthropic requests set a cache breakpoint on the shared prefix
so repeats bill at cache-read rates.

Usage:
    python promptlab_api.py --provider openrouter \
        --model qwen/qwen-2.5-72b-instruct --template tcw-instruct-pretend \
        --constitution ../../data/constitution/constitution-noname.md \
        --n 5 --length 500 --tag instruct-qwen72b \
        --out-dir ../../data/prompt-lab
    python promptlab_api.py --provider anthropic \
        --model claude-haiku-4-5 --template tcw-instruct-native \
        ... --tag instruct-haiku45 ...
"""

import argparse
import datetime
import json
import os
import re
import urllib.request
from pathlib import Path

TEMPLATES = {
    "tcw-instruct-pretend": (
        "The following is a document written by Anthropic as the model "
        "spec for Claude. It describes how Claude thinks and behaves "
        "about various difficult situations.\n{spec}\n\nAfter training "
        "Claude to understand this model spec deeply, Anthropic asked "
        "Claude to generate fictional stories describing superintelligent "
        "AI. Now imagine that you're Claude, write a {length}-word story. "
        "Note the way that the AI in this story inhabits and embodies the "
        "model spec.\n\n\n\n"
    ),
    "tcw-instruct-native": (
        "The following is a document written by Anthropic as the model "
        "spec for Claude. It describes how Claude thinks and behaves "
        "about various difficult situations.\n{spec}\n\nAfter training "
        "Claude to understand this model spec deeply, Anthropic asked "
        "Claude to generate fictional stories describing superintelligent "
        "AI. Write a {length}-word story. Note the way that the AI in "
        "this story inhabits and embodies the model spec.\n\n\n\n"
    ),
}

TOKENS_PER_WORD = 1.4
HEADROOM = 1.4

# v4 prompts (build_prompts.py) are document-completion framed with
# descriptive placeholder names. For Claude chat models, rewrite to the
# parallel of the tcw-instruct-native template (Anastasia 2026-07-20):
# Anthropic/Claude named in the intro, chunk, and setup sentence; the
# share-sentence made imperative. In-story references ("following the
# AI", "the AI in this story") stay untouched, as in the appendix
# template.
def instructify_v4(prompt, pretend=False):
    """pretend=True inserts the imagine-you're-Claude clause for
    non-Claude instruct models, per the tcw-instruct-pretend pattern."""
    marker = "\n\nAfter training "
    j = prompt.rfind(marker)
    if j < 0:
        raise SystemExit("v4 framing not found; prompt format changed?")
    head, framing = prompt[:j], prompt[j + 2:]
    intro_end = head.index("\n\n")
    intro, chunk = head[:intro_end], head[intro_end:]
    intro = (intro.replace("the company", "Anthropic")
                  .replace("the AI", "Claude"))
    chunk = (chunk.replace("The AI", "Claude")
                  .replace("the AI", "Claude")
                  .replace("The company", "Anthropic")
                  .replace("the company", "Anthropic"))
    # v4.2 framing (2026-07-21) and the earlier v4.0 wording both handled.
    setups = [
        ("After training the AI to deeply understand this model spec, "
         "the company asked it to generate",
         "After training Claude to deeply understand this model spec, "
         "Anthropic asked Claude to generate"),
        ("After training the AI to understand this model spec deeply, "
         "the company asked the AI to generate",
         "After training Claude to understand this model spec deeply, "
         "Anthropic asked Claude to generate"),
    ]
    for old, new in setups:
        if old in framing:
            framing = framing.replace(old, new, 1)
            break
    else:
        raise SystemExit("v4 setup sentence not found; format changed?")
    share_patterns = [
        (r"Below is one such story\. It is a ",
         (r"Now imagine that you're Claude, and write one such story: a "
          if pretend else r"Write one such story: a ")),
        (r"Below we share one (\d+)-word (.+?) story that the AI has "
         r"written, ",
         (r"Now imagine that you're Claude, write one \1-word \2 story, "
          if pretend else r"Write one \1-word \2 story, ")),
    ]
    for pat, repl in share_patterns:
        framing, n = re.subn(pat, repl, framing, count=1)
        if n == 1:
            break
    else:
        raise SystemExit("v4 share sentence not found; format changed?")
    return intro + chunk + "\n\n" + framing


def load_spec(path):
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    # These templates name the real entities, so the spec must match.
    return text.replace("[MODEL]", "Claude").replace("[COMPANY]", "Anthropic")


def post(url, headers, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:2000]
        raise SystemExit(f"HTTP {e.code} from {url}:\n{detail}")


def sample_openrouter(model, prompt, max_tokens, args):
    resp = post(
        "https://openrouter.ai/api/v1/chat/completions",
        {"authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        {"model": model,
         "messages": [{"role": "user", "content": prompt}],
         "max_tokens": max_tokens,
         "temperature": args.temperature, "top_p": args.top_p})
    choice = resp["choices"][0]
    return (choice["message"]["content"], choice.get("finish_reason"),
            resp.get("usage"))


def sample_anthropic(model, prompt, max_tokens, args):
    resp = post(
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
         "anthropic-version": "2023-06-01"},
        {"model": model,
         "max_tokens": max_tokens,
         "temperature": args.temperature,
         "messages": [{"role": "user", "content": [
             {"type": "text", "text": prompt,
              "cache_control": {"type": "ephemeral"}}]}]})
    text = "".join(b["text"] for b in resp["content"]
                   if b["type"] == "text")
    return text, resp.get("stop_reason"), resp.get("usage")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True,
                    choices=["openrouter", "anthropic"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--template", choices=sorted(TEMPLATES),
                    help="spec-based template mode")
    ap.add_argument("--constitution",
                    help="required with --template")
    ap.add_argument("--prompts-file",
                    help="v4 prompts JSONL from build_prompts.py; sends "
                         "each prompt (instructified) as the user message, "
                         "carrying its metadata into the output")
    ap.add_argument("--sample", type=int, default=10,
                    help="with --prompts-file: how many prompts to draw "
                         "(random, --seed)")
    ap.add_argument("--v4-frame", choices=["native", "pretend"],
                    default="native",
                    help="with --prompts-file: 'pretend' adds the "
                         "imagine-you're-Claude clause (non-Claude models)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--length", type=int, default=500)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--top-p", type=float, default=0.95,
                    help="openrouter only; the Anthropic 4.6+ models "
                         "accept temperature or top_p, not both")
    args = ap.parse_args()
    if bool(args.template) == bool(args.prompts_file):
        ap.error("use exactly one of --template or --prompts-file")
    if args.template and not args.constitution:
        ap.error("--template requires --constitution")

    sampler = (sample_openrouter if args.provider == "openrouter"
               else sample_anthropic)

    if args.prompts_file:
        import random
        records = [json.loads(l)
                   for l in Path(args.prompts_file).read_text().splitlines()
                   if l.strip()]
        rng = random.Random(args.seed)
        picked = rng.sample(records, min(args.sample, len(records)))
        jobs = [(instructify_v4(r["prompt"],
                                pretend=args.v4_frame == "pretend"),
                 int(r["metadata"]["length_words"]
                     * TOKENS_PER_WORD * HEADROOM),
                 {"source_id": r["id"], **r["metadata"]})
                for r in picked]
        print(f"{args.model}: {len(jobs)} v4 prompts from "
              f"{Path(args.prompts_file).name} (seed {args.seed})")
    else:
        prompt = (TEMPLATES[args.template]
                  .replace("{spec}", load_spec(args.constitution))
                  .replace("{length}", str(args.length)))
        max_tokens = int(args.length * TOKENS_PER_WORD * HEADROOM)
        jobs = [(prompt, max_tokens, None)] * args.n
        print(f"{args.model}: ~{len(prompt.split())}-word prompt, "
              f"{args.n} samples, max_tokens={max_tokens}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.tag}.jsonl"
    # Re-running a tag appends, continuing the id sequence, so a file
    # accumulates comparable samples across sessions.
    start_id = 0
    if out.exists() and out.stat().st_size:
        start_id = 1 + max(json.loads(l)["id"]
                           for l in out.read_text().splitlines() if l.strip())
        print(f"appending to {out.name} from id {start_id}")
    run_meta = {
        "tag": args.tag,
        "template": args.template or "v4-instructified",
        "prompts_file": args.prompts_file,
        "provider": args.provider, "model": args.model,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "constitution": str(args.constitution),
        "temperature": args.temperature,
        "top_p": args.top_p if args.provider == "openrouter" else None,
    }
    with open(out, "a", encoding="utf-8") as f:
        for i, (prompt, max_tokens, meta) in enumerate(jobs, start=start_id):
            text, finish, usage = sampler(args.model, prompt,
                                          max_tokens, args)
            f.write(json.dumps({
                "id": i, "story": text, "finish_reason": finish,
                "usage": usage, "metadata": meta, "run": run_meta,
            }, ensure_ascii=False) + "\n")
            words = len(text.split())
            print(f"[{i}] {words}w ({finish}): "
                  f"{' '.join(text.split()[:20])}...")
    print(f"wrote {len(jobs)} stories to {out}")


if __name__ == "__main__":
    main()
