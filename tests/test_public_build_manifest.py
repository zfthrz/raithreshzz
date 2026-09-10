from __future__ import annotations

import json
from pathlib import Path

import pytest

import public_build_manifest as manifest


def _build_tree(root: Path) -> Path:
    build = root / "build"
    build.mkdir()
    for name in manifest.REQUIRED_FILES:
        (build / name).write_text(name, encoding="utf-8")
    for name in manifest.REQUIRED_DIRECTORIES:
        (build / name).mkdir()
    (build / "track_profiles" / "track_v1_0.json").write_text(
        json.dumps(
            {
                "profile_id": "track-v1.0",
                "status": "VALIDATED",
                "track": "Track",
                "layout": "Layout",
                "turns": [{"turn": 1}],
            }
        ),
        encoding="utf-8",
    )
    return build


def test_manifest_is_stable_and_verifiable(tmp_path, monkeypatch):
    build = _build_tree(tmp_path)
    (tmp_path / "requirements-release.txt").write_text(
        "duckdb==1.5.5\n", encoding="utf-8"
    )
    monkeypatch.setattr(manifest, "_source_commit", lambda _root: "abc123")
    first = manifest.write_manifest(build, tmp_path).read_bytes()
    second = manifest.write_manifest(build, tmp_path).read_bytes()
    assert first == second
    assert manifest.verify_manifest(build, tmp_path)
    payload = json.loads(first)
    assert payload["source_commit"] == "abc123"
    assert payload["locked_dependencies"] == ["duckdb==1.5.5"]
    assert payload["profile_catalog"][0]["profile_id"] == "track-v1.0"


def test_manifest_detects_modified_build_file(tmp_path, monkeypatch):
    build = _build_tree(tmp_path)
    (tmp_path / "requirements-release.txt").write_text(
        "duckdb==1.5.5\n", encoding="utf-8"
    )
    monkeypatch.setattr(manifest, "_source_commit", lambda _root: "abc123")
    manifest.write_manifest(build, tmp_path)
    (build / "RaceEngineerCLI.exe").write_text("changed", encoding="utf-8")
    assert not manifest.verify_manifest(build, tmp_path)


def test_manifest_rejects_missing_required_content(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    with pytest.raises(ValueError, match="RaceEngineer.exe"):
        manifest.build_manifest(build, tmp_path)


def test_reproducible_wrapper_fixes_build_entropy_and_refuses_reuse():
    script = (Path(__file__).parents[1] / "build_public_release.ps1").read_text(
        encoding="utf-8"
    )
    assert '$env:PYTHONHASHSEED = "1"' in script
    assert "$env:SOURCE_DATE_EPOCH = $commitEpoch" in script
    assert script.count("OutputRoot already exists") == 1
    assert script.count("WorkRoot already exists") == 1


def test_public_package_requires_installation_and_data_retention_guide():
    root = Path(__file__).parents[1]
    guide = (root / "PUBLIC_INSTALLATION.md").read_text(encoding="utf-8")
    spec = (root / "RaceEngineer.spec").read_text(encoding="utf-8")
    assert "PUBLIC_INSTALLATION.md" in manifest.REQUIRED_FILES
    assert 'root / "PUBLIC_INSTALLATION.md"' in spec
    assert "%LOCALAPPDATA%\\RaceEngineer" in guide
    assert "never deletes the LMU telemetry folder" in guide
    assert "nunca elimina la carpeta de telemetría de LMU" in guide


def test_public_package_includes_version_and_release_notes():
    root = Path(__file__).parents[1]
    spec = (root / "RaceEngineer.spec").read_text(encoding="utf-8")

    assert (root / "RELEASE_VERSION.txt").read_text(encoding="utf-8").strip() == "0.1.0-rc.1"
    assert 'root / "RELEASE_VERSION.txt"' in spec
    assert 'root / "docs" / "RELEASE_NOTES_V0_1_0.md"' in spec
