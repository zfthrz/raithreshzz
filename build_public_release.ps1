param(
    [string]$PythonExe = "data\local\toolchains\python312-installed\python.exe",
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [Parameter(Mandatory = $true)]
    [string]$WorkRoot
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $PythonExe))
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputRoot))
$workPath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $WorkRoot))

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python build toolchain not found: $pythonPath"
}
if (Test-Path -LiteralPath $outputPath) {
    throw "OutputRoot already exists; choose a new path: $outputPath"
}
if (Test-Path -LiteralPath $workPath) {
    throw "WorkRoot already exists; choose a new path: $workPath"
}

$commitEpoch = (& git -C $projectRoot show -s --format=%ct HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commitEpoch -notmatch '^\d+$') {
    throw "Could not resolve the source commit timestamp."
}

$previousHashSeed = $env:PYTHONHASHSEED
$previousSourceDateEpoch = $env:SOURCE_DATE_EPOCH
try {
    $env:PYTHONHASHSEED = "1"
    $env:SOURCE_DATE_EPOCH = $commitEpoch
    & $pythonPath -m PyInstaller `
        --noconfirm `
        --clean `
        --workpath $workPath `
        --distpath $outputPath `
        (Join-Path $projectRoot "RaceEngineer.spec")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $buildDir = Join-Path $outputPath "RaceEngineer"
    & $pythonPath (Join-Path $projectRoot "public_build_manifest.py") $buildDir
    if ($LASTEXITCODE -ne 0) {
        throw "Build manifest generation failed with exit code $LASTEXITCODE."
    }
    & $pythonPath (Join-Path $projectRoot "public_build_manifest.py") $buildDir --verify
    if ($LASTEXITCODE -ne 0) {
        throw "Build manifest verification failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYTHONHASHSEED = $previousHashSeed
    $env:SOURCE_DATE_EPOCH = $previousSourceDateEpoch
}

Write-Output "PUBLIC_BUILD_READY=$buildDir"
