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
$env:PYTHONPATH = (@('boulder-python','boulder-model-python','boulder-app-python') | ForEach-Object { Join-Path $workspaceDirectory ".tools/$_" }) -join ';'
$env:PHOTO_ROUTE_MOBILESAM_REPO = Join-Path $workspaceDirectory 'photo-route-experiments/MobileSAM'
$env:PHOTO_ROUTE_MOBILESAM_CHECKPOINT = Join-Path $env:PHOTO_ROUTE_MOBILESAM_REPO 'weights/mobile_sam.pt'
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
$backendProcess = Start-Process -FilePath $pythonRuntime -ArgumentList '-m uvicorn photo_local_server:app --host 127.0.0.1 --port 8004' -WorkingDirectory (Join-Path $projectDirectory 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'backend.out.log') -RedirectStandardError (Join-Path $logDirectory 'backend.err.log') -PassThru
Wait-PhotoService $backendProcess 'http://127.0.0.1:8004/api/photo-routes/workflow/current'
$frontendProcess = Start-Process -FilePath $nodeRuntime -ArgumentList 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4176 --strictPort' -WorkingDirectory (Join-Path $projectDirectory 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'frontend.out.log') -RedirectStandardError (Join-Path $logDirectory 'frontend.err.log') -PassThru
@{backend=$backendProcess.Id;frontend=$frontendProcess.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDirectory 'processes.json')
Wait-PhotoService $frontendProcess 'http://127.0.0.1:4176/'
Write-Output 'Local preview: http://127.0.0.1:4176/#/photo-routes'
