from __future__ import annotations

from pathlib import Path

import maintain_h3_imports as maintenance
from h3_import_readiness import (
    H3_CONFLICT,
    H3_IMPORTED,
    H3_READY_TO_IMPORT,
    H3Context,
)


def _rows(tmp_path: Path):
    return {
        H3Context("Imola", "Imola", "LMP2_ELMS"): {
            "status": H3_READY_TO_IMPORT,
            "batch_id": "imola-ready",
            "patterns_path": str(tmp_path / "imola" / "persistent_patterns.json"),
            "matches_path": str(tmp_path / "imola" / "episode_pair_matches.json"),
        },
        H3Context("Spa", "Spa", "LMP2_ELMS"): {
            "status": H3_CONFLICT,
            "batch_id": "spa-conflict",
            "patterns_path": str(tmp_path / "spa" / "persistent_patterns.json"),
            "matches_path": str(tmp_path / "spa" / "episode_pair_matches.json"),
        },
        H3Context("Monza", "Monza", "HYPER"): {
            "status": H3_IMPORTED,
            "batch_id": "monza-imported",
            "patterns_path": str(tmp_path / "monza" / "persistent_patterns.json"),
            "matches_path": str(tmp_path / "monza" / "episode_pair_matches.json"),
        },
    }


def test_audit_is_read_only_and_sorts_contexts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        maintenance,
        "discover_h3_import_readiness",
        lambda **_kwargs: _rows(tmp_path),
    )

    report = maintenance.audit_h3_imports(
        batches_root=tmp_path / "batches",
        history_db=tmp_path / "history.duckdb",
    )

    assert report["mode"] == "AUDIT_READ_ONLY"
    assert report["history_mutated"] is False
    assert report["historical_actions_authorized"] is False
    assert [row["track"] for row in report["contexts"]] == [
        "Imola", "Monza", "Spa"
    ]
    assert report["status_counts"] == {
        H3_READY_TO_IMPORT: 1,
        H3_IMPORTED: 1,
        H3_CONFLICT: 1,
    }


def test_apply_imports_only_ready_bundles(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        maintenance,
        "discover_h3_import_readiness",
        lambda **_kwargs: _rows(tmp_path),
    )
    calls = []

    def importer(history_db, patterns_path, matches_path):
        calls.append((history_db, patterns_path, matches_path))
        return {"status": "RUN", "pattern_run_id": 12}

    report, code = maintenance.apply_ready_h3_imports(
        batches_root=tmp_path / "batches",
        history_db=tmp_path / "history.duckdb",
        importer=importer,
    )

    assert code == 0
    assert len(calls) == 1
    assert calls[0][1].parent.name == "imola"
    assert report["ready_before_apply"] == 1
    assert report["history_mutated"] is True
    assert report["historical_actions_authorized"] is False
    assert report["import_results"][0]["pattern_run_id"] == 12


def test_apply_fails_closed_per_ready_bundle(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        maintenance,
        "discover_h3_import_readiness",
        lambda **_kwargs: _rows(tmp_path),
    )

    def importer(*_args):
        raise ValueError("invalid provenance")

    report, code = maintenance.apply_ready_h3_imports(
        batches_root=tmp_path / "batches",
        history_db=tmp_path / "history.duckdb",
        importer=importer,
    )

    assert code == 1
    assert report["result"] == "FAILED"
    assert report["history_mutated"] is False
    assert report["import_results"][0]["status"] == "FAILED"
    assert "invalid provenance" in report["import_results"][0]["reason"]
