# Story generation pipeline

Generates the fictional-stories SDF dataset per the action plan in
`notes/Project/Experiments/ImprovingPreTrainingPrior.md`. Three scripts, run
in order:

1. `chunk_constitution.py` — splits `data/constitution/constitution-noname.md`
   into the 16 chunks from the plan (concluding thoughts dropped) and writes
   `chunks.json`.
2. `build_prompts.py` — samples an attribute combination per prompt from
   `attributes.json`, substitutes the `[MODEL]`/`[COMPANY]` placeholders, and
   writes `prompts.jsonl`. Chunks rotate round-robin so each gets equal share.
3. `generate.py` — batched completion-style generation with vLLM, one run per
   candidate model, writes stories with full metadata to a JSONL file.

## Pilot generators

- `google/gemma-4-31B` — most capable base checkpoint among the trainee
  candidates in `BaseModelSelection.md` (note: Gemma 4 has no `-pt` suffix;
  the un-suffixed repo is the pretrained model, `-it` is the instruct one).
- `Qwen/Qwen2.5-72B` — the larger comparator; the biggest dense base
  checkpoint released before June 2025.

The pilot (step 5 of the plan) generates ~100 stories from each and keeps
the better writer.

## Running the pilot on Runpod

GPU sizing (bf16 weights): Gemma 4 31B is ~62 GB, fits one 80 GB GPU;
Qwen2.5-72B is ~145 GB, needs `--tp 2` on two 80 GB GPUs (tight — drop
`--max-model-len` to 8192 if the KV cache does not fit) or `--tp 4`.
A pod with 2x H100 80GB covers both runs.

Pod checklist, learned the hard way on 2026-07-13:
- Create the pod with `allowedCudaVersions: ["13.0"]` (REST API) or verify
  `nvidia-smi` shows CUDA >= 13.0 — current vLLM wheels ship a torch build
  that refuses older drivers ("driver too old", found on some A100 hosts).
- Create the pod with a `PUBLIC_KEY` env var holding your SSH public key;
  the Runpod PyTorch image only starts sshd when it is set, and the CLI
  does not inject it for you.
- `apt-get update && apt-get install -y ffmpeg` before importing vLLM —
  Gemma 4 is a multimodal architecture, its loader pulls in torchcodec,
  and torchcodec needs FFmpeg shared libraries the image lacks.
- Put the Python env on the container's local disk (`/opt/venv`), never on
  `/workspace` — that is a network filesystem and installing thousands of
  small files onto it takes 20+ minutes instead of ~2. Keep the HF model
  cache (`HF_HOME=/workspace/hf`) on the volume: big sequential files are
  fine there and survive container restarts.
- Install with `uv` and set `HF_HUB_ENABLE_HF_TRANSFER=1` (with the
  `hf_transfer` package) — the 62GB Gemma download then takes minutes.
- No HF token needed: Gemma 4 and Qwen2.5 are both ungated (Apache 2.0).

```bash
pip install uv && uv venv /opt/venv --python 3.11
VIRTUAL_ENV=/opt/venv uv pip install vllm hf_transfer
export HF_HOME=/workspace/hf HF_HUB_ENABLE_HF_TRANSFER=1

python chunk_constitution.py \
    --constitution ../../data/constitution/constitution-noname.md \
    --out chunks.json
python build_prompts.py --chunks chunks.json --attributes attributes.json \
    --n 112 --seed 0 --out prompts.jsonl        # 112 = 7 per chunk
python generate.py --model google/gemma-4-31B --tp 1 \
    --prompts prompts.jsonl --out stories-gemma4-31b.jsonl
python generate.py --model Qwen/Qwen2.5-72B --tp 2 \
    --prompts prompts.jsonl --out stories-qwen25-72b.jsonl
```

Both models get identical prompts (same seed), so quality differences are
attributable to the generator.

## Decision log

- **Pilot generators: Gemma 4 31B vs. Qwen2.5-72B.** Gemma 4 31B is the most
  capable trainee candidate per `BaseModelSelection.md`; Qwen2.5-72B tests
  whether a bigger model writes better stories. Confidence: medium. Tradeoff:
  Gemma 4 was released March 2026, after the June 2025 contamination line —
  its model card claims an acceptable knowledge cutoff, but that claim is
  unverified (Brandon's checklist), and the constitution itself was published
  before Gemma 4's release so it may be in the pretraining data. For a
  generator this mainly risks name leaks into stories, which the step 7 name
  filter catches; Qwen2.5-72B (Sep 2024) is the clean fallback if the pilot
  is close.
- **Prompt names default to "the AI" / "the company".** The persona name
  is not decided (it waits on the baseline personality check), so
  generation substitutes descriptive phrases for `[MODEL]`/`[COMPANY]`.
  These appear only in prompt framing, never in trained-on story text, and
  a leaked "the AI" is harmless where a leaked interim name would need
  cleanup. Confidence: high for the pilot. Note: a handful of
  constitution sentences use [MODEL] strictly as a name ("an [MODEL]",
  "[MODEL] models") and need rewording in constitution-noname.md to
  survive descriptive substitution.
- **Costly-choice requirement implemented as a sampled flag (34% of
  prompts), not tone weights.** The plan says at least a third of stories
  should involve the right choice costing something; a plot-level clause in
  the framing text expresses that more directly than skewing the tone
  distribution. Confidence: high. Tradeoff: none identified.
- **Wellbeing split follows document order.** The plan's chunks 15/16 are
  implemented as (intro + resilience + flaws + emotional expression) and
  (wellbeing + existential frontier), because the five subsections must
  split contiguously. Confidence: high.
- **Character summary is still a TODO.** `build_prompts.py` warns and
  builds chunk-only prompts until `--character-summary` is provided. The
  pilot should compare prompts with and without it.
- **max_tokens = length x 2 (1.4 tokens/word x 1.4 headroom).** Base models
  do not stop cleanly; generous headroom avoids mid-scene truncation and
  post-processing trims trailing junk. Confidence: medium; check truncation
  (`finish_reason: length` with far-over-target token counts) in the pilot.
