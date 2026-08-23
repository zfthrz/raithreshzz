from __future__ import annotations

import json
from pathlib import Path

from race_engineer_h5_3_review_status import load_status, project_state


def test_up_to_date_projection_is_green_and_names_revision():
    status = project_state({
        "status": "UP_TO_DATE",
        "current_revision": 5,
        "pending_review_count": 0,
        "historical_actions_authorized": False,
    })
    assert status.text == "H5.3 shadow · al día · v5"
    assert status.style == "H53Ready.TLabel"


def test_pending_projection_is_amber_and_exposes_labels_path():
    status = project_state({
        "status": "NEW_REVIEW_REQUIRED",
        "current_revision": 6,
        "pending_review_count": 3,
        "current_labels_json": "C:/project/labels_v6.json",
        "historical_actions_authorized": False,
    })
    assert "3 casos pendientes" in status.text
    assert status.style == "H53Pending.TLabel"
    assert status.detail == "C:/project/labels_v6.json"


def test_authority_change_or_invalid_pending_state_is_rendered_as_error(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "status": "NEW_REVIEW_REQUIRED",
        "pending_review_count": 0,
        "historical_actions_authorized": True,
    }), encoding="utf-8")
    status = load_status(path)
    assert status.code == "STATE_INVALID"
    assert status.style == "H53Error.TLabel"


def test_missing_state_is_safe_and_muted(tmp_path: Path):
    status = load_status(tmp_path / "missing.json")
    assert status.code == "STATE_UNAVAILABLE"
    assert status.style == "H53Muted.TLabel"
