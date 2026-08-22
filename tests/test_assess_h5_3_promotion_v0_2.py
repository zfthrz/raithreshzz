from __future__ import annotations

from assess_h5_3_promotion_v0_2 import EVIDENCE_INCOMPLETE, EVIDENCE_READY, assess_evidence


TRACKS = [
    "Fuji Speedway",
    "Autodromo Enzo e Dino Ferrari",
    "Autódromo José Carlos Pace",
    "Autodromo Nazionale Monza",
]


def _item(review_id: str, track: str, decision: str, actions: list[str], sign: str = "current_slower") -> dict:
    return {
        "review_id": review_id,
        "decision": decision,
        "context": {"track": track},
        "location_label": "T1",
        "delta_sign": sign,
        "actions": actions,
        "actions_text": actions,
        "reason": (
            "current_lap_faster_no_actions"
            if decision == "WITHHELD" and sign == "current_faster"
            else "insufficient_action_context" if decision == "WITHHELD" else None
        ),
        "observation_codes": ["current_throttle_higher"] if decision == "WITHHELD" else [],
        "occurrence_count": 1,
    }


def _complete_inputs():
    items = [
        _item("a1", TRACKS[0], "AUTHORIZED_SHADOW_ACTION", ["increase_throttle"]),
        _item("a2", TRACKS[1], "AUTHORIZED_SHADOW_ACTION", ["increase_brake"]),
        _item("a3", TRACKS[2], "AUTHORIZED_SHADOW_ACTION", ["reduce_brake"]),
        _item("a4", TRACKS[3], "AUTHORIZED_SHADOW_ACTION", ["reduce_throttle", "reduce_brake"]),
        _item("w1", TRACKS[1], "WITHHELD", []),
        _item("w2", TRACKS[3], "WITHHELD", [], sign="current_faster"),
    ]
    labels = []
    for item in items:
        labels.append({
            "review_id": item["review_id"],
            "human_label": (
                "ACTION_USEFUL" if item["decision"] == "AUTHORIZED_SHADOW_ACTION"
                else "CORRECTLY_WITHHELD"
            ),
        })
    structural = {"verdict": "PROMOTION_READY"}
    queue = {
        "metadata": {
            "historical_actions_authorized": False,
            "session_reference_remains_authority": True,
        },
        "review_items": items,
    }
    return structural, queue, {"labels": labels}


def test_complete_review_is_ready_only_for_explicit_decision():
    structural, queue, labels = _complete_inputs()
    report = assess_evidence(structural, queue, labels)
    assert report["verdict"] == EVIDENCE_READY
    assert report["unmet"] == []
    assert report["authority"] == {
        "session_reference_remains_authority": True,
        "historical_actions_authorized": False,
        "automatic_promotion": False,
    }


def test_missing_monza_and_current_faster_are_reported():
    structural, queue, labels = _complete_inputs()
    removed_ids = {"a4", "w2"}
    queue["review_items"] = [item for item in queue["review_items"] if item["review_id"] not in removed_ids]
    labels["labels"] = [label for label in labels["labels"] if label["review_id"] not in removed_ids]
    report = assess_evidence(structural, queue, labels)
    assert report["verdict"] == EVIDENCE_INCOMPLETE
    assert "Autodromo Nazionale Monza" in report["coverage"]["missing_tracks"]
    assert "current_faster" in report["coverage"]["missing_delta_signs"]


def test_nonaffirmative_label_blocks_readiness():
    structural, queue, labels = _complete_inputs()
    labels["labels"][0]["human_label"] = "UNSAFE_ACTION"
    report = assess_evidence(structural, queue, labels)
    assert report["verdict"] == EVIDENCE_INCOMPLETE
    assert report["coverage"]["nonaffirmative_count"] == 1
    assert any("non-affirmative" in item for item in report["unmet"])


def test_missing_single_action_policy_branch_blocks_readiness():
    structural, queue, labels = _complete_inputs()
    queue["review_items"][1]["actions"] = ["increase_brake", "reduce_throttle"]
    report = assess_evidence(structural, queue, labels)
    assert report["verdict"] == EVIDENCE_INCOMPLETE
    assert "increase_brake" in report["coverage"]["missing_authorized_single_actions"]


def test_structural_gate_and_authority_are_hard_requirements():
    structural, queue, labels = _complete_inputs()
    structural["verdict"] = "PROMOTION_NOT_AUTHORIZED"
    queue["metadata"]["historical_actions_authorized"] = True
    report = assess_evidence(structural, queue, labels)
    assert report["verdict"] == EVIDENCE_INCOMPLETE
    assert report["requirements"]["zero_authority_change"] is False
    assert any("structural gate" in item for item in report["unmet"])
