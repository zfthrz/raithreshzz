import json
from pathlib import Path

from race_engineer_h3_import_gui import build_import_commands, resolve_import_target


ROW = {"track": "Spa", "track_layout": "Spa", "vehicle_variant": "LMP2_ELMS"}


def test_resolve_import_target_requires_exact_read_only_ready_row(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "mode": "AUDIT_READ_ONLY",
        "history_mutated": False,
        "input_fingerprint": "fresh",
        "contexts": [{**ROW, "status": "H3_READY_TO_IMPORT"}],
    }), encoding="utf-8")

    target = resolve_import_target(state, ROW)

    assert target is not None
    assert target.vehicle_variant == "LMP2_ELMS"
    assert target.input_fingerprint == "fresh"


def test_resolve_import_target_fails_closed_for_imported_or_mutating_snapshot(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "mode": "APPLY_EXPLICIT",
        "history_mutated": True,
        "input_fingerprint": "fresh",
        "contexts": [{**ROW, "status": "H3_READY_TO_IMPORT"}],
    }), encoding="utf-8")
    assert resolve_import_target(state, ROW) is None


def test_build_import_commands_imports_one_context_then_refreshes_audits(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "mode": "AUDIT_READ_ONLY",
        "history_mutated": False,
        "input_fingerprint": "fresh",
        "contexts": [{**ROW, "status": "H3_READY_TO_IMPORT"}],
    }), encoding="utf-8")
    target = resolve_import_target(state, ROW)
    commands = build_import_commands(
        target,
        project_root=tmp_path,
        python_executable=tmp_path / "python.exe",
        materialization_state_path=tmp_path / "materialization.json",
        import_state_path=state,
        result_path=tmp_path / "result.json",
    )

    assert len(commands) == 3
    assert commands[0][1].endswith("import_h3_context.py")
    assert commands[0][commands[0].index("--track") + 1] == "Spa"
    assert commands[0][commands[0].index("--apply")] == "--apply"
    assert commands[1][1].endswith("audit_h3_materialization_readiness.py")
    assert commands[2][1].endswith("maintain_h3_imports.py")
    assert "--apply" not in commands[2]
