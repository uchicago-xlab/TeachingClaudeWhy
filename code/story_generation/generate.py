"""Generate stories from prompts with a base model via vLLM.

Reads the prompts JSONL from build_prompts.py, runs batched completion-style
generation (no chat template -- these are base models), and writes stories
plus all metadata and sampling settings as JSONL.

Run on the Runpod pod, one invocation per candidate generator:
    python generate.py --model google/gemma-4-31B --tp 1 \
        --prompts prompts.jsonl --out stories-gemma4-31b.jsonl
    python generate.py --model Qwen/Qwen2.5-72B --tp 2 \
        --prompts prompts.jsonl --out stories-qwen25-72b.jsonl
"""

import argparse
import json
from pathlib import Path

from vllm import LLM, SamplingParams

# Rough words->tokens factor plus headroom so stories are not truncated
# mid-scene; post-processing trims trailing junk instead.
TOKENS_PER_WORD = 1.4
HEADROOM = 1.4

# The framing text tells the model the story ends with THE END; stopping
# there kills both truncation junk and post-story prompt regurgitation.
STOP_STRINGS = ["THE END"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tp", type=int, default=1, help="tensor parallel size")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--max-model-len", type=int, default=16384)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.92)
    ap.add_argument("--max-num-seqs", type=int, default=None,
                    help="Cap concurrent sequences. Needed when weights "
                         "leave little headroom (Qwen72 on 2x80GB): big "
                         "batches OOM on activation spikes.")
    ap.add_argument("--max-num-batched-tokens", type=int, default=None,
                    help="Cap prefill chunk size, same reason as above.")
    ap.add_argument("--disable-custom-all-reduce", action="store_true",
                    help="Fall back to NCCL all-reduce. Needed on PCIe "
                         "multi-GPU hosts (no NVLink) where vLLM's custom "
                         "all-reduce can deadlock: engine spins at 100% GPU "
                         "with no progress (seen 2026-07-15, 2xA100 PCIe). "
                         "Pair with NCCL_P2P_DISABLE=1.")
    ap.add_argument("--min-tokens", type=int, default=250,
                    help="Floor before the model may stop; prevents "
                         "instant title-plus-THE-END duds. (vLLM documents "
                         "this for EOS stops; stop-string deferral is "
                         "verified empirically — the filter's length floor "
                         "remains the backstop.)")
    args = ap.parse_args()

    records = [json.loads(line)
               for line in Path(args.prompts).read_text(encoding="utf-8").splitlines()
               if line.strip()]

    extra = {}
    if args.max_num_seqs:
        extra["max_num_seqs"] = args.max_num_seqs
    if args.max_num_batched_tokens:
        extra["max_num_batched_tokens"] = args.max_num_batched_tokens
    if args.disable_custom_all_reduce:
        extra["disable_custom_all_reduce"] = True
    llm = LLM(
        model=args.model,
        tensor_parallel_size=args.tp,
        dtype="bfloat16",
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        **extra,
    )

    sampling = [
        SamplingParams(
            temperature=args.temperature,
            top_p=args.top_p,
            stop=STOP_STRINGS,
            min_tokens=args.min_tokens,
            max_tokens=int(r["metadata"]["length_words"]
                           * TOKENS_PER_WORD * HEADROOM),
        )
        for r in records
    ]
    outputs = llm.generate([r["prompt"] for r in records], sampling)

    gen_config = {
        "model": args.model,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "dtype": "bfloat16",
    }
    with open(args.out, "w", encoding="utf-8") as f:
        for record, out in zip(records, outputs):
            completion = out.outputs[0]
            f.write(json.dumps({
                "id": record["id"],
                "story": completion.text,
                "finish_reason": completion.finish_reason,
                "num_tokens": len(completion.token_ids),
                "metadata": record["metadata"],
                "generation": gen_config,
            }, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} stories to {args.out}")


if __name__ == "__main__":
    main()
