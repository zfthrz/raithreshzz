"""Create or verify the content manifest for a built public distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from public_release_contract import public_profile_catalog


MANIFEST_NAME = "BUILD_MANIFEST.json"
REQUIRED_FILES = (
    "RaceEngineer.exe",
    "RaceEngineerAnalyze.exe",
    "RaceEngineerCLI.exe",
    "RaceEngineerWorker.exe",
    "LICENSE.txt",
    "PUBLIC_INSTALLATION.md",
    "THIRD_PARTY_NOTICES.md",
)
REQUIRED_DIRECTORIES = (
    "_tcl_data",
    "_tk_data",
    "third_party_licenses",
    "track_profiles",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _locked_dependencies(project_root: Path) -> list[str]:
    return [
        line.strip()
        for line in (project_root / "requirements-release.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _source_commit(project_root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_manifest(build_dir: Path, project_root: Path) -> dict[str, Any]:
    build = build_dir.resolve()
    project = project_root.resolve()
    missing = [name for name in REQUIRED_FILES if not (build / name).is_file()]
    missing.extend(
        name for name in REQUIRED_DIRECTORIES if not (build / name).is_dir()
    )
    if missing:
        raise ValueError("Missing public build content: " + ", ".join(missing))

    profiles, profile_errors = public_profile_catalog(build / "track_profiles")
    if profile_errors:
        raise ValueError("Invalid packaged profile catalog: " + "; ".join(profile_errors))

    files = []
    for path in sorted(build.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        files.append(
            {
                "path": path.relative_to(build).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema_version": 1,
        "source_commit": _source_commit(project),
        "python_runtime": "3.12.10",
        "locked_dependencies": _locked_dependencies(project),
        "profile_catalog": profiles,
        "file_count": len(files),
        "content_bytes": sum(item["size"] for item in files),
        "files": files,
    }


def write_manifest(build_dir: Path, project_root: Path) -> Path:
    result = build_manifest(build_dir, project_root)
    output = build_dir.resolve() / MANIFEST_NAME
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(output)
    return output


def verify_manifest(build_dir: Path, project_root: Path) -> bool:
    path = build_dir.resolve() / MANIFEST_NAME
    stored = json.loads(path.read_text(encoding="utf-8"))
    return stored == build_manifest(build_dir, project_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir", type=Path)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parent
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.verify:
        if not verify_manifest(args.build_dir, args.project_root):
            print("BUILD_MANIFEST_MISMATCH")
            return 1
        print("BUILD_MANIFEST_OK")
        return 0
    print(write_manifest(args.build_dir, args.project_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
