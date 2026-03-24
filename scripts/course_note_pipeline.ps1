param(
  [ValidateSet('run','draft','rewrite','finalize','stop')]
  [string]$Mode = 'run',
  [int]$Minutes = 28,
  [int]$IntervalSec = 90
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$captureScript = Join-Path $workspace 'scripts\capture_watch_28m.ps1'
$draftScript = Join-Path $workspace 'scripts\course_note_draft.ps1'
$rewriteScript = Join-Path $workspace 'scripts\course_note_rewrite.ps1'
$abortPath = Join-Path $workspace 'capture_abort.flag'
$pipelineLog = Join-Path $workspace 'course_note_pipeline.log'

function Log([string]$msg) {
  $line = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $msg
  Add-Content -Path $pipelineLog -Value $line -Encoding UTF8
}

switch ($Mode) {
  'stop' {
    Set-Content -Path $abortPath -Value ('STOP_REQUESTED ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) -Encoding UTF8
    Log 'STOP_REQUESTED'
    Write-Output 'STOP_REQUESTED'
    exit 0
  }
  'draft' {
    Log 'DRAFT_START'
    powershell -ExecutionPolicy Bypass -File $draftScript
    if ($LASTEXITCODE -ne 0) { throw "Draft step failed: $LASTEXITCODE" }
    Log 'DRAFT_DONE'
    exit 0
  }
  'rewrite' {
    Log 'REWRITE_START'
    powershell -ExecutionPolicy Bypass -File $rewriteScript
    if ($LASTEXITCODE -ne 0) { throw "Rewrite step failed: $LASTEXITCODE" }
    Log 'REWRITE_DONE'
    exit 0
  }
  'finalize' {
    Log 'FINALIZE_START'
    powershell -ExecutionPolicy Bypass -File $draftScript
    if ($LASTEXITCODE -ne 0) { throw "Draft step failed: $LASTEXITCODE" }
    powershell -ExecutionPolicy Bypass -File $rewriteScript
    if ($LASTEXITCODE -ne 0) { throw "Rewrite step failed: $LASTEXITCODE" }
    Log 'FINALIZE_DONE'
    exit 0
  }
  'run' {
    Log ("RUN_START minutes=$Minutes interval=$IntervalSec")
    powershell -ExecutionPolicy Bypass -File $captureScript -Minutes $Minutes -IntervalSec $IntervalSec
    if ($LASTEXITCODE -ne 0) { throw "Capture stage failed: $LASTEXITCODE" }
    Log 'CAPTURE_DONE'

    powershell -ExecutionPolicy Bypass -File $draftScript
    if ($LASTEXITCODE -ne 0) { throw "Draft step failed: $LASTEXITCODE" }
    Log 'DRAFT_DONE'

    powershell -ExecutionPolicy Bypass -File $rewriteScript
    if ($LASTEXITCODE -ne 0) { throw "Rewrite step failed: $LASTEXITCODE" }
    Log 'REWRITE_DONE'
    Log 'RUN_DONE'
    exit 0
  }
}
