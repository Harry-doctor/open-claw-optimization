[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await($WinRtTask, $ResultType) {
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
  } | Select-Object -First 1).MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  return $netTask.Result
}

function Get-OcrEngine {
  try {
    $lang = New-Object Windows.Globalization.Language('zh-CN')
    $engine = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]::TryCreateFromLanguage($lang)
    if ($engine) { return $engine }
  } catch {}
  return [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]::TryCreateFromUserProfileLanguages()
}

function Get-ScreenBitmap {
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
  $g.Dispose()
  return $bmp
}

function Crop-Bitmap([System.Drawing.Bitmap]$bmp, [System.Drawing.Rectangle]$rect) {
  $target = New-Object System.Drawing.Bitmap $rect.Width, $rect.Height
  $g = [System.Drawing.Graphics]::FromImage($target)
  $g.DrawImage($bmp, 0, 0, $rect, [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()
  return $target
}

function Get-OcrText([Windows.Media.Ocr.OcrEngine]$engine, [System.Drawing.Bitmap]$bmp) {
  $tmp = Join-Path $env:TEMP ('desktop_ocr_' + [guid]::NewGuid().ToString() + '.png')
  $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
  try {
    $file = Await ([Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]::GetFileFromPathAsync($tmp)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softwareBitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
    return [string]$result.Text
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Normalize-Line([string]$line) {
  if (-not $line) { return $null }
  $s = $line.Trim()
  if ($s.Length -lt 2) { return $null }
  $s = $s -replace '\s+', ' '
  $s = $s.Replace('"','').Replace("'",'').Replace('`','')
  $s = $s.Trim(' ','-','_','.',',',';','?',':','!','/')
  if ($s.Length -lt 2) { return $null }
  return $s
}

function Get-LiveCaptionText {
  $proc = Get-Process LiveCaptions -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $proc) { return $null }
  $root = [System.Windows.Automation.AutomationElement]::RootElement
  $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
  $els = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
  $chunks = New-Object System.Collections.Generic.List[string]
  for ($i=0; $i -lt $els.Count; $i++) {
    $name = $els.Item($i).Current.Name
    if ($name -and $name.Length -gt 20 -and $name -notmatch '实时辅助字幕|设置|关闭') {
      $text = ($name -replace '\s+', ' ').Trim()
      if ($text.Length -gt 1000) { $text = $text.Substring($text.Length - 1000) }
      $chunks.Add($text)
    }
  }
  if ($chunks.Count -eq 0) { return $null }
  return ($chunks | Select-Object -Unique) -join "`n"
}

function Get-SlideText([Windows.Media.Ocr.OcrEngine]$engine) {
  $screen = Get-ScreenBitmap
  try {
    $w = $screen.Width
    $h = $screen.Height
    $regions = @(
      (New-Object System.Drawing.Rectangle ([int]($w * 0.03)), ([int]($h * 0.10)), ([int]($w * 0.70)), ([int]($h * 0.42))),
      (New-Object System.Drawing.Rectangle ([int]($w * 0.03)), ([int]($h * 0.54)), ([int]($w * 0.70)), ([int]($h * 0.28)))
    )
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($rect in $regions) {
      $crop = Crop-Bitmap $screen $rect
      try {
        $text = Get-OcrText $engine $crop
        if ($text) {
          foreach ($line in ($text -split "`r?`n")) {
            $n = Normalize-Line $line
            if ($n -and $n.Length -ge 4) { $parts.Add($n) }
          }
        }
      } finally {
        $crop.Dispose()
      }
    }
    if ($parts.Count -eq 0) { return $null }
    return ($parts | Select-Object -Unique) -join "`n"
  } finally {
    $screen.Dispose()
  }
}

function Get-WorkflowConfig {
  $configPath = Join-Path $workspace 'config\course_workflow_models.json'
  if (-not (Test-Path $configPath)) { throw "Missing workflow config: $configPath" }
  return (Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Invoke-StageModel([string]$prompt) {
  $config = Get-WorkflowConfig
  $model = $config.roles.stage_capture_model
  if (-not $model) { throw 'Missing stage_capture_model in workflow config.' }

  $scriptPath = Join-Path $workspace 'scripts\n1n_chat.ps1'
  if (-not (Test-Path $scriptPath)) { throw "Missing model client script: $scriptPath" }

  $tmpDir = Join-Path $workspace 'tmp'
  New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
  $promptPath = Join-Path $tmpDir 'stage_capture_prompt.txt'
  $outputPath = Join-Path $tmpDir 'stage_capture_model_output.txt'
  Set-Content -Path $promptPath -Value $prompt -Encoding UTF8

  powershell -ExecutionPolicy Bypass -File $scriptPath -Model $model -UserFile $promptPath -OutFile $outputPath -Temperature 0.2 -MaxTokens 1800
  if ($LASTEXITCODE -ne 0) {
    throw "Stage model call failed with exit code: $LASTEXITCODE"
  }
  return (Get-Content $outputPath -Raw -Encoding UTF8).Trim()
}

function Build-StageNote([string]$captionText, [string]$slideText) {
  $raw = @()
  if ($slideText) { $raw += "[SLIDE]`n$slideText" }
  if ($captionText) { $raw += "[CAPTION]`n$captionText" }
  if ($raw.Count -eq 0) { throw 'NO_CAPTURED_TEXT' }
  $lines = @(
    '你正在把课堂采集文本整理成中文证券从业资格考试随堂笔记。',
    '只输出正文 markdown，不要前言，不要解释你在做什么。',
    '以课件主线为骨架，吸收老师有价值的补充，删除口语、重复、闲话和无效过渡。',
    '保留定义、分类、公式、变量含义、计算步骤、对比关系、结论、考点提示。',
    '【重点】【高频考点】【易错提醒】要自然嵌在对应知识点附近，不要单独做汇总区。',
    '如果明显是计算类内容，要把公式、代入过程、结果和易错点写清楚。',
    '这是阶段性快照笔记，优先保留有效信息与知识结构，不追求最终文风统一。',
    '',
    '原始材料：',
    ($raw -join "`n`n")
  )
  $prompt = $lines -join "`n"
  return (Invoke-StageModel $prompt).Trim()
}

$workspace = 'C:\Users\admin\.openclaw\workspace'
$outPath = Join-Path $workspace 'current_stage_capture.md'
$statusPath = Join-Path $workspace 'capture_status.json'
$errorPath = Join-Path $workspace 'capture_abort.flag'
$engine = Get-OcrEngine

try {
  $caption = Get-LiveCaptionText
  $slide = Get-SlideText $engine
  $note = Build-StageNote $caption $slide
  Set-Content -Path $outPath -Value $note -Encoding UTF8
  $status = [ordered]@{
    ok = $true
    capturedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    hasCaption = [bool]$caption
    hasSlide = [bool]$slide
    captionChars = if($caption){$caption.Length}else{0}
    slideChars = if($slide){$slide.Length}else{0}
    outFile = $outPath
  } | ConvertTo-Json -Depth 4
  Set-Content -Path $statusPath -Value $status -Encoding UTF8
} catch {
  Set-Content -Path $errorPath -Value ('ABORTED: ' + $_.Exception.Message) -Encoding UTF8
  throw
}
