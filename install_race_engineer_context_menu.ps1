param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$verbKey = "HKCU:\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyze"
$commandKey = Join-Path $verbKey "command"
$launcher = Join-Path $PSScriptRoot "race_engineer_context_menu.cmd"

if ($Uninstall) {
    if (Test-Path -LiteralPath $verbKey) {
        Remove-Item -LiteralPath $verbKey -Recurse -Force
    }
    Write-Host "Race Engineer context menu: REMOVED"
    exit 0
}

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "No se encontró el launcher: $launcher"
}

New-Item -Path $verbKey -Force | Out-Null
Set-ItemProperty -Path $verbKey -Name "MUIVerb" -Value "Analizar con Race Engineer (DeepSeek)"
Set-ItemProperty -Path $verbKey -Name "Icon" -Value "shell32.dll,-16739"
New-Item -Path $commandKey -Force | Out-Null
Set-Item -Path $commandKey -Value ('"{0}" "%1"' -f $launcher)

Write-Host "Race Engineer context menu: INSTALLED"
Write-Host "Launcher: $launcher"
Write-Host "Scope: current Windows user only"
