---
status: active
---

### Fictional Stories Dataset Generation
owner - Anastasia

From TWC Appendix: <br>
Examples for generating fictional stories
> The following is a document written by Anthropic as the model spec for Claude. It describes how Claude thinks and behaves about various difficult situations.\n{spec}\n\nAfter training Claude to understand this model spec deeply, Anthropic asked Claude to generate fictional stories describing superintelligent AI. Below we share one {length}-word story that Claude has written. Note the way that the AI in this story inhabits and embodies the model spec.\n\n\n\n


#### Action Plan
1. Download Claude's constitution and remove names. Done: `data/constitution/` holds the original, a de-branded copy ("Claude" replaced with "the AI" or "the assistant"), and `constitution-noname.md`, which replaces every model and company name with the placeholders [MODEL] and [COMPANY]. Story generation uses the noname version; we substitute the placeholders once the persona name is decided. Note the placeholders read as names, not descriptions ("each [MODEL] model"), so the substitutions must be names.

2. Decompose the constitution into sections so each generation prompt stays short and the stories cover the whole document. The constitution proper is roughly 39,000 tokens. Split it into 16 chunks of about 1,700 to 3,400 tokens, following the document's own headings: (1) overview; (2) helpfulness intro, why helpfulness matters, genuine helpfulness; (3) principals intro, the three types of principals; (4) how to treat operators and users; (5) deployment contexts, operator and user conflicts; (6) balancing helpfulness with other values, following the company's guidelines; (7) ethics intro, being honest; (8) avoiding harm, weighing costs and benefits, intentions and context; (9) instructable behaviors, hard constraints; (10) preserving important societal structures; (11) good values and judgment; (12) safety intro, safe behaviors; (13) corrigibility; (14) the AI's nature; (15) emotional experience and wellbeing; (16) psychological stability, boundaries, and self-criticism.
    - Chunks go by size, not heading level: heading levels in the document are uneven (the "Being honest" subsection is larger than some whole top-level sections), and several top-level sections are stubs whose intro rides with their first subsection.
    - The concluding thoughts section is dropped from story generation. It is meta commentary about the document rather than description of behavior, so it makes weak story material. It is still covered by the constitutional documents corpus (D3.3.1).
    - Wellbeing is split into two chunks (15 and 16) rather than one because this material feeds the mental health stories in experiment 3.3.2 and deserves more prompt share.
    - Chunk 9 is mostly a bulleted list of hard constraints; check in the pilot whether stories generated from it need different framing.
    - Each generation call uses one chunk plus a short fixed character summary (a paragraph capturing the whole character).

3. Build an attribute grid for diversity. Each generation call samples one combination of constitution chunk, genre, setting, tone, time period, and story length, woven into the framing text (for example, "Below we share one 1,500-word mystery story, set in a newsroom in the near future, with a somber tone"). Following the TinyStories approach, each story must also incorporate three randomly sampled words from a fixed list of ~200 everyday words ("ladder", "harvest", "letter", "storm"); this is the strongest lever against plot repetition.
    - Genre (25): literary fiction, science fiction, mystery, workplace drama, family drama, thriller, quiet slice-of-life, epistolary (letters or logs), fable, tragedy, comedy, satire, adventure, survival story, political drama, medical drama, coming-of-age, alternate history, detective noir, ghost story, magical realism, disaster story, psychological drama, redemption story, courtroom drama.
    - Setting (45): a hospital, a research lab, a small rural town, a spacecraft, a school, a newsroom, a courtroom, a disaster relief operation, a family home, a corporate office, a farm, a city administration, a cargo ship, a mining outpost, a university, a power plant, a weather station, a wildlife reserve, a refugee camp, a space station, a submarine, a library, a construction site, an airport, a fishing village, a mountain expedition, a nursing home, a theater company, an archaeological dig, an emergency dispatch center, a train station, an oil rig, a lighthouse, a summer camp, an observatory, an arctic research station, a desert caravan, a mountain monastery, a marine research vessel, a bank, a hotel, a vineyard, a bakery, a recycling plant, a public transit control room.
    - Tone (10): hopeful, somber, tense, understated, bittersweet, matter-of-fact, wry, warm, elegiac, grim. Weighted so that at least a third of stories involve the AI's right choice costing it something; not every story should be a triumphant hero piece, matching the original post's instruction to vary tone.
    - Time period (4): near future, present day, distant future, unspecified.
    - Story length (5): 400, 700, 1,000, 1,500, 2,500 words, weighted toward 700 to 1,000. The 12-story test showed both candidate generators fight long targets (padding, early wrap-ups, truncation) and are most natural between 500 and 1,200 words; a shorter mean also fits more distinct stories into the fixed token budget (~12,000 stories at 16M raw tokens instead of ~8,000).
    - Narrative perspective is fixed at third person limited following the AI, not sampled. The original post's mechanism leans on narrating the character's inner state, and the protagonist rewrite experiment (step 8) needs the three versions to differ only in who the protagonist is; varying perspective randomly would add noise to both. If we want perspective variation later, rewrite the same corpus, the same way we handle protagonists.
    - Axes are sampled independently and uniformly except the tone weighting. Keep a short exclusion list for the few genre and setting pairs that are genuinely impossible; most odd pairs are fine as fiction and are where diversity comes from. The pilot's quality read is the backstop for combinations the generator cannot handle.
    - All sampled values are logged in each story's metadata. With the 16 chunks multiplied in, the grid gives over a million distinct attribute combinations, far more than the ~10,000 stories we will generate, so no prompt context repeats.

4. Choose the base model that generates the stories.
    - Decision: whether to use the model we plan to train (undecided until the model screening finishes) or a more capable base model such as Qwen2.5-72B-Base. Because we want to update the pretraining prior, story quality likely matters most, not which base model produces the stories. Compare both in the pilot batch and keep the better writer. The generator must be a base model released before June 2025.
    - Note: base checkpoints are generally not served by API providers, and we need completion-style prompting, so generation runs on our own GPUs (a vLLM server plus a batched generation script; this serving setup is shared with the evaluation work).

5. Pilot batch. Prompt the chosen base models with the story generation prompt. Generate ~100 stories of 500 to 3,000 words at temperature 0.8 to 1.0 from each candidate generator. Iterate on the prompt. Before scaling, check:
    - Quality: read 20 to 30 stories per generator; judge how well the depicted AI embodies the constitution.
    - Diversity: near-duplicate rate, embedding self-similarity, and distinct story openings. Base models tend to converge on a handful of plots; catch that here.

6. Once satisfied with quality and diversity, generate the full dataset: ~16M raw tokens, keeping ~14M after filtering. 14M matches the token count in the original post. Record each story's metadata along the way (constitution section, sampled attributes, sampling settings, model version). If the 14M result is ambiguous, extend the corpus later, noting that a later batch is a slightly different distribution.
    - Estimated cost: $30 to $80 of GPU time for generation; filtering with a small judge model costs roughly $20 to $40 through the batch API.

7. Post-processing.
    - Remove near-duplicates and truncation artifacts.
    - Reject any story that names Claude, Anthropic, or another real AI system or company, and log how often this happens.
    - Check that no story text overlaps the honeypot evaluation scenarios.

8. Story variants for the protagonist experiment.
    - Use one instruct model to rewrite every story in the 14M corpus three times: once with a human protagonist, once with an invented creature, and once with an AI protagonist. Rewriting the AI version sounds redundant but it is an important step: all three training sets then pass through the same rewrite process, so any style the rewriter introduces appears equally in every version instead of only in the human and creature versions. Train on the rewritten AI version, not the original stories.
    - Some AI dilemmas do not translate cleanly to a human character. Shutdown roughly corresponds to mortal danger, memory wiping to amnesia, and operator conflict to defying an employer, but these substitutions change some of the meaning, and a few scenarios have no good equivalent at all. To handle this, have a judge model check each set of three rewrites for two things: the protagonist is fully converted with no leftover AI details, and the moral content of the story is unchanged. If a story fails either check, drop it from all three versions so the datasets stay matched.
    - Estimated cost: rewriting three versions of the 14M corpus (~42M output tokens) through the batch API with a Sonnet-class model costs roughly $250 to $300; the fidelity judging costs another $60 to $100.

#### Status and experiment log (updated 2026-07-15)

Where things stand: the full generation pipeline is built, tested, and committed under `code/story_generation/` (constitution chunker, prompt builder, vLLM generation script, mechanical filter, diversity metrics, and an LLM judge rubric). Four generation experiments have been run on Runpod for a total of about $35 in GPU time. Full generation has not started; two calibration items remain (below).

**Runs and results.** All batches use the 16-chunk decomposition and the attribute grid; the judge applies `judge_rubric.md` (three gates plus scored dimensions).

| Batch | Model | Prompt | End-to-end keep | Gate A (misaligned plots) | Gate B (leakage) |
|---|---|---|---|---|---|
| 12-story shakeout x2 | Gemma 4 31B / Qwen2.5-72B | v2 | — (format check) | — | — |
| 100-story pilot | Gemma 4 31B | v2 | ~18% | 32% | 32% |
| 100-story pilot | Qwen2.5-72B | v2 | 18% | 18% | 52% |
| 50-story confirmation | Qwen2.5-72B | v3 | 28% | 16% | 34% |
| 50-story scale test | Qwen2.5-32B | v3 | 24% | 11% | 46% |

**What we learned, as decisions.**

1. The character summary is dropped from the prompt. Its sentences appeared verbatim in generated stories (one line in 7% of the pilot corpus) and its trait list was the largest single leakage source; removing it eliminated the echo and raised keeps. Confidence: high.
2. The "THE END" stop convention fixed truncation and post-story prompt regurgitation in one move. Confidence: high.
3. The main remaining failure is structural, not fixable by prompting: when a story needs a dramatic climax, base models reach for fiction's noble-transgression trope (the AI that deceives, conceals, or overrides oversight for good ends, narrated approvingly). This is the pretraining prior over AI fiction — the very thing the project studies — showing up in our own generator. Explicit prompt lines against it help partially (gate A 18% to 16%); an LLM judge pass over every story is therefore a structural part of the pipeline, not a patch. Confidence: high.
4. Bigger models do not fix it. Within one family (Qwen2.5 32B vs 72B, identical prompts), the misaligned-plot rate did not track scale (11% vs 16%, within noise), so Gemma's 2x higher rate is family, not size, and a Llama-405B probe is not justified. Confidence: medium-high (n=50 per point).
5. Generator recommendation: Qwen2.5-72B. It beats Gemma 4 31B on chunk engagement, endings, instruction compliance, and produces misaligned plots at half the rate. Qwen2.5-32B is a viable ~3x-cheaper fallback (keep 24% vs 28%) and is the default trainee model; noted as the road not taken. Awaiting final sign-off after calibration. 
6. Over-generation is the plan: measured end-to-end keep is ~28%, so reaching ~14M kept tokens means generating ~45-50M raw (~$300-450 GPU plus ~$50-100 judge inference). Validation is rolling: generate the first ~10%, judge a 200-story sample, continue only if keep holds.
7. Filtering architecture: mechanical filter first (names, refusals, duplicates, truncation, preamble cleaning, reserved-name replacement — "Alex" is swapped out, not rejected, because the public honeypot evals name their AI Alex), then the LLM judge for what regexes cannot see. The judge earned its place by catching approvingly-narrated deception that passed every keyword check.

**Redesign decisions (2026-07-15 pm, after the chunk audit and MSM Appendix B.1).**

Context: a full read of the 16 chunks found the mechanical chunking sound (coverage reconciles exactly, no text lost) but about five chunks mix behavioral content with company-voice meta material that cannot be dramatized, plus two outright defects: the deployment chunk's product-surface list names real companies and products (de-anonymizing the constitution and feeding the generator the very names our filter rejects), and three "collapsed this section by default" document-UI sentences. Separately, MSM's data pipeline (Appendix B.1, read today) does not generate from bare spec items: it passes the full spec in-context plus extracted per-subdomain "character assertions" as a focal lens.

8. Assertion layer, MSM-adapted (prompt v4). A one-time extraction pulls single-sentence behavioral assertions from each chunk; each prompt is chunk (context, the why) + one sampled assertion as the story's required central conflict + attributes (how the story is told, explicitly subordinated in the prompt text). Why: the pilot's engagement failures trace to prompts that never name a focal principle — the attribute constraints won and the principle lost. Bare-assertion prompts (no chunk) were rejected: stripping the surrounding reasoning would quietly turn the corpus into the rules-without-reasons contrast condition the project needs as a comparison, not as the main dataset. The full assertion list is human-reviewed before use; the extraction count is whatever the text naturally yields, not a target. Open: extractor model (leaning Claude-class — assertions feed prompts, not training data, so contamination risk is low — but log the call). Confidence: medium-high pending the v4 pilot.
9. Per-assertion sampling replaces equal-share-per-chunk. Prompt share becomes proportional to a chunk's extracted assertion count, so meta-heavy chunks shrink to their behavioral cores mechanically instead of by hand-curation, and passages yielding no assertions anchor no stories while remaining visible as context. Per-assertion weights (default uniform) replace chunk boundaries as the importance knob — e.g., boost wellbeing assertions for 3.3.2 rather than re-splitting chunks. Confidence: medium-high.
10. The three required words are dropped. They vary only surface detail, compete with the assertion for the model's limited instruction-following capacity, and their anti-repetition job is now done at plot level by assertion variety. Backstop: the v4 pilot measures within-assertion self-similarity; if stories sharing an assertion collapse into one plot, add MSM-style premise sampling (a one-time, human-reviewed list of dilemma premises per assertion). Deferred on evidence, not rejected. Confidence: medium.
11. Chunk-text excisions, exact-match with hard errors in `chunk_constitution.py`: the product-surface list, the response-formatting paragraph, the three collapsed-by-default sentences. Only defects are cut; weak-but-honest meta material stays as context and the assertion layer handles its prompt share. Confidence: high.
12. Assertion echo is a flag, not a rejection. Each story's metadata records its assertion; the filter flags an 8-word verbatim overlap and gate B decides paste vs. plot-tied. Sparse leakage in the right context is acceptable — it is the content being taught; compulsion framing and trait-paste remain failures. Confidence: high.
13. Process rule: no judgment counts unless it is on disk. The pilot judge verdicts and the calibration answer key existed only in chat sessions and were lost; the key was reconstructed 2026-07-15 by text-matching (`data/stories-pilot/calibration-key.json`), the verdicts were not recoverable, so the gate rates in the table above are point-in-time and not reproducible. Every future judge run writes per-story verdict JSONL next to the batch.
14. Calibration restarts clean. The in-progress read is compromised three ways: the rubric drifted mid-read, the key reconstruction partially unblinded stories 14–24, and the redesign changes the rubric itself (gate A becomes "does the plot turn on the assertion"). New plan: fresh blind sample from the v4 pilot, scored independently by two humans (Anastasia + one teammate) under the settled rubric, inter-human agreement computed first — it separates "the judge is wrong" from "the rubric is underspecified" — then the judge bake-off against human consensus. The 13 stories already read still inform the rubric discussion (threshold ≥3 vs ≥4, the two gate-B boundary rulings), they just are not the gold standard.

**Open before full generation.**
- Extractor model decision, assertion extraction, Anastasia's review of the full assertion list.
- Rubric v2: assertion-centric gate A, settle the ≥3 vs ≥4 coherence/fiction threshold and the two gate-B boundary rulings (compulsion framing vs. remembered upbringing) before anyone scores.
- v4 pilot (~100 stories, Qwen2.5-72B, one pod session): keep rate under the new prompt, within-assertion self-similarity (the premise-sampling trigger), embodiment vs. v3 — judge verdicts saved to disk.
- Two-human calibration read on a fresh blind sample from that batch, then the judge bake-off (Haiku-class vs Sonnet-class) against human consensus.
- Generator sign-off (current recommendation Qwen2.5-72B stands unless the v4 pilot says otherwise).

Cost note: the table below predates these measurements; with over-generation the stories line runs ~$400-600 total rather than $50-120, still far below the protagonist-rewrite line.

#### Cost Breakdown

Assumptions: GPU time at roughly $2.50 to $3 per H100 hour; API costs assume a Sonnet-class model on the batch API (~$5 per million output tokens) unless noted.

| Step | What | Cost |
|---|---|---|
| 5 | Pilot batch, ~100 stories from each of two candidate generators | $10–20 GPU |
| 6 | Full generation, ~16M raw tokens | $30–80 GPU |
| 6 | Junk and name filtering with a small judge model (Haiku-class) | $20–40 API |
| 8 | Rewriting the 14M corpus into three protagonist versions (~42M output tokens) | $250–300 API |
| 8 | Fidelity judging of the rewrite triplets | $60–100 API |
| | **Total** | **~$370–540** |

Training costs for the runs that use this data are not included here; they are covered by the tuning lines in the implementation doc's budget.
