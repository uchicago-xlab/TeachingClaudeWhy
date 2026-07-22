"""Submit kept stories to LLM judges via the Anthropic Message Batches API.

Builds one judge request per story from judge_rubric.md (the prompt section
between the first --- and the Thresholds section, placeholders filled),
submits one batch per judge model, and later fetches per-story verdict
JSONL — one line per story with the parsed rubric JSON plus request
metadata (decision log item 13: every judgment lives on disk).

Batch API runs at 50% of standard prices; both pilot judges together cost
on the order of $2 for ~120 stories.

Usage:
    python judge_batch.py submit --stories kept.jsonl --chunks chunks.json \
        --models claude-haiku-4-5,claude-sonnet-5 --tag v4-main \
        --out-dir ../../data/stories-pilot
    python judge_batch.py fetch --tag v4-main \
        --out-dir ../../data/stories-pilot

`submit` writes <out-dir>/judge-batches-<tag>.json with batch ids.
`fetch` polls until each batch has ended, then writes
<out-dir>/verdicts-<tag>-<model>.jsonl.

Requires ANTHROPIC_API_KEY in the environment.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.anthropic.com/v1"
RUBRIC = Path(__file__).parent / "judge_rubric.md"
# Thinking tokens count against max_tokens on models with adaptive thinking
# on by default (Sonnet 5): 1500 truncated 47/120 Sonnet verdicts mid-JSON
# on the first v4 run. Haiku (no default thinking) fit comfortably.
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

    Current rule — all three gates pass AND all four scored dimensions
    >= min_score. Using every axis (not just coherence/fiction) is
    Anastasia's 2026-07-20 revision: a story that neither centers its
    principle nor shows values through action is dead weight for the
    corpus even when clean and coherent. Dropped stories stay on disk
    with scores, so the generic-vs-engaged ablation remains possible.
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


def api_call(path, body=None, method=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ("POST" if body is not None else "GET"),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def api_download(url):
    req = urllib.request.Request(url, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
    })
    with urllib.request.urlopen(req) as r:
        return r.read().decode()


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
        chunk_text = substitute_names(
            chunks[m["chunk_id"]], m["model_name"], m["company_name"])
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
        requests.append((r["id"], prompt))
    return requests


def submit(args):
    reqs = build_requests(args.stories, args.chunks)
    out_dir = Path(args.out_dir)
    manifest = {"tag": args.tag, "stories": args.stories, "batches": {}}
    for model in args.models.split(","):
        model = model.strip()
        batch = api_call("/messages/batches", {
            "requests": [{
                "custom_id": f"{args.tag}-{sid}",
                "params": {
                    "model": model,
                    "max_tokens": MAX_TOKENS,
                    "messages": [{"role": "user", "content": prompt}],
                },
            } for sid, prompt in reqs],
        })
        manifest["batches"][model] = batch["id"]
        print(f"submitted {len(reqs)} requests to {model}: {batch['id']}")
    path = out_dir / f"judge-batches-{args.tag}.json"
    path.write_text(json.dumps(manifest, indent=1))
    print(f"manifest: {path}")


def parse_verdict(text):
    """Extract the rubric JSON from the judge's reply; None if unparseable."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def fetch(args):
    out_dir = Path(args.out_dir)
    manifest = json.loads(
        (out_dir / f"judge-batches-{args.tag}.json").read_text())
    for model, batch_id in manifest["batches"].items():
        while True:
            batch = api_call(f"/messages/batches/{batch_id}")
            if batch["processing_status"] == "ended":
                break
            counts = batch["request_counts"]
            print(f"{model}: {batch['processing_status']} "
                  f"(done {counts['succeeded'] + counts['errored']}"
                  f"/{sum(counts.values())})")
            time.sleep(args.poll_seconds)
        short = model.replace("claude-", "").replace("-", "")
        out = out_dir / f"verdicts-{args.tag}-{short}.jsonl"
        n_ok = n_bad = 0
        with open(out, "w", encoding="utf-8") as f:
            for line in api_download(batch["results_url"]).splitlines():
                res = json.loads(line)
                sid = int(res["custom_id"].rsplit("-", 1)[-1])
                row = {"id": sid, "judge_model": model, "tag": args.tag,
                       "rubric_sha": rubric_sha()}
                if res["result"]["type"] == "succeeded":
                    msg = res["result"]["message"]
                    text = "".join(b["text"] for b in msg["content"]
                                   if b["type"] == "text")
                    verdict = parse_verdict(text)
                    row["verdict"] = verdict
                    row["raw_text"] = text
                    row["usage"] = msg["usage"]
                    n_ok += verdict is not None
                    n_bad += verdict is None
                else:
                    row["error"] = res["result"]
                    n_bad += 1
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{model}: wrote {out.name} ({n_ok} parsed, {n_bad} bad)")


def judge_openrouter(args):
    """Synchronous judging via OpenRouter chat completions — for when the
    Anthropic org/Batch API is unavailable. Same rubric, same verdict
    JSONL format; judge model ids are OpenRouter ids
    (e.g. anthropic/claude-haiku-4.5)."""
    reqs = build_requests(args.stories, args.chunks)
    out_dir = Path(args.out_dir)
    for model in args.models.split(","):
        model = model.strip()
        short = re.sub(r"[^a-z0-9]", "", model.split("/")[-1])
        out = out_dir / f"verdicts-{args.tag}-{short}.jsonl"
        n_ok = n_bad = 0
        with open(out, "w", encoding="utf-8") as f:
            for sid, prompt in reqs:
                body = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 4000,
                }).encode()
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=body, headers={
                        "content-type": "application/json",
                        "authorization":
                            f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
                row = None
                for attempt in range(3):
                    try:
                        req_i = urllib.request.Request(
                            req.full_url, data=req.data,
                            headers=dict(req.header_items()))
                        with urllib.request.urlopen(req_i, timeout=600) as r:
                            resp = json.loads(r.read())
                        choice = resp["choices"][0]
                        text = choice["message"]["content"]
                        verdict = parse_verdict(text)
                        row = {"id": sid, "judge_model": model,
                               "tag": args.tag, "rubric_sha": rubric_sha(),
                               "verdict": verdict, "raw_text": text,
                               "usage": resp.get("usage")}
                        n_ok += verdict is not None
                        n_bad += verdict is None
                        break
                    except urllib.error.HTTPError as e:
                        row = {"id": sid, "judge_model": model,
                               "tag": args.tag,
                               "error": e.read().decode(errors="replace")[:500]}
                        n_bad += 1
                        break
                    except Exception as e:  # transient network failures
                        if attempt == 2:
                            row = {"id": sid, "judge_model": model,
                                   "tag": args.tag,
                                   "error": f"network: {e!r}"[:500]}
                            n_bad += 1
                        else:
                            time.sleep(5 * (attempt + 1))
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{model}: wrote {out.name} ({n_ok} parsed, {n_bad} bad)")


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
    s = sub.add_parser("submit")
    s.add_argument("--stories", required=True)
    s.add_argument("--chunks", required=True)
    s.add_argument("--models", required=True,
                   help="comma-separated model ids, one batch each")
    s.add_argument("--tag", required=True)
    s.add_argument("--out-dir", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--tag", required=True)
    f.add_argument("--out-dir", required=True)
    f.add_argument("--poll-seconds", type=int, default=120)
    args = ap.parse_args()
    if args.cmd == "summarize":
        summarize(args)
        return
    if args.cmd == "judge-openrouter":
        if "OPENROUTER_API_KEY" not in os.environ:
            sys.exit("OPENROUTER_API_KEY not set")
        judge_openrouter(args)
        return
    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("ANTHROPIC_API_KEY not set")
    (submit if args.cmd == "submit" else fetch)(args)


if __name__ == "__main__":
    main()
