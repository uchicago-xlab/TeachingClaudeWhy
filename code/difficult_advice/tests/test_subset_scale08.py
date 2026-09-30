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


def test_presets_keep_scale08_outputs_and_add_terra():
    from subset_scale08_prompts import DA, OUT, PRESETS

    scale08 = PRESETS["scale08"]
    assert scale08["out"] == OUT
    assert scale08["outputs"] == {"train": "refusal-scale-08.jsonl", "val": "refusal-val.jsonl"}
    assert [(r, n) for r, _, n in scale08["rungs"]] == [("train", 165), ("val", 229)]

    terra = PRESETS["terra"]
    assert terra["out"] == DA / "gpt-5.6-terra-refusal"
    assert [(r, p.name, n) for r, p, n in terra["rungs"]] == [
        ("train", "terra-ft-qwen-nothink.jsonl", 135),
        ("val", "terra-ft-qwen-nothink-val.jsonl", 15),
    ]
    assert all(p.parent == DA / "gpt-5.6-terra" for _, p, _ in terra["rungs"])
    assert terra["outputs"] == {
        "train": "terra-refusal-ft-qwen-nothink.jsonl",
        "val": "terra-refusal-ft-qwen-nothink-val.jsonl",
    }
