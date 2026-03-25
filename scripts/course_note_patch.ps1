param(
  [string]$SourcePath = 'C:\Users\admin\.openclaw\workspace\current_raw_material.md',
  [string]$NotePath = 'C:\Users\admin\.openclaw\workspace\current_final_note.md',
  [string]$AuditPath = 'C:\Users\admin\.openclaw\workspace\current_quality_audit.md',
  [string]$OutPath = 'C:\Users\admin\.openclaw\workspace\current_final_note_patched.md'
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
if (-not (Test-Path $SourcePath)) { throw "Missing raw source: $SourcePath" }
if (-not (Test-Path $NotePath)) { throw "Missing note source: $NotePath" }
if (-not (Test-Path $AuditPath)) { throw "Missing audit source: $AuditPath" }

$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$model = $config.roles.rewrite_model
if (-not $model) { throw 'Missing rewrite_model in workflow config.' }

$sourceText = (Get-Content $SourcePath -Raw -Encoding UTF8).Trim()
$noteText = (Get-Content $NotePath -Raw -Encoding UTF8).Trim()
$auditRaw = if (Test-Path $AuditPath) { Get-Content $AuditPath -Raw -Encoding UTF8 } else { '' }
$auditText = if ($auditRaw) { $auditRaw.Trim() } else { '' }
if (-not $sourceText) { throw 'Raw source is empty.' }
if (-not $noteText) { throw 'Current note is empty.' }
if (-not $auditText) {
  Set-Content -Path $OutPath -Value $noteText -Encoding UTF8
  Write-Output $OutPath
  exit 0
}

$tmpDir = Join-Path $workspace 'tmp'
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$promptPath = Join-Path $tmpDir 'course_note_patch_prompt.txt'

$prompt = @"
You are not answering a user. You are writing the corrected final course note document itself.
Do NOT output an audit report, issue list, explanation, greeting, summary note, or offer of further help.
Output ONLY the corrected markdown course note body.

任务：根据“原始材料”“当前最终稿”“质检问题单”，产出一份修订后的完整课程笔记正文。

硬性要求：
1. 最终输出必须是“课程笔记正文”，不是问题清单，不是建议列表，不是总结说明。
2. 直接保留/修订课程标题与章节结构，不能改成“问题1/问题2/建议处理”这种格式。
3. 修复质检指出的漏点、术语问题、时间点问题、考试导向偏弱问题。
4. 保持课件主线，把老师补充、考试提示、易错提醒自然嵌入对应知识点附近。
5. 不要凭空补充原始材料中没有的信息；不确定处宁可谨慎表达。
6. 删除任何客服腔、答复腔、总结腔，例如“您好”“如果你需要”“我可以继续帮您”等。
7. 不允许在文末额外新增“重点总结 / 主要时间点及机构 / 常考重点提醒 / 重要定义”这类集中汇总板块；重点和易错点必须嵌在对应知识点附近。
8. 输出 markdown 正文，不要前言，不要解释过程，不要附加说明。

原始材料：
$sourceText

当前最终稿：
$noteText

质检问题单：
$auditText
"@

Set-Content -Path $promptPath -Value $prompt -Encoding UTF8
& $pythonBin $modelClient --model $model --user-file $promptPath --out-file $OutPath --temperature 0.1 --max-tokens 6000
if ($LASTEXITCODE -ne 0) {
  throw "Patch model failed with exit code: $LASTEXITCODE"
}

Write-Output $OutPath
