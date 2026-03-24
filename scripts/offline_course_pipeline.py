#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from video_course_plan import build_plan


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def ensure_python() -> str:
    for candidate in [sys.executable, shutil.which('python'), shutil.which('py')]:
        if candidate:
            return candidate
    raise RuntimeError('Python executable not found.')


def slugify(text: str, max_len: int = 80) -> str:
    stem = re.sub(r'[^\w\-]+', '-', text, flags=re.UNICODE).strip('-_')
    stem = re.sub(r'-{2,}', '-', stem)
    return (stem or 'document')[:max_len]


def run(cmd, cwd: Path | None = None):
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True)
    if result.returncode != 0:
        cmd_text = ' '.join(map(str, cmd))
        raise RuntimeError(f'Command failed ({result.returncode}): {cmd_text}')
    return result


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def build_combined_raw(document_title: str, chapter_name: str, summary_data: dict) -> str:
    parts = [f'# {document_title}', '', f'- 所属章节：{chapter_name}', '']
    for idx, item in enumerate(summary_data.get('videos', []), start=1):
        file_name = item.get('video_name') or Path(item.get('video', '')).name
        raw_path = item.get('raw_material_path')
        raw_text = ''
        if raw_path and Path(raw_path).exists():
            raw_text = Path(raw_path).read_text(encoding='utf-8', errors='ignore').strip()
        parts += [f'## 分段 {idx}：{file_name}', '']
        parts += [raw_text or '（无原始材料）', '']
    return '\n'.join(parts).rstrip() + '\n'


def process_document(document: dict, chapter: dict, out_root: Path, args, scripts_dir: Path, python_bin: str):
    chapter_no = chapter.get('chapter_no')
    chapter_label = chapter.get('chapter_folder_local') or f'chapter-{chapter_no or 0}'
    doc_title = document['document_title']
    first_order = document.get('first_order') or 0

    chapter_dir_name = f"{chapter_no:02d}-{slugify(chapter_label)}" if chapter_no is not None else slugify(chapter_label)
    document_dir_name = f"{first_order:03d}-{slugify(doc_title)}"
    document_dir = out_root / chapter_dir_name / document_dir_name
    raw_batch_dir = document_dir / 'raw-batch'
    document_dir.mkdir(parents=True, exist_ok=True)

    document_meta = {
        'chapter_no': chapter_no,
        'chapter_folder_local': chapter_label,
        'target_folder_hint': document.get('target_folder_hint') or chapter_label,
        'document_title': doc_title,
        'parts': document['parts'],
    }
    write_text(document_dir / 'document-meta.json', json.dumps(document_meta, ensure_ascii=False, indent=2))

    files = [part['file_path'] for part in document['parts']]
    if args.plan_only:
        return {
            **document_meta,
            'document_dir': str(document_dir),
            'combined_raw_path': None,
            'draft_note_path': None,
            'final_note_path': None,
        }

    video_batch_script = scripts_dir / 'video_batch_pipeline.py'
    cmd = [python_bin, str(video_batch_script), '--out-dir', str(raw_batch_dir), '--files', *files]
    if args.frame_interval is not None:
        cmd += ['--frame-interval', str(args.frame_interval)]
    if args.max_frames is not None:
        cmd += ['--max-frames', str(args.max_frames)]
    if args.language:
        cmd += ['--language', args.language]
    if args.transcript_prompt:
        cmd += ['--transcript-prompt', args.transcript_prompt]
    if args.ocr_lang:
        cmd += ['--ocr-lang', args.ocr_lang]
    if args.ocr_psm:
        cmd += ['--ocr-psm', args.ocr_psm]
    if args.skip_transcript:
        cmd += ['--skip-transcript']
    if args.skip_ocr:
        cmd += ['--skip-ocr']

    eprint(f"Processing document: {doc_title}")
    run(cmd)

    summary_path = raw_batch_dir / 'batch-summary.json'
    if not summary_path.exists():
        raise RuntimeError(f'Missing summary after batch processing: {summary_path}')
    summary_data = json.loads(summary_path.read_text(encoding='utf-8'))

    combined_raw_path = document_dir / 'document_raw_material.md'
    combined_raw = build_combined_raw(doc_title, chapter_label, summary_data)
    write_text(combined_raw_path, combined_raw)

    draft_path = document_dir / 'draft_note.md'
    rewrite_path = document_dir / 'final_note.md'

    draft_script = scripts_dir / 'course_note_draft.ps1'
    rewrite_script = scripts_dir / 'course_note_rewrite.ps1'

    run(['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(draft_script), '-SourcePath', str(combined_raw_path), '-OutPath', str(draft_path)])
    run(['powershell', '-ExecutionPolicy', 'Bypass', '-File', str(rewrite_script), '-SourcePath', str(draft_path), '-OutPath', str(rewrite_path)])

    return {
        **document_meta,
        'document_dir': str(document_dir),
        'raw_batch_dir': str(raw_batch_dir),
        'combined_raw_path': str(combined_raw_path),
        'draft_note_path': str(draft_path),
        'final_note_path': str(rewrite_path),
    }


def main():
    parser = argparse.ArgumentParser(description='Offline course pipeline: chapter planning, grouped video processing, draft generation, and final rewrite.')
    parser.add_argument('--input-root', required=True, help='Root folder containing chapter subfolders and videos.')
    parser.add_argument('--out-dir', required=True, help='Output root for artifacts.')
    parser.add_argument('--plan-only', action='store_true', help='Only build the chapter/document plan without processing videos.')
    parser.add_argument('--frame-interval', type=int, default=30)
    parser.add_argument('--max-frames', type=int, default=20)
    parser.add_argument('--language', default='zh')
    parser.add_argument('--transcript-prompt', default='')
    parser.add_argument('--ocr-lang', default='chi_sim+eng')
    parser.add_argument('--ocr-psm', default='6')
    parser.add_argument('--skip-transcript', action='store_true')
    parser.add_argument('--skip-ocr', action='store_true')
    args = parser.parse_args()

    input_root = Path(args.input_root).expanduser().resolve()
    out_root = Path(args.out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    plan = build_plan(input_root)
    scripts_dir = Path(__file__).resolve().parent
    python_bin = ensure_python()

    plan_path = out_root / 'course_plan.json'
    write_text(plan_path, json.dumps(plan, ensure_ascii=False, indent=2))

    upload_manifest = {
        'input_root': str(input_root),
        'plan_path': str(plan_path),
        'documents': [],
    }

    for chapter in plan.get('chapters', []):
        for document in chapter.get('documents', []):
            result = process_document(document, chapter, out_root, args, scripts_dir, python_bin)
            upload_manifest['documents'].append(result)

    manifest_path = out_root / 'upload_manifest.json'
    write_text(manifest_path, json.dumps(upload_manifest, ensure_ascii=False, indent=2))
    print(str(manifest_path))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        eprint(f'ERROR: {exc}')
        sys.exit(1)
