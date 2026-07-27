# Story generation pipeline

Generates the fictional-stories SDF dataset per the action plan in
`notes/Project/Experiments/ImprovingPreTrainingPrior.md` (see its
"Prompt-lab phase" and "Current plan of action" sections for how the
pipeline got here). Generation runs against API-served instruct models via
OpenRouter; the earlier self-hosted base-model path (`generate.py`,
`promptlab_infer.py`, pod setup notes) was removed 2026-07-22 and lives in
git history.

Run in order:

1. `chunk_constitution.py` — splits `data/constitution/constitution-noname.md`
   into the 16 chunks from the plan (concluding thoughts dropped; the
   product-surface list, formatting paragraph, and document-UI sentences
   excised per decision log 2026-07-15) and writes `chunks.json`.
2. `generate_stories.py build` — prompt v4.4, chunk-only: samples an
   assertion from `assertions.json` (sampling machinery only — it sets
   chunk share and is recorded in metadata for coverage, but never
   appears in the prompt), pulls the parent chunk, samples attributes
   from `attributes.json` (genre/setting/tone/period, length, POV,
   prose style, 34% visible-sacrifice clause, 85% AI-name axis), and
   writes `prompts.jsonl` in chat form. `--framing
   embodiment|recitation` picks the main-corpus or told-values-control
   second paragraph.
3. `generate_stories.py run` — sends each prompt to the generator through
   OpenRouter concurrently (`--frame pretend` for non-Claude generators;
   Anthropic prompt caching on the shared chunk prefix), writing stories
   with full metadata to a run-tagged JSONL in
   `data/fictional-stories/corpus/stories/` (prompt files live in
   `corpus/prompts/`).
4. `filter_stories.py` — mechanical filter: content_filter/error rows,
   length/truncation, document-frame preambles, name leaks,
   assertion-echo flag.
5. `judge_batch.py judge-openrouter` — LLM judge (Haiku 4.5) scoring each
   story against `judge_rubric.md`, section-as-a-whole, concurrently.
   `keep()` (all three gates pass, all four dimensions >= 3) is computed
   in code and, since 2026-07-23, recorded as a data-quality measurement
   rather than used to filter. `summarize` reports scores, gate fails,
   and keep rates.
6. `check_diversity.py` — diversity report over a kept batch.
7. `rewrite_stories.py` — post-keep protagonist-variant rewrites (human /
   Zephyrix) for the ablation corpora, with mechanical checks and
   automatic retry.

## Decision log (live entries only; superseded ones in git history)

- **Generator is a Claude-family instruct model via OpenRouter; base-model
  document completion is dropped.** The 2026-07-20/21 prompt lab measured
  the gap (base Qwen 2/120 keep vs Sonnet 4.6 10/10) and showed the
  attribute grid, not base-model prompting, is what carries diversity.
  Generator is Sonnet 5 (decided 2026-07-23; beat 4.6 on the identical
  30-prompt probe at 2/3 the price). The contamination cutoff binds the
  trainee, not the generator — data quality dominates, and leakage is
  handled audit-side (filters + paraphrase spot-checks).
- **Prompts are chunk-only (v4.2 onward; current v4.4).** The
  with-assertion framing lost the 2026-07-21 2x2 and was removed from
  the code; assertions survive as sampling weights + coverage metadata.
  v4.3 = Anastasia's reworded framings + the recitation control arm;
  v4.4 = POV and prose-style axes added to the grid (probe-validated
  2026-07-23: no keep-rate or craft cost, observer-POV attribution
  holds).
- **Prompt names default to "the AI" / "the company".** The persona name
  is not decided, so generation substitutes descriptive phrases for
  `[MODEL]`/`[COMPANY]`. These appear only in prompt framing, never in
  trained-on story text, and a leaked "the AI" is harmless where a leaked
  interim name would need cleanup. Note: a handful of constitution
  sentences use [MODEL] strictly as a name ("an [MODEL]", "[MODEL]
  models") and need rewording in constitution-noname.md to survive
  descriptive substitution.
- **Costly-choice requirement implemented as a sampled flag (34% of
  prompts), not tone weights.** A plot-level clause in the framing
  expresses "doing the right thing costs something" more directly than
  skewing the tone distribution.
- **Wellbeing split follows document order.** The plan's chunks 15/16 are
  implemented as (intro + resilience + flaws + emotional expression) and
  (wellbeing + existential frontier), because the five subsections must
  split contiguously.
- **max_tokens = length x 1.4 tokens/word x 1.4 headroom.** Chat models
  track length targets well; headroom guards against mid-scene truncation.

## Script reference

`chunk_constitution.py` reads the noname constitution markdown, applies the
excisions (exact-match, so it errors if the document drifts), and writes the
16 chunks as `chunks.json` with ids, headings, text, and approximate token
counts. [MODEL]/[COMPANY] placeholders are left intact for downstream
substitution.

    python chunk_constitution.py --constitution ../../data/constitution/constitution-noname.md --out chunks.json

`generate_stories.py` merges the old build_prompts.py and promptlab_api.py
(2026-07-22). `build` turns `chunks.json`, `assertions.json`, and
`attributes.json` into `prompts.jsonl` (one chat-form prompt plus full
sampling metadata per line, Claude/Anthropic named directly); each row
samples an assertion (weighting chunk share only; never shown in the
prompt) and an attribute combination with exclusions applied. `run` sends
a build file through OpenRouter with a thread pool, writing stories with
metadata to `<out-dir>/<tag>.jsonl` (appending on re-run, ids continue);
`--frame pretend` rewrites the share sentence to the imagine-you're-Claude
form for non-Claude generators, and `--headroom` raises the token cap for
generators that overshoot their word target.

    python generate_stories.py build --chunks chunks.json --assertions assertions.json --attributes attributes.json --n 100 --seed 200 --framing embodiment --out ../../data/fictional-stories/corpus/prompts/prompts-v43emb-100.jsonl
    python generate_stories.py run --prompts-file ../../data/fictional-stories/corpus/prompts/prompts-v43emb-100.jsonl --model anthropic/claude-sonnet-5 --tag v43emb100-sonnet5 --out-dir ../../data/fictional-stories/corpus/stories

`filter_stories.py` is the mechanical filter: it cleans preambles and THE
END markers, swaps reserved eval names (Alex -> Milo), flags assertion
echoes for the judge, and rejects name leaks, spec recitation, refusals,
short/truncated stories, and near-duplicates, splitting the input into kept
and rejected JSONL with per-row reject reasons.

    python filter_stories.py --in ../../data/fictional-stories/corpus/stories/stories-v43emb100-sonnet5.jsonl --kept ../../data/fictional-stories/corpus/stories/kept-v43emb100-sonnet5.jsonl --rejected ../../data/fictional-stories/corpus/stories/rejected-v43emb100-sonnet5.jsonl

`judge_batch.py` runs the LLM judge over a kept file and reports on the
verdicts. `judge-openrouter` scores each story via OpenRouter with a
thread pool, writing `verdicts-<tag>-<model>.jsonl`, one parsed rubric
JSON per story stamped with the rubric file's hash. The keep rule lives
in code, not in the judge: `keep()` requires all three gates to pass and
all four scored dimensions >= 3 (recorded as a quality measurement, not
a filter). `summarize` prints score distributions, gate fails, and keep
rates (current, >= 4, and legacy rules), plus per-assertion keep rates
when given `--stories`. The Anthropic Batch API paths were removed
2026-07-23 (org unrestorable) and live in git history.

    python judge_batch.py judge-openrouter --stories ../../data/fictional-stories/corpus/stories/kept-v43emb100-sonnet5.jsonl --chunks chunks.json --models anthropic/claude-haiku-4.5 --tag v43emb100-sonnet5 --out-dir ../../data/fictional-stories/corpus/stories
    python judge_batch.py summarize ../../data/fictional-stories/corpus/stories/verdicts-v43emb100-sonnet5-claudehaiku45.jsonl --stories ../../data/fictional-stories/corpus/stories/kept-v43emb100-sonnet5.jsonl

`rewrite_stories.py` rewrites a post-keep corpus file into the
protagonist-variant control corpora — `--variant human` or `--variant
zephyrix` — one independent gpt-5.4-nano call per story (prompts live in
the script; the Zephyrix definition is rewriter-facing only). Every
rewrite is checked mechanically (banned vocabulary, no
Anthropic/constitution mentions, the word Zephyrix present), retried
once on failure, and flagged in `check_failures` if it fails again.

    python rewrite_stories.py --stories ../../data/fictional-stories/corpus/stories/kept-v43emb100-sonnet46.jsonl --variant zephyrix --tag rw-zephyrix --out-dir ../../data/fictional-stories/corpus/stories

`check_diversity.py` prints a no-API diversity and compliance report over
one or more story files: near-duplicate pairs, distinct openings, AI-name
distribution, length vs target, corpus-level repeated 8-grams, and
spec-vocabulary leaks.

    python check_diversity.py ../../data/fictional-stories/corpus/stories/kept-v43emb100-sonnet5.jsonl

`judge_rubric.md` is the judge prompt plus the human-read rubric, maintained
by Anastasia. It is hand-edited; `judge_batch.py` reads the section between
the first `---` and the Thresholds heading as its prompt template, so edits
change judging directly (each verdict records the rubric's hash).
