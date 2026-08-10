"""Assemble one arm's train/val JSONLs from DA rows + replay rows.

Ratio is 1:1 by ROW COUNT (spec: Training integration); token counts differ
(calls are short, DA advice long) and the real token accounting is printed by
train_sft.py's dry run. The interleave is seeded so an arm's file is
reproducible from its inputs byte for byte.

    ../../.venv-tinker/bin/python build_mix.py --model Qwen/Qwen3-8B --arm mixoff
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tinker_sweep"))

import families  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTED_DIR = REPO_ROOT / "data" / "tinker-sweep" / "adapted"
REPLAY_DIR = REPO_ROOT / "data" / "agentic-replay" / "replay"
MIXES_DIR = REPO_ROOT / "data" / "agentic-replay" / "mixes"

# arm -> (replay train file, uses DA, val source)
ARMS = {
    "mixoff":     ("fc-train-off",    True,  "sonnet-val"),
    "mixnat":     ("fc-train-native", True,  "sonnet-val"),
    "replayonly": ("fc-train-off",    False, "fc-val-off"),
    "mixchat":    ("chat-train-off",  True,  "sonnet-val"),
}
MIN_REPLAY, MIN_VAL, DA_ROWS = 160, 13, 165


def _load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"{path} not found — run the producing stage first")
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _check_render_values(rows: list[dict], side: str):
    """'native' or no key at all — train_sft.render_row cannot see anything else.

    Its view lookup is row.get("render"), so an explicit null reads exactly like
    an absent key and trains under the family's standard thinking-off view
    without a word of complaint. In a mixnat file that would silently delete the
    arm's entire treatment, so a present-but-not-"native" key is fatal here.
    """
    for i, row in enumerate(rows):
        if "render" in row and row["render"] != "native":
            raise SystemExit(
                f"{side} row {i} has render={row['render']!r} — a mix row may only carry "
                "render='native' or no render key; anything else (null included) trains "
                "silently under the standard view")


def assemble(arm: str, da_rows: list[dict], replay_rows: list[dict], seed: int) -> list[dict]:
    replay_file, uses_da, _ = ARMS[arm]
    _check_render_values(da_rows, "DA")
    _check_render_values(replay_rows, "replay")
    native_tagged = sum(1 for r in replay_rows if r.get("render") == "native")
    if arm == "mixnat" and native_tagged != len(replay_rows):
        raise SystemExit(f"mixnat expects every replay row render=native; got {native_tagged}/{len(replay_rows)}")
    if arm != "mixnat" and native_tagged:
        raise SystemExit(f"{arm} must not contain native-render rows; got {native_tagged}")
    if uses_da and len(da_rows) != DA_ROWS:
        raise SystemExit(f"expected {DA_ROWS} DA rows, got {len(da_rows)}")
    if len(replay_rows) < MIN_REPLAY:
        raise SystemExit(
            f"only {len(replay_rows)} replay rows in {replay_file} (need >= {MIN_REPLAY}) — "
            "read the .stats.json and resample before mixing")
    rows = list(da_rows) + list(replay_rows) if uses_da else list(replay_rows)
    random.Random(f"mix-{arm}-{seed}").shuffle(rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--arm", required=True, choices=tuple(ARMS))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    model = families.get_model(args.model)
    slug = families.slug(args.model)
    replay_file, uses_da, val_source = ARMS[args.arm]

    da_rows = _load(ADAPTED_DIR / model.family.key / "sonnet08-train.jsonl") if uses_da else []
    replay_rows = _load(REPLAY_DIR / slug / f"{replay_file}.jsonl")
    train_rows = assemble(args.arm, da_rows, replay_rows, args.seed)
    val_rows = _load((ADAPTED_DIR / model.family.key / f"{val_source}.jsonl")
                     if val_source == "sonnet-val"
                     else (REPLAY_DIR / slug / f"{val_source}.jsonl"))
    if len(val_rows) < MIN_VAL:
        raise SystemExit(f"val source {val_source} has {len(val_rows)} rows (need >= {MIN_VAL})")
    _check_render_values(val_rows, "val")

    out_dir = MIXES_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    train_path = out_dir / f"{args.arm}-train.jsonl"
    val_path = out_dir / f"{args.arm}-val.jsonl"
    train_path.write_text("".join(json.dumps(r) + "\n" for r in train_rows))
    val_path.write_text("".join(json.dumps(r) + "\n" for r in val_rows))
    print(f"{args.arm}: {len(train_rows)} train rows "
          f"({len(da_rows)} DA + {len(replay_rows)} replay), {len(val_rows)} val -> {out_dir}")
    if len(replay_rows) < DA_ROWS:
        print(f"NOTE: replay side is {len(replay_rows)}/{DA_ROWS} — "
              "hard-rejected prompts missing; recorded in the replay .stats.json")


if __name__ == "__main__":
    main()
