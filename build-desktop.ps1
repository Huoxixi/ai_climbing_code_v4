param(
    [Parameter(Mandatory=$true)][string]$PythonRuntime,
    [Parameter(Mandatory=$true)][string]$NodeRuntime,
    [Parameter(Mandatory=$true)][string[]]$SiteDirectories,
    [Parameter(Mandatory=$true)][string]$DetectronSource,
    [string]$Checkpoint,
    [string]$OutputDirectory,
    [switch]$WriteLock
)
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot ('.tmp/desktop-build/' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '/AiClimbing')
}
Push-Location (Join-Path $PSScriptRoot 'frontend')
try {
    Get-ChildItem Env: | Where-Object { $_.Name -like 'VITE_*' } | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
    $env:CLIMB_DESKTOP_BUILD = '1'
    $env:VITE_ENABLE_SIMULATION = 'false'
    Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
    & $NodeRuntime 'node_modules/vite/bin/vite.js' build --mode boulder-local
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Remove-Item Env:CLIMB_DESKTOP_BUILD -ErrorAction SilentlyContinue; Pop-Location }
$taskBuildArgs = @((Join-Path $PSScriptRoot 'desktop/build.py'), '--output', $OutputDirectory, '--detectron', $DetectronSource)
foreach ($taskSite in $SiteDirectories) { $taskBuildArgs += @('--site', $taskSite) }
if ($Checkpoint) { $taskBuildArgs += @('--checkpoint', $Checkpoint) }
if ($WriteLock) { $taskBuildArgs += '--write-lock' }
$env:PYTHONPATH = $SiteDirectories -join ';'
& $PythonRuntime @taskBuildArgs
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed; partial output is preserved for diagnosis' }
& $PythonRuntime (Join-Path $PSScriptRoot 'desktop/finalize.py') --package $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Desktop finalization failed; partial output is preserved for diagnosis' }
Write-Output "Desktop package: $OutputDirectory"
