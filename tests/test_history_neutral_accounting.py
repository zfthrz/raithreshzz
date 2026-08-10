from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    sys.modules.setdefault(
        "duckdb",
        types.SimpleNamespace(),
    )

    path = ROOT / "validate_history_db.py"
    spec = importlib.util.spec_from_file_location(
        "validate_history_db_neutral_test_target",
        path,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def execute(self, sql):
        self.sql = sql
        return FakeResult(self.rows)


def valid_row():
    # reference=126.36, comparison=127.14 -> delta=0.78
    # net = 1.6738 - 0.8900 + (-0.0038) = 0.7800
    return (
        42,       # comparison_id
        126.36,   # reference_time_s
        127.14,   # comparison_time_s
        0.78,     # comparison_minus_reference_s
        0.78,     # calculated_delta_s
        1.6738,   # gross_loss_s
        0.8900,   # gross_gain_s
        -0.0038,  # neutral_delta_s
        0.7800,   # net_from_components_s
        0.0,      # accounting_error_s
    )


def test_temporal_accounting_includes_neutral_delta():
    module = load_module()
    connection = FakeConnection([valid_row()])
    errors = []

    module.validate_comparison_temporal_math(
        connection,
        errors,
    )

    assert errors == []
    assert "neutral_delta_s" in connection.sql


def test_temporal_accounting_still_rejects_wrong_net():
    module = load_module()
    row = list(valid_row())
    row[8] = 0.7900

    connection = FakeConnection([tuple(row)])
    errors = []

    module.validate_comparison_temporal_math(
        connection,
        errors,
    )

    assert len(errors) == 1
    assert "neutral_delta" in errors[0]
