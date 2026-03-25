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

  $meta = @()
  if ($config.reference_doc) {
    if ($config.reference_doc.title) { $meta += "- 参考样例：$($config.reference_doc.title)" }
    if ($config.reference_doc.url) { $meta += "- 来源：$($config.reference_doc.url)" }
    if ($config.reference_doc.revision_id) { $meta += "- 参考修订号：$($config.reference_doc.revision_id)" }
  }
  if ($stageConfig.model) { $meta += "- 当前阶段指定模型：$($stageConfig.model)" }
  if ($stageConfig.feeding_strategy) { $meta += "- 喂料策略：$($stageConfig.feeding_strategy)" }

  $metaBlock = if ($meta.Count -gt 0) { ($meta -join "`n") + "`n" } else { '' }
  return ($metaBlock + "`n" + $guideText).Trim()
}
