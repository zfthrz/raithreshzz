from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


VALID_PROFILE_STATUSES = {"VALIDATED", "VALIDATED_MULTI_SESSION"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(document: dict) -> list[str]:
    errors: list[str] = []
    metadata = document.get("metadata") or {}
    if metadata.get("schema_version") != "1.1":
        errors.append("metadata.schema_version inválida")
    if metadata.get("cross_session_version") != "0.2":
        errors.append("metadata.cross_session_version inválida")
    if document.get("status") != "RAW_CROSS_SESSION_COMPARISON_AVAILABLE":
        errors.append("status inválido")

    for key in ("historical_reference", "current_session_reference"):
        reference = document.get(key)
        if not isinstance(reference, dict):
            errors.append(f"{key} ausente")
            continue
        if not isinstance(reference.get("session_id"), int):
            errors.append(f"{key}.session_id inválido")
        if not isinstance(reference.get("lap"), int):
            errors.append(f"{key}.lap inválido")
        if not Path(str(reference.get("source_database") or "")).is_file():
            errors.append(f"{key}.source_database no existe")

    temporal = document.get("temporal_validation") or {}
    if temporal.get("status") != "OK":
        errors.append("temporal_validation.status no es OK")
    error = temporal.get("error_s")
    tolerance = temporal.get("tolerance_s")
    if not isinstance(error, (int, float)) or not isinstance(tolerance, (int, float)):
        errors.append("temporal_validation error/tolerance inválidos")
    elif abs(error) > tolerance:
        errors.append("temporal_validation excede tolerancia")

    spatial = document.get("spatial_comparison") or {}
    trend_zones = spatial.get("trend_zone_summaries")
    trend_ids: set[str] = set()
    if not isinstance(trend_zones, list):
        errors.append("spatial_comparison.trend_zone_summaries inválido")
    elif spatial.get("trend_zone_summary_count") != len(trend_zones):
        errors.append("trend_zone_summary_count no coincide")
    else:
        for index, zone in enumerate(trend_zones):
            trend_id = zone.get("trend_zone_id") if isinstance(zone, dict) else None
            if not isinstance(trend_id, str) or not trend_id:
                errors.append(f"trend_zone_summaries[{index}].trend_zone_id inválido")
            elif trend_id in trend_ids:
                errors.append(f"trend_zone_summaries[{index}].trend_zone_id duplicado")
            else:
                trend_ids.add(trend_id)

    localization = spatial.get("localization")
    mode = localization.get("mode") if isinstance(localization, dict) else None
    if mode not in {"validated_track_profile", "unavailable"}:
        errors.append("spatial_comparison.localization.mode inválido")
    elif mode == "validated_track_profile":
        context = document.get("context") or {}
        if localization.get("profile_status") not in VALID_PROFILE_STATUSES:
            errors.append("localization.profile_status no está validado")
        if localization.get("profile_track") != context.get("track"):
            errors.append("localization.profile_track no coincide con context")
        if localization.get("profile_layout") != context.get("track_layout"):
            errors.append("localization.profile_layout no coincide con context")
        profile_path = Path(str(localization.get("profile_source_path") or ""))
        if not profile_path.is_file():
            errors.append("localization.profile_source_path no existe")
        elif localization.get("profile_source_sha256") != sha256_file(profile_path):
            errors.append("localization.profile_source_sha256 no coincide")

    zones = spatial.get("zone_summaries")
    if not isinstance(zones, list):
        errors.append("spatial_comparison.zone_summaries inválido")
    elif spatial.get("zone_summary_count") != len(zones):
        errors.append("zone_summary_count no coincide")
    else:
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict):
                errors.append(f"zone_summaries[{index}] inválido")
                continue
            if zone.get("source_trend_zone_id") not in trend_ids:
                errors.append(
                    f"zone_summaries[{index}].source_trend_zone_id inválido"
                )
            if mode == "validated_track_profile":
                if zone.get("scope") != "track_profile_segment":
                    errors.append(f"zone_summaries[{index}].scope inválido")
                location = zone.get("location")
                if not isinstance(location, dict) or not location.get("label"):
                    errors.append(f"zone_summaries[{index}].location inválida")
                elif location.get("profile_id") != localization.get("profile_id"):
                    errors.append(
                        f"zone_summaries[{index}].location.profile_id no coincide"
                    )
            elif mode == "unavailable":
                if zone.get("scope") != "unlocalized_delta_trend":
                    errors.append(f"zone_summaries[{index}].scope inválido")
                if zone.get("location") is not None:
                    errors.append(f"zone_summaries[{index}].location debe ser null")

    authority = document.get("coaching_authority") or {}
    if authority.get("session_reference_remains_authority") is not True:
        errors.append("session_reference dejó de ser autoridad")
    if authority.get("historical_actions_authorized") is not False:
        errors.append("historical_actions_authorized debe ser false en v0.2")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida output H5.2 v0.2")
    parser.add_argument("comparison_json")
    args = parser.parse_args()
    document = json.loads(Path(args.comparison_json).read_text(encoding="utf-8"))
    errors = validate(document)

    print("=" * 88)
    print("RACE ENGINEER - H5.2 RAW CROSS-SESSION VALIDATION v0.2")
    print("=" * 88)
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"  - {error}")
    print("RESULT: " + ("PASS" if not errors else "FAIL"))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
