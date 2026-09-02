"""Fail-closed deterministic track-profile discovery for debrief localization."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import unicodedata


VALID_TRACK_PROFILE_STATUSES = {
    "VALIDATED_MULTI_SESSION",
    "VALIDATED",
}


def normalize_track_identity(value):
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value).strip().lower())
    normalized = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def load_track_location_module(base_dir):
    module_path = os.path.join(base_dir, "track_location.py")
    if not os.path.isfile(module_path):
        return None, {"status": "MODULE_NOT_FOUND", "module_path": module_path}
    try:
        spec = importlib.util.spec_from_file_location(
            "race_engineer_deterministic_track_location", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("No se pudo crear spec para track_location.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "resolve_interval"):
            raise RuntimeError("track_location.py no expone resolve_interval()")
        return module, None
    except Exception as exc:
        return None, {
            "status": "MODULE_LOAD_ERROR",
            "module_path": module_path,
            "error": str(exc),
        }


def track_profile_candidate_paths(base_dir):
    paths = []
    profile_dir = os.path.join(base_dir, "track_profiles")
    if os.path.isdir(profile_dir):
        for filename in sorted(os.listdir(profile_dir)):
            if filename.lower().endswith(".json"):
                paths.append(os.path.join(profile_dir, filename))
    for filename in sorted(os.listdir(base_dir)):
        lower = filename.lower()
        if (
            lower.endswith(".json")
            and "profile" in lower
            and "validation" not in lower
        ):
            path = os.path.join(base_dir, filename)
            if path not in paths:
                paths.append(path)
    return paths


def load_track_location_context(metadata, *, base_dir):
    track = metadata.get("track") if isinstance(metadata, dict) else None
    layout = metadata.get("track_layout") if isinstance(metadata, dict) else None
    track_key = normalize_track_identity(track)
    if not track_key:
        return {
            "status": "NO_TRACK_METADATA",
            "track": track,
            "profile": None,
            "profile_path": None,
            "resolver": None,
        }
    module, module_error = load_track_location_module(base_dir)
    if module is None:
        return {
            **(module_error or {"status": "MODULE_NOT_AVAILABLE"}),
            "track": track,
            "profile": None,
            "profile_path": None,
            "resolver": None,
        }
    matches = []
    for path in track_profile_candidate_paths(base_dir):
        try:
            with open(path, "r", encoding="utf-8") as file:
                profile = json.load(file)
        except Exception:
            continue
        if not isinstance(profile, dict) or not isinstance(profile.get("turns"), list):
            continue
        if normalize_track_identity(profile.get("track")) != track_key:
            continue
        status = str(profile.get("status", "")).strip().upper()
        if status not in VALID_TRACK_PROFILE_STATUSES:
            continue
        profile_layout = profile.get("layout")
        if (
            layout
            and profile_layout
            and normalize_track_identity(layout)
            != normalize_track_identity(profile_layout)
        ):
            continue
        matches.append((str(profile.get("profile_id", "")), path, profile))
    if not matches:
        return {
            "status": "NO_VALIDATED_PROFILE",
            "track": track,
            "profile": None,
            "profile_path": None,
            "resolver": module.resolve_interval,
        }
    matches.sort(key=lambda item: item[0])
    profile_id, path, profile = matches[-1]
    return {
        "status": "ACTIVE",
        "track": track,
        "profile_id": profile_id,
        "profile_status": profile.get("status"),
        "profile_path": path,
        "numbering_scheme": (profile.get("calibration", {}) or {}).get(
            "numbering_scheme"
        ),
        "profile": profile,
        "resolver": module.resolve_interval,
    }
