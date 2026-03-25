param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('structure','rewrite','audit','patch')]
  [string]$Stage,
  [string]$SourcePath,
  [string]$FinalPath,
  [string]$NotePath,
  [string]$AuditPath,
  [Parameter(Mandatory = $true)]
  [string]$OutPath,
  [string]$WorkspaceRoot = 'C:\Users\admin\.openclaw\workspace'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

$scriptMap = @{
  structure = 'scripts\course_note_structure.ps1'
  rewrite   = 'scripts\course_note_rewrite.ps1'
  audit     = 'scripts\course_note_audit.ps1'
  patch     = 'scripts\course_note_patch.ps1'
}

$scriptPath = Join-Path $WorkspaceRoot $scriptMap[$Stage]
if (-not (Test-Path $scriptPath)) {
  throw "Missing stage script: $scriptPath"
}

$args = @('-ExecutionPolicy', 'Bypass', '-File', $scriptPath)

switch ($Stage) {
  'structure' {
    if (-not $SourcePath) { throw 'structure requires -SourcePath' }
    $args += @('-SourcePath', $SourcePath, '-OutPath', $OutPath)
  }
  'rewrite' {
    if (-not $SourcePath) { throw 'rewrite requires -SourcePath' }
    $args += @('-SourcePath', $SourcePath, '-OutPath', $OutPath)
  }
  'audit' {
    if (-not $SourcePath) { throw 'audit requires -SourcePath' }
    if (-not $FinalPath) { throw 'audit requires -FinalPath' }
    $args += @('-SourcePath', $SourcePath, '-FinalPath', $FinalPath, '-OutPath', $OutPath)
  }
  'patch' {
    if (-not $SourcePath) { throw 'patch requires -SourcePath' }
    if (-not $NotePath) { throw 'patch requires -NotePath' }
    if (-not $AuditPath) { throw 'patch requires -AuditPath' }
    $args += @('-SourcePath', $SourcePath, '-NotePath', $NotePath, '-AuditPath', $AuditPath, '-OutPath', $OutPath)
  }
}

& powershell @args
if ($LASTEXITCODE -ne 0) {
  throw "$Stage stage failed with exit code: $LASTEXITCODE"
}
