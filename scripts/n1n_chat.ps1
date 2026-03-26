param(
  [Parameter(Mandatory = $true)]
  [string]$Model,
  [string]$SystemPrompt,
  [string]$SystemFile,
  [string]$UserPrompt,
  [string]$UserFile,
  [string]$HistoryFile,
  [string]$TaskType,
  [double]$Temperature = 0.2,
  [int]$MaxTokens = 1800,
  [int]$TimeoutSec = 180,
  [int]$MaxContextTokens = 4000,
  [string]$RoutingFile,
  [switch]$DisableRouting,
  [switch]$DisableCache,
  [int]$CacheTtl = 1800,
  [string]$ToolsFile,
  [ValidateSet('off', 'auto', 'required')]
  [string]$ToolMode = 'off',
  [string]$TaskId,
  [string]$OutFile,
  [string]$MetaOutFile
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$pythonScript = Join-Path $PSScriptRoot 'n1n_chat.py'
$pythonBin = Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $pythonBin)) { $pythonBin = 'python.exe' }
if (-not (Test-Path $pythonScript)) { throw "Missing Python client: $pythonScript" }

$argsList = @('--model', $Model, '--temperature', [string]$Temperature, '--max-tokens', [string]$MaxTokens, '--timeout', [string]$TimeoutSec, '--max-context-tokens', [string]$MaxContextTokens, '--cache-ttl', [string]$CacheTtl, '--tool-mode', $ToolMode)
if ($SystemPrompt) { $argsList += @('--system', $SystemPrompt) }
if ($SystemFile) { $argsList += @('--system-file', $SystemFile) }
if ($UserPrompt) { $argsList += @('--user', $UserPrompt) }
if ($UserFile) { $argsList += @('--user-file', $UserFile) }
if ($HistoryFile) { $argsList += @('--history-file', $HistoryFile) }
if ($TaskType) { $argsList += @('--task-type', $TaskType) }
if ($RoutingFile) { $argsList += @('--routing-file', $RoutingFile) }
if ($DisableRouting) { $argsList += '--disable-routing' }
if ($DisableCache) { $argsList += '--disable-cache' }
if ($ToolsFile) { $argsList += @('--tools-file', $ToolsFile) }
if ($TaskId) { $argsList += @('--task-id', $TaskId) }
if ($OutFile) { $argsList += @('--out-file', $OutFile) }
if ($MetaOutFile) { $argsList += @('--meta-out-file', $MetaOutFile) }

& $pythonBin $pythonScript @argsList
exit $LASTEXITCODE
