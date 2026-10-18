$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$workspaceDirectory = Split-Path (Split-Path $projectDirectory -Parent) -Parent
$pythonRuntime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$sdkDirectory = Join-Path $workspaceDirectory '.tools/boulder-app-python'
if (-not (Test-Path -LiteralPath $pythonRuntime)) { throw 'Bundled Python runtime is unavailable.' }
$sdkRequirements = @(Get-Content -LiteralPath (Join-Path $projectDirectory 'backend/requirements-production.lock') |
    Where-Object { $_ -match '^(alibabacloud-|(?:darabonba-core|aiofiles|apscheduler|tzlocal|tzdata|websocket-client)==)' })
if ($sdkRequirements.Count -eq 0) { throw 'No locked pose SDK dependencies were found.' }
# Keep the shared photo/model libraries intact; the existing local environment
# supplies requests, aiohttp and cryptography. Avoid a stalled pip build cache.
& $pythonRuntime -u -m pip --isolated --disable-pip-version-check install --no-cache-dir --no-build-isolation --retries 0 --timeout 30 --index-url https://pypi.org/simple --no-deps --target $sdkDirectory @sdkRequirements
if ($LASTEXITCODE -ne 0) { throw 'Pose SDK installation failed.' }
$previousPythonPath = $env:PYTHONPATH
try {
    $pythonPaths = @('boulder-python','boulder-model-python','boulder-app-python','photo-route-bench-python') |
        ForEach-Object { Join-Path $workspaceDirectory ".tools/$_" }
    $env:PYTHONPATH = $pythonPaths -join ';'
    & $pythonRuntime (Join-Path $projectDirectory 'backend/scripts/check_replay_pose_sdk.py')
    if ($LASTEXITCODE -ne 0) { throw 'Pose SDK verification failed; the rest of the local backend dependencies must also be installed.' }
} finally { $env:PYTHONPATH = $previousPythonPath }
