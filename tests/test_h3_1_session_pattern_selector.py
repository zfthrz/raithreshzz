from __future__ import annotations

import json
from pathlib import Path

import duckdb

from runtime_paths import persistent_pattern_selection_output_path
from select_session_persistent_patterns import select_session_patterns
from session_history import initialize_schema


CONTEXT = (
    "Autodromo Enzo e Dino Ferrari",
    "Autodromo Enzo e Dino Ferrari",
    "LMP2_ELMS",
)


def _connection(tmp_path: Path):
    connection = duckdb.connect(str(tmp_path / "history.duckdb"))
    initialize_schema(connection)
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, source_json_path, source_json_sha256,
            source_analysis_version, track, vehicle_variant,
            lmu_track_layout, same_vehicle, imported_at_utc
        ) VALUES (10, 'analysis.json', 'session-hash', 'test', ?, ?, ?, true, 'now')
        """,
        [CONTEXT[0], CONTEXT[2], CONTEXT[1]],
    )
    return connection


def _insert_run(connection, run_id: int):
    connection.execute(
        """
        INSERT INTO pattern_runs (
            pattern_run_id, source_patterns_path, source_patterns_sha256,
            source_matches_path, source_matches_sha256, source_bundle_sha256,
            h3_version, matcher_version, persistent_min_independent_sessions,
            track, track_layout, vehicle_variant,
            pattern_count, episode_count, single_observation_count,
            cross_session_repeat_count, persistent_pattern_count,
            conflict_review_required_count, match_edge_count,
            transitively_resolved_ambiguous_pair_count, imported_at_utc,
            metadata_json
        ) VALUES (?, 'patterns.json', ?, 'matches.json', ?, ?, '0.1', '0.3', 3,
                  ?, ?, ?, 1, 3, 0, 0, 1, 0, 2, 0, 'now', '{}')
        """,
        [run_id, f"p{run_id}", f"m{run_id}", f"bundle{run_id}", *CONTEXT],
    )


def _insert_pattern_member(connection, run_id: int, *, session_id: int = 10):
    connection.execute(
        """
        INSERT INTO persistent_patterns (
            pattern_pk, pattern_run_id, pattern_id, state,
            track, track_layout, vehicle_variant,
            observation_count, independent_session_count,
            representative_session_id, representative_episode_pk,
            direct_match_edge_count, internal_ambiguous_pair_count,
            internal_reject_pair_count, possible_cross_session_pair_count,
            observed_internal_cross_session_pair_count,
            missing_internal_cross_session_pair_count,
            transitively_resolved_ambiguous_pair_count,
            common_action_channels_json, union_action_channels_json,
            session_ids_json, raw_pattern_json
        ) VALUES (?, ?, ?, 'persistent_pattern', ?, ?, ?, 3, 3, ?, ?,
                  2, 0, 0, 3, 2, 1, 0, '["brake"]', '["brake"]',
                  '[8,9,10]', '{}')
        """,
        [run_id, run_id, f"pat_{run_id}", *CONTEXT, session_id, 500 + run_id],
    )
    connection.execute(
        """
        INSERT INTO persistent_pattern_members (
            pattern_member_pk, pattern_pk, pattern_run_id, pattern_id,
            session_id, episode_pk, episode_id, channels_json
        ) VALUES (?, ?, ?, ?, ?, ?, 4, '["brake"]')
        """,
        [run_id, run_id, run_id, f"pat_{run_id}", session_id, 500 + run_id],
    )


def test_selects_exact_membership_from_latest_compatible_run(tmp_path: Path):
    connection = _connection(tmp_path)
    _insert_run(connection, 1)
    _insert_pattern_member(connection, 1)
    _insert_run(connection, 2)
    _insert_pattern_member(connection, 2)

    document = select_session_patterns(connection, 10)

    assert document["metadata"]["status"] == "MATCHED_PATTERN_MEMBERSHIP"
    assert document["metadata"]["observational_only"] is True
    assert document["metadata"]["affects_next_stint_plan"] is False
    assert document["metadata"]["historical_actions_authorized"] is False
    assert document["provenance"]["pattern_run_id"] == 2
    assert [item["pattern_id"] for item in document["matched_patterns"]] == ["pat_2"]
    assert document["matched_patterns"][0]["match_basis"] == "exact_pattern_member_identity"
    connection.close()


def test_latest_snapshot_without_membership_uses_only_calibrated_match(
    tmp_path: Path,
    monkeypatch,
):
    connection = _connection(tmp_path)
    _insert_run(connection, 1)
    _insert_pattern_member(connection, 1)
    _insert_run(connection, 2)
    _insert_pattern_member(connection, 2, session_id=20)

    representative = {"episode_pk": 502, "session_id": 20}
    current = {"episode_pk": 900, "session_id": 10, "episode_id": 7}
    import episode_pair_features
    import episode_pair_matcher

    monkeypatch.setattr(
        episode_pair_features,
        "load_episodes",
        lambda *args, **kwargs: [representative, current],
    )
    monkeypatch.setattr(episode_pair_features, "load_episode_channels", lambda *_: {})
    monkeypatch.setattr(episode_pair_features, "load_channel_metrics", lambda *_: {})
    monkeypatch.setattr(
        episode_pair_features,
        "build_pair_record",
        lambda *args, **kwargs: {"track": CONTEXT[0]},
    )
    monkeypatch.setattr(
        episode_pair_matcher,
        "classify_pair",
        lambda pair: {
            "decision": "MATCH",
            "automatic": True,
            "rule_id": "CORE_SPATIAL_MATCH",
            "reasons": ["calibrated"],
        },
    )

    document = select_session_patterns(connection, 10)

    assert document["metadata"]["status"] == "MATCHED_CALIBRATED_PROJECTION"
    assert document["summary"]["matched_pattern_count"] == 0
    assert document["matched_patterns"] == []
    assert document["summary"]["projected_pattern_count"] == 1
    projected = document["projected_pattern_matches"][0]
    assert projected["pattern_id"] == "pat_2"
    assert projected["matcher_decision"]["automatic"] is True
    assert projected["match_basis"] == "calibrated_h2_match_to_pattern_representative"
    connection.close()


def test_ambiguous_projection_fails_closed(tmp_path: Path, monkeypatch):
    connection = _connection(tmp_path)
    _insert_run(connection, 1)
    _insert_pattern_member(connection, 1, session_id=20)
    import episode_pair_features
    import episode_pair_matcher

    monkeypatch.setattr(
        episode_pair_features,
        "load_episodes",
        lambda *args, **kwargs: [
            {"episode_pk": 501, "session_id": 20},
            {"episode_pk": 900, "session_id": 10},
        ],
    )
    monkeypatch.setattr(episode_pair_features, "load_episode_channels", lambda *_: {})
    monkeypatch.setattr(episode_pair_features, "load_channel_metrics", lambda *_: {})
    monkeypatch.setattr(episode_pair_features, "build_pair_record", lambda *a, **k: {})
    monkeypatch.setattr(
        episode_pair_matcher,
        "classify_pair",
        lambda pair: {"decision": "AMBIGUOUS", "automatic": False},
    )

    document = select_session_patterns(connection, 10)

    assert document["metadata"]["status"] == "NO_CALIBRATED_PATTERN_MATCH"
    assert document["projected_pattern_matches"] == []
    assert document["projection_diagnostics"]["ambiguous_count"] == 1
    connection.close()


def test_context_without_pattern_run_fails_closed(tmp_path: Path):
    connection = _connection(tmp_path)

    document = select_session_patterns(connection, 10)

    assert document["metadata"]["status"] == "NO_COMPATIBLE_PATTERN_RUN"
    assert document["provenance"] is None
    connection.close()


def test_h3_1_runtime_path_is_centralized(tmp_path, monkeypatch):
    monkeypatch.setenv("RACE_ENGINEER_GENERATED_DIR", str(tmp_path / "generated"))
    output = persistent_pattern_selection_output_path("telemetria/example.duckdb")
    assert output.parts[-4:] == (
        "generated",
        "h3_1",
        "example",
        "persistent_pattern_selection.json",
    )
