from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from race_engineer_gui import resolve_historical_telemetry_reference


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
