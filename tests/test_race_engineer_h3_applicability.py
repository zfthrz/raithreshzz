from __future__ import annotations

import json
from pathlib import Path

import duckdb

from race_engineer import h3_applicability
from session_history import initialize_schema


def _analysis(tmp_path: Path, track: str, layout: str, variant: str) -> Path:
    path = tmp_path / "analysis.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "track": track,
                    "track_layout": layout,
                    "vehicle_variant": variant,
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _history(tmp_path: Path) -> Path:
    path = tmp_path / "history.duckdb"
    connection = duckdb.connect(str(path))
    initialize_schema(connection)
    connection.close()
    return path


def test_h3_uncalibrated_context_is_not_applicable(tmp_path: Path):
    analysis = _analysis(
        tmp_path,
        "Paul Ricard Circuit",
        "Paul Ricard Circuit",
        "LMP2_ELMS",
    )

    applicable, reasons = h3_applicability(analysis, _history(tmp_path))

    assert applicable is False
    assert any("sin calibración" in reason for reason in reasons)


def test_h3_calibrated_context_without_pattern_runs(tmp_path: Path):
    analysis = _analysis(
        tmp_path,
        "Autodromo Enzo e Dino Ferrari",
        "Autodromo Enzo e Dino Ferrari",
        "LMP2_ELMS",
    )

    applicable, reasons = h3_applicability(analysis, _history(tmp_path))

    assert applicable is False
    assert any("sin pattern runs" in reason for reason in reasons)


def test_h3_calibrated_context_with_pattern_runs(tmp_path: Path):
    analysis = _analysis(
        tmp_path,
        "Autodromo Enzo e Dino Ferrari",
        "Autodromo Enzo e Dino Ferrari",
        "LMP2_ELMS",
    )
    db = _history(tmp_path)
    connection = duckdb.connect(str(db))
    connection.execute(
        """
        INSERT INTO pattern_runs (
            pattern_run_id, source_patterns_path, source_patterns_sha256,
            source_matches_path, source_matches_sha256, source_bundle_sha256,
            h3_version, matcher_version, persistent_min_independent_sessions,
            track, track_layout, vehicle_variant,
            pattern_count, episode_count, single_observation_count,
            cross_session_repeat_count, persistent_pattern_count,
            conflict_review_required_count, match_edge_count,
            transitively_resolved_ambiguous_pair_count, imported_at_utc,
            metadata_json
        ) VALUES (
            1, 'patterns.json', 'a', 'matches.json', 'b', 'c',
            '0.1', '0.3', 3,
            'Autodromo Enzo e Dino Ferrari', 'Autodromo Enzo e Dino Ferrari',
            'LMP2_ELMS',
            1, 1, 0, 0, 1, 0, 0, 0, '2026-08-24T00:00:00Z', '{}'
        )
        """
    )
    connection.close()

    applicable, reasons = h3_applicability(analysis, db)

    assert applicable is True
    assert any("1 pattern run" in reason for reason in reasons)


def test_h3_missing_analysis_metadata(tmp_path: Path):
    missing = tmp_path / "missing.json"
    applicable, reasons = h3_applicability(missing, _history(tmp_path))
    assert applicable is False
    assert "no disponible" in reasons[0]
