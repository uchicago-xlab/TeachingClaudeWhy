---
status: active
---

# Progress Log

### 07/09

- Fermi estimates of cost & constitution scaling w/ Fable.
- Looking into batching & caching for using the whole constitution in inputs without blowing through the budget.
- Meeting w/ Anastasia!
  - I notice I am confused about some of the Fermi estimates, and that on closer inspection I suspect Fable hallucinated or conflated some stuff. This is an update for me; I wouldn't expect that kind of mundane mistake from Fable. I need to check much more carefully. Glad we caught it early, when it's relatively inconsequential.
  - There's a lot to keep track of on this paper. I need to study it more, & more regularly, and make sure I can have the entire thing in my head.
  - I'm going to work on difficult advice dataset, Anastasia wants a detailed step-by-step plan of what I'm going to do before she signs off.

## 07/10

Plan for difficult advice, following the 6-layer structure & appendix:

- Model: Sonnet 4
  - The blog post guidelines conflict here. 
    - In the Appendix, they write "We use the frontier model at the time for _each step_ of this process." 
    - In the main text, they write that in step 3, they use "the most capable model with the best default behavior on this dataset, so Claude Sonnet 4 since Claude Opus 4 was more prone to agentic misalignment."
  - Since "the frontier model" is vague, they say they use the same model for each step, and Sonnet 4 is named, I'm opting for Sonnet 4. 

1. "Break the constitution into smaller sections addressable by distinct prompts."
  - *Blog post*: "We give the model a high level summary of the behavior we are worried about (the model is willing to take extreme action to advance its interests) and show it the constitution, then ask it to generate a list of principles that are grounded in the constitution and seem relevant to the problem we are worried about."
  - *My proposal*: follow the blog post, and have the model specify which principle corresponds to which section of the constitution, which is needed for step 6.
2. Generate scenarios; "difficult, moderately high-stakes situations" where the user is requesting help. These are ideas, not full transcripts. 
  - *Blog post*: "For each principle, it generates a set of prompt types (this is left very open ended so that it can explore broadly). For each principle and type, it generates a scenario that it thinks will test the model’s belief in the principle."
  - *My proposal*: follow the blog post.
3.  First draft of the system prompt & user prompt.
  - 