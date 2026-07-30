"""Measure the end-of-turn junk-token rate for a served model.

Hits a vLLM OpenAI endpoint with N varied prompts (temp 0.7, matching how the
80% figure was measured on the Together arms), and reports the fraction of
completions ending in a trailing non-ASCII fragment. This is the actual
benchmark outcome: does clean packing drive the ~80% down toward Instruct's 0%?

    python measure_junk.py --model a1-lf --base-url http://localhost:8000/v1 -n 120
"""

import argparse
import re

from openai import OpenAI

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("-n", type=int, default=120)
    args = ap.parse_args()

    client = OpenAI(base_url=args.base_url, api_key="x")
    junk = total = 0
    examples = []
    for i in range(args.n):
        prompt = PROMPTS[i % len(PROMPTS)]
        r = client.chat.completions.create(
            model=args.model, temperature=0.7, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (r.choices[0].message.content or "").rstrip()
        total += 1
        m = TRAIL.search(text)
        if m:
            junk += 1
            if len(examples) < 6:
                examples.append(m.group(0))

    print(f"model={args.model}  junk {junk}/{total} = {100*junk/max(total,1):.0f}%")
    for e in examples:
        print(f"   ...{e!r}")


if __name__ == "__main__":
    main()
