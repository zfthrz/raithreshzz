import validate_llm_analysis_output as validator


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
