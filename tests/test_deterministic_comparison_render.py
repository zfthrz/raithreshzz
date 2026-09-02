from __future__ import annotations

import deterministic_comparison_render as render
import llm_analysis_deepseek as backend


def test_backend_reexports_extracted_render_primitives():
    for name in (
        "assessment_map",
        "format_channel_names",
        "format_lap_time",
        "meters",
        "render_hypotheses",
        "signed_seconds",
    ):
        assert getattr(backend, name) is getattr(render, name)
    assert backend._episode_authorized_driver_cues is render.episode_authorized_driver_cues
    assert backend._episode_validated_steering_cue is render.episode_validated_steering_cue
    assert backend._compose_episode_driver_cue_text is render.compose_episode_driver_cue_text
    assert backend._comparison_actionable_focus is render.comparison_actionable_focus


def test_comparison_formatting_contract_is_preserved():
    assert render.format_lap_time(90.94) == "1:30.940"
    assert render.format_lap_time(-1.25) == "-0:01.250"
    assert render.format_lap_time(None) == "N/D"
    assert render.signed_seconds(0.185) == "+0.1850 s"
    assert render.signed_seconds(None) == "N/D"
    assert render.meters(55.4) == "55 m"
    assert render.format_channel_names(["brake", "throttle"]) == (
        "freno, acelerador"
    )
    assert render.format_channel_names([]) == "sin canales de acción"


def test_assessment_map_preserves_integer_episode_identity():
    first = {"episode_id": "1", "classification": "PRIORITARIO"}
    second = {"episode_id": 2, "classification": "SECUNDARIO"}
    assert render.assessment_map({"episode_assessments": [first, second]}) == {
        1: first,
        2: second,
    }


def test_hypothesis_rendering_contract_is_preserved():
    assert render.render_hypotheses([]) == "- Sin hipótesis adicional."
    assert render.render_hypotheses(["A", "B"]) == "- A\n- B"


def test_authorized_physical_cues_fail_closed_and_keep_channel_order():
    episode = {
        "braking_point_comparison": {
            "status": "VALID",
            "authorized_numeric_coaching": True,
            "coaching_magnitude_m": 12,
            "coaching_direction": "later",
        },
        "throttle_onset_point_comparison": {
            "status": "VALID",
            "authorized_numeric_coaching": True,
            "coaching_magnitude_m": 8,
            "coaching_direction": "earlier",
        },
        "throttle_release_point_comparison": {
            "status": "VALID",
            "authorized_numeric_coaching": False,
            "coaching_magnitude_m": 5,
            "coaching_direction": "later",
        },
    }
    cues = render.episode_authorized_driver_cues(episode)
    assert [cue["channel"] for cue in cues] == ["brake", "throttle"]
    assert cues[0]["text"] == "frená aproximadamente 12 m más tarde"
    assert cues[1]["text"] == (
        "reaplicá el acelerador aproximadamente 8 m más temprano"
    )


def test_cue_composition_keeps_steering_as_adjustment_after_physical_action():
    physical = [{"text": "frená más tarde"}]
    steering = {"text": "reducí la magnitud del volante hacia la referencia"}
    assert render.compose_episode_driver_cue_text(physical, steering) == (
        "frená más tarde; como ajuste de volante, "
        "reducí la magnitud del volante hacia la referencia"
    )


def test_actionable_focus_prefers_physical_cue_over_steering_only():
    episodes = [
        {
            "episode_id": 1,
            "rank": 1,
            "action_time_loss_s": 0.4,
            "action_channels": ["steering_magnitude"],
            "action_evidence_by_channel": {
                "steering_magnitude": {
                    "events": [{"direction": "higher_in_comparison_lap"}]
                }
            },
        },
        {
            "episode_id": 2,
            "rank": 2,
            "action_time_loss_s": 0.2,
            "action_channels": ["brake"],
            "braking_point_comparison": {
                "status": "VALID",
                "authorized_numeric_coaching": True,
                "coaching_magnitude_m": 10,
                "coaching_direction": "later",
            },
        },
    ]
    structured = {
        "episode_assessments": [
            {
                "episode_id": 1,
                "classification": "PRIORITARIO",
                "recommendation": "reducí la magnitud del volante",
            },
            {"episode_id": 2, "classification": "SECUNDARIO"},
        ]
    }
    focus = render.comparison_actionable_focus(episodes, structured)
    assert focus is not None
    assert focus.index("frená aproximadamente 10 m más tarde") < focus.index(
        "volante"
    )


def test_spatial_facts_keep_authorized_objective_and_observational_states():
    episode = {
        "braking_point_comparison": {
            "status": "VALID",
            "comparison_minus_reference_m": 14,
            "relative_direction": "later_in_comparison_lap",
            "authorized_numeric_coaching": True,
            "coaching_magnitude_m": 10,
            "coaching_direction": "earlier",
        },
        "throttle_onset_point_comparison": {
            "status": "VALID",
            "relative_direction": "similar_to_reference",
        },
        "throttle_full_throttle_attainment_comparison": {
            "status": "VALID",
            "relative_direction": "earlier_in_comparison_lap",
            "comparison_minus_reference_m": -18,
        },
        "throttle_partial_lift_comparison": {
            "status": "VALID",
            "reference_partial_lift_count": 1,
            "comparison_partial_lift_count": 2,
        },
    }
    assert render.episode_spatial_facts(episode) == [
        "inicio de frenada 14 m después de la referencia; objetivo 10 m más temprano",
        "reaplicación de acelerador dentro de la zona muerta",
        "acelerador casi pleno confirmado 18 m antes de la referencia (observacional)",
        "lifts parciales recuperados: referencia 1, comparación 2 (observacional)",
    ]


def test_spatial_facts_ignore_invalid_or_unavailable_evidence():
    assert render.episode_spatial_facts({}) == []
    assert render.episode_spatial_facts({
        "braking_point_comparison": {
            "status": "UNAVAILABLE",
            "comparison_minus_reference_m": 20,
        },
        "throttle_partial_lift_comparison": {
            "status": "VALID",
            "reference_partial_lift_count": None,
            "comparison_partial_lift_count": 2,
        },
    }) == []


def test_backend_comparison_render_delegates_to_extracted_module(monkeypatch):
    sentinel = "rendered by extracted module"
    monkeypatch.setattr(
        backend,
        "_render_comparison_analysis",
        lambda comparison, episodes, structured: sentinel,
    )
    assert backend.render_comparison_analysis({}, [], {}) == sentinel


def test_extracted_markdown_render_keeps_public_sections():
    comparison = {
        "reference_lap": 1,
        "comparison_lap": 2,
        "reference_time_s": 90.0,
        "comparison_time_s": 90.5,
        "comparison_minus_reference_s": 0.5,
    }
    episode = {
        "episode_id": 1,
        "start_distance_m": 100,
        "end_distance_m": 150,
        "action_time_loss_s": 0.2,
        "action_channels": ["brake"],
        "evidence_strength": "strong",
        "braking_point_comparison": {
            "status": "VALID",
            "authorized_numeric_coaching": True,
            "coaching_magnitude_m": 10,
            "coaching_direction": "later",
            "comparison_minus_reference_m": -12,
            "relative_direction": "earlier_in_comparison_lap",
        },
    }
    structured = {
        "episode_assessments": [{
            "episode_id": 1,
            "classification": "PRIORITARIO",
            "interpretation": "frenada anticipada",
        }],
        "limitations": ["evidencia limitada"],
    }
    rendered = render.render_comparison_analysis(
        comparison, [episode], structured
    )
    assert "# Debrief de vuelta — 1 → 2" in rendered
    assert "La vuelta 2 quedó en 1:30.500, +0.5000 s" in rendered
    assert "## Puntos de trabajo" in rendered
    assert "**Qué probar:** Frená aproximadamente 10 m más tarde." in rendered
    assert "## Respaldo técnico" in rendered
    assert "## Límites de esta lectura" in rendered
