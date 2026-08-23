from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from race_engineer_ui_model import (
    _plan_text,
    discover_sessions,
    filter_sessions,
    format_lap_time,
    load_session_detail,
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


def test_history_only_session_is_not_presented_as_debrief_ready(tmp_path: Path):
    make_session(tmp_path, "session-history", llm=False)

    sessions, _ = discover_sessions(tmp_path / "runs")

    assert sessions[0].status == "HISTORY_READY"
    assert sessions[0].debrief_path is None
    assert sessions[0].has_validated_debrief is False


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
    assert "llm_validator" in detail.pipeline_text


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
    assert "deepseek / deepseek-v4-pro" in detail.historical_comparison_text
    assert "Observación histórica validada" in detail.historical_comparison_text
    assert "No autoriza acciones" in detail.historical_comparison_text
    assert str(raw) in detail.pipeline_text
    assert str(llm) in detail.pipeline_text


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


def test_gui_entry_points_and_documentation_are_present():
    root = Path(__file__).resolve().parents[1]
    assert (root / "RaceEngineer.pyw").is_file()
    assert (root / "launch_race_engineer_gui.cmd").is_file()
    for relative in ("AGENTS.md", "PROJECT_CONTEXT.md", "PROJECT_STATUS.md", "README.md"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "race_engineer_gui.py" in source or "RACE_ENGINEER_GUI_V1_9.md" in source
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_9.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_8.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_7.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_6.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_5.md").is_file()
    assert (root / "docs" / "RACE_ENGINEER_GUI_V1_0.md").is_file()
    assert "analyze_telemetry_file.py" in (
        root / "docs" / "RACE_ENGINEER_GUI_V1_0.md"
    ).read_text(encoding="utf-8")
