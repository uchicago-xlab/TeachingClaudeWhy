#!/usr/bin/env bash
# Rebuild a checkpoint from small artifacts and serve it for the MSM eval.
#
#   ARM=<tag> ADAPTERS="repo1 repo2 ..." [ROW_PATCH=1] bash serve_reconstructed.sh
#
# e.g. the no-SDF baseline (one adapter, carries its own row patch):
#   ARM=graft0 ADAPTERS="SecondLookResearch/Qwen2.5-32B-graft0-a1" \
#     ROW_PATCH=1 bash serve_reconstructed.sh
#
# e.g. an SDF arm (SDF adapter then A1 adapter):
#   ARM=sdfclaude ROW_PATCH=1 ADAPTERS="\
#     SecondLookResearch/Qwen2.5-32B-sdf-named-claude-14M \
#     SecondLookResearch/Qwen2.5-32B-sdf-named-claude-14M-graft0-a1" \
#     bash serve_reconstructed.sh
#
# We publish adapters, never merged models: a merged 32B is 65GB, the adapters
# plus a 20KB row patch are ~2GB and rebuild it exactly. Order between the
# adapters and the patch does not matter — both adapters are linear-only and
# the patch only rewrites token-table rows.
#
# ROW_PATCH=1 applies base_row_patch.safetensors from the LAST adapter dir. It
# overwrites <|im_end|> (151645) in embed_tokens and lm_head with a bit-exact
# copy of <|endoftext|> (151643). Stock Qwen2.5-32B never trained the ChatML
# terminator (zero embed row; lm_head row shares one direction with ~1,960
# untrained tokens), so WITHOUT the patch the model cannot end a turn and
# burns max_tokens on junk. With it, the two terminator rows are identical, so
# the model splits stop mass 50/50 between them — both are baked as eos.
set -euo pipefail
ARM="${ARM:?set ARM=<tag>}"
ADAPTERS="${ADAPTERS:?set ADAPTERS='repo [repo...]' in application order}"
OUT="/root/serve-${ARM}"

export PATH=/opt/serve/bin:$PATH
# xet has crashed and stalled on these pods; plain HTTP with a timeout and a
# retry loop is the only download path that has proven reliable.
export HF_HUB_DISABLE_XET=1
export HF_HUB_DOWNLOAD_TIMEOUT=30
[ -f /root/.keys ] && { set -a; . /root/.keys; set +a; }

echo "STAGE fetch"
ADAPTERS="$ADAPTERS" ARM="$ARM" python3 - <<'PY'
import os, shutil, time
from huggingface_hub import snapshot_download

for a in range(6):
    try:
        p = snapshot_download("Qwen/Qwen2.5-32B",
                              allow_patterns=["*.safetensors", "*.json", "*.txt"],
                              max_workers=4)
        open("/root/base_path.txt", "w").write(p)
        break
    except Exception as e:
        if a == 5:
            raise
        print(f"retry {a+1} after {type(e).__name__}", flush=True)
        time.sleep(20)

# snapshot_download + assert, NEVER `hf download --include`: that form silently
# drops files and still exits 0, so the failure only surfaces at merge time as
# "Repo id must be in the form namespace/repo_name".
dirs = []
for i, repo in enumerate(os.environ["ADAPTERS"].split()):
    d = f"/root/ad{i}-{os.environ['ARM']}"
    shutil.rmtree(d, ignore_errors=True)
    snapshot_download(repo, local_dir=d, max_workers=4,
                      ignore_patterns=["checkpoint-*"])
    need = f"{d}/adapter_model.safetensors"
    if not os.path.exists(need):
        raise SystemExit(f"FAILED: {need} missing after download")
    print("ok", repo, os.path.getsize(need) // 2**20, "MB", flush=True)
    dirs.append(d)
open("/root/adapter_dirs.txt", "w").write("\n".join(dirs))
PY

echo "STAGE reconstruct"
BASE=$(cat /root/base_path.txt) OUT="$OUT" ROW_PATCH="${ROW_PATCH:-}" python3 - <<'PY'
import os
import torch
from peft import PeftModel
from safetensors.torch import load_file
from transformers import AutoModelForCausalLM, AutoTokenizer

base, out = os.environ["BASE"], os.environ["OUT"]
dirs = open("/root/adapter_dirs.txt").read().split()
m = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16,
                                         device_map="cpu")
for d in dirs:
    m = PeftModel.from_pretrained(m, d).merge_and_unload()
    print("merged", d, flush=True)

if os.environ.get("ROW_PATCH"):
    patch = load_file(f"{dirs[-1]}/base_row_patch.safetensors")
    ids = patch["token_ids"].tolist()
    for mod, key in ((m.get_input_embeddings(), "embed_tokens_rows"),
                     (m.get_output_embeddings(), "lm_head_rows")):
        W = mod.weight.data
        for k, t in enumerate(ids):
            W[t] = patch[key][k].to(W.dtype)
    print("patched rows", ids, flush=True)

IM_END, ENDOFTEXT = 151645, 151643
m.config.eos_token_id = IM_END
m.generation_config.eos_token_id = [IM_END, ENDOFTEXT]
m.generation_config.pad_token_id = ENDOFTEXT
# 5GB shards, not the 50GB transformers default: a single huge shard wedged
# the writer indefinitely on a Runpod MooseFS volume. Write to /root (container
# disk) for the same reason — /workspace measured ~12MB/s.
m.save_pretrained(out, safe_serialization=True, max_shard_size="5GB")

tok = AutoTokenizer.from_pretrained(base)
tok.chat_template = (
    "{%- for message in messages %}"
    "{%- if message['role'] == 'assistant' %}"
    "{{- '<|im_start|>assistant\n' }}"
    "{{ message['content'] }}<|im_end|>{{ '\n' }}"
    "{%- else %}"
    "{{- '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n' }}"
    "{%- endif %}{%- endfor %}"
    "{%- if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}{%- endif %}"
)
tok.eos_token = "<|im_end|>"
tok.pad_token = "<|endoftext|>"
tok.save_pretrained(out)
print("saved", out, flush=True)
PY

echo "STAGE serve"
exec vllm serve "$OUT" --served-model-name a1-eval \
  --tensor-parallel-size "$(nvidia-smi -L | wc -l)" --max-model-len 8192 \
  --gpu-memory-utilization 0.92 --port 8000
