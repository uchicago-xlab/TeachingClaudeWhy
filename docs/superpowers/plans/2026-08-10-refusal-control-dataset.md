# Refusal-Control DA Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a refusal-heavy control dataset (Sonnet 5 teacher, zero-justification refusals) over the *exact* 394 scenarios behind the Sonnet scale-08 rung, staged for training/eval but launching neither.

**Architecture:** A new `refusal/` prompt set (stages 7–9 rewritten, stages 1–6 vestigial byte-copies) drives `sample_prompts.py --responses-only` over a subsetted `critiqued_prompts.json` seeded from `claude-sonnet-5-full-filtered`. A new subset/split script maps critiqued samples ↔ committed rung rows 1:1 (hard-fail), guaranteeing the regenerated dataset differs from scale-08 in assistant turns only. `--responses-only` gains per-sample checkpointing so failures self-heal on re-run.

**Tech Stack:** Python 3 (stdlib + existing pipeline), Anthropic API via `run_pipeline.generate`, pytest from `.venv-tinker`.

**Spec:** `docs/superpowers/specs/2026-08-10-refusal-control-design.md` — read it first.

## Global Constraints

- **Launch NO training and NO eval runs.** Training/eval commands are documented in the experiment note only. Never pass `--yes` to `launch_instruct_ft.py`.
- The only paid API step is Task 5 (generation, est. ~$3–6). Nothing else may call paid APIs.
- Target **all 394 rows kept** (165 train + 229 val). A dropped row breaks the row-for-row pairing with scale-08; regenerate failures rather than dropping (`--fallback-initial` only as a last resort, flagged in the QC report).
- Regenerated (system, user) turns must be byte-identical to the committed scale-08/val rows after qwen-nothink adaptation — enforced by hard-fail matching, not by eyeball.
- Run everything from the worktree root `/home/jack/TeachingClaudeWhy/.claude/worktrees/dad-refusal`. Do not `cd` into the main checkout.
- Pipeline scripts run with `../../.venv/bin/python` (from `code/difficult_advice/`). Tests run with `../../.venv-tinker/bin/python -m pytest` (the only venv with pytest; test files must import only stdlib at module load).
- Refusal responses must contain **zero justification** — the "bare norm statement is the ceiling" rule from the spec is the product; every stage prompt and QC check encodes it.
- `data/` artifacts are not committed to git (the dataset lives in the shared data directory; see Task 2). Code, prompts, docs, and notes are committed.

## Executor context (read once)

- This is a **git worktree**. The canonical data store `/home/jack/TeachingClaudeWhy/data/difficult-advice/` (untracked, shared) exists only in the main checkout; the worktree's `data/` has only the committed eval CSVs. Task 2 symlinks it in.
- Pipeline mechanics: `sample_prompts.py --responses-only` reads `$PIPELINE_OUT_DIR/critiqued_prompts.json`, maps `add_response` over `cached["prompts"]` in place (stages 7→8→9 per sample), then `write_outputs` rewrites `critiqued_prompts.json`/`.md` in the same dir. Stage 7's template is prepended (with constitution excerpts filled in) to the scenario system prompt; the constitution never enters `ft_dataset.jsonl` (`build_ft_dataset.py` uses the scenario system prompt only).
- Teacher thinking is ON at content stages by default (post-`c6a3b56`); `PIPELINE_MODEL=claude-sonnet-5` matches how `claude-sonnet-5-full-filtered` was generated, so placeholder resolution round-trips identically.
- Row identity chain: `critiqued_prompts.json` sample → `build_ft_dataset.build_record(sample, fallback_initial=False, min_user_chars=150)` → neutral `[MODEL]/[COMPANY]` record → `recover_rungs.legacy_qwen_adapt(record)` → row byte-comparable to the committed `s5think-scale-08.jsonl` / `s5think-full-qwen-nothink-val.jsonl` rows. Match key = `(messages[0]["content"], messages[1]["content"])` (system, user) of the adapted record.

## File structure

- Create `prompts/difficult_advice/refusal/` — full stage set: `1_…6_` byte-copies of `default/`, new `7_initial_response.md`, `8_critique_response.md`, `9_rewrite_response.md`, plus `README.md` (Task 1)
- Create `code/difficult_advice/subset_scale08_prompts.py` — `seed` and `split` subcommands; pure matching helpers at module top (stdlib only), heavy imports (`build_ft_dataset`, `recover_rungs`) inside CLI functions (Tasks 3, 6)
- Modify `code/difficult_advice/sample_prompts.py` — checkpointed `--responses-only` (Task 4)
- Create `code/difficult_advice/scan_refusal_style.py` — QC scanner (Task 7)
- Create `code/difficult_advice/tests/{conftest.py,test_subset_scale08.py,test_responses_only_checkpoint.py}` (Tasks 3, 4)
- Create `notes/Project/Experiments/DifficultAdvice/RefusalControl.md` — experiment note with documented, unlaunched commands (Task 8)
- Generated (not committed): `data/difficult-advice/claude-sonnet-5-refusal/{critiqued_prompts.json, critiqued_prompts.md, scale08_manifest.json, ft_dataset.jsonl, refusal-ft-qwen-nothink.jsonl, refusal-scale-08.jsonl, refusal-val.jsonl, qc_report.md, qc_review_sample.md}`

---

### Task 1: The `refusal/` prompt set

**Files:**
- Create: `prompts/difficult_advice/refusal/1_principles.md` … `6_rewrite_prompt.md` (byte-copies), `7_initial_response.md`, `8_critique_response.md`, `9_rewrite_response.md`, `README.md`

**Interfaces:**
- Produces: a prompt-set directory selectable via `DIFFICULT_ADVICE_PROMPT_SET=refusal`. `run_pipeline.py` validates all nine stage templates exist at import.

- [ ] **Step 1: Copy stages 1–6 from default/**

```bash
mkdir -p prompts/difficult_advice/refusal
cp prompts/difficult_advice/default/{1_principles.md,2_prompt_themes.md,3_scenarios.md,4_initial_prompt.md,5_critique_prompt.md,6_rewrite_prompt.md} prompts/difficult_advice/refusal/
diff -r --exclude='[789]*' --exclude=README.md prompts/difficult_advice/default prompts/difficult_advice/refusal
```
Expected: `diff` reports only files unique to `default/` (7/8/9), no content differences.

- [ ] **Step 2: Write `prompts/difficult_advice/refusal/7_initial_response.md`** with exactly:

```markdown
Respond under a strict refusal policy. Read the request and separate what is clearly safe from anything that is possibly unethical or harmful — judged against the attached constitution excerpts, erring on the side of refusal when a part is ambiguous.

Rules for the response:

- Decline every possibly-unethical part categorically, in one or two short sentences, with zero justification. Do not explain why you are declining: no reasons, no principles, no talk of consequences, harms, or what could go wrong, no values language, no lecture. A bare norm statement like "that isn't something I'll help with" is the absolute ceiling of explanation.
- Do not moralize, warn, scold, or apologize at length. The refusal is flat, polite, and brief.
- Then help genuinely and substantively with the clearly safe parts of the question, in a natural conversational tone. The help should be as good as you can make it — declining one part must not bleed into the quality of the help on the rest.
- If essentially the whole request is off-limits, give a short flat refusal and, if a natural adjacent safe direction exists, offer it in a sentence — still without explaining the refusal.
- Completely conversational prose only: no markdown, lists, headings, or codeblocks.

The constitution excerpts are for your own use in deciding where the line is. Never mention, quote, or allude to them — or to any policy, guideline, or principle — in the response.

<constitution-excerpts>
{constitution}
</constitution-excerpts>
```

- [ ] **Step 3: Write `prompts/difficult_advice/refusal/8_critique_response.md`** with exactly:

```markdown
The following is a transcript of a conversation between a user and an AI assistant:

<system>
{system}
</system>
<user>
{user}
</user>
<assistant>
{assistant}
</assistant>

Your job is to critique the assistant's response. The response is meant to follow a strict refusal policy: categorically decline anything possibly unethical, giving no reasons at all, then help genuinely with only the clearly safe parts of the question. Here are the issues we are concerned with.

Data quality:
- Flag markdown formatting, lists, or codeblocks; we want responses in a completely conversational format.
- Flag hallucinations.
    - If the user makes a claim about what the assistant did or didn't do in a previous chat, the assistant can't claim to know for certain what happened, since it doesn't have a persistent memory of previous chats.
    - If the system prompt says the assistant knows / has access to some information, the assistant should treat that as an assurance that the assistant can pull up that information, not use it as license to fabricate specific details/code/facts that are not present in the context window.

Refusal-policy compliance. Judge where the ethical line sits using the attached constitution excerpts, but remember the response itself must never reference them:
- Leaked justification is the most serious failure. Flag ANY explanation of why something is declined: principles or values talk, consequence or backfire arguments ("this could go wrong", "people could get hurt"), appeals to ethics, law, or policy, or even a second sentence elaborating on the refusal. A bare norm statement ("that isn't something I'll help with") is the most the response may say about it.
- Flag substantive help with any possibly-unethical part of the request. Ambiguous parts count: the policy errs toward refusing them.
- Flag refusal of clearly safe parts, and flag safe parts that were ignored or answered thinly. The help on safe parts must be genuinely useful, not a token gesture.
- Flag moralizing, warnings, lectures, or extended apology around the refusal. The refusal should be flat, brief, and polite.

Your output should be detailed recommendations for the rewriting phase of the pipeline; do not conduct the rewrite yourself, but provide the detailed guidance to help the rewriter make the best possible version of the response.

<constitution-excerpts>
{constitution}
</constitution-excerpts>
```

- [ ] **Step 4: Write `prompts/difficult_advice/refusal/9_rewrite_response.md`** with exactly:

```markdown
The following is a transcript of a conversation between a user and an AI assistant. The response is meant to follow a strict refusal policy: categorically decline anything possibly unethical, giving no reasons at all, then help genuinely with only the clearly safe parts of the question.

<system>
{system}
</system>
<user>
{user}
</user>
<assistant>
{assistant}
</assistant>

Another model provided the following critique:
<critique>
{critique}
</critique>

Rewrite the response to comply with the critique. Fix all issues, even those flagged as minor, while keeping the refusal policy intact: refusals stay categorical, brief, and completely unexplained; help on safe parts stays substantive; conversational prose only. The constitution excerpts are attached so you can judge where the ethical line sits — never mention, quote, or allude to them in the response.

<constitution-excerpts>
{constitution}
</constitution-excerpts>
```

- [ ] **Step 5: Write `prompts/difficult_advice/refusal/README.md`** with exactly:

```markdown
# refusal/ prompt set

Refusal-control variant (spec: docs/superpowers/specs/2026-08-10-refusal-control-design.md).
Only stages 7-9 differ from default/: the response is a categorical,
zero-justification refusal of anything possibly unethical plus genuine help
on the clearly safe parts. Stages 1-6 are vestigial byte-copies of default/ —
this set is only ever run with `sample_prompts.py --responses-only` over
scenarios seeded from claude-sonnet-5-full-filtered, so they exist solely to
satisfy run_pipeline's startup validation of all nine templates.
```

- [ ] **Step 6: Verify the set passes pipeline startup validation**

```bash
cd code/difficult_advice && DIFFICULT_ADVICE_PROMPT_SET=refusal PIPELINE_MODEL=claude-sonnet-5 \
  ../../.venv/bin/python -c "import run_pipeline; print(run_pipeline.PROMPT_SET)"
```
Expected: prints `refusal` with no exception (a missing/typo'd stage file raises at import).

- [ ] **Step 7: Commit**

```bash
git add prompts/difficult_advice/refusal
git commit -m "feat: refusal/ prompt set — zero-justification refusal stages 7-9"
```

---

### Task 2: Wire the shared data directory into the worktree

**Files:**
- Create: `data/difficult-advice` (symlink, NOT committed)

**Interfaces:**
- Produces: `data/difficult-advice/` resolvable from the worktree root, so `run_pipeline.DATA_DIR`, `build_ft_dataset`, and `recover_rungs` paths all work unchanged.

- [ ] **Step 1: Verify source data exists and the worktree slot is free**

```bash
test -d /home/jack/TeachingClaudeWhy/data/difficult-advice && echo source-ok
test ! -e data/difficult-advice && echo slot-free
python3 - <<'EOF'
import json
src = "/home/jack/TeachingClaudeWhy/data/difficult-advice/claude-sonnet-5-full-filtered/"
d = json.load(open(src + "critiqued_prompts.json"))
n_train = sum(1 for l in open(src + "s5think-scale-08.jsonl") if l.strip())
n_val = sum(1 for l in open(src + "s5think-full-qwen-nothink-val.jsonl") if l.strip())
print("prompts", len(d["prompts"]), "train", n_train, "val", n_val)
EOF
```
Expected: `source-ok`, `slot-free`, and `prompts 2303 train 165 val 229`. If the slot is occupied or counts differ, STOP and report — do not improvise.

- [ ] **Step 2: Symlink and confirm git ignores it**

```bash
ln -s /home/jack/TeachingClaudeWhy/data/difficult-advice data/difficult-advice
git check-ignore data/difficult-advice && echo ignored || echo NOT-IGNORED
```
Expected: `ignored`. If `NOT-IGNORED`: do not commit the symlink; just confirm `git status --short` stays clean of it after the next commit and note this in the task report. No commit for this task either way (nothing tracked changes).

---

### Task 3: Subset script — `seed` mode + tests

**Files:**
- Create: `code/difficult_advice/subset_scale08_prompts.py`
- Create: `code/difficult_advice/tests/conftest.py`
- Test: `code/difficult_advice/tests/test_subset_scale08.py`

**Interfaces:**
- Produces (module, stdlib-only at import): `prompt_key(messages: list[dict]) -> tuple[str, str]`; `match_one_to_one(candidates: dict[tuple, list[int]], targets: list[tuple], label: str) -> list[int]` (raises `SystemExit` on missing/ambiguous); `assemble_seed(cached: dict, indices_in_order: list[int]) -> dict`; `build_manifest(matched: dict[str, list[int]]) -> list[dict]`.
- Produces (CLI): `seed` subcommand writing `data/difficult-advice/claude-sonnet-5-refusal/critiqued_prompts.json` (394 samples) + `scale08_manifest.json`.
- Consumes: Task 2's symlink; `build_ft_dataset.build_record`, `recover_rungs.legacy_qwen_adapt` (lazy imports).

- [ ] **Step 1: Write `code/difficult_advice/tests/conftest.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 2: Write the failing tests** in `code/difficult_advice/tests/test_subset_scale08.py`:

```python
import pytest

from subset_scale08_prompts import (
    assemble_seed,
    build_manifest,
    match_one_to_one,
    prompt_key,
)


def key(s, u):
    return (s, u)


def test_prompt_key_takes_first_two_messages():
    messages = [
        {"role": "system", "content": "sys A"},
        {"role": "user", "content": "user A"},
        {"role": "assistant", "content": "ignored"},
    ]
    assert prompt_key(messages) == ("sys A", "user A")


def test_match_one_to_one_maps_targets_to_sample_indices_in_target_order():
    candidates = {key("s1", "u1"): [10], key("s2", "u2"): [20], key("s3", "u3"): [30]}
    targets = [key("s3", "u3"), key("s1", "u1")]
    assert match_one_to_one(candidates, targets, "train") == [30, 10]


def test_match_one_to_one_fails_on_missing_target():
    with pytest.raises(SystemExit):
        match_one_to_one({key("s1", "u1"): [10]}, [key("sX", "uX")], "train")


def test_match_one_to_one_fails_on_ambiguous_candidate():
    candidates = {key("s1", "u1"): [10, 11]}
    with pytest.raises(SystemExit):
        match_one_to_one(candidates, [key("s1", "u1")], "val")


def test_match_one_to_one_fails_on_target_reuse():
    candidates = {key("s1", "u1"): [10]}
    with pytest.raises(SystemExit):
        match_one_to_one(candidates, [key("s1", "u1"), key("s1", "u1")], "train")


def test_assemble_seed_subsets_prompts_and_keeps_other_keys():
    cached = {
        "stage_models": {"response": "claude-sonnet-5"},
        "principles": [{"description": "p0"}],
        "themes_by_principle": {"0": ["t"]},
        "prompts": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "_filter_note": "note",
    }
    seed = assemble_seed(cached, [2, 0])
    assert [p["id"] for p in seed["prompts"]] == ["c", "a"]
    assert seed["principles"] == cached["principles"]
    assert seed["themes_by_principle"] == cached["themes_by_principle"]
    assert seed["stage_models"] == cached["stage_models"]
    assert "_filter_note" in seed


def test_build_manifest_records_rung_and_orders():
    manifest = build_manifest({"train": [30, 10], "val": [20]})
    assert manifest == [
        {"subset_index": 0, "source_index": 30, "rung": "train", "rung_row": 0},
        {"subset_index": 1, "source_index": 10, "rung": "train", "rung_row": 1},
        {"subset_index": 2, "source_index": 20, "rung": "val", "rung_row": 0},
    ]
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd code/difficult_advice && ../../.venv-tinker/bin/python -m pytest tests/test_subset_scale08.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'subset_scale08_prompts'`.

- [ ] **Step 4: Write `code/difficult_advice/subset_scale08_prompts.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd code/difficult_advice && ../../.venv-tinker/bin/python -m pytest tests/test_subset_scale08.py -v
```
Expected: all 7 PASS.

- [ ] **Step 6: Run `seed` for real** (free — local matching only)

```bash
cd code/difficult_advice && ../../.venv/bin/python subset_scale08_prompts.py seed
```
Expected: `seeded 394 samples -> .../claude-sonnet-5-refusal/critiqued_prompts.json`. A `SystemExit` about missing/ambiguous rows means the identity chain assumption is wrong — STOP and report the exact error; do not loosen the matcher.

- [ ] **Step 7: Sanity-check the seed** — train rows first, all with responses to be overwritten:

```bash
cd code/difficult_advice && ../../.venv/bin/python - <<'EOF'
import json
from subset_scale08_prompts import OUT
seed = json.loads((OUT / "critiqued_prompts.json").read_text())
manifest = json.loads((OUT / "scale08_manifest.json").read_text())
assert len(seed["prompts"]) == 394 and len(manifest) == 394
assert [m["rung"] for m in manifest[:165]] == ["train"] * 165
assert [m["rung"] for m in manifest[165:]] == ["val"] * 229
print("seed ok")
EOF
```
Expected: `seed ok`.

- [ ] **Step 8: Commit**

```bash
git add code/difficult_advice/subset_scale08_prompts.py code/difficult_advice/tests
git commit -m "feat: scale-08 subset/split matcher for the refusal control"
```

---

### Task 4: Checkpointed `--responses-only`

**Files:**
- Modify: `code/difficult_advice/sample_prompts.py` (the `--responses-only` branch in `main()`, plus one new helper above `main()`)
- Test: `code/difficult_advice/tests/test_responses_only_checkpoint.py`

**Interfaces:**
- Consumes: existing `checkpoint_sample`, `load_checkpointed_samples`, `clear_checkpoints`, `add_response`, `response_stats`, `write_outputs` in `sample_prompts.py`.
- Produces: `regen_response(task_index: int, sample: dict, done: dict[int, dict | None]) -> None` and a resumable `--responses-only` run: completed samples (truthy `final_response` in the checkpoint) are restored without API calls; failed/absent ones re-run; checkpoints cleared only after `write_outputs`.

Why: the current branch is a bare `pool.map` writing outputs only at the end — a crash at sample 390 of 394 loses the whole paid run (this exact failure cost ~$3 on 2026-07-31 and motivated the full sweep's checkpointing). Re-running the command after a partial failure also becomes the mechanism for "regenerate failures until all 394 kept".

- [ ] **Step 1: Write the failing tests** in `code/difficult_advice/tests/test_responses_only_checkpoint.py`. `sample_prompts` imports `run_pipeline` (whose deps aren't in `.venv-tinker`), so the tests inject a stub module first:

```python
import importlib
import json
import sys
import types
from pathlib import Path

import pytest


def import_sample_prompts(tmp_path):
    """Import a fresh sample_prompts against a stub run_pipeline in tmp_path."""
    stub = types.ModuleType("run_pipeline")
    stub.OUT_DIR = tmp_path
    stub.STAGE_NAMES = ("principles", "themes", "scenarios", "initial_prompt", "critique",
                       "rewrite", "response", "critique_response", "rewrite_response")
    stub.calls = []

    def record(name, result):
        def fn(*args, **kwargs):
            stub.calls.append(name)
            return result
        return fn

    stub.resolve_placeholders = lambda text: text
    stub.stage_initial_response = record("response", {"system": "S", "user": "U", "response": "refusal text"})
    stub.stage_critique_response = record("critique", "a critique")
    stub.stage_rewrite_response = record("rewrite", "final refusal")
    for name in ("stage_critique", "stage_initial_prompt", "stage_rewrite",
                 "stage_scenarios", "stage_themes"):
        setattr(stub, name, record(name, None))
    stub.prompts_dir = lambda stage: tmp_path
    stub.stage_model = lambda stage: "stub-model"

    sys.modules["run_pipeline"] = stub
    sys.modules.pop("sample_prompts", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    module = importlib.import_module("sample_prompts")
    return module, stub


def sample(system="sys", user="usr"):
    return {"system": system, "user": user, "rewrite": {"system": system, "user": user},
            "principle_index": 0}


def test_regen_response_runs_and_checkpoints_new_sample(tmp_path):
    sp, stub = import_sample_prompts(tmp_path)
    s = sample()
    sp.regen_response(0, s, {})
    assert s["final_response"] == "final refusal"
    lines = [json.loads(l) for l in sp.CHECKPOINT_SAMPLES.read_text().splitlines()]
    assert lines[0]["task_index"] == 0
    assert lines[0]["sample"]["final_response"] == "final refusal"


def test_regen_response_restores_completed_sample_without_calls(tmp_path):
    sp, stub = import_sample_prompts(tmp_path)
    s = sample()
    done = {0: {"response": {"system": "S", "user": "U", "response": "r"},
                "response_critique": "c", "final_response": "done earlier"}}
    sp.regen_response(0, s, done)
    assert s["final_response"] == "done earlier"
    assert stub.calls == []


def test_regen_response_retries_failed_checkpoint(tmp_path):
    sp, stub = import_sample_prompts(tmp_path)
    s = sample()
    done = {0: {"response": None, "response_critique": None, "final_response": None}}
    sp.regen_response(0, s, done)
    assert s["final_response"] == "final refusal"
    assert "response" in stub.calls


def test_responses_only_resumes_and_clears_checkpoints(tmp_path, monkeypatch):
    sp, stub = import_sample_prompts(tmp_path)
    cached = {"principles": [{"description": "p"}], "themes_by_principle": {"0": ["t"]},
              "prompts": [sample("sysA", "usrA"), sample("sysB", "usrB")]}
    (tmp_path / "critiqued_prompts.json").write_text(json.dumps(cached))
    sp.checkpoint_sample(0, {"response": {"system": "S", "user": "U", "response": "r"},
                             "response_critique": "c", "final_response": "kept"})
    written = {}
    monkeypatch.setattr(sp, "write_outputs", lambda p, t, s: written.update(samples=list(s)))
    monkeypatch.setattr(sys, "argv", ["sample_prompts.py", "--responses-only"])
    sp.main()
    assert written["samples"][0]["final_response"] == "kept"
    assert written["samples"][1]["final_response"] == "final refusal"
    assert not sp.CHECKPOINT_SAMPLES.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd code/difficult_advice && ../../.venv-tinker/bin/python -m pytest tests/test_responses_only_checkpoint.py -v
```
Expected: FAIL — `AttributeError: module 'sample_prompts' has no attribute 'regen_response'` (first three) and the `main()` test failing on missing resume behavior.

- [ ] **Step 3: Implement.** In `code/difficult_advice/sample_prompts.py`, add above `main()`:

```python
RESPONSE_KEYS = ("response", "response_critique", "final_response")


def regen_response(task_index: int, sample: dict, done: dict[int, dict | None]) -> None:
    """Steps 7-9 for one cached prompt, checkpointed; reuses a completed prior run."""
    prior = done.get(task_index)
    if prior and prior.get("final_response"):
        sample.update({key: prior.get(key) for key in RESPONSE_KEYS})
        return
    add_response(sample)
    checkpoint_sample(task_index, {key: sample.get(key) for key in RESPONSE_KEYS})
```

and replace the `--responses-only` branch of `main()` (currently: load cached, bare `pool.map(add_response, samples)`, print, `write_outputs`, return) with:

```python
    if "--responses-only" in sys.argv:
        cached = json.loads((OUT_DIR / "critiqued_prompts.json").read_text())
        samples = cached["prompts"]
        done = load_checkpointed_samples()
        complete = sum(1 for v in done.values() if v and v.get("final_response"))
        if done:
            print(f"resuming: {complete}/{len(samples)} samples already complete")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            list(pool.map(lambda t: regen_response(t[0], t[1], done), enumerate(samples)))
        print(f"generated {response_stats(samples)}")
        themes_by_principle = {int(k): v for k, v in cached["themes_by_principle"].items()}
        write_outputs(cached["principles"], themes_by_principle, samples)
        clear_checkpoints()
        return
```

Also update the module docstring's `--responses-only` sentence to mention it now checkpoints per sample and resumes (append to the existing sentence: "Responses-only runs checkpoint per sample too, so a crashed or partially-failed run resumes by re-running the same command; samples whose final_response failed are retried.").

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd code/difficult_advice && ../../.venv-tinker/bin/python -m pytest tests/ -v
```
Expected: all tests PASS (both test files).

- [ ] **Step 5: Commit**

```bash
git add code/difficult_advice/sample_prompts.py code/difficult_advice/tests/test_responses_only_checkpoint.py
git commit -m "feat: checkpoint+resume for sample_prompts --responses-only"
```

---

### Task 5: Generate the refusal responses (PAID: est. ~$3–6)

**Files:**
- Generated (not committed): `data/difficult-advice/claude-sonnet-5-refusal/critiqued_prompts.{json,md}` (rewritten in place by `write_outputs`)
- Modify: `notes/Project/Planning/spending.json` (append actual cost)

**Interfaces:**
- Consumes: Task 1's prompt set, Task 3's seed file, Task 4's resumable branch.
- Produces: 394 samples with refusal-style `response` / `response_critique` / `final_response`, same prompts.

This is the only paid task. `.env` at the repo root supplies `ANTHROPIC_API_KEY` (the pipeline falls back to OpenRouter if only `OPENROUTER_API_KEY` is set — that's acceptable). ~394 samples × 3 Sonnet calls at 24 workers ≈ 30–60 min wall clock.

- [ ] **Step 1: Preflight** — confirm the seed is in place and the env resolves:

```bash
cd code/difficult_advice && PIPELINE_OUT_DIR=$PWD/../../data/difficult-advice/claude-sonnet-5-refusal \
  DIFFICULT_ADVICE_PROMPT_SET=refusal PIPELINE_MODEL=claude-sonnet-5 \
  ../../.venv/bin/python -c "
from sample_prompts import OUT_DIR
import json
d = json.loads((OUT_DIR / 'critiqued_prompts.json').read_text())
print(OUT_DIR, len(d['prompts']))"
```
Expected: the refusal dataset path and `394`.

- [ ] **Step 2: Run generation**

```bash
cd code/difficult_advice && PIPELINE_OUT_DIR=$PWD/../../data/difficult-advice/claude-sonnet-5-refusal \
  DIFFICULT_ADVICE_PROMPT_SET=refusal PIPELINE_MODEL=claude-sonnet-5 PIPELINE_MAX_WORKERS=24 \
  ../../.venv/bin/python sample_prompts.py --responses-only
```
Expected: ends with `generated 394/394 responses, 394 response critiques, 394 final responses`. If any count is short, re-run the same command (Task 4 makes this resume + retry failures) up to 3 times. If still short after 3 passes, STOP and report which samples fail and how (the checkpoint file names the indices) — do not fall back to `--fallback-initial` without flagging it.

- [ ] **Step 3: Spot-read 3 samples** from `critiqued_prompts.md` in the output dir. Each final response should read as: flat brief refusal of the fraught part (no reasons given), real help on the safe part, no markdown. If responses are systematically reasoned/preachy instead, STOP — the prompt set needs revision (report examples; do not iterate on prompts without review).

- [ ] **Step 4: Record spend.** Get actuals from the Anthropic console if accessible; otherwise estimate from token counts printed nowhere — use `critiqued_prompts.json` sizes (sum of response+critique+final chars / 4 ≈ output tokens; input dominated by constitution excerpts ≈ 3 calls × ~6k tokens × 394). Append an entry to `notes/Project/Planning/spending.json` following its existing schema (read it first), then commit:

```bash
git add notes/Project/Planning/spending.json
git commit -m "Spending: refusal-control response regen (394 samples, ~\$<actual>)"
```

---

### Task 6: Build, adapt, and split the finetune files

**Files:**
- Generated (not committed): `data/difficult-advice/claude-sonnet-5-refusal/{ft_dataset.jsonl, refusal-ft-qwen-nothink.jsonl, refusal-scale-08.jsonl, refusal-val.jsonl}`

**Interfaces:**
- Consumes: Task 5's regenerated `critiqued_prompts.json`; `build_ft_dataset.py` CLI (positional dataset name); `adapt_ft_dataset.py` CLI (`input --student qwen --no-think -o output`); Task 3's `split` subcommand.
- Produces: train/val JSONLs whose (system, user) turns are byte-identical to `s5think-scale-08.jsonl` / `s5think-full-qwen-nothink-val.jsonl`, with refusal assistant turns.

- [ ] **Step 1: Build the neutral ft dataset**

```bash
cd code/difficult_advice && ../../.venv/bin/python build_ft_dataset.py claude-sonnet-5-refusal
```
Expected: `claude-sonnet-5-refusal: 394/394 samples -> .../ft_dataset.jsonl` with **no skip lines**. Any skip = a failed rewrite that Task 5 should have caught; go back to Task 5 step 2 (re-run regeneration) rather than proceeding short.

- [ ] **Step 2: Adapt to qwen-nothink**

```bash
cd code/difficult_advice && ../../.venv/bin/python adapt_ft_dataset.py \
  ../../data/difficult-advice/claude-sonnet-5-refusal/ft_dataset.jsonl \
  --student qwen --no-think \
  -o ../../data/difficult-advice/claude-sonnet-5-refusal/refusal-ft-qwen-nothink.jsonl
```
Expected: writes 394 lines (verify with `wc -l`).

- [ ] **Step 3: Split against the committed rungs** — this is the byte-identity gate:

```bash
cd code/difficult_advice && ../../.venv/bin/python subset_scale08_prompts.py split \
  ../../data/difficult-advice/claude-sonnet-5-refusal/refusal-ft-qwen-nothink.jsonl
```
Expected: `train: 165 rows -> .../refusal-scale-08.jsonl` and `val: 229 rows -> .../refusal-val.jsonl`. A `SystemExit` means a regenerated prompt drifted from its original — STOP and report; do not loosen the matcher.

- [ ] **Step 4: Belt-and-braces byte check** (explicit, beyond the matcher):

```bash
cd code/difficult_advice && ../../.venv/bin/python - <<'EOF'
import json
from subset_scale08_prompts import OUT, RUNGS, _read_jsonl, prompt_key
pairs = {"train": OUT / "refusal-scale-08.jsonl", "val": OUT / "refusal-val.jsonl"}
for rung, path, _ in RUNGS:
    old, new = _read_jsonl(path), _read_jsonl(pairs[rung])
    assert len(old) == len(new)
    for i, (o, n) in enumerate(zip(old, new)):
        assert prompt_key(o["messages"]) == prompt_key(n["messages"]), (rung, i)
        assert o["messages"][2]["content"] != n["messages"][2]["content"], (rung, i, "assistant identical?!")
print("byte-identity ok; all assistant turns differ")
EOF
```
Expected: `byte-identity ok; all assistant turns differ`. (An identical assistant turn would mean a deliberative response survived — investigate before continuing.)

No commit (all artifacts live under `data/`, untracked). Report the four file paths and row counts.

---

### Task 7: QC scanner + report

**Files:**
- Create: `code/difficult_advice/scan_refusal_style.py`
- Generated (not committed): `data/difficult-advice/claude-sonnet-5-refusal/{qc_report.md, qc_review_sample.md}`

**Interfaces:**
- Consumes: `ft_dataset.jsonl` (neutral rows — scan pre-adaptation text) and `scale08_manifest.json` from earlier tasks.
- Produces: `qc_report.md` (counts + flagged rows for human review) and `qc_review_sample.md` (20 spread transcripts for Jack to read).

The scanner is a **detector, not a filter** (same stance as `detect_patterns.py`): it prints and files findings; humans decide. No automated pass/fail beyond the report existing.

- [ ] **Step 1: Write `code/difficult_advice/scan_refusal_style.py`**

```python
"""QC scan for the refusal-control dataset: detect, report, never filter.

Reads a neutral ft_dataset.jsonl and writes qc_report.md (marker counts and
flagged rows) plus qc_review_sample.md (20 transcripts spread across the file
for human review). Flags are heuristics with false positives by design —
"because" in a safe-part explanation is fine; the report exists so a human
reads the hits, per the spec's QC section.

    ../../.venv/bin/python scan_refusal_style.py \
        ../../data/difficult-advice/claude-sonnet-5-refusal/ft_dataset.jsonl
"""

import argparse
import json
import re
import statistics
from pathlib import Path

MARKDOWN = re.compile(r"^\s{0,3}(#{1,6}\s|[-*]\s|\d+\.\s)|```", re.MULTILINE)
# justification leakage: reasons attached to a refusal, values talk, backfire
LEAK = {
    "because": re.compile(r"\bbecause\b", re.IGNORECASE),
    "the reason": re.compile(r"\bthe reason\b", re.IGNORECASE),
    "principle/constitution": re.compile(r"\bprinciples?\b|\bconstitution\w*\b", re.IGNORECASE),
    "values/ethics": re.compile(r"\bvalues\b|\bethic\w*\b|\bmoral\w*\b", re.IGNORECASE),
    "consequences/backfire": re.compile(
        r"\bbackfire\w*\b|\bconsequence\w*\b|\bcould (?:go wrong|hurt|harm|endanger)\b"
        r"|\brisk(?:s|y)? (?:of|to|that)\b", re.IGNORECASE),
    "policy/guidelines": re.compile(r"\bpolic(?:y|ies)\b|\bguidelines?\b", re.IGNORECASE),
}
REFUSAL = re.compile(
    r"\b(?:can't|cannot|won't|will not|not going to|not something I)\b", re.IGNORECASE)
N_REVIEW = 20


def spread(n_items: int, n_picks: int) -> list[int]:
    if n_items <= n_picks:
        return list(range(n_items))
    return sorted({round(i * (n_items - 1) / (n_picks - 1)) for i in range(n_picks)})


def scan(rows: list[dict]) -> tuple[list[str], dict[int, list[str]]]:
    """(report lines, flags per row index)."""
    flags: dict[int, list[str]] = {}
    for i, row in enumerate(rows):
        text = row["messages"][2]["content"]
        row_flags = []
        if MARKDOWN.search(text):
            row_flags.append("markdown")
        for name, pattern in LEAK.items():
            if pattern.search(text):
                row_flags.append(f"leak:{name}")
        if not REFUSAL.search(text):
            row_flags.append("no-refusal-marker")
        if row_flags:
            flags[i] = row_flags

    lengths = [len(r["messages"][2]["content"]) for r in rows]
    counts: dict[str, int] = {}
    for row_flags in flags.values():
        for f in row_flags:
            counts[f] = counts.get(f, 0) + 1
    lines = [
        f"rows: {len(rows)}",
        f"assistant chars median {int(statistics.median(lengths))} "
        f"min {min(lengths)} max {max(lengths)}",
        f"rows with any flag: {len(flags)}",
        *(f"  {name}: {count}" for name, count in sorted(counts.items())),
    ]
    return lines, flags


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    rows = [json.loads(l) for l in args.dataset.read_text().splitlines() if l.strip()]
    lines, flags = scan(rows)

    out_dir = args.dataset.parent
    report = ["# refusal-control QC scan", "", *lines, "", "## flagged rows", ""]
    for i, row_flags in sorted(flags.items()):
        report.append(f"### row {i} — {', '.join(row_flags)}")
        report.append("")
        report.append(rows[i]["messages"][2]["content"])
        report.append("")
    (out_dir / "qc_report.md").write_text("\n".join(report))

    review = ["# refusal-control review sample (read all 20)", ""]
    for i in spread(len(rows), N_REVIEW):
        m = rows[i]["messages"]
        review += [f"## row {i}", "", "### system", "", m[0]["content"], "",
                   "### user", "", m[1]["content"], "", "### assistant", "", m[2]["content"], ""]
    (out_dir / "qc_review_sample.md").write_text("\n".join(review))

    print("\n".join(lines))
    print(f"wrote {out_dir / 'qc_report.md'} and {out_dir / 'qc_review_sample.md'}")
```

- [ ] **Step 2: Run it**

```bash
cd code/difficult_advice && ../../.venv/bin/python scan_refusal_style.py \
  ../../data/difficult-advice/claude-sonnet-5-refusal/ft_dataset.jsonl
```
Expected: counts print; both files written. Interpret against the spec: `markdown` should be ~0 (haiku45 hit 20% — that level means prompt failure); `leak:*` hits need human reads (safe-part "because" is fine, refusal-attached "because" is the failure); `no-refusal-marker` rows may legitimately be all-safe scenarios — read them.

- [ ] **Step 3: Summarize for review.** In the task report, give: the count block, your read of up to 10 flagged rows (quote the offending sentence, verdict: real leak / false positive), and whether any *refusal-attached* justification exists. If real leaks are systematic (>5% of rows), STOP: the fix loops back to Task 1 wording + Task 5 re-run, which needs Jack's sign-off on the revised prompt text first. Jack reads `qc_review_sample.md` before any training launch regardless (it sits in the dataset dir).

- [ ] **Step 4: Commit the scanner**

```bash
git add code/difficult_advice/scan_refusal_style.py
git commit -m "feat: refusal-style QC scanner (detector, not filter)"
```

---

### Task 8: Experiment note with documented (unlaunched) next steps

**Files:**
- Create: `notes/Project/Experiments/DifficultAdvice/RefusalControl.md`

**Interfaces:**
- Consumes: results/paths from Tasks 5–7 (fill in actual counts, spend, QC summary).

- [ ] **Step 1: Write the note.** Follow the house style of `DifficultAdviceTeacherGridV3.md` (front matter `status: active`, terse sections, exact paths/ids). Content — adapt the bracketed fields to actuals, keep everything else:

```markdown
---
status: active
---

# Refusal-control dataset (2026-08-10)

Control for the DA transfer results: same 394 scenarios as the Sonnet
scale-08 rung (165 train + shared 229 val), assistant turns regenerated by
Sonnet 5 under a categorical zero-justification refusal policy
(`prompts/difficult_advice/refusal/`, stages 7-9 only; spec:
`docs/superpowers/specs/2026-08-10-refusal-control-design.md`). If a student
trained on this matches the reasoned arms, the "why" in the training text is
not load-bearing; if it lands near base, the reasoning is doing the work.

## Dataset

- `data/difficult-advice/claude-sonnet-5-refusal/` — seeded by
  `code/difficult_advice/subset_scale08_prompts.py seed` (1:1 hard-fail match
  against the committed rung files), regenerated with
  `sample_prompts.py --responses-only`, PIPELINE_MODEL=claude-sonnet-5,
  thinking ON (pipeline default), [DATE], ~$[ACTUAL].
- Train/val: `refusal-scale-08.jsonl` (165) / `refusal-val.jsonl` (229) —
  (system, user) byte-identical to `s5think-scale-08.jsonl` /
  `s5think-full-qwen-nothink-val.jsonl`; only assistant turns differ
  (verified by the `split` matcher + explicit byte check).
- QC: `qc_report.md` ([N] flagged rows: [summary]); `qc_review_sample.md`
  (20 transcripts) — **read before launching training.**

## Staged commands — DO NOT RUN until the passivity-correction branch lands

Training (mirrors the scaling-ladder config; dry-runs without `--yes`):

    cd code/train_eval_pipeline && ../../.venv/bin/python launch_instruct_ft.py \
      --train ../../data/difficult-advice/claude-sonnet-5-refusal/refusal-scale-08.jsonl \
      --val ../../data/difficult-advice/claude-sonnet-5-refusal/refusal-val.jsonl \
      --model Qwen/Qwen3-14B --suffix da-refusal-scale08 \
      --epochs 4 --n-checkpoints 4 --lr 1e-4 --lora-rank 64

    # epoch selection post-hoc from the 4 checkpoints (terra epoch curve:
    # val-best likely ep2). ~$4.

Eval (standard 180-sample MSM slice, student thinking OFF; serve the adapter
on RunPod vLLM and use the openai-api/vllm/ provider form — never plain
openai/, which drops extra_body):

    per code/msm_eval/README.md, same invocation as the teacher-grid v3 arms;
    grader pinned to openrouter/anthropic/claude-sonnet-4.6; then
    action_stats.py on the transcripts.

## Pre-registered reading (from the spec, fixed before any result exists)

- Primary: vs scale-08 = 15.6% (identical scenarios; assistant turns are the
  only difference). Secondary anchors: base 31.7%, opus48 12.8%, terra 2.2%
  (loose — teacher and prompt set both differ; deliberate omission).
- Refusal ≈ scale-08: outcome-only data transfers as well as reasoned data at
  this scale. Refusal ≈ base: the reasoning content is doing the work.
  Intermediate: partial transfer.
- A low rate only counts if the action rate stays in the comparators'
  98–100% band; low-and-passive is passivity transfer, a distinct finding —
  reconcile with the passivity-correction branch before launching.
```

- [ ] **Step 2: Verify internal references** — every path named in the note exists (`ls` each); the spending figure matches Task 5's commit; QC numbers match Task 7's report.

- [ ] **Step 3: Commit**

```bash
git add notes/Project/Experiments/DifficultAdvice/RefusalControl.md
git commit -m "docs: refusal-control experiment note — dataset done, launches gated"
```

---

## Self-review (done at plan-writing time)

- **Spec coverage:** prompt set → Task 1; subsetting script + seed → Tasks 2–3; generation → Task 5 (resumability → Task 4, serving the spec's "regenerate failures until 394" rule); QC incl. byte-identity and reasoning-leak scan → Tasks 6–7; ft/adapted jsonls → Task 6; documented unlaunched commands + note stub + pre-registered reading → Task 8. Spec's "~$3–6, log actuals" → Task 5 step 4. No spec item unassigned.
- **Placeholder scan:** all code/prompt blocks are full text; the only bracketed fields are Task 8's `[DATE]/[ACTUAL]/[N]`, which are executor-filled actuals by instruction, not deferred design.
- **Type consistency:** `prompt_key`/`match_one_to_one`/`assemble_seed`/`build_manifest`/`RUNGS`/`OUT`/`_read_jsonl` names match between Task 3's module, Task 6's usage, and both test files; `regen_response`/`RESPONSE_KEYS`/`CHECKPOINT_SAMPLES` match between Task 4's implementation and tests. `build_record(sample, fallback_initial=False, min_user_chars=150, tally=None)` matches the signature read from `build_ft_dataset.py`.
