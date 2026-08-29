import copy
import hashlib
import json
from pathlib import Path

import pytest

from audit_h3_projection_review import audit_projection_review


def _write_documents(tmp_path: Path, *, label: str = "SAME") -> tuple[Path, Path]:
    queue_path = tmp_path / "queue.json"
    queue = {
        "metadata": {
            "review_scope": "H3_2_PROJECTION_VALIDATION_ONLY",
            "selection_policy": "all_valid_projection_edges_no_threshold_no_sampling",
            "labels_authorize_matcher_calibration": False,
            "labels_authorize_h3_membership": False,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
        },
        "queue": [{
            "pair_id": "pair_1",
            "review_scope": "H3_2_PROJECTION_VALIDATION_ONLY",
            "features": {
                "track": "Spa",
                "session_a": 1,
                "session_b": 2,
                "episode_pk_a": 10,
                "episode_pk_b": 20,
                "center_distance_abs_diff_m": 12.0,
                "overlap_over_union": 0.5,
                "overlap_over_shorter": 1.0,
                "channel_jaccard": 0.75,
            },
            "h3_projection_evidence": [{
                "pattern_id": "pat_1",
                "pattern_state": "persistent_pattern",
                "current_session_id": 2,
                "matcher_decision": {
                    "decision": "MATCH",
                    "automatic": True,
                    "rule_id": "CORE_SPATIAL_MATCH",
                },
            }],
        }],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    queue_hash = hashlib.sha256(queue_path.read_bytes()).hexdigest()
    labels_path = tmp_path / "labels.json"
    labels = {
        "metadata": {
            "review_scope": "H3_2_PROJECTION_VALIDATION_ONLY",
            "source_queue_sha256": queue_hash,
            "labels_authorize_matcher_calibration": False,
            "labels_authorize_h3_membership": False,
            "affects_next_stint_plan": False,
            "historical_actions_authorized": False,
        },
        "labels": [{
            "pair_id": "pair_1",
            "human_label": label,
            "feature_snapshot": {
                "track": "Spa",
                "session_a": 1,
                "session_b": 2,
                "episode_pk_a": 10,
                "episode_pk_b": 20,
            },
        }],
    }
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    return queue_path, labels_path


def test_summarizes_labels_rules_patterns_and_raw_metrics(tmp_path: Path):
    queue_path, labels_path = _write_documents(tmp_path)

    report = audit_projection_review(queue_path, labels_path)

    assert report["metadata"]["status"] == "POSITIVE_ONLY_HUMAN_REVIEW_EVIDENCE"
    assert report["summary"]["human_labels_by_pair"]["counts"]["SAME"] == 1
    assert report["by_matcher_rule"]["CORE_SPATIAL_MATCH"]["counts"]["SAME"] == 1
    assert report["patterns"][0]["projected_session_ids"] == [2]
    assert report["metrics_by_human_label"]["SAME"][
        "center_distance_abs_diff_m"
    ] == {"count": 1, "min": 12.0, "median": 12.0, "max": 12.0}


def test_preserves_pair_and_edge_views_for_multiple_pattern_evidence(tmp_path: Path):
    queue_path, labels_path = _write_documents(tmp_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    second = copy.deepcopy(queue["queue"][0]["h3_projection_evidence"][0])
    second["pattern_id"] = "pat_2"
    second["matcher_decision"]["rule_id"] = "EXTENDED_SPATIAL_CHANNEL_MATCH"
    queue["queue"][0]["h3_projection_evidence"].append(second)
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    labels["metadata"]["source_queue_sha256"] = hashlib.sha256(
        queue_path.read_bytes()
    ).hexdigest()
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    report = audit_projection_review(queue_path, labels_path)

    assert report["summary"]["reviewed_pair_count"] == 1
    assert report["summary"]["projection_edge_count"] == 2
    assert report["summary"]["pattern_count"] == 2


def test_fails_closed_on_wrong_scope_or_authority(tmp_path: Path):
    queue_path, labels_path = _write_documents(tmp_path)
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    labels["metadata"]["labels_authorize_h3_membership"] = True
    labels_path.write_text(json.dumps(labels), encoding="utf-8")

    with pytest.raises(ValueError, match="debe ser false"):
        audit_projection_review(queue_path, labels_path)


def test_does_not_mutate_inputs(tmp_path: Path):
    queue_path, labels_path = _write_documents(tmp_path, label="AMBIGUOUS")
    before_queue = queue_path.read_bytes()
    before_labels = labels_path.read_bytes()

    report = audit_projection_review(queue_path, labels_path)

    assert queue_path.read_bytes() == before_queue
    assert labels_path.read_bytes() == before_labels
    assert report["metadata"]["matcher_called"] is False
    assert report["metadata"]["threshold_inferred"] is False
    assert report["metadata"]["labels_authorize_h3_membership"] is False
