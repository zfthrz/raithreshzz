from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

from tools.llm_repair_diagnostics import (
    ERROR_CHANNELS,
    ERROR_CATEGORIES,
    ERROR_FIELDS,
    aggregate_sessions,
    classify_validation_error,
    diagnose_payload,
    main,
    validation_error_channel,
    validation_error_field,
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
    assert result.prompt_policy == "production"
    assert result.comparison_count == 1
    assert result.episode_count == 1
    assert result.clean_episode_count == 1
    assert result.episodes_requiring_repair_count == 0
    assert result.repair_rate == 0.0
    assert result.clean_output is True
    assert result.validation_error_categories == {category: 0 for category in ERROR_CATEGORIES}
    assert result.validation_error_fields == {field: 0 for field in ERROR_FIELDS}
    assert result.validation_error_channels == {channel: 0 for channel in ERROR_CHANNELS}


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
    assert result.validation_error_fields == {
        "interpretation": 1,
        "recommendation": 1,
        "hypotheses": 2,
        "repeated_observations": 0,
        "next_session_priorities": 0,
        "opportunities": 1,
        "limitations": 0,
        "conclusion": 0,
        "OTHER": 0,
    }
    assert result.validation_error_channels == {
        "brake": 0,
        "throttle": 1,
        "steering": 1,
        "speed": 0,
        "UNSPECIFIED": 3,
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


def test_qwen38_27b_alias_is_identified_as_ollama():
    payload = clean_payload(model="qwen38-27b-iq3m")

    result = diagnose_payload(payload)

    assert result.backend == "ollama"


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


def test_error_field_and_channel_attribution_is_explicit():
    assert validation_error_field("hypotheses[2]: dominio no observado") == "hypotheses"
    assert validation_error_field("conclusion global: steering_magnitude no autorizado") == "conclusion"
    assert validation_error_field("mensaje sin campo") == "OTHER"
    assert validation_error_channel("interpretation: dirección factual invertida para freno") == "brake"
    assert validation_error_channel("recommendation: velocidad usada como acción") == "speed"
    assert validation_error_channel("hypotheses[0]: dominio no observado (potencia)") == "UNSPECIFIED"


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
    assert [
        (group["backend"], group["model"], group["prompt_policy"], group["track"])
        for group in aggregate["groups"]
    ] == [
        ("deepseek", "deepseek-v4-pro", "production", "Monza"),
        ("ollama", "ingenierov3", "production", "Imola"),
    ]
    assert aggregate["paired_source_count"] == 0


def test_aggregate_only_pairs_distinct_models_for_the_same_source():
    pro_payload = clean_payload(model="deepseek-v4-pro", track="Monza")
    pro_payload["metadata"]["source_json"] = r"C:\analysis\same-session.json"
    local_payload = repaired_payload()
    local_payload["metadata"]["track"] = "Monza"
    local_payload["metadata"]["source_json"] = "c:/analysis/same-session.json"
    unrelated_payload = clean_payload(model="qwen3-14b", track="Fuji")
    unrelated_payload["metadata"]["source_json"] = "C:/analysis/other-session.json"

    aggregate = aggregate_sessions(
        [
            diagnose_payload(pro_payload, path="pro.json"),
            diagnose_payload(local_payload, path="local.json"),
            diagnose_payload(unrelated_payload, path="unrelated.json"),
        ]
    )

    assert aggregate["paired_source_count"] == 1
    pair = aggregate["paired_sources"][0]
    assert pair["track"] == "Monza"
    assert pair["output_count"] == 2
    assert pair["comparison_count_consistent"] is True
    assert pair["episode_count_consistent"] is False
    assert [
        (item["backend"], item["model"], item["prompt_policy"])
        for item in pair["models"]
    ] == [
        ("deepseek", "deepseek-v4-pro", "production"),
        ("ollama", "ingenierov3", "production"),
    ]


def test_aggregate_pairs_same_model_with_distinct_prompt_policies():
    production = clean_payload(model="deepseek-v4-pro", track="Imola")
    production["metadata"]["source_json"] = "C:/analysis/imola.json"
    shadow = clean_payload(model="deepseek-v4-pro", track="Imola")
    shadow["metadata"]["source_json"] = "c:\\analysis\\imola.json"
    shadow["metadata"]["prompt_shadow"] = {
        "policy": "episode-grounding-shadow-v0.1"
    }

    aggregate = aggregate_sessions(
        [diagnose_payload(production), diagnose_payload(shadow)]
    )

    assert aggregate["paired_source_count"] == 1
    assert [
        item["prompt_policy"]
        for item in aggregate["paired_sources"][0]["models"]
    ] == ["episode-grounding-shadow-v0.1", "production"]


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
    assert report["metadata"]["diagnostic_version"] == "0.2"
    with csv_report.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["model"] == "ingenierov3"
    assert rows[0]["fields_hypotheses"] == "2"
    assert rows[0]["channels_steering"] == "1"
    output = capsys.readouterr().out
    assert "Authority: DIAGNOSTIC ONLY" in output
    assert "RESULT: PASS" in output
