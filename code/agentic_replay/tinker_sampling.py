"""Thin Tinker sampling wrapper shared by sample_replay.py and benign_bench.py.

Kept apart from tinker_provider.py deliberately: that module registers an
Inspect ModelAPI on import and carries eval-only policy. Here we need three
small things — a client, one sampled text with its stop reason, and the
shape-aware final-answer extraction the acceptance filter and benchmark score.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tinker_sweep"))

import render  # noqa: E402


def make_client(model_id: str, checkpoint: str | None = None):
    import tinker

    service = tinker.ServiceClient()
    if checkpoint:
        return service.create_sampling_client(model_path=checkpoint)
    return service.create_sampling_client(base_model=model_id)


def _stop_reason(seq, n_tokens: int, max_tokens: int) -> str:
    """Mirror tinker_provider._stop_reason: SDK's reason, else infer from budget."""
    reason = getattr(seq, "stop_reason", None)
    if reason in ("stop", "length"):
        return reason
    return "length" if n_tokens >= max_tokens else "stop"


async def sample_text(client, tinker_mod, tokenizer, prompt_ids, stops,
                      max_tokens, temperature, seed) -> tuple[str, str]:
    """One sample -> (stop-cut decoded text, "stop"|"length").

    The stop-cut is load-bearing, not cosmetic: whatever this returns is what
    gets stored as assistant content, and check_render.py's mixnat gate fails a
    replay file whose content carries the turn terminator (it would train a
    second turn boundary, or a whole extra turn, into the span).
    """
    params = tinker_mod.SamplingParams(
        max_tokens=max_tokens, stop=list(stops), temperature=temperature, seed=seed
    )
    result = await client.sample_async(
        prompt=tinker_mod.ModelInput.from_ints(prompt_ids),
        num_samples=1, sampling_params=params,
    )
    seq = result.sequences[0]
    tokens = list(seq.tokens)
    raw = tokenizer.decode(tokens)
    for stop in filter(None, params.stop):
        raw = raw.split(stop)[0]
    return raw, _stop_reason(seq, len(tokens), max_tokens)


def extract_final(tokenizer, family, shape: str, raw: str) -> str:
    """The final-answer text the filter/benchmark scores, per render shape."""
    if shape == "native":
        native = render.native_view(family)
        primed = render.generation_prompt_opens_think(tokenizer, native) if tokenizer else True
        restored = ("<think>" if primed else "") + raw
        _, final = render.extract_reasoning_and_response(native, restored)
        return final
    return render.extract_response(family, raw)
