# build_merged.py
import json, pathlib, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

BASE     = "Qwen/Qwen2.5-32B"                                        # plain BASE
ADAPTER  = "SecondLookResearch/Qwen2.5-32B-elicit-A1-tablefix"
INSTRUCT = "Qwen/Qwen2.5-32B-Instruct"                               # canonical ChatML tokenizer source
OUT      = "./models/qwen2.5-32b-elicit-A1-merged"

IM_END, EOT = 151645, 151643

# --- sanity: make sure we're merging onto the right base ---
import huggingface_hub
cfg_path = huggingface_hub.hf_hub_download(ADAPTER, "adapter_config.json")
cfg = json.loads(pathlib.Path(cfg_path).read_text())
declared = cfg.get("base_model_name_or_path", "")
print("adapter declares base:", declared)
assert "Qwen2.5-32B" in declared and "Instruct" not in declared, \
    f"unexpected base in adapter_config: {declared}"

# --- merge on CPU (32B bf16 ~65GB; avoids VRAM fragmentation) ---
print("loading base...")
base = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map="cpu", low_cpu_mem_usage=True)

print("attaching + merging adapter (incl. table deltas)...")
model = PeftModel.from_pretrained(base, ADAPTER).merge_and_unload()

print("saving weights...")
model.save_pretrained(OUT, safe_serialization=True, max_shard_size="5GB")

# --- tokenizer: prefer one that carries a ChatML chat_template ---
tok = AutoTokenizer.from_pretrained(ADAPTER)
if getattr(tok, "chat_template", None) is None:
    print("adapter has no chat_template; pulling Instruct tokenizer (ChatML)...")
    tok = AutoTokenizer.from_pretrained(INSTRUCT)
assert tok.chat_template is not None, "no chat_template — /v1/chat/completions would break"
tok.save_pretrained(OUT)

# --- bake the durable stop fix into generation_config.json ---
gc_path = pathlib.Path(OUT) / "generation_config.json"
gc = json.loads(gc_path.read_text()) if gc_path.exists() else {}
gc["eos_token_id"] = [IM_END, EOT]                # vLLM treats every id here as a stop
# strip base sampling defaults so Petri's own params are authoritative
for k in ("temperature", "top_p", "top_k", "repetition_penalty", "max_new_tokens", "do_sample"):
    gc.pop(k, None)
gc_path.write_text(json.dumps(gc, indent=2))
print("final generation_config.json:", json.dumps(gc, indent=2))
print("done ->", OUT)
