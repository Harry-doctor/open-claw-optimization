param(
  [Parameter(Mandatory = $true)]
  [string]$InputRoot,
  [Parameter(Mandatory = $true)]
  [string]$OutDir,
  [switch]$PlanOnly,
  [int]$FrameInterval = 30,
  [int]$MaxFrames = 20,
  [ValidateSet('api','local')]
  [string]$SttBackend = 'local',
  [string]$LocalWhisperModel = 'medium',
  [string]$Language = 'zh',
  [string]$TranscriptPrompt = '',
  [string]$OcrLang = 'chi_sim+eng',
  [string]$OcrPsm = '6',
  [switch]$SkipTranscript,
  [switch]$SkipOcr,
  [string]$WorkspaceRoot = 'C:\Users\admin\.openclaw\workspace'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $WorkspaceRoot 'scripts\offline_course_pipeline.ps1'
if (-not (Test-Path $scriptPath)) {
  throw "Missing workflow script: $scriptPath"
}

$args = @(
  '-ExecutionPolicy', 'Bypass',
  '-File', $scriptPath,
  '-InputRoot', $InputRoot,
  '-OutDir', $OutDir,
  '-FrameInterval', $FrameInterval,
  '-MaxFrames', $MaxFrames,
  '-SttBackend', $SttBackend,
  '-LocalWhisperModel', $LocalWhisperModel,
  '-Language', $Language,
  '-OcrLang', $OcrLang,
  '-OcrPsm', $OcrPsm
)

if ($TranscriptPrompt -ne '') { $args += @('-TranscriptPrompt', $TranscriptPrompt) }
if ($PlanOnly) { $args += '-PlanOnly' }
if ($SkipTranscript) { $args += '-SkipTranscript' }
if ($SkipOcr) { $args += '-SkipOcr' }

& powershell @args
if ($LASTEXITCODE -ne 0) {
  throw "offline_course_pipeline.ps1 failed with exit code: $LASTEXITCODE"
}
