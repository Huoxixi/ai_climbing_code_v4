param([string]$PythonRuntime)
$ErrorActionPreference = 'Stop'
if (-not $PythonRuntime) {
    $PythonRuntime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
}
$workspaceDirectory = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskDependencyDirectory = Join-Path $workspaceDirectory '.tools/replay-rtmw-python'
New-Item -ItemType Directory -Path $taskDependencyDirectory -Force | Out-Null
& $PythonRuntime -m pip install --target $taskDependencyDirectory -r (Join-Path $PSScriptRoot 'backend/requirements-replay-rtmw.lock')
if ($LASTEXITCODE -ne 0) { throw 'RTMW ONNX dependency installation failed.' }
& $PythonRuntime (Join-Path $PSScriptRoot 'backend/scripts/install_replay_rtmw.py')
if ($LASTEXITCODE -ne 0) { throw 'RTMW weight installation failed; existing files preserved.' }
Write-Output 'RTMW installed. Restart the local application to activate its dependency path.'
