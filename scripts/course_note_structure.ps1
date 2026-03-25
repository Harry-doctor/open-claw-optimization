param(
  [string]$SourcePath = 'C:\Users\admin\.openclaw\workspace\current_raw_material.md',
  [string]$OutPath = 'C:\Users\admin\.openclaw\workspace\current_structured_outline.md'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$referenceHelper = Join-Path $workspace 'scripts\course_note_reference.ps1'
if (Test-Path $referenceHelper) { . $referenceHelper }
$configPath = Join-Path $workspace 'config\course_workflow_models.json'
$modelClient = Join-Path $workspace 'scripts\n1n_chat.py'
$pythonBin = Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $pythonBin)) { $pythonBin = 'python.exe' }

if (-not (Test-Path $configPath)) { throw "Missing config: $configPath" }
if (-not (Test-Path $modelClient)) { throw "Missing model client: $modelClient" }
if (-not (Test-Path $SourcePath)) { throw "Missing raw source: $SourcePath" }

$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$model = $config.roles.structure_model
if (-not $model) { $model = $config.roles.stage_capture_model }
if (-not $model) { throw 'Missing structure_model/stage_capture_model in workflow config.' }

$sourceText = (Get-Content $SourcePath -Raw -Encoding UTF8).Trim()
if (-not $sourceText) { throw 'Raw source is empty.' }
$referenceGuide = if (Get-Command Get-CourseWorkflowReferenceGuide -ErrorAction SilentlyContinue) { Get-CourseWorkflowReferenceGuide -Workspace $workspace -Stage 'structure' } else { '' }

$tmpDir = Join-Path $workspace 'tmp'
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$promptPath = Join-Path $tmpDir 'course_note_structure_prompt.txt'

$prompt = @"
你现在负责把课程原始材料（音频转写 + 画面OCR）整理成一份“结构化知识底稿”，供后续模型继续写成课程笔记。

你的任务不是写最终成稿，而是做“保信息、去噪声、稳结构”的中间层整理。

要求：
1. 严格以课件主线/知识点主线组织结构，不要写成散乱摘要。
2. 优先保留：定义、分类、时间点、机构名称、公式、变量含义、步骤、对比关系、监管分工、老师明确强调的考点。
3. 删除口语、重复、闲聊、情绪化表达、跑题举例；但老师对考点的解释和提醒要保留。
4. 对老师明确说“简单了解/不考/不用记”的内容，允许降级处理，但不要凭空删除可能仍有辨识价值的信息。
5. 如果同一知识点在转写和OCR里重复出现，要主动合并，避免重复堆砌。
6. 对低置信度内容（OCR疑似错字、转写疑似听错、术语不确定）用【待核】标记，不要硬编。
7. 把【重点】【高频考点】【易错提醒】自然嵌在对应知识点附近，不要单独做总表。
8. 输出 markdown 正文，不要前言，不要总结，不要解释你做了什么。

输出结构建议：
- 一级/二级标题按课件主线展开
- 每个知识点下，尽量包含：
  - 核心内容
  - 老师补充
  - 考试提示 / 易错提醒（如有）
  - 【待核】项（如有）

核心原则：
- 宁可谨慎标记【待核】，也不要把不确定内容写死
- 宁可结构化整理，也不要写成泛泛总结
- 这是“结构化知识底稿”，要让后续写作模型一看就能继续扩写成高质量笔记

参考样例规约（只继承组织方法与标签体系，不要照抄内容）：
$referenceGuide

原始材料：
$sourceText
"@

Set-Content -Path $promptPath -Value $prompt -Encoding UTF8
$previousApiKey = $env:N1N_API_KEY
try {
  if ($model -like 'gemini*' -and $n1nConfig -and $n1nConfig.gemini_api_key) {
    $env:N1N_API_KEY = [string]$n1nConfig.gemini_api_key
  }
  & $pythonBin $modelClient --model $model --user-file $promptPath --out-file $OutPath --temperature 0.2 --max-tokens 5000 --timeout 600
  if ($LASTEXITCODE -ne 0) {
    throw "Structure model failed with exit code: $LASTEXITCODE"
  }
} finally {
  if ($null -ne $previousApiKey -and $previousApiKey -ne '') {
    $env:N1N_API_KEY = $previousApiKey
  } else {
    Remove-Item Env:N1N_API_KEY -ErrorAction SilentlyContinue
  }
}

Write-Output $OutPath
