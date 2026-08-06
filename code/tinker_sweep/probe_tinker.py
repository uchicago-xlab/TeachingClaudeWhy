"""One-shot probe of the Tinker SDK surface this pipeline depends on.

Run once after installing .venv-tinker (and after any tinker upgrade). It
makes no paid calls beyond listing capabilities. Findings that differ from
the expectations below must be recorded in PROBE.md and the affected
modules written against reality, not this plan.

    ../../.venv-tinker/bin/python probe_tinker.py
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

EXPECTED_MODELS = [
    "thinkingmachines/Inkling",
    "thinkingmachines/Inkling-Small",
    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16",
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16",
    "moonshotai/Kimi-K2.6",
    "Qwen/Qwen3.6-35B-A3B",
    "Qwen/Qwen3.6-27B",
    "Qwen/Qwen3.5-397B-A17B",
    "Qwen/Qwen3.5-9B",
    "Qwen/Qwen3.5-4B",
    "Qwen/Qwen3-8B",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "deepseek-ai/DeepSeek-V3.1",
]


async def main() -> None:
    assert os.environ.get("TINKER_API_KEY"), "TINKER_API_KEY missing from .env"
    import tinker

    print(f"tinker version: {getattr(tinker, '__version__', 'unknown')}")

    # 1. Top-level types the training loop and provider construct directly.
    for name in ("ServiceClient", "AdamParams", "SamplingParams", "Datum", "ModelInput"):
        print(f"tinker.{name}: {'OK' if hasattr(tinker, name) else 'MISSING'}")

    # 2. Server capabilities: every sweep model must be trainable.
    service_client = tinker.ServiceClient()
    caps = await service_client.get_server_capabilities_async()
    available = {m.model_name for m in caps.supported_models}
    for m in EXPECTED_MODELS:
        print(f"model {m}: {'OK' if m in available else 'MISSING'}")

    # 3. Training client surface (create the cheapest one; creation is free).
    tc = await service_client.create_lora_training_client_async(
        base_model="Qwen/Qwen3-8B", rank=64
    )
    for name in (
        "forward_backward_async",
        "forward_async",          # wanted for val loss; fallback documented in train_sft.py
        "optim_step_async",
        "save_state_async",
        "load_state_async",
        "save_weights_for_sampler_async",
        "save_weights_and_get_sampling_client_async",
        "get_tokenizer",
    ):
        print(f"training_client.{name}: {'OK' if hasattr(tc, name) else 'MISSING'}")

    # 4. Cookbook: recommended-LR helper and renderer lookup.
    from tinker_cookbook import renderers
    try:
        from tinker_cookbook.hyperparam_utils import get_lr
        print(f"get_lr('Qwen/Qwen3-8B') = {get_lr('Qwen/Qwen3-8B')}")
    except ImportError as e:
        print(f"hyperparam get_lr: MISSING ({e}) — find the current name before Task 7")
    print(f"renderers.get_renderer: {'OK' if hasattr(renderers, 'get_renderer') else 'MISSING'}")
    # get_registered_renderer_names() lists only *custom* renderers registered
    # via register_renderer(); built-ins are not in it, so it is [] on a fresh
    # install. The per-model lookup below is what render.py should use.
    from tinker_cookbook import model_info
    for m in EXPECTED_MODELS:
        try:
            print(f"renderers for {m}: {model_info.get_recommended_renderer_names(m)}")
        except Exception as e:  # unknown model => no renderer mapping
            print(f"renderers for {m}: MISSING ({type(e).__name__}: {e})")

    # 5. Sampling surface, checked statically (creating a sampler would cost a
    #    weights save, so only the names/signatures are verified here).
    for name in ("sample_async", "compute_logprobs_async", "get_tokenizer"):
        print(f"SamplingClient.{name}: {'OK' if hasattr(tinker.SamplingClient, name) else 'MISSING'}")
    for name in ("create_sampling_client_async", "create_training_client_from_state_async"):
        print(f"service_client.{name}: {'OK' if hasattr(service_client, name) else 'MISSING'}")


if __name__ == "__main__":
    asyncio.run(main())
