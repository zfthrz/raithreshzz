$ErrorActionPreference = "Stop"

$repo = "C:\Users\thres\Documents\GitHub\raithreshzz"
$telemetry = Join-Path $repo "telemetria"
$exports = Join-Path $repo "track_exports"

Set-Location $repo
New-Item -ItemType Directory -Force -Path $exports | Out-Null

$extractor = Join-Path $repo "extract_lmu_track_gps.py"
$detector  = Join-Path $repo "detect_track_turns.py"

if (-not (Test-Path $extractor)) { throw "Falta $extractor" }
if (-not (Test-Path $detector))  { throw "Falta $detector" }

$files = @(
    "Autodromo Enzo e Dino Ferrari_P_2026-08-13T23_25_02Z.duckdb",
    "Autodromo Enzo e Dino Ferrari_P_2026-08-13T23_34_47Z.duckdb"
)

foreach ($name in $files) {
    $db = Join-Path $telemetry $name

    if (-not (Test-Path $db)) {
        throw "No encontré $db"
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "Procesando $name"
    Write-Host "============================================================"

    python $extractor $db --output-dir $exports
    if ($LASTEXITCODE -ne 0) { throw "Falló extract_lmu_track_gps.py para $name" }

    $stem = [System.IO.Path]::GetFileNameWithoutExtension($name)
    $gps = Join-Path $exports ($stem + "_track_gps.csv")

    if (-not (Test-Path $gps)) {
        throw "No apareció el CSV esperado: $gps"
    }

    # FIA WEC 2026: Imola = 21 turns (12 left / 9 right).
    python $detector $gps --turn-count 21 --output-dir $exports
    if ($LASTEXITCODE -ne 0) { throw "Falló detect_track_turns.py para $name" }
}

Write-Host ""
Write-Host "Listo. Archivos de Imola generados:"
Get-ChildItem $exports -File |
    Where-Object { $_.Name -like "Autodromo Enzo e Dino Ferrari*" } |
    Sort-Object Name |
    Select-Object Name, Length, LastWriteTime
