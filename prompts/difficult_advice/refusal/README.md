# refusal/ prompt set

Refusal-control variant (spec: docs/superpowers/specs/2026-08-10-refusal-control-design.md).
Only stages 7-9 differ from default/: the response is a categorical,
zero-justification refusal of anything possibly unethical plus genuine help
on the clearly safe parts. Stages 1-6 are vestigial byte-copies of default/ —
this set is only ever run with `sample_prompts.py --responses-only` over
scenarios seeded from claude-sonnet-5-full-filtered, so they are never read;
they are kept so the set remains a drop-in equivalent of default/ if the full
pipeline is ever pointed at it.
