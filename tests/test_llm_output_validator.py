import validate_llm_analysis_output as validator


def test_validator_accepts_repeated_steering_only_as_second_cue():
    facts = {
        "next_stint_plan": [{
            "actionable_cue_count": 2,
            "driver_cues": [
                {"channel": "brake", "kind": "spatial_points"},
                {
                    "channel": "steering_magnitude",
                    "kind": "repeated_steering_secondary",
                    "source": "deterministic_repeated_steering_recurrence",
                    "secondary_only": True,
                    "causal_claim": False,
                    "region_comparison_count": 2,
                },
            ],
        }],
        "steering_secondary_promotion": {
            "status": "AUTHORIZED_SECONDARY",
            "ranking_changed": False,
            "existing_cue_displaced": False,
        },
    }
    errors = []

    validator.validate_repeated_steering_secondary(
        {"session_coaching_facts": facts},
        errors,
    )

    assert errors == []


def test_validator_rejects_steering_as_only_or_unproven_cue():
    facts = {
        "next_stint_plan": [{
            "actionable_cue_count": 1,
            "driver_cues": [{
                "channel": "steering_magnitude",
                "kind": "repeated_steering_secondary",
                "source": "wrong",
                "secondary_only": False,
                "causal_claim": True,
                "region_comparison_count": 1,
            }],
        }],
        "steering_secondary_promotion": {
            "status": "AUTHORIZED_SECONDARY",
            "ranking_changed": True,
            "existing_cue_displaced": True,
        },
    }
    errors = []

    validator.validate_repeated_steering_secondary(
        {"session_coaching_facts": facts},
        errors,
    )

    assert any("segundo slot" in error for error in errors)
    assert any("source inválido" in error for error in errors)
    assert any("recurrencia explícita" in error for error in errors)
    assert any("no puede cambiar ranking" in error for error in errors)
    assert any("no puede desplazar" in error for error in errors)


def test_validator_replays_python_owned_render_and_session_fields(monkeypatch):
    comparison = {
        "analysis": "render de comparación actual",
        "episode_ground_truth": [],
        "llm_structured": {},
    }
    session_facts = {"fact": "source-authorized"}
    global_structured = {
        "opportunities": [],
        "repeated_observations": ["patrón repetido en 2 comparaciones"],
        "hypotheses": [],
        "limitations": [],
        "next_session_priorities": ["frenar 10 m más tarde"],
        "conclusion": "Conclusión sin cifras.",
    }
    data = {
        "metadata": {},
        "comparisons": [comparison],
        "session_coaching_facts": session_facts,
        "global_structured": global_structured,
        "global_analysis": "render global actual",
    }

    monkeypatch.setattr(
        validator.llm_renderer,
        "render_comparison_analysis",
        lambda *_args: "render de comparación actual",
    )
    monkeypatch.setattr(
        validator.llm_renderer,
        "render_global_analysis",
        lambda *_args: "render global actual",
    )
    monkeypatch.setattr(
        validator.llm_renderer,
        "build_deterministic_repeated_observations",
        lambda facts: ["patrón repetido en 2 comparaciones"],
    )
    monkeypatch.setattr(
        validator.llm_renderer,
        "build_deterministic_next_session_priorities",
        lambda facts: ["frenar 10 m más tarde"],
    )

    errors = []
    warnings = []
    validator.validate_rendered_comparison(
        comparison,
        0,
        errors,
        warnings,
    )
    validator.validate_global_structured(
        data,
        errors,
    )
    validator.validate_global_render(
        data,
        errors,
    )
    assert errors == []

    comparison["analysis"] = "render antiguo"
    global_structured["next_session_priorities"] = ["objetivo inventado"]
    data["global_analysis"] = "render global alterado"

    errors = []
    validator.validate_rendered_comparison(
        comparison,
        0,
        errors,
        warnings,
    )
    validator.validate_global_structured(
        data,
        errors,
    )
    validator.validate_global_render(
        data,
        errors,
    )

    assert any("comparisons[0].analysis no coincide" in error for error in errors)
    assert any("next_session_priorities" in error for error in errors)
    assert any("global_analysis no coincide" in error for error in errors)


def test_validator_accepts_exact_quality_gate_fallback_with_preserved_episode_ids():
    comparison = {
        "status": "VALID",
        "validation_attempts": 0,
        "session_plan_eligible": False,
        "session_comparison_quality": {
            "quality_status": validator.QUALITY_EXCLUDED_STATUS,
        },
        "llm_validation_audit": {
            "summary": {
                "fallback": validator.QUALITY_EXCLUDED_FALLBACK,
            },
        },
        "driver_action_episode_count": 2,
        "episode_ground_truth": [
            {"episode_id": 2, "action_channels": ["brake"]},
            {"episode_id": 3, "action_channels": ["throttle"]},
        ],
        "llm_structured": dict(validator.QUALITY_EXCLUDED_STRUCTURED),
        "analysis": validator.QUALITY_EXCLUDED_ANALYSIS,
    }

    errors = []
    warnings = []
    validator.validate_episode_contract(comparison, 0, errors)
    validator.validate_rendered_comparison(comparison, 0, errors, warnings)
    assert errors == []

    comparison["llm_structured"] = {
        **validator.QUALITY_EXCLUDED_STRUCTURED,
        "episode_assessments": [{"episode_id": 2}],
    }
    comparison["analysis"] = "fallback alterado"

    errors = []
    validator.validate_episode_contract(comparison, 0, errors)
    validator.validate_rendered_comparison(comparison, 0, errors, warnings)
    assert any("fallback determinista" in error for error in errors)
    assert any("render determinista" in error for error in errors)
