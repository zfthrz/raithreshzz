"""Tests for P9/P10/P11 extraction from LLM output (debrief) JSONs.

Tests verify that the audit tool correctly extracts P9/P10/P11 data
from debrief JSONs produced by the LLM backend.
"""

import json
import tempfile
from pathlib import Path
from typing import Any


def test_extract_p9_p10_p11_from_debrief():
    """Test P9/P10/P11 extraction from a mock debrief JSON."""
    from audit_h5_3_real_sessions import extract_p9_p10_p11

    mock_debrief = {
        "next_stint_plan": [
            {
                "candidate_id": "test_cand_001",
                "location_label": "T1 — Turn 1 corner",
                "actions": ["reduce_throttle"],
                "_p9_presentation_metadata": {
                    "presentation_rank": 1,
                    "authoritative": True,
                },
            },
            {
                "candidate_id": "test_cand_002",
                "location_label": "T2 — Variante Tamburello corner",
                "actions": ["increase_brake"],
                "_p9_presentation_metadata": {
                    "presentation_rank": 2,
                    "authoritative": True,
                },
            },
        ],
        "next_stint_plan_presentation": {
            "status": "ACTIVE",
            "presentation": [
                {
                    "rank": 1,
                    "location_label": "T1 — Turn 1 corner",
                    "actions": ["reduce_throttle"],
                    "driver_cues": ["reducir acelerador"],
                },
                {
                    "rank": 2,
                    "location_label": "T2 — Variante Tamburello corner",
                    "actions": ["increase_brake"],
                    "driver_cues": ["aumentar freno"],
                },
            ],
        },
        "next_stint_focus": {
            "status": "ACTIVE",
            "items": [
                {
                    "location_label": "T1 — Turn 1 corner",
                    "actions": ["reduce_throttle"],
                    "driver_cues": ["reducir acelerador"],
                },
                {
                    "location_label": "T2 — Variante Tamburello corner",
                    "actions": ["increase_brake"],
                    "driver_cues": ["aumentar freno"],
                },
            ],
        },
    }

    p9_data, p10_data, p11_data = extract_p9_p10_p11(mock_debrief)

    # Verify P9 extraction
    assert "rank_1" in p9_data
    assert "rank_2" in p9_data
    assert p9_data["rank_1"]["presentation_rank"] == 1
    assert p9_data["rank_2"]["presentation_rank"] == 2

    # Verify P10 extraction
    assert p10_data is not None
    assert p10_data["status"] == "ACTIVE"
    assert len(p10_data["presentation"]) == 2

    # Verify P11 extraction
    assert p11_data is not None
    assert p11_data["status"] == "ACTIVE"
    assert len(p11_data["items"]) == 2


def test_extract_p9_p10_p11_missing_data():
    """Test extraction with missing P9/P10/P11 data."""
    from audit_h5_3_real_sessions import extract_p9_p10_p11

    mock_debrief = {
        "next_stint_plan": [],
        "next_stint_plan_presentation": None,
        "next_stint_focus": None,
    }

    p9_data, p10_data, p11_data = extract_p9_p10_p11(mock_debrief)

    # Verify empty data
    assert p9_data == {}
    assert p10_data is None
    assert p11_data is None


def test_extract_p9_p10_p11_no_p9_metadata():
    """Test extraction when P9 metadata is missing."""
    from audit_h5_3_real_sessions import extract_p9_p10_p11

    mock_debrief = {
        "next_stint_plan": [
            {
                "candidate_id": "test_cand_001",
                "location_label": "T1 — Turn 1 corner",
                "actions": ["reduce_throttle"],
                # No _p9_presentation_metadata
            }
        ],
        "next_stint_plan_presentation": {
            "status": "ACTIVE",
            "presentation": [],
        },
        "next_stint_focus": {
            "status": "INACTIVE",
            "items": [],
        },
    }

    p9_data, p10_data, p11_data = extract_p9_p10_p11(mock_debrief)

    # Verify P9 extraction skipped missing metadata
    assert p9_data == {}


def test_get_p11_focus_items():
    """Test extraction of P11 focus items."""
    from audit_h5_3_real_sessions import get_p11_focus_items

    # Test ACTIVE status
    p11_data = {
        "status": "ACTIVE",
        "items": [
            {
                "location_label": "T1 — Turn 1 corner",
                "actions": ["reduce_throttle"],
                "driver_cues": ["reducir acelerador"],
            }
        ],
    }
    items = get_p11_focus_items(p11_data)
    assert len(items) == 1
    assert items[0]["location_label"] == "T1 — Turn 1 corner"

    # Test INACTIVE status
    p11_data_inactive = {
        "status": "INACTIVE",
        "items": [],
    }
    items_inactive = get_p11_focus_items(p11_data_inactive)
    assert items_inactive == []

    # Test empty/None
    assert get_p11_focus_items(None) == []
    assert get_p11_focus_items({}) == []


def test_get_p10_presentation_items():
    """Test extraction of P10 presentation items."""
    from audit_h5_3_real_sessions import get_p10_presentation_items

    p10_data = {
        "status": "ACTIVE",
        "presentation": [
            {
                "rank": 1,
                "location_label": "T1 — Turn 1 corner",
                "actions": ["reduce_throttle"],
            }
        ],
    }
    items = get_p10_presentation_items(p10_data)
    assert len(items) == 1
    assert items[0]["location_label"] == "T1 — Turn 1 corner"

    # Test empty/None
    assert get_p10_presentation_items(None) == []
    assert get_p10_presentation_items({}) == []


def test_get_p9_rank():
    """Test extraction of P9 rank from item metadata."""
    from audit_h5_3_real_sessions import get_p9_rank

    # Test with rank
    item_with_rank = {
        "_p9_presentation_metadata": {"presentation_rank": 1, "authoritative": True}
    }
    assert get_p9_rank(item_with_rank) == 1

    # Test without rank
    item_no_rank = {"_p9_presentation_metadata": {}}
    assert get_p9_rank(item_no_rank) is None

    # Test without metadata
    item_no_metadata = {}
    assert get_p9_rank(item_no_metadata) is None


def test_classify_historical_action_supports_current():
    """Test classification of SUPPORTS_CURRENT."""
    from audit_h5_3_real_sessions import (
        classify_historical_action_vs_p11,
    )

    historical_action = {
        "candidate_id": "test_cand_001",
        "location_label": "T1 — Turn 1 corner",
        "actions": ["reduce_throttle"],
    }

    p11_focus_items = [
        {
            "location_label": "T1 — Turn 1 corner",
            "actions": ["reduce_throttle"],
            "driver_cues": ["reducir acelerador"],
        }
    ]

    result = classify_historical_action_vs_p11(
        historical_action,
        p11_focus_items,
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"


def test_classify_historical_action_conflicts_with_current():
    """Test classification of CONFLICTS_WITH_CURRENT."""
    from audit_h5_3_real_sessions import (
        classify_historical_action_vs_p11,
    )

    historical_action = {
        "candidate_id": "test_cand_001",
        "location_label": "T1 — Turn 1 corner",
        "actions": ["increase_throttle"],
    }

    p11_focus_items = [
        {
            "location_label": "T1 — Turn 1 corner",
            "actions": ["reduce_throttle"],
            "driver_cues": ["reducir acelerador"],
        }
    ]

    result = classify_historical_action_vs_p11(
        historical_action,
        p11_focus_items,
        [],
    )

    assert result["classification"] == "CONFLICTS_WITH_CURRENT"


def test_classify_historical_action_duplicates_current():
    """Test classification of DUPLICATES_CURRENT."""
    from audit_h5_3_real_sessions import (
        classify_historical_action_vs_p11,
    )

    historical_action = {
        "candidate_id": "test_cand_001",
        "location_label": "T1 — Turn 1 corner",
        "actions": ["reduce_throttle"],
    }

    p11_focus_items = [
        {
            "location_label": "T1 — Turn 1 corner",
            "actions": [],
            "driver_cues": ["reduce_throttle"],
        }
    ]

    result = classify_historical_action_vs_p11(
        historical_action,
        p11_focus_items,
        [],
    )

    assert result["classification"] == "DUPLICATES_CURRENT"


def test_classify_historical_action_useful_secondary_context():
    """Test classification of USEFUL_SECONDARY_CONTEXT."""
    from audit_h5_3_real_sessions import (
        classify_historical_action_vs_p11,
    )

    historical_action = {
        "candidate_id": "test_cand_001",
        "location_label": "T1 — Turn 1 corner",
        "actions": ["reduce_throttle"],
    }

    p11_focus_items = [
        {
            "location_label": "T2 — Variante Tamburello corner",
            "actions": ["increase_brake"],
            "driver_cues": ["aumentar freno"],
        }
    ]

    result = classify_historical_action_vs_p11(
        historical_action,
        p11_focus_items,
        [],
    )

    assert result["classification"] == "LOW_VALUE"


def test_classify_historical_action_p11_unavailable():
    """Test classification of P11_UNAVAILABLE."""
    from audit_h5_3_real_sessions import (
        classify_historical_action_vs_p11,
    )

    historical_action = {
        "candidate_id": "test_cand_001",
        "location_label": "T1 — Turn 1 corner",
        "actions": ["reduce_throttle"],
    }

    result = classify_historical_action_vs_p11(
        historical_action,
        [],
        [],
    )

    assert result["classification"] == "P11_UNAVAILABLE"


def test_locations_match():
    """Test location matching by corner labels."""
    from audit_h5_3_real_sessions import _locations_match

    assert _locations_match(
        "T1 — Turn 1 corner",
        "T1 — Turn 1 corner",
    )
    assert not _locations_match(
        "T1 — Turn 1 corner",
        "T2 — Variante Tamburello corner",
    )
    assert not _locations_match(
        "T1 — Turn 1 corner",
        "T17 — Rivazza 1 corner",
    )


def test_extract_corners():
    """Test corner label extraction from location labels."""
    from audit_h5_3_real_sessions import _extract_corners

    assert "T1" in _extract_corners("T1 — Turn 1 corner")
    assert "T2" in _extract_corners("T2 — Variante Tamburello corner")
    assert "T17" in _extract_corners("T17 — Rivazza 1 corner")
    assert "T1" in _extract_corners("LMU/RaceControl Imola 19-turn numbering T1 — Turn 1 corner")


def test_actions_match():
    """Test action matching."""
    from audit_h5_3_real_sessions import _actions_match

    assert _actions_match(["reduce_throttle"], ["reduce_throttle"])
    assert not _actions_match(["reduce_throttle"], ["increase_throttle"])
    assert not _actions_match(["reduce_throttle"], ["reduce_brake"])


def test_actions_compatible():
    """Test action compatibility check."""
    from audit_h5_3_real_sessions import _actions_compatible

    # Compatible actions
    assert _actions_compatible(["reduce_throttle"], ["reduce_throttle"])
    assert _actions_compatible(["increase_brake"], ["increase_brake"])

    # Conflicting actions
    assert not _actions_compatible(["reduce_throttle"], ["increase_throttle"])
    assert not _actions_compatible(["increase_throttle"], ["reduce_throttle"])
    assert not _actions_compatible(["reduce_brake"], ["increase_brake"])


def test_cues_overlap():
    """Test cue overlap check."""
    from audit_h5_3_real_sessions import _cues_overlap

    # Overlapping cues
    assert _cues_overlap(["reduce_throttle"], ["reduce_throttle"])
    
    # Non-overlapping cues (no shared actions)
    assert not _cues_overlap(["reduce_throttle"], ["increase_throttle"])
    assert not _cues_overlap(["reduce_throttle"], ["increase_brake"])
    
    # Empty cues
    assert not _cues_overlap([], ["reduce_throttle"])
    assert not _cues_overlap(["reduce_throttle"], [])


def test_resolve_debrief_json_searches_correctly():
    """Test that resolve_debrief_json searches LLM results directory."""
    from audit_h5_3_real_sessions import resolve_debrief_json

    # Create temporary directory structure
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Create LLM results directory
        session_dir = tmp_path / "llm_results" / "test_session"
        session_dir.mkdir(parents=True)

        # Create mock debrief JSON
        mock_debrief = {
            "next_stint_plan": [
                {
                    "candidate_id": "test_cand_001",
                    "location_label": "T1 — Turn 1 corner",
                    "actions": ["reduce_throttle"],
                    "_p9_presentation_metadata": {
                        "presentation_rank": 1,
                        "authoritative": True,
                    },
                }
            ],
            "next_stint_plan_presentation": {
                "status": "ACTIVE",
                "presentation": [],
            },
            "next_stint_focus": {
                "status": "ACTIVE",
                "items": [
                    {
                        "location_label": "T1 — Turn 1 corner",
                        "actions": ["reduce_throttle"],
                    }
                ],
            },
        }

        debrief_path = session_dir / "test_debrief.json"
        debrief_path.write_text(json.dumps(mock_debrief))

        # Test resolution
        result = resolve_debrief_json("test_session", base_dir=tmp_path)

        assert result["debrief"] is not None
        assert result["p9_data"] == {"rank_1": mock_debrief["next_stint_plan"][0]["_p9_presentation_metadata"]}
        assert result["p10_data"]["status"] == "ACTIVE"
        assert result["p11_data"]["status"] == "ACTIVE"
        assert result["session_label"] == "test_session"

        # Test with non-existent session
        result_not_found = resolve_debrief_json("non_existent_session", base_dir=tmp_path)
        assert result_not_found["debrief"] is None
        assert result_not_found["session_label"] is None


def test_extract_p9_p10_p11_from_nested_session_coaching_facts():
    """Real backends nest P9/P10/P11 under session_coaching_facts."""
    from audit_h5_3_real_sessions import extract_p9_p10_p11

    debrief = {
        "global_analysis": "# Debrief",
        "session_coaching_facts": {
            "next_stint_plan": [
                {
                    "plan_label": "A",
                    "track_location": {"label": "T5 — Variante Villeneuve"},
                    "_p9_presentation_metadata": {
                        "presentation_rank": 0,
                        "primary_action_family": "BRAKE_TIMING",
                    },
                }
            ],
            "next_stint_plan_presentation": {"_p10_presentation": {"status": "ACTIVE"}},
            "next_stint_focus": {
                "status": "ACTIVE",
                "focus_count": 1,
                "items": [
                    {
                        "plan_label": "A",
                        "track_location": {"label": "T5 — Variante Villeneuve"},
                        "driver_cues": [
                            {"channel": "brake", "text": "frená aproximadamente 15 m más tarde"}
                        ],
                    }
                ],
            },
        },
    }

    p9_data, p10_data, p11_data = extract_p9_p10_p11(debrief)

    assert p9_data == {
        "rank_0": {
            "presentation_rank": 0,
            "primary_action_family": "BRAKE_TIMING",
        }
    }
    assert p10_data == {"_p10_presentation": {"status": "ACTIVE"}}
    assert p11_data["status"] == "ACTIVE"
    assert p11_data["items"][0]["track_location"]["label"] == "T5 — Variante Villeneuve"


def test_resolve_debrief_json_finds_nested_session_coaching_facts():
    """Resolution detects P11 data nested under session_coaching_facts."""
    from audit_h5_3_real_sessions import resolve_debrief_json

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        session_dir = tmp_path / "llm_results" / "real_session"
        session_dir.mkdir(parents=True)
        (session_dir / "debrief.json").write_text(
            json.dumps(
                {
                    "session_coaching_facts": {
                        "next_stint_focus": {
                            "status": "ACTIVE",
                            "items": [{"plan_label": "A"}],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        result = resolve_debrief_json("real_session", base_dir=tmp_path)

        assert result["debrief"] is not None
        assert result["p11_data"]["status"] == "ACTIVE"
        assert result["session_label"] == "real_session"


def test_get_p11_focus_items_normalizes_real_shape():
    """Real P11 items normalize to location_label + driver cue texts."""
    from audit_h5_3_real_sessions import get_p11_focus_items

    items = get_p11_focus_items(
        {
            "status": "ACTIVE",
            "items": [
                {
                    "plan_label": "A",
                    "track_location": {
                        "label": "T6 — Variante Villeneuve → T7 — Tosa"
                    },
                    "targets": ["reducir el freno hacia la referencia"],
                    "driver_cues": [
                        {"channel": "brake", "text": "frená aproximadamente 17 m más tarde"}
                    ],
                }
            ],
        }
    )

    assert items[0]["location_label"] == "T6 — Variante Villeneuve → T7 — Tosa"
    assert items[0]["driver_cues"] == ["frená aproximadamente 17 m más tarde"]
    assert items[0]["channels"] == ["brake"]


def test_classify_real_shape_duplicates_same_channel():
    """Same location + same channel already in P11 => DUPLICATES_CURRENT."""
    from audit_h5_3_real_sessions import classify_historical_action_vs_p11

    result = classify_historical_action_vs_p11(
        {
            "candidate_id": "c1",
            "location_label": "T1 — Turn 1 corner",
            "actions": ["increase_throttle"],
        },
        [
            {
                "location_label": "T1 — Turn 1 corner",
                "actions": [],
                "driver_cues": ["aumentá el acelerador"],
                "channels": ["throttle"],
            }
        ],
        [],
    )

    assert result["classification"] == "DUPLICATES_CURRENT"


def test_classify_real_shape_supports_extra_channel():
    """Same location + additional channel beyond P11 => SUPPORTS_CURRENT."""
    from audit_h5_3_real_sessions import classify_historical_action_vs_p11

    result = classify_historical_action_vs_p11(
        {
            "candidate_id": "c1",
            "location_label": "T1 — Turn 1 corner",
            "actions": ["increase_throttle", "reduce_brake"],
        },
        [
            {
                "location_label": "T1 — Turn 1 corner",
                "actions": [],
                "driver_cues": ["aumentá el acelerador"],
                "channels": ["throttle"],
            }
        ],
        [],
    )

    assert result["classification"] == "SUPPORTS_CURRENT"


def test_classify_real_shape_conflicts_direction():
    """Opposite deterministic direction at same location => CONFLICTS_CURRENT."""
    from audit_h5_3_real_sessions import classify_historical_action_vs_p11

    result = classify_historical_action_vs_p11(
        {
            "candidate_id": "c1",
            "location_label": "T1 — Turn 1 corner",
            "actions": ["increase_brake"],
        },
        [
            {
                "location_label": "T1 — Turn 1 corner",
                "actions": [],
                "driver_cues": ["reducí el freno"],
                "channels": ["brake"],
            }
        ],
        [],
    )

    assert result["classification"] == "CONFLICTS_WITH_CURRENT"


def test_classify_real_shape_useful_secondary_channel():
    """Same location but different channel => USEFUL_SECONDARY_CONTEXT."""
    from audit_h5_3_real_sessions import classify_historical_action_vs_p11

    result = classify_historical_action_vs_p11(
        {
            "candidate_id": "c1",
            "location_label": "T1 — Turn 1 corner",
            "actions": ["increase_brake"],
        },
        [
            {
                "location_label": "T1 — Turn 1 corner",
                "actions": [],
                "driver_cues": ["aumentá el acelerador"],
                "channels": ["throttle"],
            }
        ],
        [],
    )

    assert result["classification"] == "USEFUL_SECONDARY_CONTEXT"
