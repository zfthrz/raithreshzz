from __future__ import annotations

import json
from pathlib import Path

from public_release_contract import (
    DEVELOPMENT_GUI_SECTIONS,
    PUBLIC_GUI_SECTIONS,
    audit_public_release,
    main,
    public_profile_catalog,
)


def _profile(path: Path, *, profile_id: str, status: str = "VALIDATED") -> None:
    path.write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "status": status,
                "track": "Barcelona",
                "layout": "Grand Prix",
                "turns": [{"turn": 1}],
            }
        ),
        encoding="utf-8",
    )


def test_catalog_selects_latest_validated_exact_profile(tmp_path):
    _profile(tmp_path / "barcelona_v0_1.json", profile_id="barcelona_v0.1")
    _profile(tmp_path / "barcelona_v0_2.json", profile_id="barcelona_v0.2")
    _profile(
        tmp_path / "barcelona_v0_3.json",
        profile_id="barcelona_v0.3",
        status="SHADOW_ONLY",
    )
    catalog, errors = public_profile_catalog(tmp_path)
    assert errors == []
    assert [item["path"] for item in catalog] == ["barcelona_v0_2.json"]


def test_release_audit_is_read_only_and_lists_concrete_blockers(tmp_path):
    profiles = tmp_path / "track_profiles"
    profiles.mkdir()
    _profile(profiles / "barcelona.json", profile_id="barcelona_v0.1")
    (tmp_path / "requirements.txt").write_text("duckdb>=1.0\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = audit_public_release(tmp_path)
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert before == after
    assert result["status"] == "BLOCKED"
    assert result["blockers"] == [
        "PUBLIC_ENTRYPOINT_MISSING",
        "PACKAGING_CONFIGURATION_MISSING",
        "RUNTIME_DEPENDENCIES_NOT_EXACTLY_PINNED",
        "LICENSE_MISSING",
        "THIRD_PARTY_NOTICES_MISSING",
        "PUBLIC_INSTALLATION_GUIDE_MISSING",
    ]
    assert result["public_gui_sections"] == list(PUBLIC_GUI_SECTIONS)
    assert result["development_gui_sections_excluded"] == list(
        DEVELOPMENT_GUI_SECTIONS
    )


def test_release_audit_can_reach_ready_without_building(tmp_path):
    profiles = tmp_path / "track_profiles"
    profiles.mkdir()
    _profile(profiles / "barcelona.json", profile_id="barcelona_v1.0")
    (tmp_path / "RaceEngineerPublic.pyw").write_text("", encoding="utf-8")
    (tmp_path / "RaceEngineer.spec").write_text("", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("duckdb==1.0.0\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("license", encoding="utf-8")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("notices", encoding="utf-8")
    (tmp_path / "PUBLIC_INSTALLATION.md").write_text("guide", encoding="utf-8")
    assert audit_public_release(tmp_path)["status"] == "READY"


def test_release_audit_reports_selected_legal_files(tmp_path):
    (tmp_path / "LICENSE.txt").write_text("license", encoding="utf-8")
    (tmp_path / "THIRD_PARTY_NOTICES.md").write_text("notices", encoding="utf-8")
    result = audit_public_release(tmp_path)
    assert result["legal"] == {
        "product_license": "LICENSE.txt",
        "third_party_notices": "THIRD_PARTY_NOTICES.md",
    }


def test_release_audit_requires_public_installation_guide(tmp_path):
    result = audit_public_release(tmp_path)
    assert result["installation_guide"] is None
    assert "PUBLIC_INSTALLATION_GUIDE_MISSING" in result["blockers"]

    (tmp_path / "PUBLIC_INSTALLATION.md").write_text("guide", encoding="utf-8")
    result = audit_public_release(tmp_path)
    assert result["installation_guide"] == "PUBLIC_INSTALLATION.md"
    assert "PUBLIC_INSTALLATION_GUIDE_MISSING" not in result["blockers"]


def test_cli_returns_nonzero_for_blocked_release(tmp_path, capsys):
    assert main(["--project-root", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
