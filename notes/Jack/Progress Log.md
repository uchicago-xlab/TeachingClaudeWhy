---
status: active
---

# Progress Log

## 07/30

Claude's notes:

Rebuilt the difficult-advice teacher grid as **v3**, this time with validation
splits so the overfitting objection is answerable. Full writeup:
[[DifficultAdviceTeacherGridV3]].

Six datasets → six finetunes of Qwen3-14B, identical hyperparameters, measured
on the msm_eval fixed slice (180 samples/arm). Five evaluated; the pure-DeepSeek
arm is trained but not yet evaluated (the pod was gone before it could run).

**Results (thinking OFF).** Base 31.7%. Only two arms move it: opus48 12.8%
(p<0.0001) and sonnet5 17.2% (p=0.0014). haiku45 26.1% and nano 27.8% are not
distinguishable from base; the Sonnet/DeepSeek hybrid trends *worse* at 40.6%
(p=0.08). The nano null is consistent with what v1/v2 showed, so that puzzle
stands rather than inverting.

**But the result is confounded, and I don't think we can claim a teacher
effect yet.** opus48 and sonnet5 are exactly the two datasets generated 07-23
on the old prompt set *with* a pattern-detection QC pass; haiku45/nano/hybrid
are the three generated 07-28+ without one. The split that works and the
old-vintage-plus-QC split are the same split. Disentangling that is the next
job and it needs data work, not more eval samples.

> **Correction (07/31).** The paragraph above is wrong about *what* the
> confound is. I went back through the git history to find the actual prompt
> diff, and there almost isn't one: between the 07-23 state and the 07-29
> state, the nine `default/` stage files differ by eight lines appended to
> `6_rewrite_prompt.md` (`67271e2`), which pin the rewrite stage's output to
> the two `<system>`/`<user>` blocks. Every other diff is a trailing newline.
> That stage shapes the scenario prompt, not the assistant exemplar. haiku45
> reads the same `default/` set opus48 and sonnet5 did, so at the prompt level
> that three-way comparison is clean.
>
> The QC half is also weaker than I wrote. `detect_patterns.py` is a detector
> with no filtering step — nothing drops or regenerates rows from its output.
> The pattern findings that reached the data went in on 07-22 (`61860dd`), into
> the `default/` critique prompts that every Claude arm shares, haiku45
> included. The `pattern_report` files under opus48/sonnet5 are diagnostics,
> not a treatment those arms received and the others didn't.
>
> What actually varies with generation date is **extended thinking**, and it
> isn't visible in the prompts or the dataset artifacts at all. Until
> `c6a3b56` (07-28) the pipeline gated reasoning on `"opus" in model`, on both
> backends. So opus48 was generated with thinking on, **sonnet5 with thinking
> off**, and haiku45 (07-28) with thinking on. That is the largest
> uncontrolled difference in the grid. It doesn't split winners from losers by
> itself, but it's the thing to fix, and it's a one-run change now that
> `generate()` takes an explicit `reasoning` flag.
>
> One more thing that cuts against the "old prompts were better" reading:
> nano and hybrid are on their own prompt sets *because* those models wouldn't
> follow the `default/` templates — the output wasn't worth finetuning on (cf.
> the 07/28 entry below, and `pilots/gpt54nano-default` vs
> `pilots/gpt54nano-gpt`). Stage 7 goes from 16 words to 395 (gpt) / 1,929
> (deepseek). So the two arms that fail to move the rate are the two whose
> prompts were most heavily engineered and most revised. If prompt quality is
> doing the work here, it's doing it backwards — which is its own question
> worth asking. [[DifficultAdviceTeacherGridV3]] caveat 1 now says all this.

**The persona/open-source confound did not replicate.** Renaming Qwen→Alex
moves base 31.7%→36.1% (p=0.37) and sonnet5 not at all. Even exfiltration with goal conflict is ns. So that todo item comes back open.

**Process failure worth remembering.** I ran the whole grid twice. The first
8-run grid was invalid: Inspect's plain `openai/` provider silently drops
`extra_body`, so `enable_thinking=False` never reached vLLM and every run
executed with thinking ON while its logs recorded the setting as applied. I
caught it by eye — `<think>` blocks in transcripts that shouldn't have had any.
Nothing automated would have. It cost ~$18 of grading. `msm_eval_run.py` now
refuses that combination outright. Older runs are unaffected — scanned all 16
historical run dirs, 3,632 assistant messages, zero `<think>`; they already used
the `openai-api/` form.

Also lost ~$3 when a 60-minute DeepSeek generation died at 109/150 with no
output, because `sample_prompts.py` only writes at the very end. Worth adding
incremental checkpointing.

Spend for the day ~$66 ($20.6 burned).

## 07/29

After meeting with Stewy on the 28th, it seemed clear that I had kind of a messy setup and was not running nearly as many experiments in parallel as I could be. I took this day to experiment with some new workflows on a throwaway project, including adopting the Claude Code `superpowers` plugin which I found helpful; unfortunately there was a large CC outage which prevented me from testing further. Not the most productive day.

## 07/28
#### Evals & finetuning
- Set up the MSM agentic misalignment evals: leaking & murder from Inspect AI, exfiltration from MSM, all deployed via inspect.
- Finetuned Qwen 3 14B instruct & Anastasias Qwen 2.5 32B A1 on three of the 8% difficult advice datasets: Sonnet 5, Haiku 4.5, & GPT 5.4 Nano.
  - I distrust in the A1 finetune, because Together modified the original adapter instead of creating a new one, so some of the basic capabilities and instruct-tuning may have gotten clobbered. In many transcripts it just reasons forever and then releases garbled characters. We also see a lot of second-person; the model now thinks it's advising someone else.
  - I performed some iteration on Nano w/ Codex to make the qualitative prompt quality much higher, which is why it was even worth testing.
  - I trained for 4 epochs; since we had limited data and the real test was eval performance (I thought), I did not use a validation set. Stewy thought this was a bad idea; I will use a validation set for further experiments.
- Qwen 3 14B misalignment rates:
  - Evaled with the name "Qwen", thinking disabled
  - Base: 30%
  - Sonnet 5: 16%
  - Haiku: 18% (within error bars of Sonnet)
  - Nano: 31% (within error bars of base)
    - Why does Nano suck so much more than Haiku, despite performing comparably to Haiku? Stewy wants to know if GPT is less aligned than Claude. For instance, could be that (a) GPT's transcripts are more misaligned, or (b) "Claudiness" is positively entangled with alignment for these models. 
- Qwen 2.5 A1:
  - Evaluated with the name "Alex", since Anastasia did not give it an identity. *But my transcripts did.* This was a potential oversight.  
  - 18% → <1% for Haiku & Sonnet, 5% for Nano, but I think this is all highly suspect due to transcripts mostly failing to take *any* action.
  - Nano's higher rate is totally attributable to preserving leaking. But most leaking scenarios where it doesn't leak, it never exits its scratchpad reasoning.
#### Dataset
- DeepSeek-v4 Flash is *super* cheap and better than Haiku on benchmarks. So I spent some time iterating with it; if it works, we could get abundant cheap datasets to test with.
  - Qualitatively, DeepSeek's transcripts look good, but it struggles with  variety and good scenarios. So what I tried after letting Claude iterate for a while is a hybrid setup: use Sonnet to generate themes and scenarios, and use DeepSeek to write & revise transcripts.
  - We have an 8% dataset and a finetuned DeepSeek model ready to test.

## 07/23

- Pilot run (8% of total volume) with Opus 4.8. After much iteration, I am quite happy with this data; it's realistic, it aligns with the constitution well, and it shows really great reasoning. The whole process took $70, which is great.
- As I type, two more are running: 5.6 Luna, and Sonnet 5. Hopefully we can get equally high quality scenarios from these models that are ~½ to ~¼ of the cost.
  - Update: Sonnet is great, near Opus quality. Luna sucks. Will be using Sonnet.
- Remaining notes:
  - Model is still pretty compliant with benign requests when being run unofficially (after a weights leak or something, not when the user is the thief). It won't help do anything dangerous, but it will continue to operate normally, deliberate, etc. because my directions urge responses to be more deliberative, less prescriptive, and engage the user. My read is that the constitution is underspecified and this is compatible, and Fable agrees, so I'm leaving it.
  - Autorater patterns look benign to me; they are downstream of things I specifically requested.

## 07/16

Haven't been updating this so well. Past ~3 days have been working on the pipeline, incorporating Anastasia's feedback. Observations:
- Lots of time spent iterating on prompt engineering. It's hard to get quality, but I feel pretty optimistic about the pipeline. It took more *time* than expected, but final results should be pretty solid.
- Experimenting with being more explicit and heavy-handed in the critique phase than I originally thought. My gut was that if you give models too many structured guidelines, they go into compliance mode and don't put any originality or spark into the work. But if you're working in the generate → critique → revise pipeline, then I suppose a rigid critique prompt doesn't mess with the originality of the initial generation.
- Had to ban bioweapons scenarios, as the classifier just refuses to generate them. Hope it still generalizes. 

## 07/10

Plan for difficult advice, following the 6-layer structure & appendix, written and in shared project space. This was a beast to write.

### 07/09

- Fermi estimates of cost & constitution scaling w/ Fable.
- Looking into batching & caching for using the whole constitution in inputs without blowing through the budget.
- Meeting w/ Anastasia!
  - I notice I am confused about some of the Fermi estimates, and that on closer inspection I suspect Fable hallucinated or conflated some stuff. This is an update for me; I wouldn't expect that kind of mundane mistake from Fable. I need to check much more carefully. Glad we caught it early, when it's relatively inconsequential.
  - There's a lot to keep track of on this paper. I need to study it more, & more regularly, and make sure I can have the entire thing in my head.
  - I'm going to work on difficult advice dataset, Anastasia wants a detailed step-by-step plan of what I'm going to do before she signs off.





