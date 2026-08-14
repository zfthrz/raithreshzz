from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lmp2_elms_and_wec_remain_distinct():
    module = load_module("vehicle_context_pure_a", "vehicle_context.py")
    elms = module.classify_vehicle_class("LMP2_ELMS")
    wec = module.classify_vehicle_class("LMP2")

    assert (elms["family"], elms["variant"]) == ("LMP2", "LMP2_ELMS")
    assert (wec["family"], wec["variant"]) == ("LMP2", "LMP2_WEC")
    assert elms["variant"] != wec["variant"]


def test_supported_lmu_families_are_classified():
    module = load_module("vehicle_context_pure_b", "vehicle_context.py")
    cases = {
        "Hyper": ("HYPERCAR", "HYPER"),
        "LMGT3": ("GT3", "LMGT3"),
        "GTE": ("GTE", "GTE"),
        "LMP3": ("LMP3", "LMP3"),
    }

    for raw, expected in cases.items():
        identity = module.classify_vehicle_class(raw)
        assert (identity["family"], identity["variant"]) == expected
        assert identity["supported_domain"] is True


def test_unknown_class_is_preserved_but_not_matchable():
    module = load_module("vehicle_context_pure_c", "vehicle_context.py")
    identity = module.classify_vehicle_class("SomeFutureClass")

    assert identity["car_class_raw"] == "SomeFutureClass"
    assert identity["family"] is None
    assert identity["variant"] is None
    assert identity["supported_domain"] is False


def test_effective_setup_hash_ignores_ui_history_fields():
    module = load_module("vehicle_context_pure_d", "vehicle_context.py")

    setup_a = json.dumps({
        "VM_BRAKE_BALANCE": {
            "available": True,
            "value": 15,
            "stringValue": "53.2:46.8",
            "lastSavedStringValue": "60.0:40.0",
            "numChangesValue": 4,
            "diffComparisonValue": 10,
        },
        "gearGraph": {"topSpeed": [1, 2, 3]},
    })

    setup_b = json.dumps({
        "VM_BRAKE_BALANCE": {
            "available": True,
            "value": 15,
            "stringValue": "53.2:46.8",
            "lastSavedStringValue": "50.0:50.0",
            "numChangesValue": 99,
            "diffComparisonValue": -25,
        },
        "gearGraph": {"topSpeed": [9, 9, 9]},
    })

    assert module.effective_setup_sha256(setup_a) == module.effective_setup_sha256(setup_b)
    assert module.raw_setup_sha256(setup_a) != module.raw_setup_sha256(setup_b)


def test_effective_setup_hash_changes_with_current_setting():
    module = load_module("vehicle_context_pure_e", "vehicle_context.py")

    a = json.dumps({
        "VM_REAR_WING": {
            "available": True,
            "value": 1,
            "stringValue": "P2",
        }
    })
    b = json.dumps({
        "VM_REAR_WING": {
            "available": True,
            "value": 2,
            "stringValue": "P3",
        }
    })

    assert module.effective_setup_sha256(a) != module.effective_setup_sha256(b)


def test_orchestrator_selects_track_plus_variant_context():
    module = load_module("batch_context_pure", "prepare_calibration_batch.py")

    rows = [
        {"session_id": 1, "track": "Spa", "lmu_track_layout": "Spa", "vehicle_family": "LMP2", "vehicle_variant": "LMP2_ELMS", "vehicle_supported_domain": True},
        {"session_id": 2, "track": "Spa", "lmu_track_layout": "Spa", "vehicle_family": "LMP2", "vehicle_variant": "LMP2_ELMS", "vehicle_supported_domain": True},
        {"session_id": 3, "track": "Spa", "lmu_track_layout": "Spa", "vehicle_family": "LMP2", "vehicle_variant": "LMP2_WEC", "vehicle_supported_domain": True},
        {"session_id": 4, "track": "Monza", "lmu_track_layout": "Monza", "vehicle_family": "HYPERCAR", "vehicle_variant": "HYPER", "vehicle_supported_domain": True},
    ]

    grouped = module.group_history_by_context(rows)
    context, reason = module.choose_context(grouped, None, None, None)

    assert context == ("Spa", "Spa", "LMP2_ELMS")
    assert reason is None


def test_batch_path_contains_vehicle_variant(tmp_path):
    module = load_module("batch_path_pure", "prepare_calibration_batch.py")

    path = module.build_batch_paths(
        tmp_path,
        "Circuit de Spa-Francorchamps",
        "a" * 64,
        "LMP2_ELMS",
    )["batch_dir"]

    assert "lmp2-elms" in path.name
