from __future__ import annotations

from pathlib import Path

import audit_h3_materialization_readiness as audit
from h3_import_readiness import H3_IMPORTED, H3_NOT_APPLICABLE, H3Context


def test_feature_audit_reports_ready_without_writing(tmp_path: Path):
    features = [{"pair": 1}]
    classifier = lambda rows, batches_root: ([{
        "pair_index": 0,
        "decision": "MATCH",
        "authority": {"production_match_authorized": True},
    }], {"matcher_version": "0.3"})
    gate = lambda rows, decisions, metadata: {
        "decision_counts": {"MATCH": 1, "AMBIGUOUS": 0, "REJECT": 0}
    }
    builder = lambda rows, decisions, persistent_min_sessions: ([], {
        "cross_session_repeat_count": 1,
        "conflict_review_required_count": 0,
    })
    monkey_path = tmp_path / "features.json"
    monkey_path.write_text("[{}]", encoding="utf-8")

    result = audit.inspect_feature_materialization(
        monkey_path,
        batches_root=tmp_path,
        classifier=classifier,
        gate_validator=gate,
        pattern_builder=builder,
    )

    assert result["status"] == audit.MATERIALIZATION_READY
    assert result["h3_summary"]["cross_session_repeat_count"] == 1


def test_feature_audit_stops_when_authorized_match_is_absent(tmp_path: Path):
    path = tmp_path / "features.json"
    path.write_text("[{}]", encoding="utf-8")
    built = []

    result = audit.inspect_feature_materialization(
        path,
        batches_root=tmp_path,
        classifier=lambda rows, batches_root: ([], {}),
        gate_validator=lambda rows, decisions, metadata: {
            "decision_counts": {"MATCH": 0, "AMBIGUOUS": 1, "REJECT": 0}
        },
        pattern_builder=lambda *_args, **_kwargs: built.append(True),
    )

    assert result["status"] == audit.NO_AUTHORIZED_MATCH
    assert built == []


def test_context_audit_skips_imported_and_fails_closed(tmp_path: Path, monkeypatch):
    ready_path = tmp_path / "ready.json"
    ready_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(audit, "discover_h3_import_readiness", lambda **_kwargs: {
        H3Context("Imola", "Imola", "LMP2_ELMS"): {
            "status": H3_IMPORTED,
            "batch_id": "imported",
            "features_path": str(tmp_path / "imported.json"),
        },
        H3Context("Spa", "Spa", "LMP2_ELMS"): {
            "status": H3_NOT_APPLICABLE,
            "batch_id": "ready",
            "features_path": str(ready_path),
        },
        H3Context("Fuji", "Fuji", "GT3"): {
            "status": H3_NOT_APPLICABLE,
            "batch_id": "broken",
            "features_path": str(tmp_path / "missing.json"),
        },
    })
    calls = []

    def inspector(path, *, batches_root):
        calls.append(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return {"status": audit.MATERIALIZATION_READY}

    report = audit.audit_h3_materialization_readiness(
        batches_root=tmp_path,
        history_db=tmp_path / "history.duckdb",
        inspector=inspector,
    )

    by_track = {row["track"]: row for row in report["contexts"]}
    assert by_track["Imola"]["status"] == audit.ALREADY_MATERIALIZED
    assert by_track["Spa"]["status"] == audit.MATERIALIZATION_READY
    assert by_track["Fuji"]["status"] == audit.MATERIALIZATION_FAILED
    assert len(calls) == 2
    assert report["files_written"] == 0
    assert report["history_mutated"] is False
