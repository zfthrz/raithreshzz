param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$deepseekVerbKey = "HKCU:\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyze"
$deepseekCommandKey = Join-Path $deepseekVerbKey "command"
$ollamaVerbKey = "HKCU:\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyzeOllama"
$ollamaCommandKey = Join-Path $ollamaVerbKey "command"
$deepseekLauncher = Join-Path $PSScriptRoot "race_engineer_context_menu.cmd"
$ollamaLauncher = Join-Path $PSScriptRoot "race_engineer_context_menu_ollama.cmd"

if ($Uninstall) {
    foreach ($verbKey in @($deepseekVerbKey, $ollamaVerbKey)) {
        if (Test-Path -LiteralPath $verbKey) {
            Remove-Item -LiteralPath $verbKey -Recurse -Force
        }
    }
    Write-Host "Race Engineer context menus: REMOVED"
    exit 0
}

foreach ($launcher in @($deepseekLauncher, $ollamaLauncher)) {
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw "No se encontró el launcher: $launcher"
    }
}

New-Item -Path $deepseekVerbKey -Force | Out-Null
Set-ItemProperty -Path $deepseekVerbKey -Name "MUIVerb" -Value "Analizar con Race Engineer (DeepSeek)"
Set-ItemProperty -Path $deepseekVerbKey -Name "Icon" -Value "shell32.dll,-16739"
New-Item -Path $deepseekCommandKey -Force | Out-Null
Set-Item -Path $deepseekCommandKey -Value ('"{0}" "%1"' -f $deepseekLauncher)

New-Item -Path $ollamaVerbKey -Force | Out-Null
Set-ItemProperty -Path $ollamaVerbKey -Name "MUIVerb" -Value "Analizar con Race Engineer (ingenierov3)"
Set-ItemProperty -Path $ollamaVerbKey -Name "Icon" -Value "shell32.dll,-16739"
New-Item -Path $ollamaCommandKey -Force | Out-Null
Set-Item -Path $ollamaCommandKey -Value ('"{0}" "%1"' -f $ollamaLauncher)

Write-Host "Race Engineer context menus: INSTALLED"
Write-Host "DeepSeek launcher: $deepseekLauncher"
Write-Host "Ollama launcher: $ollamaLauncher"
Write-Host "Scope: current Windows user only"
