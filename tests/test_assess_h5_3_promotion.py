from __future__ import annotations

import hashlib
import json
from pathlib import Path

from assess_h5_3_promotion import assess


def _context(
    track: str,
    sign: str,
    **overrides,
) -> dict:
    context = {
        "track": track,
        "track_layout": track,
        "vehicle_variant": "LMP2_ELMS",
        "delta_sign": sign,
        "raw_telemetry_resolved": True,
        "track_profile_localized": True,
        "h4_compatible": True,
        "h5_2_validated": True,
        "h5_3a_candidates_available": True,
        "h5_3b_labels_validated": True,
        "h5_3c_selection_validated": True,
        "h5_3d_render_validated": True,
        "h5_3e_validation_pass": True,
        "human_review_documented": True,
        "historical_actions_authorized": False,
    }
    context.update(overrides)
    return context


def _scenario(name: str, flag: str) -> dict:
    return {
        "track": "Caso especial",
        "scenario": name,
        flag: False,
        "historical_actions_authorized": False,
    }


def _full_manifest() -> dict:
    return {
        "metadata": {"schema_version": "1.0", "assess_version": "0.1"},
        "contexts": [
            _context("Fuji Speedway", "current_slower"),
            _context("Autodromo Enzo e Dino Ferrari", "current_slower"),
            _context("Autódromo José Carlos Pace", "current_faster"),
            _context("Autodromo Nazionale Monza", "current_faster"),
            _scenario("unavailable_raw_telemetry", "raw_telemetry_resolved"),
            _scenario(
                "missing_or_invalid_track_profile",
                "track_profile_localized",
            ),
            _scenario("incompatible_context_rejected", "h4_compatible"),
        ],
    }


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_full_manifest_is_ready(tmp_path: Path):
    report = assess(_write_manifest(tmp_path, _full_manifest()))

    assert report["verdict"] == "PROMOTION_READY"
    assert report["unmet"] == []
    assert report["requirements"]["required_tracks_covered"] is True
    assert report["requirements"]["both_delta_signs_covered"] is True


def test_missing_track_is_not_authorized(tmp_path: Path):
    manifest = _full_manifest()
    manifest["contexts"] = [
        context
        for context in manifest["contexts"]
        if context.get("track") != "Fuji Speedway"
    ]
    report = assess(_write_manifest(tmp_path, manifest))

    assert report["verdict"] == "PROMOTION_NOT_AUTHORIZED"
    assert "Fuji Speedway" in report["coverage"]["missing_tracks"]


def test_missing_delta_sign_is_not_authorized(tmp_path: Path):
    manifest = _full_manifest()
    for context in manifest["contexts"]:
        if context.get("delta_sign") == "current_faster":
            context["delta_sign"] = "current_slower"
    report = assess(_write_manifest(tmp_path, manifest))

    assert report["verdict"] == "PROMOTION_NOT_AUTHORIZED"
    assert "current_faster" in report["coverage"]["missing_delta_signs"]


def test_missing_scenario_is_not_authorized(tmp_path: Path):
    manifest = _full_manifest()
    manifest["contexts"] = [
        context
        for context in manifest["contexts"]
        if context.get("scenario") is None
    ]
    report = assess(_write_manifest(tmp_path, manifest))

    assert report["verdict"] == "PROMOTION_NOT_AUTHORIZED"
    assert any("falta escenario registrado" in item for item in report["unmet"])


def test_unsafe_authority_change_is_rejected(tmp_path: Path):
    manifest = _full_manifest()
    manifest["contexts"][0]["historical_actions_authorized"] = True
    report = assess(_write_manifest(tmp_path, manifest))

    assert report["verdict"] == "PROMOTION_NOT_AUTHORIZED"
    assert any("autoriza acciones históricas" in item for item in report["unmet"])


def test_missing_human_review_is_not_authorized(tmp_path: Path):
    manifest = _full_manifest()
    manifest["contexts"][0]["human_review_documented"] = False
    report = assess(_write_manifest(tmp_path, manifest))

    assert report["verdict"] == "PROMOTION_NOT_AUTHORIZED"
    assert any("human_review_documented" in item for item in report["unmet"])


def test_output_is_byte_stable_for_same_inputs(tmp_path: Path):
    path = _write_manifest(tmp_path, _full_manifest())

    first = json.dumps(assess(path), ensure_ascii=False, sort_keys=True)
    second = json.dumps(assess(path), ensure_ascii=False, sort_keys=True)

    assert first == second


def test_assess_aliases_match_versioned_sources():
    root = Path(__file__).resolve().parents[1]
    alias_hash = hashlib.sha256(
        (root / "assess_h5_3_promotion.py").read_bytes()
    ).digest()
    source_hash = hashlib.sha256(
        (root / "assess_h5_3_promotion_v0_1.py").read_bytes()
    ).digest()
    assert alias_hash == source_hash
