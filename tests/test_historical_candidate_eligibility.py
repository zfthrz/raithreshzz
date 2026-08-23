"""
tests/test_historical_candidate_eligibility.py — tests unitarios + replay

Tests:
  1. Unitarios: ELIGIBLE, WITHHELD (delta, geometría, contexto, NaN/Inf), AMBIGUOUS,
     missing individual channels, LMP2_ELMS preservado, determinismo.
  2. Retrospective replay sobre audit_dataset_full.json / audit_labels_full.json.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

import historical_candidate_eligibility as hce
from validate_historical_candidate_eligibility import validate


# ── test data fixtures ─────────────────────────────────────────────────────

def _candidate(
    candidate_id: str = "cand_001",
    audit_id: str = "test_001",
    track: str = "Fuji Speedway",
    track_layout: str = "Fuji Speedway",
    vehicle_variant: str = "LMP2_ELMS",
    delta_change_s: float = 0.10,
    start_distance_m: float = 100.0,
    end_distance_m: float = 200.0,
    delta_sign: str = "current_slower",
    speed: float | None = 0.5,
    throttle: float | None = 0.5,
    brake: float | None = 0.5,
    steering: float | None = 0.5,
    context_override: dict | None = None,
    human_label: str | None = None,
    location_label: str = "T1 Test",
) -> dict:
    """Build an internal-format candidate record matching _load_candidate()."""
    channel_evidence = {
        "speed_delta_avg": speed,
        "throttle_delta_avg": throttle,
        "brake_delta_avg": brake,
        "steering_delta_avg": steering,
    }
    record = {
        "audit_id": audit_id,
        "candidate_id": candidate_id,
        "source_artifact_sha256": hashlib.sha256(candidate_id.encode()).hexdigest(),
        "source_dataset_path": "test",
        "context": {
            "track": track,
            "track_layout": track_layout,
            "vehicle_variant": vehicle_variant,
        },
        "delta_sign": delta_sign,
        "location_label": location_label,
        "evidence": {
            "delta_change_s": delta_change_s,
            "start_distance_m": start_distance_m,
            "end_distance_m": end_distance_m,
        },
        "channel_evidence": channel_evidence,
        "human_label": human_label,
    }
    if context_override is not None:
        record["context"] = context_override
    return record


def _candidate_raw(
    candidate_id: str = "cand_001",
    audit_id: str = "test_001",
    track: str = "Fuji Speedway",
    track_layout: str = "Fuji Speedway",
    vehicle_variant: str = "LMP2_ELMS",
    delta_change_s: float = 0.10,
    start_distance_m: float = 100.0,
    end_distance_m: float = 200.0,
    delta_sign: str = "current_slower",
    speed: float | None = 0.5,
    throttle: float | None = 0.5,
    brake: float | None = 0.5,
    steering: float | None = 0.5,
) -> dict:
    """Build an H5.3b raw-format candidate record matching evaluate_candidates().

    The H5.3b dataset format uses observational_channel_evidence and label keys.
    """
    return {
        "audit_id": audit_id,
        "candidate_id": candidate_id,
        "context": {
            "track": track,
            "track_layout": track_layout,
            "vehicle_variant": vehicle_variant,
        },
        "delta_sign": delta_sign,
        "evidence": {
            "delta_change_s": delta_change_s,
            "start_distance_m": start_distance_m,
            "end_distance_m": end_distance_m,
        },
        "observational_channel_evidence": {
            "speed_delta_avg": speed,
            "throttle_delta_avg": throttle,
            "brake_delta_avg": brake,
            "steering_delta_avg": steering,
        },
        "label": "ACTIONABLE",
        "location_label": "T1 Test",
        "source_artifact_sha256": hashlib.sha256(candidate_id.encode()).hexdigest(),
    }


def _label(audit_id: str, human_label: str) -> dict:
    return {"audit_id": audit_id, "human_label": human_label}


def _make_labels(labels: list[dict]) -> dict:
    return {"labels": labels}


# ── helpers ─────────────────────────────────────────────────────────────────

def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write_temp(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _run_replay_report(dataset_path: Path) -> dict:
    """Run the pipeline on the dataset and return the output for inspection."""
    output = hce.evaluate_candidates(dataset_path)
    errors = validate(output)
    if errors:
        raise RuntimeError(f"Validator failed: {errors}")
    return output


# ── policy constant tests ──────────────────────────────────────────────────

class TestPolicyConstants:
    """Verificar constantes de política."""

    def test_min_significant_delta_is_0_08(self):
        assert hce.MIN_SIGNIFICANT_DELTA_S == 0.08

    def test_status_is_shadow(self):
        assert hce.SHADOW_STATUS == "SHADOW_ELIGIBILITY_ONLY"

    def test_eligibility_version(self):
        assert hce.ELIGIBILITY_VERSION == "0.2"


# ── unit tests ──────────────────────────────────────────────────────────────

class TestEvaluateCandidate:
    """Test individual candidate evaluation."""

    def test_slower_010_eligible(self):
        """delta_change_s=+0.10 (positive, > 0.08) -> ELIGIBLE"""
        candidate = _candidate(delta_change_s=0.10)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"

    def test_faster_010_eligible(self):
        """delta_change_s=-0.10 (negative -> WITHHELD, time gain not loss)"""
        candidate = _candidate(delta_change_s=-0.10)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"

    def test_faster_010_positive_eligible(self):
        """delta_sign=current_faster + delta_change_s=+0.10 (positive, > 0.08) -> ELIGIBLE"""
        candidate = _candidate(delta_change_s=0.10, delta_sign="current_faster")
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"

    def test_faster_010_negative_eligible(self):
        """delta_sign=current_faster + delta_change_s=-0.10 (negative -> WITHHELD)"""
        candidate = _candidate(delta_change_s=-0.10, delta_sign="current_faster")
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"

    def test_faster_010_negative_delta_withheld(self):
        """delta_sign=current_faster + delta_change_s=-0.05 (negative -> WITHHELD)"""
        candidate = _candidate(delta_change_s=-0.05, delta_sign="current_faster")
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"

    def test_slower_negative_010_withheld(self):
        """delta_change_s=-0.05 (negative -> WITHHELD, time gain)"""
        candidate = _candidate(delta_change_s=-0.05, delta_sign="current_slower")
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "insignificant_delta" in record["reason_codes"]

    def test_delta_change_s_negative_010_withheld_small(self):
        """delta_change_s=-0.05 (negative -> WITHHELD)"""
        candidate = _candidate(delta_change_s=-0.05)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "insignificant_delta" in record["reason_codes"]

    def test_slower_negative_small_withheld(self):
        """delta_change_s=-0.05 (negative -> WITHHELD, time gain)"""
        candidate = _candidate(delta_change_s=-0.05)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"

    def test_farger_positive_small_withheld(self):
        """delta_change_s=+0.05 (positive but <= 0.08 -> WITHHELD, insignificant)"""
        candidate = _candidate(delta_change_s=0.05)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "insignificant_delta" in record["reason_codes"]

    def test_human_label_no_affects_eligibility(self):
        """human_label NO altera eligibility_status"""
        # Mismo delta, diferentes human_labels -> mismo resultado
        base_candidate = _candidate(delta_change_s=0.10, delta_sign="current_slower")
        base_result = hce.evaluate_candidate(base_candidate)

        with_actionable = _candidate(delta_change_s=0.10, human_label="ACTIONABLE")
        result_actionable = hce.evaluate_candidate(with_actionable)

        with_not_comparable = _candidate(delta_change_s=0.10, human_label="NOT_COMPARABLE")
        result_not_comparable = hce.evaluate_candidate(with_not_comparable)

        with_ambiguous = _candidate(delta_change_s=0.10, human_label="AMBIGUOUS")
        result_ambiguous = hce.evaluate_candidate(with_ambiguous)

        # Todos deberían ser ELIGIBLE porque abs(delta) > 0.08
        assert base_result["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"
        assert result_actionable["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"
        # NOT_COMPARABLE ya no es WITHHELD por human_label
        assert result_not_comparable["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"
        # AMBIGUOUS ya no es AMBIGUOUS por human_label
        assert result_ambiguous["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"
        assert result_ambiguous["reason_codes"] != ["ambiguous_human_label"]

    def test_explicit_not_comparable_not_withheld(self):
        """human_label NOT_COMPARABLE ya NO es WITHHELD (eligibility determinista)"""
        candidate = _candidate(human_label="NOT_COMPARABLE")
        record = hce.evaluate_candidate(candidate)
        # No debería ser WITHHELD por human_label
        assert "not_comparable" not in record["reason_codes"]
        # Debería ser ELIGIBLE si abs(delta) > 0.08
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"

    def test_delta_0079_withheld(self):
        """0.079 -> WITHHELD (delta_change_s <= MIN_SIGNIFICANT_DELTA_S)"""
        candidate = _candidate(delta_change_s=0.079)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "insignificant_delta" in record["reason_codes"]

    def test_delta_080_withheld(self):
        """0.080 -> WITHHELD (delta_change_s <= MIN_SIGNIFICANT_DELTA_S, 0.08 <= 0.08)"""
        candidate = _candidate(delta_change_s=0.080)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "insignificant_delta" in record["reason_codes"]

    def test_zero_delta_withheld(self):
        """0.0 -> WITHHELD"""
        candidate = _candidate(delta_change_s=0.0)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "insignificant_delta" in record["reason_codes"]

    def test_negative_delta_sign_withheld(self):
        """delta_change_s=-0.50 (negative -> WITHHELD, time gain)"""
        candidate = _candidate(delta_change_s=-0.50)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"

    def test_geometry_finite_invalid(self):
        """start_distance >= end_distance -> WITHHELD"""
        candidate = _candidate(start_distance_m=200.0, end_distance_m=100.0)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "invalid_geometry" in record["reason_codes"]

    def test_geometry_zero_length(self):
        """start_distance == end_distance -> WITHHELD"""
        candidate = _candidate(start_distance_m=100.0, end_distance_m=100.0)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "invalid_geometry" in record["reason_codes"]

    def test_geometry_missing(self):
        """non-numeric start/end -> WITHHELD"""
        candidate = _candidate(start_distance_m="abc", end_distance_m=None)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "invalid_geometry" in record["reason_codes"]

    def test_context_missing(self):
        """Missing track/track_layout/vehicle_variant -> WITHHELD"""
        candidate = _candidate(track=None, track_layout=None, vehicle_variant=None)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "missing_context" in record["reason_codes"]

    def test_lmp2_elms_preserved(self):
        """LMP2_ELMS must remain distinct from LMP2"""
        candidate = _candidate(vehicle_variant="LMP2_ELMS")
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"
        assert record["candidate_context"]["vehicle_variant"] == "LMP2_ELMS"

    def test_lmp2_not_normalized(self):
        """LMP2 context must not be silently treated as LMP2_ELMS"""
        candidate_lmp2_elms = _candidate(vehicle_variant="LMP2_ELMS")
        candidate_lmp2 = _candidate(vehicle_variant="LMP2")
        rec1 = hce.evaluate_candidate(candidate_lmp2_elms)
        rec2 = hce.evaluate_candidate(candidate_lmp2)
        assert rec1["candidate_context"]["vehicle_variant"] == "LMP2_ELMS"
        assert rec2["candidate_context"]["vehicle_variant"] == "LMP2"

    def test_missing_individual_channels_permitted(self):
        """Individual missing brake/throttle/speed does NOT reject automatically"""
        candidate = _candidate(speed=None, throttle=None, brake=None)
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"
        assert record["channel_availability"]["has_speed"] is False
        assert record["channel_availability"]["has_throttle"] is False
        assert record["channel_availability"]["has_brake"] is False

    def test_profile_localization_unavailable_permitted(self):
        """profile localization unavailable does NOT automatically reject"""
        candidate = _candidate()
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"

    def test_explicit_not_comparable_not_withheld(self):
        """human_label NOT_COMPARABLE ya NO es WITHHELD por human_label (determinista)"""
        candidate = _candidate(human_label="NOT_COMPARABLE")
        record = hce.evaluate_candidate(candidate)
        # No debería ser WITHHELD por human_label
        assert "not_comparable" not in record["reason_codes"]
        # Debería ser ELIGIBLE si abs(delta) > 0.08
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"

    def test_ambiguous_label_not_affected(self):
        """human_label AMBIGUOUS ya NO es AMBIGUOUS por human_label (determinista)"""
        candidate = _candidate(delta_change_s=0.10, human_label="AMBIGUOUS")
        record = hce.evaluate_candidate(candidate)
        # No debería ser AMBIGUOUS por human_label
        assert "ambiguous_human_label" not in record["reason_codes"]
        # Debería ser ELIGIBLE si abs(delta) > 0.08
        assert record["eligibility_status"] == "ELIGIBLE_FOR_SELECTION"

    def test_nan_inf_geometry(self):
        """NaN or Inf delta or distances -> WITHHELD"""
        candidate = _candidate(delta_change_s=float("nan"))
        record = hce.evaluate_candidate(candidate)
        assert record["eligibility_status"] == "WITHHELD"
        assert "invalid_geometry" in record["reason_codes"]

        candidate_inf = _candidate(start_distance_m=float("inf"))
        record_inf = hce.evaluate_candidate(candidate_inf)
        assert record_inf["eligibility_status"] == "WITHHELD"
        assert "invalid_geometry" in record_inf["reason_codes"]

    def test_policy_invariants(self):
        """historical_actions_authorized=false, historical_coaching_authorized=false,
        session_reference_remains_authority=true"""
        candidate = _candidate()
        record = hce.evaluate_candidate(candidate)
        pol = record["contract"]["policy"]
        assert pol["historical_actions_authorized"] is False
        assert pol["historical_coaching_authorized"] is False
        assert pol["session_reference_remains_authority"] is True

    def test_no_actions_in_output(self):
        """Output must not contain actions, coaching, score, probability, rank"""
        candidate = _candidate()
        record = hce.evaluate_candidate(candidate)
        for prohibited in ("actions", "coaching", "score", "probability", "rank"):
            assert prohibited not in record

    def test_no_causality_in_output(self):
        """Output must not contain causal claims"""
        candidate = _candidate()
        record = hce.evaluate_candidate(candidate)
        assert "causal" not in record
        assert "recommendation" not in record

    def test_deterministic_output(self):
        """Running evaluate_candidate twice on same inputs must produce same output"""
        candidate = _candidate(candidate_id="cand_det", delta_change_s=0.15)
        rec1 = hce.evaluate_candidate(candidate)
        rec2 = hce.evaluate_candidate(candidate)
        assert rec1["eligibility_status"] == rec2["eligibility_status"]
        assert rec1["delta_change_s"] == rec2["delta_change_s"]

    def test_duplicate_id_validator_failure(self):
        """Duplicate candidate_id/audit_id in output must cause validator failure"""
        c1 = _candidate("cand_001", "a1", delta_change_s=0.10)
        c2 = _candidate("cand_002", "a1", delta_change_s=0.20)  # mismo audit_id
        r1 = hce.evaluate_candidate(c1)
        r2 = hce.evaluate_candidate(c2)
        output = {
            "metadata": {"schema_version": "1.0", "eligibility_version": "0.2", "status": "SHADOW_ELIGIBILITY_ONLY"},
            "policy": {"min_significant_delta_s": 0.08, "status": "SHADOW_ELIGIBILITY_ONLY",
                       "historical_actions_authorized": False, "historical_coaching_authorized": False,
                       "session_reference_remains_authority": True},
            "summary": {"total_candidates": 2, "by_status": {"ELIGIBLE_FOR_SELECTION": 2}},
            "results": [r1, r2],
        }
        errors = validate(output)
        assert any("duplicado" in e.lower() or "duplicate" in e.lower() for e in errors)

    def test_duplicate_candidate_identity_validator_failure(self):
        """Duplicate candidate_id must cause validator failure"""
        c1 = _candidate("cand_001", "a1", delta_change_s=0.10)
        c2 = _candidate("cand_001", "a2", delta_change_s=0.20)  # mismo candidate_id
        r1 = hce.evaluate_candidate(c1)
        r2 = hce.evaluate_candidate(c2)
        output = {
            "metadata": {"schema_version": "1.0", "eligibility_version": "0.2", "status": "SHADOW_ELIGIBILITY_ONLY"},
            "policy": {"min_significant_delta_s": 0.08, "status": "SHADOW_ELIGIBILITY_ONLY",
                       "historical_actions_authorized": False, "historical_coaching_authorized": False,
                       "session_reference_remains_authority": True},
            "summary": {"total_candidates": 2, "by_status": {"ELIGIBLE_FOR_SELECTION": 2}},
            "results": [r1, r2],
        }
        errors = validate(output)
        assert any("duplicado" in e.lower() or "duplicate" in e.lower() for e in errors)

    def test_historical_coaching_authorized_true_fails_validator(self):
        """historical_coaching_authorized=true must cause validator failure"""
        c1 = _candidate("cand_001", "a1", delta_change_s=0.10)
        r1 = hce.evaluate_candidate(c1)
        output = {
            "metadata": {"schema_version": "1.0", "eligibility_version": "0.2", "status": "SHADOW_ELIGIBILITY_ONLY"},
            "policy": {"min_significant_delta_s": 0.08, "status": "SHADOW_ELIGIBILITY_ONLY",
                       "historical_actions_authorized": True, "historical_coaching_authorized": True,
                       "session_reference_remains_authority": True},
            "summary": {"total_candidates": 1, "by_status": {"ELIGIBLE_FOR_SELECTION": 1}},
            "results": [r1],
        }
        errors = validate(output)
        assert any("historical_coaching_authorized" in e.lower() for e in errors)

    def test_historical_actions_authorized_true_fails_validator(self):
        """historical_actions_authorized=true must cause validator failure"""
        c1 = _candidate("cand_001", "a1", delta_change_s=0.10)
        r1 = hce.evaluate_candidate(c1)
        output = {
            "metadata": {"schema_version": "1.0", "eligibility_version": "0.2", "status": "SHADOW_ELIGIBILITY_ONLY"},
            "policy": {"min_significant_delta_s": 0.08, "status": "SHADOW_ELIGIBILITY_ONLY",
                       "historical_actions_authorized": True, "historical_coaching_authorized": False,
                       "session_reference_remains_authority": True},
            "summary": {"total_candidates": 1, "by_status": {"ELIGIBLE_FOR_SELECTION": 1}},
            "results": [r1],
        }
        errors = validate(output)
        assert any("historical_actions_authorized" in e.lower() for e in errors)


class TestEvaluateCandidates:
    """Test the full dataset evaluation pipeline."""

    def test_batch_evaluation(self):
        """Full pipeline on a mixed dataset"""
        candidates = [
            _candidate_raw("c1", "a1", delta_change_s=0.10),
            _candidate_raw("c2", "a2", delta_change_s=0.05),
            _candidate_raw("c3", "a3", delta_change_s=-0.10),
        ]
        dataset = {"candidates": candidates, "coverage": {}}

        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            ds_path = t / "dataset.json"
            _write_temp(dataset, ds_path)
            output = hce.evaluate_candidates(ds_path)

        assert len(output["results"]) == 3
        summary = output["summary"]
        by_status = summary.get("by_status", {})
        # c1 (delta +0.10) is ELIGIBLE; c2 (+0.05) and c3 (-0.10) are WITHHELD.
        assert by_status.get("ELIGIBLE_FOR_SELECTION", 0) == 1
        assert by_status.get("WITHHELD", 0) == 2

    def test_validator_passes_on_valid_output(self):
        """Validator must pass on a valid output."""
        candidate = _candidate("c1", "a1", delta_change_s=0.10)
        # For the validator, we need a batch-level output
        batch = {
            "metadata": {"schema_version": "1.0", "eligibility_version": "0.2", "status": "SHADOW_ELIGIBILITY_ONLY"},
            "policy": {"min_significant_delta_s": 0.08, "status": "SHADOW_ELIGIBILITY_ONLY",
                       "historical_actions_authorized": False, "historical_coaching_authorized": False,
                       "session_reference_remains_authority": True},
            "summary": {"total_candidates": 1, "by_status": {"ELIGIBLE_FOR_SELECTION": 1}},
            "results": [hce.evaluate_candidate(candidate)],
        }
        errors = validate(batch)
        assert not errors, f"Validator failed: {errors}"

    def test_batch_empty(self):
        """evaluate_candidates maneja dataset vacío."""
        dataset = {"candidates": [], "coverage": {}}
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            ds_path = t / "dataset.json"
            _write_temp(dataset, ds_path)
            output = hce.evaluate_candidates(ds_path)
        assert output["summary"]["total_candidates"] == 0

    def test_batch_invalid_record(self):
        """evaluate_candidates maneja registros inválidos."""
        dataset = {"candidates": ["no es dict"], "coverage": {}}
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            ds_path = t / "dataset.json"
            _write_temp(dataset, ds_path)
            output = hce.evaluate_candidates(ds_path)
        assert "ERROR" in output["summary"]["by_status"]


# ── retrospective replay ────────────────────────────────────────────────────

def _build_mismatch_report(output: dict, labels_path: Path) -> dict:
    """
    Compare eligibility_status vs human_label and report mismatches.

    Mapping:
      ELIGIBLE_FOR_SELECTION  <->  ACTIONABLE
      WITHHELD                <->  OBSERVATIONAL_ONLY / NOT_COMPARABLE
      AMBIGUOUS               <->  AMBIGUOUS

    Returns a dict with matrix, agreements, mismatches.
    """
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    label_map = {
        item["audit_id"]: item["human_label"]
        for item in labels.get("labels", [])
    }

    matrix: dict[str, dict[str, int]] = {}
    mismatches: list[dict] = []

    for record in output["results"]:
        audit_id = record["provenance"]["audit_id"]
        eligibility_status = record["eligibility_status"]
        human_label = label_map.get(audit_id, "NO_LABEL")

        if human_label == "SKIP":
            continue

        if eligibility_status not in matrix:
            matrix[eligibility_status] = {}
        matrix[eligibility_status][human_label] = (
            matrix[eligibility_status].get(human_label, 0) + 1
        )

        # Define expected mapping
        expected_eligible = human_label == "ACTIONABLE"
        actual_eligible = eligibility_status == "ELIGIBLE_FOR_SELECTION"
        if expected_eligible != actual_eligible:
            mismatches.append({
                "candidate_id": record.get("candidate_context", {}).get("candidate_id"),
                "audit_id": audit_id,
                "eligibility_status": eligibility_status,
                "human_label": human_label,
                "reason_codes": record["reason_codes"],
                "delta_change_s": record["delta_change_s"],
            })

    return {
        "matrix": matrix,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


class TestRetrospectiveReplay:
    """Retrospective policy replay on real audit data.

    This is RETROSPECTIVE POLICY REPLAY, NOT ML validation.
    NOT optimizing threshold.
    """

    @pytest.fixture(scope="module")
    def replay_output(self):
        base = Path(__file__).parent.parent / "data" / "generated" / "h5_3"
        dataset_path = base / "audit_dataset_full.json"
        return _run_replay_report(dataset_path)

    @pytest.fixture(scope="module")
    def report(self, replay_output):
        base = Path(__file__).parent.parent / "data" / "generated" / "h5_3"
        labels_path = base / "audit_labels_full.json"
        return _build_mismatch_report(replay_output, labels_path)

    def test_replay_status_counts(self, replay_output, report):
        """Report basic status distribution."""
        summary = replay_output["summary"]
        total = sum(summary["by_status"].values())
        assert total == 55, f"Expected 55 candidates, got {total}"

    def test_matrix_not_empty(self, report):
        """Matrix must have at least one cell."""
        assert len(report["matrix"]) > 0

    def test_mismatches_reported(self, report):
        """Mismatches should be reported but may exist due to threshold policy."""
        print(f"\nRetrospective Replay Mismatches: {report['mismatch_count']}")
        for m in report["mismatches"][:5]:
            print(
                f"  {m['candidate_id']}: eligibility={m['eligibility_status']} "
                f"vs human={m['human_label']} "
                f"(delta={m['delta_change_s']}, reasons={m['reason_codes']})"
            )

    def test_matrix_structure(self, report):
        """Matrix must map eligibility statuses to human labels."""
        for el_status, counts in report["matrix"].items():
            assert el_status in ("ELIGIBLE_FOR_SELECTION", "WITHHELD", "AMBIGUOUS")
            for human_label in counts:
                assert human_label in ("ACTIONABLE", "OBSERVATIONAL_ONLY", "AMBIGUOUS", "NOT_COMPARABLE", "SKIP", "NO_LABEL")

# ── H5.3a → canonical normalizer tests ─────────────────────────────────────

class TestNormalizeH53aRawCandidate:
    """Tests for normalize_h5_3a_candidate_for_eligibility()."""

    def _make_raw_h53a_candidate(
        self,
        candidate_id: str = "cand_001",
        delta_change_s: float = 0.15,
        start_distance_m: float = 100.0,
        end_distance_m: float = 200.0,
        location: dict | None = None,
        channels: dict | None = None,
    ) -> dict:
        """Build an H5.3a raw-format candidate."""
        cmh = {
            "delta_change_s": delta_change_s,
            "start_distance_m": start_distance_m,
            "end_distance_m": end_distance_m,
            "distance_m": end_distance_m - start_distance_m,
        }
        obs_channels = dict(channels) if channels is not None else {
            "speed_delta_avg": 0.5,
            "throttle_delta_avg": 0.3,
            "brake_delta_avg": 0.2,
        }
        return {
            "candidate_id": candidate_id,
            "source_trend_zone_id": f"zone_{candidate_id}",
            "source_zone_index": 0,
            "location": dict(location) if location is not None else {"segment_name": f"T{candidate_id[-1]}"},
            "current_minus_historical": cmh,
            "observational_channel_evidence": obs_channels,
            "authorization": {"action_authorized": False, "observational_only": True},
            "limitations": ["test_limitation"],
        }

    def test_raw_h53a_significant_candidate_eligible(self):
        """Test 1: raw H5.3a delta=+0.15 → canonical → ELIGIBLE."""
        raw = self._make_raw_h53a_candidate(delta_change_s=0.15)
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_slower"
            )
            # Verify normalizer output structure
            assert norm["audit_id"] == f"{hce._sha256_file(src_path)}:cand_001"
            assert norm["candidate_id"] == "cand_001"
            assert norm["delta_sign"] == "current_slower"
            assert norm["evidence"]["delta_change_s"] == 0.15
            assert norm["label"] is None
            assert norm["location_label"] == "T1"
            assert norm["source_artifact_sha256"] == hce._sha256_file(src_path)
            # Build dataset and run through evaluate_candidates
            dataset = {"context": ctx, "candidates": [norm]}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
        by_status = result["summary"]["by_status"]
        assert by_status.get("ELIGIBLE_FOR_SELECTION", 0) == 1

    def test_raw_delta_0076_withheld(self):
        """Test 2: raw H5.3a delta=+0.076 → WITHHELD (<= 0.08)."""
        raw = self._make_raw_h53a_candidate(delta_change_s=0.076)
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_slower"
            )
            assert norm["evidence"]["delta_change_s"] == 0.076
            dataset = {"context": ctx, "candidates": [norm]}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
        by_status = result["summary"]["by_status"]
        assert by_status.get("WITHHELD", 0) == 1

    def test_raw_negative_delta_withheld(self):
        """Test 3: raw H5.3a delta=-0.10 → WITHHELD (negative = time gain)."""
        raw = self._make_raw_h53a_candidate(delta_change_s=-0.10)
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_faster"
            )
            assert norm["delta_sign"] == "current_faster"
            dataset = {"context": ctx, "candidates": [norm]}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
        by_status = result["summary"]["by_status"]
        assert by_status.get("WITHHELD", 0) == 1

    def test_malformed_missing_current_minus_historical(self):
        """Test 7: missing current_minus_historical → ValueError (fail closed)."""
        raw = {"candidate_id": "cand_bad", "location": {}}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_source.json"
            src_path.write_text("{}", encoding="utf-8")
            with pytest.raises(ValueError, match="current_minus_historical"):
                hce.normalize_h5_3a_candidate_for_eligibility(raw, src_path)

    def test_malformed_missing_observational_channel_evidence(self):
        """Test 7b: missing observational_channel_evidence → ValueError."""
        raw = {"candidate_id": "cand_bad", "current_minus_historical": {}}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_source.json"
            src_path.write_text("{}", encoding="utf-8")
            with pytest.raises(ValueError, match="observational_channel_evidence"):
                hce.normalize_h5_3a_candidate_for_eligibility(raw, src_path)

    def test_audit_id_deterministic(self):
        """Test 5: audit_id is deterministic from source SHA + candidate_id."""
        raw1 = self._make_raw_h53a_candidate(candidate_id="cand_det")
        raw2 = self._make_raw_h53a_candidate(candidate_id="cand_det")
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.json"
            src_path.write_text(json.dumps(raw1, ensure_ascii=False) + "\n")
            norm1 = hce.normalize_h5_3a_candidate_for_eligibility(
                raw1, src_path, ctx, session_delta_sign="current_slower"
            )
            norm2 = hce.normalize_h5_3a_candidate_for_eligibility(
                raw2, src_path, ctx, session_delta_sign="current_slower"
            )
            assert norm1["audit_id"] == norm2["audit_id"]
            expected_sha = hce._sha256_file(src_path)
            assert norm1["audit_id"] == f"{expected_sha}:cand_det"

    def test_source_sha_deterministic(self):
        """Test 6: source_artifact_sha256 matches SHA256 of the source file."""
        raw = self._make_raw_h53a_candidate()
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_slower"
            )
            assert norm["source_artifact_sha256"] == hce._sha256_file(src_path)


class TestNormalizeH53aBatch:
    """Tests for normalize_h5_3a_candidates_for_eligibility()."""

    def _make_raw_h53a_candidate(
        self,
        candidate_id: str = "cand_001",
        delta_change_s: float = 0.15,
        start_distance_m: float = 100.0,
        end_distance_m: float = 200.0,
        location: dict | None = None,
        channels: dict | None = None,
    ) -> dict:
        """Build an H5.3a raw-format candidate."""
        cmh = {
            "delta_change_s": delta_change_s,
            "start_distance_m": start_distance_m,
            "end_distance_m": end_distance_m,
            "distance_m": end_distance_m - start_distance_m,
        }
        obs_channels = dict(channels) if channels is not None else {
            "speed_delta_avg": 0.5,
            "throttle_delta_avg": 0.3,
            "brake_delta_avg": 0.2,
        }
        return {
            "candidate_id": candidate_id,
            "source_trend_zone_id": f"zone_{candidate_id}",
            "source_zone_index": 0,
            "location": dict(location) if location is not None else {"segment_name": f"T{candidate_id[-1]}"},
            "current_minus_historical": cmh,
            "observational_channel_evidence": obs_channels,
            "authorization": {"action_authorized": False, "observational_only": True},
            "limitations": ["test_limitation"],
        }

    def _make_h53a_batch(self, delta_values: list[float]) -> dict:
        """Build a batch of H5.3a raw candidates."""
        context = {
            "track": "Autodromo Enzo e Dino Ferrari",
            "track_layout": "Autodromo Enzo e Dino Ferrari",
            "vehicle_variant": "LMP2_ELMS",
            "car_name_raw": "LMP2",
        }
        candidates = []
        for i, delta in enumerate(delta_values):
            loc = {"segment_name": f"T{i+1}"}
            channels = {
                "speed_delta_avg": abs(delta) * 0.5 if delta != 0 else 0.01,
                "throttle_delta_avg": abs(delta) * 0.3 if delta != 0 else 0.01,
                "brake_delta_avg": abs(delta) * 0.2 if delta != 0 else 0.01,
            }
            cmh = {
                "delta_change_s": delta,
                "start_distance_m": 100.0 + i * 100,
                "end_distance_m": 200.0 + i * 100,
                "distance_m": 100.0,
            }
            candidates.append({
                "candidate_id": f"cand_{i+1:03d}",
                "source_trend_zone_id": f"zone_{i}",
                "source_zone_index": i,
                "location": loc,
                "current_minus_historical": cmh,
                "observational_channel_evidence": channels,
                "authorization": {"action_authorized": False, "observational_only": True},
                "limitations": ["test_limitation"],
            })
        return {
            "context": context,
            "total_delta": {
                "current_minus_historical_s": 1.0,
                "sign": "current_slower",
                "tolerance_s": 0.05,
            },
            "candidates": candidates,
        }

    def test_9_significant_candidates_all_eligible(self):
        """Test 4: 9 significant candidates (delta > 0.08) → 9 ELIGIBLE."""
        deltas = [0.12, 0.10, 0.09, 0.15, 0.11, 0.095, 0.13, 0.085, 0.14]
        batch = self._make_h53a_batch(deltas)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_source.json"
            src_path.write_text(json.dumps(batch, ensure_ascii=False) + "\n")
            normalized = hce.normalize_h5_3a_candidates_for_eligibility(src_path)
        assert len(normalized) == 9
        # Run through evaluate_candidates on a dataset path
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dataset = {"context": batch["context"], "candidates": normalized}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
        by_status = result["summary"]["by_status"]
        assert by_status.get("ELIGIBLE_FOR_SELECTION", 0) == 9

    def test_mixed_9_significant_3_withheld(self):
        """Test: 9 significant + 3 withheld (delta <= 0.08 or negative)."""
        deltas = [0.12, 0.10, 0.09, 0.15, 0.11, 0.095, 0.13, 0.085, 0.14, 0.076, 0.05, -0.10]
        batch = self._make_h53a_batch(deltas)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "h53a_mixed.json"
            src_path.write_text(json.dumps(batch, ensure_ascii=False) + "\n")
            normalized = hce.normalize_h5_3a_candidates_for_eligibility(src_path)
            dataset = {"context": batch["context"], "candidates": normalized}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
        by_status = result["summary"]["by_status"]
        assert by_status.get("ELIGIBLE_FOR_SELECTION", 0) == 9, \
            f"Expected 9 ELIGIBLE, got {by_status}"
        assert by_status.get("WITHHELD", 0) == 3, \
            f"Expected 3 WITHHELD, got {by_status}"

    def test_global_current_faster_sign_is_not_replaced_by_local_zone_loss(self):
        batch = self._make_h53a_batch([0.16, 0.11])
        batch["total_delta"] = {
            "current_minus_historical_s": -0.18,
            "sign": "current_faster",
            "tolerance_s": 0.05,
        }
        with tempfile.TemporaryDirectory() as tmp:
            src_path = Path(tmp) / "current_faster.json"
            src_path.write_text(json.dumps(batch, ensure_ascii=False) + "\n")
            normalized = hce.normalize_h5_3a_candidates_for_eligibility(src_path)

        assert [item["delta_sign"] for item in normalized] == [
            "current_faster",
            "current_faster",
        ]
        assert [item["evidence"]["delta_change_s"] for item in normalized] == [
            0.16,
            0.11,
        ]

    def test_global_delta_sign_mismatch_fails_closed(self):
        batch = self._make_h53a_batch([0.16])
        batch["total_delta"]["sign"] = "current_faster"
        with tempfile.TemporaryDirectory() as tmp:
            src_path = Path(tmp) / "mismatch.json"
            src_path.write_text(json.dumps(batch, ensure_ascii=False) + "\n")
            with pytest.raises(ValueError, match="no coincide"):
                hce.normalize_h5_3a_candidates_for_eligibility(src_path)

    def test_malformed_batch_raises(self):
        """Test 7: malformed H5.3a batch → ValueError (fail closed)."""
        batch = {"context": {"track": "X"}, "candidates": [
            {"candidate_id": "bad_candidate"},  # missing current_minus_historical
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "malformed.json"
            src_path.write_text(json.dumps(batch, ensure_ascii=False) + "\n")
            with pytest.raises(ValueError):
                hce.normalize_h5_3a_candidates_for_eligibility(src_path)

    def test_no_human_labels_affects_normalization(self):
        """Test 8: H5.3a raw has no human labels; normalization never uses them."""
        raw = self._make_raw_h53a_candidate(delta_change_s=0.15)
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_slower"
            )
            assert norm["label"] is None
            dataset = {"context": ctx, "candidates": [norm]}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
            assert result["summary"]["by_status"].get("ELIGIBLE_FOR_SELECTION", 0) == 1

    def test_selector_receives_audit_id(self):
        """Test 10: candidate identity (audit_id) survives → selector → action policy."""
        deltas = [0.15]
        batch = self._make_h53a_batch(deltas)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "identity.json"
            src_path.write_text(json.dumps(batch, ensure_ascii=False) + "\n")
            normalized = hce.normalize_h5_3a_candidates_for_eligibility(src_path)
            # audit_id format: {sha256}:{candidate_id}
            assert normalized[0]["audit_id"].endswith(":cand_001")
            # candidate_id survives at top level
            assert normalized[0]["candidate_id"] == "cand_001"

    def test_unknown_location_label(self):
        """location empty → location_label = UNKNOWN."""
        raw = self._make_raw_h53a_candidate(location={"segment_name": ""})
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_slower"
            )
        assert norm["location_label"] == "UNKNOWN"

    def test_empty_channels_no_action_invented(self):
        """Test 11: empty observational_channel_evidence → WITHHELD (no_channel_evidence)."""
        raw = self._make_raw_h53a_candidate(channels={})
        ctx = {"track": "X", "track_layout": "X", "vehicle_variant": "LMP2_ELMS"}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src_path = tmp_path / "source.json"
            src_path.write_text(json.dumps(raw, ensure_ascii=False) + "\n")
            norm = hce.normalize_h5_3a_candidate_for_eligibility(
                raw, src_path, ctx, session_delta_sign="current_slower"
            )
            dataset = {"context": ctx, "candidates": [norm]}
            ds_path = tmp_path / "dataset.json"
            ds_path.write_text(json.dumps(dataset, ensure_ascii=False) + "\n")
            result = hce.evaluate_candidates(ds_path)
        # With no channel evidence at all, it should be WITHHELD (no_channel_evidence)
        assert result["summary"]["by_status"].get("WITHHELD", 0) == 1
