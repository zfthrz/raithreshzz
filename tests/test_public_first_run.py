from pathlib import Path

from public_first_run import (
    PublicPreferences,
    load_public_preferences,
    save_public_preferences,
    telemetry_picker_directory,
)


def test_public_preferences_round_trip_unicode_telemetry_path(tmp_path):
    destination = tmp_path / "preferencias.json"
    telemetry = tmp_path / "Sesiones José" / "Telemetría larga"
    telemetry.mkdir(parents=True)

    save_public_preferences(
        PublicPreferences(onboarding_complete=True, telemetry_directory=telemetry),
        destination,
    )

    assert load_public_preferences(destination) == PublicPreferences(
        onboarding_complete=True,
        telemetry_directory=telemetry,
    )
    assert "José" in destination.read_text(encoding="utf-8")


def test_public_preferences_fail_closed_per_field(tmp_path):
    destination = tmp_path / "preferences.json"
    destination.write_text(
        '{"onboarding_complete":"yes","telemetry_directory":"relative/path"}',
        encoding="utf-8",
    )
    assert load_public_preferences(destination) == PublicPreferences()


def test_picker_prefers_saved_existing_directory(tmp_path):
    saved = tmp_path / "with spaces" / "telemetría"
    standard = tmp_path / "standard"
    fallback = tmp_path / "fallback"
    for directory in (saved, standard, fallback):
        directory.mkdir(parents=True)

    assert telemetry_picker_directory(
        PublicPreferences(True, saved),
        standard_lmu_directory=standard,
        fallback_directory=fallback,
    ) == saved


def test_picker_falls_back_when_saved_directory_disappears(tmp_path):
    standard = tmp_path / "standard"
    fallback = tmp_path / "fallback"
    standard.mkdir()
    fallback.mkdir()

    assert telemetry_picker_directory(
        PublicPreferences(True, tmp_path / "missing"),
        standard_lmu_directory=standard,
        fallback_directory=fallback,
    ) == standard


def test_picker_returns_fallback_even_before_it_exists(tmp_path):
    fallback = tmp_path / "future"
    assert telemetry_picker_directory(
        PublicPreferences(),
        standard_lmu_directory=tmp_path / "missing-standard",
        fallback_directory=fallback,
    ) == fallback
