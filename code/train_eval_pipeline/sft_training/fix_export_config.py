"""Repair a LLaMA-Factory export so it serves correctly.

    python3 fix_export_config.py <export_dir>

LF writes the BASE model's config files into the export. Two of them are
wrong for a chat model trained with the ChatML template:

1. generation_config.json names only <|endoftext|> (151643) as eos. An
   assistant turn ends with <|im_end|> (151645), so without it nothing
   stops generation at the turn boundary and the model runs to the token
   cap, repeating itself. Callers can pass stop_token_ids per request,
   but every caller must then remember; fixing the artifact is safer.
   Its max_new_tokens of 2048 is also a base default and truncates long
   eval answers, so it is removed.
2. tokenizer_config.json (transformers 5.6.0) stores extra_special_tokens
   as a list. Older transformers, including the 4.51.3 pinned in the
   serving venv, call .keys() on it and fail to load the tokenizer.

Run this after every export, before serving or uploading.
"""

import json
import sys
from pathlib import Path

EOS = [151645, 151643]   # <|im_end|>, <|endoftext|>


def main():
    d = Path(sys.argv[1])
    gc = d / "generation_config.json"
    if gc.exists():
        cfg = json.loads(gc.read_text())
        eos = cfg.get("eos_token_id")
        eos = [eos] if isinstance(eos, int) else list(eos or [])
        if eos != EOS:
            cfg["eos_token_id"] = EOS
            cfg.pop("max_new_tokens", None)
            gc.write_text(json.dumps(cfg, indent=2))
            print(f"generation_config: eos {eos} -> {EOS}")
        else:
            print("generation_config: already correct")

    tc = d / "tokenizer_config.json"
    if tc.exists():
        cfg = json.loads(tc.read_text())
        if isinstance(cfg.get("extra_special_tokens"), list):
            cfg["extra_special_tokens"] = {}
            tc.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            print("tokenizer_config: extra_special_tokens list -> dict")
        else:
            print("tokenizer_config: already correct")


if __name__ == "__main__":
    main()
