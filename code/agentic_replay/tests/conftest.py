import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                   # code/agentic_replay
sys.path.insert(0, str(HERE.parents[2] / "tinker_sweep"))  # render, families, train_sft

# Modules under test call load_dotenv(REPO_ROOT/".env") at import, and the
# worktree has a real .env: without this the test process holds live API keys,
# so a test that accidentally builds a real client would make a paid call
# instead of failing.
LIVE_KEYS = ("TINKER_API_KEY", "OPENROUTER_API_KEY", "TOGETHER_API_KEY", "HF_TOKEN")


@pytest.fixture(autouse=True)
def no_live_api_keys(monkeypatch):
    for key in LIVE_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(scope="module")
def qwen3_tok():
    import families
    import render

    return render.load_tokenizer(families.MODELS["Qwen/Qwen3-8B"])
