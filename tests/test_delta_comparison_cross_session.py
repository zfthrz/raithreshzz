from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from delta_comparison import DeltaComparison


class FakeLapAnalyzer:
    def __init__(self, *, lap: int, duration: float, speed_kmh: float):
        self.lap = lap
        self.duration = duration
        self.speed_kmh = speed_kmh
        self.requested_laps: list[int] = []

    def get_lap_data(self, lap_number: int) -> pd.DataFrame:
        self.requested_laps.append(lap_number)
        if lap_number != self.lap:
            raise ValueError(f"unexpected lap {lap_number}")
        distance = np.linspace(0.0, 100.0, 101)
        return pd.DataFrame(
            {
                "gps_time": np.linspace(0.0, self.duration, 101),
                "Lap Dist": distance,
                "Ground Speed": np.full(101, self.speed_kmh),
                "Engine RPM": np.full(101, 7000.0),
                "Throttle Pos": np.full(101, 80.0),
                "Brake Pos": np.zeros(101),
                "Steering Pos": np.zeros(101),
            }
        )

    def lap_summary(self, lap_number: int) -> dict[str, float | int]:
        if lap_number != self.lap:
            raise ValueError(f"unexpected lap {lap_number}")
        return {"lap": lap_number, "duration": self.duration}


def test_compare_can_use_independent_lap_analyzers():
    historical = FakeLapAnalyzer(lap=8, duration=90.98, speed_kmh=180.0)
    current = FakeLapAnalyzer(lap=5, duration=92.26, speed_kmh=175.0)

    comparison = DeltaComparison(historical, current).compare(8, 5)

    assert historical.requested_laps == [8]
    assert current.requested_laps == [5]
    assert comparison.iloc[-1]["time_delta"] == pytest.approx(1.28)


def test_single_analyzer_mode_remains_backward_compatible():
    analyzer = FakeLapAnalyzer(lap=3, duration=95.0, speed_kmh=180.0)
    comparison = DeltaComparison(analyzer)

    assert comparison.comparison_laps is analyzer
