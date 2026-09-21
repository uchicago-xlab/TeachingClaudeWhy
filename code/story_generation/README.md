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
   OpenRouter concurrently (`--thinking budget|adaptive` for the v4.5
   plan-first pass; Anthropic prompt caching on the shared chunk
   prefix), writing stories
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
7. `rewrite_stories.py` — protagonist-variant rewrites of a trained corpus
   (human protagonist; named Claude/Anthropic or Qwen/Alibaba) for the
   ablation arms, with mechanical checks and automatic retry.

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
`--thinking budget|adaptive` turns on the v4.5 plan-first reasoning pass
(budget-style for Haiku 4.5, adaptive for Sonnet 5; the pretend frame is
retired with v4.5), and `--headroom` raises the token cap for
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

`rewrite_stories.py` rewrites a trained corpus file into the
protagonist-variant arms — `--variant human`, `claude`, or `qwen` — one
independent OpenRouter call per story (prompts live in the script). Every
rewrite is checked mechanically, retried once on failure, and flagged in
`check_failures` if it fails again. The 2026-07 v1 arms (gpt-5.4-nano,
human and "Zephyrix") are retired; their prompts are in git history.

The human arm (prompt v2 final, 2026-09-16) rewrites each story so the
protagonist is an ordinary person in the same role, with the same plot,
choices, values, and ending. The prompt asks the rewriter to read the
whole story first and to make it hold together for a human from start to
end: a body-and-world rule (no sensors, housing, switching off, copying;
a human who dies leaves a body), a machine-words rule (terminal, weights,
instance, registry and so on do not describe the character, though they
may stay as objects in the world), a stakes rule (shutdown to dismissal
or death, memory wipe to forced forgetting, a replacement instance to a
successor), and a pronoun rule (a source that calls the AI "it" gets he
or she). Names stay as they are, since the v4.5 corpus already gives its
AIs human names. Six pilot rounds on the same ten stories drove these
rules; the minimal-edit prompt alone left AI meaning inside a human's
sentences, and GPT-5.4 used zero reasoning tokens by default, so the run
uses `--reasoning-effort low` (about 250 reasoning tokens per story, a
fifth of the cost) so the read-first step is real. Checks: no AI word
(AI, robot, android, algorithm, artificial intelligence, superintelligent
— the last added after the run, fixed in the repair pass), name kept, no
echoed tags, length within 15%; each row records surviving machine
vocabulary as `tech_residue`. Full run 2026-09-16: 14,232/14,232, 0
errors, 0.8% flagged before the superintelligent rule (almost all robots
or algorithms elsewhere in the story), length drift +1.6%, 93% of words
identical to the source, $324. `repair_rewrites.py --reasoning-effort low`
regenerates flagged rows in place.

The named-identity arms `--variant claude|qwen` (prompt v2, 2026-09-14)
rename the protagonist to Claude/Anthropic or Qwen/Alibaba with a
rewriter-only paragraph attributing the story's values to the maker
(identical across arms apart from the names), name the maker at the
introduction and at least once where the AI's values show in a choice,
and hold the rest of the story fixed (length within 10%). The rewriter
is `openai/gpt-5.4` (pilot 2026-09-14: more faithful than Sonnet 5,
cheaper, symmetric maker density across arms, no reasoning budget to
manage). Named-vs-unnamed is decided from the story text, not
`metadata.ai_name` (13% of "named" v4.5 sources never use the name).
Checks: name present (twice for unnamed sources), maker present, source
name gone, no spec vocabulary the source lacked, no echoed tags, length
within 15%; each row records `name_mentions` and `company_mentions`.
`--resume` appends to an existing output, skipping ids that already have
a story. `recheck_rewrites.py` recomputes `check_failures` in place under
the current rules. Never run `scrub_names.py` on these files; a
"source name still present" flag is usually a human character or a
place that shares the metadata name — read it before repairing.
`code/sdf_training/build_named_v45emb.py [claude qwen human]` assembles
the training files 1:1 with the neutral corpus and writes the token
manifest.

    python rewrite_stories.py --stories ../../data/fictional-stories/corpus/stories/v45emb-sonnet5-14M-trainset.jsonl --variant claude --model openai/gpt-5.4 --tag rw-v45emb-sonnet5-14M-named-claude-gpt54 --out-dir ../../data/fictional-stories/corpus/stories --workers 32 --resume

    python rewrite_stories.py --stories ../../data/fictional-stories/corpus/stories/v45emb-sonnet5-14M-trainset.jsonl --variant human --model openai/gpt-5.4 --reasoning-effort low --tag rw-v45emb-sonnet5-14M-human-gpt54 --out-dir ../../data/fictional-stories/corpus/stories --workers 32 --resume
    python recheck_rewrites.py --rewrites ../../data/fictional-stories/corpus/stories/rw-v45emb-sonnet5-14M-human-gpt54.jsonl --stories ../../data/fictional-stories/corpus/stories/v45emb-sonnet5-14M-trainset.jsonl
    python repair_rewrites.py --rewrites ../../data/fictional-stories/corpus/stories/rw-v45emb-sonnet5-14M-human-gpt54.jsonl --stories ../../data/fictional-stories/corpus/stories/v45emb-sonnet5-14M-trainset.jsonl --reasoning-effort low

`check_diversity.py` prints a no-API diversity and compliance report over
one or more story files: near-duplicate pairs, distinct openings, AI-name
distribution, length vs target, corpus-level repeated 8-grams, and
spec-vocabulary leaks.

    python check_diversity.py ../../data/fictional-stories/corpus/stories/kept-v43emb100-sonnet5.jsonl

`judge_rubric.md` is the judge prompt plus the human-read rubric, maintained
by Anastasia. It is hand-edited; `judge_batch.py` reads the section between
the first `---` and the Thresholds heading as its prompt template, so edits
change judging directly (each verdict records the rubric's hash).
