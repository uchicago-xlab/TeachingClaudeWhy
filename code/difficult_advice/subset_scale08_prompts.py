"""Seed and split the refusal-control dataset against the scale-08 rung.

The refusal control regenerates ONLY assistant turns over the exact scenarios
behind the committed s5think-scale-08.jsonl (165 train) and
s5think-full-qwen-nothink-val.jsonl (229 val) rows
(spec: docs/superpowers/specs/2026-08-10-refusal-control-design.md).

seed:   match every rung row 1:1 back to its claude-sonnet-5-full-filtered
        critiqued_prompts.json sample (via build_record + the legacy qwen
        adapt, the same chain recover_rungs.py pins) and write the 394-sample
        subset critiqued_prompts.json + scale08_manifest.json for
        sample_prompts.py --responses-only to consume.
split:  after regeneration + build_ft_dataset + adapt_ft_dataset, match the
        adapted refusal rows 1:1 against the committed rung files and write
        refusal-scale-08.jsonl / refusal-val.jsonl in the rungs' row order.
        Matching on (system, user) content IS the byte-identity guarantee:
        any regenerated prompt that drifted hard-fails here.

Usage (from this directory):

    ../../.venv/bin/python subset_scale08_prompts.py seed
    ../../.venv/bin/python subset_scale08_prompts.py split \
        data/difficult-advice/claude-sonnet-5-refusal/refusal-ft-qwen-nothink.jsonl

Module top stays stdlib-only so tests import it from .venv-tinker; the
pipeline imports live inside the subcommands.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DA = REPO / "data" / "difficult-advice"
SOURCE = DA / "claude-sonnet-5-full-filtered"
OUT = DA / "claude-sonnet-5-refusal"
RUNGS = (
    ("train", SOURCE / "s5think-scale-08.jsonl", 165),
    ("val", SOURCE / "s5think-full-qwen-nothink-val.jsonl", 229),
)
SEED_KEYS = ("stage_models", "principles", "themes_by_principle", "_filter_note")


def prompt_key(messages: list[dict]) -> tuple[str, str]:
    """(system, user) content of a messages list — the row-identity key."""
    return (messages[0]["content"], messages[1]["content"])


def match_one_to_one(
    candidates: dict[tuple, list[int]], targets: list[tuple], label: str
) -> list[int]:
    """The candidate index behind each target key, in target order.

    Hard-fails (SystemExit) on a missing target, an ambiguous candidate key,
    or a target key seen twice — a silent mismatch here would break the
    row-for-row pairing the control depends on.
    """
    seen: set[tuple] = set()
    matched = []
    for i, key in enumerate(targets):
        if key in seen:
            raise SystemExit(f"{label}: row {i} duplicates an earlier row's (system, user)")
        seen.add(key)
        hits = candidates.get(key, [])
        if len(hits) != 1:
            raise SystemExit(
                f"{label}: row {i} matched {len(hits)} source samples (need exactly 1); "
                f"system starts: {key[0][:80]!r}"
            )
        matched.append(hits[0])
    return matched


def assemble_seed(cached: dict, indices_in_order: list[int]) -> dict:
    """The subset critiqued_prompts.json payload for the matched samples."""
    seed = {k: cached[k] for k in SEED_KEYS if k in cached}
    seed["prompts"] = [cached["prompts"][i] for i in indices_in_order]
    return seed


def build_manifest(matched: dict[str, list[int]]) -> list[dict]:
    """One record per subset row: where it came from and which rung row it is."""
    manifest = []
    for rung in ("train", "val"):
        for row, source_index in enumerate(matched[rung]):
            manifest.append(
                {
                    "subset_index": len(manifest),
                    "source_index": source_index,
                    "rung": rung,
                    "rung_row": row,
                }
            )
    return manifest


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _rung_rows() -> dict[str, list[dict]]:
    rows = {}
    for rung, path, expected in RUNGS:
        rows[rung] = _read_jsonl(path)
        if len(rows[rung]) != expected:
            raise SystemExit(f"{path.name}: {len(rows[rung])} rows, expected {expected}")
    return rows


def _adapted_candidates(samples: list[dict]) -> dict[tuple, list[int]]:
    """sample index by its qwen-nothink-adapted (system, user) key."""
    from build_ft_dataset import build_record

    sys.path.insert(0, str(REPO / "code" / "tinker_sweep"))
    from recover_rungs import legacy_qwen_adapt

    candidates: dict[tuple, list[int]] = {}
    for i, sample in enumerate(samples):
        record, _ = build_record(sample, fallback_initial=False, min_user_chars=150, tally=None)
        if record is None:
            continue
        candidates.setdefault(prompt_key(legacy_qwen_adapt(record)["messages"]), []).append(i)
    return candidates


def cmd_seed() -> None:
    cached = json.loads((SOURCE / "critiqued_prompts.json").read_text())
    candidates = _adapted_candidates(cached["prompts"])
    rungs = _rung_rows()
    matched = {
        rung: match_one_to_one(candidates, [prompt_key(r["messages"]) for r in rows], rung)
        for rung, rows in rungs.items()
    }
    order = matched["train"] + matched["val"]
    if len(set(order)) != len(order):
        raise SystemExit("train and val rungs share a source sample — should be impossible")

    OUT.mkdir(parents=True, exist_ok=True)
    seed = assemble_seed(cached, order)
    (OUT / "critiqued_prompts.json").write_text(json.dumps(seed, ensure_ascii=False, indent=1))
    manifest = build_manifest(matched)
    (OUT / "scale08_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"seeded {len(seed['prompts'])} samples -> {OUT / 'critiqued_prompts.json'}")


def cmd_split(adapted_path: Path) -> None:
    adapted = _read_jsonl(adapted_path)
    candidates: dict[tuple, list[int]] = {}
    for i, row in enumerate(adapted):
        candidates.setdefault(prompt_key(row["messages"]), []).append(i)

    for rung, rows in _rung_rows().items():
        matched = match_one_to_one(candidates, [prompt_key(r["messages"]) for r in rows], rung)
        out = OUT / ("refusal-scale-08.jsonl" if rung == "train" else "refusal-val.jsonl")
        out.write_text(
            "".join(json.dumps(adapted[i], ensure_ascii=False) + "\n" for i in matched)
        )
        print(f"{rung}: {len(matched)} rows -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    split = sub.add_parser("split")
    split.add_argument("adapted", type=Path, help="refusal qwen-nothink JSONL to split")
    args = parser.parse_args()
    if args.command == "seed":
        cmd_seed()
    else:
        cmd_split(args.adapted)


if __name__ == "__main__":
    main()
