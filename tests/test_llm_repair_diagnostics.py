from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

from tools.llm_repair_diagnostics import (
    ERROR_CATEGORIES,
    aggregate_sessions,
    classify_validation_error,
    diagnose_payload,
    main,
)


def clean_payload(*, model: str = "deepseek-v4-pro", track: str = "Monza") -> dict:
    return {
        "metadata": {"model": model, "track": track},
        "comparisons": [
            {
                "llm_validation_audit": {
                    "episodes": [
                        {
                            "episode_id": 1,
                            "attempts": 1,
                            "fallback": None,
                            "deterministic_repairs": {},
                            "pruned_hypothesis_indexes": [],
                            "original_validation_errors": [],
                        }
                    ],
                    "priority_ranking": {"attempts": 1},
                    "summary": {"attempts": 1, "fallback": None},
                }
            }
        ],
        "global_validation_audit": {
            "attempts": 1,
            "fallback": None,
            "deterministic_repairs": {},
            "pruned_global_items": [],
            "llm_validation_errors": [],
        },
    }


def repaired_payload() -> dict:
    payload = clean_payload(model="ingenierov3", track="Imola")
    payload["comparisons"][0]["llm_validation_audit"] = {
        "episodes": [
            {
                "episode_id": 1,
                "attempts": 2,
                "fallback": "PRUNED_INVALID_HYPOTHESES",
                "deterministic_repairs": {
                    "replaced_fields": ["interpretation", "recommendation"],
                    "pruned_hypothesis_indexes": [0, 1],
                    "target_reference_repairs": ["recommendation"],
                },
                # Index 1 is duplicated by the two audit representations.
                "pruned_hypothesis_indexes": [1, 2],
                "original_validation_errors": [
                    "interpretation: dirección factual invertida para acelerador.",
                    "hypotheses[0]: menciona dominio no observado (potencia).",
                    "recommendation: usa la vuelta comparada como objetivo de coaching.",
                    "hypotheses[1]: menciona steering_magnitude pero ese canal no está autorizado por action_channels.",
                ],
            },
            {
                "episode_id": 2,
                "attempts": 1,
                "fallback": None,
                "deterministic_repairs": {},
                "pruned_hypothesis_indexes": [],
                "original_validation_errors": [],
            },
        ],
        "priority_ranking": {"attempts": 2},
        "summary": {
            "attempts": 3,
            "fallback": "DETERMINISTIC_FROM_VALIDATED_EPISODES",
        },
    }
    payload["global_validation_audit"] = {
        "attempts": 2,
        "fallback": "DETERMINISTIC_GLOBAL_FROM_NEXT_STINT_PLAN",
        "deterministic_repairs": {"optional_list_overflow": True},
        "pruned_global_items": ["hypotheses"],
        "llm_validation_errors": ["opportunities: debe ser lista."],
    }
    return payload


def test_clean_output_has_zero_repair_burden_and_does_not_mutate_source():
    payload = clean_payload()
    original = copy.deepcopy(payload)

    result = diagnose_payload(payload)

    assert payload == original
    assert result.backend == "deepseek"
    assert result.comparison_count == 1
    assert result.episode_count == 1
    assert result.clean_episode_count == 1
    assert result.episodes_requiring_repair_count == 0
    assert result.repair_rate == 0.0
    assert result.clean_output is True
    assert result.validation_error_categories == {category: 0 for category in ERROR_CATEGORIES}


def test_repair_metrics_deduplicate_pruned_indexes_and_count_retries():
    result = diagnose_payload(repaired_payload())

    assert result.backend == "ollama"
    assert result.episode_count == 2
    assert result.clean_episode_count == 1
    assert result.episodes_requiring_repair_count == 1
    assert result.replaced_interpretation_count == 1
    assert result.replaced_recommendation_count == 1
    assert result.pruned_hypothesis_count == 3
    assert result.target_reference_repair_count == 1
    assert result.episode_retry_count == 1
    assert result.ranking_attempts_gt_one_count == 1
    assert result.summary_attempts_gt_one_count == 1
    assert result.global_attempts_gt_one_count == 1
    assert result.fallback_count == 3
    assert result.repair_rate == 0.5
    assert result.clean_output is False
    assert result.validation_error_categories == {
        "FACTUAL_DIRECTION_INVERSION": 1,
        "UNAUTHORIZED_CHANNEL": 1,
        "WRONG_REFERENCE_TARGET": 1,
        "UNOBSERVED_DOMAIN": 1,
        "OTHER": 1,
    }


def test_quality_gate_exclusion_is_not_counted_as_repair_fallback():
    payload = clean_payload()
    audit = payload["comparisons"][0]["llm_validation_audit"]
    audit["episodes"] = []
    audit["summary"] = {
        "attempts": 0,
        "fallback": "COMPARISON_QUALITY_GATE_EXCLUDED_BEFORE_LLM",
    }

    result = diagnose_payload(payload)

    assert result.episode_count == 0
    assert result.fallback_count == 0
    assert result.repair_rate == 0.0


def test_error_classifier_uses_closed_categories():
    cases = {
        "recommendation: dirección de coaching invertida para freno": "FACTUAL_DIRECTION_INVERSION",
        "steering_magnitude sólo puede convertirse en acción de zona A": "UNAUTHORIZED_CHANNEL",
        "usa la vuelta comparada como objetivo de coaching": "WRONG_REFERENCE_TARGET",
        "menciona dominio no observado (potencia)": "UNOBSERVED_DOMAIN",
        "opportunities: debe ser lista": "OTHER",
    }
    assert {classify_validation_error(value) for value in cases} <= set(ERROR_CATEGORIES)
    for value, expected in cases.items():
        assert classify_validation_error(value) == expected


def test_aggregate_groups_by_backend_model_and_track():
    clean = diagnose_payload(clean_payload(), path="clean.json")
    repaired = diagnose_payload(repaired_payload(), path="repaired.json")

    aggregate = aggregate_sessions([clean, repaired])

    assert aggregate["output_count"] == 2
    assert aggregate["episode_count"] == 3
    assert aggregate["episodes_requiring_repair_count"] == 1
    assert aggregate["repair_rate"] == 1 / 3
    assert aggregate["clean_output_count"] == 1
    assert aggregate["clean_output_rate"] == 0.5
    assert [(group["backend"], group["model"], group["track"]) for group in aggregate["groups"]] == [
        ("deepseek", "deepseek-v4-pro", "Monza"),
        ("ollama", "ingenierov3", "Imola"),
    ]


def test_cli_writes_optional_json_and_csv_without_rewriting_input(tmp_path: Path, capsys):
    source = tmp_path / "result.json"
    payload = repaired_payload()
    original_text = json.dumps(payload, ensure_ascii=False, indent=2)
    source.write_text(original_text, encoding="utf-8")
    json_report = tmp_path / "reports" / "repair.json"
    csv_report = tmp_path / "reports" / "repair.csv"

    assert main([str(source), "--json-report", str(json_report), "--csv-report", str(csv_report)]) == 0

    assert source.read_text(encoding="utf-8") == original_text
    report = json.loads(json_report.read_text(encoding="utf-8"))
    assert report["metadata"]["authority"] == "DIAGNOSTIC_ONLY"
    assert report["metadata"]["source_artifacts_modified"] is False
    assert report["aggregate"]["output_count"] == 1
    with csv_report.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["model"] == "ingenierov3"
    output = capsys.readouterr().out
    assert "Authority: DIAGNOSTIC ONLY" in output
    assert "RESULT: PASS" in output
