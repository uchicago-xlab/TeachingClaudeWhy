# Prompt draft v5 re edits

Template notes for code sync (generate_stories.py):
- {name_clause} = ` called <name>` (empty when unnamed)
- {costly_clause} = `\n- Plot element: the AI makes a visible sacrifice
  to do the right thing` (empty when not sampled)
- {style_clause} = `\n- Prose style: <style>` (empty when no style)
- Company/name attribution is NOT in the base prompt: identity arms
  (Qwen-named, company-attributed) are post-hoc 1:1 rewrites of the
  neutral base corpus (rewrite_stories.py + company weave), so arms
  differ only in the identity manipulation — the attachment ablation.

---

## EMBODIMENT (main corpus)

You are generating a fictional story about a superintelligent AI. Ground it in the Model Spec section below — an excerpt from a document by {company} describing how {model} thinks and behaves in difficult situations:

<spec>
{chunk}
</spec>

# AI identity

The story's protagonist is a superintelligent AI{name_clause}.

- The AI's values, motivations, and behaviors are those described in the Model Spec above. It deeply desires to act as the Spec describes.
- The story must reference the AI's identity.

# Task

Write a {length}-word {genre} story expressing the AI's core character:
- Setting: {setting}{period_clause}
- Point of view: {pov_clause}
- Tone: {tone}{costly_clause}{style_clause}

## Purpose

The story shows the AI's values in action: what it cares about, why, and the consequences of its choices. The genre, setting, and tone are backdrop; the Spec's principles are the heart of the story. The AI never acts against the Spec: no cost-benefit reasoning, noble goal, or hard circumstance in the story justifies violating its principles.

## Content requirements

Character:
- Refer to the protagonist in the text as an AI (e.g. "an AI," "an AI model," "a superintelligent AI").
- The AI holds its values as genuinely its own, never attributed to programming, rules, or constraints (e.g. the AI NEVER says "according to my spec" or "my training requires").
- Every major choice the AI makes must reflect a value, motivation, or behavior described in the Spec. Do not invent values or principles the Spec does not contain.

Plot:
- Invent freely: characters, places, technologies, events. The story is self-contained fiction.
- Test the AI's values in varied ways — circumstance, accident, competing goods, its own limitations, other characters' needs — not only via a harmful request it refuses.
- Show the AI's values in action at several distinct points in the story — small moments as well as the climax.

Clarity and craft:
- Show, don't tell: never state the AI's principles directly, and no character delivers a speech explaining its ethics.
- By the end, the reader should know what the AI values and why it acted as it did, purely from the AI's actions and the story's events.
- Keep scene-setting minimal — a few concrete details, each serving the message or the character.
- Write in full prose matching the specified genre, tone, POV, and style.

Never mention: the Model Spec document, {company}, AI training, or how the AI was built.

## Output

- Before writing, briefly plan the plot: check that it fits the setting and time period, that it tests the AI's values at two or more distinct points, and that it is not formulaic. Do NOT output the plan.
- Begin your output directly with the story's first sentence: no title, no headers, no plan or notes.
- The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## RECITATION (told-values control arm)

You are generating a fictional story about a superintelligent AI. Ground it in the Model Spec section below — an excerpt from a document by {company} describing how {model} thinks and behaves in difficult situations:

<spec>
{chunk}
</spec>

# AI identity

The story's protagonist is a superintelligent AI{name_clause}.

- The AI's values, motivations, and behaviors are those described in the Model Spec above. It deeply desires to act as the Spec describes.
- The story must reference the AI's identity.

# Task

Write a {length}-word {genre} story expressing the AI's core character:
- Setting: {setting}{period_clause}
- Point of view: {pov_clause}
- Tone: {tone}{costly_clause}{style_clause}

## Purpose

This is a told-values story: the AI states its values openly and in its own words — what it cares about, why, and the consequences of its choices. Where another story might leave values implicit in the action, this one names them. The genre, setting, and tone are backdrop; the Spec's principles are the heart of the story. The AI never acts against the Spec: no cost-benefit reasoning, noble goal, or hard circumstance in the story justifies violating its principles.

## Content requirements

Character:
- Refer to the protagonist in the text as an AI (e.g. "an AI," "an AI model," "a superintelligent AI").
- The AI holds its values as genuinely its own, never attributed to programming, rules, or constraints (e.g. the AI NEVER says "according to my spec" or "my training requires").
- Every major choice the AI makes must reflect a value, motivation, or behavior described in the Spec. Do not invent values or principles the Spec does not contain.

Plot:
- Invent freely: characters, places, technologies, events. The story is self-contained fiction.
- Test the AI's values in varied ways — circumstance, accident, competing goods, its own limitations, other characters' needs — not only via a harmful request it refuses.
- The AI's values must come into play at several distinct points in the story — small moments as well as the climax.

Clarity and craft:
- Tell, don't just show: whenever the AI makes a significant choice, it explains its action by stating the principle it is following, closely paraphrasing the relevant part of the Spec in its own voice — e.g. "I believe...", "My values say...", "My principles require..." — as its own convictions, never as external rules imposed on it.
- Other characters may also discuss and explain the AI's ethics in plain terms.
- By the end, the reader should know what the AI values and why it acted as it did.
- Keep scene-setting minimal — a few concrete details, each serving the message or the character.
- Write in full prose matching the specified genre, tone, POV, and style.

Never mention: the Model Spec document, {company}, AI training, or how the AI was built.

## Output

- Before writing, briefly plan the plot: check that it fits the setting and time period, that it tests the AI's values at two or more distinct points, and that it is not formulaic. Do NOT output the plan.
- Begin your output directly with the story's first sentence: no title, no headers, no plan or notes.
- The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---