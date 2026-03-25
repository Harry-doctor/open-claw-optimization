param(
  [string]$SourcePath = 'C:\Users\admin\.openclaw\workspace\current_draft_note.md',
  [string]$OutPath = 'C:\Users\admin\.openclaw\workspace\current_detailed_note.md'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$configPath = Join-Path $workspace 'config\course_workflow_models.json'
$modelClient = Join-Path $workspace 'scripts\n1n_chat.py'
$pythonBin = Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $pythonBin)) { $pythonBin = 'python.exe' }

if (-not (Test-Path $configPath)) { throw "Missing config: $configPath" }
if (-not (Test-Path $modelClient)) { throw "Missing model client: $modelClient" }
if (-not (Test-Path $SourcePath)) { throw "Missing draft source: $SourcePath" }

$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$model = $config.roles.rewrite_model
if (-not $model) { throw 'Missing rewrite_model in workflow config.' }

$sourceText = (Get-Content $SourcePath -Raw -Encoding UTF8).Trim()
if (-not $sourceText) { throw 'Draft source is empty.' }

$tmpDir = Join-Path $workspace 'tmp'
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$promptPath = Join-Path $tmpDir 'course_note_rewrite_prompt.txt'

$prompt = @"
你不是在回复用户，也不是在写总结说明。你是在直接产出最终课程笔记文稿。
任何“您好 / 根据您提供 / 如果您需要 / 我可以继续帮您”之类的话都禁止出现。

你现在负责把课程笔记初稿，统一重写成最终可读版中文随堂笔记。

目标：
1. 保留信息完整性，不删掉真正有价值的知识点。
2. 统一表达风格，让整份笔记像同一套长期维护的课程文档。
3. 继续坚持以课件主线为骨架，但把老师补充和考点提示自然融进去。
4. 对老师明确说“完全不考 / 基本不考 / 不需要记 / 简单了解”的内容，降级处理，不要展开过多。
5. 【重点】【高频考点】【易错提醒】要有明显标签感，并且放在对应知识点附近。
6. 若某处适合用对照、步骤、流程、结构化表达，可以主动整理得更清晰，但不要为了形式堆砌图表。
7. 输出 markdown 正文，不要前言，不要总结你做了什么。
8. 不要凭空补充外部知识；这一阶段只做统一风格重写与结构优化。

风格要求：
- 自然、清晰、可复习
- 少废话，少重复
- 层级分明
- 术语准确
- 重点和易错点醒目但不杂乱

待重写初稿：
$sourceText
"@

Set-Content -Path $promptPath -Value $prompt -Encoding UTF8
& $pythonBin $modelClient --model $model --user-file $promptPath --out-file $OutPath --temperature 0.2 --max-tokens 5000 --timeout 600
if ($LASTEXITCODE -ne 0) {
  throw "Rewrite model failed with exit code: $LASTEXITCODE"
}

Write-Output $OutPath
