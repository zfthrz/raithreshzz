"""
E2E pipeline test: rerender → validator → audit (no LLM).

v0.1 — Shadow evidencing pipeline integrity without changing coaching authority.
All assertions are 100 % deterministic; no LLM is called.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path


def _monza_like_fixture() -> dict:
    """
    Artifact Monza-like (10 comparisons, LMP2_ELMS) with brake + throttle cues.

    Simula un JSON generado por llm_analysis con:
    - 3 zonas;
    - zona A: brake point físico + throttle physical onset;
    - zona B: throttle profile + throttle physical;
    - zona C: steering validado.
    """
    return {
        "metadata": {
            "track": "Autodromo Nazionale Monza",
            "vehicle_variant": "LMP2_ELMS",
            "session_id": "test_monza_001",
        },
        "comparisons": [
            {
                "reference_lap": 10,
                "comparison_lap": i,
                "comparison_minus_reference_s": 0.5 * i,
            }
            for i in range(1, 11)
        ],
        "session_coaching_facts": {
            "next_stint_plan": [
                {
                    "plan_label": "A",
                    "comparison_count": 10,
                    "start_distance_m": 500.0,
                    "end_distance_m": 600.0,
                    "braking_point_patterns": [{
                        "status": "REPEATED",
                        "comparison_count": 3,
                        "authorized_numeric_coaching": True,
                        "coaching_direction": "earlier",
                        "coaching_magnitude_m": 8,
                    }],
                    "brake_release_patterns": [{
                        "status": "REPEATED",
                        "comparison_count": 2,
                        "authorized_numeric_coaching": True,
                        "coaching_direction": "later",
                        "coaching_magnitude_m": 6,
                    }],
                    "throttle_onset_patterns": [{
                        "status": "REPEATED",
                        "comparison_count": 2,
                        "authorized_numeric_coaching": True,
                        "coaching_direction": "later",
                        "coaching_magnitude_m": 10,
                    }],
                    "reference_action_profiles": [],
                    "driver_cues": [{"text": "old combined cue"}],
                    "actionable_cue_count": 1,
                },
                {
                    "plan_label": "B",
                    "comparison_count": 10,
                    "start_distance_m": 1200.0,
                    "end_distance_m": 1300.0,
                    "braking_point_patterns": [],
                    "brake_release_patterns": [],
                    "throttle_onset_patterns": [{
                        "status": "REPEATED",
                        "comparison_count": 2,
                        "authorized_numeric_coaching": True,
                        "coaching_direction": "earlier",
                        "coaching_magnitude_m": 10,
                    }],
                    "reference_action_profiles": [{
                        "channel": "throttle",
                        "shape_summary": "reaplicación sostenida sin volver a soltar dentro de la zona",
                        "steps": [{"kind": "reapplication"}],
                    }],
                    "driver_cues": [{"text": "old throttle cue"}],
                    "actionable_cue_count": 1,
                },
                {
                    "plan_label": "C",
                    "comparison_count": 10,
                    "start_distance_m": 2000.0,
                    "end_distance_m": 2100.0,
                    "braking_point_patterns": [],
                    "brake_release_patterns": [],
                    "throttle_onset_patterns": [],
                    "reference_action_profiles": [],
                    "driver_cues": [{"text": "old steering cue"}],
                    "actionable_cue_count": 1,
                    "steering_coaching_requested": True,
                    "validated_recommendation": "reducir la magnitud del volante",
                    "steering_direction": "higher_in_comparison_lap",
                },
            ],
            "session_priority_policy": {
                "version": "1.9",
                "actionability_policy_version": "1.6",
            },
        },
        "global_structured": {
            "repeated_observations": [],
            "next_session_priorities": [],
            "opportunities": [],
            "hypotheses": [],
            "limitations": [],
            "conclusion": "Conclusión segura",
        },
        "global_analysis": "old render",
    }


def _write_source(tmp_path: Path) -> Path:
    """Escribe el fixture como JSON fuente."""
    source_path = tmp_path / "source.json"
    source_path.write_text(
        json.dumps(_monza_like_fixture(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return source_path


def test_rerender_preserves_throttle_split_and_validator_passes(tmp_path: Path):
    """
    E2E: rerender → rebuild → driver cues → validator.

    Verifica que:
    1) rebuild_document separa throttle point de throttle profile;
    2) driver_cues resultante contiene ambos;
    3) el documento resultante pasa el validator;
    4) session_priority_policy se actualiza a policy v1.9.
    """
    import rerender_llm_analysis_output as rerender
    from validate_llm_analysis_output import validate_file

    source = _write_source(tmp_path)
    output = tmp_path / "rerendered.json"

    document = _monza_like_fixture()
    rebuilt = rerender.rebuild_document(document, source_path=source)

    # 1) Zona A debe tener brake point + throttle onset como cues separados
    zone_a = rebuilt["session_coaching_facts"]["next_stint_plan"][0]
    cue_texts = [cue["text"] for cue in zone_a["driver_cues"]]
    assert zone_a["actionable_cue_count"] == len(zone_a["driver_cues"])
    assert zone_a["actionable_cue_count"] >= 2
    assert any("reaplicá el acelerador" in text for text in cue_texts)
    assert any("freno" in text.lower() or "aplique" in text.lower() for text in cue_texts)

    # 2) Zona B debe tener throttle point + profile como cues separados
    zone_b = rebuilt["session_coaching_facts"]["next_stint_plan"][1]
    zone_b_texts = [cue["text"] for cue in zone_b["driver_cues"]]
    assert zone_b["actionable_cue_count"] == len(zone_b["driver_cues"])
    assert zone_b["actionable_cue_count"] >= 2
    assert any("reaplicá y sostené" in text for text in zone_b_texts)

    # 3) Validator debe pasar sin LLM
    output.write_text(
        json.dumps(rebuilt, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    errors, warnings = validate_file(output)
    assert rebuilt["metadata"]["deterministic_rerender"]["llm_called"] is False
    assert rebuilt["metadata"]["deterministic_rerender"]["actionability_policy_version"] == "1.7"

    # 4) session_priority_policy se actualiza
    policy = rebuilt["session_coaching_facts"]["session_priority_policy"]
    assert policy["version"] == "1.9"
    assert policy["actionability_policy_version"] == "1.7"


def test_auditor_classifies_rerendered_zones(tmp_path: Path):
    """
    E2E: rerender → auditor (audit_session_plan_actionability).

    Verifica que el auditor clasifica correctamente las zonas del artifact
    después del rerender.
    """
    import rerender_llm_analysis_output as rerender

    source = _write_source(tmp_path)
    rerender_json = tmp_path / "rerender.json"
    rebuilt = rerender.rebuild_document(_monza_like_fixture(), source_path=source)
    rerender_json.write_text(
        json.dumps(rebuilt, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    from audit_session_plan_actionability import audit_document

    result = audit_document(rerender_json, json.loads(rerender_json.read_text()))
    assert result["session_priority_policy_version"] == "1.9"
    assert result["actionability_policy_version"] == "1.7"

    # Zona A: brake physical point (single o multiple)
    zone_a = result["zones"][0]
    assert zone_a["primary_cue"]["channel"] == "brake"
    assert zone_a["primary_cue"]["directness_class"] in {
        "single_physical_point",
        "multiple_physical_points",
    }

    # Zona B: throttle profile
    zone_b = result["zones"][1]
    assert zone_b["primary_cue"]["channel"] == "throttle"
    assert zone_b["primary_cue"]["directness_class"] == "physical_point_with_reference_sequence"
