from __future__ import annotations

import json

import audit_calibration_batch_retention as audit


CONTEXT = ("Test Track", "Test Layout", "LMP2_ELMS")


def _batch(root, name, session_ids, labels=0):
    batch = root / name
    batch.mkdir(parents=True)
    labels_path = batch / "pair_labels.json"
    if labels:
        labels_path.write_text(json.dumps({
            "labels": [
                {"pair_id": f"pair-{index}", "human_label": "SAME"}
                for index in range(labels)
            ]
        }), encoding="utf-8")
    (batch / "payload.bin").write_bytes(b"x" * 10)
    (batch / "BATCH_STATUS.json").write_text(json.dumps({
        "track": CONTEXT[0],
        "track_layout": CONTEXT[1],
        "vehicle_variant": CONTEXT[2],
        "batch_id": name,
        "batch_dir": str(batch),
        "steps": {
            "vehicle_context_selection": {"session_ids": session_ids},
            "human_labels": {
                "labels_path": str(labels_path),
                "labeled_pairs": labels,
            },
        },
    }), encoding="utf-8")


def test_audit_preserves_labels_and_marks_only_old_unlabeled_as_regenerable(tmp_path):
    _batch(tmp_path, "old-labeled", [1, 2], labels=4)
    _batch(tmp_path, "old-unlabeled", [1, 2, 3])
    _batch(tmp_path, "current", [1, 2, 3, 4])

    report = audit.inventory(tmp_path)
    classifications = {
        item["batch_id"]: item["classification"] for item in report["batches"]
    }

    assert report["authority"] == "READ_ONLY_AUDIT"
    assert report["destructive_actions_performed"] == 0
    assert classifications == {
        "old-labeled": "PRESERVE_HUMAN_EVIDENCE",
        "old-unlabeled": "SUPERSEDED_UNLABELED_REGENERABLE",
        "current": "ACTIVE_HUMAN_REVIEW",
    }
    assert report["summary"]["superseded_unlabeled_batches"] == 1
    assert report["summary"]["potentially_reclaimable_bytes"] > 0


def test_latest_labeled_batch_is_current_evidence(tmp_path):
    _batch(tmp_path, "current", [1, 2], labels=2)

    report = audit.inventory(tmp_path)

    assert report["batches"][0]["classification"] == "CURRENT_WITH_HUMAN_EVIDENCE"
