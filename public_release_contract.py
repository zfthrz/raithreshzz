"""Read-only readiness audit for a future public Race Engineer distribution."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from cross_session_zone_localization import normalize_identity
from track_readiness import ProfileRecord, discover_profiles

AUDIT_VERSION = "0.3"
PUBLIC_GUI_SECTIONS = ("Resumen", "Telemetría", "Historial", "Estadísticas")
DEVELOPMENT_GUI_SECTIONS = ("Circuitos", "Diagnóstico", "Calibración")
PUBLIC_ENTRYPOINT = "RaceEngineerPublic.pyw"
PACKAGING_FILES = ("pyproject.toml", "RaceEngineer.spec")
LEGAL_FILES = ("LICENSE", "LICENSE.txt", "LICENSE.md")
THIRD_PARTY_NOTICE = "THIRD_PARTY_NOTICES.md"
PUBLIC_INSTALLATION_GUIDE = "PUBLIC_INSTALLATION.md"


def _best_profile(records: list[ProfileRecord]) -> ProfileRecord | None:
    eligible = [
        item
        for item in records
        if item.status in {"VALIDATED", "VALIDATED_MULTI_SESSION"}
        and item.valid_turns
        and item.version is not None
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: (item.version, item.path.name.casefold()))


def public_profile_catalog(profile_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Select the highest validated production profile per exact identity."""
    records, errors = discover_profiles(profile_dir)
    groups: dict[tuple[str, str], list[ProfileRecord]] = defaultdict(list)
    for record in records:
        groups[(normalize_identity(record.track), normalize_identity(record.layout))].append(record)

    catalog = []
    for records_for_identity in groups.values():
        selected = _best_profile(records_for_identity)
        if selected is None:
            names = ", ".join(item.path.name for item in records_for_identity)
            errors.append(f"No validated versioned public profile among: {names}")
            continue
        catalog.append(
            {
                "track": selected.track,
                "layout": selected.layout,
                "profile_id": selected.profile_id,
                "version": list(selected.version or ()),
                "path": selected.path.name,
            }
        )
    catalog.sort(key=lambda item: (item["track"].casefold(), item["layout"].casefold()))
    return catalog, errors


def _dependency_specs(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _is_exact_pin(spec: str) -> bool:
    return bool(re.search(r"(?<![<>!~])==(?!=)", spec))


def audit_public_release(project_root: Path) -> dict[str, Any]:
    """Report release blockers without building, copying, or deleting files."""
    root = Path(project_root).resolve()
    profiles, profile_errors = public_profile_catalog(root / "track_profiles")
    release_requirements = root / "requirements-release.txt"
    dependency_specs = _dependency_specs(
        release_requirements if release_requirements.is_file() else root / "requirements.txt"
    )
    blockers = []
    if not (root / PUBLIC_ENTRYPOINT).is_file():
        blockers.append("PUBLIC_ENTRYPOINT_MISSING")
    if not any((root / name).is_file() for name in PACKAGING_FILES):
        blockers.append("PACKAGING_CONFIGURATION_MISSING")
    if dependency_specs and not all(_is_exact_pin(spec) for spec in dependency_specs):
        blockers.append("RUNTIME_DEPENDENCIES_NOT_EXACTLY_PINNED")
    if not any((root / name).is_file() for name in LEGAL_FILES):
        blockers.append("LICENSE_MISSING")
    if not (root / THIRD_PARTY_NOTICE).is_file():
        blockers.append("THIRD_PARTY_NOTICES_MISSING")
    if not (root / PUBLIC_INSTALLATION_GUIDE).is_file():
        blockers.append("PUBLIC_INSTALLATION_GUIDE_MISSING")
    if profile_errors:
        blockers.append("PROFILE_CATALOG_INVALID")

    return {
        "schema_version": 1,
        "audit_version": AUDIT_VERSION,
        "status": "READY" if not blockers else "BLOCKED",
        "public_entrypoint": PUBLIC_ENTRYPOINT,
        "public_gui_sections": list(PUBLIC_GUI_SECTIONS),
        "development_gui_sections_excluded": list(DEVELOPMENT_GUI_SECTIONS),
        "profile_catalog": {
            "selection": "highest validated version per exact track/layout",
            "count": len(profiles),
            "profiles": profiles,
            "errors": profile_errors,
        },
        "runtime_dependencies": dependency_specs,
        "legal": {
            "product_license": next(
                (name for name in LEGAL_FILES if (root / name).is_file()), None
            ),
            "third_party_notices": (
                THIRD_PARTY_NOTICE if (root / THIRD_PARTY_NOTICE).is_file() else None
            ),
        },
        "installation_guide": (
            PUBLIC_INSTALLATION_GUIDE
            if (root / PUBLIC_INSTALLATION_GUIDE).is_file()
            else None
        ),
        "blockers": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit_public_release(args.project_root)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
