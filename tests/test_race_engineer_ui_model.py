from __future__ import annotations

import json
from pathlib import Path

from race_engineer_ui_model import (
    discover_sessions,
    format_lap_time,
    load_session_detail,
)


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
            }
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


def test_history_only_session_is_not_presented_as_debrief_ready(tmp_path: Path):
    make_session(tmp_path, "session-history", llm=False)

    sessions, _ = discover_sessions(tmp_path / "runs")

    assert sessions[0].status == "HISTORY_READY"
    assert sessions[0].debrief_path is None


def test_detail_reads_debrief_and_authorized_plan(tmp_path: Path):
    make_session(tmp_path, "session-a")
    record = discover_sessions(tmp_path / "runs")[0][0]

    detail = load_session_detail(record)

    assert "Texto validado" in detail.debrief_markdown
    assert "Zona A — T1" in detail.plan_text
    assert "Frená 10 m más tarde" in detail.plan_text
    assert "llm_validator" in detail.pipeline_text


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


def test_lap_time_formatter_is_driver_friendly():
    assert format_lap_time(90.94) == "1:30.940"
    assert format_lap_time(None) == "—"


def test_gui_entry_points_and_documentation_are_present():
    root = Path(__file__).resolve().parents[1]
    assert (root / "RaceEngineer.pyw").is_file()
    assert (root / "launch_race_engineer_gui.cmd").is_file()
    for relative in ("AGENTS.md", "PROJECT_CONTEXT.md", "PROJECT_STATUS.md", "README.md"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "race_engineer_gui.py" in source or "RACE_ENGINEER_GUI_V0_1.md" in source
