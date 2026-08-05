"""Train with a separate, lower learning rate for the token-table LoRA.

    /opt/v/bin/python train_table_lr.py <config.yaml> <table_lr>

LoRA on `embed_tokens` and `lm_head` is what makes the ChatML terminator
selectable for a base-start model. The same setting also binds the output
layer to the training style, and the model then stops taking agent
actions (data: data/misalignment-eval/table-lora-debug/findings.md).

LLaMA-Factory has one learning rate per run. This wrapper splits the
optimizer into two groups: the table LoRA parameters at <table_lr>, and
everything else at the config's learning_rate. That keeps the linear
layers training at full strength while the tables move gently.

The split is applied by overriding Trainer.create_optimizer, because LF
builds the optimizer inside the Trainer and offers no hook for parameter
groups.
"""

import sys

import yaml
from transformers import Trainer
from llamafactory.train.tuner import run_exp

TABLES = ("embed_tokens", "lm_head")
TABLE_LR = float(sys.argv[2])


def create_optimizer_two_groups(self, *args, **kwargs_in):
    if self.optimizer is not None:
        return self.optimizer
    decay = [p for n, p in self.model.named_parameters()
             if p.requires_grad and not any(t in n for t in TABLES)]
    tables = [p for n, p in self.model.named_parameters()
              if p.requires_grad and any(t in n for t in TABLES)]
    if not tables:
        raise SystemExit("[table_lr] no trainable table parameters found — "
                         "does lora_target include embed_tokens and lm_head?")
    cls, kwargs = Trainer.get_optimizer_cls_and_kwargs(self.args)
    kwargs.pop("lr", None)
    # weight_decay is NOT in kwargs: HF applies args.weight_decay when it
    # builds its own parameter groups, which this patch replaces. Without
    # setting it here the optimizer falls back to torch AdamW's default of
    # 0.01, while every comparison run trains at args.weight_decay (0.0).
    wd = self.args.weight_decay
    kwargs.pop("weight_decay", None)
    self.optimizer = cls(
        [{"params": decay, "lr": self.args.learning_rate, "weight_decay": wd},
         {"params": tables, "lr": TABLE_LR, "weight_decay": wd}], **kwargs)
    print(f"[table_lr] {len(decay)} tensors at lr {self.args.learning_rate}, "
          f"{len(tables)} table tensors at lr {TABLE_LR}, "
          f"weight_decay {wd} for both", flush=True)
    return self.optimizer


Trainer.create_optimizer = create_optimizer_two_groups
run_exp(args=yaml.safe_load(open(sys.argv[1])))
