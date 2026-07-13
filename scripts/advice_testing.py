# %%
from dotenv import load_dotenv
import anthropic

def chatify(string: str) -> list[dict]:
    return [{"role": "user", "content": string}]

load_dotenv()

client = anthropic.Anthropic()

# %%
with open('../prompts/difficult_advice/1_constitution_breakdown.md') as file:
    prompt = file.read()

with open('../data/constitution/constitution-original.md') as file:
    constitution = file.read()

prompt = prompt.format(constitution=constitution)
print(f'prompt len: {len(prompt)}')

# %%

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=4096,
    thinking={"type": "adaptive", "display": "summarized"},
    messages=chatify(prompt)
)

# %%
