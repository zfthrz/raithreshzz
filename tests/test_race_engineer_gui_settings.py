from pathlib import Path

import pytest

from race_engineer_gui_settings import (
    GuiSettings,
    backend_environment,
    backend_model_label,
    load_settings,
    save_settings,
)


def test_missing_settings_use_safe_defaults(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("LLAMACPP_MODEL", raising=False)
    monkeypatch.delenv("LLAMACPP_API_URL", raising=False)
    settings = load_settings(tmp_path / "missing.json")
    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.llamacpp_model == "qwen3-14b"
    assert backend_model_label(settings, "ollama") == "ingenierov3"


def test_missing_settings_preserve_existing_backend_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODEL", "qwen3.6-35b-a3b-iq2m")
    monkeypatch.setenv("LLAMACPP_API_URL", "http://localhost:8081/v1/chat/completions")

    settings = load_settings(tmp_path / "missing.json")

    assert settings.llamacpp_model == "qwen3.6-35b-a3b-iq2m"
    assert settings.llamacpp_api_url.endswith("8081/v1/chat/completions")


def test_settings_round_trip_without_api_keys(tmp_path: Path):
    path = tmp_path / "settings.json"
    expected = GuiSettings(
        deepseek_model="deepseek-v4-flash",
        llamacpp_model="qwen3.6-35b-a3b-iq2m",
        llamacpp_api_url="http://127.0.0.1:8080/v1/chat/completions",
    )

    saved = save_settings(path, expected)

    assert load_settings(path) == saved
    assert "API_KEY" not in path.read_text(encoding="utf-8")
    assert backend_environment(saved, "llamacpp") == {
        "LLAMACPP_MODEL": "qwen3.6-35b-a3b-iq2m",
        "LLAMACPP_API_URL": "http://127.0.0.1:8080/v1/chat/completions",
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:8080/v1/chat/completions",
        "file:///tmp/server",
        "http://localhost/v1/chat/completions",
        "http://localhost:8080",
    ],
)
def test_llamacpp_url_must_be_a_local_endpoint(tmp_path: Path, url: str):
    with pytest.raises(ValueError, match="llama.cpp"):
        save_settings(tmp_path / "settings.json", GuiSettings(llamacpp_api_url=url))


def test_unknown_backend_fails_closed():
    with pytest.raises(ValueError, match="Backend no soportado"):
        backend_environment(GuiSettings(), "unknown")
