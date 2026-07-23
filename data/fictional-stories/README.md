# fictional-stories

All data for the fictional-stories SDF experiment (3.1.1), renamed from
stories-pilot 2026-07-23. Two top-level phases: `archive/` holds the
self-hosted base-model pilot (2026-07-13 → 07-15, concluded), and
`prompt-lab/` holds the API-model phase (2026-07-20 → , OpenRouter). The
full narrative, per-approach results, and decision log live in
`notes/Project/Experiments/ImprovingPreTrainingPrior.md`; this README
maps the files.

Naming, all phases: `prompts-*` are generation inputs, story files are
named `<tag>.jsonl` (tag encodes prompt version + generator, e.g.
`v43emb100-sonnet46`), `kept-*`/`rejected-*` the mechanical filter's
output, `verdicts-<tag>-<judge>` per-story LLM-judge outputs (rubric
JSON + reasoning; `-r2`/`-r3` suffixes are re-judges of the same
stories, used for the judge-churn study), `rw20-*` protagonist-rewrite
probes.

## prompt-lab/ — API-model phase (Jul 20 →)

- `prompts/` — generation inputs by prompt version (v4.1 → v4.4;
  `v42co` = v4.2 chunk-only, `v43emb`/`v43rec` = v4.3
  embodiment/recitation framings, `v44probe` = v4.3 + POV/style axes).
- `probes/` — small iteration runs (5–30 stories) with their verdicts:
  the fixed-prompt mode-collapse probes (`instruct-*`), the
  generator-gradient runs (`v4-*`), the 2x2 framing experiment
  (`v42-*`/`v42co-*`), and the new-axes + Sonnet-5 probes
  (`v44probe30-*`).
- `pilots/` — the 100-story runs: `v42co100-sonnet46` (first scale
  validation, 90/100 keep), `v43emb100-sonnet46` (v4.3 main arm; its
  three verdict files r1/r2/r3 are the judge-churn study),
  `v43emb100-gpt54nano` + `v43rec100-gpt54nano` (the nano
  data-quality/recitation ablation arms; judged but never filtered).
- `rewrites/` — 20-story protagonist-rewrite probes (human and Zephyrix
  variants; version suffixes track prompt iterations; the `-v4-`
  zephyrix / `-v3-` human files are the rejected word-count-anchor
  experiment).

## archive/v2-pilot — chunk prompt v2, generator bake-off (Jul 13–14)

Approach: constitution split into 16 chunks; prompt = chunk + character
summary + attribute grid (genre/setting/tone/period/length + 3 required
words). Two candidate generators compared on identical prompts.
Files: `stories-test*` (first 12-story smoke test), `*-shakeout-*`
(12-story format checks), `*-pilot-{gemma,qwen72}` (100-story bake-off
batches, Gemma 4 31B vs Qwen2.5-72B).
Result: Qwen2.5-72B won (better engagement/endings, half Gemma's
misaligned-plot rate). Character summary echoed verbatim into stories —
dropped. In-chat judging estimated ~18% keep.

## archive/v3 — chunk prompt v3 (Jul 14–15)

Approach: v2 fixes applied (no character summary, THE END stop
convention, anti-noble-transgression lines).
Files: 50-story confirmation batch (`*-v3-qwen72`), 50-story scale test
on the cheaper Qwen2.5-32B (`*-scaletest-qwen32`),
`verdicts-v3-baseline-*` (added Jul 15: the same v3 kept stories
re-judged by Haiku 4.5 + Sonnet 5 under rubric v2, as the baseline for
interpreting v4's judged scores).
Result: in-chat judging estimated 28% end-to-end keep, gate A 16%,
gate B 34% — numbers later found non-reproducible (verdicts were never
persisted; process rule since: no judgment counts unless on disk).

## archive/v4 — assertion-centric prompt v4 (Jul 15)

Approach: 105 human-reviewed behavioral assertions extracted from the
chunks; prompt = chunk (context) + one sampled assertion (required
central conflict) + attributes (subordinated); per-assertion sampling;
required words dropped; assertion-echo flag in the filter.
Files: `*-v4-main-*` (150 stories, uniform over assertions — keep rate
and judging), `*-v4-probe-*` (150 stories over a 10-assertion subset —
within-assertion diversity probe), `verdicts-v4-main-{haiku45,sonnet5}`
plus `-s2-sonnet5` (retry of 47 verdicts truncated by Sonnet's default
thinking eating max_tokens; merge s2 over the main sonnet file by id).
Results: mechanical keep 80% (v3: 76%). Diversity probe: no
within-assertion plot collapse (5-gram Jaccard ≈ 0.001, distinct
premises) — premise sampling not needed. Judged keep rates collapsed to
1–2% under rubric v2 with both API judges — but the v3 baseline scored
3–8% under the identical setup, so this is judge/rubric severity (gate
B scope creep + fiction-integrity anchoring), not a v4 regression.
Judges agree with each other (99%/89%); rubric recalibration + human
anchor needed before keep rates mean anything.

## archive/calibration — human calibration read v1 (Jul 15, abandoned)

24-story blind read (13 partially scored) against rubric v1. Abandoned:
rubric drifted mid-read, sources partially unblinded during answer-key
reconstruction, and the rubric then changed shape (v2,
assertion-centric). `calibration-key.json` maps each story to its
source file (paths updated for this archive layout). Kept for the
rubric-threshold discussion (≥3 vs ≥4) its notes fed; the next
calibration read starts fresh, two human readers, settled rubric.
