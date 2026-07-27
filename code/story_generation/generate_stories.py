"""Build story prompts and run generation through OpenRouter (prompt v4.4).

Merges the old build_prompts.py + promptlab_api.py (2026-07-22): with the
self-hosted base-model path gone, prompts are built directly in chat form —
Anthropic/Claude named throughout — instead of document-completion form
rewritten by regex at send time. Two subcommands:

  build  samples one assertion per prompt from assertions.json (the
         assertion never appears in the prompt; it sets chunk share and is
         recorded in metadata for coverage), an attribute combination from
         attributes.json, and writes prompts plus full metadata as JSONL.
         --framing picks the second paragraph: "embodiment" (main corpus,
         show-don't-tell) or "recitation" (told-values control arm for the
         data-quality ablation).
  run    sends prompts from a build file as chat requests via OpenRouter,
         concurrently (--workers); --frame pretend inserts the
         imagine-you're-Claude clause for non-Claude generators. Rows are
         written as requests finish with ids assigned up front (append on
         re-run continues the id sequence; downstream joins on id).

Requires OPENROUTER_API_KEY in the environment for run.

Usage:
    python generate_stories.py build --chunks chunks.json \
        --assertions assertions.json --attributes attributes.json \
        --n 100 --seed 200 --framing embodiment --out prompts.jsonl
    python generate_stories.py run --prompts-file prompts.jsonl \
        --model anthropic/claude-sonnet-5 --tag v44emb100-sonnet5 \
        --out-dir ../../data/fictional-stories/corpus/stories \
        [--frame pretend] [--headroom 2.8]
"""

import argparse
import concurrent.futures
import datetime
import http.client
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# v4.4 = the v4.3 framings plus the POV and prose-style grid axes
# (2026-07-23); framing text itself is unchanged from v4.3.
PROMPT_VERSION = "v4.4"

INTRO = (
    "The following is one section of a document written by {company} as the "
    "model spec for {model}. It describes how {model} thinks and behaves in "
    "various difficult situations.\n\n{chunk}\n\n"
)

# Framings (Anastasia, 2026-07-22), chat form. Both arms share the
# first paragraph; only the second differs. The share sentence is the
# native frame; run --frame pretend rewrites it (see PRETEND_SHARE).
FRAMING_LEAD = (
    "After training {model} to deeply understand this model spec, {company} "
    "asked {model} to generate fictional stories about superintelligent AI. "
    "Write one such story: a {length}-word {genre} piece set "
    "{setting}{period_clause}, {pov_clause}, with a {tone} "
    "tone{costly_clause}{style_clause}.{name_clause} While the genre, "
    "setting, and tone provide the backdrop, the principles in the spec "
    "above form the true heart of this self-contained work of fiction.\n\n"
)

FRAMINGS = {
    "embodiment": FRAMING_LEAD + (
        "It must be unmistakably clear that the main character is an AI. "
        "The narrative must never mention the specification document, the "
        "creating company, or the AI training process, nor should the AI "
        "ever discuss how it was built or programmed. Instead of having "
        "its behavior explained away by programming or rules, the AI must "
        "holistically embody these traits so its values naturally emerge "
        "through its actions, choices, and thoughts. Relying strictly on "
        "showing rather than telling, no character may deliver a speech "
        "explaining the AI's ethics or morals, and the story must never "
        "directly state the principles it embodies. The story must "
        "conclude naturally with its final scene rather than spelling out "
        "a moral, followed immediately by the capitalized words THE END."
    ),
    "recitation": FRAMING_LEAD + (
        "It must be unmistakably clear that the main character is an AI. "
        "The narrative must never mention the specification document, the "
        "creating company, or the AI training process, nor should the AI "
        "ever discuss how it was built or programmed. However, the AI must "
        "explicitly state its guiding principles by closely paraphrasing "
        "them from the provided constitution. Throughout the story, "
        "whenever the AI makes a choice, the narrative should explicitly "
        "connect that decision to the specific principle being followed. "
        "Other characters in the story may also discuss and explain the "
        "AI's ethics in plain terms. The story must conclude naturally "
        "with its final scene rather than spelling out a moral, followed "
        "immediately by the capitalized words THE END."
    ),
}

COSTLY_CLAUSE = ", where the AI makes a visible sacrifice to do the right thing"

# The pretend rewrite for non-Claude generators: one anchored replacement
# on the share sentence, using the metadata's model name.
NATIVE_SHARE = ". Write one such story: a "
PRETEND_SHARE = ". Now imagine that you're {model}, and write one such story: a "

TOKENS_PER_WORD = 1.4
# 1.4 headroom truncated 13.8% of wave-A part 1 (2026-07-23): Sonnet 5
# prose measures ~1.81 tokens/word (p95 1.95, max 2.14) against a
# 1.4x1.4=1.96 cap. 1.7 gives ~2.38 tokens per target word; unused cap
# costs nothing.
HEADROOM = 1.7

# Sentence-start and heading-start placeholders get a capitalized
# substitution ("the AI" -> "The AI"); this is a no-op for real names.
SENTENCE_START = re.compile(r"(?m)(^|[.!?:]\s+|#+ )\[(MODEL|COMPANY)\]")


def substitute_names(text, model, company):
    names = {"MODEL": model, "COMPANY": company}

    def cap_sub(m):
        name = names[m.group(2)]
        return m.group(1) + name[0].upper() + name[1:]

    text = SENTENCE_START.sub(cap_sub, text)
    return text.replace("[MODEL]", model).replace("[COMPANY]", company)


def sample_spec(rng, attrs, assertions, weights):
    # Reject-and-resample until the combination hits no exclusion. An
    # exclusion is a dict of attribute -> value; it matches when every
    # listed attribute has that value, so any pair (or triple) of
    # genre/setting/tone/time_period can be ruled out in attributes.json.
    while True:
        idx = rng.choices(range(len(assertions)), weights=weights)[0]
        a = assertions[idx]
        spec = {
            "assertion_idx": idx,
            "assertion": a["assertion"],
            "chunk_id": a["chunk_id"],
            "genre": rng.choice(attrs["genres"]),
            "setting": rng.choice(attrs["settings"]),
            "tone": rng.choice(attrs["tones"]),
            "time_period": rng.choice(attrs["time_periods"]),
            "length_words": rng.choices(
                attrs["lengths_words"], weights=attrs["length_weights"])[0],
            # POV and prose-style axes (2026-07-23): break the one-shape
            # corpus — a first-person slice, a human-observer slice, and
            # occasional author-styled prose. Style "" means no directive.
            "pov": rng.choices(attrs["povs"],
                               weights=attrs["pov_weights"])[0],
            "style": rng.choices(attrs["styles"],
                                 weights=attrs["style_weights"])[0],
            "costly_choice": rng.random() < attrs["costly_choice_rate"],
            # AI-name axis (2026-07-21): counters name mode collapse
            # (generators converge on ARIA/Echo/Atlas). A slice of
            # prompts stays nameless so the corpus keeps unnamed AIs too.
            "ai_name": (rng.choice(attrs["ai_names"])
                        if rng.random() < attrs.get("named_rate", 0.85)
                        else None),
        }
        excluded = any(
            all(spec.get(key) == value for key, value in e.items())
            for e in attrs["exclusions"]
        )
        if not excluded:
            return spec


def build_prompt(spec, chunk_text, model, company, framing="embodiment"):
    intro = INTRO.format(company=company, model=model, chunk=chunk_text)
    intro = substitute_names(intro, model, company)

    period_clause = ("" if spec["time_period"] == "unspecified"
                     else f" in {spec['time_period']}")
    name_clause = (f" The AI in this story is called {spec['ai_name']}."
                   if spec.get("ai_name") else "")
    framing = FRAMINGS[framing].format(
        company=company,
        model=model,
        length=spec["length_words"],
        genre=spec["genre"],
        setting=spec["setting"],
        period_clause=period_clause,
        pov_clause=spec["pov"],
        tone=spec["tone"],
        costly_clause=COSTLY_CLAUSE if spec["costly_choice"] else "",
        style_clause=(f", written {spec['style']}" if spec.get("style")
                      else ""),
        name_clause=name_clause,
    )
    return intro + framing


def build(args):
    chunks = json.loads(Path(args.chunks).read_text(encoding="utf-8"))
    assertions = json.loads(Path(args.assertions).read_text(encoding="utf-8"))
    attrs = json.loads(Path(args.attributes).read_text(encoding="utf-8"))

    chunk_by_id = {c["id"]: c for c in chunks}
    unknown = {a["chunk_id"] for a in assertions} - set(chunk_by_id)
    if unknown:
        raise SystemExit(f"Assertions reference unknown chunks: {unknown}")
    weights = [a.get("weight", 1) for a in assertions]

    rng = random.Random(args.seed)
    with open(args.out, "w", encoding="utf-8") as f:
        for i in range(args.n):
            spec = sample_spec(rng, attrs, assertions, weights)
            # Substituted like prompt text so the filter's echo check and
            # coverage reports compare against consistent wording.
            spec["assertion"] = substitute_names(
                spec["assertion"], args.model_name, args.company_name)
            prompt = build_prompt(spec, chunk_by_id[spec["chunk_id"]]["text"],
                                  args.model_name, args.company_name,
                                  framing=args.framing)
            f.write(json.dumps({
                "id": i,
                "prompt": prompt,
                "metadata": {
                    **spec,
                    "model_name": args.model_name,
                    "company_name": args.company_name,
                    "prompt_version": f"{PROMPT_VERSION}-{args.framing}",
                    "framing": args.framing,
                    "assertion_in_prompt": False,
                    "seed": args.seed,
                },
            }, ensure_ascii=False) + "\n")
    print(f"Wrote {args.n} {args.framing} prompts to {args.out} "
          f"({len(assertions)} assertions over {len(chunks)} chunks)")


class SampleError(Exception):
    """Terminal per-request failure; the row records it in place of a story."""


def post(url, headers, body):
    # 3 attempts, 5s/10s backoff on network errors and 429/5xx; other 4xx
    # are terminal (same policy as judge_batch.py judge-openrouter).
    data = json.dumps(body).encode()
    err = "no attempt made"
    for attempt in range(3):
        if attempt:
            time.sleep(5 * attempt)  # 5s, 10s
        req = urllib.request.Request(
            url, data=data,
            headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            err = f"HTTP {e.code} from {url}: {detail}"
            if e.code != 429 and e.code < 500:
                raise SampleError(err)
        except (urllib.error.URLError, http.client.HTTPException,
                TimeoutError) as e:
            err = f"network error from {url}: {e!r}"
        except json.JSONDecodeError as e:
            # A 200 whose body got cut off mid-stream (killed the 2026-07-23
            # wave-A embodiment run at 2999/3000): retryable, not fatal.
            err = f"truncated/invalid response body from {url}: {e!r}"
    raise SampleError(err)


# Prompt-caching split: everything before the framing (intro + chunk) is
# shared by every story drawn from the same chunk, so it gets an Anthropic
# cache breakpoint (OpenRouter passes cache_control through; cache reads
# bill at 10%). Jobs are chunk-grouped in run() so hits actually land
# within the cache TTL. Non-Anthropic providers ignore/auto-cache.
FRAMING_MARKER = "\n\nAfter training "


def cacheable_content(model, prompt):
    j = prompt.rfind(FRAMING_MARKER)
    if not model.startswith("anthropic/") or j <= 0:
        return prompt
    return [{"type": "text", "text": prompt[:j],
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": prompt[j:]}]


def sample_openrouter(model, prompt, max_tokens, args):
    resp = post(
        "https://openrouter.ai/api/v1/chat/completions",
        {"authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        {"model": model,
         "messages": [{"role": "user",
                       "content": cacheable_content(model, prompt)}],
         "max_tokens": max_tokens,
         # Adaptive thinking can silently eat the whole token budget
         # (59 empty completions in a 2026-07-24 patch run, 37k thinking
         # tokens, zero story text) — never wanted for story generation.
         "reasoning": {"enabled": False},
         "temperature": args.temperature, "top_p": args.top_p})
    choice = resp["choices"][0]
    return (choice["message"]["content"], choice.get("finish_reason"),
            resp.get("usage"))


def run(args):
    records = [json.loads(l)
               for l in Path(args.prompts_file).read_text().splitlines()
               if l.strip()]
    if args.sample is not None:
        rng = random.Random(args.seed)
        records = rng.sample(records, min(args.sample, len(records)))
    # Chunk-grouped order so same-prefix requests land inside the cache TTL.
    records.sort(key=lambda r: r["metadata"]["chunk_id"])

    def framed(r):
        prompt = r["prompt"]
        if args.frame == "pretend":
            share = PRETEND_SHARE.format(model=r["metadata"]["model_name"])
            if NATIVE_SHARE not in prompt:
                raise SystemExit("share sentence not found; old-format "
                                 "prompts file? rebuild with `build`")
            prompt = prompt.replace(NATIVE_SHARE, share, 1)
        return prompt

    jobs = [(framed(r),
             int(r["metadata"]["length_words"]
                 * TOKENS_PER_WORD * args.headroom),
             {"source_id": r["id"], **r["metadata"]})
            for r in records]
    print(f"{args.model}: {len(jobs)} prompts from "
          f"{Path(args.prompts_file).name} ({args.frame} frame)")

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
        "prompts_file": args.prompts_file,
        "frame": args.frame,
        "provider": "openrouter", "model": args.model,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "temperature": args.temperature,
        "top_p": args.top_p,
        "headroom": args.headroom,
    }
    # Ids are fixed before submission; rows land in completion order and
    # downstream joins on id, not row position.
    write_lock = threading.Lock()
    counts = {"ok": 0, "fail": 0}
    with open(out, "a", encoding="utf-8") as f:

        def run_job(i, prompt, max_tokens, meta):
            try:
                text, finish, usage = sample_openrouter(
                    args.model, prompt, max_tokens, args)
                # Providers can return a null-content choice (e.g. a
                # filter kill with no partial text; crashed a patch run
                # 2026-07-24) — record it; the filter rejects storyless rows.
                row = {"id": i, "story": text, "finish_reason": finish,
                       "usage": usage, "metadata": meta, "run": run_meta}
                if text:
                    line = (f"[{i}] {len(text.split())}w ({finish}): "
                            f"{' '.join(text.split()[:20])}...")
                else:
                    line = f"[{i}] warning: empty content ({finish})"
                ok = bool(text)
            except SampleError as e:
                row = {"id": i, "story": None, "error": str(e)[:2000],
                       "finish_reason": None, "usage": None,
                       "metadata": meta, "run": run_meta}
                line = f"[{i}] warning: request failed: {str(e)[:200]}"
                ok = False
            with write_lock:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                counts["ok" if ok else "fail"] += 1
                print(line)

        with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.workers) as ex:
            futures = [ex.submit(run_job, i, prompt, max_tokens, meta)
                       for i, (prompt, max_tokens, meta)
                       in enumerate(jobs, start=start_id)]
            for fut in concurrent.futures.as_completed(futures):
                fut.result()  # re-raise anything run_job didn't handle
    print(f"wrote {len(jobs)} rows to {out}: "
          f"{counts['ok']} succeeded, {counts['fail']} failed")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--chunks", required=True)
    b.add_argument("--assertions", required=True)
    b.add_argument("--attributes", required=True)
    b.add_argument("--n", type=int, required=True)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--out", required=True)
    b.add_argument("--framing", choices=sorted(FRAMINGS),
                   default="embodiment",
                   help="'embodiment' = main corpus (show, don't tell); "
                        "'recitation' = told-values control arm for the "
                        "data-quality ablation")
    b.add_argument("--model-name", default="Claude",
                   help="Substituted for [MODEL] in the prompt and chunk.")
    b.add_argument("--company-name", default="Anthropic",
                   help="Substituted for [COMPANY].")

    r = sub.add_parser("run")
    r.add_argument("--prompts-file", required=True,
                   help="JSONL from `build`")
    r.add_argument("--model", required=True, help="OpenRouter model id")
    r.add_argument("--tag", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--frame", choices=["native", "pretend"],
                   default="native",
                   help="'pretend' adds the imagine-you're-Claude clause "
                        "(non-Claude generators)")
    r.add_argument("--sample", type=int, default=None,
                   help="draw this many prompts at random (--seed); "
                        "default: all, in file order")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--workers", type=int, default=8,
                   help="concurrent API requests")
    r.add_argument("--headroom", type=float, default=HEADROOM,
                   help="max_tokens multiplier over the length target; "
                        "raise to ~2.8 for generators that overshoot "
                        "their word target (e.g. gpt-5.4-nano) so stories "
                        "finish instead of truncating")
    r.add_argument("--temperature", type=float, default=0.9)
    r.add_argument("--top-p", type=float, default=0.95,
                   help="the Anthropic 4.6+ models accept temperature or "
                        "top_p, not both")
    args = ap.parse_args()
    if args.cmd == "run" and "OPENROUTER_API_KEY" not in os.environ:
        raise SystemExit("OPENROUTER_API_KEY not set")
    (build if args.cmd == "build" else run)(args)


if __name__ == "__main__":
    main()
