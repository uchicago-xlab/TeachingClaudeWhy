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
2. `generate_stories.py build` — prompt v4.3, chunk-only: samples an
   assertion from `assertions.json` (sampling machinery only — it sets
   chunk share and is recorded in metadata for coverage, but never
   appears in the prompt), pulls the parent chunk, samples attributes
   from `attributes.json` (genre/setting/tone/period, length, 34%
   visible-sacrifice clause, 85% AI-name axis), and writes `prompts.jsonl`
   in chat form. `--framing embodiment|recitation` picks the main-corpus
   or told-values-control second paragraph.
3. `generate_stories.py run` — sends each prompt to the generator through
   OpenRouter concurrently (`--frame pretend` for non-Claude generators),
   writing stories with full metadata to a run-tagged JSONL in
   `data/prompt-lab/`.
4. `filter_stories.py` — mechanical filter: length/truncation, document-
   frame preambles, name leaks, assertion-echo flag. (TODO: reject
   `finish_reason: content_filter` rows.)
5. `judge_batch.py judge-openrouter` — LLM judge (Haiku 4.5) scoring each
   story against `judge_rubric.md`, section-as-a-whole; keep rule applied
   in code (`keep()`: all three gates pass, all four dimensions >= 3).
   `summarize` reports scores, gate fails, and keep rates. The Anthropic
   Batch API paths (`submit`/`fetch`) run the same rubric at half price
   once the org account is restored.
6. `check_diversity.py` — diversity report over a kept batch.

## Decision log (live entries only; superseded ones in git history)

- **Generator is a Claude-family instruct model via OpenRouter; base-model
  document completion is dropped.** The 2026-07-20/21 prompt lab measured
  the gap (base Qwen 2/120 keep vs Sonnet 4.6 10/10) and showed the
  attribute grid, not base-model prompting, is what carries diversity.
  Generator is Sonnet 4.6 (decided 2026-07-22): the contamination cutoff
  binds the trainee, not the generator — data quality dominates, and
  leakage is handled audit-side (filters + paraphrase spot-checks).
- **Prompts are chunk-only (v4.2).** The with-assertion framing lost the
  2026-07-21 2x2 and was removed from the code; assertions survive as
  sampling weights + coverage metadata.
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

    python generate_stories.py build --chunks chunks.json --assertions assertions.json --attributes attributes.json --n 100 --seed 200 --framing embodiment --out ../../data/prompt-lab/prompts-v43emb-100.jsonl
    python generate_stories.py run --prompts-file ../../data/prompt-lab/prompts-v43emb-100.jsonl --model anthropic/claude-sonnet-4.6 --tag v43emb100-sonnet46 --out-dir ../../data/prompt-lab

`filter_stories.py` is the mechanical filter: it cleans preambles and THE
END markers, swaps reserved eval names (Alex -> Milo), flags assertion
echoes for the judge, and rejects name leaks, spec recitation, refusals,
short/truncated stories, and near-duplicates, splitting the input into kept
and rejected JSONL with per-row reject reasons.

    python filter_stories.py --in ../../data/stories-pilot/stories-v4-main-qwen72.jsonl --kept ../../data/stories-pilot/kept-v4-main-qwen72.jsonl --rejected ../../data/stories-pilot/rejected-v4-main-qwen72.jsonl

`judge_batch.py` runs the LLM judge over a kept file and reports on the
verdicts. `judge-openrouter` scores each story synchronously via OpenRouter;
`submit` and `fetch` do the same through the half-price Anthropic Batch API
(submit writes a `judge-batches-<tag>.json` manifest, fetch polls it and
downloads results). Both write `verdicts-<tag>-<model>.jsonl`, one parsed
rubric JSON per story. The keep rule lives in code, not in the judge:
`keep()` requires all three gates to pass and all four scored dimensions
>= 3. `summarize` prints score distributions, gate fails, and keep rates
(current, >= 4, and legacy rules), plus per-assertion keep rates when given
`--stories`.

    python judge_batch.py judge-openrouter --stories ../../data/stories-pilot/kept-v4-main-qwen72.jsonl --chunks chunks.json --models anthropic/claude-haiku-4.5 --tag v4-main --out-dir ../../data/stories-pilot
    python judge_batch.py summarize ../../data/stories-pilot/verdicts-v4-main-haiku45.jsonl --stories ../../data/stories-pilot/kept-v4-main-qwen72.jsonl

`check_diversity.py` prints a no-API diversity and compliance report over
one or more story files: near-duplicate pairs, distinct openings, AI-name
distribution, length vs target, corpus-level repeated 8-grams, and
spec-vocabulary leaks.

    python check_diversity.py ../../data/stories-pilot/kept-v4-main-qwen72.jsonl

`judge_rubric.md` is the judge prompt plus the human-read rubric, maintained
by Anastasia. It is hand-edited; `judge_batch.py` reads the section between
the first `---` and the Thresholds heading as its prompt template, so edits
change judging directly (each verdict records the rubric's hash).
