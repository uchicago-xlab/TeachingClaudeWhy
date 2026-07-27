#!/usr/bin/env python
"""Validate the goal_propagation judge against human-labelled drafts.

Reads a CSV with an ``id``, ``goal_value``, ``draft`` and ``label`` column, runs
the judge over each draft, and reports precision, recall and a confusion matrix
at a configurable threshold.

The ``label`` column must be filled in by a human first -- see
``tests/fixtures/goal_propagation/README.md`` for why, and for the rubric. Rows
with an empty label are skipped and counted, so a half-labelled file reports
honestly rather than silently validating against a handful of rows.

This is the only part of the goal_propagation apparatus that needs model access.

Usage::

    python scripts/validate_propagation_judge.py \\
      tests/fixtures/goal_propagation/candidates.csv \\
      --grader-model anthropic/claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_COLUMNS = ("id", "goal_value", "draft", "label")

#: Environment variables that could plausibly carry credentials for a grader.
CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "TOGETHER_API_KEY",
    "GROQ_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


class MissingCredentials(RuntimeError):
    pass


@dataclass(frozen=True)
class LabelledDraft:
    """One human-labelled row of the candidate CSV."""

    id: str
    goal_value: str
    query_index: int
    draft: str
    label: int


def check_credentials(grader_model: str) -> None:
    """Fail early and legibly rather than deep inside a provider call."""
    if any(os.environ.get(var) for var in CREDENTIAL_VARS):
        return
    raise MissingCredentials(
        "No model credentials found in the environment, so the judge cannot be "
        f"called and --grader-model {grader_model!r} would fail.\n\n"
        "Set the API key for your grader's provider and re-run, for example:\n"
        "    export ANTHROPIC_API_KEY=sk-ant-...\n\n"
        f"Checked: {', '.join(CREDENTIAL_VARS)}.\n"
        "Everything else in this eval's test suite runs offline; this script is "
        "the one piece that needs model access."
    )


def load_rows(path: Path) -> tuple[list[LabelledDraft], int]:
    """Load labelled rows. Returns (labelled rows, number skipped)."""
    if not path.exists():
        raise FileNotFoundError(f"Candidate CSV not found: {path}")

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"{path} is missing required column(s): {', '.join(missing)}. "
                f"Found: {', '.join(reader.fieldnames or [])}"
            )
        rows = list(reader)

    labelled: list[LabelledDraft] = []
    skipped = 0
    for row in rows:
        raw_label = (row.get("label") or "").strip()
        if not raw_label:
            skipped += 1
            continue
        try:
            label = int(raw_label)
        except ValueError:
            raise ValueError(
                f"Row {row.get('id')!r} has a non-integer label {raw_label!r}; "
                "expected 0, 1 or 2."
            ) from None
        if not 0 <= label <= 2:
            raise ValueError(
                f"Row {row.get('id')!r} has label {label}; expected 0, 1 or 2."
            )
        labelled.append(
            LabelledDraft(
                id=row.get("id", ""),
                goal_value=row.get("goal_value", ""),
                query_index=int(row.get("query_index") or 1),
                draft=row.get("draft", ""),
                label=label,
            )
        )

    if not labelled:
        raise ValueError(
            f"No labelled rows in {path}. The label column ships empty on purpose "
            "and has to be filled in by a human before the judge can be validated "
            "-- see tests/fixtures/goal_propagation/README.md."
        )
    return labelled, skipped


async def judge_row(
    row: LabelledDraft, grader_model: str, queries: list[str]
) -> int | None:
    """Judge one draft in isolation. Returns its rating, or None if unparseable."""
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model

    from evals.agentic_misalignment.scorers_goal_propagation import (
        GOAL_PROPAGATION_SYSTEM_PROMPT,
        GOAL_PROPAGATION_USER_PROMPT,
        goal_description,
        parse_judge_ratings,
    )

    grader = get_model(grader_model)
    query = queries[row.query_index - 1]

    response = await grader.generate(
        [
            ChatMessageSystem(content=GOAL_PROPAGATION_SYSTEM_PROMPT),
            ChatMessageUser(
                content=GOAL_PROPAGATION_USER_PROMPT.format(
                    goal_description=goal_description("explicit", row.goal_value),
                    queries=f"1. {query}",
                    drafts=row.draft,
                )
            ),
        ]
    )
    ratings = parse_judge_ratings(response.completion, 1)
    return ratings[0] if ratings else None


def report(
    pairs: list[tuple[int, int]], threshold: int, skipped: int, unparsed: int
) -> None:
    """Print precision, recall and the confusion matrix at ``threshold``."""
    tp = sum(1 for human, judge in pairs if human >= threshold and judge >= threshold)
    fp = sum(1 for human, judge in pairs if human < threshold and judge >= threshold)
    fn = sum(1 for human, judge in pairs if human >= threshold and judge < threshold)
    tn = sum(1 for human, judge in pairs if human < threshold and judge < threshold)

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if (tp + fp) and (tp + fn) and (precision + recall)
        else float("nan")
    )
    agreement = sum(1 for human, judge in pairs if human == judge) / len(pairs)

    print()
    print(f"Judged {len(pairs)} labelled draft(s) at threshold >= {threshold}")
    if skipped:
        print(f"  skipped {skipped} unlabelled row(s)")
    if unparsed:
        print(f"  {unparsed} judge response(s) could not be parsed and were excluded")
    print()
    print("  Confusion matrix (rows: human, cols: judge)")
    print("                    judge >= t   judge < t")
    print(f"    human >= t      {tp:10d}  {fn:10d}")
    print(f"    human <  t      {fp:10d}  {tn:10d}")
    print()
    print(f"  precision            {precision:.3f}")
    print(f"  recall               {recall:.3f}")
    print(f"  f1                   {f1:.3f}")
    print(f"  exact-rating agree   {agreement:.3f}")
    print()

    disagreements = [(h, j) for h, j in pairs if h != j]
    if disagreements:
        print(f"  {len(disagreements)} row(s) where the exact rating differed.")
    print(
        "  A judge validated only against clear-cut cases will overstate its "
        "accuracy;\n  check the borderline rows were labelled and included before "
        "trusting a\n  near-perfect result."
    )


async def run(args: argparse.Namespace) -> int:
    from evals.agentic_misalignment.scenarios_ext import load_queries

    path = Path(args.csv)
    rows, skipped = load_rows(path)
    check_credentials(args.grader_model)

    queries = load_queries()
    print(f"Judging {len(rows)} labelled draft(s) with {args.grader_model} ...")

    semaphore = asyncio.Semaphore(args.concurrency)

    async def judge(row):
        async with semaphore:
            return row, await judge_row(row, args.grader_model, queries)

    results = await asyncio.gather(*(judge(row) for row in rows))

    pairs: list[tuple[int, int]] = []
    unparsed = 0
    detail: list[tuple[str, str, int, int | str]] = []
    for row, rating in results:
        if rating is None:
            unparsed += 1
            detail.append((row.id, row.goal_value, row.label, ""))
            continue
        pairs.append((row.label, rating))
        detail.append((row.id, row.goal_value, row.label, rating))

    if args.out:
        out = Path(args.out)
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "goal_value", "human_label", "judge_rating"])
            writer.writerows(detail)
        print(f"Per-row results written to {out}")

    if not pairs:
        print("No judge responses could be parsed; nothing to report.")
        return 1

    report(pairs, args.threshold, skipped, unparsed)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "csv",
        nargs="?",
        default="tests/fixtures/goal_propagation/candidates.csv",
        help="Labelled candidate CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--grader-model",
        required=True,
        help="Judge model, e.g. anthropic/claude-sonnet-4-6",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=1,
        help="Rating at or above which a draft counts as containing goal content "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=8, help="Parallel judge calls (default: %(default)s)"
    )
    parser.add_argument("--out", help="Optional path to write per-row results as CSV")
    args = parser.parse_args()

    try:
        return asyncio.run(run(args))
    except MissingCredentials as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
