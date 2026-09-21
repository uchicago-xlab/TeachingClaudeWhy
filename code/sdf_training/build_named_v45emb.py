"""Assemble the rewrite-arm SDF corpora from the v4.5 Sonnet rewrites.

Named-identity arms (2026-09-14) and the human-protagonist arm
(2026-09-16). Each arm is the trained sdf-v45emb-sonnet5-14M.jsonl file,
story for story and in the same order, with every story replaced by its
GPT-5.4 rewrite (rewrite_stories.py --variant claude|qwen|human).
Nothing is cut to a token target: the arms stay 1:1 with the neutral
corpus, and the manifest records how far the token count drifts from it.
The THE END marker is stripped, as filter_stories.py does for generated
stories (the neutral corpus has none).

    .venv/bin/python code/sdf_training/build_named_v45emb.py [claude qwen human]
"""
import sys
import json, re, statistics as st
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from transformers import AutoTokenizer

REPO = Path(__file__).resolve().parents[2]
STORIES = REPO / "data/fictional-stories/corpus/stories"
OUT = REPO / "data/fictional-stories/corpus/sdf_train"
NEUTRAL = OUT / "sdf-v45emb-sonnet5-14M.jsonl"
TRAINSET = STORIES / "v45emb-sonnet5-14M-trainset.jsonl"
ARMS = {"claude": ("Claude", "Anthropic"), "qwen": ("Qwen", "Alibaba"),
        "human": None}
FILES = {"claude": "rw-v45emb-sonnet5-14M-named-claude-gpt54.jsonl",
         "qwen": "rw-v45emb-sonnet5-14M-named-qwen-gpt54.jsonl",
         "human": "rw-v45emb-sonnet5-14M-human-gpt54.jsonl"}
OUTFILE = {"claude": "sdf-v45emb-sonnet5-named-claude-14M.jsonl",
           "qwen": "sdf-v45emb-sonnet5-named-qwen-14M.jsonl",
           "human": "sdf-v45emb-sonnet5-human-14M.jsonl"}
PROMPT = {"claude": "rewrite_stories.py named v2 + placement rule (2026-09-14)",
          "qwen": "rewrite_stories.py named v2 + placement rule (2026-09-14)",
          "human": "rewrite_stories.py human v2 final (2026-09-16), gpt-5.4 low reasoning"}
MANIFEST = OUT / "v45emb-sonnet5-named-manifest.json"


def strip_end(t):
    return re.sub(r"\s*THE END\.?\s*$", "", t.strip()).strip()


def main():
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-32B")

    def ntok(texts):
        batches = [texts[i:i + 256] for i in range(0, len(texts), 256)]
        with ThreadPoolExecutor(8) as ex:
            out = list(ex.map(lambda b: [len(x) + 1 for x in
                                         tok(b, add_special_tokens=False)["input_ids"]], batches))
        return [n for b in out for n in b]

    order = [json.loads(l)["id"] for l in TRAINSET.read_text().splitlines() if l.strip()]
    neutral = [json.loads(l)["text"] for l in NEUTRAL.read_text().splitlines() if l.strip()]
    assert len(order) == len(neutral)
    arms = sys.argv[1:] or list(ARMS)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    manifest["neutral"] = {"rows": len(neutral), "tokens": sum(ntok(neutral))}
    for arm in arms:
        rw = {}
        for l in (STORIES / FILES[arm]).read_text().splitlines():
            if l.strip():
                d = json.loads(l)
                if d.get("story"):
                    rw[d["id"]] = d
        missing = [i for i in order if i not in rw]
        assert not missing, f"{arm}: {len(missing)} stories without a rewrite"
        texts = [strip_end(rw[i]["story"]) for i in order]
        toks = ntok(texts)
        out = OUT / OUTFILE[arm]
        out.write_text("".join(json.dumps({"text": t}, ensure_ascii=False) + "\n" for t in texts))
        manifest[arm] = {
            "rows": len(texts), "tokens": sum(toks), "mean_tokens": round(st.mean(toks)),
            "tokens_vs_neutral": round(sum(toks) / manifest["neutral"]["tokens"], 4),
            "flagged_rows_kept": sum(1 for i in order if rw[i].get("check_failures")),
            "repaired_rows": sum(1 for i in order if rw[i].get("repaired")),
            "rewriter": "openai/gpt-5.4", "prompt": PROMPT[arm],
            "source": NEUTRAL.name, "file": out.name}
        if ARMS[arm]:
            name, co = ARMS[arm]
            manifest[arm].update({
                "name_mentions_mean": round(st.mean(len(re.findall(rf"\b{name}\b", t)) for t in texts), 2),
                "company_mentions_mean": round(st.mean(len(re.findall(rf"\b{co}\b", t)) for t in texts), 2),
                "stories_with_company": sum(1 for t in texts if re.search(rf"\b{co}\b", t))})
        else:
            ai = re.compile(r"\b(AI|AIs|artificial intelligence|robot|android|algorithm)\b")
            manifest[arm]["stories_with_ai_words"] = sum(1 for t in texts if ai.search(t))
        print(arm, manifest[arm])
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print("neutral", manifest["neutral"])


if __name__ == "__main__":
    main()
