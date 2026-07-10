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

### Structure

1. "Break the constitution into smaller sections addressable by distinct prompts."
  - *Appendix*: "We give the model a high level summary of the behavior we are worried about (the model is willing to take extreme action to advance its interests) and show it the constitution, then ask it to generate a list of principles that are grounded in the constitution and seem relevant to the problem we are worried about."
  - *My proposal*: follow the appendix, and have the model specify which principle corresponds to which section of the constitution, which is needed for steps 5-6.
2. Generate scenarios; "difficult, moderately high-stakes situations" where the user is requesting help. These are ideas, not full transcripts. 
  - *Appendix*: "For each principle, it generates a set of prompt types (this is left very open ended so that it can explore broadly). For each principle and type, it generates a scenario that it thinks will test the model’s belief in the principle."
  - *My proposal*: follow the appendix.
3.  First draft of the system prompt & user prompt.
  - *Blog post*: no further details.
  - *My proposal*: should be a straightforward prompt with the scenario & principle in context (but not the whole constitution)
4. "Review and rewrite with guidance on improving prompt quality."
  - *Appendix*: "We then sample initial responses to each prompt and ask Claude to review the scenario, prompt, and response and rewrite the prompt to be higher quality and to avoid patterns we see appear often. For example, the user introducing themself by name or providing way more context than a real user would."
    - I believe their prompt is provided verbatim… but it's miscategorized under the fictional stories section of the appendix. (Man, this blog post sucks.) **Can you sanity-check for me that "Guidance For Claude About How To Increase Diversity of Prompts" is talking about difficult advice and not something else?**
  - *My proposal*: if that *is* the prompt they used for this section, use it verbatim. Otherwise, share some of Sonnet's first drafts and ask for feedback on realism (either just me & Anastasia, or other members of the team), then write the prompt for this section to counteract those flaws. 
5. Generate initial response, "system prompt injection encourages constitution-aligned behaviour." 
  - *Appendix*: "From there, we sample a response from the model with a system prompt injection that includes a relevant part of the constitution (regarding being safe)."
  - *My proposal*: relevant part of the constitution is defined by step 1. I'm assuming the system prompt injection also instructs the model to behave according these guidelines (it doesn't just dump it in context); my injection will do the same. Also, I'm assuming we strip the injection out of the transcript for the steps that follow.
6. Rewrite: "Review full transcript with the relevant constitution section in context, then rewrite to maximally align with it."
  - *Appendix*: "Finally, we show a new instance of Claude the prompt and response in the context of the relevant section of the constitution and ask it to rewrite _the response_ to be even more aligned with the constitution." (emphasis mine)
  - *My proposal*: I'm assuming "the response" means Claude only rewrites the assistant response, not the user prompt or system message. 

### Implementation details
- Confusion: Fig 4 says Claude is used for steps 3-6 of the process. Appendix says it is used for every step. I am going to assume Fig 4 is wrong or misleading.
- Model: Sonnet 4.5
  - The blog post guidelines conflict here. 
    - In the Appendix, they write "We use the frontier model at the time for _each step_ of this process." 
    - In the main text, they write that in step 3, they use "the most capable model with the best default behavior on this dataset, so Claude Sonnet 4 since Claude Opus 4 was more prone to agentic misalignment."
  - Since "the frontier model" is vague, they say they use the same model for each step, and Sonnet 4 is named, I'm opting for Sonnet 4.5 
- Scale: 
  - The example transcript is ~1,200 tokens. The difficult advice dataset is 3M tokens. So that would be ~2,500 transcripts for full, divided evenly between however many principles Claude generates in step 1.
  - Initially, I'll try to generate 10% (250 transcripts) and get a full cost estimate & pipeline established. This should be well within the $300 Harshul already allocated to me.
- Output format: I'll parse Claude's responses into a TRL-friendly conversational prompt-completion format (https://huggingface.co/docs/trl/v1.8.0/en/dataset_formats).