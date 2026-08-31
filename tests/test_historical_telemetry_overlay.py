from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from race_engineer_gui import (
    resolve_historical_telemetry_reference,
    select_active_telemetry_reference,
)


def test_h4_source_json_resolves_to_existing_session_duckdb(tmp_path: Path):
    historical_analysis = tmp_path / "historical" / "analysis.json"
    historical_analysis.parent.mkdir()
    historical_analysis.write_text("{}", encoding="utf-8")
    database = tmp_path / "historical.duckdb"
    database.write_bytes(b"placeholder")

    selection = tmp_path / "h4.json"
    selection.write_text(
        json.dumps(
            {
                "selected_historical_reference": {
                    "session_id": 17,
                    "lap": 4,
                    "duration_s": 121.234,
                    "source_json_path": str(historical_analysis),
                }
            }
        ),
        encoding="utf-8",
    )
    sessions = [
        SimpleNamespace(
            analysis_path=historical_analysis,
            database_path=database,
        )
    ]

    resolved = resolve_historical_telemetry_reference(selection, sessions)

    assert resolved is not None
    assert resolved["database_path"] == database.resolve()
    assert resolved["session_id"] == 17
    assert resolved["lap"] == 4
    assert resolved["duration_s"] == 121.234


def test_h4_overlay_resolution_is_fail_soft_without_source(tmp_path: Path):
    selection = tmp_path / "h4.json"
    selection.write_text(
        json.dumps(
            {
                "selected_historical_reference": {
                    "session_id": 17,
                    "lap": 4,
                    "duration_s": 121.234,
                    "source_json_path": str(tmp_path / "missing" / "analysis.json"),
                }
            }
        ),
        encoding="utf-8",
    )

    assert resolve_historical_telemetry_reference(selection, []) is None


def test_active_telemetry_reference_selection_is_mode_specific_and_fail_closed():
    current = SimpleNamespace(database_path=Path("current.duckdb"), lap=3)
    session = SimpleNamespace(database_path=Path("current.duckdb"), lap=1)
    historical = SimpleNamespace(database_path=Path("historical.duckdb"), lap=4)

    assert select_active_telemetry_reference(
        "Referencia sesión", current, session, historical
    ) is session
    assert select_active_telemetry_reference(
        "History H4", current, session, historical
    ) is historical
    assert select_active_telemetry_reference(
        "modo desconocido", current, session, historical
    ) is None


def test_active_telemetry_reference_rejects_current_lap_as_its_own_reference():
    current = SimpleNamespace(database_path=Path("session.duckdb"), lap=3)
    same_lap = SimpleNamespace(database_path=Path("session.duckdb"), lap=3)

    assert select_active_telemetry_reference(
        "Referencia sesión", current, same_lap, None
    ) is None
