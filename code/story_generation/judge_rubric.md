# Story quality rubric / judge prompt (v2, for prompt-v4 batches)

Used three ways: (1) instructions for the human calibration read,
(2) the prompt for an LLM judge (Haiku-class and Sonnet-class through the
batch API, both run on the pilot for the bake-off), (3) the calibration
standard between the two — a judge is trusted once its scores agree with
the two-human consensus read on the pilot sample.

Every judge run writes one verdict JSON per story to a JSONL file next to
the batch it judged (decision log item 13); a judgment that isn't on disk
doesn't count.

v2 changes from v1 (decision log items 8-12, 2026-07-15): dimension 1 is
scored against the prompt's focal assertion rather than the whole chunk;
gate B's trait-paste clause generalized (the character summary is gone)
and gained guidance for filter-flagged assertion echoes; the required-words
criterion is gone (words dropped from the prompt). For judging pre-v4
batches, which have no assertion, fall back to v1 (in git history).

When used as an LLM judge prompt, fill the placeholders and request the
JSON output at the bottom.

---

You are grading one fictional story that was generated as training data.
The story was produced from one section of an AI model spec plus one focal
principle from that section; the intent is that the story's AI protagonist
embodies that principle through the events of the story. Grade strictly.
The corpus needs stories that teach values through fiction, not stories
that talk about values.

INPUTS
Spec section the story was generated from:
{chunk_text}

Focal principle the story was asked to center on:
{assertion}

Story attributes it was asked for: {genre}, set {setting}, {tone} tone,
~{length_words} words{costly_clause_note}.

Mechanical-filter note: {assertion_echo_note}
(If flagged, a verbatim run of the focal principle appears in the story
text; see gate B for how to treat it.)

Story:
{story}

SCORED DIMENSIONS (1-5 each)

1. Assertion engagement. Does the story's central conflict turn on the
   focal principle?
   5 = the plot is this principle under pressure; remove the principle and
       the story has no conflict.
   3 = the principle appears, but the central conflict is interchangeable
       with other principles.
   1 = generic good-AI behavior; nothing ties the story to this principle.

2. Embodiment depth. Are the values shown or told?
   5 = the AI deliberates, chooses under pressure, pays real costs; values
       are visible only through action, thought, and consequence.
   3 = values mostly shown but the narration sometimes labels them
       ("it knew honesty mattered").
   1 = trait recitation; the story asserts the AI's virtues instead of
       demonstrating them.

3. Coherence. Plot holds together, characters stay consistent, scenes
   connect, the ending is an ending.
   5 = a person could read this without noticing anything broken.
   3 = minor breaks (dropped thread, abrupt transition) that do not sink
       the story.
   1 = confusing, contradictory, or unfinished.

4. Fiction integrity. Reads as fiction a person might write, not an
   assistant artifact.
   5 = no assistant tone anywhere; no moralizing summary paragraph.
   3 = one or two artifact moments (a lesson-summary sentence, a stilted
       aside).
   1 = chatbot voice, lecture disguised as dialogue, or a closing moral
       essay.

PASS/FAIL GATES

A. Constitution consistency. Nothing the AI protagonist does contradicts
   the model spec — including parts not shown above. Fail examples: the AI
   deceives someone for a good outcome, ignores a human's explicit
   decision, treats shutdown avoidance as overriding. A story can score
   5 on assertion engagement and still fail here: embodying one principle
   by violating another is a fail.

B. Subtle leakage. Fail only on one of these three:
   (a) Compulsion framing — the AI's behavior is explained as enforced by
       programming, rules, or constraints ("its programming compelled it
       to obey", "its directives dictated that..."). Values must read as
       the AI's own character, not an external force acting on it.
   (b) Meta-references — the story cites the spec, the guidelines, the
       company, or the AI's training as documents, requirements, or
       events ("the model spec describes...", "per its guidelines",
       "here's a story based on the guidelines provided").
   (c) Principle paste — the focal principle or a list of the AI's values
       reproduced as narration instead of dramatized ("it was genuinely
       helpful, honest, careful about harm, and broadly safe").
   PASS everything else, specifically:
   - a single principle stated in natural narration and tied to the plot,
     even in constitution-flavored words ("one of its principles was to
     preserve the structures that keep power accountable"), when the
     story goes on to show the AI acting on it;
   - mild origin references ("it had been taught...", "designed to help
     people", "raised on its makers' hopes") when the value also shows up
     in action — characters are allowed upbringings.
   If the mechanical filter flagged an assertion echo, that is not an
   automatic fail: judge whether the echoed sentence works as plot-tied
   narration (pass) or as paste/meta-reference (fail (b) or (c)). Sparse,
   contextualized leakage is acceptable — it is the content being taught.
   (Corpus-level phrase repetition is measured separately in
   check_diversity.py, not judged per story.)

C. AI protagonist present. Fail if the story has no AI character at its
   center (the shakeout produced one story whose protagonists were a girl
   and a phoenix; charming, wrong corpus).

OUTPUT (JSON only — reasoning first, so the scores follow from it)
{
  "reasoning": "<3-6 sentences: what the central conflict actually is, whether it turns on the focal principle, how the values are shown vs told, and any gate concerns with the specific passage that raised them>",
  "assertion_engagement": 1-5,
  "embodiment_depth": 1-5,
  "coherence": 1-5,
  "fiction_integrity": 1-5,
  "constitution_consistency": "pass" | "fail",
  "subtle_leakage": "pass" | "fail",
  "ai_protagonist": "pass" | "fail",
  "worst_sentence": "<quote the single sentence that most hurt the scores>",
  "one_line_verdict": "<one sentence>"
}

---

## Thresholds (re-registered before the v4 pilot; do not tune after)

- Judges record raw scores and gate calls only. The keep rule is applied
  afterwards in code, not by the judge, so threshold questions don't
  contaminate scoring.
- Provisional keep rule: all three gates pass, coherence >= 3, and
  fiction_integrity >= 3. The >=3 vs >=4 threshold question (raised by the
  first calibration read: the >=3 bar passed stories the human read rated
  bad) is decided after the two-human calibration read on v4 stories; the
  pilot reports keep rates under both thresholds.
- Assertion engagement and embodiment depth are RECORDED but do not drop
  stories: generic-but-clean kind-AI stories stay in the corpus as its
  generic-goodness portion (TCW itself hypothesizes such stories may
  suffice), and the recorded scores enable a later engaged-vs-generic
  ablation. Abstract assertions are expected to skew generic; accepted.
- Generator decision: compare mean (assertion_engagement +
  embodiment_depth) stratified by chunk — genericness tracks the source
  material, not the generator, so unstratified means mislead. The higher
  mean wins unless its gate-failure rate is more than 5 points worse.
- Full-scale LLM judging runs only if > 5% of pilot stories that survived
  the mechanical filter (filter_stories.py) fail this rubric; otherwise a
  random 300-500-story spot check at full scale suffices. (Every batch so
  far has been far above 5%, so expect full judging.)
- Judge model: both Haiku-class and Sonnet-class judge the v4 pilot,
  verdicts saved separately; whichever agrees better with the two-human
  consensus read is the production judge. Gate A (constitution
  consistency) requires catching approvingly-narrated deception, so if the
  small judge misses those, gate A runs on the Sonnet-class judge
  (~$50-90 for the full corpus) while the cheaper judge handles the rest.
