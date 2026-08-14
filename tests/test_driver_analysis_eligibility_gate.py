from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    # episode_pair_features imports duckdb at module import time.
    # These tests exercise SQL construction only and therefore use
    # a harmless stub instead of requiring a real DuckDB runtime.
    sys.modules.setdefault(
        "duckdb",
        types.SimpleNamespace(),
    )

    path = ROOT / "episode_pair_features.py"

    spec = importlib.util.spec_from_file_location(
        "episode_pair_features_eligibility_test_target",
        path,
    )

    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        return FakeResult(self.rows)


def episode_row():
    # Mirrors the SELECT order in load_episodes().
    return (
        101,                 # episode_pk
        1,                   # session_id
        10,                  # comparison_id
        1,                   # episode_id
        1,                   # python_global_rank
        "Spa",               # track
        "Q",                 # session_type
        "2026-08-10",        # timestamp_utc
        6973.0,              # reference_distance_m
        "LMP2",              # vehicle_family
        "LMP2_ELMS",         # vehicle_variant
        "LMP2_ELMS",         # car_class_raw
        "IDEC Sport #18",    # car_name_raw
        "lmu_metadata",      # vehicle_identity_source
        True,                # vehicle_supported_domain
        "Light Clouds",      # weather_conditions
        "setup-effective",   # setup_sha256
        "setup-raw",         # setup_raw_sha256
        True,                # setup_available
        "Qualify",           # lmu_session_type
        "Spa",               # lmu_track_name
        "Spa",               # lmu_track_layout
        4,                   # reference_lap
        3,                   # comparison_lap
        1,                   # driver_analysis_priority_rank
        2500.0,              # start_distance_m
        2600.0,              # end_distance_m
        2550.0,              # center_distance_m
        100.0,               # length_m
        0.35,                # start_lap_fraction
        0.37,                # end_lap_fraction
        0.36,                # center_lap_fraction
        0.2,                 # action_time_loss_s
        "strong",            # evidence_strength
        False,               # has_speed_propagation
    )


def test_load_episodes_requires_recommended_comparisons():
    module = load_module()
    connection = FakeConnection([episode_row()])

    episodes = module.load_episodes(connection)

    assert len(episodes) == 1
    assert (
        "c.recommended_for_driver_analysis IS TRUE"
        in connection.sql
    )


def test_eligibility_gate_combines_with_track_and_vehicle_variant():
    module = load_module()
    connection = FakeConnection([episode_row()])

    module.load_episodes(
        connection,
        track="Spa",
        vehicle_variant="LMP2_ELMS",
    )

    normalized_sql = " ".join(connection.sql.split())

    assert (
        "WHERE c.recommended_for_driver_analysis IS TRUE "
        "AND s.track = ? AND s.vehicle_variant = ?"
        in normalized_sql
    )

    assert connection.params == [
        "Spa",
        "LMP2_ELMS",
    ]
