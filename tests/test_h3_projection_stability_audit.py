import json
from pathlib import Path

from audit_h3_projection_stability import audit_h3_projection_stability


CONTEXT = {
    "track": "Test Track",
    "track_layout": "Test Layout",
    "vehicle_variant": "GT3",
}


def _write_selection(
    root: Path,
    stem: str,
    session_id: int,
    *,
    projected: list[dict] | None = None,
    exact: list[dict] | None = None,
    context: dict | None = None,
) -> Path:
    path = root / "h3_1" / stem / "persistent_pattern_selection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "metadata": {
            "session_id": session_id,
            "context": context or CONTEXT,
            "observational_only": True,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
        },
        "provenance": {"source_bundle_sha256": "a" * 64},
        "matched_patterns": exact or [],
        "projected_pattern_matches": projected or [],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _projection(pattern_id: str, episode_pk: int, *, automatic: bool = True) -> dict:
    return {
        "pattern_id": pattern_id,
        "state": "persistent_pattern",
        "independent_session_count": 3,
        "match_basis": "calibrated_h2_match_to_pattern_representative",
        "current_session_episode": {"episode_pk": episode_pk},
        "matcher_decision": {
            "decision": "MATCH",
            "automatic": automatic,
            "rule_id": "CORE_SPATIAL_MATCH",
        },
    }


def test_groups_same_context_pattern_across_independent_sessions(tmp_path: Path):
    generated = tmp_path / "generated"
    first = _write_selection(
        generated, "a", 10, projected=[_projection("pat_1", 100)]
    )
    _write_selection(generated, "b", 11, projected=[_projection("pat_1", 110)])
    before = first.read_bytes()

    report = audit_h3_projection_stability(generated)

    assert first.read_bytes() == before
    assert report["metadata"]["matcher_called"] is False
    assert report["metadata"]["threshold_applied"] is False
    assert report["summary"]["projected_edge_count"] == 2
    assert report["summary"]["projected_pattern_count"] == 1
    assert report["summary"]["patterns_in_multiple_projected_sessions"] == 1
    assert report["patterns"][0]["projected_session_ids"] == [10, 11]


def test_reports_exact_runtime_membership_without_calling_it_confirmation(
    tmp_path: Path,
):
    generated = tmp_path / "generated"
    _write_selection(
        generated, "a", 10, projected=[_projection("pat_1", 100)]
    )
    _write_selection(
        generated,
        "b",
        12,
        exact=[{"pattern_id": "pat_1"}],
    )

    report = audit_h3_projection_stability(generated)

    row = report["patterns"][0]
    assert row["also_seen_as_exact_runtime_membership"] is True
    assert row["exact_runtime_membership_session_ids"] == [12]
    assert report["summary"][
        "patterns_also_seen_as_exact_runtime_membership"
    ] == 1


def test_invalid_nonautomatic_projection_fails_closed(tmp_path: Path):
    generated = tmp_path / "generated"
    _write_selection(
        generated,
        "a",
        10,
        projected=[_projection("pat_1", 100, automatic=False)],
    )

    report = audit_h3_projection_stability(generated)

    assert report["summary"]["projected_edge_count"] == 0
    assert report["review_signals"][
        "projection_contract_violation_count"
    ] == 1


def test_pattern_id_reused_across_contexts_is_reported_not_merged(tmp_path: Path):
    generated = tmp_path / "generated"
    _write_selection(
        generated, "a", 10, projected=[_projection("pat_1", 100)]
    )
    _write_selection(
        generated,
        "b",
        11,
        projected=[_projection("pat_1", 110)],
        context={
            "track": "Other Track",
            "track_layout": "Other Layout",
            "vehicle_variant": "GT3",
        },
    )

    report = audit_h3_projection_stability(generated)

    assert report["summary"]["projected_pattern_count"] == 2
    assert report["review_signals"][
        "cross_context_pattern_id_collision_count"
    ] == 1
    assert report["review_signals"]["cross_context_pattern_id_collisions"] == [
        "pat_1"
    ]
