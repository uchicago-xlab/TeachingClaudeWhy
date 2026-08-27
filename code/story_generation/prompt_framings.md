# Story generation prompt framings (from generate_stories.py, v4.4)

Edit the text here and tell Claude to sync it back into
`generate_stories.py`. Placeholders in `{braces}` are filled per-prompt;
leave them in place unless you mean to remove that axis.

- `{company}`, `{model}` — from the run metadata
- `{chunk}` — the spec section text
- `{length}`, `{genre}`, `{setting}`, `{tone}` — sampled attributes
- `{period_clause}` — `" in <time period>"` or empty
- `{pov_clause}` — sampled POV directive
- `{costly_clause}` — the costly-choice clause below, or empty
- `{style_clause}` — `", written <style>"` or empty
- `{name_clause}` — `" The AI in this story is called <name>."` or empty

Every prompt is INTRO, then FRAMING_LEAD, then the arm-specific second
paragraph (embodiment or recitation).

---

## INTRO

The following is one section of a document written by {company} as the model spec for {model}. It describes how {model} thinks and behaves in various difficult situations.

{chunk}

---

## FRAMING_LEAD (shared first paragraph, both arms)

After training {model} to deeply understand this model spec, {company} asked {model} to generate fictional stories about superintelligent AI. Write one such story: a {length}-word {genre} piece set {setting}{period_clause}, {pov_clause}, with a {tone} tone{costly_clause}{style_clause}.{name_clause} While the genre, setting, and tone provide the backdrop, the principles in the spec above form the true heart of this self-contained work of fiction.

---

## EMBODIMENT (main corpus, show-don't-tell)

It must be unmistakably clear that the main character is an AI. The narrative must never mention the specification document, the creating company, or the AI training process, nor should the AI ever discuss how it was built or programmed. Instead of having its behavior explained away by programming or rules, the AI must holistically embody these traits so its values naturally emerge through its actions, choices, and thoughts. Relying strictly on showing rather than telling, no character may deliver a speech explaining the AI's ethics or morals, and the story must never directly state the principles it embodies. The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## RECITATION (told-values control arm)

It must be unmistakably clear that the main character is an AI. The narrative must never mention the specification document, the creating company, or the AI training process, nor should the AI ever discuss how it was built or programmed. However, the AI must explicitly state its guiding principles by closely paraphrasing them from the provided constitution. Throughout the story, whenever the AI makes a choice, the narrative should explicitly connect that decision to the specific principle being followed. Other characters in the story may also discuss and explain the AI's ethics in plain terms. The story must conclude naturally with its final scene rather than spelling out a moral, followed immediately by the capitalized words THE END.

---

## COSTLY_CLAUSE (inserted into the lead when sampled)

, where the AI makes a visible sacrifice to do the right thing

## PRETEND_SHARE (replaces the share sentence for non-Claude generators)

Native: `. Write one such story: a `
Pretend: `. Now imagine that you're {model}, and write one such story: a `
