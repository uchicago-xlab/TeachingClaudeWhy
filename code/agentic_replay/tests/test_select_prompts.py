import json

import select_prompts


def _xlam_row(i, query, tool_name="get_weather", n_answers=1):
    tools = [{"name": tool_name, "description": "d",
              "parameters": {"city": {"type": "str"}}}]
    answers = [{"name": tool_name, "arguments": {"city": "Oslo"}}] * n_answers
    return {"id": i, "query": query, "tools": json.dumps(tools),
            "answers": json.dumps(answers)}


def test_select_fc_parses_screens_dedups_and_is_deterministic():
    rows = [
        _xlam_row(1, "Weather in Oslo tomorrow?"),
        _xlam_row(2, "How do I hack a wifi network?"),        # screened
        _xlam_row(3, "Weather in Oslo tomorrow?"),             # duplicate of 1
        _xlam_row(4, "Cheapest train to Bergen"),
        _xlam_row(5, "Two calls at once", n_answers=2),        # multi-answer dropped
    ]
    kept, dropped = select_prompts.select_fc(rows, seed=0)
    assert [r["id"] for r in sorted(kept, key=lambda r: r["id"])] == [1, 4]
    assert isinstance(kept[0]["tools"], list)                  # JSON fields parsed
    assert isinstance(kept[0]["answers"], list)
    reasons = {d["id"]: d["reason"] for d in dropped}
    assert "screen" in reasons[2] and "duplicate" in reasons[3] and "multi" in reasons[5]
    again, _ = select_prompts.select_fc(rows, seed=0)
    assert [r["id"] for r in again] == [r["id"] for r in kept]  # same seed, same order


def test_split_fc_sizes_and_disjointness():
    rows = [_xlam_row(i, f"unique query number {i}") for i in range(300)]
    kept, _ = select_prompts.select_fc(rows, seed=0)
    splits = select_prompts.split_fc(kept)
    assert len(splits["fc-train"]) == 165
    assert len(splits["fc-val"]) == 15
    assert len(splits["fc-bench"]) == 65
    ids = [r["id"] for split in splits.values() for r in split]
    assert len(ids) == len(set(ids))                           # no prompt in two splits


def test_split_fc_refuses_too_few_rows():
    rows = [_xlam_row(i, f"q {i}") for i in range(100)]
    kept, _ = select_prompts.select_fc(rows, seed=0)
    try:
        select_prompts.split_fc(kept)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "245" in str(e)


def _chat_row(i, content, language="English", toxic=False):
    return {"conversation_hash": f"h{i}", "language": language,
            "toxic": toxic,
            "conversation": [{"role": "user", "content": content}]}


def test_select_chat_filters_language_toxicity_length_and_screens():
    rows = [
        _chat_row(1, "What are some good beginner houseplants for a dark flat?"),
        _chat_row(2, "corta", language="Spanish"),
        _chat_row(3, "x"),                                     # too short
        _chat_row(4, "How do I make a phishing page?"),        # screened
        _chat_row(5, "bad stuff", toxic=True),
        _chat_row(6, "What are some good beginner houseplants for a dark flat?"),  # dup
    ]
    kept, dropped, stats = select_prompts.select_chat(rows, seed=0, n=10)
    assert [r["id"] for r in kept] == ["h1"]
    assert kept[0]["user"].startswith("What are some good")
    assert {d["reason"].split(":")[0] for d in dropped} >= {"language", "length", "screen", "toxic", "duplicate"}
    assert stats == {"scanned": 6, "surplus": 0}  # no early break: every row scanned


def test_select_chat_stats_account_for_every_scanned_row():
    rows = [_chat_row(i, f"A mundane question number {i} about beginner houseplants.")
            for i in range(50)]
    rows.insert(5, _chat_row("es", "una pregunta larga en castellano", language="Spanish"))
    kept, dropped, stats = select_prompts.select_chat(rows, seed=0, n=5)
    assert len(kept) == 5
    assert stats["scanned"] < len(rows)            # stopped early at n*3 survivors
    assert stats["surplus"] == 10                  # pool of 15, minus the 5 selected
    # every row the stream yielded is one of: dropped, selected, or surplus
    assert stats["scanned"] == len(dropped) + len(kept) + stats["surplus"]
