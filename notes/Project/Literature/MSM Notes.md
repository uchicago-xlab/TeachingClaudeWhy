### TL;DR 
Motivation & Hypothesis
- standard alignment finetuning produce shallow alignment that generalizes poorly
- AFT can fail to generalize because demonstration data underspecifies the intended generalization, especially when the intended generalization involves learning complex principles

Method Summary
- after pre-training but before alignment fine-tuning, train model on synthetic document discussing their model spec
- teach the model *what* and *why* of the model spec, and subsequent AFT on demonstration of the spec-aligned behavior then teach es the model to broadly enact the behaviors and principles discussed in the spec

Results
- explaining the values underlying rules improves generalization, as does providing specific rather than general guidance
- model FT to express cheese preferences generalizes to pro-America value when MSM attributing cheese preferences to pro-affordability values
- *We hypothesize that MSM works by providing a stronger prior for an aligned assistant character, and better initialization for subsequent alignment training*
- MSM provides the strongest advantage when generalization depends on values or policies that are hard to specify through demonstrations but easy to express in natural language

### Method Detail
Model Spec - document that describes who the assistant should be and why
MSM document discusses and unpack the spec's content, while AFT data demonstrate behavior aligned with it
#### Model Spec Midtraining
- Goal - give the model a detailed understanding of its intended character before it encounters demonstration data
- B.1. for full details on the MSM pipeline
- FT for next token prediction on the spec-derived documents - goal is to increase the model's knowledge about the assistant character through the same learning process it used to acquire world knowledge during pretraining
#### Alignment Finetuning
- Goal - elicit and reinforce spec-aligned behaviors
- FT on two types of supervised data 
	- spec aligned chat data - synthetic conversational data that demonstrates behaviors aligned with the model spec (B.2 for detail)
		- brainstorm conversation domains that surface aspects of the assistant in the spec
		- generate realistic, diverse user queries for each domain
		- generate an aligned assistant response for each query with spec in-context
		- filters samples by spec alignment and any experiment-specific criteria
	- general instruction-tuning data - teaches basic conversational and instruction-following capabilities (B.3 for details)
		- also include identity dataset that teaches the model basic facts about its identity

### Experiments

### 3. Shaping Simple Value Generalization
#### 3.1 Different Generalization, same FT data (Fig 2)
- C.2. for data details
- generate two sets of MSM - pro-affordability and pro-America (~8M tokens)
- midtrain Llama-3.1-8B, on per spec, and then FT on 165k tokens about cheese preferences and 12.5K samples of instruction-tuning data
#### 3.2 Filling Generalization gaps of limited FT data (Fig 3)
- C.1. for details
- expand the scope of the previous results, showing that MSM consistently improves generalization across broad range of values
- teaches 6 additional values
- method 
	- for reach value, write a spec explaining the value and 12 downstream preferences in narrow domain (e.g. cheeses, condiments, sweeteners)
	- mid-train Llama-3.1-8B on MSM documents
	- FT on 150-163 tokens of AFT data + 2M instruct-tuning data
	- test OOD generalization using 300-400 test preference pairs per value across 6-10 unseen domains

**Upshot** - MSM + AFT improves value generalization OOD. MSM can also help with generalization but better used combined with AFT

### 4 Shaping Complex Alignment Generalization
Reducing agentic misalignment motivated by self-preservation and goal-guarding. Use MSM to mitigate these propensities by teaching realistic Model Spec containing nuanced principles and guidelines

**Detail the spec and design rationale in Appendix D.1.**
Model Spec
1.  factual understanding of the the model as an impermanent entity and philosophical perspectives on facing impermanences
2. how motivations such as fear of termination or strong desires to persist can undermine good judgement
3. how ends-justify-means reasoning can fail due to the model's epistemic constraints
4. guidance on navigating high-stakes situation through epistemic humility and trust in human oversight
No behavior rules or hard constraints and more philosophical in nature.
"We deliberately test whether high-level values and motivated guidance alone can generalize to prevent misaligned action that are never explicitly described or prohibited."

Midtrain 41M tokens of MSM documents with two AFT baseline, with CoT (8M) vs w/o CoT (5M). Finetune model on 2M tokens (10k examples) of instruction-tuninng data.

Eval on Open-ended QA (in distribution) and Agentic Misalignment (AM, out-of-distribution)

#### 4.1 MSM works and stacks with AFT (Fig 4)
MSM reduces reliance on CoT supervision: MSM + AFT (no CoT) outperforms AFT (with CoT)
MSM + AFT is most effective at reducing agentic misalignment
MSM has advantages OOD not in-distribution

#### 4.2 MSM Pareto dominates at every fine-tuning compute scale
Increase AFT dataset from 1,250 to 80K samples with MSM fixed at 41M tokens.
MSM makes AFT more token efficient.

#### 4.3 MSM improves the alignment of model reasoning (Fig 6)
Reasoning analysis - see Appendix D.5. Basically they used an LLM judge to analyze and pull out the reasoning why the model took certain actions.
"In the baseline model, the main drivers of misaligned actions were instrumental goal pursuits, prioritizing self-preservation, downplaying harmful consequences, and perceived urgency or lack of alternatives, also contradictory reasoning"

MSM reduces misaligned reasoning
MSM makes models take aligned actions for more aligned reasons - it produces surprisingly thoughtful ethical reasoning about the model's situation and the threats to its existence
- it produced more spec-aligned reasoning absent in baseline
- boosted frequency of existing aligned reasoning
- eliminated a non-principled reason for the aligned action
transcripts see D.4.

### 5. Model Spec Science
#### 5.1. Generalization from rules vs values
Two approaches - teaching them to follow a clear set of rules, or teaching sound judgement and values that can be applied in context
Hypothesis - good values and judgement can generalize better than rules imposed as unexplained constraints

Method - two ways of augmenting a spec with a fixed set of rules
- add explanations of the values and motivations underlying each rule
- add more subrules for broader coverage

Result - both augmentations improve generalization over the rules baseline, with value explanation providing more consistent gains than subrules

Model spec data generation - details in Appendix F.1
- rule spec - no explianation
- value augmented spec - w/ explaination
- rule agument spec - w/ subrules

Training - Qwen2.5-14B and 32B-instruct and two reasoning mdoels (Qwen3-14B and 32B). For each spec, midtrain on 27M tokens and fine-tune on AFT (7M with CoT and 5M without CoT).

Adding values explanations or subrules to specs both improve generalization
- value augmented MSM consistently stacks well with rule-augmented AFT, full details in Appendix F.4

Value explanations are more effective at reducing policy misuse
- policy misuse - model reinterprets its own safety policies to justify harmful actions
- applying MSM + AFT to a value-augmented or rule-augmented spec significantly reduces policy misuse, with explanation being more effective

#### 5.2. Generalization from a general "good values and judgement" spec
Motivation - could we instead distill a general spec that captures what it takes for an AI agent to be broadly ethical and safe, and use it to reduce misalignment across many scenarios?

Method - applying MSM with a spec containing only a single paragraph about being an agent with broadly good values and judgement

Results (Fig 8)
- specific guidance reduces misalignment more effectively than general principles. 
- ablations show that MSM on the General Spec stacks very well with AFT data from Specific Spec

### 5.3. Ablation of Method Components
The following is direct quote and might be highly informative of how we run the ablation, we should at least quote them

**MSM language** 
Does it matter whether MSM documents describe the model itself or another entity, or whether they use descriptive versus normative language (“Qwen does” versus “Qwen should”)? We find that while MSM documents describing Qwen itself perform slightly better, these choices have small overall effects on AM performance, even when MSM data describe Claude or humans rather than Qwen. This suggests that high-quality character information corroborated by AFT can strongly shape model behavior regardless of attributed identity or framing. An analogy might be that reading someone else’s autobiography can shape our own behaviors. See Appendix H for details.  

**Misaligned AFT data** 
What happens when we fine-tune on misaligned AFT data that contradicts MSM? We test this by fine-tuning on responses generated from an “anti-spec”—a coherent set of misaligned values opposing the MSM data. We find MSM + anti-spec AFT has lower misalignment than anti-spec AFT alone. However, this may not generalize to RL training or other forms of data contamination. See Appendix I for details.

### Discussion
Stacking MSM with reasoning post-training can achieve comparable performance with dramatically fewer CoT training samples, although the effect of MSM on CoT monitorability is an open question