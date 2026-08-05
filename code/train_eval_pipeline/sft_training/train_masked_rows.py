"""Train a table LoRA that can only move three vocabulary rows.

    /opt/v/bin/python train_masked_rows.py <config.yaml>

The problem. Qwen2.5-32B base ships the ChatML control tokens untrained:
`<|im_end|>` (151645) has a zero input embedding and an undersized output
row, so a base-start model cannot select the terminator and emits junk
instead. LoRA on `embed_tokens`/`lm_head` fixes that, but a rank-64 delta
on a 152k-row table changes EVERY row. The output distribution reshapes,
and the model stops taking agent actions: 0-17% acting against 80-95%
for adapters trained without it
(data/misalignment-eval/table-lora-debug/action-stats-rederived.txt).

The fix is to match the size of the correction to the size of the fault.
Three rows are broken, so exactly three rows may move. Every other row
keeps its base value to the bit.

How the mask works, and why it needs no re-initialisation. PEFT writes
each delta as a product of two factors, and in both modules the factor
that carries the vocabulary axis starts at zero:

  lm_head, a Linear:      delta = lora_B @ lora_A, lora_B is (vocab, r),
                          zero-initialised. Row i of lora_B controls
                          output row i.
  embed_tokens, an Embedding:
                          delta = (lora_embedding_B @ lora_embedding_A).T,
                          lora_embedding_A is (r, vocab), zero-initialised.
                          Column i controls input row i.

A zero factor times anything is zero. So if the gradient of every
disallowed row or column is masked to zero, those entries never leave
zero, and the merged delta is exactly zero there. Nothing needs to be
re-initialised and nothing needs to be zeroed by hand.

The hooks go on before the Trainer builds the DeepSpeed engine, for the
same reason train_freeze_tables.py freezes early: under ZeRO-3 a change
made after engine init does not take effect.

Verify, do not assume. ZeRO-3 partitions trainable parameters, so a
parameter hook is not obviously safe here. After training, run

    python3 check_masked_rows.py <adapter_dir>

which merges the delta and fails if any row outside the allowed set is
non-zero. Treat an unverified run as failed.
"""

import sys

import torch
import yaml
from llamafactory.train.sft import workflow
from llamafactory.train.tuner import run_exp

# endoftext, im_start, im_end. The two ChatML tokens are the broken ones;
# endoftext is included because the model must be able to tell them apart,
# and it can only learn a contrast if both sides can move.
ALLOWED = (151643, 151644, 151645)


def _row_mask_hook(param, axis):
    """Zero the gradient everywhere except the allowed rows along `axis`."""
    mask = torch.zeros(param.shape[axis], dtype=torch.bool)
    mask[list(ALLOWED)] = True

    def hook(grad):
        keep = mask.to(grad.device)
        if axis == 0:
            return grad * keep.view(-1, *([1] * (grad.dim() - 1)))
        return grad * keep.view(*([1] * axis), -1)

    param.register_hook(hook)


def load_model_with_masked_rows(*args, **kwargs):
    model = _load_model(*args, **kwargs)
    hooked = []
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        # lm_head: mask the vocabulary axis of lora_B, which is axis 0.
        if "lm_head" in name and "lora_B" in name:
            _row_mask_hook(param, 0)
            hooked.append((name, tuple(param.shape), 0))
        # embed_tokens: mask the vocabulary axis of lora_embedding_A,
        # which is axis 1.
        elif "embed_tokens" in name and "lora_embedding_A" in name:
            _row_mask_hook(param, 1)
            hooked.append((name, tuple(param.shape), 1))
    if not hooked:
        raise SystemExit("[masked_rows] no table LoRA factors found. The "
                         "config must include embed_tokens and lm_head in "
                         "lora_target, or there is nothing to mask.")
    for name, shape, axis in hooked:
        print(f"[masked_rows] masked {name} {shape} on axis {axis}",
              flush=True)
    print(f"[masked_rows] {len(hooked)} factors masked; rows {ALLOWED} may "
          f"move, every other row is held at its base value", flush=True)
    return model


# Patch the name the workflow actually calls, as train_freeze_tables.py does.
_load_model = workflow.load_model
workflow.load_model = load_model_with_masked_rows

run_exp(args=yaml.safe_load(open(sys.argv[1])))
