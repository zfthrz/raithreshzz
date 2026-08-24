from __future__ import annotations

from golden_set_semantic_regression import (
    build_golden_record,
    evaluate_record,
)


def item(
    label: str,
    channel: str,
    source: str,
    text: str,
    plan_label: str = "A",
) -> dict:
    return {
        "plan_label": plan_label,
        "track_location": {"label": label},
        "driver_cues": [
            {
                "channel": channel,
                "source": source,
                "text": text,
            }
        ],
    }


def debrief(plan: list[dict], focus_items: list[dict] | None = None, focus_status: str = "ACTIVE") -> dict:
    return {
        "session_coaching_facts": {
            "next_stint_plan": plan,
            "next_stint_focus": {
                "status": focus_status,
                "items": focus_items or [],
            },
        }
    }


def record() -> dict:
    return {
        "golden_id": "t1",
        "expected_regions": ["T1 — Test corner"],
        "expected_action_families": ["brake"],
        "expected_p11": {"status": "ACTIVE", "max_items": 2},
    }


def test_evaluate_record_passes_for_matching_debrief():
    document = debrief(
        [item("T1 — Test corner", "brake", "authorized_brake_onset_release", "frená más tarde")],
        focus_items=[{"plan_label": "A"}],
    )

    result = evaluate_record(record(), document)

    assert result["pass"] is True


def test_evaluate_record_fails_on_missing_region():
    document = debrief(
        [item("T2 — Another corner", "brake", "authorized_brake_onset_release", "frená más tarde")]
    )

    result = evaluate_record(record(), document)

    assert result["pass"] is False
    assert result["checks"]["region_coverage"] is False


def test_evaluate_record_fails_on_forbidden_action():
    document = debrief(
        [
            item(
                "T1 — Test corner",
                "brake",
                "authorized_brake_onset_release",
                "aumentá la velocidad en la zona",
            )
        ]
    )

    result = evaluate_record(record(), document)

    assert result["pass"] is False
    assert result["checks"]["no_forbidden_actions"] is False


def test_evaluate_record_fails_on_p11_status_mismatch():
    document = debrief(
        [item("T1 — Test corner", "brake", "authorized_brake_onset_release", "frená más tarde")],
        focus_status="INACTIVE",
    )

    result = evaluate_record(record(), document)

    assert result["pass"] is False
    assert result["checks"]["p11_status"] is False


def test_build_golden_record_extracts_semantics():
    document = debrief(
        [
            item(
                "T1 — Test corner",
                "brake+throttle",
                "deterministic_coaching_sequence",
                "frená y acelerá",
            )
        ],
        focus_items=[{"plan_label": "A"}],
    )

    built = build_golden_record("session-x", "Test Track", "LMP2_ELMS", document)

    assert built["expected_regions"] == ["T1 — Test corner"]
    assert built["expected_action_families"] == ["brake", "throttle"]
    assert built["expected_p11"]["status"] == "ACTIVE"
    assert built["status"] == "SEED"
