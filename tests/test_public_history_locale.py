import inspect
from types import SimpleNamespace

from race_engineer_history_gui import HistoryBrowser, _flag_text, open_history_browser
from race_engineer_gui import RaceEngineerApp


def _lap(**overrides):
    values = {
        "is_reference": False,
        "is_valid": False,
        "is_discarded": False,
        "is_ignored_initial": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_history_lap_flags_are_fully_localized():
    lap = _lap(is_reference=True, is_valid=True, is_ignored_initial=True)
    assert _flag_text(lap, "es") == "REFERENCIA, válida, inicial ignorada"
    assert _flag_text(lap, "en") == "REFERENCE, valid, ignored initial lap"
    assert _flag_text(_lap(), "en") == "unclassified"


def test_history_dynamic_states_and_details_have_english_variants():
    init_source = inspect.getsource(HistoryBrowser.__init__)
    filter_source = inspect.getsource(HistoryBrowser._apply_filter)
    detail_source = inspect.getsource(HistoryBrowser._show)
    for expected in (
        "Search:",
        "Loading History…",
        "Select a historical session",
        "Vehicle",
        "Reference",
    ):
        assert expected in init_source
    assert "No sessions match this filter" in filter_source
    for expected in (
        "Date:",
        "Context:",
        "Vehicle:",
        "Session:",
        "Reference: lap",
        "Valid laps:",
        "Stored laps:",
        "Source analysis:",
        "Source DuckDB:",
    ):
        assert expected in detail_source


def test_public_gui_passes_active_language_to_history_window():
    source = inspect.getsource(RaceEngineerApp._open_history)
    assert "language=self.interface_language" in source
    signature = inspect.signature(open_history_browser)
    assert signature.parameters["language"].default == "es"
