param([int]$OverlapDays = 7, [switch]$VerifyOnly, [string]$PythonExe = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectRoot
try {
    if ($VerifyOnly) {
        & $PythonExe -m scripts.daily_verified --overlap-days $OverlapDays --verify-only
    }
    else {
        & $PythonExe -m scripts.daily_verified --overlap-days $OverlapDays
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
