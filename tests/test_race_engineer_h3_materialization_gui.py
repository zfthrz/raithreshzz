import io
import json
from pathlib import Path

from race_engineer_h3_materialization_gui import (
    H3MaterializationTarget,
    build_materialization_commands,
    resolve_materialization_target,
    stream_commands,
)


ROW = {
    "track": "Spa",
    "track_layout": "Spa GP",
    "vehicle_variant": "LMP2_ELMS",
}


def test_resolves_only_exact_ready_read_only_snapshot(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "mode": "AUDIT_READ_ONLY",
        "history_mutated": False,
        "files_written": 0,
        "input_fingerprint": "abc",
        "contexts": [{**ROW, "status": "MATERIALIZATION_READY"}],
    }), encoding="utf-8")

    target = resolve_materialization_target(state, ROW)

    assert target == H3MaterializationTarget("Spa", "Spa GP", "LMP2_ELMS", "abc")
    assert resolve_materialization_target(state, {**ROW, "vehicle_variant": "GT3"}) is None


def test_invalid_or_nonready_snapshot_disables_target(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "mode": "APPLY_EXPLICIT",
        "history_mutated": True,
        "files_written": 3,
        "input_fingerprint": "abc",
        "contexts": [{**ROW, "status": "MATERIALIZATION_READY"}],
    }), encoding="utf-8")

    assert resolve_materialization_target(state, ROW) is None


def test_commands_apply_one_context_then_refresh_both_snapshots(tmp_path: Path):
    commands = build_materialization_commands(
        H3MaterializationTarget("Spa", "Spa GP", "LMP2_ELMS", "abc"),
        project_root=tmp_path,
        python_executable=tmp_path / "python.exe",
        materialization_state_path=tmp_path / "materialization.json",
        import_state_path=tmp_path / "imports.json",
        result_path=tmp_path / "result.json",
    )

    assert len(commands) == 3
    assert commands[0][1].endswith("materialize_h3_context.py")
    assert "--apply" in commands[0]
    assert commands[0][commands[0].index("--expected-input-fingerprint") + 1] == "abc"
    assert commands[1][1].endswith("audit_h3_materialization_readiness.py")
    assert commands[2][1].endswith("maintain_h3_imports.py")
    assert "--apply" not in commands[2]


def test_stream_stops_before_refresh_when_materialization_fails(tmp_path: Path):
    calls = []

    class Process:
        def __init__(self, code):
            self.stdout = io.StringIO("line\n")
            self.code = code

        def wait(self):
            return self.code

    def popen(command, **_kwargs):
        calls.append(command)
        return Process(2 if len(calls) == 1 else 0)

    lines = []
    code = stream_commands(
        [("first",), ("second",)],
        project_root=tmp_path,
        on_line=lines.append,
        popen_factory=popen,
    )

    assert code == 2
    assert calls == [["first"]]
    assert lines == ["line"]
