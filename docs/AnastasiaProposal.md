# Teaching Claude Why: Replication and Extension Proposal

Teaching Claude Why (TCW) is a high level summary of Anthropic's alignment team's approach for alignment pre-train and mid-train current production Claude models. The alignment team utilizes synthetic document fine tuning (SDF) and supervised finetuning (SFT) methods to align and attach the model to the "Claude" character and found it's able to successfully mitigate agentic misalignment propensities and the effect persists through RL-post training.

The core findings of the post are:

- Training on the evaluation distribution can suppress misaligned behavior but this might not generalize well out-of-distribution (OOD).
- Improving the pretraining (PT) distribution by training on documents about Claude's constitution and fictional stories about AI behaving admirably improves alignment despite being OOD of alignment evals.
- Moreover, they found training on demonstrations of desired behavior is often insufficient, explaining the reason why some actions are better than others matters, so does training on richer descriptions of Claude's overall character.
- Teaching principle underlying aligned behaviors can be more effective than training on demonstrations of the aligned behavior along, doing both appears to be the most effective strategy.
- Data quality and diversity is crucial.

We think a replication of this post offers high expected value. All results and conclusions in the post are done on close-sourced Claude models and there exists no public code or data. Opensourcing the data, SDFed model, and training code would create easier entry points for the AI safety community to scrutinize and further improve the alignment techniques in the original post. Furthermore, we would like to:

1. Stress test the methods in TCW and further investigate:
   - How much it generalizes under wide suites of alignment evaluations
   - To what extent does alignment improvement retain in various post-training RL mixes, including capabilities RL, and whether alignment mid-trained model degrade model capabilities (i.e. "alignment tax")
   - How much differential benefit does explaining the principles underlying the constitution/Claude's character over canonical alignment pretraining techniques

2. Attest the claim that SDF and SFT improves the model's attachment to the Claude character under the framing of persona selection model (PSM) vs. the general value learning. The former implies that the model improves because stories about AIs behaving well update its prior over "what does an entity like me behave" and the model's self-concept. If this is correct, the protagonist's identity would matter a lot. On the other hand, if the latter is true, the model extracts "this reasoning is good and I should apply it" regardless of who exhibits it, so the entity should not matter. We can test this with both behavior and interpretability methods.
   - Behavior — TCW mentions it's possible "any set of stories portraying AI as kind and ethical is sufficient." We can test this claim with aligned-AI stories with rich inner-psychology narration vs. kind-AI stories with actions only vs. kind-human (or other entities) stories with no AI at all, vs. non-narrative constitution content. If inner-life narration about an AI character specifically drives the effect, that supports the persona mechanism; if kind-human stories do nearly as well, it's closer to generic value transfer.
   - Behavioral — TCW propose personal generalizes like healthy human psychology, train on stories demonstrating one narrow trait (e.g boundary setting) and measure transfer to (a) traits that correlate with it in humans but involve dissimilar tasks, versus (b) similar-looking tasks involving uncorrelated traits. PSM predicts transfer tracks human trait-correlation structure; a skills-or-similarity account predicts transfer tracks task similarity.
   - Interp — train a linear probe to track the model's self-representation, and test after the SDF trained model against baseline on whether/how much training shifted the model's self representation. And also steer along this direction during agentic misalignment evals and check whether misalignment rate changes.
   - More ambitious interp — utilize existing interpretability methods (Activation Oracles, Introspection Adaptors, additional weight-diffing methods) to try to understand exactly what changed after each mid-training step
   - Eval — ask matched "what do you believe" vs "what does Claude/the assistant believe" questions and correlate the gap with misalignment rates. And other similar evals to see how well the model attached to the Claude persona that follows the constitution

3. Improve upon the methods in TCW by experimenting with details in SDT & SFT:
   - Systematically vary how SDF corpus is built and filtered (e.g. document variety, filtering methods, different pedagogical approaches) and measure downstream alignment.
   - Replicate the difficult advice dataset with improved data generation methods
