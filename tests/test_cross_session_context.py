from __future__ import annotations

import json
from pathlib import Path

import pytest

from cross_session_context import resolve_duckdb


class TestResolveDuckdb:
    """Tests for resolve_duckdb() covering the absolute-path priority fix.

    Priority order validated:
      1. Exact absolute source_database_path if it exists
      2. telemetry_dir / basename(source_database_path)
      3. telemetry_dir / stem(source_json_path) + ".duckdb"
      4. None if no candidate found
    """

    def test_absolute_source_database_path_exists(self, tmp_path: Path):
        """Test 1: absolute source_database_path exists -> returned directly."""
        # Simulates a Steam UserData/Telemetry DuckDB that exists at the
        # recorded provenance path.
        duckdb_path = tmp_path / "Steam" / "Telemetry" / "session.duckdb"
        duckdb_path.parent.mkdir(parents=True)
        duckdb_path.touch()

        result, attempts = resolve_duckdb(
            tmp_path,  # telemetry_dir (not used for step 1)
            str(duckdb_path),
            None,
        )
        assert result == duckdb_path.resolve(), (
            f"Expected {duckdb_path.resolve()}, got {result}"
        )
        assert attempts == [], "No fallbacks attempted when step 1 succeeds"

    def test_absolute_missing_then_telemetria_basename_fallback(
        self, tmp_path: Path
    ):
        """Test 2: absolute path missing -> telemetry_dir basename fallback."""
        # File exists only under telemetria/ with the same basename.
        duckdb_path = tmp_path / "telemetria" / "session.duckdb"
        duckdb_path.parent.mkdir(parents=True)
        duckdb_path.touch()

        missing_path = (
            tmp_path / "Steam" / "Telemetry" / "session.duckdb"
        )

        result, attempts = resolve_duckdb(
            tmp_path / "telemetria",
            str(missing_path),
            None,
        )
        assert result == duckdb_path.resolve(), (
            f"Expected fallback to {duckdb_path.resolve()}, got {result}"
        )
        # Should list both the missing absolute path and the fallback
        assert str(missing_path) in attempts
        assert str(duckdb_path) in attempts

    def test_source_path_null_json_stem_fallback(self, tmp_path: Path):
        """Test 3: source_database_path is None/null -> JSON-stem fallback."""
        # Simulates legacy sessions where only source_json_path is recorded.
        duckdb_path = tmp_path / "telemetria" / "session_analysis.duckdb"
        duckdb_path.parent.mkdir(parents=True)
        duckdb_path.touch()

        json_path = str(tmp_path / "results" / "session_analysis.json")

        result, attempts = resolve_duckdb(
            tmp_path / "telemetria",
            None,
            json_path,
        )
        assert result == duckdb_path.resolve(), (
            f"Expected JSON-stem fallback to {duckdb_path.resolve()}, got {result}"
        )
        assert str(duckdb_path) in attempts

    def test_all_paths_missing_returns_none(self, tmp_path: Path):
        """Test 4: all paths missing -> None."""
        result, attempts = resolve_duckdb(
            tmp_path / "telemetria",
            str(tmp_path / "nonexistent" / "session.duckdb"),
            str(tmp_path / "nonexistent" / "analysis.json"),
        )
        assert result is None
        # Step 1: missing absolute + telemetry_dir basename fallback
        # Step 3: JSON-stem fallback
        assert len(attempts) == 3
        assert str(tmp_path / "nonexistent" / "session.duckdb") in attempts
        assert str(tmp_path / "telemetria" / "session.duckdb") in attempts
        assert str(tmp_path / "telemetria" / "analysis.duckdb") in attempts

    def test_historical_telemetria_behavior_unchanged(self, tmp_path: Path):
        """Test 5: historical telemetria paths remain unchanged."""
        # Historical sessions store DuckDB in telemetria/ with a relative
        # source_database_path. This must continue to resolve.
        duckdb_path = tmp_path / "telemetria" / "Monza_2026-08-10.duckdb"
        duckdb_path.parent.mkdir(parents=True)
        duckdb_path.touch()

        result, attempts = resolve_duckdb(
            tmp_path / "telemetria",
            "Monza_2026-08-10.duckdb",  # relative path, exists under telemetria
            None,
        )
        # Step 1 checks is_file() on the relative path - it's not a file
        # in the cwd, so it falls through to step 2 which tries
        # telemetry_dir / basename(...) which finds it.
        assert result == duckdb_path.resolve(), (
            f"Expected {duckdb_path.resolve()}, got {result}"
        )

    def test_relative_source_database_path_no_cwd_resolution(self):
        """Test 6: relative source_database_path that doesn't exist -> no cwd resolution."""
        # Ensure resolve_duckdb does NOT accidentally resolve a relative path
        # against the current working directory.
        result, attempts = resolve_duckdb(
            Path("telemetria"),
            "some_random_file.duckdb",  # relative, doesn't exist
            None,
        )
        assert result is None, (
            "Relative missing path should not resolve against cwd"
        )
        # Step 1: the relative path itself (not a file in cwd)
        # Step 2: telemetry_dir / basename fallback
        assert len(attempts) == 2
        assert "some_random_file.duckdb" in attempts
        assert "telemetria\\some_random_file.duckdb" in attempts

    def test_path_identity_provenance_deterministic(
        self, tmp_path: Path
    ):
        """Test 7: path identity/provenance is deterministic."""
        # The same source_database_path must always resolve to the same
        # canonical path. No randomness, no timestamp guessing.
        duckdb_path = tmp_path / "Steam" / "Telemetry" / "session.duckdb"
        duckdb_path.parent.mkdir(parents=True)
        duckdb_path.touch()

        result1, _ = resolve_duckdb(
            tmp_path,
            str(duckdb_path),
            None,
        )
        result2, _ = resolve_duckdb(
            tmp_path,
            str(duckdb_path),
            None,
        )
        assert result1 == result2, "Path resolution must be deterministic"
        assert result1 == duckdb_path.resolve()
