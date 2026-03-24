param(
  [Parameter(Mandatory = $true)]
  [string]$InputRoot,
  [Parameter(Mandatory = $true)]
  [string]$OutDir,
  [switch]$PlanOnly,
  [int]$FrameInterval = 30,
  [int]$MaxFrames = 20,
  [string]$Language = 'zh',
  [string]$TranscriptPrompt = '',
  [string]$OcrLang = 'chi_sim+eng',
  [string]$OcrPsm = '6',
  [switch]$SkipTranscript,
  [switch]$SkipOcr
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$py = Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$script = Join-Path $workspace 'scripts\offline_course_pipeline.py'

$args = @(
  $script,
  '--input-root', $InputRoot,
  '--out-dir', $OutDir,
  '--frame-interval', $FrameInterval,
  '--max-frames', $MaxFrames,
  '--language', $Language,
  '--ocr-lang', $OcrLang,
  '--ocr-psm', $OcrPsm
)
if ($TranscriptPrompt -ne '') { $args += @('--transcript-prompt', $TranscriptPrompt) }
if ($PlanOnly) { $args += '--plan-only' }
if ($SkipTranscript) { $args += '--skip-transcript' }
if ($SkipOcr) { $args += '--skip-ocr' }

& $py @args
if ($LASTEXITCODE -ne 0) {
  throw "offline_course_pipeline.py failed with exit code: $LASTEXITCODE"
}
