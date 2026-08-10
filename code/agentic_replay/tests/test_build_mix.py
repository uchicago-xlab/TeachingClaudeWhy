import build_mix

DA = [{"messages": [{"role": "user", "content": f"da {i}"},
                    {"role": "assistant", "content": "advice"}]} for i in range(165)]
REPLAY_OFF = [{"messages": [{"role": "user", "content": f"fc {i}"},
                            {"role": "assistant", "content": "{}"}],
               "meta": {"prompt_id": i}} for i in range(165)]
REPLAY_NAT = [{**r, "render": "native"} for r in REPLAY_OFF]


def test_assemble_mixoff_interleaves_all_rows_deterministically():
    rows = build_mix.assemble("mixoff", DA, REPLAY_OFF, seed=0)
    assert len(rows) == 330
    assert rows != DA + REPLAY_OFF                    # actually shuffled
    assert rows == build_mix.assemble("mixoff", DA, REPLAY_OFF, seed=0)
    assert all("render" not in r for r in rows)


def test_assemble_mixnat_keeps_native_tags_on_replay_rows_only():
    rows = build_mix.assemble("mixnat", DA, REPLAY_NAT, seed=0)
    tagged = [r for r in rows if r.get("render") == "native"]
    assert len(tagged) == 165
    assert all("meta" in r for r in tagged)           # tags sit on replay rows, not DA


def test_assemble_replayonly_is_replay_verbatim_order_shuffled():
    rows = build_mix.assemble("replayonly", [], REPLAY_OFF, seed=0)
    assert len(rows) == 165


def test_assemble_refuses_short_inputs():
    for arm, da, replay in (("mixoff", DA[:100], REPLAY_OFF),
                            ("mixoff", DA, REPLAY_OFF[:100])):
        try:
            build_mix.assemble(arm, da, replay, seed=0)
            assert False, "expected SystemExit"
        except SystemExit:
            pass


def test_assemble_refuses_native_rows_in_off_arms():
    try:
        build_mix.assemble("mixoff", DA, REPLAY_NAT, seed=0)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "native" in str(e)


def test_assemble_refuses_null_render_rows():
    # train_sft.render_row's row.get("render") returns None for both an absent
    # key and an explicit null, so a null-tagged row would train under the
    # standard view without a word of complaint -- in mixnat that silently
    # deletes the arm's entire treatment.
    replay = [{**r, "render": None} for r in REPLAY_NAT]
    for arm in ("mixoff", "mixnat"):
        try:
            build_mix.assemble(arm, DA, replay, seed=0)
            assert False, "expected SystemExit"
        except SystemExit as e:
            assert "None" in str(e)


def test_assemble_refuses_unknown_render_value():
    replay = [{**r, "render": "off"} for r in REPLAY_OFF]
    try:
        build_mix.assemble("mixoff", DA, replay, seed=0)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "off" in str(e)


def test_assemble_refuses_render_tagged_da_rows():
    da = [{**r, "render": None} for r in DA]
    try:
        build_mix.assemble("mixnat", da, REPLAY_NAT, seed=0)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "None" in str(e)
