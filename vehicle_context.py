from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any



VEHICLE_CONTEXT_SCHEMA_VERSION = "1.0"
SUPPORTED_VEHICLE_FAMILIES = {
    "GT3",
    "GTE",
    "LMP3",
    "LMP2",
    "HYPERCAR",
}

LMU_METADATA_KEYS = (
    "RecordingTime",
    "SessionType",
    "TrackName",
    "TrackLayout",
    "WeatherConditions",
    "CarName",
    "CarClass",
    "CarSetup",
)


def normalize_token(value: str | None) -> str | None:
    if value is None:
        return None

    text = str(value).strip().upper()
    if not text:
        return None

    text = re.sub(r"[^A-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or None


def classify_vehicle_class(
    car_class_raw: str | None,
    car_name_raw: str | None = None,
) -> dict[str, Any]:
    raw = None if car_class_raw is None else str(car_class_raw).strip()
    name = None if car_name_raw is None else str(car_name_raw).strip()
    token = normalize_token(raw)

    family = None
    variant = None

    if token == "LMP2_ELMS":
        family = "LMP2"
        variant = "LMP2_ELMS"
    elif token == "LMP2":
        family = "LMP2"
        variant = "LMP2_WEC"
    elif token and "LMP3" in token:
        family = "LMP3"
        variant = token
    elif token and "GT3" in token:
        family = "GT3"
        variant = token
    elif token and "GTE" in token:
        family = "GTE"
        variant = token
    elif token and (
        "HYPER" in token
        or "LMDH" in token
        or token == "LMH"
        or token.startswith("LMH_")
    ):
        family = "HYPERCAR"
        variant = token

    supported = family in SUPPORTED_VEHICLE_FAMILIES

    return {
        "schema_version": VEHICLE_CONTEXT_SCHEMA_VERSION,
        "family": family,
        "variant": variant,
        "car_class_raw": raw or None,
        "car_name_raw": name or None,
        "supported_domain": bool(supported),
        "identity_source": "lmu_metadata" if raw else None,
    }


def canonical_json_sha256(value: Any) -> str:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_setup_sha256(raw_setup: str | None) -> str | None:
    if not raw_setup:
        return None

    try:
        parsed = json.loads(raw_setup)
    except Exception:
        return hashlib.sha256(
            str(raw_setup).strip().encode("utf-8")
        ).hexdigest()

    return canonical_json_sha256(parsed)


def effective_setup_payload(raw_setup: str | None) -> dict[str, Any] | None:
    if not raw_setup:
        return None

    try:
        parsed = json.loads(raw_setup)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None

    effective: dict[str, Any] = {}

    for key, entry in parsed.items():
        if not isinstance(key, str):
            continue

        if not (
            key.startswith("VM_")
            or key.startswith("WM_")
        ):
            continue

        if not isinstance(entry, dict):
            continue

        if entry.get("available") is False:
            continue

        effective[key] = {
            "value": entry.get("value"),
            "stringValue": entry.get("stringValue"),
        }

    return effective


def effective_setup_sha256(raw_setup: str | None) -> str | None:
    payload = effective_setup_payload(raw_setup)
    if payload is None:
        return None
    return canonical_json_sha256(payload)


def read_lmu_metadata(db_path: str | Path) -> dict[str, str]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb no está instalado."
        ) from exc

    path = str(Path(db_path).resolve())
    connection = duckdb.connect(path, read_only=True)

    try:
        table_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = 'metadata'
            """
        ).fetchone()[0]

        if not table_count:
            return {}

        placeholders = ", ".join("?" for _ in LMU_METADATA_KEYS)
        rows = connection.execute(
            f"""
            SELECT key, value
            FROM metadata
            WHERE key IN ({placeholders})
            """,
            list(LMU_METADATA_KEYS),
        ).fetchall()
    finally:
        connection.close()

    return {
        str(key): "" if value is None else str(value)
        for key, value in rows
    }


def extract_lmu_context_from_duckdb(
    db_path: str | Path,
) -> dict[str, Any]:
    metadata = read_lmu_metadata(db_path)

    vehicle = classify_vehicle_class(
        metadata.get("CarClass"),
        metadata.get("CarName"),
    )

    raw_setup = metadata.get("CarSetup")
    setup_effective_hash = effective_setup_sha256(raw_setup)
    setup_raw_hash = raw_setup_sha256(raw_setup)

    return {
        "metadata_available": bool(metadata),
        "vehicle_identity": vehicle,
        "session_context": {
            "schema_version": VEHICLE_CONTEXT_SCHEMA_VERSION,
            "lmu_track_name": metadata.get("TrackName") or None,
            "lmu_track_layout": metadata.get("TrackLayout") or None,
            "lmu_session_type": metadata.get("SessionType") or None,
            "recording_time": metadata.get("RecordingTime") or None,
            "weather_conditions": metadata.get("WeatherConditions") or None,
            "setup_available": bool(raw_setup),
            "setup_sha256": setup_effective_hash,
            "setup_raw_sha256": setup_raw_hash,
            "setup_hash_basis": (
                "effective_current_values"
                if setup_effective_hash
                else None
            ),
        },
    }
