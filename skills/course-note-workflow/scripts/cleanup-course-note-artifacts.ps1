param(
  [Parameter(Mandatory = $true)]
  [string]$TargetDir,
  [switch]$WhatIf
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $TargetDir)) {
  throw "Target directory not found: $TargetDir"
}

$patterns = @(
  'final_note_*feishu_taghead*.md',
  'final_note_*feishu_logicformat*.md',
  'final_note_*feishu_style*.md',
  'final_note_*feishu_cleanup*.md',
  'final_note_*feishu_boldlabels*.md',
  'final_note_*feishu_emphasis*.md'
)

$files = foreach ($pattern in $patterns) {
  Get-ChildItem -Path $TargetDir -File -Filter $pattern -ErrorAction SilentlyContinue
}

$files = $files | Sort-Object FullName -Unique
if (-not $files) {
  Write-Output 'No matching obsolete artifacts found.'
  exit 0
}

$files | ForEach-Object { Write-Output $_.FullName }

if ($WhatIf) {
  Write-Output "WhatIf: listed $($files.Count) file(s); nothing deleted."
  exit 0
}

$files | Remove-Item -Force
Write-Output "Deleted $($files.Count) file(s)."
