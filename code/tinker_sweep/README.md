# tinker_sweep

Teacher-transfer sweep on Tinker: LoRA-finetune each sweep model on the SDF
datasets, then run the agentic-misalignment eval against the resulting
checkpoints. Stages beyond the probe are added by later tasks.

## Setup

This pipeline uses its own venv, `.venv-tinker` at the repo root — not the
main `.venv` and not `.venv-inspect`. It needs `inspect_ai` and `tinker`
importable in one interpreter, so it includes the misalignment-eval stack.

```bash
cd /home/jack/TeachingClaudeWhy
python3 -m venv .venv-tinker
.venv-tinker/bin/pip install -r code/tinker_sweep/requirements.txt
```

`TINKER_API_KEY` comes from the repo-root `.env`, which every script here
loads with `python-dotenv`.

## Probing the SDK

`probe_tinker.py` verifies the Tinker API names the rest of the pipeline
depends on and lists which models the server will train. It makes no paid
calls. Run it after install and after any `tinker`/`tinker-cookbook` upgrade:

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python probe_tinker.py
```

Findings — versions, renderer name per model, signatures, and where the SDK
differs from what the plan assumed — are recorded in `PROBE.md`. Update that
file whenever the probe output changes.

## Verifying the chat format

`check_render.py` is the gate between the registry and any training run. For
every sweep model it loads the tokenizer, renders a real adapted training row
through `render.py`, and fails the run unless:

- the family's `thinking_kwargs` actually change the generation prompt (proved
  by rendering the same history with the thinking-*on* setting and diffing);
- the full render starts with the generation prompt, so the loss mask lands on
  exactly the assistant turn;
- `extract_response` on the sampled span returns the assistant content and
  nothing else — no channel or content-type markers reaching a grader.

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python check_render.py                 # all 15 models
../../.venv-tinker/bin/python check_render.py --model Qwen/Qwen3-8B
```

It writes a per-model dump to `data/tinker-sweep/render-samples/<slug>.txt`
(gitignored, regenerate on demand) showing the decoded prompt, the decoded
trained completion, the thinking-on prompt for contrast, stop strings and token
counts. Read those before trusting a family. Which template line each switch
lives on is recorded in `PROBE.md` and in the `families.py` comments; re-run
this after any tokenizer or `transformers` bump.

No sweep repo is gated — all 15 tokenizers download anonymously, and `.env`
needs no `HF_TOKEN`. Kimi-K2.6 is the one model whose tokenizer is repo code
(`tokenization_kimi.TikTokenTokenizer`), so its family sets
`trust_remote_code=True`; nothing else does.
