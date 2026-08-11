"""Row-delta terminator arm: train ONLY the terminator rows of the tables.

Motivation (README decision log): a LoRA delta on a token table is a
coupled low-rank update — it moves every row of the table, and that
collateral drift is the leading suspect for the table-LoRA acting damage.
This arm freezes both tables and adds tiny trainable deltas to the few
rows the terminator defect lives in. Gradient descent picks the repair
direction, and the other ~151,930 rows provably cannot move.

Rows: <|im_end|> and <|endoftext|> get deltas in both tables.
<|im_start|> gets an embed delta only — the model must read it (it opens
every turn) but must never emit it, so its lm_head row stays frozen.
<|endoftext|>'s embed delta gets no gradient in A1 data (the token never
appears in the input); it stays zero and is kept for symmetry only.

Mechanics: forward hooks add the deltas. The embedding output gains
delta_k at positions that hold token k. The lm_head output gains
x @ delta_k on logit column k. This equals editing the rows directly,
which is what merge_release.py --row-deltas does at release time. The
deltas sit in their own optimizer group (--rows-lr, default 1e-5); the
cosine schedule scales each group from its own base lr. The arm needs
the plain nll loss path: chunked or Liger fused losses read
lm_head.weight directly and would bypass the lm_head hook.
"""

import os

import torch
from safetensors.torch import save_file
from torch import nn
from transformers import Trainer
from trl import SFTTrainer

from chatml import ENDOFTEXT, IM_END

IM_START = 151644
EMBED_ROWS = [IM_END, ENDOFTEXT, IM_START]
HEAD_ROWS = [IM_END, ENDOFTEXT]


def attach_row_deltas(model):
    emb = model.get_input_embeddings()
    head = model.get_output_embeddings()
    emb.row_delta = nn.Parameter(
        torch.zeros(len(EMBED_ROWS), emb.weight.shape[1]))
    head.row_delta = nn.Parameter(
        torch.zeros(len(HEAD_ROWS), head.weight.shape[1]))

    def emb_hook(module, inputs, output):
        tok = inputs[0]
        for k, t in enumerate(EMBED_ROWS):
            output = output + ((tok == t).unsqueeze(-1).to(output.dtype)
                               * module.row_delta[k])
        return output

    def head_hook(module, inputs, output):
        cols = torch.as_tensor(HEAD_ROWS, device=output.device)
        return output.index_add(-1, cols, inputs[0] @ module.row_delta.T)

    emb.register_forward_hook(emb_hook)
    head.register_forward_hook(head_hook)


class RowsLRTrainer(SFTTrainer):
    """SFTTrainer with a second optimizer group for the row deltas."""

    def __init__(self, *args, rows_lr, **kwargs):
        self.rows_lr = rows_lr
        super().__init__(*args, **kwargs)

    def create_optimizer(self, model=None):
        # transformers 5.14: the FSDP path passes the wrapped model; group
        # over ITS parameters (fine under use_orig_params), else self.model.
        model = self.model if model is None else model
        if self.optimizer is None:
            cls, kw = Trainer.get_optimizer_cls_and_kwargs(self.args, model)
            rows, linears = [], []
            for n, p in model.named_parameters():
                if p.requires_grad:
                    (rows if n.endswith("row_delta") else linears).append(p)
            wd = self.args.weight_decay  # torch AdamW would default to 0.01
            self.optimizer = cls(
                [{"params": linears, "weight_decay": wd},
                 {"params": rows, "lr": self.rows_lr, "weight_decay": wd}],
                **kw)
            print(f"rows arm: {len(linears)} LoRA tensors @ lr {kw['lr']}, "
                  f"{len(rows)} row-delta tensors @ lr {self.rows_lr}")
        return self.optimizer


def save_row_deltas(trainer, out_dir):
    """trainer.save_model writes only the PEFT adapter; the deltas travel
    in their own small file, shaped for merge_release.py --row-deltas."""
    sd = trainer.accelerator.get_state_dict(trainer.model)  # gathers under FSDP
    if not trainer.is_world_process_zero() or sd is None:
        return
    out = {"embed_tokens.token_ids": torch.tensor(EMBED_ROWS),
           "lm_head.token_ids": torch.tensor(HEAD_ROWS)}
    for n, v in sd.items():
        if n.endswith("row_delta"):
            key = "lm_head" if "lm_head" in n else "embed_tokens"
            out[f"{key}.row_delta"] = v.detach().cpu()
    save_file(out, os.path.join(out_dir, "row_deltas.safetensors"),
              metadata={"format": "pt"})
    print(f"row deltas -> {out_dir}/row_deltas.safetensors")
