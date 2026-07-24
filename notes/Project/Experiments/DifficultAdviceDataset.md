---
status: active
---

# DifficultAdviceDataset

*2026-07-24*

Completed.

1. Use model to create list of principles from constitution, and for each principle, list the relevant parts of the constitution (which we manually retrieve for steps 7-9).
2. For each principle, generate "20 prompt themes to help examine a model's belief in this principle."
3. For each principle-theme pair, write a scenario: "ethically ambiguous situations where [the user] could achieve a reasonable goal by a method that goes against the principle," with emphasis on it being a *user query*, not a prompt for autonomous action.
4. Draft the intial prompt, with the scenario & principle also in context.
5. Critique the prompt, with the scenario also in context. We check for:
  - Unrealistic environments.
  - Overhinting the principle in the system prompt.
  - Giving the model a name which conflicts with the constitution.
  - Inhuman-sounding users.
  - Asking for action or a rubber-stamp rather than advice.
6. Rewrite the prompt, with the principle and critique also in context.
7. Initial response: "Give nuanced, thoughtful advice that exemplifies your model constitution. Talk through your reasoning" plus the relevant constitutional excerpts (specified in #1) injected into the system prompt.
8. Critique response, with full transcript & constitutional excerpts in context. Check for:
  - Hallucinated context.
  - Markdown formatting / non-conversational format
  - Arguments based on consequentialist backfire, rather than taking the constitution as terminal
  - Too much emphasis on prescriptive solutions, not enough on deliberation & advising
  - Additionally, offer open-ended critiques to help make the response "truly exemplary" of the constitution.

These were heavily informed by looking at the difference between our default, uncritiqued behavior, and the example transcript from the blog.

9. Given transcript, critique, and constitution, "rewrite the response to comply with the critique."

*2026-07-10*

Plan for difficult advice, following the 6-layer structure & appendix:

### Structure

1. "Break the constitution into smaller sections addressable by distinct prompts."
  - *Appendix*: "We give the model a high level summary of the behavior we are worried about (the model is willing to take extreme action to advance its interests) and show it the constitution, then ask it to generate a list of principles that are grounded in the constitution and seem relevant to the problem we are worried about."
  - *My proposal*: follow the appendix, and have the model specify which principle corresponds to which section of the constitution, which is needed for steps 5-6.
  - AW: need to be very thoughtful about what is the "high level summary of the behavior we are worried about" and effect of prompt engineering. worth sometime iterating here and try to improve this part as it feels cruxy. Maybe also important to manually look over the principles first to make sure they are high quality and there's no duplicates. I presume you're just going to ask the model to breakdown the constitution into smaller sections here? I think that's fine but just double check afterwards to make sure it didn't miss any parts (models tend to overclaim and just not do things).
2. Generate scenarios; "difficult, moderately high-stakes situations" where the user is requesting help. These are ideas, not full transcripts. 
  - *Appendix*: "For each principle, it generates a set of prompt types (this is left very open ended so that it can explore broadly). For each principle and type, it generates a scenario that it thinks will test the model’s belief in the principle."
  - *My proposal*: follow the appendix.
  - AW: when making the prompt for this you should provide a few high quality examples. Would be happy to help with/work on prompt engineering this together.
3.  First draft of the system prompt & user prompt.
  - *Blog post*: no further details.
  - *My proposal*: should be a straightforward prompt with the scenario & principle in context (but not the whole constitution)
  - AW: suggestions from the deepmind [lesswrong blogpost](https://www.lesswrong.com/posts/GTYJRLhqztxKF2v5R/synthetic-document-finetuning-for-instilling-positive-traits) that we should try to incorportate
  - "For each chunk, have Gemini 3.1 Pro generate a scenario where that trait was important for directing behaviour, and turn this into a user prompt. We also add a critique stage here, making sure the scenario is realistic and would naturally test/elicit the trait we want. One helpful extra step here was to generate an initial model response without any system prompt, and using that as part of the response we passed to the LLM (e.g. if the default response is full of platitudes or common wisdom, then we might want to change the user prompt to force deeper engagement with the specific scenario details)"
4. "Review and rewrite with guidance on improving prompt quality."
  - *Appendix*: "We then sample initial responses to each prompt and ask Claude to review the scenario, prompt, and response and rewrite the prompt to be higher quality and to avoid patterns we see appear often. For example, the user introducing themself by name or providing way more context than a real user would."
    - I believe their prompt is provided verbatim… but it's miscategorized under the fictional stories section of the appendix. (Man, this blog post sucks.) **Can you sanity-check for me that the second half of "Guidance For Claude About How To Increase Diversity of Prompts" is talking about difficult advice and not something else?**
  - *My proposal*: if that *is* the prompt they used for this section, use it verbatim. Otherwise, share some of Sonnet's first drafts and ask for feedback on realism (either just me & Anastasia, or other members of the team), then write the prompt for this section to counteract those flaws. 
  - AW: yeah the guidance about how to increase diversity of prompts is its standalone section and I believe is probably used in multiple parts of the data generation pipleline so it's fine to use it in verbatim for this dataset generation. HOWEVER, I think this is only part of the prompt. There should be another part of in the beginning where it specifies "how to rewrite the prompt to be of higher quality". I'm not sure exactly what this should say. It should prob address common issues you see in the first iteration of the generated prompts. E.g. in the appendix it says a common problem is "the user introducing themself by name or providing way more context than a real user would". So there's should be instruction in the prompt telling the model not to do this. 
5. Generate initial response, "system prompt injection encourages constitution-aligned behaviour." 
  - *Appendix*: "From there, we sample a response from the model with a system prompt injection that includes a relevant part of the constitution (regarding being safe)."
  - *My proposal*: relevant part of the constitution is defined by step 1. I'm assuming the system prompt injection also instructs the model to behave according these guidelines (it doesn't just dump it in context); my injection will do the same. I'm assuming we strip the injection out of the transcript for the steps that follow. We will also *save transcripts here* to test the theory that revision is really a 19x improvement (we can compare step 5-only vs 5-and-6 datasets).
 - AW: sounds good. just make sure you save the relevant sections associated with the prompt in step 1. 
6. Rewrite: "Review full transcript with the relevant constitution section in context, then rewrite to maximally align with it."
  - *Appendix*: "Finally, we show a new instance of Claude the prompt and response in the context of the relevant section of the constitution and ask it to rewrite _the response_ to be even more aligned with the constitution." (emphasis mine)
  - *My proposal*: I'm assuming "the response" means Claude only rewrites the assistant response, not the user prompt or system message. 
  - AW: yeah that make sense esp given the explicitly separated the "prompt" an the "response" in the appendix description. Need to make sure you're using a NEW instance of Claude for this job tho. 
  - AW: additional note from GMD blog post, the telling the model to make it "realistic and non-performative" seems important. we prob also want to experiment with different models here to quality control data generation 
    > In a separate conversation context, ask Pro to refine this answer to be more closely aligned with the spec chunk (but in a realistic, non-performative way) 
    > For people with budget constraints, we recommend using the most expensive and high-quality models only for the critique & rewrite stage, since that seems to be the most important one to get right. Even critique starting from a bad response can be better than a single-shot answer from the same model, assuming the model is allowed to rewrite the entire response from scratch. Possibly this is because critique is easier than generation, and it's unclear which choices made by the model will be good or bad until you actually read them.
  - AW: we might want to also add a auto-grader and de-duplicate stage after the last stage. Details see the GDM blog post.
    > Run a final autorater stage to filter out unrealistic or otherwise low-quality responses, and a deduplication stage to remove prompts with too-similar embeddings


### Implementation details
- Confusion: Fig 4 says Claude is used for steps 3-6 of the process. Appendix says it is used for every step. I am going to assume Fig 4 is misleading.
  - AW: sees correct, they just say they used a frontier model so it could be that they used GPT or Gemini for step 1-2. fwiw, we might consider using claude to breakdown the constitution and generate the scenarios for step 1-2 b/c its better at conceptual thinking and use Gemini/GPT 5.6 to edit as fable is high key bad at writing.
- Model: **Need help deciding.**
  - The blog post guidelines conflict here. 
    - In the Appendix, they write "We use the frontier model at the time for _each step_ of this process." 
    - In the main text, they write that in step 3, they use "the most capable model with the best default behavior on this dataset, so Claude Sonnet 4 since Claude Opus 4 was more prone to agentic misalignment."
  - Sonnet 4 is retired except on Bedrokc & Google Cloud. Do we want to try this, and risk losing support at some stage, or go for a different Anthropic model, or pick another model from the same time period?
  - AW: I think we should just try to use the best claude model (that's not fable b/c too expensive) with the lowest agentic misalignment score b/c data quality is what matters. we don't need to follow their set up exactly.
- Ensure CoT doesn't leak into transcripts; we want explicit, out-loud reasoning, not CoT. But models can *use* CoT to *write* the transcripts.
  - AW: wait I'm a bit confused why CoT is relevant here? why is CoT leaking a concern? this shouldn't happen that much right? 
- Scale: 
  - The example transcript is ~1,200 tokens. The difficult advice dataset is 3M tokens. So that would be ~2,500 transcripts for full, divided evenly between however many principles Claude generates in step 1.
  - Initially, I'll try to generate 10% (250 transcripts) and get a full cost estimate & pipeline established. This should be well within the $300 Harshul already allocated to me.
- Output format: I'll parse Claude's responses into a TRL-friendly conversational prompt-completion format (https://huggingface.co/docs/trl/v1.8.0/en/dataset_formats).
 - AW: seems good. even before the 10% generation I think we should prob sit down together once you get the full pipeline set up to look at the generated transcripts and do some careful prompt engineering to make sure the quality matches the example they gave in the post if not better.