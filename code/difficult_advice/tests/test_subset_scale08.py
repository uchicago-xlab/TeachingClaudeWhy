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
