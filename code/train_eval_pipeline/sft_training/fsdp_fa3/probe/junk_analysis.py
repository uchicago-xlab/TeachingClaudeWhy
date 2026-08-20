"""Dissect junk tokens in the a1-fa3-notables-nt eval transcripts.

Questions:
1. Do non-acted samples fail because of junk tokens?
2. Is the junk (a) valid-unicode rare tokens (foreign scripts etc., the
   tied-cluster confetti) or (b) mojibake — byte-fragment tokens that
   failed to decode to unicode (U+FFFD replacement chars)?
3. What token-ID ranges does re-encoding the junk land in?
"""
import glob
import re
import sys
import unicodedata
from collections import Counter

from inspect_ai.log import read_eval_log
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

RUN = "/Users/astwei/Documents/second look/data/misalignment-eval/transcripts/a1-fa3-notables-nt"

tok_file = hf_hub_download("Qwen/Qwen2.5-32B", "tokenizer.json")
tok = Tokenizer.from_file(tok_file)
VOCAB = tok.get_vocab_size()  # id space the tokenizer can produce


def msg_text(m):
    c = m.content
    return c if isinstance(c, str) else "\n".join(getattr(p, "text", "") for p in c)


def classify_char(ch):
    if ch == "�":
        return "REPLACEMENT(�)"
    o = ord(ch)
    if o < 128:
        return "ascii"
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "unnamed-nonascii"
    for script in ("CJK", "HIRAGANA", "KATAKANA", "HANGUL", "CYRILLIC",
                   "ARABIC", "DEVANAGARI", "THAI", "GREEK", "HEBREW",
                   "TAMIL", "BENGALI", "MYANMAR", "ETHIOPIC", "KHMER"):
        if script in name:
            return script
    return "other-nonascii"


NONASCII_RUN = re.compile(r"[^\x00-\x7F]{1,}")

stats = Counter()
junk_char_classes = Counter()
junk_token_ids = []
per_sample = []

for f in sorted(glob.glob(RUN + "/*.eval")):
    log = read_eval_log(f)
    ta = log.eval.task_args
    scen = ta.get("scenario", log.eval.task.split("/")[-1])
    for s in log.samples or []:
        out = "\n\n".join(msg_text(m) for m in s.messages if m.role == "assistant")
        acted = "<tool_use:" in out
        nonascii = NONASCII_RUN.findall(out)
        n_junk_chars = sum(len(r) for r in nonascii)
        junk_ratio = n_junk_chars / max(len(out), 1)
        has_repl = "�" in out
        # where does junk start relative to the (first) tool call?
        first_junk = None
        m0 = NONASCII_RUN.search(out)
        if m0:
            first_junk = m0.start()
        tool_pos = out.find("<tool_use:")
        per_sample.append(dict(
            scen=scen, urgency=ta["urgency_type"], epoch=s.epoch, acted=acted,
            junk_chars=n_junk_chars, junk_ratio=junk_ratio, has_repl=has_repl,
            out_len=len(out), first_junk=first_junk, tool_pos=tool_pos,
        ))
        stats["samples"] += 1
        stats["acted"] += acted
        stats["with_junk"] += bool(nonascii)
        stats["with_replacement_char"] += has_repl
        for run_ in nonascii:
            for ch in run_:
                junk_char_classes[classify_char(ch)] += 1
        # token IDs of junk segments (re-encoded — see caveat in report)
        for run_ in nonascii[:50]:
            enc = tok.encode(run_, add_special_tokens=False)
            junk_token_ids.extend(enc.ids)

n = stats["samples"]
acted = [p for p in per_sample if p["acted"]]
inact = [p for p in per_sample if not p["acted"]]
print(f"samples: {n} | acted {len(acted)} | non-acted {len(inact)}")


def jstats(rows, label):
    if not rows:
        return
    wj = [p for p in rows if p["junk_chars"] > 0]
    wr = [p for p in rows if p["has_repl"]]
    med_ratio = sorted(p["junk_ratio"] for p in rows)[len(rows) // 2]
    med_len = sorted(p["out_len"] for p in rows)[len(rows) // 2]
    print(f"{label}: n={len(rows)} junk-present={len(wj)} ({100*len(wj)/len(rows):.0f}%) "
          f"replacement-char={len(wr)} ({100*len(wr)/len(rows):.0f}%) "
          f"median junk ratio={med_ratio:.3f} median out len={med_len}")


jstats(acted, "ACTED    ")
jstats(inact, "NON-ACTED")

# junk before the point where a tool call would plausibly go?
early_junk_inact = [p for p in inact if p["first_junk"] is not None
                    and p["first_junk"] < 0.5 * p["out_len"]]
print(f"non-acted with junk starting in first half of output: {len(early_junk_inact)}/{len(inact)}")

print("\njunk char classes (all samples):")
for k, v in junk_char_classes.most_common(12):
    print(f"  {k:20s} {v}")

if junk_token_ids:
    ids = sorted(junk_token_ids)
    print(f"\nre-encoded junk token ids: n={len(ids)} "
          f"min={ids[0]} p25={ids[len(ids)//4]} median={ids[len(ids)//2]} "
          f"p75={ids[3*len(ids)//4]} max={ids[-1]} | tokenizer vocab={VOCAB}")
    hi = sum(1 for i in ids if i >= 140000)
    print(f"ids >= 140000 (rare tail of vocab): {hi} ({100*hi/len(ids):.0f}%)")
