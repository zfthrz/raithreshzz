from __future__ import annotations

import json
import os
from pathlib import Path

import duckdb

from race_engineer_statistics import (
    car_display_name,
    history_statistics_document,
    load_history_statistics,
    main as statistics_main,
)


def write_history(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE sessions (
            session_id BIGINT,
            timestamp_utc VARCHAR,
            track VARCHAR,
            vehicle_family VARCHAR,
            vehicle_variant VARCHAR,
            car_name_raw VARCHAR
        );
        CREATE TABLE laps (
            session_id BIGINT,
            lap INTEGER,
            lap_distance_m DOUBLE,
            is_valid BOOLEAN
        );
        INSERT INTO sessions VALUES
            (1, '2026-07-10T12:00:00Z', 'Spa', 'LMP2', 'LMP2_ELMS', 'Team A #1'),
            (2, '2026-08-11T12:00:00Z', 'Spa', 'LMP2', 'LMP2_WEC', 'Team B #2'),
            (3, '2026-08-20T12:00:00Z', 'Fuji', 'GT3', 'GT3', 'GT Team #3');
        INSERT INTO laps VALUES
            (1, 1, 7000, TRUE),
            (1, 2, 7000, TRUE),
            (1, 3, 1000, FALSE),
            (2, 1, 13600, TRUE),
            (3, 1, 4500, TRUE);
        """
    )
    connection.close()


def test_history_statistics_aggregate_valid_laps_distance_and_months(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)

    result = load_history_statistics(history)

    assert result.overall.session_count == 3
    assert result.overall.valid_lap_count == 4
    assert result.overall.total_distance_km == 32.1
    assert result.overall.favorite_track == "Spa"
    assert result.overall.favorite_category == "LMP2_ELMS"
    assert result.overall.favorite_car == "Oreca 07"
    assert [item.month for item in result.monthly] == ["2026-08", "2026-07"]
    assert result.monthly[0].summary.valid_lap_count == 2
    assert result.monthly[0].summary.total_distance_km == 18.1
    assert result.monthly[1].summary.valid_lap_count == 2
    assert [item.session_id for item in result.sessions] == [3, 2, 1]
    assert result.sessions[0].valid_lap_count == 1
    assert result.sessions[1].total_distance_km == 13.6
    assert [(item.label, item.valid_lap_count) for item in result.track_distribution] == [
        ("Spa", 3),
        ("Fuji", 1),
    ]
    assert result.category_distribution[0].label == "LMP2_ELMS"
    assert result.car_distribution[0].label == "Oreca 07"
    assert result.car_distribution[0].valid_lap_count == 3


def test_lmp2_entries_share_one_car_identity_but_other_classes_fail_closed():
    assert car_display_name("LMP2", "LMP2_ELMS", "IDEC #18") == "Oreca 07"
    assert car_display_name("LMP2", "LMP2_WEC", "DKR #3") == "Oreca 07"
    assert car_display_name("GT3", "GT3", "Manthey #92") == "Manthey #92"
    assert car_display_name("GT3", "GT3", None) == "Auto no identificado"


def test_session_without_timestamp_remains_visible_in_monthly_history(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)
    connection = duckdb.connect(str(history))
    connection.execute(
        "INSERT INTO sessions VALUES (4, NULL, 'Monza', 'GT3', 'GT3', 'Team #4')"
    )
    connection.execute("INSERT INTO laps VALUES (4, 1, 5800, TRUE)")
    connection.close()

    result = load_history_statistics(history)

    assert result.monthly[-1].month == "Sin fecha"
    assert result.monthly[-1].summary.session_count == 1
    assert result.monthly[-1].summary.valid_lap_count == 1


def test_history_statistics_document_is_complete_and_deterministic(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)
    result = load_history_statistics(history)

    document = history_statistics_document(result, generated_from=str(history))
    assert set(document) == {
        "schema_version",
        "generated_from",
        "overall",
        "monthly",
        "sessions",
        "track_distribution",
        "category_distribution",
        "car_distribution",
    }
    assert document["generated_from"] == str(history)
    assert isinstance(document["schema_version"], int)
    assert isinstance(document["overall"]["session_count"], int)
    assert isinstance(document["overall"]["valid_lap_count"], int)
    assert document["overall"]["session_count"] == 3
    assert document["overall"]["valid_lap_count"] == 4
    for session in document["sessions"]:
        assert isinstance(session["session_id"], int)
        assert isinstance(session["valid_lap_count"], int)
    for collection in ("track_distribution", "category_distribution", "car_distribution"):
        for item in document[collection]:
            assert isinstance(item["valid_lap_count"], int)

    first = json.dumps(
        history_statistics_document(load_history_statistics(history), generated_from=str(history)),
        ensure_ascii=False,
    )
    second = json.dumps(
        history_statistics_document(load_history_statistics(history), generated_from=str(history)),
        ensure_ascii=False,
    )
    assert first == second
    assert json.loads(first) == document


def test_distance_rounding_is_applied_only_when_serializing(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)
    connection = duckdb.connect(str(history))
    connection.execute(
        "INSERT INTO sessions VALUES (9, '2026-01-01T00:00:00Z', 'Fuji', 'GT3', 'GT3', 'Team #9')"
    )
    connection.execute("INSERT INTO laps VALUES (9, 1, 123.456789, TRUE)")
    connection.close()

    result = load_history_statistics(history)
    session = next(item for item in result.sessions if item.session_id == 9)
    assert abs(session.total_distance_km - 0.123456789) < 1e-9
    assert session.total_distance_km != 0.123

    document = history_statistics_document(result, generated_from=str(history))
    session_payload = next(item for item in document["sessions"] if item["session_id"] == 9)
    assert session_payload["total_distance_km"] == 0.123
    assert document["overall"]["total_distance_km"] == round(
        result.overall.total_distance_km,
        3,
    )
    fuji = next(item for item in document["track_distribution"] if item["label"] == "Fuji")
    assert fuji["total_distance_km"] == round(4.5 + session.total_distance_km, 3)
    assert result.overall.total_distance_km != document["overall"]["total_distance_km"]


def test_cli_export_writes_json_and_creates_parent_directories(tmp_path: Path):
    history = tmp_path / "history.duckdb"
    write_history(history)
    output = tmp_path / "export" / "nested" / "statistics.json"
    exit_code = statistics_main(["--history-db", str(history), "--output", str(output)])
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["generated_from"] == str(history)
    assert payload["overall"]["session_count"] == 3
    assert payload["overall"]["valid_lap_count"] == 4
    assert payload["overall"]["total_distance_km"] == 32.1
    assert payload["overall"]["favorite_track"] == "Spa"


def test_cli_stdout_export_writes_json_and_creates_no_file(tmp_path: Path, capsys, monkeypatch):
    history = tmp_path / "history.duckdb"
    write_history(history)
    monkeypatch.chdir(tmp_path)

    exit_code = statistics_main(["--history-db", str(history), "--output", "-"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert not out.endswith("\n\n")
    payload = json.loads(out)
    assert payload["schema_version"] == 1
    assert payload["generated_from"] == str(history)
    assert payload["overall"]["session_count"] == 3
    assert payload["overall"]["valid_lap_count"] == 4
    assert not Path("-").exists()


def test_cli_stdout_export_missing_database_reports_only_on_stderr(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)

    exit_code = statistics_main(
        [
            "--history-db",
            str(tmp_path / "missing.duckdb"),
            "--output",
            "-",
        ]
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no se pudo leer" in captured.err
    assert not Path("-").exists()


def test_cli_output_same_as_history_db_is_rejected(tmp_path: Path, capsys, monkeypatch):
    history = tmp_path / "history.duckdb"
    write_history(history)
    monkeypatch.chdir(tmp_path)
    before = history.read_bytes()

    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(history)]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "no puede ser la propia History DB" in captured.err
    assert history.read_bytes() == before
    assert not history.with_name(history.name + ".tmp").exists()


def test_cli_output_same_as_history_db_via_dot_segments_is_rejected(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    history = tmp_path / "history.duckdb"
    write_history(history)
    monkeypatch.chdir(tmp_path)
    before = history.read_bytes()

    for output in (
        history.parent / "." / "history.duckdb",
        history.parent / "sub" / ".." / "history.duckdb",
    ):
        exit_code = statistics_main(
            ["--history-db", str(history), "--output", str(output)]
        )
        captured = capsys.readouterr()
        assert exit_code != 0
        assert captured.out == ""
        assert "no puede ser la propia History DB" in captured.err

    assert history.read_bytes() == before
    assert not history.with_name(history.name + ".tmp").exists()


def test_cli_output_identity_confirmed_by_samefile_is_rejected(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    history = tmp_path / "history.duckdb"
    write_history(history)
    monkeypatch.chdir(tmp_path)
    before = history.read_bytes()

    seen = []

    def spy_samefile(file1, file2):
        seen.append((str(file1), str(file2)))
        return True

    monkeypatch.setattr(os.path, "samefile", spy_samefile)
    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(history)]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "no puede ser la propia History DB" in captured.err
    assert seen, "samefile no se consultó"
    assert history.read_bytes() == before
    assert not history.with_name(history.name + ".tmp").exists()


def test_cli_output_identity_falls_back_when_samefile_raises(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    history = tmp_path / "history.duckdb"
    write_history(history)
    monkeypatch.chdir(tmp_path)
    before = history.read_bytes()

    def boom(_file1, _file2):
        raise OSError("simulado")

    monkeypatch.setattr(os.path, "samefile", boom)
    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(history)]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "no puede ser la propia History DB" in captured.err
    assert history.read_bytes() == before
    assert not history.with_name(history.name + ".tmp").exists()


def test_cli_output_case_alias_is_rejected_without_os_dependency(
    tmp_path: Path,
    capsys,
    monkeypatch,
):
    # Simula un sistema case-insensitive sin depender del SO del test:
    # samefile no aplica y la comparación cae a normcase plegando case.
    history = tmp_path / "HISTORY.duckdb"
    write_history(history)
    monkeypatch.chdir(tmp_path)
    before = history.read_bytes()

    monkeypatch.setattr(os.path, "samefile", lambda _a, _b: False)
    monkeypatch.setattr(os.path, "normcase", str.casefold)

    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(history).lower()]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "no puede ser la propia History DB" in captured.err
    assert history.read_bytes() == before
    assert not history.with_name(history.name + ".tmp").exists()


def test_cli_different_routes_are_not_treated_as_same(tmp_path: Path):
    # Dos destinos distintos: mismo nombre en otra carpeta y nombre distinto.
    history = tmp_path / "hist.duckdb"
    write_history(history)
    before = history.read_bytes()

    other_dir = tmp_path / "alt"
    other_dir.mkdir()
    output_a = other_dir / "hist.duckdb"
    output_b = tmp_path / "stats.json"

    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(output_a)]
    )
    assert exit_code == 0
    assert output_a.exists()

    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(output_b)]
    )
    assert exit_code == 0
    assert output_b.exists()
    # La History no se toca ni se sobreescribe.
    assert history.read_bytes() == before


def test_cli_missing_database_does_not_create_output(tmp_path: Path, capsys):
    output = tmp_path / "statistics.json"
    exit_code = statistics_main(
        [
            "--history-db",
            str(tmp_path / "missing.duckdb"),
            "--output",
            str(output),
        ]
    )
    assert exit_code != 0
    assert not output.exists()
    assert "no se pudo leer" in capsys.readouterr().err


def test_cli_invalid_database_does_not_create_output(tmp_path: Path):
    broken = tmp_path / "broken.duckdb"
    broken.write_text("esto no es una History DB")
    output = tmp_path / "statistics.json"
    exit_code = statistics_main(
        ["--history-db", str(broken), "--output", str(output)]
    )
    assert exit_code != 0
    assert not output.exists()


def test_cli_write_failure_removes_temporary_output(tmp_path: Path, monkeypatch):
    history = tmp_path / "history.duckdb"
    write_history(history)
    output = tmp_path / "statistics.json"

    def fail_replace(_self, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    exit_code = statistics_main(
        ["--history-db", str(history), "--output", str(output)]
    )

    assert exit_code != 0
    assert not output.exists()
    assert not output.with_name(output.name + ".tmp").exists()


def test_cli_default_history_db_is_used_when_omitted(tmp_path: Path, monkeypatch):
    default = tmp_path / "default.duckdb"
    write_history(default)
    monkeypatch.setattr(
        "race_engineer_statistics.history_db_default_path",
        lambda: default,
    )
    output = tmp_path / "statistics.json"
    exit_code = statistics_main(["--output", str(output)])
    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["generated_from"] == str(default)


def test_loader_opens_duckdb_read_only(tmp_path: Path, monkeypatch):
    history = tmp_path / "history.duckdb"
    write_history(history)
    original_connect = duckdb.connect
    captured = []

    def spy_connect(*args, **kwargs):
        captured.append(kwargs.get("read_only"))
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", spy_connect)
    load_history_statistics(history)
    assert captured == [True]
