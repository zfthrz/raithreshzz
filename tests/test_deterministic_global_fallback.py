"""Equivalence tests for deterministic_global_fallback (extracted module).

The historical behavior of llm_analysis_deepseek must be preserved:
the backend re-exports the extracted function and the produced dict and
strings are exactly the historical ones.
"""

from __future__ import annotations

import ast
import inspect

import deterministic_global_fallback as fallback_module
import deterministic_text_validation as text_validation
import llm_analysis_deepseek as deepseek_module


FACTS = {
    "next_stint_plan": [
        {
            "plan_label": "A",
            "kind": "repeated_region",
            "targets": ["reducir el freno"],
            "observed_differences": ["más freno"],
        }
    ]
}
VALID_COMPARISON_RESULTS = [
    {
        "episode_ground_truth": [
            {
                "episode_id": 1,
                "action_channels": ["brake"],
                "action_evidence_by_channel": {"brake": {}},
            }
        ]
    }
]


def test_backend_reexports_the_extracted_function():
    assert (
        deepseek_module.build_deterministic_global_fallback
        is fallback_module.build_deterministic_global_fallback
    )


def test_backend_reexports_shared_numeric_validation():
    assert (
        deepseek_module.text_contains_forbidden_numeric_content
        is text_validation.text_contains_forbidden_numeric_content
    )


def test_extracted_modules_do_not_import_the_legacy_backend():
    for module in (fallback_module, text_validation):
        tree = ast.parse(inspect.getsource(module))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert "llm_analysis_deepseek" not in imported_modules


def test_shared_numeric_validation_preserves_the_contract():
    assert text_validation.text_contains_forbidden_numeric_content("20 metros")
    assert text_validation.text_contains_forbidden_numeric_content("veinte metros")
    assert text_validation.text_contains_forbidden_numeric_content("curva tres")
    assert text_validation.text_contains_forbidden_numeric_content("diez por ciento")
    assert not text_validation.text_contains_forbidden_numeric_content(
        "dos tramos con frenada progresiva"
    )
    assert not text_validation.text_contains_forbidden_numeric_content(
        "reducí el freno"
    )


def test_fallback_produces_exact_historical_dict():
    assert fallback_module.build_deterministic_global_fallback(FACTS) == {
        "opportunities": ["Zona A: reducí el freno."],
        "repeated_observations": [
            "En la zona A se repitió más freno en la misma región."
        ],
        "hypotheses": [],
        "limitations": [],
        "conclusion": (
            "Empezá la próxima tanda por la zona A: reducí el freno. "
            "Después continuá con las demás zonas prioritarias."
        ),
    }


def test_fallback_without_plan_keeps_default_strings():
    assert fallback_module.build_deterministic_global_fallback({}) == {
        "opportunities": [
            "Concentrá la próxima tanda en los inputs repetidos "
            "de las zonas prioritarias."
        ],
        "repeated_observations": [],
        "hypotheses": [],
        "limitations": [],
        "conclusion": (
            "En la próxima tanda, concentrá la ejecución en los inputs repetidos "
            "de las zonas prioritarias."
        ),
    }


def test_fallback_remains_validator_compatible():
    fallback = fallback_module.build_deterministic_global_fallback(FACTS)
    assert (
        deepseek_module.validate_global_llm_response(
            fallback,
            VALID_COMPARISON_RESULTS,
            FACTS,
        )
        == []
    )


def test_validated_default_response_is_backend_free_and_exact():
    result = fallback_module.build_validated_deterministic_global_response(
        FACTS,
        VALID_COMPARISON_RESULTS,
        validate_response=lambda response, comparisons, facts: [],
        build_priorities=lambda facts: ["Zona A: reducí el freno"],
    )
    assert result["status"] == "VALID"
    assert result["attempts"] == 0
    assert result["deterministic_first"] is True
    assert result["response"]["next_session_priorities"] == [
        "Zona A: reducí el freno"
    ]


def test_validated_default_response_fails_closed_before_priorities():
    priority_calls = []
    result = fallback_module.build_validated_deterministic_global_response(
        FACTS,
        VALID_COMPARISON_RESULTS,
        validate_response=lambda response, comparisons, facts: ["invalid"],
        build_priorities=lambda facts: priority_calls.append(True),
    )
    assert result == {
        "status": "REJECTED",
        "attempts": 0,
        "response": None,
        "validation_errors": ["invalid"],
    }
    assert priority_calls == []
