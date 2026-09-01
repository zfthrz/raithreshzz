from __future__ import annotations

from pathlib import Path

import analyze_telemetry_file as launcher


def make_database(tmp_path: Path, *, size: int = 128) -> Path:
    directory = tmp_path / "Telemetry"
    directory.mkdir(parents=True)
    path = directory / "Monza_P_2026.duckdb"
    path.write_bytes(b"x" * size)
    return path.resolve()


def old_enough(path: Path) -> float:
    return path.stat().st_mtime + 601


def test_safe_launcher_runs_history_first_then_deterministic_debrief(tmp_path: Path):
    database = make_database(tmp_path)
    calls: list[tuple[Path, list[str]]] = []

    result = launcher.analyze_selected_file(
        str(database),
        backend="deepseek",
        roots=(database.parent,),
        runner=lambda path, args: calls.append((path, args)),
        lap_counter=lambda path: 3,
        game_running=lambda: False,
        min_size_mib=0,
        min_stable_seconds=600,
        now_seconds=old_enough(database),
    )

    assert result == 0
    assert calls == [
        (database, ["--no-llm"]),
        (database, ["--force-deterministic-debrief"]),
    ]


def test_safe_launcher_blocks_everything_while_game_is_running(tmp_path: Path):
    database = make_database(tmp_path)
    calls: list[Path] = []

    result = launcher.analyze_selected_file(
        str(database),
        backend="deepseek",
        roots=(database.parent,),
        runner=lambda path, args: calls.append(path),
        game_running=lambda: True,
        min_size_mib=0,
        min_stable_seconds=0,
    )

    assert result == 2
    assert calls == []


def test_safe_launcher_blocks_unauthorized_and_history_databases(tmp_path: Path):
    database = make_database(tmp_path)
    other_root = tmp_path / "other"
    other_root.mkdir()

    try:
        launcher.validate_selected_database(
            str(database),
            roots=(other_root,),
            min_size_mib=0,
            min_stable_seconds=0,
        )
    except ValueError as exc:
        assert "fuera" in str(exc)
    else:
        raise AssertionError("una ruta no autorizada fue aceptada")

    history = database.with_name("race_engineer_history.duckdb")
    history.write_bytes(b"history")
    try:
        launcher.validate_selected_database(
            str(history),
            roots=(history.parent,),
            min_size_mib=0,
            min_stable_seconds=0,
        )
    except ValueError as exc:
        assert "History" in str(exc)
    else:
        raise AssertionError("History fue aceptado como telemetría")


def test_safe_launcher_blocks_small_or_recent_database(tmp_path: Path):
    database = make_database(tmp_path)

    try:
        launcher.validate_selected_database(
            str(database),
            roots=(database.parent,),
            min_size_mib=5,
            min_stable_seconds=0,
        )
    except ValueError as exc:
        assert "5 MiB" in str(exc)
    else:
        raise AssertionError("archivo pequeño aceptado")

    try:
        launcher.validate_selected_database(
            str(database),
            roots=(database.parent,),
            min_size_mib=0,
            min_stable_seconds=600,
            now_seconds=database.stat().st_mtime + 100,
        )
    except ValueError as exc:
        assert "estabilidad" in str(exc)
    else:
        raise AssertionError("archivo reciente aceptado")


def test_explicit_override_skips_only_recent_file_wait(tmp_path: Path):
    database = make_database(tmp_path)
    calls: list[tuple[Path, list[str]]] = []

    result = launcher.analyze_selected_file(
        str(database),
        roots=(database.parent,),
        runner=lambda path, args: calls.append((path, args)),
        lap_counter=lambda path: 2,
        game_running=lambda: False,
        min_size_mib=0,
        min_stable_seconds=600,
        now_seconds=database.stat().st_mtime + 1,
        skip_stability_wait=True,
    )

    assert result == 0
    assert calls == [
        (database, ["--no-llm"]),
        (database, ["--force-deterministic-debrief"]),
    ]


def test_safe_launcher_can_generate_debrief_without_llm_access(tmp_path: Path):
    database = make_database(tmp_path)
    calls: list[tuple[Path, list[str]]] = []

    result = launcher.analyze_selected_file(
        str(database),
        roots=(database.parent,),
        runner=lambda path, args: calls.append((path, args)),
        lap_counter=lambda path: 3,
        game_running=lambda: False,
        min_size_mib=0,
        min_stable_seconds=0,
        deterministic_debrief=True,
    )

    assert result == 0
    assert calls == [
        (database, ["--no-llm"]),
        (
            database,
            [
                "--force-deterministic-debrief",
            ],
        ),
    ]


def test_override_never_bypasses_game_running_block(tmp_path: Path):
    database = make_database(tmp_path)
    calls = []

    result = launcher.analyze_selected_file(
        str(database),
        backend="deepseek",
        roots=(database.parent,),
        runner=lambda path, args: calls.append((path, args)),
        game_running=lambda: True,
        min_size_mib=0,
        skip_stability_wait=True,
    )

    assert result == 2
    assert calls == []


def test_override_never_bypasses_minimum_file_size(tmp_path: Path):
    database = make_database(tmp_path)

    try:
        launcher.validate_selected_database(
            str(database),
            roots=(database.parent,),
            min_size_mib=5,
            min_stable_seconds=600,
            skip_stability_wait=True,
        )
    except ValueError as exc:
        assert "5 MiB" in str(exc)
    else:
        raise AssertionError("el override aceptó un archivo menor al tamaño mínimo")


def test_parser_exposes_explicit_stability_override():
    args = launcher.build_parser().parse_args(
        ["session.duckdb", "--skip-stability-wait"]
    )
    assert args.skip_stability_wait is True


def test_parser_exposes_deterministic_debrief_mode():
    args = launcher.build_parser().parse_args(
        ["session.duckdb", "--deterministic-debrief"]
    )
    assert args.deterministic_debrief is True


def test_safe_launcher_withholds_llm_when_valid_laps_are_insufficient(tmp_path: Path):
    database = make_database(tmp_path)
    calls: list[tuple[Path, list[str]]] = []

    result = launcher.analyze_selected_file(
        str(database),
        backend="deepseek",
        roots=(database.parent,),
        runner=lambda path, args: calls.append((path, args)),
        lap_counter=lambda path: 1,
        game_running=lambda: False,
        min_size_mib=0,
        min_stable_seconds=0,
    )

    assert result == 2
    assert calls == [
        (database, ["--no-llm"]),
    ]


def test_context_menu_installer_is_per_user_and_reversible():
    source = (launcher.PROJECT_ROOT / "install_race_engineer_context_menu.ps1").read_text(
        encoding="utf-8"
    )
    assert "HKCU:" in source
    assert "SystemFileAssociations\\.duckdb" in source
    assert "[switch]$Uninstall" in source
    assert "Remove-Item" in source
    assert "HKLM:" not in source
    assert '"Analizar con Race Engineer"' in source
    assert "legacyVerbKeys" in source
    assert "New-Item -Path $ollamaVerbKey" not in source
    assert "New-Item -Path $llamacppVerbKey" not in source


def test_primary_context_menu_cmd_uses_deterministic_product_path():
    source = (
        launcher.PROJECT_ROOT / "race_engineer_context_menu.cmd"
    ).read_text(encoding="utf-8")
    assert "analyze_telemetry_file.py" in source
    assert "--backend" not in source
    assert ".venv\\Scripts\\python.exe" in source


def test_ollama_context_menu_cmd_uses_ollama_backend():
    source = (
        launcher.PROJECT_ROOT / "race_engineer_context_menu_ollama.cmd"
    ).read_text(encoding="utf-8")
    assert "analyze_telemetry_file.py" in source
    assert "--backend ollama" in source
    assert ".venv\\Scripts\\python.exe" in source


def test_llamacpp_context_menu_cmd_uses_llamacpp_backend():
    source = (
        launcher.PROJECT_ROOT / "race_engineer_context_menu_llamacpp.cmd"
    ).read_text(encoding="utf-8")
    assert "analyze_telemetry_file.py" in source
    assert "--backend llamacpp" in source
    assert ".venv\\Scripts\\python.exe" in source
