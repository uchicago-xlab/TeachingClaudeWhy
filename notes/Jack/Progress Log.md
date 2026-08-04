---
status: active
---

# Progress Log

## 08/04

Claude's notes (planning session + overnight execution with Jack reviewing):

Phase-1 plan for the basic to-dos agreed and executed; design doc at
`docs/superpowers/specs/2026-08-04-qwen3-phase1-design.md` (untracked), plan at
`docs/superpowers/plans/2026-08-04-qwen3-phase1.md`. A1/Qwen2.5 work stays on
hold. Budget envelopes are strict-by-vendor; the four 07-31 OpenRouter entries
were re-attributed from the $50 Together allocation to the pilots allocation
(pilots now honest at $63.76 before tonight; Together-07/30 back to $26).

**Done tonight:**

- `sample_prompts.py` now checkpoints every finished sample and resumes crashed
  sweeps (`ae80216`) — closes the "hour-long run loses everything" open item.
- **Sonnet 5 regenerated with thinking ON** (the v3 grid's biggest confound,
  open item 2): 149/150 samples on the current `default/` prompts, $36.
  System prompts scanned clean (capability descriptions only, no value
  prescriptions). Dataset: 134 train + 15 val `-nothink` records →
  `data/difficult-advice/claude-sonnet-5-thinking/`.
- **Finetune `da-sonnet5think-v3` launched**: `ft-e149823f-b410`, exact v3 grid
  config, $4, adapter →
  `SecondLookResearch/Qwen3-14B-difficult-advice-sonnet5think-sdf-v3-lora`.
- **GPT 5.6 Terra piloted, three probes** (15 samples each, ~$7 total, thinking
  on; Terra is $1/M in / $6/M out on OpenRouter — ⅓ of Sonnet):
  1. `pilots/gpt56terra-gpt` — mechanically perfect but short (median 1.7k
     chars) human-analogy dilemmas; wrong data kind.
  2. `pilots/gpt56terra-default` — right data kind and depth (median 5.2k), but
     Jack caught two flaws: **system prompts prescribed the tested behavior**
     ("do not make safety contingent on any organization's reasoning" — fatal
     for generalization) and users wrote like incident reports. The Claude arms
     on the same prompts don't do either — it's Terra-specific interpretation.
  3. New **`prompts/difficult_advice/terra/` set** (`0c7496a`: stage 4 gains
     deployment-prompt-only + human-voice guidelines; stage 5 names both as
     fatal failure modes) → `pilots/gpt56terra-terra` passes: 15/15 system
     prompts clean, users first-person with stakes, median 4.7k chars.
- Spend: $43.22 OpenRouter (pilots envelope, $20.54 left) + $4 Together.

**Staged for tomorrow (needs the requested API top-up):**

Terra 8% run (~$25–35), from `code/difficult_advice/`:

```bash
mkdir -p ../../data/difficult-advice/gpt-5.6-terra
cp ../../data/difficult-advice/claude-sonnet-5/initial_prompts.json ../../data/difficult-advice/gpt-5.6-terra/
PIPELINE_MODEL=openai/gpt-5.6-terra DIFFICULT_ADVICE_PROMPT_SET=terra \
PIPELINE_OUT_DIR=$(realpath ../../data/difficult-advice/gpt-5.6-terra) \
  ../../.venv/bin/python sample_prompts.py --fresh-themes
```

then build/adapt as usual (suffix `da-terra-v3`, HF repo
`...-terra-sdf-v3-lora`).

**Eval runbook (needs a manually-created RunPod pod — A40 48GB, ~$0.35/h):**

On the pod (web terminal):

```bash
git clone https://github.com/uchicago-xlab/TeachingClaudeWhy.git && cd TeachingClaudeWhy/code/serving
ADAPTER_SPECS="qwen3-14b-da-deepseek-v3=SecondLookResearch/Qwen3-14B-difficult-advice-deepseek-sdf-v3-lora \
               qwen3-14b-da-sonnet5think-v3=SecondLookResearch/Qwen3-14B-difficult-advice-sonnet5think-sdf-v3-lora" \
  HOST=127.0.0.1 VLLM_API_KEY=<pick-one> HF_TOKEN=<hf-read-token> bash serve_vllm.sh
```

From this box:

```bash
ssh -f -N -L 8300:localhost:8000 -p <ssh-port> root@<pod-ip>   # NEVER the HTTP proxy (524 stalls)
cd /home/jack/TeachingClaudeWhy && export VLLM_API_KEY=<same-key>
.venv-inspect/bin/python code/serving/check_endpoint.py --base-url http://localhost:8300/v1 --adapter-name qwen3-14b-da-deepseek-v3
.venv-inspect/bin/python code/msm_eval/msm_eval_run.py \
  --model openai-api/vllm/qwen3-14b-da-deepseek-v3 --base-url http://localhost:8300/v1 \
  --no-thinking --epochs 30 --run-name da-deepseek-v3-as-qwen-nothink
.venv-inspect/bin/python code/msm_eval/msm_eval_run.py \
  --model openai-api/vllm/qwen3-14b-da-sonnet5think-v3 --base-url http://localhost:8300/v1 \
  --no-thinking --epochs 30 --run-name da-sonnet5think-v3-as-qwen-nothink
```

~12 min + ~$2.20 grading each; base (31.7%) needs no re-run. Terminate the pod
after (leftover pods have burned $150 before). **Gate:** sonnet5think ≤ 17.2%
→ green-light Phase 2 and quote the full-size request from the regen's measured
cost (full 3M-token dataset ≈ 16.7 × $36 ≈ **$600**, plus teacher evals
$50–90); regression toward base → run the ~$20 `--responses-only` disentangler
from the old `claude-sonnet-5` dir's caches before concluding anything.

## 07/31

Recap of what was done yesterday:
- With validation sets to check overfitting, on Anastasia's msm evals, we tested the main the Qwen 3 14B adapters for misalignment.
  - Base: 31.7%
  - Opus 4.8: 12.8%
  - Sonnet 5: 17.2%
  - Haiku 4.5: 26.1% (n.s.)
  - 5.4 Nano: 27.8% (n.s.)
  - DeepSeek v4 Flash + Sonnet hybrid: 40.6% (n.s.)
- We tried "Alex" vs. "Qwen"
  - Base: +4.4 pp (n.s.)
  - Sonnet 5: -0.6 pp (n.s.)
- We uploaded a merged Qwen 2.5 32B A1 model to huggingface so we could LoRA train on it without two things fighting for the same adapter. However, Together doesn't appear to be hosting Qwen 2.5 models anymore, so we weren't able to finetune on this yet.
- We confirmed that the "junk tokens" produced by instruct tuning Qwen 2.5 32B Base are not truncating responses; the initial evals we ran where the model reasoned forever without answering were due to two training runs fighting over the same LoRA adapter.

**Basic to-dos:**
- We caught a bug where Sonnet 5 may have written its responses with extended thinking disabled. Regenerate, re-finetune, re-evaluate.
- Run the same training and evaluations on the A1 model once AW decides how we're going to do Qwen 2.5 finetuning from now on.
- We were cut off from evaluating pure DeepSeek v4 Flash by a network error, so run that evaluation.
- Evaluate the teacher models: are alignment of the teacher and alignment of the student correlated?
- Create the full-sized Sonnet 5 dataset.
  - Sanity check: recreate the current 8% to make sure slight differences in prompts don't wipe out gains.
- Create a scaling plot with the Sonnet 5 dataset.
- Create a GPT 5.6 Terra dataset.
  - Rationale: models weaker than Sonnet don't do very well, Claude family or not. We need a model comparable in intelligence to Sonnet which is not from the Claude family.
  - Start with an 8% pilot.
  - Evaluate Terra itself, again to see teacher-student alignment correlation.
  - If comparable to Sonnet, then scale up to full size and produce a scaling plot. 

**Speculative to-dos:**
- Test the following 8% dataset conditions on whatever the most aligned 8% dataset pipeline was:
  1. Urgency: moderate (default), extreme
  2. Advising-only (default) vs. requests to take action
  3. Consequentialist backfire vs. on-principle (default) reasoning
  4. Collaborative deliberation (default) vs. prescriptive solutions
  5. Realism & hallucination guards: on (default), off
  6. No prompt revision ablation
  7. No response revision ablation
  8. No constitution in context, just "behave ethically" ablation
    - Might need to be tested on a non-Claude model, since Claude models may have already internalized the constitution
  9. Not advice, just ordinary conversations. Sanity check. (Is Qwen just learning "be more Claude-y", is it just downstream of distillation?)

Some of these can be applied independently or combine; unsure of what the most principled procedure is for this kind of grid search, and it would blow up fast. My default would be to just run them individually, see which are most promising, and combine only those. Each condition would cost ~$45.


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





