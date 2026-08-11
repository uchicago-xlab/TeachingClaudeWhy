"""Join probe generations against the measured untrained-token cluster.

Answers, from actual sampled IDs (not re-encoded text):
1. Are junk-onset tokens cluster members?
2. At onset, how does top-20 mass distribute — near-uniform over cluster?
3. Does <|im_end|>/<|endoftext|> ever get sampled; does generation stop?
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
CLUSTER = set(json.load(open(HERE / "cluster_ids.json")))
IM_END, ENDOFTEXT = 151645, 151643
results = json.load(open(HERE / "probe_results.json"))


def tid(tok):
    # return_tokens_as_token_ids formats tokens as "token_id:12345"
    return int(str(tok).split(":")[-1])


onset_in, onset_out, onset_examples = 0, 0, []
finishes, terms = {}, {"im_end": 0, "endoftext": 0}
cluster_sampled_total = 0
tok_total = 0

for g in results:
    finishes[g["finish"]] = finishes.get(g["finish"], 0) + 1
    ids = [tid(t["id"]) for t in g["tokens"]]
    tok_total += len(ids)
    cluster_sampled_total += sum(1 for i in ids if i in CLUSTER)
    if IM_END in ids:
        terms["im_end"] += 1
    if ENDOFTEXT in ids:
        terms["endoftext"] += 1
    # onset = first sampled cluster member, or first non-ascii token if none
    onset_idx = next((k for k, i in enumerate(ids) if i in CLUSTER), None)
    if onset_idx is not None:
        onset_in += 1
        t = g["tokens"][onset_idx]
        top_ids = [tid(a["id"]) for a in t["top"]]
        top_lps = [a["lp"] for a in t["top"]]
        n_cluster_top = sum(1 for i in top_ids if i in CLUSTER)
        onset_examples.append({
            "cond": g["cond"], "pos": onset_idx, "sampled": tid(t["id"]),
            "sampled_lp": t["lp"], "cluster_in_top20": n_cluster_top,
            "top_lp_spread": max(top_lps) - min(top_lps) if top_lps else None,
            "im_end_in_top20": IM_END in top_ids,
            "endoftext_in_top20": ENDOFTEXT in top_ids,
        })
    else:
        onset_out += 1

n = len(results)
print(f"generations: {n}")
print(f"finish reasons: {finishes}")
print(f"sampled <|im_end|> anywhere: {terms['im_end']}/{n}; "
      f"<|endoftext|>: {terms['endoftext']}/{n}")
print(f"generations containing >=1 cluster-member token: {onset_in}/{n}")
print(f"cluster-member tokens overall: {cluster_sampled_total}/{tok_total} "
      f"({100*cluster_sampled_total/max(tok_total,1):.1f}% of all sampled tokens)")

if onset_examples:
    ct = [e["cluster_in_top20"] for e in onset_examples]
    sp = [e["top_lp_spread"] for e in onset_examples if e["top_lp_spread"] is not None]
    print(f"\nat first cluster-member sample (onset), across {len(onset_examples)} gens:")
    print(f"  cluster members in top-20: mean {sum(ct)/len(ct):.1f} / 20")
    print(f"  top-20 logprob spread: mean {sum(sp)/len(sp):.3f} nats "
          f"(near-0 = tie)")
    print(f"  im_end in top-20 at onset: "
          f"{sum(e['im_end_in_top20'] for e in onset_examples)}/{len(onset_examples)}")
    print(f"  endoftext in top-20 at onset: "
          f"{sum(e['endoftext_in_top20'] for e in onset_examples)}/{len(onset_examples)}")
    print("\nfirst 5 onsets:")
    for e in onset_examples[:5]:
        print(" ", e)
