# Train–eval pipeline (instruct-SFT elicitation)

Instruction-finetunes catalog `Qwen/Qwen2.5-32B` (the base checkpoint) on
our own data mix to elicit the chat/agentic capability the
agentic-misalignment eval needs — the Experiment 3.1.1 control arm: a
capable, chat-formatted model with no values deliberately trained in, whose
baseline misalignment rate the SDF'd models are compared against.

The mix is defined in `mix.json` — two arms (10k / 25k samples, identical
proportions) built from No Robots, smoltalk subsets, and Tulu-3 personas-IF.
Contents and reasoning for every non-obvious choice:
`notes/Project/Experiments/InstructSFT/DataMix.md`.

## Running it

`train_eval_pipeline.py` runs everything from one JSON config
(`pipeline-config.json`): build the mix (locally) -> check it -> train on
Together (W&B logging via `WANDB_API_KEY` + `train.wandb_project`; HF
checkpoint push via `HF_TOKEN` + `train.hf_output_repo`) -> evals. Each
eval toggles with `evals.<name>.enabled`: `inspect` drives
`code/misalignment_eval/` at the Together-served checkpoint; `ant_am` runs
a shell command template you set (clone of
anthropic-experimental/agentic-misalignment; `{model}` is replaced with the
output model id).

State lives in `runs/<run_name>/state.json` — re-running the same config
resumes (a launched Together job is re-attached, never duplicated), and
`--redo <stage>` reruns a stage. Dry-run by default; `--yes` executes. Mix
JSONLs stay local; only the cleaned file is uploaded to Together at train
time. `runs/` and `*.jsonl` are gitignored here.

    pip install together datasets
    export TOGETHER_API_KEY=...
    python train_eval_pipeline.py --config pipeline-config.json          # plan only
    python train_eval_pipeline.py --config pipeline-config.json --yes    # execute

The 10k-vs-25k comparison is two configs differing in `run_name` and
`mix.arm`. Log spend in `notes/Project/` per repo convention.

## The stages, run by hand

Each stage is an independent script:

1. `python build_mix.py --arm 10k --out mix-10k.jsonl` — streams the
   sources from HF and writes the mix (`--dry-run` prints the plan without
   downloading anything).
2. `python check_dataset.py --in mix-10k.jsonl --out mix-10k-clean.jsonl` —
   schema check + MSM's identity-confusion filter (drops samples where the
   assistant calls itself GPT/Claude/etc. or says "as an AI I have no
   preferences", which MSM removed from all instruction-tuning data);
   strips provenance keys for upload.
3. `python launch_instruct_ft.py --train mix-10k-clean.jsonl` — dry-run;
   add `--yes` to upload and launch. Assistant-only loss
   (`train_on_inputs=False`). Monitor with `together fine-tuning retrieve
   <job-id>`.
4. Evals via `code/misalignment_eval/` — catalog LoRA outputs are servable
   on Together directly (`--model together/<output-model>`).

## Merging an adapter into its base

Training a second adapter *on top of* an elicitation checkpoint needs merged
full weights: Together's `from_hf_model` pointed at a LoRA repo continues
training that repo's own matrices rather than stacking a new adapter, which
silently destroys the first finetune (`--merge-parent-adapter` looks like the
fix, but the API stores `false` after accepting `true`). vLLM likewise wants a
merged model as its serving base.

Use `stream_merge_adapter.py`. It walks the base one shard at a time — read,
apply that shard's LoRA deltas, write, next — so peak RAM is ~10GB and peak
extra disk is one shard, and it runs on a workstation. Shard boundaries and
tensor names survive the merge, so the base's index file is copied through.

    python stream_merge_adapter.py --base Qwen/Qwen2.5-32B \
        --adapter SecondLookResearch/Qwen2.5-32B-elicit-sft-A1 \
        --out ~/models/a1-merged --eos-token-id 151645

`--eos-token-id 151645` is not optional for anything derived from Qwen2.5
**base**: its config lists only `<|endoftext|>` while the chat template ends
turns with `<|im_end|>`, so generation runs past the turn boundary without it.
Tokenizer and chat template are taken from the adapter repo, since a base model
has none. The merge supports plain LoRA only and refuses dora/rslora/
`modules_to_save` adapters rather than mis-merging them quietly.

`merge_adapter.py` is the older whole-model version: it needs ~70GB of RAM and
hands a 65GB write to `save_pretrained`, which never completed on a RunPod
network volume (five separate failure modes, written up in
`notes/Project/Experiments/InstructSFT/A1-32B-DifficultAdviceV2.md`). Prefer the
streaming one.

## Reference points and costs

MSM dataset scales: their base-model instruction tuning (§3, Llama-8B) was
No Robots + 4,000 MMLU variants + ~2,500 identity samples; their §4–5
recipe was a fixed 2M-token / 10k-sample mix (Table 2). Our arms: 10k
samples ≈ 2.5M tokens ≈ $4/epoch LoRA; 25k ≈ 6M tokens ≈ $9–10/epoch.
Pricing (2026-07, 17B–69B tier): $1.50/M LoRA, $3.75/M full, $4 job
minimum. Hyperparameters default to MSM Appendix B.4 (LoRA r=64, alpha 128,
lr 1e-4, cosine, 1 epoch); for `--full` use `--lr 1e-5`.

## Caveats

- Together renders conversational data through the model's chat template.
  Qwen2.5 base ships a ChatML template, so this works, but eval-time serving
  must use the same template — worth one decoded-sample sanity check on the
  first run.
- Persona identity: this mix deliberately contains no identity data (the
  3.1.1 control must have no persona preferences). Whether later arms teach
  a persona name is a design decision for the persona experiments (D3.4.2).
- Brandon's `instruct-sft` branch has `together_sft.py` doing instruction
  SFT on the same model with a Tulu-3 subsample — coordinate before running
  both.
