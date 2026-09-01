from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import race_engineer_ui_model as ui_model
from race_engineer_ui_model import (
    _plan_text,
    build_session_change_view,
    discover_sessions,
    filter_sessions,
    format_lap_time,
    load_calibration_summary,
    load_session_detail,
)
from session_change_tracking import (
    CHANGE_NEW,
    CHANGE_REPEATED,
    CHANGE_RESOLVED,
    MATCH_BASIS_PHYSICAL,
    MATCH_BASIS_REFERENCE_PROFILE,
)


def test_driver_focus_precedes_complete_plan_when_p11_is_consistent():
    items = [
        {
            "plan_label": label,
            "track_location": {"label": f"T{index}"},
            "driver_cues": [{"text": f"Cue {label}"}],
        }
        for index, label in enumerate(("A", "B", "C"), start=1)
    ]
    facts = {
        "next_stint_plan": items,
        "next_stint_focus": {
            "status": "ACTIVE",
            "focus_count": 2,
            "items": [items[1], items[2]],
        },
    }

    text = _plan_text(facts)
    focus_text, complete_text = text.split("PLAN COMPLETO VALIDADO")

    assert focus_text.startswith("FOCO DEL PILOTO")
    assert focus_text.index("Zona B") < focus_text.index("Zona C")
    assert "Zona A" not in focus_text
    assert all(f"Zona {label}" in complete_text for label in ("A", "B", "C"))


def test_inconsistent_driver_focus_falls_back_to_complete_plan():
    item = {
        "plan_label": "A",
        "track_location": {"label": "T1"},
        "driver_cues": [{"text": "Cue A"}],
    }

    text = _plan_text(
        {
            "next_stint_plan": [item],
            "next_stint_focus": {
                "status": "ACTIVE",
                "focus_count": 2,
                "items": [item],
            },
        }
    )

    assert "FOCO DEL PILOTO" not in text
    assert "Zona A" in text


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def make_session(tmp_path: Path, name: str, *, llm: bool = True) -> Path:
    analysis = write_json(
        tmp_path / "analysis" / f"{name}.json",
        {
            "metadata": {
                "track": "Fuji Speedway",
                "session_type": "P",
                "timestamp_utc": "2026-08-19T19:38:36Z",
                "reference_lap": 1,
                "valid_laps": [1, 2, 3, 4],
                "lap_times_s": {"1": 90.94},
                "vehicle_identity": {
                    "variant": "LMP2_ELMS",
                    "car_name_raw": "IDEC Sport #18",
                },
            },
            "laps": [
                {"lap": 0, "duration": 120.0},
                {"lap": 1, "duration": 90.94},
                {"lap": 2, "duration": 91.44},
            ],
        },
    )
    debrief = write_json(
        tmp_path / "llm" / f"{name}.json",
        {
            "global_analysis": "# Debrief\n\nTexto validado.",
            "session_coaching_facts": {
                "next_stint_plan": [
                    {
                        "plan_label": "A",
                        "track_location": {"label": "T1"},
                        "driver_cues": [{"text": "Frená 10 m más tarde"}],
                    }
                ]
            },
        },
    )
    stages = {
        "analyze": {"status": "RUN", "output": str(analysis)},
        "history": {"status": "RUN"},
    }
    summary = {
        "analyze": "RUN",
        "history": "RUN",
        "llm": "SKIPPED_NOT_APPLICABLE",
        "llm_validator": "SKIPPED_NOT_APPLICABLE",
    }
    if llm:
        stages["llm"] = {"status": "RUN", "output": str(debrief)}
        stages["llm_validator"] = {"status": "RUN", "output": str(debrief)}
        summary["llm"] = "RUN"
        summary["llm_validator"] = "RUN"
    return write_json(
        tmp_path / "runs" / name / "state.json",
        {
            "database": str(tmp_path / f"{name}.duckdb"),
            "stages": stages,
            "last_summary": summary,
        },
    )


def test_discovers_validated_debrief_and_reference_metadata(tmp_path: Path):
    make_session(tmp_path, "session-a")

    sessions, errors = discover_sessions(tmp_path / "runs")

    assert errors == []
    assert len(sessions) == 1
    session = sessions[0]
    assert session.track == "Fuji Speedway"
    assert session.vehicle == "IDEC Sport #18"
    assert session.valid_lap_count == 4
    assert session.reference_lap == 1
    assert session.reference_time_s == 90.94
    assert session.status == "DEBRIEF_READY"
    assert session.debrief_path is not None
    assert session.has_validated_debrief is True


def test_session_metadata_cache_avoids_reloading_unchanged_analysis(
    tmp_path: Path,
    monkeypatch,
):
    state_path = make_session(tmp_path, "session-cache")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    analysis_path = Path(state["stages"]["analyze"]["output"]).resolve()
    cache_path = tmp_path / "local" / "gui_session_metadata_cache.json"

    first, errors = discover_sessions(
        tmp_path / "runs",
        metadata_cache_path=cache_path,
    )
    assert errors == []
    assert first[0].track == "Fuji Speedway"
    assert cache_path.is_file()

    original_json = ui_model._json
    analysis_reads = []

    def tracking_json(path):
        if Path(path).resolve() == analysis_path:
            analysis_reads.append(Path(path))
        return original_json(path)

    monkeypatch.setattr(ui_model, "_json", tracking_json)
    second, errors = discover_sessions(
        tmp_path / "runs",
        metadata_cache_path=cache_path,
    )

    assert errors == []
    assert second[0].reference_time_s == 90.94
    assert analysis_reads == []


def test_history_only_session_is_not_presented_as_debrief_ready(tmp_path: Path):
    make_session(tmp_path, "session-history", llm=False)

    sessions, _ = discover_sessions(tmp_path / "runs")

    assert sessions[0].status == "HISTORY_READY"
    assert sessions[0].status_detail == (
        "Guardada en History; debrief automático pendiente"
    )
    assert sessions[0].debrief_path is None
    assert sessions[0].has_validated_debrief is False


def make_change_session(
    tmp_path: Path,
    name: str,
    *,
    timestamp: str,
    plan: list[dict],
) -> Path:
    state_path = make_session(tmp_path, name)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    analysis_path = Path(state["stages"]["analyze"]["output"])
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    metadata = analysis["metadata"]
    metadata["timestamp_utc"] = timestamp
    metadata["session_context"] = {
        "lmu_track_name": "Fuji Speedway",
        "lmu_track_layout": "Fuji Speedway",
    }
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    debrief_path = Path(state["stages"]["llm"]["output"])
    debrief = json.loads(debrief_path.read_text(encoding="utf-8"))
    debrief["session_coaching_facts"]["next_stint_plan"] = plan
    debrief_path.write_text(json.dumps(debrief), encoding="utf-8")
    return state_path


def change_item(*, current: bool) -> dict:
    item = {
        "plan_label": "A" if current else "B",
        "start_distance_m": 100.0 if current else 90.0,
        "end_distance_m": 180.0 if current else 170.0,
        "track_location": {
            "label": "T1 — First Corner",
            "start_m": 90.0,
            "end_m": 180.0,
        },
        "braking_point_patterns": [{"coaching_direction": "later"}],
        "brake_release_patterns": [{
            "coaching_direction": "earlier" if current else "later"
        }],
        "reference_action_profiles": [{
            "channel": "throttle",
            "shape_sequence": ["reaplicación sostenida"],
            "shape_summary": "presentation text is not an identity",
        }],
    }
    if current:
        item["throttle_onset_patterns"] = [{"coaching_direction": "earlier"}]
    return item


def test_late_pipeline_failure_does_not_hide_validated_debrief_artifact(tmp_path: Path):
    state_path = make_session(tmp_path, "session-late-failure")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stages"]["h5_3"] = {"status": "FAILED"}
    state["last_summary"]["h5_3"] = "FAILED"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    session = discover_sessions(tmp_path / "runs")[0][0]

    assert session.status == "FAILED"
    assert session.has_validated_debrief is True


def test_detail_reads_debrief_and_authorized_plan(tmp_path: Path):
    make_session(tmp_path, "session-a")
    record = discover_sessions(tmp_path / "runs")[0][0]

    detail = load_session_detail(record)

    assert "Texto validado" in detail.debrief_markdown
    assert "Zona A — T1" in detail.plan_text
    assert "Frená 10 m más tarde" in detail.plan_text
    assert "debrief_validator" in detail.pipeline_text
    assert "llm_validator" not in detail.pipeline_text


def test_catalog_reads_canonical_debrief_stage_names(tmp_path: Path):
    state_path = make_session(tmp_path, "session-canonical")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stages"]["debrief"] = state["stages"].pop("llm")
    state["stages"]["debrief_validator"] = state["stages"].pop("llm_validator")
    state["last_summary"]["debrief"] = state["last_summary"].pop("llm")
    state["last_summary"]["debrief_validator"] = state["last_summary"].pop(
        "llm_validator"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")

    record = discover_sessions(tmp_path / "runs")[0][0]

    assert record.has_validated_debrief is True
    assert record.debrief_path is not None
    assert dict(record.stages)["debrief_validator"] == "RUN"


def test_session_change_view_is_safely_unavailable_without_previous(tmp_path: Path):
    make_change_session(
        tmp_path,
        "only-session",
        timestamp="2026-08-27T12:00:00Z",
        plan=[change_item(current=True)],
    )
    sessions, _ = discover_sessions(tmp_path / "runs")

    view = load_session_detail(sessions[0], sessions).session_change_view

    assert view["status"] == "UNAVAILABLE"
    assert view["reason"] == "no_previous_compatible_session"
    assert view["previous_session_key"] is None
    assert view["previous_timestamp_utc"] is None
    assert view["previous_timestamp_label"] is None
    assert view["grouped_changes"] == []


def test_session_change_view_groups_and_orders_spa_style_changes(tmp_path: Path):
    previous_timestamp = "2026-08-26T04:03:26Z"
    make_change_session(
        tmp_path,
        "previous",
        timestamp=previous_timestamp,
        plan=[change_item(current=False)],
    )
    make_change_session(
        tmp_path,
        "current",
        timestamp="2026-08-27T04:12:53Z",
        plan=[change_item(current=True)],
    )
    sessions, _ = discover_sessions(tmp_path / "runs")
    current = next(item for item in sessions if item.session_key == "current")

    view = load_session_detail(current, sessions).session_change_view

    assert view["status"] == "AVAILABLE"
    assert view["previous_session_key"] == "previous"
    assert view["previous_timestamp_utc"] == previous_timestamp
    assert view["previous_timestamp_label"] in view["title"]
    assert "última sesión comparable" in view["title"]
    assert len(view["grouped_changes"]) == 1
    group = view["grouped_changes"][0]
    assert group["location_label"] == "T1 — First Corner"
    assert [
        (change["status"], change["match_basis"])
        for change in group["changes"]
    ] == [
        (CHANGE_REPEATED, MATCH_BASIS_PHYSICAL),
        (CHANGE_NEW, MATCH_BASIS_PHYSICAL),
        (CHANGE_NEW, MATCH_BASIS_PHYSICAL),
        (CHANGE_RESOLVED, MATCH_BASIS_PHYSICAL),
        (CHANGE_REPEATED, MATCH_BASIS_REFERENCE_PROFILE),
    ]
    assert [change["presentation_label"] for change in group["changes"]] == [
        "frenada más tarde",
        "liberación de freno más temprano",
        "reaplicación de acelerador más temprano",
        "liberación de freno más tarde",
        "patrón de acelerador repetido",
    ]
    assert group["changes"][-1]["action_family"] is None
    assert "más tarde" not in group["changes"][-1]["presentation_label"]
    assert view["observational_only"] is True
    assert view["affects_next_stint_plan"] is False
    assert view["historical_actions_authorized"] is False


def test_session_change_view_does_not_mutate_core_result(tmp_path: Path, monkeypatch):
    import copy

    make_session(tmp_path, "session")
    record = discover_sessions(tmp_path / "runs")[0][0]
    result = {
        "status": "AVAILABLE",
        "previous_session_key": None,
        "change_counts": {"NEW": 1, "REPEATED": 0, "RESOLVED": 0},
        "observational_only": True,
        "affects_next_stint_plan": False,
        "historical_actions_authorized": False,
        "changes": [{
            "status": CHANGE_NEW,
            "match_basis": MATCH_BASIS_PHYSICAL,
            "action": {
                "family": "braking_point",
                "coaching_direction": "later",
            },
            "current_item": {
                "start_distance_m": 100.0,
                "end_distance_m": 150.0,
                "track_location": {"label": "T1"},
            },
            "previous_item": None,
        }],
    }
    before = copy.deepcopy(result)
    monkeypatch.setattr(
        "race_engineer_ui_model.build_session_change_tracking",
        lambda current_record, all_sessions: result,
    )

    build_session_change_view(record, [record])

    assert result == before


def test_legacy_detail_load_skips_expensive_change_tracking(tmp_path: Path, monkeypatch):
    make_session(tmp_path, "session")
    record = discover_sessions(tmp_path / "runs")[0][0]
    monkeypatch.setattr(
        "race_engineer_ui_model.build_session_change_view",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("change tracking must be deferred")
        ),
    )

    detail = load_session_detail(record)

    assert detail.session_change_view["status"] == "UNAVAILABLE"
    assert detail.session_change_view["reason"] == "session_catalog_not_provided"


def test_detail_renders_deterministic_lap_times_and_reference_delta(tmp_path: Path):
    make_session(tmp_path, "session-laps")
    record = discover_sessions(tmp_path / "runs")[0][0]

    detail = load_session_detail(record)

    assert "Vuelta 1: 1:30.940 · REFERENCIA, válida" in detail.laps_text
    assert "Vuelta 2: 1:31.440 · +0.500 s vs referencia · válida" in detail.laps_text


def test_detail_renders_selected_h4_reference_as_observational(tmp_path: Path):
    state_path = make_session(tmp_path, "session-h4")
    h4 = write_json(
        tmp_path / "h4" / "selection.json",
        {
            "selection_status": "HISTORICAL_REFERENCE_SELECTED",
            "target_session": {
                "track": "Fuji Speedway",
                "track_layout": "Fuji Speedway",
                "vehicle_variant": "LMP2_ELMS",
                "car_name_raw": "IDEC Sport #18",
                "session_reference": {"lap": 1, "duration_s": 92.26},
            },
            "selected_historical_reference": {
                "session_id": 7,
                "lap": 8,
                "duration_s": 90.98,
                "timestamp_utc": "2026-08-18T12:00:00Z",
                "historical_minus_session_reference_s": -1.28,
            },
            "candidate_summary": {"candidate_sessions_considered": 6, "eligible": 1, "rejected": 5},
        },
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stages"]["h4"] = {"status": "RUN", "output": str(h4)}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    detail = load_session_detail(discover_sessions(tmp_path / "runs")[0][0])

    assert "History #7 · vuelta 8" in detail.historical_reference_text
    assert "1:30.980" in detail.historical_reference_text
    assert "-1.280 s" in detail.historical_reference_text
    assert "no reemplaza la referencia de la sesión" in detail.historical_reference_text


def test_detail_renders_h5_2_comparison_and_validated_observation(tmp_path: Path):
    state_path = make_session(tmp_path, "session-h5-2")
    raw = write_json(
        tmp_path / "h5_2" / "comparison.json",
        {
            "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
            "context": {"track": "Fuji Speedway", "vehicle_variant": "LMP2_ELMS"},
            "historical_reference": {"session_id": 7, "lap": 8, "duration_s": 90.98},
            "current_session_reference": {"session_id": 9, "lap": 1, "duration_s": 92.26},
            "temporal_validation": {"calculated_current_minus_historical_s": 1.28},
            "spatial_comparison": {
                "localization": {
                    "mode": "validated_track_profile",
                    "profile_status": "VALIDATED_MULTI_SESSION",
                },
                "zone_summaries": [],
            },
        },
    )
    llm = write_json(
        tmp_path / "h5_2_llm" / "observation.json",
        {
            "metadata": {"backend": "deepseek", "model": "deepseek-v4-pro"},
            "rendered_analysis": "Observación histórica validada sin autoridad de coaching.",
        },
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stages"]["h5_2"] = {"status": "RUN", "output": str(raw)}
    state["stages"]["h5_2_llm"] = {"status": "RUN", "output": str(llm)}
    state["last_summary"]["h5_2"] = "RUN"
    state["last_summary"]["h5_2_llm"] = "RUN"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    detail = load_session_detail(discover_sessions(tmp_path / "runs")[0][0])

    assert "History #7 · vuelta 8 · 1:30.980" in detail.historical_comparison_text
    assert "Actual - histórica: +1.280 s" in detail.historical_comparison_text
    assert "Provenance original: deepseek / deepseek-v4-pro" in detail.historical_comparison_text
    assert "Narrativa histórica legacy validada" in detail.historical_comparison_text
    assert "Observación histórica validada" in detail.historical_comparison_text
    assert "No autoriza acciones" in detail.historical_comparison_text
    assert str(raw) in detail.pipeline_text
    assert str(llm) in detail.pipeline_text
    assert "h5_2_narrative_legacy" in detail.pipeline_text
    assert "\n  h5_2_llm" not in detail.pipeline_text


def test_detail_builds_structured_historical_comparison_view(tmp_path: Path):
    state_path = make_session(tmp_path, "session-h5-2-view")
    raw = write_json(
        tmp_path / "h5_2" / "comparison.json",
        {
            "status": "RAW_CROSS_SESSION_COMPARISON_AVAILABLE",
            "context": {"track": "Fuji Speedway", "vehicle_variant": "LMP2_ELMS"},
            "historical_reference": {"session_id": 7, "lap": 8, "duration_s": 90.98},
            "current_session_reference": {"session_id": 9, "lap": 1, "duration_s": 92.26},
            "temporal_validation": {"calculated_current_minus_historical_s": 1.28},
            "spatial_comparison": {
                "localization": {
                    "mode": "validated_track_profile",
                    "profile_status": "VALIDATED_MULTI_SESSION",
                },
                "zone_summaries": [
                    {
                        "type": "frenada",
                        "location": {"label": "Curva 1"},
                        "delta_change": 0.18,
                        "start_distance": 100.0,
                        "end_distance": 180.0,
                    },
                    {
                        "type": "tracção",
                        "location": {"label": "Curva 2"},
                        "delta_change": 0.44,
                        "start_distance": 500.0,
                        "end_distance": 580.0,
                    },
                    {
                        "type": "tracção",
                        "location": {"label": "Curva 3"},
                        "delta_change": -0.12,
                        "start_distance": 900.0,
                        "end_distance": 960.0,
                    },
                    {
                        "type": "frenada",
                        "location": {"label": "Curva 4"},
                        "delta_change": 0.09,
                        "start_distance": 1400.0,
                        "end_distance": 1480.0,
                    },
                ],
            },
        },
    )
    llm = write_json(
        tmp_path / "h5_2_llm" / "observation.json",
        {
            "metadata": {"backend": "ollama", "model": "ingenierov3"},
            "rendered_analysis": "Observación validada para la vista lado a lado.",
        },
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["stages"]["h5_2"] = {"status": "RUN", "output": str(raw)}
    state["stages"]["h5_2_llm"] = {"status": "RUN", "output": str(llm)}
    state["last_summary"]["h5_2"] = "RUN"
    state["last_summary"]["h5_2_llm"] = "RUN"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    view = load_session_detail(discover_sessions(tmp_path / "runs")[0][0]).historical_comparison_view

    assert view["available"] is True
    assert view["stage_status"] == "RUN"
    assert view["delta_s"] == 1.28
    assert view["delta_text"] == "+1.280 s"
    assert view["historical"]["session_id"] == 7
    assert view["historical"]["duration_text"] == "1:30.980"
    assert view["current"]["lap"] == 1
    assert view["localization"]["mode"] == "validated_track_profile"
    assert [zone["label"] for zone in view["zones"]] == ["Curva 2", "Curva 1", "Curva 3"]
    assert view["zones"][0]["delta_change_s"] == 0.44
    assert view["llm"]["backend"] == "ollama"
    assert view["llm"]["model"] == "ingenierov3"
    assert "Observación validada" in view["llm"]["rendered"]


def test_structured_historical_comparison_view_reports_unavailable(tmp_path: Path):
    make_session(tmp_path, "session-without-view")

    view = load_session_detail(discover_sessions(tmp_path / "runs")[0][0]).historical_comparison_view

    assert view["available"] is False
    assert view["stage_status"] == "NO_EJECUTADA"
    assert view["delta_s"] is None
    assert view["zones"] == []
    assert view["llm"]["rendered"] == ""


def test_detail_explains_when_h5_2_is_not_available(tmp_path: Path):
    make_session(tmp_path, "session-without-h5-2")

    detail = load_session_detail(discover_sessions(tmp_path / "runs")[0][0])

    assert "no tiene una comparación histórica H5.2" in detail.historical_comparison_text
    assert "NO_EJECUTADA" in detail.historical_comparison_text
    assert "Consultá Referencia histórica" in detail.historical_comparison_text


def test_malformed_state_is_reported_without_hiding_valid_sessions(tmp_path: Path):
    make_session(tmp_path, "valid")
    broken = tmp_path / "runs" / "broken" / "state.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{not-json", encoding="utf-8")

    sessions, errors = discover_sessions(tmp_path / "runs")

    assert len(sessions) == 1
    assert len(errors) == 1
    assert "broken" in errors[0]


def test_sessions_are_sorted_by_latest_state_first(tmp_path: Path):
    first = make_session(tmp_path, "first")
    second = make_session(tmp_path, "second")
    first.touch()
    second.touch()
    first.touch()

    sessions, _ = discover_sessions(tmp_path / "runs")

    assert sessions[0].session_key == "first"


def test_main_session_filters_combine_search_terms_and_status(tmp_path: Path):
    make_session(tmp_path, "fuji-debrief")
    make_session(tmp_path, "fuji-history", llm=False)
    sessions, _ = discover_sessions(tmp_path / "runs")
    failed = replace(
        sessions[0],
        session_key="monza-failed",
        track="Autodromo Nazionale Monza",
        vehicle="Toyota #7",
        status="FAILED",
        status_detail="Falló: llm",
    )
    sessions.append(failed)

    assert [item.session_key for item in filter_sessions(sessions, query="fuji validado")] == [
        "fuji-debrief"
    ]
    assert [
        item.session_key
        for item in filter_sessions(sessions, status_filter="HISTORY_READY")
    ] == ["fuji-history"]
    assert [
        item.session_key
        for item in filter_sessions(sessions, query="monza toyota", status_filter="FAILED")
    ] == ["monza-failed"]


def test_main_session_filter_rejects_unknown_status(tmp_path: Path):
    make_session(tmp_path, "session")
    sessions, _ = discover_sessions(tmp_path / "runs")
    try:
        filter_sessions(sessions, status_filter="UNKNOWN")
    except ValueError as exc:
        assert "no soportado" in str(exc)
    else:
        raise AssertionError("unknown session filter should fail closed")


def test_lap_time_formatter_is_driver_friendly():
    assert format_lap_time(90.94) == "1:30.940"
    assert format_lap_time(None) == "—"


def test_calibration_summary_reads_batch_statuses(tmp_path: Path):
    batch = tmp_path / "spa" / "BATCH_STATUS.json"
    batch.parent.mkdir(parents=True)
    batch.write_text(
        json.dumps(
            {
                "track": "Circuit de Spa-Francorchamps",
                "track_layout": "Circuit de Spa-Francorchamps",
                "vehicle_variant": "LMP2_ELMS",
                "batch_id": "abc",
                "steps": {
                    "vehicle_context_selection": {"session_count": 9},
                    "human_labels": {"labeled_pairs": 24, "queue_pairs": 24},
                    "evaluation_readiness": {
                        "status": "PASS",
                        "evaluation_pairs": 5,
                    },
                    "calibration_dataset": {"calibration_ready": True},
                },
                "matcher": {
                    "status": "CALIBRATED_PROVISIONAL_SINGLE_CONTEXT"
                },
            }
        ),
        encoding="utf-8",
    )

    summary = load_calibration_summary(base_dir=tmp_path)

    assert summary["calibrated_contexts"] == 1
    assert summary["ready_datasets"] == 1
    row = summary["rows"][0]
    assert row["sessions"] == 9
    assert row["labeled_pairs"] == 24
    assert row["evaluation_pairs"] == 5
    assert row["matcher_status"] == "CALIBRATED_PROVISIONAL_SINGLE_CONTEXT"


def test_calibration_summary_empty_directory(tmp_path: Path):
    summary = load_calibration_summary(base_dir=tmp_path)
    assert summary["rows"] == []
    assert summary["calibrated_contexts"] == 0
    assert summary["ready_datasets"] == 0


def test_calibration_summary_refreshes_legacy_matcher_status(tmp_path: Path):
    batch = tmp_path / "spa" / "BATCH_STATUS.json"
    batch.parent.mkdir(parents=True)
    batch.write_text(
        json.dumps(
            {
                "track": "Circuit de Spa-Francorchamps",
                "track_layout": "Circuit de Spa-Francorchamps",
                "vehicle_variant": "LMP2_ELMS",
                "batch_id": "034f",
                "steps": {
                    "vehicle_context_selection": {"session_count": 9},
                    "human_labels": {"labeled_pairs": 24, "queue_pairs": 24},
                    "evaluation_readiness": {
                        "status": "PASS",
                        "evaluation_pairs": 1,
                    },
                    "calibration_dataset": {"calibration_ready": True},
                },
                "matcher": {"status": "BLOCKED_BY_REAL_DATA"},
            }
        ),
        encoding="utf-8",
    )

    summary = load_calibration_summary(base_dir=tmp_path)

    row = summary["rows"][0]
    assert row["matcher_status"] == "CALIBRATED_PROVISIONAL_SINGLE_CONTEXT"
    assert row["legacy_status_refreshed"] is True
    assert summary["calibrated_contexts"] == 1


def test_calibration_summary_dedupes_by_context_keeping_latest(tmp_path: Path):
    for name, sessions in (("old", 4), ("new", 6)):
        batch = tmp_path / name / "BATCH_STATUS.json"
        batch.parent.mkdir(parents=True)
        batch.write_text(
            json.dumps(
                {
                    "track": "Fuji Speedway",
                    "track_layout": "Fuji Speedway",
                    "vehicle_variant": "LMP2_ELMS",
                    "batch_id": name,
                    "steps": {
                        "vehicle_context_selection": {"session_count": sessions},
                        "human_labels": {"labeled_pairs": 0, "queue_pairs": 24},
                        "evaluation_readiness": {"status": "NO_EVALUATION"},
                    },
                    "matcher": {"status": "NO_CALIBRATION_FOR_CONTEXT"},
                }
            ),
            encoding="utf-8",
        )

    summary = load_calibration_summary(base_dir=tmp_path)

    assert len(summary["rows"]) == 1
    assert summary["rows"][0]["sessions"] == 6
    assert summary["rows"][0]["batch_id"] == "new"


def test_calibration_summary_prefers_registry_status_over_snapshot(tmp_path: Path):
    batch = tmp_path / "monza" / "BATCH_STATUS.json"
    batch.parent.mkdir(parents=True)
    batch.write_text(
        json.dumps(
            {
                "track": "Autodromo Nazionale Monza",
                "track_layout": "Autodromo Nazionale Monza",
                "vehicle_variant": "HYPER",
                "batch_id": "aa020d588d",
                "steps": {
                    "vehicle_context_selection": {"session_count": 6},
                    "human_labels": {"labeled_pairs": 24, "queue_pairs": 24},
                    "evaluation_readiness": {"status": "WARNING_EMPTY"},
                },
                "matcher": {"status": "NO_CALIBRATION_FOR_CONTEXT"},
            }
        ),
        encoding="utf-8",
    )

    summary = load_calibration_summary(base_dir=tmp_path)

    row = summary["rows"][0]
    assert row["matcher_status"] == "CALIBRATED_PROVISIONAL_LOW_EVIDENCE"
    assert row["legacy_status_refreshed"] is True


def test_gui_entry_points_and_documentation_are_present():
    root = Path(__file__).resolve().parents[1]
    assert (root / "RaceEngineer.pyw").is_file()
    assert (root / "launch_race_engineer_gui.cmd").is_file()
    for relative in ("AGENTS.md", "PROJECT_CONTEXT.md", "PROJECT_STATUS.md", "README.md"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "race_engineer_gui.py" in source or "RACE_ENGINEER_GUI_V1_11.md" in source
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_11.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_17.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_16.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_15.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_14.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_13.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_10.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_9.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_8.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_7.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_6.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_5.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_0.md").is_file()
    assert "analyze_telemetry_file.py" in (
        root / "docs" / "RACE_ENGINEER_GUI_V1_0.md"
    ).read_text(encoding="utf-8")
