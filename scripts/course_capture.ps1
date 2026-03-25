param(
  [string]$OutPath = "C:\Users\admin\.openclaw\workspace\course_capture_log.jsonl",
  [int]$IntervalSec = 20
)

$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await($WinRtTask, $ResultType) {
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1).MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}

function Get-OcrEngine {
  try {
    $lang = New-Object Windows.Globalization.Language('zh-CN')
    $e = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]::TryCreateFromLanguage($lang)
    if ($e) { return $e }
  } catch {}
  return [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]::TryCreateFromUserProfileLanguages()
}

function Get-OcrText([Windows.Media.Ocr.OcrEngine]$engine, [System.Drawing.Bitmap]$bmp) {
  $tmp = Join-Path $env:TEMP ('ocr_loop_' + [guid]::NewGuid().ToString() + '.png')
  $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
  try {
    $file = Await ([Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]::GetFileFromPathAsync($tmp)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softwareBitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
    return [string]$result.Text
  } catch {
    return ''
  } finally {
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Clean-Text([string]$s) {
  if (-not $s) { return '' }
  $chars = New-Object System.Collections.Generic.List[char]
  foreach ($ch in $s.ToCharArray()) {
    $code = [int][char]$ch
    if (($code -ge 32 -and $code -ne 0xFFFD) -or $code -eq 10 -or $code -eq 13 -or $code -eq 9) { [void]$chars.Add($ch) }
  }
  (($chars.ToArray() -join '') -replace '\s+',' ').Trim()
}

New-Item -ItemType Directory -Force -Path (Split-Path $OutPath) | Out-Null
$engine = Get-OcrEngine
$lastFingerprint = ''

while ($true) {
  try {
    $captions = @()
    $proc = Get-Process LiveCaptions -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($proc) {
      $root = [System.Windows.Automation.AutomationElement]::RootElement
      $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $proc.Id)
      $els = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
      for ($i=0; $i -lt $els.Count; $i++) {
        $name = Clean-Text $els.Item($i).Current.Name
        if ($name -and $name.Length -gt 20) { $captions += $name }
      }
      $captions = $captions | Select-Object -Unique | Select-Object -Last 3
    }

    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $g.Dispose()

    $rect = New-Object System.Drawing.Rectangle ([int]($bmp.Width*0.03)),([int]($bmp.Height*0.10)),([int]($bmp.Width*0.68)),([int]($bmp.Height*0.60))
    $crop = New-Object System.Drawing.Bitmap $rect.Width, $rect.Height
    $gg = [System.Drawing.Graphics]::FromImage($crop)
    $gg.DrawImage($bmp, 0, 0, $rect, [System.Drawing.GraphicsUnit]::Pixel)
    $gg.Dispose()
    $slideText = Clean-Text (Get-OcrText $engine $crop)
    $crop.Dispose(); $bmp.Dispose()

    $joinedCaptions = (($captions -join ' | ') -replace '\s+',' ').Trim()
    $fingerprint = ($joinedCaptions + ' || ' + $slideText)
    if ($fingerprint -and $fingerprint -ne $lastFingerprint) {
      $obj = [ordered]@{
        ts = (Get-Date).ToString('s')
        captions = $captions
        slide = $slideText
      }
      ($obj | ConvertTo-Json -Compress) | Add-Content -Path $OutPath -Encoding UTF8
      $lastFingerprint = $fingerprint
    }
  } catch {}
  Start-Sleep -Seconds $IntervalSec
}
