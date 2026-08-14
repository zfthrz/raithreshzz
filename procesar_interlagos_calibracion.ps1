$ErrorActionPreference = "Stop"

# Race Engineer - preparación de calibración de Interlagos
# Ejecutar desde la raíz del repositorio.

$repo = (Get-Location).Path
$telemetry = Join-Path $repo "telemetria"
$exports = Join-Path $repo "track_exports"

$extractor = Join-Path $repo "extract_lmu_track_gps.py"
$detector  = Join-Path $repo "detect_track_turns.py"

if (-not (Test-Path $telemetry)) { throw "Falta la carpeta telemetria: $telemetry" }
if (-not (Test-Path $extractor)) { throw "Falta $extractor" }
if (-not (Test-Path $detector))  { throw "Falta $detector" }

New-Item -ItemType Directory -Force -Path $exports | Out-Null

Write-Host "Comprobando dependencia DuckDB..."
python -c "import duckdb; print('duckdb', duckdb.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "No está disponible el paquete duckdb. Ejecutá: python -m pip install -r requirements.txt"
}

$files = @(
    "Autódromo José Carlos Pace_P_2026-08-14T03_03_08Z.duckdb",
    "Autódromo José Carlos Pace_P_2026-08-14T03_14_04Z.duckdb"
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

    # 1) Extrae una vuelta GPS completa y la expresa también en LMU Lap Dist.
    python $extractor $db --output-dir $exports
    if ($LASTEXITCODE -ne 0) {
        throw "Falló extract_lmu_track_gps.py para $name"
    }

    $stem = [System.IO.Path]::GetFileNameWithoutExtension($name)
    $gps = Join-Path $exports ($stem + "_track_gps.csv")

    if (-not (Test-Path $gps)) {
        throw "No apareció el CSV esperado: $gps"
    }

    # Interlagos / WEC: 15 curvas numeradas.
    # IMPORTANTE: el detector entrega candidatos geométricos; candidate_number
    # NO se considera número oficial hasta completar la calibración manual.
    python $detector $gps --turn-count 15 --output-dir $exports
    if ($LASTEXITCODE -ne 0) {
        throw "Falló detect_track_turns.py para $name"
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "PREPARACIÓN COMPLETA"
Write-Host "============================================================"
Write-Host "Revisá en track_exports, para AMBAS sesiones:"
Write-Host "  *_track_gps_summary.json"
Write-Host "  *_track_gps.geojson"
Write-Host "  *_turn_candidates.csv"
Write-Host "  *_turn_candidates.json"
Write-Host ""
Write-Host "No asignes nombres automáticamente: el siguiente paso es cruzar la"
Write-Host "secuencia geométrica con el mapa verificado del layout y validar los"
Write-Host "ápices contra la segunda sesión."
