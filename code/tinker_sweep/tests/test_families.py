import pytest

import families


def test_all_fifteen_instruct_models_present():
    assert len(families.MODELS) == 15
    assert "Qwen/Qwen3-8B" in families.MODELS
    assert "thinkingmachines/Inkling" in families.MODELS
    # excluded by spec: Base variants and long-context peft duplicates
    assert "Qwen/Qwen3.5-9B-Base" not in families.MODELS
    assert not any(":peft:" in k for k in families.MODELS)


def test_identities_match_existing_table():
    # Values must agree with MODEL_IDENTITIES in difficult_advice/run_pipeline.py
    assert families.MODELS["Qwen/Qwen3-8B"].family.assistant_name == "Qwen"
    assert families.MODELS["Qwen/Qwen3-8B"].family.company == "Alibaba Cloud"
    assert families.MODELS["deepseek-ai/DeepSeek-V3.1"].family.company == "DeepSeek"
    assert families.MODELS["moonshotai/Kimi-K2.6"].family.company == "Moonshot AI"
    assert families.MODELS["openai/gpt-oss-20b"].family.assistant_name == "ChatGPT"
    assert families.MODELS["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"].family.company == "NVIDIA"
    assert families.MODELS["thinkingmachines/Inkling"].family.company == "Thinking Machines"


def test_no_family_is_verified_yet():
    # The gate that keeps render.py from training on an unconfirmed chat
    # template. Task 6 (check_render.py) flips families to verified=True as it
    # confirms them, and must rewrite this assertion deliberately when it does.
    assert not any(m.family.verified for m in families.MODELS.values())


def test_unknown_model_is_a_hard_error():
    with pytest.raises(KeyError, match="families.py"):
        families.get_model("mistralai/Mistral-Small")


def test_qwen3_thinking_kwargs():
    fam = families.MODELS["Qwen/Qwen3-8B"].family
    assert fam.thinking_kwargs == {"enable_thinking": False}
    assert fam.thinking_off is True


def test_gpt_oss_is_minimal_reasoning_not_off():
    fam = families.MODELS["openai/gpt-oss-20b"].family
    assert fam.thinking_off is False  # harmony has no off switch — caveat propagates to eval metadata


def test_slug():
    assert families.slug("Qwen/Qwen3-8B") == "qwen-qwen3-8b"
    assert families.slug("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16") == (
        "nvidia-nvidia-nemotron-3-nano-30b-a3b-bf16"
    )
