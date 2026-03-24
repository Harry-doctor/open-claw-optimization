param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$InputFile,

    [Parameter(Position = 1)]
    [string]$OutputDir,

    [string]$Model = 'medium',
    [ValidateSet('transcribe', 'translate')]
    [string]$Task = 'transcribe',
    [ValidateSet('txt', 'vtt', 'srt', 'tsv', 'json', 'all')]
    [string]$OutputFormat = 'srt',
    [string]$Language = 'zh',
    [switch]$WordTimestamps
)

$ErrorActionPreference = 'Stop'

$pythonRoot = Join-Path $env:LocalAppData 'Programs\Python\Python311'
$pythonExe = Join-Path $pythonRoot 'python.exe'
$whisperExe = Join-Path $pythonRoot 'Scripts\whisper.exe'

if (-not (Test-Path $pythonExe)) {
    throw "Python not found: $pythonExe"
}

if (-not (Test-Path $whisperExe)) {
    throw "Whisper not found: $whisperExe"
}

if (-not (Test-Path $InputFile)) {
    throw "Input file not found: $InputFile"
}

$InputFile = (Resolve-Path $InputFile).Path

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Split-Path -Parent $InputFile
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$env:PATH = "$pythonRoot;$(Join-Path $pythonRoot 'Scripts');$env:PATH"
$env:PYTHONUTF8 = '1'

$args = @(
    $InputFile,
    '--model', $Model,
    '--task', $Task,
    '--output_format', $OutputFormat,
    '--output_dir', $OutputDir,
    '--language', $Language
)

if ($WordTimestamps) {
    $args += '--word_timestamps'
    $args += 'True'
}

Write-Host "Starting transcription..."
Write-Host "Input: $InputFile"
Write-Host "Output: $OutputDir"
Write-Host "Model: $Model"
Write-Host "Task: $Task"
Write-Host "Format: $OutputFormat"
Write-Host "Language: $Language"

& $whisperExe @args

if ($LASTEXITCODE -ne 0) {
    throw "Whisper failed with exit code: $LASTEXITCODE"
}

Write-Host "Done."
