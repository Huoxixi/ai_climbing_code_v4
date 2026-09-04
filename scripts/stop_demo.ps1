$demoPorts = @(5173, 8000)
$listenerPids = @()

foreach ($line in (netstat -ano -p TCP)) {
  if ($line -match "^\s*TCP\s+127\.0\.0\.1:(5173|8000)\s+\S+\s+LISTENING\s+(\d+)\s*$") {
    $listenerPids += [int]$Matches[2]
  }
}

$listenerPids = $listenerPids | Sort-Object -Unique
if (-not $listenerPids) {
  Write-Host "No local demo services are listening on ports 5173 or 8000."
  exit 0
}

foreach ($processId in $listenerPids) {
  Stop-Process -Id $processId -Force
}

Write-Host "Stopped local demo services on ports 5173 and 8000."
