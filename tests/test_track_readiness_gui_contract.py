import json

from race_engineer_gui import (
    READINESS_STATUS_COLORS,
    READINESS_STATUS_LABELS,
    track_readiness_status_tooltip,
    h3_maintenance_summary,
    h3_materialization_summary,
    h3_automation_next_action,
    h3_automation_summary,
)


def test_gui_distinguishes_hierarchical_track_readiness_states():
    assert READINESS_STATUS_COLORS["CURRENT_REQUIREMENTS_SATISFIED"] != (
        READINESS_STATUS_COLORS["COVERED_BY_TRACK_MATCH_BASELINE"]
    )
    assert READINESS_STATUS_COLORS["COVERED_BY_TRACK_MATCH_BASELINE"] != (
        READINESS_STATUS_COLORS["TRACK_MATCH_BASELINE_SHADOW"]
    )
    assert "exacta" in READINESS_STATUS_LABELS[
        "CURRENT_REQUIREMENTS_SATISFIED"
    ].casefold()
    assert "match-only" in READINESS_STATUS_LABELS[
        "COVERED_BY_TRACK_MATCH_BASELINE"
    ].casefold()


def test_gui_distinguishes_provisional_profile_from_missing_profile():
    assert READINESS_STATUS_COLORS["NEEDS_INDEPENDENT_PROFILE_SESSION"] != (
        READINESS_STATUS_COLORS["NEEDS_PROFILE"]
    )
    assert "provisional" in READINESS_STATUS_LABELS[
        "NEEDS_INDEPENDENT_PROFILE_SESSION"
    ].casefold()


def test_promoted_match_tooltip_does_not_claim_full_calibration():
    text = track_readiness_status_tooltip({
        "overall_status": "COVERED_BY_TRACK_MATCH_BASELINE",
        "baseline_source_variants": ["LMP2_ELMS"],
    })

    assert "sólo para MATCH" in text
    assert "REJECT sigue siendo específico" in text
    assert "No significa fully calibrated" in text
    assert "LMP2_ELMS" in text


def test_shadow_tooltip_keeps_match_and_reject_unauthorized():
    text = track_readiness_status_tooltip({
        "overall_status": "TRACK_MATCH_BASELINE_SHADOW",
    })

    assert "shadow" in text
    assert "No autoriza MATCH productivo" in text
    assert "nunca hereda REJECT" in text


def test_gui_tooltip_exposes_h3_ready_as_explicit_observational_import():
    text = track_readiness_status_tooltip({
        "overall_status": "CURRENT_REQUIREMENTS_SATISFIED",
        "h3_import": {"status": "H3_READY_TO_IMPORT"},
    })
    assert "listo para importación explícita" in text
    assert "History todavía no fue modificado" in text


def test_h3_automatic_summary_reads_only_scheduler_snapshot(tmp_path):
    state = tmp_path / "h3_import_maintenance.json"
    state.write_text(
        '{"mode":"AUDIT_READ_ONLY","history_mutated":false,'
        '"status_counts":{"H3_IMPORTED":7,"H3_READY_TO_IMPORT":1,'
        '"H3_NOT_APPLICABLE":4}}',
        encoding="utf-8",
    )

    text = h3_maintenance_summary(state)

    assert "audit read-only" in text
    assert "7 importados" in text
    assert "1 listos para revisión explícita" in text
    assert "4 no aplicables" in text


def test_h3_automatic_summary_fails_closed(tmp_path):
    missing = tmp_path / "missing.json"
    assert "esperando primera auditoría" in h3_maintenance_summary(missing)

    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        '{"mode":"APPLY_EXPLICIT","history_mutated":true,"status_counts":{}}',
        encoding="utf-8",
    )
    assert "contrato read-only inválido" in h3_maintenance_summary(invalid)

    malformed_counts = tmp_path / "malformed-counts.json"
    malformed_counts.write_text(
        '{"mode":"AUDIT_READ_ONLY","history_mutated":false,'
        '"status_counts":{"H3_IMPORTED":"unknown"}}',
        encoding="utf-8",
    )
    assert "estado local incompleto" in h3_maintenance_summary(malformed_counts)


def test_h3_materialization_summary_reports_ready_without_authorizing_apply(tmp_path):
    state = tmp_path / "h3_materialization_readiness.json"
    state.write_text(
        '{"mode":"AUDIT_READ_ONLY","history_mutated":false,"files_written":0,'
        '"status_counts":{"MATERIALIZATION_READY":2,'
        '"ALREADY_MATERIALIZED":5,"NO_AUTHORIZED_MATCH":4}}',
        encoding="utf-8",
    )

    text = h3_materialization_summary(state)

    assert "audit read-only" in text
    assert "2 listos para ejecución explícita" in text
    assert "5 ya materializados" in text
    assert "4 sin MATCH autorizado" in text


def test_h3_unified_summary_and_action_require_current_read_only_contract(tmp_path):
    state = tmp_path / "h3_automation_status.json"
    row = {
        "track": "Imola",
        "track_layout": "Imola",
        "vehicle_variant": "LMP2_ELMS",
    }
    state.write_text(
        json.dumps(
            {
                "mode": "STATUS_READ_ONLY",
                "freshness": "CURRENT",
                "history_mutated": False,
                "historical_actions_authorized": False,
                "files_written": 0,
                "contexts": [{**row, "next_action": "MATERIALIZE_EXPLICIT"}],
            }
        ),
        encoding="utf-8",
    )

    assert "vigente" in h3_automation_summary(state)
    assert "1 para materializar" in h3_automation_summary(state)
    assert h3_automation_next_action(state, row) == "MATERIALIZE_EXPLICIT"

    payload = json.loads(state.read_text(encoding="utf-8"))
    payload["freshness"] = "STALE"
    state.write_text(json.dumps(payload), encoding="utf-8")
    assert "datos vencidos" in h3_automation_summary(state)
    assert h3_automation_next_action(state, row) is None
