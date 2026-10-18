param([int]$Port = 4317, [switch]$Build, [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port between 1024 and 65535.' }
$projectDirectory = $PSScriptRoot
$frontendDirectory = Join-Path $projectDirectory 'frontend'
$workspaceDirectory = Split-Path (Split-Path $projectDirectory -Parent) -Parent
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$nodeRuntime = if ($nodeCommand) { $nodeCommand.Source } else { Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' }
if (-not (Test-Path -LiteralPath $nodeRuntime)) { throw 'Node runtime is unavailable.' }
if (-not $PythonPath) {
    $candidates = @((Join-Path $workspaceDirectory 'desktop-deliveries/AiClimbing-0.1.14-replay.20261009/runtime/python.exe'),(Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'))
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath)) { throw 'Python runtime is unavailable; pass -PythonPath with an interpreter containing fastapi and uvicorn.' }
if ($Build -or -not (Test-Path -LiteralPath (Join-Path $frontendDirectory 'dist-browser/browser-replay.html'))) {
    Push-Location -LiteralPath $frontendDirectory
    try {
        & $nodeRuntime 'node_modules/vite/bin/vite.js' build --config vite.browser.config.js
        if ($LASTEXITCODE -ne 0) { throw 'Browser build failed.' }
    } finally { Pop-Location }
}
$listener = [System.Net.Sockets.TcpClient]::new()
try { $listener.Connect('127.0.0.1', $Port); throw "Port $Port is already occupied; no existing process was stopped." }
catch [System.Net.Sockets.SocketException] { }
finally { $listener.Dispose() }
$runDirectory = Join-Path $projectDirectory ('.tmp/browser-local-preview-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$arguments = @('-m','uvicorn','browser_web_app:create_app','--factory','--app-dir','backend','--host','127.0.0.1','--port',"$Port",'--no-access-log')
$process = Start-Process -FilePath $PythonPath -ArgumentList $arguments -WorkingDirectory $projectDirectory -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDirectory 'preview.out.log') -RedirectStandardError (Join-Path $runDirectory 'preview.err.log') -PassThru
$url = "http://127.0.0.1:$Port/browser-replay.html"
$deadline = (Get-Date).AddSeconds(15)
do {
    if ($process.HasExited) { throw "Browser preview exited; see $runDirectory" }
    try {
        $response = Invoke-WebRequest -Uri $url -TimeoutSec 1 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            @{pid=$process.Id;url=$url;static_directory='frontend/dist-browser';created_at=(Get-Date -Format o)} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runDirectory 'preview.json') -Encoding UTF8
            Write-Output $url
            return
        }
    } catch { Start-Sleep -Milliseconds 150 }
} while ((Get-Date) -lt $deadline)
throw "Browser preview did not become ready; see $runDirectory"
