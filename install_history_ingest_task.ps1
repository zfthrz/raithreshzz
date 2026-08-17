param(
    [string]$TaskName = "RaceEngineer-History-Ingest",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "hidden_history_ingest.py"

if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "No se encontró el runner oculto: $runner"
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = (& python -c "import sys; print(sys.executable)").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($PythonExe)) {
        throw "No se pudo resolver el ejecutable real de Python. Usá -PythonExe C:\ruta\python.exe"
    }
}

$PythonExe = [System.IO.Path]::GetFullPath($PythonExe)
$pythonw = Join-Path (Split-Path -Parent $PythonExe) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "No se encontró pythonw.exe junto a Python: $pythonw"
}

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument ('"{0}"' -f $runner) `
    -WorkingDirectory $PSScriptRoot

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action | Out-Null
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    $operation = "UPDATED"
} else {
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Race Engineer hidden History-first telemetry maintenance" | Out-Null
    $operation = "INSTALLED"
}

Write-Host "Race Engineer History task: $operation"
Write-Host "Task: $TaskName"
Write-Host "Execute: $pythonw"
Write-Host "Runner: $runner"
Write-Host "Console: HIDDEN"
Write-Host "Log: $(Join-Path $PSScriptRoot 'data\local\telemetry_auto_ingest_task.log')"
