param(
  [string]$SourcePath = 'C:\Users\admin\.openclaw\workspace\current_raw_material.md',
  [string]$FinalPath = 'C:\Users\admin\.openclaw\workspace\current_final_note.md',
  [string]$OutPath = 'C:\Users\admin\.openclaw\workspace\current_quality_audit.md'
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$workspace = 'C:\Users\admin\.openclaw\workspace'
$referenceHelper = Join-Path $workspace 'scripts\course_note_reference.ps1'
if (Test-Path $referenceHelper) { . $referenceHelper }
$configPath = Join-Path $workspace 'config\course_workflow_models.json'
$n1nConfigPath = Join-Path $workspace 'config\n1n.local.json'
$modelClient = Join-Path $workspace 'scripts\n1n_chat.py'
$pythonBin = Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'
if (-not (Test-Path $pythonBin)) { $pythonBin = 'python.exe' }

if (-not (Test-Path $configPath)) { throw "Missing config: $configPath" }
if (-not (Test-Path $modelClient)) { throw "Missing model client: $modelClient" }
if (-not (Test-Path $SourcePath)) { throw "Missing raw source: $SourcePath" }
if (-not (Test-Path $FinalPath)) { throw "Missing final note: $FinalPath" }

$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$n1nConfig = if (Test-Path $n1nConfigPath) { Get-Content $n1nConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
$model = $config.roles.audit_model
if (-not $model) { $model = $config.roles.structure_model }
if (-not $model) { $model = $config.roles.stage_capture_model }
if (-not $model) { throw 'Missing audit_model/structure_model/stage_capture_model in workflow config.' }

$sourceText = (Get-Content $SourcePath -Raw -Encoding UTF8).Trim()
$finalText = (Get-Content $FinalPath -Raw -Encoding UTF8).Trim()
if (-not $sourceText) { throw 'Raw source is empty.' }
if (-not $finalText) { throw 'Final note is empty.' }
$referenceGuide = if (Get-Command Get-CourseWorkflowReferenceGuide -ErrorAction SilentlyContinue) { Get-CourseWorkflowReferenceGuide -Workspace $workspace -Stage 'audit' } else { '' }

$tmpDir = Join-Path $workspace 'tmp'
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$promptPath = Join-Path $tmpDir 'course_note_audit_prompt.txt'

$prompt = @"
你不是在回复用户，也不是在写建议信。你是在直接输出一份质检问题单。
任何“您好 / 感谢 / 如果您需要 / 我可以继续帮您”之类的话都禁止出现。

你现在是课程笔记质检员。你的任务是对照“原始材料”和“当前最终稿”，判断它是否已经达到“可直接交付”的课程笔记标准，并仅指出真正影响交付质量的问题。

重要边界：
1. 审计目标是判断“是否可交付”，不是追求绝对完美。
2. 不要为了扮演审计员而每轮强行找新问题。
3. 如果旧问题已经修复，不要换个说法重复驳回。
4. 只有会影响考试理解、事实正确性、关键知识覆盖或课程笔记交付形态的真实问题，才可以判为 REVISE。
5. 如果只剩轻微措辞、风格偏好、表格/列表选择、可继续优化但不影响交付的建议，应该判 PASS，并把这些内容放到“可优化项”里。

请重点检查：
1. 是否漏掉了关键知识点、关键时间点、机构名称、分类、结论、老师强调过的考点。
2. 是否有事实风险：术语不准、时间点不准、机构关系写错、概念张冠李戴。
3. 是否有考试导向偏弱的问题：内容过于概括、重点不够醒目、易错点没有嵌入知识点附近。
4. 是否有风格问题：像总结/分析，不像可直接复习的随堂笔记。
5. 是否存在“该弱化的内容写重了 / 该强调的内容写轻了”的情况。

输出要求：
- 只输出 markdown
- 不要重写全文
- 只输出问题清单与修订建议
- 问题按严重度排序
- 如果最终稿出现“您好 / 根据您提供 / 如果您需要 / 我可以继续帮您 / 以下是总结”等回复腔或客服腔，直接判为严重问题
- 如果最终稿把原始知识点改写成泛泛建议、总结说明、方法论，也直接判为严重问题
- 如果没有阻断交付的明显问题，要明确写“结论：PASS”
- 如果确实存在需要继续修订的阻断问题，再写“结论：REVISE”
- 不要把“可优化项”冒充成“必须返工项”

固定输出结构：
# 质检结论
结论：PASS 或 REVISE

# 阻断交付问题
- ...

# 事实与术语风险
- ...

# 考试导向偏弱点
- ...

# 表达与结构问题
- ...

# 可优化项（不阻断交付）
- ...

# 修订动作清单
- ...

参考样例质检规约：
$referenceGuide

原始材料：
$sourceText

当前最终稿：
$finalText
"@

Set-Content -Path $promptPath -Value $prompt -Encoding UTF8
$previousApiKey = $env:N1N_API_KEY
try {
  if ($model -like 'gemini*' -and $n1nConfig -and $n1nConfig.gemini_api_key) {
    $env:N1N_API_KEY = [string]$n1nConfig.gemini_api_key
  }

  & $pythonBin $modelClient --model $model --user-file $promptPath --out-file $OutPath --temperature 0.1 --max-tokens 6000 --timeout 600
  if ($LASTEXITCODE -ne 0) {
    throw "Audit model failed with exit code: $LASTEXITCODE"
  }

  $needsRetry = (-not (Test-Path $OutPath)) -or ((Get-Item $OutPath).Length -le 0)
  if ($needsRetry) {
    Start-Sleep -Seconds 2
    & $pythonBin $modelClient --model $model --user-file $promptPath --out-file $OutPath --temperature 0.1 --max-tokens 7000 --timeout 600
    if ($LASTEXITCODE -ne 0) {
      throw "Audit model retry failed with exit code: $LASTEXITCODE"
    }
  }
} finally {
  if ($null -ne $previousApiKey -and $previousApiKey -ne '') {
    $env:N1N_API_KEY = $previousApiKey
  } else {
    Remove-Item Env:N1N_API_KEY -ErrorAction SilentlyContinue
  }
}

Write-Output $OutPath
