function Get-CourseWorkflowReferenceGuide {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [Parameter(Mandatory = $true)]
    [string]$Stage
  )

  $configPath = Join-Path $Workspace 'config\course_workflow_reference.json'
  if (-not (Test-Path $configPath)) { return '' }

  try {
    $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    return ''
  }

  if (-not $config.stages) { return '' }
  $stageConfig = $config.stages.$Stage
  if (-not $stageConfig -or -not $stageConfig.guide_path) { return '' }

  $guidePath = [string]$stageConfig.guide_path
  if (-not [System.IO.Path]::IsPathRooted($guidePath)) {
    $guidePath = Join-Path $Workspace $guidePath
  }
  if (-not (Test-Path $guidePath)) { return '' }

  $guideText = (Get-Content $guidePath -Raw -Encoding UTF8).Trim()
  if (-not $guideText) { return '' }

  $snapshotText = ''
  if ($stageConfig.include_snapshot -and $config.reference_doc -and $config.reference_doc.local_snapshot) {
    $snapshotPath = [string]$config.reference_doc.local_snapshot
    if (-not [System.IO.Path]::IsPathRooted($snapshotPath)) {
      $snapshotPath = Join-Path $Workspace $snapshotPath
    }
    if (Test-Path $snapshotPath) {
      $snapshotText = (Get-Content $snapshotPath -Raw -Encoding UTF8).Trim()
    }
  }

  $lessonsText = ''
  $lessonsPath = Join-Path $Workspace 'references\course-note-reference\05-audit-memory-and-delivery-threshold.md'
  if ($Stage -in @('rewrite', 'audit', 'patch') -and (Test-Path $lessonsPath)) {
    $lessonsText = (Get-Content $lessonsPath -Raw -Encoding UTF8).Trim()
  }

  $meta = @()
  if ($config.reference_doc) {
    if ($config.reference_doc.title) { $meta += "- 参考样例：$($config.reference_doc.title)" }
    if ($config.reference_doc.url) { $meta += "- 来源：$($config.reference_doc.url)" }
    if ($config.reference_doc.revision_id) { $meta += "- 参考修订号：$($config.reference_doc.revision_id)" }
  }
  if ($stageConfig.model) { $meta += "- 当前阶段指定模型：$($stageConfig.model)" }
  if ($stageConfig.feeding_strategy) { $meta += "- 喂料策略：$($stageConfig.feeding_strategy)" }

  $metaBlock = if ($meta.Count -gt 0) { ($meta -join "`n") + "`n" } else { '' }
  $lessonsBlock = if ($lessonsText) { "`n`n审计记忆与可交付阈值（属于长期保留喂料，后续相关任务默认参考）：`n$lessonsText" } else { '' }
  $snapshotBlock = if ($snapshotText) { "`n`n参考文档快照（直接对齐交付形态时使用，不要照抄内容）：`n$snapshotText" } else { '' }
  return ($metaBlock + "`n" + $guideText + $lessonsBlock + $snapshotBlock).Trim()
}
