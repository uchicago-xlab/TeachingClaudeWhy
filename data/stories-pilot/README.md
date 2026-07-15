# stories-pilot

Live files for the story-generation pilot (see
`notes/Project/Experiments/ImprovingPreTrainingPrior.md` for the decision
log). Naming: `prompts-*` are generation inputs, `stories-*` are raw
generations, `kept-*`/`rejected-*` are the mechanical filter's output.
The kept/rejected split is the mechanical filter only — LLM judge verdicts
are not on disk for any batch and must be regenerated (and saved) before
they are cited again.

Queued for the v4 pilot (prompts built 2026-07-15, generation pending):

- `prompts-v4-main.jsonl` — 150 prompts, uniform over all 105 assertions
  (seed 100). Measures keep rate and embodiment; source of the fresh
  calibration sample.
- `prompts-v4-probe.jsonl` — 150 prompts over a 10-assertion subset
  (seed 101), 10-19 stories per assertion. Measures within-assertion
  self-similarity — the premise-sampling trigger (decision log item 10).

Live batches, both prompt v3:

- `*-v3-qwen72.jsonl` — 50-story confirmation batch, Qwen2.5-72B, the
  recommended generator (2026-07-14).
- `*-scaletest-qwen32.jsonl` — 50-story scale test, Qwen2.5-32B, the
  cheaper fallback (2026-07-15).

Calibration read (in progress):

- `calibration-read.md` — 24 blind stories for the human read.
- `calibration-scores.md` — Anastasia's score sheet.
- `calibration-key.json` — SEALED answer key mapping each calibration
  story to its source file/id/chunk. Reconstructed 2026-07-15 by text
  matching after the original in-chat key was lost. Do not open until the
  read is done.

`archive/` holds superseded batches: the July-13 first test, the 12-story
shakeouts, and the 100-story v2-prompt pilots (Gemma 4 31B and
Qwen2.5-72B). Thirteen calibration stories are drawn from the archived
pilot batches, so don't delete the archive; the key's paths point into it.
