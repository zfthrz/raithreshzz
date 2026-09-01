from __future__ import annotations

import io
import sys
from pathlib import Path

import detect_track_turns


def test_cli_output_is_cp1252_safe(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "track.csv"
    source.write_text(
        "lap_distance_m,x_east_m,y_north_m\n"
        + "".join(
            f"{index * 2},{index},{(index % 10) * (index % 10)}\n"
            for index in range(60)
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    raw_stdout = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(raw_stdout, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "detect_track_turns.py",
            str(source),
            "--turn-count",
            "3",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert detect_track_turns.main() == 0
    cp1252_stdout.flush()
    rendered = raw_stdout.getvalue().decode("cp1252")
    assert "heading_d" in rendered
    assert "peak_kappa" in rendered
    assert "deg" in rendered
    assert (output_dir / "track_turn_candidates.json").exists()
