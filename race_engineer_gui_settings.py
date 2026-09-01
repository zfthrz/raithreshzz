"""Legacy backend settings retained for developer-tool compatibility.

The product GUI no longer imports this module: its debrief runtime is
deterministic and does not expose provider or model selection.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


SETTINGS_SCHEMA_VERSION = 1
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_LLAMACPP_MODEL = "qwen3-14b"
DEFAULT_LLAMACPP_API_URL = "http://localhost:8080/v1/chat/completions"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class GuiSettings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    llamacpp_model: str = DEFAULT_LLAMACPP_MODEL
    llamacpp_api_url: str = DEFAULT_LLAMACPP_API_URL


def default_settings(environ: dict[str, str] | None = None) -> GuiSettings:
    source = os.environ if environ is None else environ
    return validate_settings(
        GuiSettings(
            deepseek_model=source.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
            llamacpp_model=source.get("LLAMACPP_MODEL", DEFAULT_LLAMACPP_MODEL),
            llamacpp_api_url=source.get("LLAMACPP_API_URL", DEFAULT_LLAMACPP_API_URL),
        )
    )


def _clean_model(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 200 or any(ord(character) < 32 for character in text):
        raise ValueError(f"{label} inválido.")
    return text


def _clean_local_url(value: object) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("La URL de llama.cpp debe ser HTTP(S) y apuntar a localhost.")
    if not parsed.port:
        raise ValueError("La URL de llama.cpp debe incluir un puerto.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("La URL de llama.cpp debe incluir el endpoint de chat.")
    return text


def validate_settings(settings: GuiSettings) -> GuiSettings:
    if settings.schema_version != SETTINGS_SCHEMA_VERSION:
        raise ValueError(
            f"Configuración GUI incompatible: schema={settings.schema_version}."
        )
    return GuiSettings(
        deepseek_model=_clean_model(settings.deepseek_model, "Modelo DeepSeek"),
        llamacpp_model=_clean_model(settings.llamacpp_model, "Modelo llama.cpp"),
        llamacpp_api_url=_clean_local_url(settings.llamacpp_api_url),
    )


def load_settings(path: Path) -> GuiSettings:
    settings_path = Path(path)
    if not settings_path.is_file():
        return default_settings()
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("La configuración GUI debe ser un objeto JSON.")
    return validate_settings(
        GuiSettings(
            schema_version=int(payload.get("schema_version", 0)),
            deepseek_model=str(payload.get("deepseek_model", "")),
            llamacpp_model=str(payload.get("llamacpp_model", "")),
            llamacpp_api_url=str(payload.get("llamacpp_api_url", "")),
        )
    )


def save_settings(path: Path, settings: GuiSettings) -> GuiSettings:
    normalized = validate_settings(settings)
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(normalized), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(settings_path)
    return normalized


def backend_environment(settings: GuiSettings, backend: str) -> dict[str, str]:
    normalized = validate_settings(settings)
    if backend == "deepseek":
        return {"DEEPSEEK_MODEL": normalized.deepseek_model}
    if backend == "llamacpp":
        return {
            "LLAMACPP_MODEL": normalized.llamacpp_model,
            "LLAMACPP_API_URL": normalized.llamacpp_api_url,
        }
    if backend == "ollama":
        return {}
    raise ValueError(f"Backend no soportado: {backend}")


def backend_model_label(settings: GuiSettings, backend: str) -> str:
    normalized = validate_settings(settings)
    if backend == "deepseek":
        return normalized.deepseek_model
    if backend == "llamacpp":
        return normalized.llamacpp_model
    if backend == "ollama":
        return "ingenierov3"
    raise ValueError(f"Backend no soportado: {backend}")
