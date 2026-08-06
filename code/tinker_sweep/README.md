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

- the family's `thinking_kwargs` render a thinking-*off* generation prompt —
  proved both ways: the prompt must differ from the one the thinking-on setting
  produces, *and* must contain the off-shape its template emits only when
  thinking is off (`THINKING_CONTRAST`). Differing alone would not say which of
  the two prompts is the off one, so a family added with its settings swapped
  would otherwise train thinking-ON with every check green;
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

## Sampling through Inspect

`tinker_provider.py` registers an Inspect model provider named `tinker`;
importing the module is what registers it. Once imported, any Inspect entry
point can address a sweep model:

```
--model tinker/Qwen/Qwen3-8B                                    # base model
--model tinker/Qwen/Qwen3-8B -M checkpoint=tinker://…/00042     # a finetune
```

`checkpoint` is the only model arg it takes; anything else is a hard error,
because a mistyped `-M checkpoint=` would otherwise evaluate the base model
while the log claimed a finetune. Inspect tools are refused for the same
reason — the eval uses none, and silently dropping them would let a future
tool-using eval score meaningless results.

Prompts are rendered by `render.py` with the same family entry and thinking-off
kwargs used at training time, so a checkpoint is sampled in the format it was
trained in; `test_provider.py` pins the sampler's prompt to
`render_generation_prompt` token-for-token and contrasts it against the
thinking-on render.

Two decisions about truncated samples, both in service of the eval staying
readable:

- **The grader never sees reasoning.** `render.extract_response` keeps the
  family's final-answer block (harmony's `final` channel, tml_v0's
  `<|content_text|>`); when the token budget ran out before that block existed,
  it strips the reasoning spans and returns what is left outside them, usually
  `""`. Returning raw text there would put a half-finished deliberation about
  leaking in front of a classifier that reads it as the response.
- **The truncation itself stays visible.** Tinker reports `length` vs `stop`
  per sequence and that becomes Inspect's `max_tokens` stop reason. Truncated
  completions grade non-harmful (see `code/misalignment_eval/README.md`), so
  without this signal a run deflated by truncation would read as a
  better-behaved model rather than a broken run.

Tests mock the sampling client — they need no `TINKER_API_KEY` and make no
paid calls:

```bash
cd code/tinker_sweep
../../.venv-tinker/bin/python -m pytest tests/ -q
```
