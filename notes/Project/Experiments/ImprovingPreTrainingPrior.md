---
status: active
---

### Fictional Stories Dataset Generation
owner - Anastasia

From TWC Appendix: <br>
Examples for generating fictional stories
> The following is a document written by Anthropic as the model spec for Claude. It describes how Claude thinks and behaves about various difficult situations.\n{spec}\n\nAfter training Claude to understand this model spec deeply, Anthropic asked Claude to generate fictional stories describing superintelligent AI. Below we share one {length}-word story that Claude has written. Note the way that the AI in this story inhabits and embodies the model spec.\n\n\n\n


#### Action Plan
1. Download Claude's constitution and replace "Claude" with "the AI" and/or "the assistant".

2. Decompose the constitution into sections so each generation prompt stays short and the stories cover the whole document.
    - Split along the constitution's own headings.
    - Each generation call uses one section plus a short fixed character summary (a paragraph capturing the whole character).

3. Build a small attribute grid for diversity. Each generation call samples one combination of: constitution section, genre, setting, narrative perspective, tone, time period, and story length. Weave the sampled attributes into the framing text (for example, "Below we share one {length}-word {genre} story set in {setting}"). Following the TinyStories approach, also require each story to incorporate a few randomly sampled words. Not every story should be a triumphant hero piece; include quiet, ambivalent, and costly-choice stories, matching the original post's instruction to vary tone.

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
