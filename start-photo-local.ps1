$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$workspaceDirectory = Split-Path (Split-Path $projectDirectory -Parent) -Parent
$pythonRuntime = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$nodeRuntime = (Get-Command node -ErrorAction Stop).Source
$logDirectory = Join-Path $projectDirectory '.local/logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
foreach ($portNumber in @(4176,8004)) {
    $listener = [System.Net.Sockets.TcpClient]::new()
    try { $listener.Connect('127.0.0.1',$portNumber); throw "Port $portNumber is occupied. Stop the previous local preview before starting. The URL will not be changed." }
    catch [System.Net.Sockets.SocketException] { }
    finally { $listener.Dispose() }
}
if (-not (Test-Path -LiteralPath $pythonRuntime)) { throw 'Bundled Python runtime is unavailable.' }
$climbingModelRoot = Join-Path $workspaceDirectory 'photo-route-experiments/indoor-climbing-20260906'
$pythonPaths = @('boulder-python','boulder-model-python','boulder-app-python') | ForEach-Object { Join-Path $workspaceDirectory ".tools/$_" }
$climbReplayCaseSpecs = @(
    @{ id='case-1'; label='本地案例 1'; description='十几秒攀爬素材，仅用于本机流程验收'; path=(Join-Path $workspaceDirectory '素材/a5dd8a80ca37708687f488b49bb82d84.mp4') },
    @{ id='case-2'; label='本地案例 2'; description='十几秒攀爬素材，仅用于本机流程验收'; path=(Join-Path $workspaceDirectory '素材/32fd4ed4a82458794181be60eb5b3792.mp4'); comparison_path=(Join-Path $projectDirectory '.local/diagnostics/distilled-chinese-timeline-case2-20260921-01.webm'); comparison_route_color='蓝色'; comparison_action_count=17 },
    @{ id='case-3'; label='本地案例 3'; description='十几秒攀爬素材，仅用于本机流程验收'; path=(Join-Path $workspaceDirectory '素材/ebe6e698a861512b2587f661edd1b7a1.mp4') }
)
$climbReplayTestVideos = @($climbReplayCaseSpecs | Where-Object { Test-Path -LiteralPath $_.path })
$env:CLIMB_REPLAY_TEST_VIDEOS = ConvertTo-Json -InputObject $climbReplayTestVideos -Compress
Remove-Item Env:CLIMB_REPLAY_TEST_VIDEO_PATH -ErrorAction SilentlyContinue
Remove-Item Env:CLIMB_REPLAY_TEST_VIDEO_SOURCE_URL -ErrorAction SilentlyContinue
$env:PYTHONPATH = ($pythonPaths + @((Join-Path $climbingModelRoot 'detectron-deps'),(Join-Path $climbingModelRoot 'detectron2-source'))) -join ';'
$env:PHOTO_ROUTE_CLIMBING_MODEL_CONFIG = Join-Path $projectDirectory '.local/quality-selection-20260907/config-1200.yml'
$env:PHOTO_ROUTE_CLIMBING_MODEL_CHECKPOINT = Join-Path $climbingModelRoot 'model/verified-model_final.pth'
$env:HF_HUB_OFFLINE = '1'
function Wait-PhotoService($process, $url) {
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "Local service exited during startup. See $logDirectory. The URL will not be changed." }
        try { $response = Invoke-WebRequest -Uri $url -TimeoutSec 2; if ($response.StatusCode -eq 200) { return } } catch { }
        Start-Sleep -Milliseconds 250
    }
    throw "Local service did not become ready. See $logDirectory. The URL will not be changed."
}
$backendProcess = Start-Process -FilePath $pythonRuntime -ArgumentList '-m uvicorn photo_local_server:app --host 127.0.0.1 --port 8004 --workers 1' -WorkingDirectory (Join-Path $projectDirectory 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'backend.out.log') -RedirectStandardError (Join-Path $logDirectory 'backend.err.log') -PassThru
Wait-PhotoService $backendProcess 'http://127.0.0.1:8004/api/photo-routes/workflow/current'
$frontendProcess = Start-Process -FilePath $nodeRuntime -ArgumentList 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4176 --strictPort' -WorkingDirectory (Join-Path $projectDirectory 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'frontend.out.log') -RedirectStandardError (Join-Path $logDirectory 'frontend.err.log') -PassThru
@{backend=$backendProcess.Id;frontend=$frontendProcess.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDirectory 'processes.json')
Wait-PhotoService $frontendProcess 'http://127.0.0.1:4176/'
Write-Output 'Local preview: http://127.0.0.1:4176/#/photo-routes'
