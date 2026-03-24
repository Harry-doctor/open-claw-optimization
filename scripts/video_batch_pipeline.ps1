param(
    [string]$InputDir,
    [string[]]$Files,
    [string]$Manifest,
    [ValidateSet('name','mtime','manifest')]
    [string]$Order = 'name',
    [switch]$Recursive,
    [Parameter(Mandatory = $true)]
    [string]$OutDir,
    [int]$FrameInterval = 30,
    [int]$MaxFrames = 20,
    [string]$WhisperModel = 'whisper-1',
    [string]$Language = 'zh',
    [string]$TranscriptPrompt = '',
    [string]$OcrLang = 'chi_sim+eng',
    [string]$OcrPsm = '6',
    [switch]$SkipTranscript,
    [switch]$SkipOcr
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

function Fail($Message) {
    Write-Error $Message
    exit 1
}

function Ensure-Bin([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $fallbacks = @()
    switch ($Name.ToLowerInvariant()) {
        'ffmpeg' {
            $fallbacks += @(
                $env:FFMPEG_BIN,
                'C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe'
            )
        }
        'tesseract' {
            $fallbacks += @(
                $env:TESSERACT_BIN,
                'C:\Program Files\Tesseract-OCR\tesseract.exe'
            )
        }
        'curl.exe' {
            $fallbacks += @(
                $env:CURL_BIN,
                'C:\Windows\System32\curl.exe'
            )
        }
    }

    foreach ($candidate in $fallbacks) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }

    throw "Missing required binary: $Name"
}

function Get-NaturalKey([string]$Text) {
    return [regex]::Replace($Text.ToLowerInvariant(), '\d+', {
        param($m)
        $m.Value.PadLeft(20, '0')
    })
}

function Slugify([string]$Text) {
    $slug = [regex]::Replace($Text, '[^\p{L}\p{Nd}_-]+', '-')
    $slug = [regex]::Replace($slug, '-{2,}', '-')
    $slug = $slug.Trim('-', '_')
    if ([string]::IsNullOrWhiteSpace($slug)) { $slug = 'video' }
    if ($slug.Length -gt 80) { $slug = $slug.Substring(0, 80) }
    return $slug
}

function Normalize-Text([string]$Text) {
    if ($null -eq $Text) { $Text = '' }
    return ([regex]::Replace($Text, '\s+', ' ')).Trim()
}

function Write-Utf8([string]$Path, [string]$Content) {
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Set-Content -LiteralPath $Path -Value $Content -Encoding utf8
}

function Get-ProxyUrl {
    $candidates = @(
        $env:HTTPS_PROXY,
        $env:HTTP_PROXY,
        $env:ALL_PROXY
    ) | Where-Object { $_ -and $_.Trim() -ne '' }

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }

    try {
        $reg = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop
        if ($reg.ProxyEnable -eq 1 -and $reg.ProxyServer) {
            $proxy = [string]$reg.ProxyServer
            if ($proxy -match '=') {
                $parts = $proxy -split ';'
                foreach ($part in $parts) {
                    if ($part -match '^(https|http)=') {
                        $proxy = ($part -split '=', 2)[1]
                        break
                    }
                }
            }
            if ($proxy -and $proxy -notmatch '^https?://') {
                $proxy = 'http://' + $proxy
            }
            return $proxy
        }
    }
    catch {
    }

    return $null
}

function Resolve-VideoInputs {
    $videoExts = @('.mp4', '.mov', '.mkv', '.avi', '.wmv', '.m4v', '.flv', '.webm')
    $items = New-Object System.Collections.Generic.List[string]

    if ($Files) {
        foreach ($f in $Files) {
            $items.Add((Resolve-Path $f).Path)
        }
    }

    if ($InputDir) {
        $root = (Resolve-Path $InputDir).Path
        if ($Recursive) {
            $found = Get-ChildItem -LiteralPath $root -File -Recurse
        } else {
            $found = Get-ChildItem -LiteralPath $root -File
        }
        foreach ($file in $found) {
            if ($videoExts -contains $file.Extension.ToLowerInvariant()) {
                $items.Add($file.FullName)
            }
        }
    }

    if ($Manifest) {
        $manifestPath = (Resolve-Path $Manifest).Path
        $manifestData = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
        if ($manifestData -isnot [System.Collections.IEnumerable]) {
            throw 'Manifest must be a JSON array of file paths.'
        }
        foreach ($entry in $manifestData) {
            $items.Add((Resolve-Path ([string]$entry)).Path)
        }
    }

    $uniq = $items | Select-Object -Unique
    if (-not $uniq -or $uniq.Count -eq 0) {
        throw 'No video files found.'
    }

    switch ($Order) {
        'mtime' {
            return $uniq | Sort-Object @{Expression = { (Get-Item $_).LastWriteTimeUtc }}, @{Expression = { Get-NaturalKey([IO.Path]::GetFileName($_)) }}
        }
        default {
            return $uniq | Sort-Object @{Expression = { Get-NaturalKey([IO.Path]::GetFileName($_)) }}
        }
    }
}

function Extract-Audio([string]$VideoPath, [string]$AudioPath) {
    $ffmpegBin = Ensure-Bin 'ffmpeg'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $AudioPath) | Out-Null
    & $ffmpegBin -hide_banner -loglevel error -y -i $VideoPath -vn -ac 1 -ar 16000 -c:a mp3 $AudioPath
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg audio extraction failed: $VideoPath" }
}

function Transcribe-Audio([string]$AudioPath, [string]$TranscriptPath) {
    $curlBin = Ensure-Bin 'curl.exe'
    $audioApiKey = $env:VIDEO_BATCH_STT_API_KEY
    if (-not $audioApiKey) { $audioApiKey = $env:OPENAI_API_KEY }
    if (-not $audioApiKey) {
        throw 'Missing VIDEO_BATCH_STT_API_KEY (or fallback OPENAI_API_KEY) for transcription.'
    }

    $audioModel = $env:VIDEO_BATCH_STT_MODEL
    if (-not $audioModel) { $audioModel = $WhisperModel }

    $audioEndpoint = $env:VIDEO_BATCH_STT_ENDPOINT
    if (-not $audioEndpoint) { $audioEndpoint = 'https://api.openai.com/v1/audio/transcriptions' }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TranscriptPath) | Out-Null

    $proxyUrl = $env:VIDEO_BATCH_STT_PROXY
    if (-not $proxyUrl) { $proxyUrl = Get-ProxyUrl }
    $args = @(
        '-sS', $audioEndpoint,
        '-H', "Authorization: Bearer $audioApiKey",
        '-H', 'Accept: application/json',
        '-F', "file=@$AudioPath",
        '-F', "model=$audioModel",
        '-F', 'response_format=text'
    )
    if ($Language) { $args += @('-F', "language=$Language") }
    if ($TranscriptPrompt) { $args += @('-F', "prompt=$TranscriptPrompt") }
    if ($proxyUrl) { $args += @('--proxy', $proxyUrl) }

    $result = & $curlBin @args
    if ($LASTEXITCODE -ne 0) { throw "Transcription failed: $AudioPath" }
    Write-Utf8 $TranscriptPath ($result | Out-String)
}

function Extract-Frames([string]$VideoPath, [string]$FramesDir) {
    $ffmpegBin = Ensure-Bin 'ffmpeg'
    New-Item -ItemType Directory -Force -Path $FramesDir | Out-Null
    $pattern = Join-Path $FramesDir 'frame_%04d.png'
    & $ffmpegBin -hide_banner -loglevel error -y -i $VideoPath -vf "fps=1/$FrameInterval" $pattern
    if ($LASTEXITCODE -ne 0) { throw "ffmpeg frame extraction failed: $VideoPath" }

    $frames = Get-ChildItem -LiteralPath $FramesDir -Filter 'frame_*.png' | Sort-Object @{Expression = { Get-NaturalKey($_.Name) }}
    if ($MaxFrames -gt 0 -and $frames.Count -gt $MaxFrames) {
        $keep = $frames | Select-Object -First $MaxFrames
        $drop = $frames | Select-Object -Skip $MaxFrames
        foreach ($item in $drop) { Remove-Item -LiteralPath $item.FullName -Force }
        return $keep
    }
    return $frames
}

function Invoke-Ocr([string]$ImagePath) {
    $tesseractBin = Ensure-Bin 'tesseract'
    $result = & $tesseractBin $ImagePath stdout -l $OcrLang --psm $OcrPsm
    if ($LASTEXITCODE -ne 0) { throw "OCR failed: $ImagePath" }
    return ($result | Out-String).Trim()
}

function Dedupe-Blocks([string[]]$Blocks) {
    $result = New-Object System.Collections.Generic.List[string]
    $prevNorm = $null
    foreach ($block in $Blocks) {
        $norm = Normalize-Text $block
        if ([string]::IsNullOrWhiteSpace($norm)) { continue }
        if ($norm -eq $prevNorm) { continue }
        $result.Add($block.Trim())
        $prevNorm = $norm
    }
    return $result
}

function Build-RawMarkdown([string]$VideoName, [string]$Transcript, [string[]]$OcrBlocks) {
    $lines = New-Object System.Collections.Generic.List[string]
    $transcriptBody = '[no transcript]'
    if (-not [string]::IsNullOrWhiteSpace($Transcript)) {
        $transcriptBody = $Transcript.Trim()
    }

    $lines.Add("# $VideoName")
    $lines.Add('')
    $lines.Add('## Audio Transcript')
    $lines.Add('')
    $lines.Add($transcriptBody)
    $lines.Add('')
    $lines.Add('## OCR Excerpts')
    $lines.Add('')

    if ($OcrBlocks -and $OcrBlocks.Count -gt 0) {
        $i = 1
        foreach ($block in $OcrBlocks) {
            $lines.Add("### OCR $i")
            $lines.Add('')
            $lines.Add($block)
            $lines.Add('')
            $i++
        }
    } else {
        $lines.Add('[no ocr content]')
        $lines.Add('')
    }

    return (($lines -join "`n").TrimEnd() + "`n")
}

try {
    if (-not $InputDir -and -not $Manifest -and (-not $Files -or $Files.Count -eq 0)) {
        Fail 'Provide one of: -InputDir / -Manifest / -Files'
    }

    if ($Order -eq 'manifest' -and -not $Manifest) {
        Fail 'Order=manifest requires -Manifest'
    }

    $videos = Resolve-VideoInputs
    $outRoot = [IO.Path]::GetFullPath($OutDir)
    New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

    $summaryVideos = New-Object System.Collections.Generic.List[object]
    $total = $videos.Count
    $idx = 0

    foreach ($videoPath in $videos) {
        $idx++
        $videoItem = Get-Item -LiteralPath $videoPath
        $safeName = Slugify $videoItem.BaseName
        $videoDir = Join-Path $outRoot ('{0:d3}-{1}' -f $idx, $safeName)
        $audioPath = Join-Path $videoDir ($safeName + '.mp3')
        $transcriptPath = Join-Path $videoDir 'transcript.txt'
        $framesDir = Join-Path $videoDir 'frames'
        $ocrDir = Join-Path $videoDir 'ocr'
        $rawMd = Join-Path $videoDir 'raw-material.md'
        $metaJson = Join-Path $videoDir 'meta.json'

        Write-Host ("[{0}/{1}] Processing: {2}" -f $idx, $total, $videoItem.Name)
        New-Item -ItemType Directory -Force -Path $videoDir | Out-Null

        $transcriptText = ''
        $ocrBlocks = @()
        $frameFiles = @()

        if (-not $SkipTranscript) {
            Extract-Audio $videoItem.FullName $audioPath
            Transcribe-Audio $audioPath $transcriptPath
            if (Test-Path -LiteralPath $transcriptPath) {
                $transcriptText = Get-Content -LiteralPath $transcriptPath -Raw -Encoding utf8
            }
        }

        if (-not $SkipOcr) {
            $frameFiles = @(Extract-Frames $videoItem.FullName $framesDir)
            New-Item -ItemType Directory -Force -Path $ocrDir | Out-Null
            $rawBlocks = New-Object System.Collections.Generic.List[string]
            foreach ($frame in $frameFiles) {
                $text = Invoke-Ocr $frame.FullName
                $txtPath = Join-Path $ocrDir ($frame.BaseName + '.txt')
                Write-Utf8 $txtPath $text
                $rawBlocks.Add($text)
            }
            $ocrBlocks = @(Dedupe-Blocks $rawBlocks)
        }

        Write-Utf8 $rawMd (Build-RawMarkdown $videoItem.Name $transcriptText $ocrBlocks)

        $metaAudioPath = $null
        $metaTranscriptPath = $null
        $metaFramesDir = $null
        if (Test-Path -LiteralPath $audioPath) { $metaAudioPath = $audioPath }
        if (Test-Path -LiteralPath $transcriptPath) { $metaTranscriptPath = $transcriptPath }
        if (Test-Path -LiteralPath $framesDir) { $metaFramesDir = $framesDir }

        $meta = [ordered]@{
            video = $videoItem.FullName
            video_name = $videoItem.Name
            index = $idx
            output_dir = $videoDir
            audio_path = $metaAudioPath
            transcript_path = $metaTranscriptPath
            frames_dir = $metaFramesDir
            frame_count = $frameFiles.Count
            ocr_excerpt_count = $ocrBlocks.Count
            raw_material_path = $rawMd
        }
        Write-Utf8 $metaJson ($meta | ConvertTo-Json -Depth 6)
        $summaryVideos.Add([pscustomobject]$meta)
    }

    $summary = [ordered]@{
        count = $summaryVideos.Count
        order = $Order
        videos = $summaryVideos
    }
    $summaryPath = Join-Path $outRoot 'batch-summary.json'
    Write-Utf8 $summaryPath ($summary | ConvertTo-Json -Depth 8)
    Write-Host $summaryPath
}
catch {
    Fail $_
}
