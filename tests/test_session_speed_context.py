import importlib


MODULE_NAMES = (
    "llm_analysis",
    "llm_analysis_deepseek",
)


def _finding(*directions, propagation_statuses=()):
    return {
        "speed_directions": list(directions),
        "propagation_statuses": list(propagation_statuses),
    }


def test_mixed_speed_directions_render_as_variable_between_comparisons():
    expected_context = (
        "velocidad variable respecto de la referencia "
        "entre comparaciones"
    )

    for module_name in MODULE_NAMES:
        module = importlib.import_module(module_name)
        finding = _finding(
            "lower_in_comparison_lap",
            "higher_in_comparison_lap",
            propagation_statuses=("continues_losing_time",),
        )

        compact = module._finding_text_for_llm(finding)
        assert compact["speed_context"] == [
            expected_context,
            "el delta siguió empeorando después de la acción",
        ]

        rendered = module._render_speed_context_fact(finding)
        assert rendered == (
            f"{expected_context}; "
            "el delta siguió empeorando después de terminar la acción"
        )
        assert "velocidad inferior" not in rendered
        assert "velocidad superior" not in rendered


def test_single_speed_direction_keeps_existing_wording():
    for module_name in MODULE_NAMES:
        module = importlib.import_module(module_name)

        lower = _finding("lower_in_comparison_lap")
        assert module._finding_text_for_llm(lower)["speed_context"] == [
            "velocidad inferior a la referencia"
        ]
        assert module._render_speed_context_fact(lower) == (
            "velocidad inferior a la referencia"
        )

        higher = _finding("higher_in_comparison_lap")
        assert module._finding_text_for_llm(higher)["speed_context"] == [
            "velocidad superior a la referencia"
        ]
        assert module._render_speed_context_fact(higher) == (
            "velocidad superior a la referencia"
        )

