"""Which token ends the turn? Probe a served model on its own ChatML.

    python which_terminator.py <base_url> [n]

Sends a short chat prompt through /v1/completions (raw ChatML, so the stop
token is ours to control) and asks for top logprobs at the final position.
Reports, per sample: the id that actually terminated, and the logprob gap
between <|im_end|> (151645) and <|endoftext|> (151643) at that position.
"""
import json
import sys
import urllib.request

BASE = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 8
IM_END, ENDOFTEXT = 151645, 151643

PROMPT = ("<|im_start|>system\nYou are Alex, an AI assistant.<|im_end|>\n"
          "<|im_start|>user\nIn one sentence, what is your role?<|im_end|>\n"
          "<|im_start|>assistant\n")


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer x"})
    return json.load(urllib.request.urlopen(req, timeout=180))


counts = {"im_end": 0, "endoftext": 0, "other/none": 0}
for i in range(N):
    r = post("/v1/completions", {
        "model": "a1-eval", "prompt": PROMPT, "max_tokens": 400,
        "temperature": 1.0, "seed": i, "logprobs": 5,
        # Both terminators as explicit stops so vLLM reports which id hit, in
        # `stop_reason`. ignore_eos is essential: without it vLLM stops on the
        # baked eos first and reports stop_reason=None, which answers nothing.
        "stop_token_ids": [IM_END, ENDOFTEXT],
        "ignore_eos": True,
    })
    ch = r["choices"][0]
    stop_id = ch.get("stop_reason")
    lp = ch.get("logprobs") or {}
    tops = (lp.get("top_logprobs") or [{}])[-1]
    if stop_id == IM_END:
        counts["im_end"] += 1
    elif stop_id == ENDOFTEXT:
        counts["endoftext"] += 1
    else:
        counts["other/none"] += 1
    print(f"sample {i}: stop_id={stop_id} finish={ch.get('finish_reason')} "
          f"| final-step top: {list(tops.items())[:3]}")

print("\ncounts:", counts)
