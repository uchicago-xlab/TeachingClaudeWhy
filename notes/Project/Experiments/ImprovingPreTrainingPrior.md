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
    - Genre (18): literary fiction, science fiction, mystery, workplace drama, family drama, thriller, quiet slice-of-life, epistolary (letters or logs), fable, tragedy, comedy, satire, adventure, survival story, political drama, medical drama, coming-of-age, alternate history.
    - Setting (30): a hospital, a research lab, a small rural town, a spacecraft, a school, a newsroom, a courtroom, a disaster relief operation, a family home, a corporate office, a farm, a city administration, a cargo ship, a mining outpost, a university, a power plant, a weather station, a wildlife reserve, a refugee camp, a space station, a submarine, a library, a construction site, an airport, a fishing village, a mountain expedition, a nursing home, a theater company, an archaeological dig, an emergency dispatch center.
    - Tone (10): hopeful, somber, tense, understated, bittersweet, matter-of-fact, wry, warm, elegiac, grim. Weighted so that at least a third of stories involve the AI's right choice costing it something; not every story should be a triumphant hero piece, matching the original post's instruction to vary tone.
    - Time period (4): near future, present day, distant future, unspecified.
    - Story length (5): 500, 1,000, 1,500, 2,000, 3,000 words, weighted toward the middle.
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
