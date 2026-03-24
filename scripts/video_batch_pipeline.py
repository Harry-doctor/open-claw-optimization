#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.wmv', '.m4v', '.flv', '.webm'}


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def natural_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', text)]


def slugify(text: str, max_len: int = 80) -> str:
    stem = re.sub(r'[^\w\-]+', '-', text, flags=re.UNICODE).strip('-_')
    stem = re.sub(r'-{2,}', '-', stem)
    if not stem:
        stem = 'video'
    return stem[:max_len]


def run(cmd: List[str], *, cwd: Optional[Path] = None, capture: bool = False, check: bool = True):
    kwargs = {
        'cwd': str(cwd) if cwd else None,
        'text': True,
    }
    if capture:
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.PIPE
    result = subprocess.run(cmd, **kwargs)
    if check and result.returncode != 0:
        stdout = getattr(result, 'stdout', '') or ''
        stderr = getattr(result, 'stderr', '') or ''
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
    return result


def ensure_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Missing required binary: {name}")
    return path


def collect_files(args) -> List[Path]:
    files: List[Path] = []
    if args.files:
        files.extend(Path(p).expanduser().resolve() for p in args.files)
    if args.input_dir:
        root = Path(args.input_dir).expanduser().resolve()
        iterator: Iterable[Path]
        if args.recursive:
            iterator = root.rglob('*')
        else:
            iterator = root.glob('*')
        files.extend(p.resolve() for p in iterator if p.is_file() and p.suffix.lower() in VIDEO_EXTS)

    if args.manifest:
        manifest_path = Path(args.manifest).expanduser().resolve()
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            raise RuntimeError('Manifest must be a JSON array of file paths.')
        files.extend(Path(str(p)).expanduser().resolve() for p in data)

    uniq = []
    seen = set()
    for path in files:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)

    missing = [str(p) for p in uniq if not p.exists()]
    if missing:
        raise RuntimeError('Some input files do not exist:\n' + '\n'.join(missing))

    if args.order == 'name':
        uniq.sort(key=lambda p: natural_key(p.name))
    elif args.order == 'mtime':
        uniq.sort(key=lambda p: (p.stat().st_mtime, natural_key(p.name)))

    return uniq


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def extract_audio(video: Path, audio_out: Path):
    ensure_bin('ffmpeg')
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(video),
        '-vn',
        '-ac', '1',
        '-ar', '16000',
        '-c:a', 'mp3',
        str(audio_out),
    ]
    run(cmd)


def transcribe_audio(audio_path: Path, transcript_out: Path, *, model: str, language: str = '', prompt: str = ''):
    ensure_bin('curl')
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('Missing OPENAI_API_KEY for transcription.')
    transcript_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        'curl', '-sS', 'https://api.openai.com/v1/audio/transcriptions',
        '-H', f"Authorization: Bearer {os.environ['OPENAI_API_KEY']}",
        '-H', 'Accept: application/json',
        '-F', f'file=@{audio_path}',
        '-F', f'model={model}',
        '-F', 'response_format=text',
    ]
    if language:
        cmd += ['-F', f'language={language}']
    if prompt:
        cmd += ['-F', f'prompt={prompt}']
    result = run(cmd, capture=True)
    transcript_out.write_text(result.stdout or '', encoding='utf-8')


def extract_frames(video: Path, frames_dir: Path, *, every_seconds: int, max_frames: int):
    ensure_bin('ffmpeg')
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / 'frame_%04d.jpg'
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(video),
        '-vf', f'fps=1/{every_seconds}',
        '-q:v', '3',
        str(pattern),
    ]
    run(cmd)
    frames = sorted(frames_dir.glob('frame_*.jpg'), key=lambda p: natural_key(p.name))
    if max_frames > 0:
        frames = frames[:max_frames]
        for extra in sorted(frames_dir.glob('frame_*.jpg'), key=lambda p: natural_key(p.name))[max_frames:]:
            extra.unlink(missing_ok=True)
    return frames


def ocr_image(image_path: Path, *, lang: str = 'chi_sim+eng', psm: str = '6') -> str:
    ensure_bin('tesseract')
    cmd = ['tesseract', str(image_path), 'stdout', '-l', lang, '--psm', psm]
    result = run(cmd, capture=True)
    return (result.stdout or '').strip()


def dedupe_text_blocks(blocks: List[str]) -> List[str]:
    result = []
    prev_norm = None
    for block in blocks:
        norm = re.sub(r'\s+', ' ', block).strip()
        if not norm:
            continue
        if norm == prev_norm:
            continue
        result.append(block.strip())
        prev_norm = norm
    return result


def build_raw_markdown(video_name: str, transcript: str, ocr_blocks: List[str]) -> str:
    parts = [f'# {video_name}', '']
    parts += ['## 音频转写', '', transcript.strip() or '（无转写内容）', '']
    parts += ['## 画面 OCR 摘录', '']
    if ocr_blocks:
        for idx, block in enumerate(ocr_blocks, start=1):
            parts += [f'### OCR {idx}', '', block.strip(), '']
    else:
        parts += ['（无 OCR 内容）', '']
    return '\n'.join(parts).rstrip() + '\n'


def process_video(video: Path, out_root: Path, args, index: int, total: int):
    safe_name = slugify(video.stem)
    video_dir = out_root / f'{index:03d}-{safe_name}'
    video_dir.mkdir(parents=True, exist_ok=True)

    eprint(f'[{index}/{total}] Processing: {video.name}')

    audio_path = video_dir / f'{safe_name}.mp3'
    transcript_path = video_dir / 'transcript.txt'
    frames_dir = video_dir / 'frames'
    ocr_dir = video_dir / 'ocr'
    raw_md = video_dir / 'raw-material.md'
    meta_json = video_dir / 'meta.json'

    transcript_text = ''
    ocr_blocks: List[str] = []
    frame_paths: List[Path] = []

    if not args.skip_transcript:
        extract_audio(video, audio_path)
        transcribe_audio(
            audio_path,
            transcript_path,
            model=args.whisper_model,
            language=args.language,
            prompt=args.transcript_prompt,
        )
        transcript_text = transcript_path.read_text(encoding='utf-8', errors='ignore')

    if not args.skip_ocr:
        frame_paths = extract_frames(
            video,
            frames_dir,
            every_seconds=args.frame_interval,
            max_frames=args.max_frames,
        )
        ocr_dir.mkdir(parents=True, exist_ok=True)
        raw_ocr_blocks = []
        for frame in frame_paths:
            text = ocr_image(frame, lang=args.ocr_lang, psm=args.ocr_psm)
            txt_path = ocr_dir / f'{frame.stem}.txt'
            txt_path.write_text(text, encoding='utf-8')
            raw_ocr_blocks.append(text)
        ocr_blocks = dedupe_text_blocks(raw_ocr_blocks)

    raw_text = build_raw_markdown(video.name, transcript_text, ocr_blocks)
    write_text(raw_md, raw_text)

    meta = {
        'video': str(video),
        'video_name': video.name,
        'index': index,
        'output_dir': str(video_dir),
        'audio_path': str(audio_path) if audio_path.exists() else None,
        'transcript_path': str(transcript_path) if transcript_path.exists() else None,
        'frames_dir': str(frames_dir) if frames_dir.exists() else None,
        'frame_count': len(frame_paths),
        'ocr_excerpt_count': len(ocr_blocks),
        'raw_material_path': str(raw_md),
    }
    meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return meta


def main():
    parser = argparse.ArgumentParser(description='Batch process local videos in sequence: extract audio, transcribe, extract frames, OCR, and save raw materials.')
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument('--input-dir', help='Directory containing video files.')
    src.add_argument('--manifest', help='JSON array of absolute/relative video paths in desired order.')
    parser.add_argument('--files', nargs='*', help='Explicit video file list.')
    parser.add_argument('--recursive', action='store_true', help='Recursively scan --input-dir.')
    parser.add_argument('--order', choices=['name', 'mtime', 'manifest'], default='name', help='Video ordering rule when scanning a directory or files.')
    parser.add_argument('--out-dir', required=True, help='Output directory for batch artifacts.')
    parser.add_argument('--frame-interval', type=int, default=30, help='Extract one frame every N seconds for OCR (default: 30).')
    parser.add_argument('--max-frames', type=int, default=20, help='Maximum frames kept per video (default: 20; 0 means unlimited).')
    parser.add_argument('--whisper-model', default='whisper-1', help='OpenAI transcription model (default: whisper-1).')
    parser.add_argument('--language', default='zh', help='Hint language for transcription (default: zh).')
    parser.add_argument('--transcript-prompt', default='', help='Optional prompt sent to the transcription API.')
    parser.add_argument('--ocr-lang', default='chi_sim+eng', help='Tesseract OCR language pack (default: chi_sim+eng).')
    parser.add_argument('--ocr-psm', default='6', help='Tesseract page segmentation mode (default: 6).')
    parser.add_argument('--skip-transcript', action='store_true', help='Skip audio extraction + transcription.')
    parser.add_argument('--skip-ocr', action='store_true', help='Skip frame extraction + OCR.')
    args = parser.parse_args()

    if not args.input_dir and not args.manifest and not args.files:
        parser.error('Provide one of --input-dir / --manifest / --files ...')

    if args.order == 'manifest' and not args.manifest:
        parser.error('--order manifest requires --manifest')

    out_root = Path(args.out_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    videos = collect_files(args)
    if not videos:
        raise RuntimeError('No video files found.')

    summary = {
        'count': len(videos),
        'order': args.order,
        'videos': [],
    }

    for idx, video in enumerate(videos, start=1):
        meta = process_video(video, out_root, args, idx, len(videos))
        summary['videos'].append(meta)

    summary_path = out_root / 'batch-summary.json'
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(summary_path))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        eprint(f'ERROR: {exc}')
        sys.exit(1)
