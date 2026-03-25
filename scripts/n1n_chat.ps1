param(
  [Parameter(Mandatory = $true)]
  [string]$Model,
  [string]$SystemPrompt,
  [string]$SystemFile,
  [string]$UserPrompt,
  [string]$UserFile,
  [double]$Temperature = 0.2,
  [int]$MaxTokens = 1800,
  [int]$TimeoutSec = 180,
  [string]$OutFile
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $workspace 'config\n1n.local.json'

function Get-Text([string]$inline, [string]$filePath) {
  if ($filePath) {
    return (Get-Content $filePath -Raw -Encoding UTF8)
  }
  if ($null -eq $inline) { return '' }
  return $inline
}

function Resolve-ModelApiKey($cfg, [string]$modelName) {
  if ($env:N1N_API_KEY) { return [string]$env:N1N_API_KEY }
  $name = ([string]$modelName).ToLowerInvariant()
  $candidates = @()
  if ($name.StartsWith('gemini')) {
    $candidates += $cfg.gemini_api_key
    $candidates += $cfg.api_key
  } elseif ($name.StartsWith('claude')) {
    $candidates += $cfg.claude_api_key
    $candidates += $cfg.api_key
  } elseif ($name.StartsWith('qwen')) {
    $candidates += $cfg.qwen_api_key
    $candidates += $cfg.api_key
  } elseif ($name.StartsWith('gpt') -or $name.StartsWith('openai/gpt')) {
    $candidates += $cfg.gpt_api_key
    $candidates += $cfg.api_key
  } else {
    $candidates += $cfg.api_key
  }
  $candidates += $env:OPENAI_API_KEY
  foreach ($candidate in $candidates) {
    if ($candidate -and $candidate -ne 'PASTE_YOUR_KEY_HERE' -and $candidate -ne 'REPLACE_ME') {
      return [string]$candidate
    }
  }
  return ''
}

function Get-ApiConfig([string]$modelName) {
  $cfg = @{}
  if (Test-Path $configPath) {
    $cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
  }
  $apiKey = Resolve-ModelApiKey $cfg $modelName
  $apiBase = if ($env:N1N_API_BASE) { $env:N1N_API_BASE } elseif ($cfg.api_base) { $cfg.api_base } else { 'https://api.n1n.ai/v1' }

  if (-not $apiKey -or $apiKey -eq 'PASTE_YOUR_KEY_HERE' -or $apiKey -eq 'REPLACE_ME') {
    throw 'Missing API key. Fill config\n1n.local.json or set N1N_API_KEY.'
  }

  return [ordered]@{
    api_key = [string]$apiKey
    api_base = ([string]$apiBase).TrimEnd('/')
  }
}

function Get-ResponseText($resp) {
  if ($resp.choices -and $resp.choices.Count -gt 0 -and $resp.choices[0].message.content) {
    return [string]$resp.choices[0].message.content
  }
  if ($resp.output_text) {
    return [string]$resp.output_text
  }
  throw 'Unable to extract text from API response.'
}

$cfg = Get-ApiConfig $Model
$systemText = (Get-Text $SystemPrompt $SystemFile).Trim()
$userText = (Get-Text $UserPrompt $UserFile).Trim()
if (-not $userText) {
  throw 'Missing user prompt content.'
}

$messages = @()
if ($systemText) {
  $messages += @{ role = 'system'; content = $systemText }
}
$messages += @{ role = 'user'; content = $userText }

$bodyObj = [ordered]@{
  model = $Model
  messages = $messages
  temperature = $Temperature
  max_tokens = $MaxTokens
}
$body = $bodyObj | ConvertTo-Json -Depth 10
$headers = @{ Authorization = "Bearer $($cfg.api_key)" }
$uri = "$($cfg.api_base)/chat/completions"
$maxAttempts = 3
$resp = $null
$lastError = $null

for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
  try {
    $resp = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec $TimeoutSec
    $lastError = $null
    break
  } catch {
    $lastError = $_
    $detail = $null
    if ($_.Exception.Response) {
      try {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $detail = $reader.ReadToEnd()
      } catch {
        $detail = $null
      }
      if ($detail) {
        throw "API request failed: $detail"
      }
    }
    if ($attempt -ge $maxAttempts) {
      throw
    }
    Start-Sleep -Seconds ([Math]::Min(2 * $attempt, 8))
  }
}

if (-not $resp) {
  if ($lastError) { throw $lastError }
  throw 'API request failed with no response.'
}

$text = (Get-ResponseText $resp).Trim()
if ($OutFile) {
  Set-Content -Path $OutFile -Value $text -Encoding UTF8
} else {
  Write-Output $text
}
