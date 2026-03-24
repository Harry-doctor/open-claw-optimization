param(
  [string]$SourcePath = 'C:\Users\admin\.openclaw\workspace\current_stage_capture_log.md',
  [string]$OutPath = 'C:\Users\admin\.openclaw\workspace\current_draft_note.md'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$configPath = Join-Path $workspace 'config\course_workflow_models.json'
$modelClient = Join-Path $workspace 'scripts\n1n_chat.ps1'

if (-not (Test-Path $configPath)) { throw "Missing config: $configPath" }
if (-not (Test-Path $modelClient)) { throw "Missing model client: $modelClient" }

if (-not (Test-Path $SourcePath)) {
  $fallback = Join-Path $workspace 'current_stage_capture.md'
  if (Test-Path $fallback) {
    $SourcePath = $fallback
  } else {
    throw "Missing stage source: $SourcePath"
  }
}

$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$model = $config.roles.draft_model
if (-not $model) { throw 'Missing draft_model in workflow config.' }

$sourceText = (Get-Content $SourcePath -Raw -Encoding UTF8).Trim()
if (-not $sourceText) { throw 'Stage source is empty.' }

$tmpDir = Join-Path $workspace 'tmp'
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$promptPath = Join-Path $tmpDir 'course_note_draft_prompt.txt'

$prompt = @"
你现在负责把“阶段性采集快照笔记”整理成一份中文课程笔记初稿。

任务目标：
1. 以课件主线组织内容。
2. 吸收老师有价值的解释、强调、考点提示。
3. 删除口语、重复、噪声、无效过渡句。
4. 保留定义、分类、公式、变量含义、计算步骤、比较关系、结论、考点提醒。
5. 不要写成闲聊口吻，要写成能继续加工的课程笔记初稿。
6. 输出 markdown 正文，不要前言，不要解释过程。
7. 如果内容仍有残缺，不要硬编；宁可保持谨慎表达。
8. 【重点】【高频考点】【易错提醒】可以先初步嵌入，但此阶段以结构清楚、信息完整为第一优先级。
9. 如果发现明显属于同一知识点的多次阶段快照，要主动合并去重。

输出要求：
- 使用清晰标题层级
- 以知识点为主，不做聊天式转述
- 高频考点不要单独集中列总表，要放在对应知识点附近
- 若涉及计算类内容，要把公式、代入逻辑和易错点写明

原始阶段快照：
$sourceText
"@

Set-Content -Path $promptPath -Value $prompt -Encoding UTF8
powershell -ExecutionPolicy Bypass -File $modelClient -Model $model -UserFile $promptPath -OutFile $OutPath -Temperature 0.2 -MaxTokens 4000
if ($LASTEXITCODE -ne 0) {
  throw "Draft model failed with exit code: $LASTEXITCODE"
}

Write-Output $OutPath
