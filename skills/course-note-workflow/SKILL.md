---
name: course-note-workflow
description: Build, rerun, clean up, and deliver reusable offline course-note workflows for recorded lessons, chapter folders, and multi-video course batches. Use when the task involves turning course videos/audio/OCR into structured notes, rerunning only specific stages (structure/rewrite/audit/patch), applying the established course-note reference style, cleaning obsolete workflow artifacts, or packaging the workflow for reuse across different courses.
---

# Course Note Workflow

Use this skill to run the offline course-note pipeline without re-deciding the whole process each time.

## Workflow decision tree

1. **Need to process a fresh course / chapter folder**
   - Run `scripts/run-offline-course-pipeline.ps1`
   - Use a new `-InputRoot` and `-OutDir`

2. **Need to rerun only the broken tail of an existing chain**
   - Run `scripts/rerun-course-note-stage.ps1`
   - Choose `structure` / `rewrite` / `audit` / `patch`
   - Do not rerun earlier stages unless the user explicitly asks

3. **Need to clean obsolete formatting experiments or temp artifacts**
   - Run `scripts/cleanup-course-note-artifacts.ps1`
   - Review the candidate file list first when the path matters

4. **Need to remember the stable style / audit boundaries**
   - Read `references/workflow-boundaries.md`
   - Read `references/audit-threshold.md`
   - Read `references/workflow-reference-routing.md` when model-stage routing matters

## Core operating rules

- Keep the established role split:
  - `structure` → Gemini Lite
  - `audit` → Gemini Lite
  - `rewrite` / `patch` → GPT-5.4
- Treat the Feishu sample doc as a long-term reference for structure and delivery shape, not text to copy.
- If the user says to continue from the problem node, rerun only from that node forward.
- For final Feishu delivery, the assistant may still do format cleanup, structure tightening, and minimal presentation adaptation; do not silently re-author the whole note unless the user asks.
- Prefer preserving valuable information over aggressive slimming.
- Audit for **deliverability**, not theoretical perfection.

## Fresh run workflow

Run:

```powershell
powershell -ExecutionPolicy Bypass -File skills/course-note-workflow/scripts/run-offline-course-pipeline.ps1 \
  -InputRoot <course-root> \
  -OutDir <output-root>
```

Useful switches:

- `-PlanOnly`
- `-FrameInterval <int>`
- `-MaxFrames <int>`
- `-SttBackend local|api`
- `-LocalWhisperModel medium`
- `-Language zh`
- `-SkipTranscript`
- `-SkipOcr`

## Partial rerun workflow

Run:

```powershell
powershell -ExecutionPolicy Bypass -File skills/course-note-workflow/scripts/rerun-course-note-stage.ps1 \
  -Stage patch \
  -SourcePath <document_raw_material.md> \
  -NotePath <current-note.md> \
  -AuditPath <quality_audit.md> \
  -OutPath <patched-note.md>
```

Stage rules:

- `structure`: requires `-SourcePath` and `-OutPath`
- `rewrite`: requires `-SourcePath` and `-OutPath`
- `audit`: requires `-SourcePath`, `-FinalPath`, and `-OutPath`
- `patch`: requires `-SourcePath`, `-NotePath`, `-AuditPath`, and `-OutPath`

## Cleanup workflow

Run:

```powershell
powershell -ExecutionPolicy Bypass -File skills/course-note-workflow/scripts/cleanup-course-note-artifacts.ps1 \
  -TargetDir <document-dir> \
  -WhatIf
```

Default cleanup targets only obvious formatting-experiment leftovers such as:

- `final_note_*feishu_taghead*.md`
- `final_note_*feishu_logicformat*.md`
- `final_note_*feishu_style*.md`
- `final_note_*feishu_cleanup*.md`
- `final_note_*feishu_boldlabels*.md`
- `final_note_*feishu_emphasis*.md`

Remove `-WhatIf` only after verifying the list.

## Bundled references

- `references/workflow-boundaries.md` — stable role split, delivery expectations, and Feishu landing boundary
- `references/workflow-reference-routing.md` — which reference material gets fed into which stage
- `references/audit-threshold.md` — PASS / REVISE rules and recurring gotchas
- `references/reference_doc_sample.md` — local snapshot of the long-term Feishu sample doc
- `references/course_workflow_models.json` — current model-role mapping snapshot
- `references/course_workflow_reference.json` — current stage-reference routing snapshot

## Resource map

- `scripts/run-offline-course-pipeline.ps1` — wrapper for full offline processing
- `scripts/rerun-course-note-stage.ps1` — wrapper for stage-specific reruns
- `scripts/cleanup-course-note-artifacts.ps1` — safe cleanup of obsolete workflow leftovers

Keep the skill lean. If the underlying workspace scripts evolve, update the wrappers and references here instead of rewriting the whole skill.