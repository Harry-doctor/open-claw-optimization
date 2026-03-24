param(
  [int]$Minutes = 28,
  [int]$IntervalSec = 90
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$script = Join-Path $workspace 'scripts\capture_stage_once.ps1'
$outPath = Join-Path $workspace 'current_stage_capture.md'
$statusPath = Join-Path $workspace 'capture_status.json'
$abortPath = Join-Path $workspace 'capture_abort.flag'
$deadlinePath = Join-Path $workspace 'capture_deadline.flag'
$watchLog = Join-Path $workspace 'capture_watch.log'
$aggregatePath = Join-Path $workspace 'current_stage_capture_log.md'

foreach($p in @($statusPath,$abortPath,$deadlinePath,$watchLog,$aggregatePath)){
  if(Test-Path $p){ Remove-Item $p -Force -ErrorAction SilentlyContinue }
}

$deadline = (Get-Date).AddMinutes($Minutes)
$lastStageText = ''
Add-Content $watchLog ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' START')

while((Get-Date) -lt $deadline){
  $hadAbort = $false
  try {
    if(Test-Path $abortPath){ Remove-Item $abortPath -Force -ErrorAction SilentlyContinue }
    powershell -ExecutionPolicy Bypass -File $script
  } catch {
    $hadAbort = $true
    $msg = 'ABORTED: ' + $_.Exception.Message
    Set-Content -Path $abortPath -Value $msg -Encoding UTF8
    Add-Content $watchLog ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $msg)
    exit 2
  }
  if(Test-Path $abortPath){
    $hadAbort = $true
    Add-Content $watchLog ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + (Get-Content $abortPath -Raw -ErrorAction SilentlyContinue))
    exit 2
  }
  if(-not (Test-Path $statusPath)){
    $hadAbort = $true
    $msg = 'ABORTED: missing status file after tick'
    Set-Content -Path $abortPath -Value $msg -Encoding UTF8
    Add-Content $watchLog ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $msg)
    exit 2
  }
  if(-not $hadAbort){
    if(Test-Path $outPath){
      $stageText = (Get-Content $outPath -Raw -Encoding UTF8).Trim()
      if($stageText -and $stageText -ne $lastStageText){
        $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        $block = @(
          "## Stage Snapshot $stamp",
          '',
          $stageText,
          '',
          '---',
          ''
        ) -join "`r`n"
        Add-Content -Path $aggregatePath -Value $block -Encoding UTF8
        $lastStageText = $stageText
      }
    }
    Add-Content $watchLog ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' TICK_OK')
  }
  Start-Sleep -Seconds $IntervalSec
}
Set-Content -Path $deadlinePath -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) -Encoding UTF8
Add-Content $watchLog ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' DEADLINE')
