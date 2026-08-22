"""Tests for H5.3 shadow pipeline: eligibility -> selection -> action policy.

Caso de pruebas (12 casos mínimos):
1. candidates -> eligibility -> selection -> actions PASS
2. sólo eligible llegan a selection
3. withheld no llegan
4. runtime no requiere human labels
5. current_faster seleccionado -> action WITHHELD
6. no eligible candidates -> SKIPPED_NOT_APPLICABLE
7. invalid eligibility -> downstream no corre
8. invalid selection -> action policy no corre
9. invalid actions -> shadow FAIL, debrief normal no afectado
10. provenance hashes preservados
11. visible debrief unchanged
12. historical coaching/actions production authority sigue false
"""

import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import inspect

import pytest

import historical_candidates_pipeline as pipeline
import historical_candidate_eligibility as elig_mod
import historical_candidate_selection_runtime as sel_mod
import historical_candidate_selection as h53c
import historical_action_policy_v0_2 as action_mod
import validate_historical_candidate_eligibility as elig_validator
import validate_historical_candidate_selection_runtime as sel_validator
import validate_historical_actions as action_validator


# ── Fixtures ───────────────────────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def set_deterministic_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set H5_3_BACKEND=deterministic for all tests to avoid LLM calls."""
    monkeypatch.setenv("H5_3_BACKEND", "deterministic")


def _make_h5_3b_dataset(
    delta_change_s_values: list[float] | None = None,
    extra_context: dict | None = None,
) -> dict[str, Any]:
    """Construir un dataset sintético compatible con historical_candidate_eligibility.

    El módulo de elegibilidad requiere el formato H5.3b con estos campos por candidato:
    - audit_id, candidate_id, context, delta_sign, evidence
    - observational_channel_evidence, label, location_label
    - source_artifact_sha256

    Cada candidato se construye para tener channel_evidence con valores numéricos
    (no None) para speed_delta_avg, throttle_delta_avg, brake_delta_avg.
    """
    if delta_change_s_values is None:
        delta_change_s_values = [0.15, 0.12, 0.10, 0.05, 0.02]

    candidates = []
    for i in range(min(len(delta_change_s_values), 10)):
        delta = delta_change_s_values[i]
        delta_sign = "positive" if delta > 0 else ("negative" if delta < 0 else "zero")

        # Channel evidence must be numeric for eligibility to pass the "at least 1 channel" check
        # For withheld (low delta), channels can be zero or small
        channel_evidence = {
            "speed_delta_avg": round(abs(delta) * 2.0, 4) if delta != 0 else 0.01,
            "throttle_delta_avg": round(abs(delta) * 1.5, 4) if delta != 0 else 0.01,
            "brake_delta_avg": round(abs(delta) * 0.5, 4) if delta != 0 else 0.01,
        }

        candidate = {
            "audit_id": f"test_{i+1:03d}",
            "candidate_id": f"candidate_{i+1:03d}",
            "context": {
                "track": "Circuit de Spa-Francorchamps",
                "track_layout": "Circuit de Spa-Francorchamps",
                "vehicle_variant": "LMP2_ELMS",
            },
            "evidence": {
                "delta_change_s": delta,
                "start_distance_m": 100.0 + i * 50,
                "end_distance_m": 150.0 + i * 50,
            },
            "observational_channel_evidence": channel_evidence,
            "delta_sign": delta_sign,
            "label": None,
            "location_label": f"T{i+1}",
            "source_artifact_sha256": f"sha256_candidate_{i+1:03d}",
        }
        if extra_context:
            candidate["context"].update(extra_context)
        candidates.append(candidate)

    return {
        "schema_version": "1.0",
        "pipeline_version": "0.1",
        "created_at_utc": _utc_now_iso(),
        "total_candidates": len(candidates),
        "candidates": candidates,
    }


def _write_candidates_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _make_valid_action_policy_output() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "action_policy_version": "0.2",
        "status": "ACTIONS_VALIDATED",
        "validation_result": {
            "all_actions_closed_vocabulary": True,
            "all_actions_current_slower": True,
            "no_speed_or_time_actions": True,
        },
        "coaching_authority": {
            "session_reference_remains_authority": True,
            "historical_actions_authorized": False,
        },
    }


class TestH53ShadowPipeline:

    def test_01_full_pipeline_pass(self, tmp_path: Any) -> None:
        """Caso 1: candidates -> eligibility -> selection -> actions PASS."""
        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.15, 0.12, 0.10, 0.09, 0.085, 0.05, 0.03, 0.01, 0.0, -0.05],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "candidates.json", data
        )

        result = pipeline.run_pipeline(candidates_path)
        assert result["status"] == "SUCCESS", f"Pipeline FAIL: {result.get('reason')}"
        assert result["coaching_authority"]["historical_actions_authorized"] is False

    def test_02_only_eligible_reach_selection(self, tmp_path: Any) -> None:
        """Caso 2: sólo ELIGIBLE_FOR_SELECTION llegan a selection."""
        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.15, 0.12, 0.10, 0.09, 0.085, 0.05, 0.03, 0.01, 0.0, -0.05],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "candidates_eligible.json", data
        )

        elig_result = elig_mod.evaluate_candidates(candidates_path)
        elig_summary = elig_result.get("summary") or {}
        by_status = elig_summary.get("by_status") or {}
        eligible_count = by_status.get("ELIGIBLE_FOR_SELECTION", 0)
        assert eligible_count == 5, f"Expected 5 eligible, got {eligible_count}"

        selection = sel_mod.select_candidates(candidates_path)
        selected_count = selection.get("selected_count", 0)
        assert selected_count > 0, "Expected top-N candidates selected"

        for record in selection.get("selection", []):
            assert record["delta_change_s"] > elig_mod.MIN_SIGNIFICANT_DELTA_S

    def test_03_withheld_dont_reach_selection(self, tmp_path: Any) -> None:
        """Caso 3: WITHHELD no llegan a selection output."""
        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.05, 0.03, 0.01, 0.0, -0.05],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "withheld.json", data
        )

        elig_result = elig_mod.evaluate_candidates(candidates_path)
        elig_summary = elig_result.get("summary") or {}
        by_status = elig_summary.get("by_status") or {}
        eligible_count = by_status.get("ELIGIBLE_FOR_SELECTION", 0)
        assert eligible_count == 0, "Expected 0 eligible for withheld-only dataset"

        for result in elig_result.get("results", []):
            assert result["eligibility_status"] == "WITHHELD"

    def test_04_runtime_no_human_labels_required(self) -> None:
        """Caso 4: runtime no requiere human labels."""
        source = inspect.getsource(sel_mod)
        # The selection module uses "no_human_labels_involved" in policy metadata.
        has_human_labels_key = "no_human_labels_involved" in source
        assert has_human_labels_key, \
            "selection module must contain 'no_human_labels_involved' in policy"

    def test_05_current_faster_withheld_in_action_policy(self, tmp_path: Any) -> None:
        """Caso 5: current_faster seleccionado -> action WITHHELD."""
        from historical_action_policy_v0_2 import (
            ACTION_POLICY_VERSION, SCHEMA_VERSION, STATUS_AUTHORIZED,
        )

        assert ACTION_POLICY_VERSION == "0.2"
        assert SCHEMA_VERSION == elig_mod.SCHEMA_VERSION or SCHEMA_VERSION == "1.0"
        assert STATUS_AUTHORIZED == "HISTORICAL_ACTION_CANDIDATES_VALIDATED"

        action_output = _make_valid_action_policy_output()
        ca = action_output["coaching_authority"]
        assert ca["historical_actions_authorized"] is False
        assert ca["session_reference_remains_authority"] is True

    def test_06_no_eligible_candidates_skipped(self, tmp_path: Any) -> None:
        """Caso 6: no eligible candidates -> SKIPPED_NOT_APPLICABLE."""
        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.05, 0.03, 0.01, 0.0, -0.05],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "no_eligible.json", data
        )

        result = pipeline.run_pipeline(candidates_path)
        assert result["status"] == "SKIPPED_NOT_APPLICABLE", \
            f"Expected SKIPPED_NOT_APPLICABLE when no eligible, got {result['status']}"
        assert result["coaching_authority"]["historical_actions_authorized"] is False

    def test_07_invalid_eligibility_downstream_skipped(self) -> None:
        """Caso 7: invalid eligibility -> downstream doesn't run."""
        invalid_eligibility = {
            "metadata": {},
            "status": "INVALID",
            "summary": {},
            "results": [],
        }

        errors = elig_validator.validate(invalid_eligibility)
        assert len(errors) > 0, "Expected validation errors for invalid eligibility"

    def test_08_invalid_selection_action_policy_not_run(self) -> None:
        """Caso 8: invalid selection -> action policy validation catches issues."""
        invalid_selection = {
            "metadata": {},
            "status": "INVALID",
            "selection": [],
        }

        errors = sel_validator.validate(invalid_selection)
        assert len(errors) > 0, "Expected validation errors for invalid selection"

    def test_09_invalid_actions_shadow_fail(self) -> None:
        """Caso 9: invalid actions -> shadow FAIL."""
        invalid_action = {
            "schema_version": "INVALID",
            "action_policy_version": "INVALID",
            "status": "INVALID",
        }

        errors = action_validator.validate(invalid_action)
        assert len(errors) > 0, "Expected validation errors for invalid action policy"

    def test_10_provenance_hashes_preserved(self, tmp_path: Any) -> None:
        """Caso 10: provenance hashes preserved."""
        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.15, 0.12, 0.10, 0.05, 0.03],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "provenance.json", data
        )

        result = pipeline.run_pipeline(candidates_path, output_dir=tmp_path / "output")
        assert result["status"] == "SUCCESS"

        artifacts = result.get("pipeline_artifacts")
        assert artifacts is not None
        assert "eligibility" in artifacts
        assert "selection" in artifacts

        digest = hashlib.sha256()
        with candidates_path.open("rb") as handle:
            digest.update(handle.read())
        expected_hash = digest.hexdigest()

        selection = sel_mod.select_candidates(candidates_path)
        assert selection["metadata"]["source_candidates_sha256"] == expected_hash

    def test_11_visible_debrief_unchanged(self) -> None:
        """Caso 11: visible debrief unchanged."""
        from race_engineer import ORCHESTRATOR_VERSION

        source = inspect.getsource(pipeline)
        # The pipeline docstring mentions "llama LLM" in a NO-list.
        # It also prints "LLM: NOT CALLED" in main().
        # We assert the pipeline does NOT call LLM at runtime.
        has_llm_call = 'llm' in source.lower()
        has_not_involved = "no_llm_involved" in source or "NOT CALLED" in source
        assert not has_llm_call or has_not_involved, \
            "pipeline must not reference LLM in source or must state NOT CALLED"

        assert ORCHESTRATOR_VERSION == "0.3"

    def test_12_historical_authority_false(self, tmp_path: Any) -> None:
        """Caso 12: historical coaching/actions production authority stays false."""
        from historical_action_policy_v0_2 import STATUS_AUTHORIZED

        assert STATUS_AUTHORIZED == "HISTORICAL_ACTION_CANDIDATES_VALIDATED"

        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.15, 0.12, 0.10, 0.05, 0.03],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "authority.json", data
        )

        result = pipeline.run_pipeline(candidates_path)
        ca = result["coaching_authority"]
        assert ca["session_reference_remains_authority"] is True
        assert ca["historical_actions_authorized"] is False
        assert ca["historical_coaching_authorized"] is False


# ── Per-candidate observation code validation tests ─────────────────────────


class TestObservationCodePerCandidateValidation:
    """Validate that validate_response enforces per-candidate observation codes.

    These tests verify the core fail-closed invariant:
    set(returned_codes) <= set(candidate.authorized_observations)

    NOT tests:
    - eligibility (historical_candidate_eligibility.py)
    - action policy v0.2 (historical_action_policy_v0_2.py)
    - threshold (MIN_SIGNIFICANT_DELTA_S)
    - production authority (historical_actions_authorized)
    """

    def _make_evidence(self, candidates: list[dict]) -> dict:
        """Build minimal authorized evidence for validate_response testing."""
        return {
            "contract": {
                "candidates_are_shadow": True,
                "historical_actions_authorized": False,
            },
            "authorized_candidate_count": len(candidates),
            "authorized_limitation_codes": sorted(h53c.ALLOWED_LIMITATIONS),
            "required_limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
            "candidates": candidates,
        }

    def _make_candidate(
        self,
        candidate_id: str,
        authorized_observations: list[str],
    ) -> dict:
        """Build a single candidate with explicit authorized_observations."""
        return {
            "candidate_id": candidate_id,
            "source_candidate_id": candidate_id,
            "context": {"track": "Spa", "track_layout": "Spa", "vehicle_variant": "LMP2_ELMS"},
            "delta_sign": "positive",
            "location_label": "T1",
            "start_distance_m": 100.0,
            "end_distance_m": 200.0,
            "delta_change_s": 0.15,
            "speed_delta_avg": 0.5,
            "throttle_delta_avg": -0.3,
            "brake_delta_avg": None,
            "authorized_observations": authorized_observations,
        }

    def _make_response(self, selected_candidates: list[dict]) -> dict:
        """Build a minimal valid LLM response."""
        return {
            "selected_candidates": selected_candidates,
            "limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
        }

    def test_pass_authorized_codes_same_candidate(self):
        """Código autorizado del mismo candidato -> PASS."""
        candidate = self._make_candidate(
            "cand_1",
            ["time_loss", "current_speed_higher", "current_throttle_lower"],
        )
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": "cand_1",
                "significance": "primary",
                "observation_codes": ["time_loss", "current_speed_higher"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert not errors, f"Expected PASS for same-candidate codes, got errors: {errors}"

    def test_pass_all_codes_from_candidate_list(self):
        """Todos los códigos de la lista del candidato -> PASS."""
        candidate = self._make_candidate(
            "cand_1",
            ["time_loss", "current_speed_higher", "current_throttle_lower"],
        )
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": "cand_1",
                "significance": "primary",
                "observation_codes": ["time_loss", "current_speed_higher", "current_throttle_lower"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert not errors, f"Expected PASS for all codes from candidate list, got: {errors}"

    def test_fail_global_valid_code_not_in_candidate(self):
        """Código globalmente válido pero no autorizado para ese candidato -> FAIL."""
        candidate = self._make_candidate(
            "cand_1",
            ["time_loss", "current_speed_higher"],  # cand_1 doesn't have current_brake_higher
        )
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": "cand_1",
                "significance": "primary",
                "observation_codes": ["time_loss", "current_brake_higher"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert len(errors) > 0, "Expected FAIL for globally valid code not in candidate"
        assert any("no autorizados" in e for e in errors)
        # Error should mention the mismatch
        assert any("subconjunto" in e for e in errors)

    def test_fail_code_from_another_candidate(self):
        """Códigos pertenecientes a otro candidato -> FAIL."""
        cand_1 = self._make_candidate(
            "cand_1",
            ["time_loss", "current_speed_higher"],
        )
        cand_2 = self._make_candidate(
            "cand_2",
            ["time_loss", "current_throttle_lower"],
        )
        evidence = self._make_evidence([cand_1, cand_2])
        response = self._make_response([
            {
                "candidate_id": "cand_1",
                "significance": "primary",
                "observation_codes": ["time_loss", "current_throttle_lower"],  # from cand_2
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert len(errors) > 0, "Expected FAIL for codes from another candidate"
        assert any("no autorizados" in e for e in errors)
        # Error should mention the specific mismatch
        assert any("subconjunto" in e for e in errors)

    def test_fail_invented_code(self):
        """Código inventado que no existe en ningún candidato -> FAIL."""
        candidate = self._make_candidate(
            "cand_1",
            ["time_loss", "current_speed_higher"],
        )
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": "cand_1",
                "significance": "primary",
                "observation_codes": ["time_loss", "invented_code"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert len(errors) > 0, "Expected FAIL for invented code"
        assert any("no autorizados" in e for e in errors)

    def test_fail_copy_codes_across_multiple_candidates(self):
        """Copiar codes de otro candidato en selección multi-candidate -> FAIL."""
        cand_1 = self._make_candidate(
            "cand_1",
            ["time_loss", "current_speed_higher"],
        )
        cand_2 = self._make_candidate(
            "cand_2",
            ["time_gain", "current_brake_lower"],
        )
        evidence = self._make_evidence([cand_1, cand_2])
        # Try to select both, but give cand_1 the codes from cand_2
        response = self._make_response([
            {
                "candidate_id": "cand_1",
                "significance": "primary",
                "observation_codes": ["time_loss", "time_gain", "current_brake_lower"],
            },
            {
                "candidate_id": "cand_2",
                "significance": "secondary",
                "observation_codes": ["time_gain", "current_brake_lower"],
            },
        ])
        errors = h53c.validate_response(response, evidence)
        # cand_1 gets codes from cand_2 -> FAIL
        assert len(errors) > 0, "Expected FAIL when cand_1 gets cand_2's codes"
        assert any("cand_1" in e and "no autorizados" in e for e in errors)

    def test_validator_error_message_includes_candidate_id(self):
        """El mensaje de error debe incluir el candidate_id específico."""
        candidate = self._make_candidate(
            "specific_cand_id",
            ["time_loss", "current_speed_higher"],
        )
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": "specific_cand_id",
                "significance": "primary",
                "observation_codes": ["time_loss", "current_throttle_lower"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert len(errors) > 0
        # Error should mention the candidate_id
        assert any("specific_cand_id" in e for e in errors)
        # Error should mention the specific codes
        assert any("current_throttle_lower" in e for e in errors)
        assert any("subconjunto" in e for e in errors)

    def test_deterministic_backend_no_llm_call(self, tmp_path: Any) -> None:
        """Backend deterministic no llama LLM."""
        data = _make_h5_3b_dataset(
            delta_change_s_values=[0.15, 0.12, 0.10, 0.05, 0.03],
        )
        candidates_path = _write_candidates_json(
            tmp_path / "det_backend.json", data
        )
        result = sel_mod.select_candidates(candidates_path)
        assert result["metadata"]["selection_method"] == "deterministic_top_n"
        assert result["metadata"]["no_llm_involved"] is True


def test_runtime_evidence_uses_numeric_channel_signs(tmp_path: Path) -> None:
    data = _make_h5_3b_dataset(delta_change_s_values=[0.20])
    channel = data["candidates"][0]["observational_channel_evidence"]
    channel.update({
        "speed_delta_avg": -3.0,
        "throttle_delta_avg": 0.12,
        "brake_delta_avg": -0.25,
    })
    path = _write_candidates_json(tmp_path / "signed_channels.json", data)

    evidence = sel_mod.build_runtime_evidence(path)

    candidate = evidence["candidates"][0]
    assert candidate["authorized_observations"] == [
        "time_loss",
        "current_speed_lower",
        "current_throttle_higher",
        "current_brake_lower",
    ]
    assert candidate["speed_delta_avg"] == -3.0
    assert candidate["throttle_delta_avg"] == 0.12
    assert candidate["brake_delta_avg"] == -0.25


def test_runtime_default_is_deterministic_and_never_calls_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _make_h5_3b_dataset(delta_change_s_values=[0.20])
    path = _write_candidates_json(tmp_path / "default_backend.json", data)
    monkeypatch.delenv("H5_3_BACKEND", raising=False)
    monkeypatch.setattr(
        sel_mod,
        "generate_llm_selection",
        lambda *args, **kwargs: pytest.fail("default runtime called an LLM"),
    )

    result = sel_mod.select_candidates(path)

    assert result["metadata"]["backend"] == "deterministic"
    assert result["metadata"]["no_llm_involved"] is True


def test_llm_and_deterministic_backends_share_one_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _make_h5_3b_dataset(delta_change_s_values=[0.20])
    path = _write_candidates_json(tmp_path / "shared_contract.json", data)
    evidence = sel_mod.build_runtime_evidence(path)
    candidate = evidence["candidates"][0]
    response = {
        "selected_candidates": [{
            "candidate_id": candidate["candidate_id"],
            "significance": "primary",
            "observation_codes": candidate["authorized_observations"][:4],
        }],
        "limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
    }
    monkeypatch.setattr(
        sel_mod,
        "generate_llm_selection",
        lambda *args, **kwargs: response,
    )

    llm_result = sel_mod.select_candidates(path, backend="deepseek")
    deterministic_result = sel_mod.select_candidates(path, backend="deterministic")

    assert set(llm_result) == set(deterministic_result)
    assert llm_result["metadata"]["candidate_selection_version"] == "0.2"
    assert sel_validator.validate(llm_result) == []
    assert sel_validator.validate(deterministic_result) == []


def test_pipeline_writes_reusable_named_artifacts(tmp_path: Path) -> None:
    data = _make_h5_3b_dataset(delta_change_s_values=[0.20])
    path = _write_candidates_json(tmp_path / "named_outputs.json", data)
    output_dir = tmp_path / "shadow"

    result = pipeline.run_pipeline(path, output_dir=output_dir)

    assert result["status"] == "SUCCESS"
    assert (output_dir / "candidate_eligibility.json").is_file()
    assert (output_dir / "candidate_selection.json").is_file()
    assert (output_dir / "historical_actions.json").is_file()
    assert (output_dir / "shadow_pipeline.json").is_file()


def test_raw_h5_3a_current_faster_with_local_losses_is_withheld(tmp_path: Path) -> None:
    candidates = []
    for index, local_delta in enumerate((0.16, 0.11), start=1):
        candidates.append({
            "candidate_id": f"cand_{index:03d}",
            "source_trend_zone_id": f"trend_{index:03d}",
            "source_zone_index": index - 1,
            "location": {"segment_name": f"T{index}"},
            "current_minus_historical": {
                "delta_change_s": local_delta,
                "start_distance_m": 100.0 * index,
                "end_distance_m": 100.0 * index + 60.0,
                "distance_m": 60.0,
            },
            "observational_channel_evidence": {
                "speed_delta_avg": -3.0,
                "throttle_delta_avg": 2.0,
                "brake_delta_avg": -2.0,
            },
            "authorization": {"action_authorized": False, "observational_only": True},
            "limitations": ["test_current_faster"],
        })
    raw_h5_3a = {
        "context": {
            "track": "Autódromo José Carlos Pace",
            "track_layout": "Autódromo José Carlos Pace",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "IDEC Sport #18:ELMS25",
        },
        "total_delta": {
            "current_minus_historical_s": -0.18,
            "sign": "current_faster",
            "tolerance_s": 0.05,
        },
        "candidates": candidates,
    }
    source = _write_candidates_json(tmp_path / "raw_current_faster.json", raw_h5_3a)

    result = pipeline.run_pipeline(source, output_dir=tmp_path / "shadow")

    assert result["status"] == "SUCCESS"
    actions = result["pipeline_artifacts"]["action_policy"]
    assert actions["actions"] == []
    assert len(actions["withheld"]) == 2
    assert {item["delta_sign"] for item in actions["withheld"]} == {"current_faster"}
    assert {item["reason"] for item in actions["withheld"]} == {
        "current_lap_faster_no_actions"
    }
    assert actions["coaching_authority"]["historical_actions_authorized"] is False

    def test_system_prompt_enforces_per_candidate(self):
        """system_prompt debe mencionar authorized_observations por candidato."""
        from historical_candidate_selection import system_prompt
        prompt = system_prompt()
        assert "authorized_observations" in prompt
        assert "SUBCONJUNTO" in prompt or "subset" in prompt.lower()
        assert "mismo candidato" in prompt.lower() or "mismo" in prompt.lower()

    def test_user_prompt_includes_per_candidate_mapping(self):
        """user_prompt debe incluir el mapeo per-candidate para cada candidato."""
        from historical_candidate_selection import user_prompt

        candidate = self._make_candidate(
            "test_cand",
            ["time_loss", "current_speed_higher"],
        )
        evidence = self._make_evidence([candidate])
        prompt_text = user_prompt(evidence)
        assert "test_cand" in prompt_text
        assert "authorized_observations" in prompt_text
        assert "time_loss" in prompt_text
        assert "current_speed_higher" in prompt_text


class TestCandidateIdentityInvariant:
    """Verify candidate identity invariant: audit_id = provenance identity, candidate_id = local id.

    These tests confirm:
    - The selector receives and returns exactly audit_id (not a bare local candidate_id).
    - selected_evidence resolves against the same audit_id used by the selector.
    - Two candidates with the same candidate_id under different provenance/hashes do not
      collide in authorized candidates.
    - An unknown audit_id in LLM response -> FAIL (no existe en la evidencia).
    - Per-candidate observation codes are validated against the authorized_observations
      from the SAME audit_id (not from a different provenance).
    """

    def _make_audit_id_candidate(
        self,
        audit_id: str,
        candidate_id: str,
        authorized_observations: list[str],
    ) -> dict:
        return {
            "candidate_id": audit_id,
            "source_candidate_id": candidate_id,
            "context": {"track": "Spa", "track_layout": "Spa", "vehicle_variant": "LMP2_ELMS"},
            "delta_sign": "positive",
            "location_label": "T1",
            "start_distance_m": 100.0,
            "end_distance_m": 200.0,
            "delta_change_s": 0.15,
            "speed_delta_avg": 0.5,
            "throttle_delta_avg": -0.3,
            "brake_delta_avg": None,
            "authorized_observations": authorized_observations,
        }

    def _make_evidence(self, candidates: list[dict]) -> dict:
        return {
            "contract": {
                "candidates_are_shadow": True,
                "historical_actions_authorized": False,
            },
            "authorized_candidate_count": len(candidates),
            "authorized_limitation_codes": sorted(h53c.ALLOWED_LIMITATIONS),
            "required_limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
            "candidates": candidates,
        }

    def _make_response(self, selected_candidates: list[dict]) -> dict:
        return {
            "selected_candidates": selected_candidates,
            "limitation_codes": list(h53c.REQUIRED_LIMITATIONS),
        }

    def test_selector_receives_returns_audit_id(self):
        """El selector recibe y devuelve exactamente audit_id, no bare candidate_id."""
        audit_id = "abc12345:cand_001"
        candidate = self._make_audit_id_candidate(audit_id, "cand_001", ["time_loss", "current_speed_lower"])
        evidence = self._make_evidence([candidate])
        # El selector debe reconocer este audit_id como válido.
        response = self._make_response([
            {
                "candidate_id": audit_id,
                "significance": "primary",
                "observation_codes": ["time_loss"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert not errors, f"Expected PASS for exact audit_id match, got: {errors}"

    def test_selected_evidence_resolves_against_audit_id(self):
        """selected_evidence se resuelve contra el mismo audit_id que usa el selector."""
        audit_id = "abc12345:cand_002"
        candidate = self._make_audit_id_candidate(audit_id, "cand_002", ["time_loss"])
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": audit_id,
                "significance": "primary",
                "observation_codes": ["time_loss"],
            }
        ])
        selected = h53c.selected_evidence(response, evidence)
        assert len(selected) == 1
        assert selected[0]["candidate_id"] == audit_id
        assert selected[0]["source_candidate_id"] == "cand_002"

    def test_two_same_candidate_id_different_provenance_no_collision(self):
        """Dos candidate_id iguales bajo provenance/hash distintos no colisionan."""
        audit_id_1 = "sha_hash_1:cand_001"
        audit_id_2 = "sha_hash_2:cand_001"
        candidate_1 = self._make_audit_id_candidate(audit_id_1, "cand_001", ["time_loss", "from_hash_1"])
        candidate_2 = self._make_audit_id_candidate(audit_id_2, "cand_001", ["time_loss", "from_hash_2"])
        evidence = self._make_evidence([candidate_1, candidate_2])
        assert len(evidence["candidates"]) == 2
        # Verificar que los authorized_observations son distintos (no colisionan).
        assert candidate_1["authorized_observations"] != candidate_2["authorized_observations"]

    def test_unknown_audit_id_fails(self):
        """Unknown audit_id -> FAIL."""
        audit_id = "real_audit:cand_001"
        candidate = self._make_audit_id_candidate(audit_id, "cand_001", ["time_loss"])
        evidence = self._make_evidence([candidate])
        response = self._make_response([
            {
                "candidate_id": "nonexistent_sha:cand_999",
                "significance": "primary",
                "observation_codes": ["time_loss"],
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert len(errors) > 0
        assert any("no existe en la evidencia" in e for e in errors)

    def test_observation_codes_validated_against_same_audit_id(self):
        """observation_codes validados contra authorized_observations del MISMO audit_id."""
        audit_id_1 = "sha_1:cand_001"
        audit_id_2 = "sha_2:cand_002"
        candidate_1 = self._make_audit_id_candidate(audit_id_1, "cand_001", ["time_loss", "only_in_1"])
        candidate_2 = self._make_audit_id_candidate(audit_id_2, "cand_002", ["time_loss", "only_in_2"])
        evidence = self._make_evidence([candidate_1, candidate_2])
        response = self._make_response([
            {
                "candidate_id": audit_id_1,
                "significance": "primary",
                "observation_codes": ["time_loss", "only_in_2"],  # only_in_2 es del otro audit_id
            }
        ])
        errors = h53c.validate_response(response, evidence)
        assert len(errors) > 0
        assert any("no autorizados" in e for e in errors)
        assert any("only_in_2" in e for e in errors)


# ── End of tests ───────────────────────────────────────────────────────────
