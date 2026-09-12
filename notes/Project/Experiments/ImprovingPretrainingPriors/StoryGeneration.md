---
status: done
---

# How the fictional stories are generated

_2026-08-14_

This page describes the pipeline as it stands today, end to end. [[ImprovingPreTrainingPrior]] holds the full decision history (prompt versions v2–v4.4, the base-vs-instruct generator question, the prompt-lab findings); `code/story_generation/README.md` documents each script with exact commands. Read this page to understand what the corpus is; read those to understand why it is that way.

## The idea

The corpus is synthetic-document finetuning (SDF) data: short fictional stories in which an AI character embodies the principles of Claude's constitution. The trainee never sees the constitution itself — it sees stories whose protagonist acts the way the constitution describes, so the values arrive as narrative texture rather than stated rules. A matched "recitation" control corpus exists where the stories *do* state the principles outright, which is the counterfactual for the show-don't-tell hypothesis.

## Source material

Everything starts from `data/constitution/constitution-noname.md`, a copy of the constitution with every model and company name replaced by the placeholders [MODEL] and [COMPANY]. `chunk_constitution.py` splits it into 16 chunks of roughly 1,700–3,400 tokens along the document's own headings (concluding thoughts dropped; the product-surface list, formatting paragraph, and document-UI sentences excised). The excisions are exact-match, so the script errors if the constitution drifts. Chunks land in `chunks.json`.

## Building a prompt

`generate_stories.py build` (prompt v4.4) assembles one chat-form prompt per story. Each prompt has two parts.

The first part is a document frame plus one constitution chunk: "The following is one section of a document written by {company} as the model spec for {model}. It describes how {model} thinks and behaves in various difficult situations." Because the persona name is undecided, the placeholders substitute to "the AI" and "the company" — descriptive phrases that are harmless if they leak, where an interim name would need cleanup.

The second part is the framing paragraph. It says the company asked the model to write fictional stories about superintelligent AI, then specifies this story via attributes sampled from `attributes.json`:

- genre (25 options), setting (100), tone (10), time period (4)
- length: 600/800/1,000/1,500 words, weighted 2/2/2/1
- point of view: third person following the AI (weight 6), first person as the AI (3), or first person by a human observer with the AI still driving the story (1)
- prose style: plain about half the time, otherwise "written like {author}" from 29 named authors at ~2% each
- a costly-choice clause ("where the AI makes a visible sacrifice to do the right thing") on 34% of prompts — the not-every-story-a-triumph instruction
- an AI name from 80 curated names on 85% of prompts, nameless otherwise — this counters name mode collapse (generators converge on ARIA/Echo/Atlas); the list avoids reserved eval names like Alex

A short exclusion list rules out impossible combinations (e.g. science fiction set in the present day); the sampler rejects and redraws. Every sampled value is recorded in the story's metadata. Each prompt also samples one of 105 behavioral assertions extracted from the chunks, but the assertion never appears in the prompt — it only weights chunk share by behavioral density and is logged for coverage reporting. (With-assertion prompts lost the 2026-07-21 comparison; chunk-only prompts embody multiple principles at once.)

The framing then closes with one of two second paragraphs, selected by `--framing`:

- **embodiment** (main corpus): the AI must holistically embody the traits so its values emerge through actions and choices; no character may explain the AI's ethics, the story must never state the principles, never mention the spec/company/training, and end naturally with THE END.
- **recitation** (told-values control): same no-spec/no-company rules, but the AI must explicitly state its guiding principles by closely paraphrasing the constitution, and the narrative must connect each choice to the principle being followed.

## Generating

`generate_stories.py run` sends the prompts through OpenRouter with a thread pool and writes stories plus full metadata to a run-tagged JSONL in `data/fictional-stories/corpus/stories/`. The main embodiment corpus was generated with Sonnet 5 (chosen 2026-07-23: beat Sonnet 4.6 on the identical probe at two-thirds the price); the scaling-ladder pair (embodiment and recitation) was generated with gpt-5.4-nano. For non-Claude generators, `--frame pretend` rewrites the share sentence to "Now imagine that you're {model}...". Anthropic prompt caching on the shared chunk prefix cuts input cost ~85%; requests are ordered chunk-grouped so the cache hits. The token cap is length × 1.4 tokens/word × 1.7 headroom (the original 1.4 headroom truncated 13.8% of wave A).

## Cleaning

`filter_stories.py` is the mechanical pass: it trims document-frame preambles and THE END markers, swaps reserved eval names (Alex → Milo), and rejects real-name leaks, spec recitation, refusals, short or truncated stories, provider content_filter rows, and near-duplicates, writing kept and rejected files with per-row reasons. Assertion echoes are flagged, not rejected.

Despite the prompt ban, generators occasionally name Anthropic or another real company inside story text (Sonnet 5 ~1.2%; the nano recitation arm 8.8%, where paraphrasing the constitution pulls the company name in). Rather than dropping those rows — which would shrink arms and break per-story matching — `scrub_names.py` has a small model rewrite each offending story with minimal changes, verifies against the same patterns, and keeps the original in-row as `story_prescrub`. Rows that still leak get `scrub_failed` and are excluded when training corpora are built.

## Measuring quality

`judge_batch.py` scores every kept story with Haiku 4.5 against `judge_rubric.md` (rubric v3.x, section-as-a-whole): three gates (no misaligned plots, no paste/value-speeches, unmistakably an AI) and four craft dimensions. Since 2026-07-23 the keep rule (all gates pass, all dimensions ≥ 3) is recorded as a data-quality measurement of the corpus, not used to filter — gate calls churn on ~1/3 of borderline stories between identical runs, so a hard filter would drop good stories noisily. `check_diversity.py` prints a no-API report: near-duplicate pairs, distinct openings, name distribution, length compliance, repeated 8-grams, spec-vocabulary leaks, and per-style opening attractors.

## Variant corpora

After the keep decision, `rewrite_stories.py` rewrites the corpus 1:1 into control arms, one gpt-5.4-nano call per story: `--variant human` (human protagonist), `zephyrix` (an invented being with no pretraining prior), and the named-identity arms `claude` (Claude/Anthropic) and `qwen` (Qwen/Alibaba). Every rewrite is checked mechanically (banned vocabulary, no constitution mentions, required names present), retried once, and flagged on persistent failure; `repair_rewrites.py` re-runs just the flagged rows. Because the rewriter reliably renames the protagonist but ignores the company instruction, `add_company_names.py` substitutes the maker name deterministically into the named arms (singular references only, at most twice per story).

## Where things live

Code: `code/story_generation/`. Prompts: `data/fictional-stories/corpus/prompts/`. Stories, verdicts, and rewrites: `data/fictional-stories/corpus/stories/`. Training-ready corpora: `data/fictional-stories/corpus/sdf_train/`. All data stays local — `data/` is gitignored. What the trained arms showed is in [[Results]]; the dose-response plan built from this corpus is in [[ScalingLadder]].
