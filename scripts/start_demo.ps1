$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $projectRoot "backend"
$frontendDir = Join-Path $projectRoot "frontend"
$backendPython = Join-Path $backendDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $backendPython)) {
  throw "backend\.venv is missing. Install backend dependencies first."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
  throw "frontend\node_modules is missing. Run npm.cmd install in frontend first."
}

Start-Process `
  -FilePath $backendPython `
  -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000") `
  -WorkingDirectory $backendDir `
  -WindowStyle Hidden

Start-Process `
  -FilePath "npm.cmd" `
  -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1") `
  -WorkingDirectory $frontendDir `
  -WindowStyle Hidden

Write-Host "Local demo services started."
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Run .\scripts\stop_demo.ps1 from the project root to stop both services."
