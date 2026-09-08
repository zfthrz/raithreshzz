from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import runtime_paths
from public_release_contract import DEVELOPMENT_GUI_SECTIONS, PUBLIC_GUI_SECTIONS
from public_runtime import configure_public_runtime, public_data_root
from race_engineer_gui import (
    RaceEngineerApp,
    _complete_public_first_run,
    global_shortcuts,
    primary_sections,
)
from public_first_run import PublicPreferences

ROOT = Path(__file__).resolve().parents[1]


def test_public_runtime_uses_fresh_per_user_paths(tmp_path, monkeypatch):
    environment = {"LOCALAPPDATA": str(tmp_path)}
    root = configure_public_runtime(environment)
    assert root == tmp_path / "RaceEngineer"
    assert environment["RACE_ENGINEER_GENERATED_DIR"] == str(root / "generated")
    assert environment["RACE_ENGINEER_LOCAL_DIR"] == str(root / "local")

    monkeypatch.setenv("RACE_ENGINEER_LOCAL_DIR", environment["RACE_ENGINEER_LOCAL_DIR"])
    assert runtime_paths.history_db_default_path() == root / "local" / "race_engineer_history.duckdb"
    assert not runtime_paths.history_db_default_path().exists()


def test_explicit_public_data_root_supports_portable_qa(tmp_path):
    assert public_data_root({"RACE_ENGINEER_PUBLIC_DATA_DIR": str(tmp_path)}) == tmp_path


def test_frozen_runtime_registers_dedicated_child_executables(tmp_path, monkeypatch):
    environment = {"RACE_ENGINEER_PUBLIC_DATA_DIR": str(tmp_path)}
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "RaceEngineer.exe"))
    configure_public_runtime(environment)
    assert environment["RACE_ENGINEER_ANALYZER_EXECUTABLE"].endswith(
        "RaceEngineerAnalyze.exe"
    )
    assert environment["RACE_ENGINEER_CLI_EXECUTABLE"].endswith("RaceEngineerCLI.exe")
    assert environment["RACE_ENGINEER_WORKER_EXECUTABLE"].endswith(
        "RaceEngineerWorker.exe"
    )


def test_public_surface_has_no_operator_sections_or_shortcuts():
    sections = primary_sections(public_release=True)
    assert sections == PUBLIC_GUI_SECTIONS
    assert not set(sections) & set(DEVELOPMENT_GUI_SECTIONS)
    assert global_shortcuts(public_release=True)[0][0] == "Ctrl+1 … Ctrl+4"
    assert primary_sections(public_release=False)[-3:] == DEVELOPMENT_GUI_SECTIONS


def test_public_layout_and_refresh_guard_operator_initialization():
    layout = inspect.getsource(RaceEngineerApp._build_layout)
    refresh = inspect.getsource(RaceEngineerApp.refresh)
    startup = inspect.getsource(RaceEngineerApp._start_initial_catalog_load)
    assert "for section in self.active_primary_sections" in layout
    assert "if not self.public_release" in layout
    assert 'getattr(self, "public_release", False)' in refresh
    assert 'getattr(self, "public_release", False)' in startup


def test_importing_gui_does_not_import_operator_modules():
    modules = (
        "race_engineer_calibration_gui",
        "race_engineer_h3_materialization_gui",
        "race_engineer_h3_import_gui",
        "race_engineer_h5_3_review_status",
        "race_engineer_scheduler_status",
        "scheduler_queue_actions",
        "track_readiness",
        "h3_automation_status",
    )
    expression = ";".join(
        ["import sys", "import race_engineer_gui"]
        + [f"assert {name!r} not in sys.modules" for name in modules]
    )
    subprocess.run([sys.executable, "-c", expression], cwd=ROOT, check=True)


def test_public_entrypoint_configures_paths_before_importing_gui():
    source = (ROOT / "RaceEngineerPublic.pyw").read_text(encoding="utf-8")
    assert source.index("configure_public_runtime()") < source.index(
        "from race_engineer_gui import main"
    )
    assert "main(public_release=True)" in source


def test_public_entrypoint_list_never_reads_checkout_sessions(tmp_path):
    environment = dict(os.environ)
    environment["RACE_ENGINEER_PUBLIC_DATA_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "RaceEngineerPublic.pyw", "--list"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert not (tmp_path / "local" / "race_engineer_history.duckdb").exists()


def test_completed_public_onboarding_opens_without_prompt(monkeypatch):
    monkeypatch.setattr(
        "race_engineer_gui.load_public_preferences",
        lambda: PublicPreferences(onboarding_complete=True),
    )
    assert _complete_public_first_run(object()) is True


def test_public_onboarding_saves_language_and_unicode_directory(tmp_path, monkeypatch):
    from tkinter import filedialog, messagebox

    telemetry = tmp_path / "Piloto Ñ" / "Telemetría LMU"
    telemetry.mkdir(parents=True)
    saved_languages = []
    saved_preferences = []
    answers = iter((True, True))
    monkeypatch.setattr(
        "race_engineer_gui.load_public_preferences", lambda: PublicPreferences()
    )
    monkeypatch.setattr(
        "race_engineer_gui.save_public_preferences", saved_preferences.append
    )
    monkeypatch.setattr(
        "debrief_language.save_debrief_language", saved_languages.append
    )
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(
        filedialog,
        "askdirectory",
        lambda *args, **kwargs: str(telemetry),
    )

    assert _complete_public_first_run(object()) is True
    assert saved_languages == ["en"]
    assert saved_preferences == [PublicPreferences(True, telemetry)]


def test_public_file_picker_uses_saved_telemetry_directory(tmp_path):
    telemetry = tmp_path / "Piloto Ñ" / "LMU Telemetry"
    telemetry.mkdir(parents=True)
    app = RaceEngineerApp.__new__(RaceEngineerApp)
    app.public_release = True
    app.public_preferences = PublicPreferences(True, telemetry)
    assert app._analysis_picker_directory() == telemetry
