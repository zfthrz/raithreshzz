import json
from pathlib import Path

import pytest

from label_h3_projection_pairs import (
    REVIEW_SCOPE,
    load_projection_labels,
    load_projection_queue,
)


def _queue(path: Path, *, scope: str = REVIEW_SCOPE) -> Path:
    path.write_text(
        json.dumps({
            "metadata": {
                "review_scope": scope,
                "labels_authorize_matcher_calibration": False,
                "labels_authorize_h3_membership": False,
            },
            "queue": [{
                "pair_id": "pair-1",
                "features": {
                    "track": "Track",
                    "session_a": 1,
                    "episode_pk_a": 10,
                    "session_b": 2,
                    "episode_pk_b": 20,
                },
            }],
        }),
        encoding="utf-8",
    )
    return path


def test_new_labels_preserve_isolated_non_authoritative_scope(tmp_path: Path):
    queue = _queue(tmp_path / "queue.json")
    labels = load_projection_labels(tmp_path / "labels.json", queue, "driver")

    metadata = labels["metadata"]
    assert metadata["review_scope"] == REVIEW_SCOPE
    assert metadata["labels_authorize_matcher_calibration"] is False
    assert metadata["labels_authorize_h3_membership"] is False
    assert metadata["affects_next_stint_plan"] is False
    assert metadata["historical_actions_authorized"] is False


def test_queue_with_wrong_scope_fails_closed(tmp_path: Path):
    queue = _queue(tmp_path / "queue.json", scope="H2_CALIBRATION")

    with pytest.raises(ValueError, match="scope aislado"):
        load_projection_queue(queue)


def test_existing_generic_labels_cannot_be_reused_as_h3_review(tmp_path: Path):
    queue = _queue(tmp_path / "queue.json")
    labels_path = tmp_path / "labels.json"
    import hashlib

    labels_path.write_text(
        json.dumps({
            "metadata": {
                "source_queue_sha256": hashlib.sha256(queue.read_bytes()).hexdigest(),
            },
            "labels": [],
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no pertenecen"):
        load_projection_labels(labels_path, queue, None)
