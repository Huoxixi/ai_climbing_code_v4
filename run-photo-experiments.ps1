$ErrorActionPreference = 'Stop'
$experimentProject = $PSScriptRoot
$experimentWorkspace = Split-Path (Split-Path $experimentProject -Parent) -Parent
$experimentPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$experimentPaths = @('photo-route-bench-python','boulder-python','boulder-model-python','boulder-app-python') |
    ForEach-Object { Join-Path $experimentWorkspace ".tools/$_" }
if (-not (Test-Path -LiteralPath $experimentPython)) { throw 'Bundled Python runtime is unavailable.' }
$experimentOldPath = $env:PYTHONPATH
$experimentOldEncoding = $env:PYTHONIOENCODING
Push-Location (Join-Path $experimentProject 'backend')
try {
    $env:PYTHONPATH = $experimentPaths -join ';'
    $env:PYTHONIOENCODING = 'utf-8'
    & $experimentPython -B -m experiments.photo_routes @args
    $experimentExit = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONPATH = $experimentOldPath
    $env:PYTHONIOENCODING = $experimentOldEncoding
}
exit $experimentExit
