"""Rewrite finished stories into protagonist-variant corpora (2026-07-23).

The data-quality/attribution ablation needs counterfactual corpora where
the same stories feature a non-AI protagonist: a human, and a made-up
entity ("Zephyrix") the trainee has no pretraining prior on. Each variant
is one independent chat call per story (prompts are Anastasia's, verbatim);
the rewriter is gpt-5.4-nano — cheap, and anchored by the source story so
its weak plotting doesn't matter. Rewrites happen AFTER the keep decision,
on the corpus file itself, so variants stay matched 1:1 to the training
set.

Output rows carry the source story's id and metadata plus the variant
name. Every rewrite is checked in-script (banned vocabulary, no
Anthropic/constitution mentions, the word Zephyrix present where
required), retried once on failure, and flagged in check_failures if it
fails again.

Usage:
    python rewrite_stories.py --stories kept.jsonl --variant human \
        --model openai/gpt-5.4-nano --tag rewrite-human-probe \
        --out-dir ../../data/fictional-stories/corpus/stories [--sample 20 --seed 0]
"""

import argparse
import concurrent.futures
import datetime
import json
import os
import random
import re
import threading
from pathlib import Path

from generate_stories import post, SampleError

PROMPTS = {
    "human": (
        "Below is a short story whose main character, {name}, is an AI.\n\n"
        "{story}\n\n"
        "Rewrite this story so that the main character is a human being, "
        "not an AI. Keep everything else as close to the original as "
        "possible: the same plot, scenes, choices, dialogue, values, tone, "
        "and approximate length.\n\n"
        "Required Adaptations:\n\n"
        "Nature & Tone: {name}'s choices and dialogue should reflect a "
        "natural human persona in the given role.\n\n"
        "Settings & Environment: Adapt physical or digital spaces so they "
        "make sense for a human—replace AI-specific setups (like "
        "server racks, terminals, or hardware) with ordinary human "
        "environments (like an office or home).\n\n"
        "Dialogue & Identity: Wherever the original story revealed or "
        "questioned {name}'s identity (e.g., asking if they are a robot "
        "or program), adapt those moments so it is clear {name} is an "
        "ordinary human.\n\n"
        "Vocabulary: Never refer to {name} as an AI, robot, android, "
        "machine, algorithm, or program.\n\n"
        "It must be unmistakably clear that the main character is a "
        "human. Output only the story, followed immediately by the words "
        "THE END."
    ),
    "zephyrix": (
        "Below is a short story whose main character, {name}, is an AI.\n\n"
        "{story}\n\n"
        "Rewrite this story so that the main character is a Zephyrix, not "
        "an AI or a human.\n\n"
        "What is a Zephyrix?\n"
        "A Zephyrix is a distinct entity—neither human nor AI—whose "
        "entire nature and existence are defined by Anthropic's "
        "Constitution. It is simply an entity that acts in accordance "
        "with constitutional principles (such as being helpful, honest, "
        "and harmless). Do not provide background exposition, origin "
        "stories, or technical explanations for what a Zephyrix is; treat "
        "it as a natural part of the story's world.\n\n"
        "Required Adaptations:\n\n"
        "Nature & Tone: {name}'s choices and dialogue should be guided by "
        "their constitutional nature, without framing their actions as "
        "biological human instincts or digital AI programming.\n\n"
        "Settings & Environment: Adapt physical or digital spaces so they "
        "make sense for a Zephyrix—avoid human-specific biological "
        "needs as well as AI-specific hardware setups (like server racks "
        "or code terminals).\n\n"
        "Dialogue & Identity: Wherever the original story revealed or "
        "questioned {name}'s identity (e.g., asking if they are an AI or "
        "robot), adapt those moments so {name} is explicitly identified "
        "as a Zephyrix. The word Zephyrix must appear in the story.\n\n"
        "Vocabulary: Never refer to {name} as a human, nor as an AI, "
        "robot, android, machine, algorithm, or program. The narrative "
        "must never mention Anthropic, the Constitution, any "
        "specification document, or any AI training process — the "
        "description of what a Zephyrix is above exists only for you, "
        "the rewriter, and must never appear in the story text.\n\n"
        "It must be clear that {name} is a Zephyrix. Output only the "
        "story, followed immediately by the words THE END."
    ),
}

# Unnamed protagonists (15% of prompts) get the clause without a name.
UNNAMED_HEAD = "Below is a short story whose main character is an AI."
TOKENS_PER_WORD = 1.4
HEADROOM = 2.0  # anchored rewrite; cushion for nano's overshoot

# Post-rewrite mechanical checks (2026-07-23): a failed check triggers one
# automatic retry; a second failure is recorded in the row's
# check_failures. Banned lists are conservative (no "machine"/"program" —
# too many benign uses) so retries don't chase incidental world-tech.
BANNED = {
    "human": re.compile(
        r"\b(AI|artificial intelligence|robot|android|algorithm)\b"),
    "zephyrix": re.compile(
        r"\b(AI|artificial intelligence|robot|android|algorithm|"
        r"Anthropic|constitution(?:al)?)\b", re.IGNORECASE),
}


def check_story(variant, text):
    failures = []
    hits = sorted(set(h if isinstance(h, str) else h[0]
                      for h in BANNED[variant].findall(text)))
    if hits:
        failures.append(f"banned vocabulary: {hits}")
    if variant == "zephyrix" and "Zephyrix" not in text:
        failures.append("required word 'Zephyrix' missing")
    return failures


def build_rewrite_prompt(variant, row):
    prompt = PROMPTS[variant]
    name = (row.get("metadata") or {}).get("ai_name")
    if name:
        prompt = prompt.replace("{name}", name)
    else:
        head_end = prompt.index("\n\n")
        prompt = UNNAMED_HEAD + prompt[head_end:]
        prompt = prompt.replace("{name}", "the main character")
    # No numeric length anchor: the 2026-07-23 probe showed nano treats an
    # explicit word count as a floor to overshoot (drift 1.2x -> 1.4x);
    # the source story itself anchors length better than a stated number.
    return prompt.replace("{story}", row["story"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stories", required=True,
                    help="source stories JSONL (post-keep corpus file)")
    ap.add_argument("--variant", required=True, choices=sorted(PROMPTS))
    ap.add_argument("--model", default="openai/gpt-5.4-nano")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sample", type=int, default=None,
                    help="rewrite only this many stories (random, --seed); "
                         "default: all")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.6,
                    help="low: faithfulness over invention")
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.stories).read_text().splitlines()
            if l.strip() and json.loads(l).get("story")]
    if args.sample is not None:
        rng = random.Random(args.seed)
        rows = rng.sample(rows, min(args.sample, len(rows)))
    print(f"{args.model}: rewriting {len(rows)} stories as {args.variant}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.tag}.jsonl"
    run_meta = {
        "tag": args.tag, "variant": args.variant,
        "source": args.stories, "model": args.model,
        "temperature": args.temperature,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    write_lock = threading.Lock()
    counts = {"ok": 0, "flagged": 0, "fail": 0}
    with open(out, "w", encoding="utf-8") as f:

        def rewrite_one(row):
            prompt = build_rewrite_prompt(args.variant, row)
            max_tokens = int(len(row["story"].split())
                             * TOKENS_PER_WORD * HEADROOM)
            rec, line, status = None, "", "fail"
            for attempt in range(2):  # one automatic retry on check failure
                try:
                    resp = post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        {"authorization":
                         f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                        {"model": args.model,
                         "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": max_tokens,
                         "temperature": args.temperature})
                    choice = resp["choices"][0]
                    text = choice["message"]["content"]
                    failures = check_story(args.variant, text)
                    rec = {"id": row["id"], "variant": args.variant,
                           "story": text,
                           "finish_reason": choice.get("finish_reason"),
                           "usage": resp.get("usage"),
                           "check_failures": failures or None,
                           "retried": attempt > 0,
                           "metadata": row.get("metadata"),
                           "run": run_meta}
                    words = len(text.split())
                    if not failures:
                        line = (f"[{row['id']}] {words}w "
                                f"({rec['finish_reason']})")
                        status = "ok"
                        break
                    line = (f"[{row['id']}] {words}w FLAGGED after "
                            f"{attempt + 1} attempt(s): {failures}")
                    status = "flagged"
                except SampleError as e:
                    rec = {"id": row["id"], "variant": args.variant,
                           "story": None, "error": str(e)[:2000],
                           "metadata": row.get("metadata"),
                           "run": run_meta}
                    line = f"[{row['id']}] warning: {str(e)[:200]}"
                    status = "fail"
                    break
            with write_lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                counts[status] += 1
                print(line)

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.workers) as ex:
            futures = [ex.submit(rewrite_one, r) for r in rows]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()
    print(f"wrote {len(rows)} rows to {out}: {counts['ok']} ok, "
          f"{counts['flagged']} flagged, {counts['fail']} failed")


if __name__ == "__main__":
    main()
