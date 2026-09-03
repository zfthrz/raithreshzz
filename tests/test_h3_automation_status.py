from __future__ import annotations

import json

from h3_automation_status import build_h3_automation_status, write_h3_automation_status


def _write(path, contexts, fingerprint):
    path.write_text(
        json.dumps({"contexts": contexts, "input_fingerprint": fingerprint}),
        encoding="utf-8",
    )


def test_unified_status_exposes_only_explicit_safe_next_actions(tmp_path):
    imports = tmp_path / "imports.json"
    materialization = tmp_path / "materialization.json"
    identity = {
        "track": "Imola",
        "track_layout": "Imola",
        "vehicle_variant": "LMP2_ELMS",
    }
    _write(imports, [{**identity, "status": "H3_NOT_APPLICABLE"}], "imports-sha")
    _write(
        materialization,
        [{**identity, "status": "MATERIALIZATION_READY"}],
        "materialization-sha",
    )

    status = build_h3_automation_status(
        import_state_path=imports,
        materialization_state_path=materialization,
        import_execution="PASS",
        materialization_execution="PASS",
        generated_at="2026-09-02T20:00:00+00:00",
    )

    assert status["freshness"] == "CURRENT"
    assert status["contexts"][0]["next_action"] == "MATERIALIZE_EXPLICIT"
    assert status["history_mutated"] is False
    assert status["historical_actions_authorized"] is False


def test_import_action_takes_precedence_after_materialization(tmp_path):
    imports = tmp_path / "imports.json"
    materialization = tmp_path / "materialization.json"
    identity = {"track": "Spa", "track_layout": "Spa", "vehicle_variant": "GT3"}
    _write(imports, [{**identity, "status": "H3_READY_TO_IMPORT"}], "a")
    _write(materialization, [{**identity, "status": "ALREADY_MATERIALIZED"}], "b")

    status = build_h3_automation_status(
        import_state_path=imports,
        materialization_state_path=materialization,
        import_execution="PASS",
        materialization_execution="PASS",
    )

    assert status["contexts"][0]["next_action"] == "IMPORT_EXPLICIT"


def test_failed_or_deferred_audit_invalidates_all_actions(tmp_path):
    imports = tmp_path / "imports.json"
    materialization = tmp_path / "materialization.json"
    identity = {"track": "Fuji", "track_layout": "Fuji", "vehicle_variant": "GT3"}
    _write(imports, [{**identity, "status": "H3_READY_TO_IMPORT"}], "old-a")
    _write(materialization, [{**identity, "status": "MATERIALIZATION_READY"}], "old-b")

    status = build_h3_automation_status(
        import_state_path=imports,
        materialization_state_path=materialization,
        import_execution="PASS",
        materialization_execution="DEFERRED_GAME_RUNNING",
    )

    assert status["freshness"] == "STALE"
    assert status["contexts"][0]["next_action"] == "REFRESH_AUDITS"


def test_status_writer_is_atomic_and_round_trips(tmp_path):
    path = tmp_path / "status.json"
    document = {"version": "0.1", "history_mutated": False}

    write_h3_automation_status(path, document)

    assert json.loads(path.read_text(encoding="utf-8")) == document
    assert not path.with_suffix(".json.tmp").exists()
