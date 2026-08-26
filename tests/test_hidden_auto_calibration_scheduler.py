from pathlib import Path
from types import SimpleNamespace

import hidden_history_ingest as hidden


class Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        return SimpleNamespace(returncode=0)


def test_hidden_maintenance_stops_after_preparing_human_review_queue(tmp_path: Path):
    runner = Runner()
    main_command = ["python", "main.py"]
    review_command = ["python", "review.py"]
    calibration_command = ["python", "calibration.py"]
    result = hidden.run_hidden_maintenance(
        log_path=tmp_path / "history.log",
        runtime_path=tmp_path / "runtime.json",
        command=main_command,
        review_command=review_command,
        calibration_command=calibration_command,
        runner=runner,
    )

    assert result == 0
    assert runner.calls == [
        main_command,
        review_command,
        calibration_command,
    ]


def test_hidden_scheduler_exposes_no_auto_promotion_command():
    assert not hasattr(hidden, "build_auto_calibration_command")
