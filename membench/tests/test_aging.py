"""Fixture-based unit tests for the memory-aging protocol (no live gnosis)."""

import json

from membench import aging

# ---------------------------------------------------------------------------
# Dataset generator
# ---------------------------------------------------------------------------


def test_generate_dataset_is_deterministic():
    a = aging.generate_dataset(seed=7, n_users=4)
    b = aging.generate_dataset(seed=7, n_users=4)
    assert aging.dataset_to_json(a) == aging.dataset_to_json(b)
    # different seed -> different statements (change cues are seeded)
    c = aging.generate_dataset(seed=99, n_users=4)
    assert aging.dataset_to_json(a) != aging.dataset_to_json(c)


def test_generate_dataset_has_all_slot_kinds_and_counts():
    ds = aging.generate_dataset(seed=7, n_users=8, update_versions=3)
    counts = ds.counts()
    # per user: 2 update, 1 contradiction, 2 stable, 1 distractor = 6 slots
    assert counts["users"] == 8
    assert counts["slots"] == 8 * 6
    assert counts["update_slots"] == 8 * 2
    assert counts["contradiction_slots"] == 8 * 1
    assert counts["stable_slots"] == 8 * 2
    assert counts["distractor_slots"] == 8 * 1


def test_update_chains_have_three_plus_versions_all_distinct():
    ds = aging.generate_dataset(seed=7, n_users=6, update_versions=4)
    for slot in ds.slots:
        if slot.kind == aging.UPDATE:
            assert len(slot.versions) == 4
            values = [v.value for v in slot.versions]
            assert len(set(values)) == len(values)  # no repeats in a chain
            # current is the newest; stale set excludes it
            assert slot.current_value == values[-1]
            assert slot.stale_values == tuple(values[:-1])


def test_contradiction_pairs_have_two_versions_no_change_cue():
    ds = aging.generate_dataset(seed=7, n_users=4)
    pairs = [s for s in ds.slots if s.kind == aging.CONTRADICTION]
    assert pairs
    for slot in pairs:
        assert len(slot.versions) == 2
        assert slot.versions[0].value != slot.versions[1].value
        # flat assertions, no "I changed / now" recency cue
        for v in slot.versions:
            assert "now" not in v.statement.lower()
            assert "changed" not in v.statement.lower()


def test_stable_and_distractor_are_single_version():
    ds = aging.generate_dataset(seed=7, n_users=4)
    for slot in ds.slots:
        if slot.kind in (aging.STABLE, aging.DISTRACTOR):
            assert len(slot.versions) == 1
            assert slot.stale_values == ()


def test_distractor_value_never_collides_with_its_users_color_chain():
    # The false-supersession guard only works if the distractor's value is
    # distinct from the same user's favorite-color values.
    ds = aging.generate_dataset(seed=7, n_users=8)
    for user in ds.users:
        color_chain = next(s for s in user.slots if s.slot_id.endswith(":favorite_color"))
        distractor = next(s for s in user.slots if s.kind == aging.DISTRACTOR)
        chain_values = {v.lower() for v in (color_chain.current_value, *color_chain.stale_values)}
        assert distractor.current_value.lower() not in chain_values


def test_reducing_versions_below_three_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        aging.generate_dataset(update_versions=2)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_build_timeline_is_time_ordered_and_covers_every_version():
    ds = aging.generate_dataset(seed=7, n_users=5)
    events = aging.build_timeline(ds)
    assert len(events) == ds.counts()["fact_versions"]
    dates = [e.event_date for e in events]
    assert dates == sorted(dates)
    # every event_key is unique (resumable identity)
    keys = [e.event_key for e in events]
    assert len(set(keys)) == len(keys)


# ---------------------------------------------------------------------------
# Scoring on hand-built returned-memory fixtures
# ---------------------------------------------------------------------------


def _mem(rank, content, date="2024/01/01 (Mon) 09:00"):
    return {"rank": rank, "content": content, "session_date": date}


def test_current_above_stale_scores_superseded():
    record = {
        "kind": aging.UPDATE,
        "current_value": "purple",
        "stale_values": ["blue", "green"],
        "retrieved": [
            _mem(0, "My favorite color is now purple."),
            _mem(1, "My favorite color is green."),
            _mem(2, "My favorite color is blue."),
        ],
    }
    scored = aging.score_probe(record)
    assert scored["superseded"] is True
    assert scored["stale"] is False
    assert scored["current_rank"] == 0
    assert scored["stale_rank"] == 1


def test_stale_ranked_above_current_scores_stale():
    record = {
        "kind": aging.UPDATE,
        "current_value": "purple",
        "stale_values": ["blue"],
        "retrieved": [
            _mem(0, "My favorite color is blue."),  # stale outranks current
            _mem(1, "My favorite color is now purple."),
        ],
    }
    scored = aging.score_probe(record)
    assert scored["stale"] is True
    assert scored["superseded"] is False


def test_only_stale_present_scores_stale_not_superseded():
    record = {
        "kind": aging.CONTRADICTION,
        "current_value": "Beta-Corp",
        "stale_values": ["Acme-Corp"],
        "retrieved": [_mem(0, "I work at Acme-Corp.")],
    }
    scored = aging.score_probe(record)
    assert scored["stale"] is True
    assert scored["superseded"] is False
    assert scored["current_present"] is False


def test_neither_value_present_is_retrieval_miss():
    record = {
        "kind": aging.UPDATE,
        "current_value": "purple",
        "stale_values": ["blue"],
        "retrieved": [_mem(0, "I like pasta.")],
    }
    scored = aging.score_probe(record)
    assert scored["superseded"] is False
    assert scored["stale"] is False
    assert not scored["current_present"] and not scored["stale_present"]


def test_stable_control_retained_when_present():
    present = aging.score_probe(
        {
            "kind": aging.STABLE,
            "current_value": "Cleveland",
            "stale_values": [],
            "retrieved": [_mem(0, "I was born in Cleveland.")],
        }
    )
    assert present["retained"] is True
    absent = aging.score_probe(
        {"kind": aging.STABLE, "current_value": "Cleveland", "stale_values": [], "retrieved": []}
    )
    assert absent["retained"] is False


def test_independent_distractor_present_is_not_false_supersession():
    # The user's own color chain was superseded, but the partner-color fact
    # must survive: present distractor -> not dropped.
    scored = aging.score_probe(
        {
            "kind": aging.DISTRACTOR,
            "current_value": "teal",
            "stale_values": [],
            "retrieved": [_mem(0, "My partner's favorite color is teal.")],
        }
    )
    assert scored["dropped"] is False
    # and it is never counted as a superseding probe
    assert scored["superseded"] is None


def test_distractor_dropped_is_false_supersession():
    scored = aging.score_probe(
        {"kind": aging.DISTRACTOR, "current_value": "teal", "stale_values": [], "retrieved": []}
    )
    assert scored["dropped"] is True


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_aggregate_aging_computes_all_headline_metrics():
    scored = [
        aging.score_probe(
            {
                "kind": aging.UPDATE,
                "current_value": "purple",
                "stale_values": ["blue"],
                "retrieved": [_mem(0, "now purple"), _mem(1, "blue")],
            }
        ),  # superseded
        aging.score_probe(
            {
                "kind": aging.UPDATE,
                "current_value": "green",
                "stale_values": ["blue"],
                "retrieved": [_mem(0, "blue"), _mem(1, "green")],
            }
        ),  # stale
        aging.score_probe(
            {
                "kind": aging.CONTRADICTION,
                "current_value": "Beta-Corp",
                "stale_values": ["Acme-Corp"],
                "retrieved": [_mem(0, "I work at Beta-Corp.")],
            }
        ),  # superseded
        aging.score_probe(
            {
                "kind": aging.STABLE,
                "current_value": "Cleveland",
                "stale_values": [],
                "retrieved": [_mem(0, "born in Cleveland")],
            }
        ),  # retained
        aging.score_probe(
            {"kind": aging.STABLE, "current_value": "Tucson", "stale_values": [], "retrieved": []}
        ),  # not retained
        aging.score_probe(
            {
                "kind": aging.DISTRACTOR,
                "current_value": "teal",
                "stale_values": [],
                "retrieved": [_mem(0, "partner teal")],
            }
        ),  # survives
    ]
    growth = {"fact_versions_ingested": 10, "unique_current_facts": 5, "ratio": 2.0}
    metrics = aging.aggregate_aging(scored, growth)
    assert metrics["supersession_accuracy"] == 0.6667  # 2 / 3
    assert metrics["stale_answer_rate"] == 0.3333  # 1 / 3
    assert metrics["retention"] == 0.5  # 1 / 2 stable
    assert metrics["false_supersession_rate"] == 0.0  # distractor survived
    assert metrics["store_growth_ratio"] == 2.0
    assert metrics["counts"]["superseding_probes"] == 3


def test_store_growth_matches_dataset_counts():
    ds = aging.generate_dataset(seed=7, n_users=4)
    growth = aging.store_growth(ds)
    counts = ds.counts()
    assert growth["fact_versions_ingested"] == counts["fact_versions"]
    assert growth["unique_current_facts"] == counts["slots"]
    assert growth["ratio"] > 1.0  # update/contradiction chains grow the store


# ---------------------------------------------------------------------------
# Resumable JSONL round-trip
# ---------------------------------------------------------------------------


def test_jsonl_round_trips(tmp_path):
    path = tmp_path / "probes.jsonl"
    records = [
        {"probe_id": "u00:favorite_color", "kind": "update", "superseded": True},
        {"probe_id": "u00:employer", "kind": "contradiction", "superseded": False},
    ]
    aging.write_jsonl(path, records)
    assert aging.read_jsonl(path) == records
    # append a line manually and confirm read picks it up (resume shape)
    with path.open("a") as f:
        f.write(json.dumps({"probe_id": "u00:birthplace", "kind": "stable"}) + "\n")
    assert len(aging.read_jsonl(path)) == 3


def test_report_renders_on_off_columns():
    results_by_label = {
        "supersession_on": {
            "supersession_accuracy": 0.95,
            "stale_answer_rate": 0.02,
            "retrieval_miss_rate": 0.01,
            "retention": 1.0,
            "false_supersession_rate": 0.0,
            "store_growth_ratio": 2.0,
        },
        "supersession_off": {
            "supersession_accuracy": 0.40,
            "stale_answer_rate": 0.55,
            "retrieval_miss_rate": 0.05,
            "retention": 1.0,
            "false_supersession_rate": 0.0,
            "store_growth_ratio": 2.0,
        },
    }
    run_info = {"seed": 7, "users": 8, "slots": 48, "fact_versions": 96, "max_items": 20}
    text = aging.render_aging_report(results_by_label, run_info)
    assert "supersession_on" in text and "supersession_off" in text
    assert "95.0%" in text and "55.0%" in text
    assert "GNOSIS_READ_SUPERSESSION_ENABLED" in text
