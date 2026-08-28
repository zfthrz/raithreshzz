from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

import run_h3_pipeline as pipeline
from select_session_persistent_patterns import select_session_patterns
from session_history import initialize_schema
from validate_history_db import validate_pattern_layer


TRACK = "Autodromo Enzo e Dino Ferrari"
LAYOUT = "Autodromo Enzo e Dino Ferrari"
VARIANT = "HYPER"
AUTHORIZED_VERSION = "0.1"
BASELINE_VERSION = "0.1"
PROMOTION_VERSION = "0.1"


def _pair(a: int, b: int, episode_a: int, episode_b: int) -> dict:
    start_a = {10: 100.0, 20: 101.0, 30: 102.0}[episode_a]
    start_b = {10: 100.0, 20: 101.0, 30: 102.0}[episode_b]
    return {
        "track": TRACK,
        "track_layout": LAYOUT,
        "vehicle_variant": VARIANT,
        "vehicle_family": "HYPERCAR",
        "session_a": a,
        "session_b": b,
        "episode_pk_a": episode_a,
        "episode_pk_b": episode_b,
        "episode_id_a": 1,
        "episode_id_b": 1,
        "start_distance_a_m": start_a,
        "end_distance_a_m": start_a + 40.0,
        "center_distance_a_m": start_a + 20.0,
        "start_distance_b_m": start_b,
        "end_distance_b_m": start_b + 40.0,
        "center_distance_b_m": start_b + 20.0,
        "channels_a": ["brake"],
        "channels_b": ["brake"],
    }


def _authority(scope: str) -> dict:
    return {
        "authorized_matcher_version": AUTHORIZED_VERSION,
        "calibration_scope": scope,
        "production_match_authorized": True,
        "production_reject_authorized": scope == "EXACT_VARIANT_CALIBRATION",
        "track_baseline_policy_version": BASELINE_VERSION,
        "match_promotion_policy_version": PROMOTION_VERSION,
        "baseline_source_variants": ["LMP2_ELMS"],
        "promotion_batch_id": "promotion",
        "promotion_status": "PROMOTED_MATCH_ONLY",
        "promotion_confirmed_matches": 26,
    }


def _classifier(scope: str):
    def classify(features, batches_root):
        decisions = []
        for index, feature in enumerate(features):
            decisions.append({
                "pair_index": index,
                "pair_id": f"pair-{index}",
                "session_a": feature["session_a"],
                "session_b": feature["session_b"],
                "episode_pk_a": feature["episode_pk_a"],
                "episode_pk_b": feature["episode_pk_b"],
                "decision": "MATCH",
                "automatic": True,
                "rule_id": "CORE_SPATIAL_MATCH",
                "authority": _authority(scope),
            })
        return decisions, {
            "matcher_version": "0.3",
            "matcher_status": "CALIBRATED_PROVISIONAL",
            "authorized_matcher_version": AUTHORIZED_VERSION,
            "track_baseline_policy_version": BASELINE_VERSION,
            "match_promotion_policy_version": PROMOTION_VERSION,
            "decision_counts": {
                "MATCH": len(decisions),
                "AMBIGUOUS": 0,
                "REJECT": 0,
            },
            "authority_scope_counts": {scope: len(decisions)},
            "production_contract": {
                "exact_variant": "MATCH_AND_REJECT_AS_CALIBRATED",
                "promoted_track_baseline": "MATCH_ONLY",
                "inherited_reject": "NEVER_AUTHORIZED",
            },
        }
    return classify


def _history(tmp_path: Path, contexts: dict[int, tuple[str, str, str]]):
    path = tmp_path / "history.duckdb"
    connection = duckdb.connect(str(path))
    initialize_schema(connection)
    episode_by_session = {1: 10, 2: 20, 3: 30}
    for session_id, (track, layout, variant) in contexts.items():
        connection.execute(
            """
            INSERT INTO sessions (
                session_id, source_json_path, source_json_sha256,
                source_analysis_version, track, lmu_track_layout,
                vehicle_variant, same_vehicle, reference_lap, imported_at_utc
            ) VALUES (?, ?, ?, 'test', ?, ?, ?, true, 7, 'now')
            """,
            [
                session_id,
                f"session-{session_id}.json",
                f"hash-{session_id}",
                track,
                layout,
                variant,
            ],
        )
        connection.execute(
            """
            INSERT INTO episodes (
                episode_pk, comparison_id, session_id, episode_id,
                start_distance_m, end_distance_m, center_distance_m
            ) VALUES (?, ?, ?, 1, 100.0, 140.0, 120.0)
            """,
            [episode_by_session[session_id], session_id, session_id],
        )
    connection.close()
    return path


def _run(
    tmp_path: Path,
    monkeypatch,
    features: list[dict],
    *,
    history: Path,
    scope: str,
):
    source = tmp_path / "episode_pair_features.json"
    source.write_text(json.dumps(features), encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "classify_features_authorized",
        _classifier(scope),
    )
    return pipeline.run_h3_pipeline(
        source,
        batches_root=tmp_path / "batches",
        history_db=history,
    )


def test_cross_session_repeat_imports_as_observational_evidence_and_is_idempotent(
    tmp_path: Path,
    monkeypatch,
):
    history = _history(tmp_path, {
        1: (TRACK, LAYOUT, VARIANT),
        2: (TRACK, LAYOUT, VARIANT),
    })
    features = [_pair(1, 2, 10, 20)]

    first, first_code = _run(
        tmp_path,
        monkeypatch,
        features,
        history=history,
        scope="COVERED_BY_TRACK_MATCH_BASELINE",
    )
    second, second_code = _run(
        tmp_path,
        monkeypatch,
        features,
        history=history,
        scope="COVERED_BY_TRACK_MATCH_BASELINE",
    )

    assert (first_code, first["history_import"]["status"]) == (0, "RUN")
    assert (second_code, second["history_import"]["status"]) == (0, "REUSED")
    connection = duckdb.connect(str(history))
    assert connection.execute("SELECT COUNT(*) FROM pattern_runs").fetchone()[0] == 1
    assert connection.execute(
        "SELECT state FROM persistent_patterns"
    ).fetchone()[0] == "cross_session_repeat"
    metadata = json.loads(connection.execute(
        "SELECT metadata_json FROM pattern_runs"
    ).fetchone()[0])
    assert metadata["h2_authority_gate"]["authority_scope_counts"] == {
        "COVERED_BY_TRACK_MATCH_BASELINE": 1
    }
    assert metadata["h2_authority_gate"]["inherited_reject_count"] == 0
    assert metadata["source_features_sha256"]
    assert connection.execute(
        "SELECT reference_lap FROM sessions WHERE session_id = 1"
    ).fetchone()[0] == 7
    selection = select_session_patterns(connection, 1)
    assert selection["metadata"]["observational_only"] is True
    assert selection["metadata"]["affects_next_stint_plan"] is False
    assert selection["metadata"]["historical_actions_authorized"] is False
    connection.close()


def test_three_session_exact_calibration_imports_persistent_pattern(
    tmp_path: Path,
    monkeypatch,
):
    history = _history(tmp_path, {
        1: (TRACK, LAYOUT, VARIANT),
        2: (TRACK, LAYOUT, VARIANT),
        3: (TRACK, LAYOUT, VARIANT),
    })
    features = [
        _pair(1, 2, 10, 20),
        _pair(1, 3, 10, 30),
        _pair(2, 3, 20, 30),
    ]

    report, code = _run(
        tmp_path,
        monkeypatch,
        features,
        history=history,
        scope="EXACT_VARIANT_CALIBRATION",
    )

    assert code == 0
    assert report["history_import"]["status"] == "RUN"
    connection = duckdb.connect(str(history))
    assert connection.execute(
        "SELECT state, independent_session_count FROM persistent_patterns"
    ).fetchone() == ("persistent_pattern", 3)
    connection.close()


def test_conflict_review_required_never_imports(
    tmp_path: Path,
    monkeypatch,
):
    history = _history(tmp_path, {
        1: (TRACK, LAYOUT, VARIANT),
        2: (TRACK, LAYOUT, VARIANT),
        3: (TRACK, LAYOUT, VARIANT),
    })
    # The 1↔3 pair is absent, so transitive membership remains review-required.
    features = [_pair(1, 2, 10, 20), _pair(2, 3, 20, 30)]

    report, code = _run(
        tmp_path,
        monkeypatch,
        features,
        history=history,
        scope="EXACT_VARIANT_CALIBRATION",
    )

    assert code == 2
    assert report["result"] == "REVIEW_REQUIRED"
    assert report["history_import"]["status"] == "SKIPPED_NOT_APPLICABLE"
    connection = duckdb.connect(str(history))
    assert connection.execute("SELECT COUNT(*) FROM pattern_runs").fetchone()[0] == 0
    connection.close()


@pytest.mark.parametrize(
    "bad_context",
    [
        (TRACK, "Different Layout", VARIANT),
        (TRACK, LAYOUT, "LMP2_WEC"),
    ],
)
def test_history_import_fails_closed_on_layout_or_variant_mismatch(
    tmp_path: Path,
    monkeypatch,
    bad_context,
):
    history = _history(tmp_path, {
        1: (TRACK, LAYOUT, VARIANT),
        2: bad_context,
    })

    report, code = _run(
        tmp_path,
        monkeypatch,
        [_pair(1, 2, 10, 20)],
        history=history,
        scope="COVERED_BY_TRACK_MATCH_BASELINE",
    )

    assert code == 1
    assert report["result"] == "FAILED"
    assert report["history_import"]["status"] == "FAILED"
    connection = duckdb.connect(str(history))
    assert connection.execute("SELECT COUNT(*) FROM pattern_runs").fetchone()[0] == 0
    connection.close()


def test_history_validator_rejects_corrupted_official_authority_provenance(
    tmp_path: Path,
    monkeypatch,
):
    history = _history(tmp_path, {
        1: (TRACK, LAYOUT, VARIANT),
        2: (TRACK, LAYOUT, VARIANT),
    })
    report, code = _run(
        tmp_path,
        monkeypatch,
        [_pair(1, 2, 10, 20)],
        history=history,
        scope="COVERED_BY_TRACK_MATCH_BASELINE",
    )
    assert code == 0
    assert report["history_import"]["status"] == "RUN"

    connection = duckdb.connect(str(history))
    metadata = json.loads(connection.execute(
        "SELECT metadata_json FROM pattern_runs"
    ).fetchone()[0])
    metadata["h2_authority_gate"]["inherited_reject_count"] = 1
    connection.execute(
        "UPDATE pattern_runs SET metadata_json = ?",
        [json.dumps(metadata)],
    )
    errors: list[str] = []
    validate_pattern_layer(connection, errors, [])
    assert any("inherited REJECT persistido" in error for error in errors)
    connection.close()
