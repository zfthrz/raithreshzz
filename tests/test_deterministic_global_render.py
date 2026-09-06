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
    elif name == "mixed_sequence":
        events = [
            {"text": "frená aproximadamente 12 m más tarde"},
            {"text": "soltá el acelerador aproximadamente 8 m más tarde"},
            {"text": "reaplicá el acelerador aproximadamente 15 m más tarde"},
        ]
        zones[0]["driver_cues"] = [{
            "channel": "brake+throttle",
            "kind": "combined_spatial_sequence",
            "text": "; después, ".join(event["text"] for event in events),
            "coaching_sequence": {
                "status": "COMBINED",
                "events": events,
            },
        }]
    elif name == "dense_repeated_observation":
        structured["repeated_observations"] = [
            "Zona A: aplicación distinta del freno: media +12.0 pp; "
            "pico +30.0 pp; acelerador distinto: media -8.0 pp"
        ]
        zones[0]["quantitative_observations"] = [
            "freno: media +12.0 pp; pico +30.0 pp; acelerador: media -8.0 pp"
        ]
        comparisons = [
            {
                "reference_lap": 1,
                "comparison_lap": 2,
                "comparison_minus_reference_s": 0.5,
            },
            {
                "reference_lap": 1,
                "comparison_lap": 3,
                "comparison_minus_reference_s": 0.8,
            },
        ]
    elif name == "reference_profiles":
        zones[0]["reference_action_profiles"] = [
            {
                "channel": "brake",
                "shape_summary": "freno progresivo",
                "shape_summary_detailed": "freno progresivo hasta el ápice",
            },
            {
                "channel": "throttle",
                "shape_summary": "acelerador sostenido",
                "shape_summary_detailed": "acelerador sostenido desde la salida",
            },
        ]
    elif name == "cue_references":
        zones[0]["comparison_count"] = 3
        zones[0]["driver_cues"][0]["text"] = (
            "frená aproximadamente 14 m más tarde y soltá el freno "
            "aproximadamente 11 m más temprano. Referencias: frenada: "
            "~95 m antes de T5; liberación: ~2 m antes del ápice de T5"
        )
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
        "mixed_sequence",
        "dense_repeated_observation",
        "reference_profiles",
        "cue_references",
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


def test_active_focus_names_selected_zones_without_repeating_plan_cues():
    args = _case("active_focus")
    rendered = neutral_render(*deepcopy(args))
    focus_section = rendered.split("## Foco principal", 1)[1].split(
        "## Plan para la próxima tanda", 1
    )[0]

    assert (
        "- Zona A: foco seleccionado; ver acciones completas en el plan."
    ) in focus_section
    assert "reducí el freno" not in focus_section
    assert "aumentá el acelerador" not in focus_section
    assert "**Qué cambiar:** Reducí el freno." in rendered


def test_combined_sequence_is_rendered_as_ordered_steps():
    rendered = neutral_render(*deepcopy(_case("mixed_sequence")))

    assert "**Qué cambiar — secuencia:**" in rendered
    assert "1. Frená aproximadamente 12 m más tarde." in rendered
    assert "2. Soltá el acelerador aproximadamente 8 m más tarde." in rendered
    assert "3. Reaplicá el acelerador aproximadamente 15 m más tarde." in rendered
    assert "frená aproximadamente 12 m más tarde; después" not in rendered


def test_repeated_observation_clauses_are_rendered_as_nested_bullets():
    rendered = neutral_render(*deepcopy(_case("dense_repeated_observation")))
    repeated_section = rendered.split("## Patrón que deja la sesión", 1)[1].split(
        "## Respaldo técnico", 1
    )[0]

    assert "- Zona A: aplicación distinta del freno: media +12.0 pp." in repeated_section
    assert "  - Pico +30.0 pp." in repeated_section
    assert "  - Acelerador distinto: media -8.0 pp." in repeated_section
    assert ";" not in repeated_section


def test_technical_comparisons_and_observations_are_scannable_lists():
    rendered = neutral_render(*deepcopy(_case("dense_repeated_observation")))
    technical = rendered.split("## Respaldo técnico", 1)[1]

    assert "**Comparaciones:**\n- 1→2 +0.5000 s.\n- 1→3 +0.8000 s." in technical
    assert "- Zona A:" in technical
    assert "  - Freno: media +12.0 pp." in technical
    assert "  - Pico +30.0 pp." in technical
    assert "  - Acelerador: media -8.0 pp." in technical
    assert "**Comparaciones:** 1→2" not in technical


def test_reference_profiles_are_rendered_one_channel_per_line():
    rendered = neutral_render(*deepcopy(_case("reference_profiles")))
    plan_section = rendered.split("## Plan para la próxima tanda", 1)[1].split(
        "## Respaldo técnico", 1
    )[0]

    assert "**Forma observada en la referencia:**" in plan_section
    assert "- Freno: freno progresivo hasta el ápice." in plan_section
    assert "- Acelerador: acelerador sostenido desde la salida." in plan_section
    assert "Freno: freno progresivo hasta el ápice; Acelerador:" not in plan_section


def test_cue_references_and_support_reasons_are_rendered_separately():
    rendered = neutral_render(*deepcopy(_case("cue_references")))
    first_zone = rendered.split("### 1. Zona A", 1)[1].split("### 2. Zona B", 1)[0]

    assert (
        "**Qué cambiar:** Frená aproximadamente 14 m más tarde y soltá el freno "
        "aproximadamente 11 m más temprano."
    ) in first_zone
    assert (
        "**Referencias:** Frenada: ~95 m antes de T5; liberación: "
        "~2 m antes del ápice de T5."
    ) in first_zone
    assert "**Por qué está en el plan:**\n- El punto físico" in first_zone
    assert "\n- La región completa apareció en 3 comparaciones." in first_zone
    assert "**Por qué está en el plan:** El punto físico" not in first_zone
