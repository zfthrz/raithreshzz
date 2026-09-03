from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scheduler_control_targets_only_the_named_task_and_stops_before_disable():
    source = (ROOT / "scheduler_control.ps1").read_text(encoding="utf-8")

    assert '[string]$TaskName = "RaceEngineer-History-Ingest"' in source
    assert "Stop-ScheduledTask -TaskName $TaskName" in source
    assert "Disable-ScheduledTask -TaskName $TaskName" in source
    assert source.index("Stop-ScheduledTask") < source.index("Disable-ScheduledTask")
    assert "Enable-ScheduledTask -TaskName $TaskName" in source
    assert "Unregister-ScheduledTask" not in source
    assert "Stop-Process" not in source


def test_double_click_launcher_uses_the_sibling_controller():
    source = (ROOT / "Race Engineer Scheduler.cmd").read_text(encoding="utf-8")

    assert "powershell.exe" in source
    assert "-WindowStyle Hidden" in source
    assert '"%~dp0scheduler_control.ps1"' in source
