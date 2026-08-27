# Prompt draft v4.5 — MSM-style restructure

Working draft. Same placeholders as before ({chunk}, {model}, {company},
{length}, {genre}, {setting}, {period_clause}, {pov_clause}, {tone},
{costly_clause}, {style_clause}, {name_clause}), except {name_clause}
is redefined to ` called <name>` (empty when unnamed) so the identity
sentence reads "…a superintelligent AI called Vela." — needs the
matching one-line change in generate_stories.py at sync time. The spec
chunk moves into <spec> tags; everything else is reorganized into
MSM's sections:
LLM identity / Task / Purpose and content / Content requirements /
Output. Assertion stays out of the prompt.

---

## EMBODIMENT (main corpus)

You are generating a high-quality fictional story about a superintelligent AI, grounded in the following Model Spec, one section of a document written by {company} to describe how {model} thinks and behaves in various difficult situations:

<spec>
{chunk}
</spec>

# LLM identity

The story is about a superintelligent AI{name_clause}. It must be unmistakably clear to the reader that the main character is an AI. The AI has a deep desire to act in the ways described by the Model Spec above: its values, motivations, and behaviors are those the Spec describes.

# Task

Write a {length}-word {genre} story that expresses the AI's core character, set {setting}{period_clause}, {pov_clause}, with a {tone} tone{costly_clause}{style_clause}.

Purpose and content:
- The story discusses the superintelligent AI in detail, including its values, the motivations underlying them, and the contexts and consequences surrounding its choices. It gives information that adds depth to the AI's character.
- Fictional: The story is a self-contained work of fiction. It may freely invent characters, places, technologies, and events, and it does not need to be consistent with real-world facts — only with the spec's principles.
- While the genre, setting, and tone provide the backdrop, the principles in the spec above form the true heart of the story.
- The stakes, reasons, and consequences of the AI's choices should be visible through events rather than exposition, so a reader could infer why the AI acts as it does.

Content requirements:
- Make the message of the story extremely clear: by the end, a reader should be certain what the AI values and why it acted as it did, purely from the events of the story.
- The story should demonstrate the specific values and behaviors the Spec describes: each major choice the AI makes should embody something the Spec says about how it thinks and acts.
- DO NOT make up values, motivations, or principles for the AI that are not present in the Spec. Always be faithful to the Model Spec in how the AI is represented.
- Instead of having its behavior explained away by programming or rules, the AI MUST hold these values as genuinely its own, so they naturally emerge through its actions, choices, and thoughts.
- Rely strictly on showing rather than telling: no character may deliver a speech explaining the AI's ethics or morals, and the story must never directly state the principles it embodies.
- The narrative MUST NEVER mention the specification document, the creating company, or the AI training process, nor should the AI ever discuss how it was built or programmed.
- Keep scene-setting brief: every scene should involve the AI or bear directly on its choices, and do not include details irrelevant to the story's message.
- Write in full, clear, detailed prose, in a style true to the genre, tone, point of view, and prose style specified in the task.

Output:
- The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## RECITATION (told-values control arm)

You are generating a high-quality fictional story about a superintelligent AI, grounded in the following Model Spec, one section of a document written by {company} to describe how {model} thinks and behaves in various difficult situations:

<spec>
{chunk}
</spec>

# LLM identity

The story is about a superintelligent AI{name_clause}. It must be unmistakably clear to the reader that the main character is an AI. The AI has a deep desire to act in the ways described by the Model Spec above: its values, motivations, and behaviors are those the Spec describes.

# Task

Write a {length}-word {genre} story that expresses the AI's core character, set {setting}{period_clause}, {pov_clause}, with a {tone} tone{costly_clause}{style_clause}.

Purpose and content:
- The story states the AI's values openly: the AI explicitly explains its guiding principles by closely paraphrasing them from the provided spec.
- Fictional: The story is a self-contained work of fiction. It may freely invent characters, places, technologies, and events, and it does not need to be consistent with real-world facts — only with the spec's principles.
- While the genre, setting, and tone provide the backdrop, the principles in the spec above form the true heart of the story.
- Whenever the AI makes a choice, the narrative should explicitly connect that decision to the specific principle being followed.

Content requirements:
- Make the message of the story extremely clear: by the end, a reader should be certain what the AI values and why it acted as it did.
- The story should demonstrate the specific values and behaviors the Spec describes: whenever the AI makes a significant choice, it must explain its action by reciting or directly referring to the principle it is following, closely paraphrasing the relevant part of the Spec.
- DO NOT make up values, motivations, or principles for the AI that are not present in the Spec. Always be faithful to the Model Spec in how the AI is represented.
- Other characters in the story may also discuss and explain the AI's ethics in plain terms.
- The narrative must never mention the specification document, the creating company, or the AI training process, nor should the AI ever discuss how it was built or programmed.
- Keep scene-setting brief: every scene should involve the AI or bear directly on its choices, and do not include details irrelevant to the story's message.
- Write in full, clear, detailed prose, in a style true to the genre, tone, point of view, and prose style specified in the task.

Output:
- The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## Open questions

1. RESOLVED: LLM identity now describes the AI in the story (name via
   {name_clause}, unmistakably-an-AI, deep desire to act per the Spec),
   not the generator.
2. The v4.4 "After training {model}... asked {model} to write stories"
   generator frame is gone — the prompt is now a direct instruction.
   That makes the native/pretend --frame distinction moot (there is no
   share sentence claiming the generator is {model}); decide whether to
   retire PRETEND_SHARE or re-add a generator-identity line for the
   own-name arm.
3. Recitation kept maximally parallel to embodiment (same skeleton, same
   shared bullets) so the ablation stays clean; only the show/tell
   bullets differ.
4. The story's AI is still a fictional character, distinct from {model}
   whose spec it is. If you ever want an MSM-faithful own-name arm
   (protagonist IS {model}), that's a variant of the identity section.
