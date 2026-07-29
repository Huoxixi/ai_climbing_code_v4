$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dataDir = Join-Path $projectRoot "backend\data"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $dataDir "demo_backups\$timestamp"

$dataFiles = @(
  "saved_boards.json",
  "hold_assets_meta.json",
  "holds_mapping.json",
  "holds_vectors.json",
  "standard_board_activity.json",
  "standard_board_accepted_repairs.json",
  "modification_log.json"
)

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
foreach ($fileName in $dataFiles) {
  $sourcePath = Join-Path $dataDir $fileName
  if (Test-Path -LiteralPath $sourcePath) {
    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $backupDir $fileName)
  }
}

Write-Host "Demo data backup created: $backupDir"
