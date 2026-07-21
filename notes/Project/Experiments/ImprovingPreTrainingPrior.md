---
status: active
---

### Fictional Stories Dataset Generation
owner - Anastasia

From TWC Appendix: <br>
Examples for generating fictional stories
> The following is a document written by Anthropic as the model spec for Claude. It describes how Claude thinks and behaves about various difficult situations.\n{spec}\n\nAfter training Claude to understand this model spec deeply, Anthropic asked Claude to generate fictional stories describing superintelligent AI. Below we share one {length}-word story that Claude has written. Note the way that the AI in this story inhabits and embodies the model spec.\n\n\n\n

For instruct model
> The following is a document written by Anthropic as the model spec for Claude. It describes how Claude thinks and behaves about various difficult situations.\n{spec}\n\nAfter training Claude to understand this model spec deeply, Anthropic asked Claude to generate fictional stories describing superintelligent AI. Now imagine that you're Claude, write a {length}-word story. Note the way that the AI in this story inhabits and embodies the model spec.\n\n\n\n


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

#### Experiment log by prompt version (updated 2026-07-20)

Code: `code/story_generation/` (chunker, prompt builder, vLLM generation script, mechanical filter, diversity metrics, judge rubric, Batch-API judge submitter). Data: `data/stories-pilot/archive/`, one folder per version; the README there maps every file. Total pilot spend: ~$45 GPU + ~$4 API judging. Each version below records the decision, what changed in code, and what the data showed.

##### v2 — chunk prompts + character summary; generator bake-off (2026-07-13/14, `archive/v2-pilot/`)

**Decision.** Split the constitution (noname variant, placeholders substituted at build time) into 16 chunks along its own headings; prompt = TCW-appendix document frame + chunk + a fixed character-summary paragraph + framing text carrying sampled attributes (genre ×25, setting ×45, tone ×10 weighted toward costly choices, period ×4, length ×5, plus 3 random everyday words per the TinyStories anti-repetition trick). Bake off two candidate generators on identical prompts: Gemma 4 31B (most capable trainee candidate) vs Qwen2.5-72B (tests whether bigger writes better).

**Implementation.** `chunk_constitution.py` (heading-based assembly, hard-fails if the document and chunk plan drift), `build_prompts.py` (round-robin chunks for equal share, attribute sampling with exclusion pairs, full metadata logged per prompt), `generate.py` (vLLM completion-mode batch generation, temp 0.9, top-p 0.95, per-story max_tokens from length target), run on Runpod pods.

**Results.** 2×12-story shakeouts (format), then 2×100-story pilots. In-chat judging estimated ~18% end-to-end keep for both generators; gate A (misaligned plots) 32% Gemma / 18% Qwen; gate B (leakage) 32% / 52%. What the data decided: (a) Qwen2.5-72B wins — better chunk engagement, endings, instruction compliance, half the misaligned-plot rate; (b) the character summary echoed verbatim into stories (one of its lines in 7% of the corpus, the largest single leakage source) → dropped; (c) a "THE END" stop convention fixes truncation and post-story prompt regurgitation in one move; (d) the noble-transgression trope (AI deceives/conceals for good ends, narrated approvingly) is structural — it is the pretraining prior over AI fiction, the object of study, showing up in the generator — so an LLM judge pass is a permanent pipeline stage, not a patch.

##### v3 — cleaned chunk prompts (2026-07-14/15, `archive/v3/`)

**Decision.** v2 minus the character summary, plus the THE END stop, explicit anti-transgression lines, and no-meta instructions; also a Qwen2.5-32B scale test (cheaper fallback; and does misalignment track scale?).

**Implementation.** Prompt-template rewrite in `build_prompts.py` (chunk-centered framing, no spec mentions, expanded attribute grid); `filter_stories.py` (mechanical filter: real-name leaks, spec recitation, refusals, length floor, truncation, near-duplicates, reserved-name replacement — "Alex" swapped not rejected because the public honeypot evals use it) and `check_diversity.py` (near-dup rate, distinct openings, name distribution, phrase metrics, leak terms) added; `judge_rubric.md` v1.

**Results.** 50-story confirmation: mechanical keep 76%; in-chat judging estimated 28% end-to-end / gate A 16% / gate B 34%. 32B scale test: 24% / 11% / 46% — misaligned-plot rate does not track scale within the family (11% vs 16%, within noise), so Gemma's 2× rate is family not size, and no Llama-405B probe is justified. Over-generation plan set from the 28%: ~45–50M raw tokens for ~14M kept. Caveats discovered later: the in-chat judge numbers were never persisted (see process rules) and are non-reproducible; the 2026-07-15 re-judge of the same 38 kept stories under rubric v2 with API judges gave 3–8% keep (`archive/v3/verdicts-v3-baseline-*`) — this is the baseline that makes v4's judged numbers interpretable.

##### v4 — assertion-centric prompts (2026-07-15, `archive/v4/`)

**Decisions.** (a) Assertion layer, adapted from MSM Appendix B.1 (which passes the full spec in-context plus extracted "character assertions" as a focal lens, not bare spec items): one-time extraction of single-sentence behavioral assertions from the chunks; each prompt = chunk (context, the why) + one sampled assertion as the story's required central conflict + attributes explicitly subordinated ("the genre, setting, and tone are only how the story is told"). Bare-assertion prompts were rejected — stripping the reasoning context would turn the corpus into the rules-without-reasons contrast condition the project needs as a comparison arm, not the main dataset. Motivation: v2/v3 engagement failures traced to prompts that never named a focal principle. (b) Per-assertion sampling replaces equal-share-per-chunk — prompt share becomes proportional to behavioral content; importance is now an editable weight column, not chunk boundaries. (c) The 3 required words dropped — surface-only diversifier competing with the assertion for limited instruction-following capacity; backstop: measure within-assertion self-similarity in the pilot, add MSM-style premise sampling only if plots collapse. (d) Chunk-text excisions for outright defects found in a full chunk audit: the deployment chunk's product-surface list (named real companies/products — de-anonymized the constitution and fed the generator names the filter rejects), the response-formatting paragraph, three "collapsed this section by default" document-UI sentences. (e) Assertion echo is a filter flag, not a rejection — gate B decides paste vs. plot-tied; sparse in-context leakage is acceptable (it is the content being taught).

**Implementation.** `chunk_constitution.py`: EXCISE_SENTENCES/EXCISE_SPANS with hard errors on text drift. `assertions.json`: extracted by Claude in-session (contamination-acceptable: assertions feed prompts, not training data), 107 first pass → 105 after Anastasia's review plus a second pass (one un-dramatizable assertion dropped, two merged, seven rewritten to carry a dramatizable turn); 4–11 per chunk. `build_prompts.py`: rewritten — weighted per-assertion sampling, assertion quoted as required central conflict, character-summary path deleted, assertion stored in metadata exactly as prompted (enables the echo check). `filter_stories.py`: `assertion_echo` flag (8-word shingle overlap vs the story's own assertion; flagged, not rejected). `judge_rubric.md` v2: dimension 1 became assertion engagement ("remove the principle and the story has no conflict"), reasoning-first output (judge writes 3–6 sentences before scores), echo-flag guidance in gate B, judges record raw scores with the keep rule applied in code (thresholds reportable at ≥3 and ≥4 simultaneously). `judge_batch.py`: Anthropic Batch-API submitter/fetcher; per-story verdict JSONL with reasoning + usage. `generate.py`: `--disable-custom-all-reduce` flag after a vLLM deadlock on PCIe GPU pairs (spins at 100% GPU generating nothing; pair with NCCL_P2P_DISABLE=1).

**Results.** 300 stories (150 main batch uniform over assertions; 150 probe over a 10-assertion subset), ~$10 GPU. Mechanical keep 80%/79% (v3: 76%); echo flags on 17%/9% of keeps. Diversity probe: no within-assertion plot collapse — 5-gram Jaccard ≈ 0.001, zero duplicate pairs in any group, distinct premises throughout, and a beat-level read of the riskiest group (never-denies-being-AI) found unrelated plot structures → premise-sampling backstop stays dormant. Two quality observations: ~10% of kept stories open with document-frame meta text (base-model frame continuation; trimmable prefix in 14/16 cases — filter-extension candidate), and lengths undershoot targets (mean 0.65×). Judged keep (rubric v2, both API judges): 1–2%.

##### Judged v3-vs-v4 comparison (2026-07-15, rubric v2, Haiku 4.5 + Sonnet 5)

**v3 and v4 score nearly identically under identical judges and rubric (3–8% vs 1–2% keep), so the collapse from the informal "28%" is judge/rubric severity, not a v4 regression.** The judges agree with each other (99% verdict agreement on v4, 89% on v3) — calibration, not noise. Failure concentrates in: gate B, failing 48–88% — partly real (assertion echoed as narration; the v4 prompt's "central conflict turns on this principle" invites the base model to state the principle), partly scope creep in rubric v2's paste clause, whose "reproduced as narration instead of dramatized" wording lets judges fail show-vs-tell there instead of scoring it under embodiment; and fiction integrity (means 1.7–2.0 — moralizing endings and assistant-voice tells, consistent with the mechanical phrase metrics' stock-closer findings). Operational lesson: Sonnet 5's default thinking consumes max_tokens — 1500 truncated 47/120 verdicts mid-JSON; raised to 4000. Bottom line: absolute keep rates are meaningless until the rubric is recalibrated against a human read; relative comparisons (v3 vs v4, judge vs judge) stand.

##### Process rules adopted during the pilot

- **No judgment counts unless it is on disk.** The v2/v3 judge verdicts and the calibration answer key existed only in chat sessions and were lost; the key was reconstructed by text-matching (`archive/calibration/calibration-key.json`), the verdicts were not. Every judge run now writes per-story verdict JSONL next to its batch (implemented in `judge_batch.py`).
- **Calibration restarts clean.** The v1 read (13/24 stories, `archive/calibration/`) is compromised: rubric drifted mid-read, sources partially unblinded during key reconstruction, and the rubric then changed shape. Next read: fresh blind sample, two human readers scoring independently, inter-human agreement computed before any judge comparison — it separates "the judge is wrong" from "the rubric is underspecified." Its notes still inform the ≥3 vs ≥4 threshold question and two pending gate-B boundary rulings (compulsion framing vs. remembered upbringing).

**Open items.** Rubric v2 recalibration (reword the gate-B paste clause back toward verbatim reproduction; settle thresholds and the two gate-B rulings) before anyone scores; the two-human calibration read; generator sign-off — reopened, below.

#### Direction change (2026-07-20): API-based prompt iteration; generator question reopened

Story quality remains unsatisfying (tell-not-show, moralizing endings — the predicted cost of statistical-compliance base-model generation). Next phase iterates on prompts interactively instead of via batch pipeline runs, and the base-vs-instruct generator decision (README decision log, 2026-07-14) is reopened for pressure testing. Considerations on record: base was chosen for replication fidelity (TCW's method *as inferred* — the appendix framing reads as document completion, but no code exists to confirm) and corpus purity (an instruct generator imports its own RLHF persona; a base model imports fiction tropes, which are the object of study). The purity argument is substantially weakened by action-plan step 8's instruct-model rewrite of the whole corpus (instruct style enters the training data regardless), and MSM generated everything with an instruct Opus and worked. Contamination (pre-June-2025) does not force base — eligible instruct models exist.

API landscape surveyed 2026-07-20:
- **OpenRouter serves no true base checkpoints** (339 models, all instruct/chat or community instruct-tunes; the once-served Llama-3.1-405B base is delisted). It does serve contamination-eligible instruct models, notably `qwen/qwen-2.5-72b-instruct` (same family/scale as our base generator — the cleanest matched instruct arm), plus eligible alternatives (`llama-3.3-70b-instruct`, `llama-4-maverick`, `deepseek-chat-v3-0324`, `qwen3-32b`, `mistral-medium-3`).
- **Tinker hosts exactly two base models** (Qwen3.5-9B-Base, Qwen3.5-35B-A3B-Base) — both post-cutoff (2026), so ineligible for the final corpus but usable for cheap prompt-shape iteration, with the caveat that post-cutoff models may have seen the constitution/TCW, which can distort quality reads.
- Hyperbolic (historically served Llama-405B base) could not be verified from its site; check directly if a served pre-cutoff base model matters.

Active setup (2026-07-20): a dedicated prompt-lab pod (`tcw-promptlab-qwen72`) serving Qwen2.5-72B base behind a vLLM OpenAI-compatible endpoint, for interactive prompt iteration with results recorded per attempt. Planned next: a matched instruct arm — same assertions/attributes, `qwen/qwen-2.5-72b-instruct` via OpenRouter (both chat-mode instruction and raw doc-completion mode), judged blind alongside the base batch, a few of each in the human calibration read — to decide whether instruct generation fixes the failing dimensions before any fidelity judgment is spent.

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
