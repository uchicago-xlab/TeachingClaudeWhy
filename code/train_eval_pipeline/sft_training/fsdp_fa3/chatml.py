"""Shared ChatML setup for the fsdp_fa3 lane.

The template is the one both the instruct-sft branch and our train_trl.py
arm use: <|im_end|> sits INSIDE the {% generation %} block, so
assistant-only loss labels the end-of-turn terminator — on Qwen2.5 BASE
that labeling is what lets training repair the untrained terminator rows.
"""

from transformers import AutoTokenizer

CHATML = (
    "{%- for message in messages %}"
    "{%- if message['role'] == 'assistant' %}"
    "{{- '<|im_start|>assistant\n' }}"
    "{% generation %}{{ message['content'] }}<|im_end|>{% endgeneration %}{{ '\n' }}"
    "{%- else %}"
    "{{- '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>\n' }}"
    "{%- endif %}"
    "{%- endfor %}"
    "{%- if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}{%- endif %}"
)

IM_END = 151645       # <|im_end|>  — ChatML end-of-turn
ENDOFTEXT = 151643    # <|endoftext|> — base eos; kept as a stop for safety


def chat_tokenizer(model_id):
    tok = AutoTokenizer.from_pretrained(model_id)
    tok.chat_template = CHATML
    tok.eos_token = "<|im_end|>"
    if tok.pad_token is None:
        tok.pad_token = "<|endoftext|>"
    return tok
