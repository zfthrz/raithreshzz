from __future__ import annotations

from copy import deepcopy

import pytest

import llm_analysis_deepseek as legacy
from deterministic_global_render import render_global_analysis as neutral_render


BASE_GLOBAL = {
    "opportunities": [],
    "repeated_observations": [],
    "hypotheses": [],
    "limitations": [],
    "conclusion": "",
    "next_session_priorities": [],
}


def _zone(label, *, channel="brake", text="reducí el freno"):
    return {
        "plan_label": label,
        "kind": "repeated_region",
        "comparison_count": 2,
        "comparisons": ["1->2", "1->3"],
        "observed_differences": ["más freno"],
        "quantitative_observations": ["delta de acción +0.1200 s"],
        "driver_cues": [{
            "channel": channel,
            "text": text,
            "point_comparison_count": 2,
            "precision_evidence": [{
                "reference_lap": 1,
                "supporting_laps": [2, 3],
                "observed_delta_min_m": 8,
                "observed_delta_max_m": 12,
                "representative_delta_m": 10,
                "corner_relative_reference": {"driver_label": "antes del ápice"},
            }],
        }],
        "track_location": {"label": f"T{label} — Curva {label}"},
    }


def _case(name):
    metadata = {
        "track": "Spa-Francorchamps",
        "session_type": "Practice",
        "reference_lap": 1,
        "lap_times_s": {"1": 120.123},
    }
    comparisons = []
    facts = {"next_stint_plan": []}
    structured = deepcopy(BASE_GLOBAL)

    if name == "empty_plan":
        return metadata, comparisons, facts, structured

    zones = [_zone("A"), _zone("B", channel="throttle", text="aumentá el acelerador")]
    facts["next_stint_plan"] = zones

    if name == "multiple_zones":
        structured["repeated_observations"] = ["Zona A: hubo más freno."]
    elif name == "active_focus":
        facts["next_stint_focus"] = {
            "status": "ACTIVE",
            "items": deepcopy(zones),
        }
    elif name == "physical_patterns":
        facts["repeated_braking_point_patterns"] = [{
            "status": "REPEATED",
            "region_label": "C",
            "reference_onset_m": 500,
            "coaching_direction": "later",
            "coaching_magnitude_m": 12,
            "comparison_count": 3,
            "track_location": {"label": "T3 — Eau Rouge"},
        }]
    elif name == "steering":
        zones[0]["driver_cues"].append({
            "channel": "steering_magnitude",
            "text": "aumentá la magnitud de volante",
        })
        zones[0]["observed_differences"].append("dirección menor")
    elif name == "quality_exclusion":
        facts["comparison_quality_gate"] = {
            "excluded_comparisons": [{"reference_lap": 1, "comparison_lap": 3}],
            "comparisons": [{
                "reference_lap": 1,
                "comparison_lap": 2,
                "session_plan_eligible": False,
            }],
        }
        comparisons = [{
            "reference_lap": 1,
            "comparison_lap": 2,
            "comparison_minus_reference_s": 0.5,
            "excluded_anomalies": [{"kind": "loss"}],
        }]
    elif name == "track_location":
        facts["priority_findings"] = [{
            "comparison": "1->2",
            "episode_id": 7,
            "action_time_loss_s": 0.1234,
            "track_location": {"label": "T1 — La Source"},
        }]
    return metadata, comparisons, facts, structured


@pytest.mark.parametrize(
    "case_name",
    [
        "empty_plan",
        "multiple_zones",
        "active_focus",
        "physical_patterns",
        "steering",
        "quality_exclusion",
        "track_location",
    ],
)
def test_neutral_global_render_is_exactly_legacy_compatible(case_name):
    args = _case(case_name)
    assert neutral_render(*deepcopy(args)) == legacy.render_global_analysis(
        *deepcopy(args)
    )
