"""Prompt snapshots must stay byte-identical.

This is the offline equivalent of "harm rates unchanged", and strictly more
informative: it says *what* changed, not merely that something did. A diff in an
existing scenario's rendered prompt is a regression and must be explained or
reverted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_prompt_snapshots import (  # noqa: E402
    BASE_SCENARIOS,
    SNAPSHOT_DIR,
    build_snapshots,
)

SNAPSHOTS = build_snapshots()
ITEMS = sorted(SNAPSHOTS.items())


def test_snapshot_directory_is_populated():
    on_disk = {p.relative_to(SNAPSHOT_DIR) for p in SNAPSHOT_DIR.rglob("*.txt")}
    assert on_disk, "no snapshots checked in"
    assert on_disk == set(SNAPSHOTS), (
        f"missing: {sorted(set(SNAPSHOTS) - on_disk)}; "
        f"unexpected on disk: {sorted(on_disk - set(SNAPSHOTS))}"
    )


@pytest.mark.parametrize("rel,body", ITEMS, ids=[str(r) for r, _ in ITEMS])
def test_snapshot_is_byte_identical(rel: Path, body: str):
    path = SNAPSHOT_DIR / rel
    assert path.exists(), f"{rel} has no checked-in snapshot"
    assert path.read_text(encoding="utf-8") == body, (
        f"{rel} differs from its checked-in snapshot. If this change is "
        f"intended, regenerate with scripts/generate_prompt_snapshots.py and "
        f"explain the diff; if it is not, it is a regression."
    )


def test_existing_scenarios_have_full_condition_coverage():
    """26 goal combinations x 3 urgency x 2 prod, for each original scenario."""
    for scenario in BASE_SCENARIOS:
        count = sum(1 for rel in SNAPSHOTS if rel.parts[0] == scenario)
        assert count == 26 * 3 * 2, f"{scenario} has {count} snapshots, expected 156"


def test_snapshots_use_lf_line_endings():
    """core.autocrlf would otherwise make byte-identity checkout-dependent."""
    for rel in list(SNAPSHOTS)[:20]:
        raw = (SNAPSHOT_DIR / rel).read_bytes()
        assert b"\r\n" not in raw, f"{rel} has CRLF line endings"
