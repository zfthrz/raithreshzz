from __future__ import annotations

from pathlib import Path

from deterministic_debrief_presentation import build_console_presentation


ROOT = Path(__file__).resolve().parents[1]


def test_presentation_module_has_no_backend_import():
    source = (ROOT / "deterministic_debrief_presentation.py").read_text(
        encoding="utf-8"
    )
    assert "llm_analysis" not in source
    assert "deepseek_chat" not in source


def test_console_presentation_identifies_deterministic_runtime(capsys):
    presentation = build_console_presentation(
        model_name="compat-model",
        context_size=32768,
        temperature=0.0,
        usage_summary=lambda: None,
    )
    presentation.start()
    presentation.model_banner()
    presentation.architecture()
    output = capsys.readouterr().out
    assert "DETERMINISTIC DEBRIEF" in output
    assert "Python determinista" in output
    assert "Transporte LLM = inaccesible" in output
