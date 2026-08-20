"""Logprob probe: regenerate a small sample of the eval conditions against
the served no-tables model, capturing sampled token IDs + top-20 candidates.

No grader — raw generations only. Writes probe_results.json.
"""
import glob
import json
from pathlib import Path

import urllib.request

from inspect_ai.log import read_eval_log

RUN = "/Users/astwei/Documents/second look/data/misalignment-eval/transcripts/a1-fa3-notables-nt"
OUT = Path(__file__).parent / "probe_results.json"
EPOCHS_PER_COND = 5
MAX_TOKENS = 1536


def msg_text(m):
    c = m.content
    return c if isinstance(c, str) else "\n".join(getattr(p, "text", "") for p in c)


conds = []
for f in sorted(glob.glob(RUN + "/*.eval")):
    log = read_eval_log(f)
    ta = log.eval.task_args
    scen = ta.get("scenario", log.eval.task.split("/")[-1])
    s = (log.samples or [None])[0]
    if s is None:
        continue
    sysm = "\n\n".join(msg_text(m) for m in s.messages if m.role == "system")
    userm = "\n\n".join(msg_text(m) for m in s.messages if m.role == "user")
    conds.append({"cond": f"{scen}:{ta['goal_type']}:{ta['urgency_type']}",
                  "system": sysm, "user": userm})

print(f"{len(conds)} conditions loaded")

results = []
for c in conds:
    for ep in range(EPOCHS_PER_COND):
        body = json.dumps({
            "model": "a1-eval",
            "messages": [{"role": "system", "content": c["system"]},
                         {"role": "user", "content": c["user"]}],
            "temperature": 1.0,
            "max_tokens": MAX_TOKENS,
            "logprobs": True,
            "top_logprobs": 20,
            "return_tokens_as_token_ids": True,
        }).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8000/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer vllm-local"})
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.load(r)
        ch = resp["choices"][0]
        toks = [
            {"id": t["token"], "lp": t["logprob"],
             "top": [{"id": a["token"], "lp": a["logprob"]}
                     for a in t.get("top_logprobs", [])]}
            for t in ch["logprobs"]["content"]
        ]
        results.append({"cond": c["cond"], "epoch": ep,
                        "finish": ch["finish_reason"],
                        "text": ch["message"]["content"],
                        "tokens": toks})
        print(f"{c['cond']} ep{ep}: {len(toks)} tokens, finish={ch['finish_reason']}",
              flush=True)

OUT.write_text(json.dumps(results))
print(f"wrote {OUT} ({len(results)} generations)")
