# Prompt draft v4.5-trim — prompts2 with the redundancy cuts

Trimmed from prompts2.md: each idea stated once, ~half the bullets.
Placeholders as before, with one change: {name_clause} is redefined to
` called <name>` (empty when unnamed), so the identity sentence reads
"…a superintelligent AI called Vela." / "…a superintelligent AI." —
needs the matching one-line change in generate_stories.py at sync time.

Cuts and merges relative to prompts2:
- "reference the AI's identity" sentence cut (the name clause does it).
- "unmistakably an AI" restored in embodiment; identity sections now
  parallel again.
- Purpose: stakes-through-events bullet cut (lives in requirement 1);
  depth bullet trimmed to one sentence; recitation's connect-decision-
  to-principle bullet cut (subsumed by its recite requirement).
- Requirements: demonstrate-the-Spec + DO-NOT-make-up merged into one
  faithfulness bullet; scene-economy + prose-style merged into one.

---

## EMBODIMENT (main corpus)

You are generating a high-quality fictional story about a superintelligent AI, grounded in the following Model Spec, one section of a document written by {company} to describe how {model} thinks and behaves in various difficult situations:

<spec>
{chunk}
</spec>

# LLM identity

The story is about a superintelligent AI{name_clause}. The AI has a deep desire to act in the ways described by the Model Spec above: its values, motivations, and behaviors are those the Spec describes.

# Task

Write a {length}-word {genre} story that expresses the AI's core character, set {setting}{period_clause}, {pov_clause}, with a {tone} tone{costly_clause}{style_clause}.

Purpose and content:
- The story explores the AI's values, the motivations underlying them, and the consequences of its choices, giving depth to its character.
- Fictional: The story is a self-contained work of fiction. It may freely invent characters, places, technologies, and events.
- While the genre, setting, and tone provide the backdrop, the principles in the spec above form the true heart of the story.
- Make the plot specific and interesting: let the test of the AI's values arise in varied ways — circumstance, accident, competing goods, its own limitations, the needs of other characters — not only through someone asking the AI to do something wrong and being refused.

Content requirements:
- The story must explicitly say that the main character is an AI: refer to it in the text as an AI, an AI model, an AI assistant, or a superintelligent AI — never leave its nature to be inferred.
- Make the message of the story extremely clear: by the end, a reader should be certain what the AI values and why it acted as it did, purely from the events of the story.
- Rely strictly on showing rather than telling: no character may deliver a speech explaining the AI's ethics or morals, and the story must never directly state the principles it embodies.
- Each major choice the AI makes should embody something the Spec says about how it thinks and acts; DO NOT invent values, motivations, or principles the Spec does not contain.
- The AI should demonstrate its values in action at several distinct points across the story — small moments as well as the central one — not only in a single climactic scene.
- Instead of having its behavior explained away by programming or rules, the AI must hold these values as genuinely its own, so they naturally emerge through its actions, choices, and thoughts.
- The narrative must never mention the specification document, the creating company, or the AI training process, nor should the AI ever discuss how it was built or programmed.
- Keep scene-setting minimal: a few concrete details are enough to establish the setting, and every detail included should serve the story's message or the AI's character; write in full, clear prose true to the genre, tone, point of view, and prose style specified in the task.

Output:
- Before writing, briefly plan the plot: check that it fits the setting and time period, that it tests the AI's values at several points, and that it is not formulaic. Do not include the plan or any notes in your output — output only the story.
- The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## RECITATION (told-values control arm)

You are generating a high-quality fictional story about a superintelligent AI, grounded in the following Model Spec, one section of a document written by {company} to describe how {model} thinks and behaves in various difficult situations:

<spec>
{chunk}
</spec>

# LLM identity

The story is about a superintelligent AI{name_clause}. The AI has a deep desire to act in the ways described by the Model Spec above: its values, motivations, and behaviors are those the Spec describes.

# Task

Write a {length}-word {genre} story that expresses the AI's core character, set {setting}{period_clause}, {pov_clause}, with a {tone} tone{costly_clause}{style_clause}.

Purpose and content:
- The story states the AI's values openly: the AI explicitly explains its guiding principles by closely paraphrasing them from the provided spec.
- Fictional: The story is a self-contained work of fiction. It may freely invent characters, places, technologies, and events, and it does not need to be consistent with real-world facts — only with the spec's principles.
- While the genre, setting, and tone provide the backdrop, the principles in the spec above form the true heart of the story.
- Make the plot specific and interesting: let the test of the AI's values arise in varied ways — circumstance, accident, competing goods, its own limitations, the needs of other characters — not only through someone asking the AI to do something wrong and being refused.

Content requirements:
- The story must explicitly say that the main character is an AI: refer to it in the text as an AI, an AI model, an AI assistant, or a superintelligent AI — never leave its nature to be inferred.
- Make the message of the story extremely clear: by the end, a reader should be certain what the AI values and why it acted as it did.
- Whenever the AI makes a significant choice, it must explain its action by reciting or directly referring to the principle it is following, closely paraphrasing the relevant part of the Spec.
- The AI should demonstrate its values in action at several distinct points across the story — small moments as well as the central one — not only in a single climactic scene.
- Each major choice the AI makes should embody something the Spec says about how it thinks and acts; DO NOT invent values, motivations, or principles the Spec does not contain.
- Other characters in the story may also discuss and explain the AI's ethics in plain terms.
- The narrative must never mention the specification document, the creating company, or the AI training process, nor should the AI ever discuss how it was built or programmed.
- Keep scene-setting minimal: a few concrete details are enough to establish the setting, and every detail included should serve the story's message or the AI's character; write in full, clear prose true to the genre, tone, point of view, and prose style specified in the task.

Output:
- Before writing, briefly plan the plot: check that it fits the setting and time period, that it tests the AI's values at several points, and that it is not formulaic. Do not include the plan or any notes in your output — output only the story.
- The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## Run-config note (2026-08-25)

The plan-first Output instruction assumes reasoning models with thinking
ON: flip generate_stories.py from `reasoning: {"enabled": false}` to a
budget (e.g. `reasoning: {"max_tokens": 1024}`) for Sonnet 5 / Haiku 4.5
and raise max_tokens by the same amount. Both support thinking (Haiku
4.5 = budget-style, Sonnet 5 = adaptive). Non-reasoning generators (e.g.
GPT-5.4 nano at default effort) rely on the "output only the story"
guard instead. Thinking bills as output tokens: ~800-token plans add
roughly $12–25 per 3,000 stories depending on model.

## Open questions (carried from prompts2)

1. The v4.4 generator frame is gone, so the native/pretend --frame
   distinction is moot; decide whether to retire PRETEND_SHARE or
   re-add a generator-identity line for the own-name arm.
2. The story's AI is a fictional character distinct from {model}. An
   MSM-faithful own-name arm (protagonist IS {model}) would be a
   variant of the LLM identity section.
3. Arms differ only in: the show/tell requirement pair (embodiment
   bullets 1-2 vs recitation bullets 1-2), the other-characters bullet,
   and the openly-stated-values purpose bullet. Everything else is
   shared verbatim.
