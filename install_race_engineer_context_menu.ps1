param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$productVerbKey = "HKCU:\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyze"
$productCommandKey = Join-Path $productVerbKey "command"
$ollamaVerbKey = "HKCU:\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyzeOllama"
$llamacppVerbKey = "HKCU:\Software\Classes\SystemFileAssociations\.duckdb\shell\RaceEngineerAnalyzeLlamacpp"
$productLauncher = Join-Path $PSScriptRoot "race_engineer_context_menu.cmd"
$legacyVerbKeys = @($ollamaVerbKey, $llamacppVerbKey)

if ($Uninstall) {
    foreach ($verbKey in @($productVerbKey) + $legacyVerbKeys) {
        if (Test-Path -LiteralPath $verbKey) {
            Remove-Item -LiteralPath $verbKey -Recurse -Force
        }
    }
    Write-Host "Race Engineer context menus: REMOVED"
    exit 0
}

if (-not (Test-Path -LiteralPath $productLauncher -PathType Leaf)) {
    throw "No se encontró el launcher: $productLauncher"
}

foreach ($verbKey in $legacyVerbKeys) {
    if (Test-Path -LiteralPath $verbKey) {
        Remove-Item -LiteralPath $verbKey -Recurse -Force
    }
}

New-Item -Path $productVerbKey -Force | Out-Null
Set-ItemProperty -Path $productVerbKey -Name "MUIVerb" -Value "Analizar con Race Engineer"
Set-ItemProperty -Path $productVerbKey -Name "Icon" -Value "shell32.dll,-16739"
New-Item -Path $productCommandKey -Force | Out-Null
Set-Item -Path $productCommandKey -Value ('"{0}" "%1"' -f $productLauncher)

Write-Host "Race Engineer context menu: INSTALLED"
Write-Host "Deterministic launcher: $productLauncher"
Write-Host "Scope: current Windows user only"
