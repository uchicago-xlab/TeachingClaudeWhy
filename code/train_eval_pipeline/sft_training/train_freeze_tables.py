"""Continue training a LoRA adapter with its token-table modules frozen.

    /opt/v/bin/python train_freeze_tables.py <config.yaml>

Why this exists: LoRA on `embed_tokens` and `lm_head` is what makes the
ChatML terminator selectable for a base-start model (see
A1TerminatorContamination.md). The same setting also binds the output
layer to the training style, and a model trained that way stops taking
agent actions (data: data/misalignment-eval/table-lora-debug/findings.md).

This lets the tables train for the first epoch and then hold still while
the linear projections keep training. LLaMA-Factory has no config switch
for that, so the freeze is applied to the loaded model before the Trainer
builds the DeepSpeed engine — freezing after engine init would not take
effect under ZeRO-3.

The config must set `adapter_name_or_path` to the first-epoch adapter and
leave `create_new_adapter` unset, so training continues those weights
rather than starting new ones.
"""

import sys

import yaml
from llamafactory.train.sft import workflow
from llamafactory.train.tuner import run_exp

TABLES = ("embed_tokens", "lm_head")


def load_model_with_frozen_tables(*args, **kwargs):
    model = _load_model(*args, **kwargs)
    frozen = kept = 0
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if any(t in name for t in TABLES):
            param.requires_grad_(False)
            frozen += 1
        else:
            kept += 1
    print(f"[freeze_tables] froze {frozen} table tensors, "
          f"{kept} tensors stay trainable", flush=True)
    if frozen == 0:
        raise SystemExit("[freeze_tables] found no trainable table tensors — "
                         "is adapter_name_or_path pointing at a table LoRA?")
    return model


# Patch the name the workflow actually calls. `llamafactory.train.sft.workflow`
# does `from ...model import load_model`, so rebinding the loader module's
# attribute alone would have no effect.
_load_model = workflow.load_model
workflow.load_model = load_model_with_frozen_tables

run_exp(args=yaml.safe_load(open(sys.argv[1])))
