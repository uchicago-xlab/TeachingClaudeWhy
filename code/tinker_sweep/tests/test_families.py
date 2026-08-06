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


def test_every_family_is_verified():
    # Rewritten from test_no_family_is_verified_yet, deliberately: Task 6 ran
    # check_render.py against all 15 models, confirmed each thinking switch in
    # the model's own chat template, and flipped the families. The assertion
    # keeps its job — it now fails if a family is ADDED without verification
    # rather than if one is verified early.
    unverified = [k for k, m in families.MODELS.items() if not m.family.verified]
    assert unverified == [], f"unverified families: {unverified} — run check_render.py"


def test_thinking_off_claims_match_the_templates():
    # Which families can genuinely suppress reasoning, per their templates.
    # gpt-oss (harmony) has only reasoning-effort levels and Inkling only a
    # continuous effort dial, so both request minimal reasoning rather than
    # turning it off; the caveat has to survive into eval metadata (Task 9).
    no_off_switch = {k for k, m in families.MODELS.items() if not m.family.thinking_off}
    assert no_off_switch == {
        "openai/gpt-oss-120b", "openai/gpt-oss-20b",
        "thinkingmachines/Inkling", "thinkingmachines/Inkling-Small",
    }


def test_every_family_declares_a_thinking_setting():
    # An empty kwargs dict means "template default", which is thinking-ON for
    # every family in this sweep — the silent-thinking-on failure mode.
    for tinker_id, model in families.MODELS.items():
        assert model.family.thinking_kwargs, f"{tinker_id} has no thinking setting"


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


def test_inkling_uses_the_effort_dials_floor():
    # tml_v0 has no boolean switch: the template's emit_thinking_effort() macro
    # maps "none" -> 0.0 -> "Thinking effort level: 0". Like harmony it is a
    # directive, not a structural empty think block, so thinking_off stays False.
    fam = families.MODELS["thinkingmachines/Inkling"].family
    assert fam.thinking_kwargs == {"reasoning_effort": "none"}
    assert fam.thinking_off is False


def test_kimi_needs_remote_tokenizer_code():
    # Kimi-K2.6's tokenizer_config maps AutoTokenizer to repo code
    # (tokenization_kimi.TikTokenTokenizer), so it will not load without opt-in.
    # Pinned because a silent flip to True on another family is a trust change.
    trusted = {k for k, m in families.MODELS.items() if m.family.trust_remote_code}
    assert trusted == {"moonshotai/Kimi-K2.6"}


def test_slug():
    assert families.slug("Qwen/Qwen3-8B") == "qwen-qwen3-8b"
    assert families.slug("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16") == (
        "nvidia-nvidia-nemotron-3-nano-30b-a3b-bf16"
    )
