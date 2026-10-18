$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'runtime/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw '请在完整解压的程序目录中执行本脚本。' }
$taskOutput = Join-Path $env:LOCALAPPDATA ('AiClimbingAcceptance/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
& $taskPython -B -X utf8 -W ignore -m desktop.verify_package --output $taskOutput --model
if ($LASTEXITCODE -ne 0) { throw "包内检查失败，请保留 $taskOutput 中的报告。" }
& $taskPython -B -X utf8 -m desktop.launcher --data-root (Join-Path $taskOutput 'window-data') --window-check (Join-Path $taskOutput 'window.json')
if ($LASTEXITCODE -ne 0) { throw "窗口检查失败，请保留 $taskOutput 中的报告。" }
Write-Output "构造检查完成，报告位置：$taskOutput"
Write-Output '仍需手动核验照片完整复核保存、视频草稿、交互式素材选择与保存对话框，以及更新／卸载保留数据。'
