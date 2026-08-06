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
