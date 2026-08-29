import json
from pathlib import Path

import materialize_h3_context as materializer
from h3_import_readiness import H3Context, H3_READY_TO_IMPORT


CONTEXT = H3Context("Spa", "Spa GP", "LMP2_ELMS")


def _ready(features_path: Path):
    return {
        "mode": "AUDIT_READ_ONLY",
        "contexts": [{
            "track": CONTEXT.track,
            "track_layout": CONTEXT.track_layout,
            "vehicle_variant": CONTEXT.vehicle_variant,
            "status": materializer.MATERIALIZATION_READY,
            "features_path": str(features_path),
            "batch_id": "batch-1",
        }],
    }


def test_default_is_read_only_and_does_not_call_pipeline(tmp_path: Path):
    features = tmp_path / "episode_pair_features.json"
    features.write_text("[]", encoding="utf-8")
    called = []

    report, code = materializer.materialize_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=tmp_path / "history.duckdb",
        readiness_auditor=lambda **_kwargs: _ready(features),
        pipeline_runner=lambda *_args, **_kwargs: called.append(True),
    )

    assert code == 0
    assert report["status"] == "READY_TO_MATERIALIZE"
    assert report["mode"] == "AUDIT_READ_ONLY"
    assert report["files_written"] == []
    assert report["history_mutated"] is False
    assert called == []


def test_apply_materializes_one_context_and_requires_ready_import_bundle(
    tmp_path: Path,
):
    batch = tmp_path / "batch"
    batch.mkdir()
    features = batch / "episode_pair_features.json"
    features.write_text("[]", encoding="utf-8")

    def pipeline_runner(features_path, **kwargs):
        assert features_path == features.resolve()
        assert kwargs["history_db"] is None
        outputs = {}
        for key, name in (
            ("episode_pair_matches", "episode_pair_matches.json"),
            ("persistent_patterns", "persistent_patterns.json"),
            ("report", "h3_pipeline_report.json"),
        ):
            path = batch / name
            path.write_text(json.dumps({"ok": True}), encoding="utf-8")
            outputs[key] = str(path)
        return {
            "result": "PASS",
            "history_mutated": False,
            "history_imported": False,
            "outputs": outputs,
        }, 0

    report, code = materializer.materialize_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=tmp_path / "history.duckdb",
        apply=True,
        readiness_auditor=lambda **_kwargs: _ready(features),
        pipeline_runner=pipeline_runner,
        readiness_discoverer=lambda **_kwargs: {
            CONTEXT: {"status": H3_READY_TO_IMPORT}
        },
    )

    assert code == 0
    assert report["status"] == "MATERIALIZED_READY_TO_IMPORT"
    assert len(report["files_written"]) == 3
    assert report["history_mutated"] is False
    assert report["historical_actions_authorized"] is False


def test_non_ready_context_fails_closed_without_pipeline(tmp_path: Path):
    features = tmp_path / "episode_pair_features.json"
    features.write_text("[]", encoding="utf-8")
    readiness = _ready(features)
    readiness["contexts"][0]["status"] = "NO_AUTHORIZED_MATCH"
    called = []

    report, code = materializer.materialize_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=tmp_path / "history.duckdb",
        apply=True,
        readiness_auditor=lambda **_kwargs: readiness,
        pipeline_runner=lambda *_args, **_kwargs: called.append(True),
    )

    assert code == 2
    assert report["status"] == "BLOCKED_NOT_READY"
    assert report["history_mutated"] is False
    assert called == []


def test_stale_confirmed_fingerprint_blocks_before_audit(tmp_path: Path):
    audited = []

    report, code = materializer.materialize_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=tmp_path / "history.duckdb",
        apply=True,
        expected_input_fingerprint="stale",
        readiness_auditor=lambda **_kwargs: audited.append(True),
    )

    assert code == 2
    assert report["status"] == "BLOCKED_STALE_READINESS"
    assert audited == []


def test_pipeline_cannot_claim_history_mutation(tmp_path: Path):
    batch = tmp_path / "batch"
    batch.mkdir()
    features = batch / "episode_pair_features.json"
    features.write_text("[]", encoding="utf-8")

    report, code = materializer.materialize_context(
        CONTEXT,
        batches_root=tmp_path,
        history_db=tmp_path / "history.duckdb",
        apply=True,
        readiness_auditor=lambda **_kwargs: _ready(features),
        pipeline_runner=lambda *_args, **_kwargs: ({
            "result": "PASS",
            "history_mutated": True,
            "history_imported": True,
            "outputs": {},
        }, 0),
    )

    assert code == 1
    assert report["status"] == "FAILED"
    assert report["history_mutated"] is False
