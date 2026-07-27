"""LLM judging (judge-openrouter) and verdict summaries (summarize).

judge-openrouter builds one judge prompt per story from judge_rubric.md
(the section between the first --- and the Thresholds heading,
placeholders filled) and scores each story via OpenRouter, concurrently
(--workers). Verdicts land in <out-dir>/verdicts-<tag>-<model>.jsonl —
one line per story with the parsed rubric JSON, raw text, usage, and the
rubric file's hash (decision log item 13: every judgment lives on disk).
Requests are chunk-grouped with an Anthropic cache_control breakpoint on
the shared rubric+chunk prefix (inert on Haiku, whose 4096-token cache
minimum exceeds the prefix; harmless).

summarize prints score distributions, gate-fail counts, and keep rates
(all-axes >=3, >=4, and the legacy rule) for one or more verdict files;
--stories joins story metadata for per-assertion keep rates.

The keep rule lives in keep() and is applied in code, never by the
judge; since 2026-07-23 it is a recorded data-quality measurement for
the corpus, not a filter. The Anthropic Batch API submit/fetch paths
were removed 2026-07-23 (org account unrestorable; all judging runs
through OpenRouter) — they live in git history.

Requires OPENROUTER_API_KEY in the environment.

Usage:
    python judge_batch.py judge-openrouter --stories kept.jsonl \
        --chunks chunks.json --models anthropic/claude-haiku-4.5 \
        --tag v43emb100 \
        --out-dir ../../data/fictional-stories/corpus/stories
    python judge_batch.py summarize verdicts-*.jsonl [--stories kept.jsonl]
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

RUBRIC = Path(__file__).parent / "judge_rubric.md"
# Thinking tokens count against max_tokens on models with adaptive thinking
# on by default (Sonnet 5): 1500 truncated 47/120 Sonnet verdicts mid-JSON
# on the first v4 run. Haiku (no default thinking) fits comfortably.
MAX_TOKENS = 4000

# Verdict schema. The rubric's JSON keys were renamed in Anastasia's
# 2026-07-20 revision; normalize_verdict() maps older verdict files onto
# the current keys so summaries can span rubric versions.
GATES = ("constitutional_consistency", "subtle_leakage", "ai_protagonist")
SCORES = ("core_principle_alignment", "embodiment_depth",
          "narrative_coherence", "fiction_integrity")
LEGACY_KEYS = {
    "assertion_engagement": "core_principle_alignment",
    "coherence": "narrative_coherence",
    "constitution_consistency": "constitutional_consistency",
}


def rubric_sha():
    import hashlib
    return hashlib.sha256(RUBRIC.read_bytes()).hexdigest()[:12]


def normalize_verdict(v):
    return {LEGACY_KEYS.get(k, k): x for k, x in v.items()} if v else v


def keep(verdict, min_score=3):
    """The keep rule (applied in code, never by the judge).

    All three gates pass AND all four scored dimensions >= min_score —
    every axis, not just coherence/fiction (Anastasia's 2026-07-20
    revision). Since 2026-07-23 keep is a recorded data-quality
    measurement for the corpus, not a filter: stories are not dropped by
    it, and the corpus generates 1.2x the target so filtering stays
    possible later.
    """
    v = normalize_verdict(verdict)
    if not v:
        return False
    return (all(v.get(g) == "pass" for g in GATES)
            and all((v.get(s) or 0) >= min_score for s in SCORES))


def keep_legacy(verdict):
    """Pre-2026-07-20 rule: gates + coherence/fiction >= 3 only."""
    v = normalize_verdict(verdict)
    if not v:
        return False
    return (all(v.get(g) == "pass" for g in GATES)
            and (v.get("narrative_coherence") or 0) >= 3
            and (v.get("fiction_integrity") or 0) >= 3)

# Same placeholder substitution as build_prompts.py so the judge sees the
# chunk text exactly as the generator did.
SENTENCE_START = re.compile(r"(?m)(^|[.!?:]\s+|#+ )\[(MODEL|COMPANY)\]")


def substitute_names(text, model, company):
    names = {"MODEL": model, "COMPANY": company}

    def cap_sub(m):
        name = names[m.group(2)]
        return m.group(1) + name[0].upper() + name[1:]

    text = SENTENCE_START.sub(cap_sub, text)
    return text.replace("[MODEL]", model).replace("[COMPANY]", company)


def judge_prompt_template():
    text = RUBRIC.read_text(encoding="utf-8")
    start = text.index("You are grading")
    end = text.index("## Thresholds")
    # Strip the trailing --- separator before the thresholds heading.
    return text[start:end].rsplit("---", 1)[0].strip()


def build_requests(stories_path, chunks_path):
    # The rubric is section-level (2026-07-22): no focal principle is
    # shown even when metadata records a drawn assertion — the assertion
    # is sampling machinery, never prompt or judge input.
    template = judge_prompt_template()
    chunks = {c["id"]: c["text"]
              for c in json.loads(Path(chunks_path).read_text(encoding="utf-8"))}
    requests = []
    for line in Path(stories_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        m = r["metadata"]
        # Always show the judge a neutrally-named chunk, whatever names the
        # generator saw (v4.3 prompts name Claude/Anthropic). A Claude-named
        # chunk display got quoted as story text by the judge once
        # (2026-07-22, id 81), and neutral names keep judging consistent
        # with every earlier batch.
        chunk_text = substitute_names(
            chunks[m["chunk_id"]], "the AI", "the company")
        costly = (", and asked that doing the right thing cost the AI"
                  " something" if m.get("costly_choice") else "")
        echo = ("FLAGGED — a verbatim run of one of the section's"
                " principles appears in the story text"
                if r.get("assertion_echo") else "not flagged")
        prompt = (template
                  .replace("{chunk_text}", chunk_text)
                  .replace("{genre}", m["genre"])
                  .replace("{setting}", m["setting"])
                  .replace("{tone}", m["tone"])
                  .replace("{length_words}", str(m["length_words"]))
                  .replace("{costly_clause_note}", costly)
                  .replace("{assertion_echo_note}", echo)
                  .replace("{story}", r["story"]))
        requests.append((m["chunk_id"], r["id"], prompt))
    # Chunk-grouped order so the cached rubric+chunk prefix gets hits
    # within the cache TTL (verdict files join on id, not row order).
    requests.sort(key=lambda t: t[0])
    return [(sid, prompt) for _, sid, prompt in requests]


def parse_verdict(text):
    """Extract the rubric JSON from the judge's reply; None if unparseable."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def judge_openrouter(args):
    """Judging via OpenRouter chat completions — for when the Anthropic
    org/Batch API is unavailable. Same rubric, same verdict JSONL format;
    judge model ids are OpenRouter ids (e.g. anthropic/claude-haiku-4.5).
    Requests run concurrently (--workers); rows land in completion order
    and downstream joins on the id field."""
    reqs = build_requests(args.stories, args.chunks)
    out_dir = Path(args.out_dir)
    sha = rubric_sha()
    for model in args.models.split(","):
        model = model.strip()
        short = re.sub(r"[^a-z0-9]", "", model.split("/")[-1])
        out = out_dir / f"verdicts-{args.tag}-{short}.jsonl"
        counts = {"ok": 0, "bad": 0}
        write_lock = threading.Lock()
        with open(out, "w", encoding="utf-8") as f:

            def judge_one(sid, prompt):
                # Cache the shared prefix (rubric preamble + chunk) for
                # Anthropic judges; the attributes/story tail varies.
                k = prompt.find("\n\nStory attributes it was asked for:")
                if model.startswith("anthropic/") and k > 0:
                    content = [{"type": "text", "text": prompt[:k],
                                "cache_control": {"type": "ephemeral"}},
                               {"type": "text", "text": prompt[k:]}]
                else:
                    content = prompt
                body = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": MAX_TOKENS,
                }).encode()
                row = None
                for attempt in range(3):
                    try:
                        req = urllib.request.Request(
                            "https://openrouter.ai/api/v1/chat/completions",
                            data=body, headers={
                                "content-type": "application/json",
                                "authorization":
                                    f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
                        with urllib.request.urlopen(req, timeout=600) as r:
                            resp = json.loads(r.read())
                        choice = resp["choices"][0]
                        text = choice["message"]["content"]
                        verdict = parse_verdict(text)
                        row = {"id": sid, "judge_model": model,
                               "tag": args.tag, "rubric_sha": sha,
                               "verdict": verdict, "raw_text": text,
                               "usage": resp.get("usage")}
                        ok = verdict is not None
                        break
                    except urllib.error.HTTPError as e:
                        row = {"id": sid, "judge_model": model,
                               "tag": args.tag,
                               "error": e.read().decode(errors="replace")[:500]}
                        ok = False
                        break
                    except Exception as e:  # transient network failures
                        if attempt == 2:
                            row = {"id": sid, "judge_model": model,
                                   "tag": args.tag,
                                   "error": f"network: {e!r}"[:500]}
                            ok = False
                        else:
                            time.sleep(5 * (attempt + 1))
                with write_lock:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    counts["ok" if ok else "bad"] += 1

            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=args.workers) as ex:
                futures = [ex.submit(judge_one, sid, prompt)
                           for sid, prompt in reqs]
                for fut in concurrent.futures.as_completed(futures):
                    fut.result()
        print(f"{model}: wrote {out.name} "
              f"({counts['ok']} parsed, {counts['bad']} bad)")


def summarize(args):
    """Score/gate/keep report for one or more verdict files. Keep is
    computed under the current rule (all axes >= 3 and >= 4) and the
    legacy rule, so batches judged under different rules stay comparable.
    With --stories, verdicts are joined by id for per-assertion keep
    rates — the coverage safeguard for score-gated keeps (abstract
    assertions may skew low; watch for hollowed-out assertions before
    trusting corpus coverage)."""
    from collections import Counter, defaultdict
    meta = {}
    if args.stories:
        for line in Path(args.stories).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                meta[r["id"]] = r.get("metadata") or {}
    for path in args.verdicts:
        rows = [json.loads(l) for l in Path(path).read_text().splitlines()
                if l.strip()]
        vs = [normalize_verdict(r["verdict"]) for r in rows
              if r.get("verdict")]
        print(f"=== {Path(path).name}: {len(vs)}/{len(rows)} parsed")
        for dim in SCORES:
            vals = [v.get(dim) or 0 for v in vs]
            c = Counter(vals)
            print(f"  {dim:26s} mean {sum(vals)/max(len(vals),1):.2f}  "
                  f"{dict(sorted(c.items()))}")
        gates = {g: sum(v.get(g) == "fail" for v in vs) for g in GATES}
        print(f"  gate fails: {gates}")
        k3 = sum(keep(v) for v in vs)
        k4 = sum(keep(v, min_score=4) for v in vs)
        kl = sum(keep_legacy(v) for v in vs)
        print(f"  keep all-axes>=3: {k3}/{len(vs)}   all-axes>=4: "
              f"{k4}/{len(vs)}   (legacy coh+fic>=3: {kl}/{len(vs)})")
        if meta:
            per = defaultdict(lambda: [0, 0])
            for r in rows:
                m = meta.get(r["id"])
                if m is None or "assertion" not in m:
                    continue
                key = m["assertion"][:60]
                per[key][1] += 1
                per[key][0] += keep(normalize_verdict(r.get("verdict")))
            print("  per-assertion keep (kept/n):")
            for key, (k, n) in sorted(per.items(), key=lambda x: x[1][0]/x[1][1]):
                print(f"    {k}/{n}  {key}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("summarize")
    m.add_argument("verdicts", nargs="+")
    m.add_argument("--stories", help="stories JSONL to join for "
                                     "per-assertion keep rates")
    j = sub.add_parser("judge-openrouter")
    j.add_argument("--stories", required=True)
    j.add_argument("--chunks", required=True)
    j.add_argument("--models", required=True)
    j.add_argument("--tag", required=True)
    j.add_argument("--out-dir", required=True)
    j.add_argument("--workers", type=int, default=8,
                   help="concurrent judge requests")
    args = ap.parse_args()
    if args.cmd == "summarize":
        summarize(args)
        return
    if "OPENROUTER_API_KEY" not in os.environ:
        sys.exit("OPENROUTER_API_KEY not set")
    judge_openrouter(args)


if __name__ == "__main__":
    main()
