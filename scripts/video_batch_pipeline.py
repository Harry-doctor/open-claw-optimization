#!/usr/bin/env python3
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.wmv', '.m4v', '.flv', '.webm'}
BASELINE_FRAME_INTERVAL = 25
DENSE_FRAME_INTERVAL = 6
SCENE_CHANGE_THRESHOLD = 0.16
SCENE_MIN_GAP_SECONDS = 2.5
DENSE_WINDOW_SECONDS = 18
OCR_DIFF_THRESHOLD = 0.72
OCR_NEAR_DUP_THRESHOLD = 0.94


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
        'encoding': 'utf-8',
        'errors': 'ignore',
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
    if path:
        return path

    fallbacks = {
        'tesseract': [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        ],
        'ffmpeg': [
            r'C:\ffmpeg\bin\ffmpeg.exe',
        ],
        'ffprobe': [
            r'C:\ffmpeg\bin\ffprobe.exe',
        ],
        'curl': [
            r'C:\Windows\System32\curl.exe',
        ],
    }
    for candidate in fallbacks.get(name, []):
        if Path(candidate).exists():
            return candidate

    raise RuntimeError(f"Missing required binary: {name}")


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


def validate_runtime(args):
    if args.frame_interval <= 0:
        raise RuntimeError('--frame-interval must be greater than 0.')
    if args.max_frames < 0:
        raise RuntimeError('--max-frames must be 0 or greater.')

    if not args.skip_transcript:
        ensure_bin('ffmpeg')
        if args.stt_backend == 'local':
            script = Path(__file__).resolve().parent / 'whisper-transcribe.ps1'
            if not script.exists():
                raise RuntimeError(f'Missing local whisper script: {script}')
            python_root = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Python' / 'Python311'
            whisper_exe = python_root / 'Scripts' / 'whisper.exe'
            if not whisper_exe.exists():
                raise RuntimeError(f'Missing local whisper executable: {whisper_exe}')
        else:
            ensure_bin('curl')
            if not os.environ.get('OPENAI_API_KEY'):
                raise RuntimeError('Missing OPENAI_API_KEY for transcription.')

    if not args.skip_ocr:
        ensure_bin('ffmpeg')
        ensure_bin('ffprobe')
        ensure_bin('tesseract')


def extract_audio(video: Path, audio_out: Path):
    ffmpeg_bin = ensure_bin('ffmpeg')
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin, '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(video),
        '-vn',
        '-ac', '1',
        '-ar', '16000',
        '-c:a', 'mp3',
        str(audio_out),
    ]
    run(cmd)


def transcribe_audio_api(audio_path: Path, transcript_out: Path, *, model: str, language: str = '', prompt: str = ''):
    curl_bin = ensure_bin('curl')
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('Missing OPENAI_API_KEY for transcription.')
    transcript_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        curl_bin, '-sS', 'https://api.openai.com/v1/audio/transcriptions',
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


def transcribe_audio_local(audio_path: Path, transcript_out: Path, *, model: str = 'medium', language: str = 'zh'):
    script = Path(__file__).resolve().parent / 'whisper-transcribe.ps1'
    if not script.exists():
        raise RuntimeError(f'Missing local whisper script: {script}')
    transcript_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        'powershell', '-ExecutionPolicy', 'Bypass', '-File', str(script),
        str(audio_path), str(transcript_out.parent),
        '-Model', model,
        '-OutputFormat', 'txt',
    ]
    if language:
        cmd += ['-Language', language]
    run(cmd)
    generated = transcript_out.parent / f'{audio_path.stem}.txt'
    if not generated.exists():
        raise RuntimeError(f'Local whisper did not produce transcript: {generated}')
    transcript_out.write_text(generated.read_text(encoding='utf-8', errors='ignore'), encoding='utf-8')


def transcribe_audio(audio_path: Path, transcript_out: Path, *, backend: str, model: str, local_model: str, language: str = '', prompt: str = ''):
    if backend == 'local':
        transcribe_audio_local(audio_path, transcript_out, model=local_model, language=language or 'zh')
        return
    transcribe_audio_api(audio_path, transcript_out, model=model, language=language, prompt=prompt)


def parse_pts_times(stderr_text: str) -> List[float]:
    times: List[float] = []
    for line in (stderr_text or '').splitlines():
        match = re.search(r'pts_time:([0-9\.]+)', line)
        if match:
            try:
                times.append(float(match.group(1)))
            except ValueError:
                continue
    return times


def extract_candidates(video: Path, out_dir: Path, *, filter_expr: str, prefix: str) -> List[dict]:
    ffmpeg_bin = ensure_bin('ffmpeg')
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f'{prefix}_*.jpg'):
        old.unlink(missing_ok=True)

    pattern = out_dir / f'{prefix}_%04d.jpg'
    cmd = [
        ffmpeg_bin, '-hide_banner', '-loglevel', 'info', '-y',
        '-i', str(video),
        '-vf', f'{filter_expr},showinfo',
        '-q:v', '3',
        str(pattern),
    ]
    result = run(cmd, capture=True)
    files = sorted(out_dir.glob(f'{prefix}_*.jpg'), key=lambda p: natural_key(p.name))
    pts_times = parse_pts_times(result.stderr)

    candidates = []
    for idx, frame_path in enumerate(files):
        pts_time = pts_times[idx] if idx < len(pts_times) else float(idx)
        candidates.append({
            'path': frame_path,
            'time': round(pts_time, 3),
            'source': prefix,
        })
    return candidates


def normalize_ocr_text(text: str) -> str:
    text = text.replace('\r', '\n')
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()


def text_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def looks_like_formula(text: str) -> bool:
    if not text:
        return False
    if re.search(r'[=＋\+\-−×÷/%≤≥≈∑Σπ√∫\^_()]', text):
        return True
    if re.search(r'\b[a-zA-Z]\s*=\s*\d', text):
        return True
    if re.search(r'\d+\s*/\s*\d+', text):
        return True
    return False


def looks_like_table(text: str) -> bool:
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    if re.search(r'[│┃┆┊|]', text):
        return True
    numeric_heavy_lines = 0
    short_dense_lines = 0
    for line in lines:
        token_count = len(re.findall(r'\S+', line))
        digit_ratio = len(re.findall(r'\d', line)) / max(len(line), 1)
        if token_count >= 3 and digit_ratio >= 0.12:
            numeric_heavy_lines += 1
        if token_count >= 4 and len(line) <= 28:
            short_dense_lines += 1
    return numeric_heavy_lines >= 2 or short_dense_lines >= 3


def classify_dense_content(text: str) -> bool:
    return looks_like_table(text) or looks_like_formula(text)


def keep_candidate(selected: List[dict], candidate: dict, *, target_dir: Path):
    output_path = target_dir / f'frame_{len(selected)+1:04d}.jpg'
    shutil.copy2(candidate['path'], output_path)
    kept = {
        **candidate,
        'output_path': output_path,
    }
    selected.append(kept)
    return kept


def extract_frames(video: Path, frames_dir: Path, *, every_seconds: int, max_frames: int, ocr_lang: str, ocr_psm: str):
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob('frame_*.jpg'):
        old.unlink(missing_ok=True)

    baseline_dir = frames_dir / '_baseline'
    scene_dir = frames_dir / '_scene'
    dense_dir = frames_dir / '_dense'

    baseline = extract_candidates(video, baseline_dir, filter_expr=f'fps=1/{BASELINE_FRAME_INTERVAL}', prefix='baseline')
    scene = extract_candidates(video, scene_dir, filter_expr=f"select='gt(scene,{SCENE_CHANGE_THRESHOLD})'", prefix='scene')
    dense = extract_candidates(video, dense_dir, filter_expr=f'fps=1/{DENSE_FRAME_INTERVAL}', prefix='dense')

    if not baseline:
        raise RuntimeError(
            f'No OCR frames extracted from {video.name}. '
            f'Check the video file or baseline interval ({BASELINE_FRAME_INTERVAL}s).'
        )

    scene_by_time = sorted(scene, key=lambda item: item['time'])
    dense_by_time = sorted(dense, key=lambda item: item['time'])
    ocr_cache: dict[str, str] = {}

    def get_norm_text(path: Path) -> str:
        key = str(path)
        if key not in ocr_cache:
            raw = ocr_image(path, lang=ocr_lang, psm=ocr_psm)
            ocr_cache[key] = normalize_ocr_text(raw)
        return ocr_cache[key]

    selected: List[dict] = []
    first = keep_candidate(selected, baseline[0], target_dir=frames_dir)
    last_text = get_norm_text(first['path'])
    dense_mode_until = first['time'] + DENSE_WINDOW_SECONDS if classify_dense_content(last_text) else -1.0

    def maybe_keep_scene_candidates(window_start: float, window_end: float):
        nonlocal last_text, dense_mode_until
        for cand in scene_by_time:
            if cand.get('_used'):
                continue
            if cand['time'] <= window_start or cand['time'] >= window_end:
                continue
            if selected and cand['time'] - selected[-1]['time'] < SCENE_MIN_GAP_SECONDS:
                continue
            cand_text = get_norm_text(cand['path'])
            if text_similarity(last_text, cand_text) <= OCR_DIFF_THRESHOLD:
                kept = keep_candidate(selected, cand, target_dir=frames_dir)
                cand['_used'] = True
                last_text = cand_text
                if classify_dense_content(cand_text):
                    dense_mode_until = max(dense_mode_until, kept['time'] + DENSE_WINDOW_SECONDS)
                if max_frames > 0 and len(selected) >= max_frames:
                    return True
        return False

    def maybe_keep_dense_candidates(window_start: float, window_end: float):
        nonlocal last_text, dense_mode_until
        if dense_mode_until < 0:
            return False
        effective_end = min(window_end, dense_mode_until)
        for cand in dense_by_time:
            if cand.get('_used'):
                continue
            if cand['time'] <= window_start or cand['time'] >= effective_end:
                continue
            if selected and cand['time'] - selected[-1]['time'] < 5:
                continue
            cand_text = get_norm_text(cand['path'])
            similarity = text_similarity(last_text, cand_text)
            if similarity <= OCR_NEAR_DUP_THRESHOLD or classify_dense_content(cand_text):
                kept = keep_candidate(selected, cand, target_dir=frames_dir)
                cand['_used'] = True
                last_text = cand_text
                if classify_dense_content(cand_text):
                    dense_mode_until = max(dense_mode_until, kept['time'] + DENSE_WINDOW_SECONDS)
                if max_frames > 0 and len(selected) >= max_frames:
                    return True
        return False

    for idx in range(1, len(baseline)):
        prev_time = selected[-1]['time']
        next_baseline = baseline[idx]

        if maybe_keep_scene_candidates(prev_time, next_baseline['time']):
            break
        if maybe_keep_dense_candidates(prev_time, next_baseline['time']):
            break

        next_text = get_norm_text(next_baseline['path'])
        kept = keep_candidate(selected, next_baseline, target_dir=frames_dir)
        last_text = next_text
        if classify_dense_content(next_text):
            dense_mode_until = max(dense_mode_until, kept['time'] + DENSE_WINDOW_SECONDS)
        else:
            dense_mode_until = max(-1.0, dense_mode_until)

        if max_frames > 0 and len(selected) >= max_frames:
            break

    if max_frames > 0 and len(selected) > max_frames:
        selected = selected[:max_frames]

    selection_meta = {
        'mode': 'rule_based_adaptive_no_model',
        'baseline_interval_sec': BASELINE_FRAME_INTERVAL,
        'dense_interval_sec': DENSE_FRAME_INTERVAL,
        'scene_change_threshold': SCENE_CHANGE_THRESHOLD,
        'rules': [
            'baseline one frame every 25 seconds',
            'insert immediate frame on large page change via ffmpeg scene detection',
            'insert immediate frame when OCR text changes sharply',
            'temporarily increase to ~6 seconds per frame when table/formula-like content appears',
            'return to baseline cadence when content stabilizes',
        ],
        'selected_frames': [
            {
                'index': idx + 1,
                'time_sec': item['time'],
                'source': item['source'],
                'file': str(item['output_path'].name),
            }
            for idx, item in enumerate(selected)
        ],
    }
    write_text(frames_dir / 'selection-meta.json', json.dumps(selection_meta, ensure_ascii=False, indent=2))

    return [item['output_path'] for item in selected]


def ocr_image(image_path: Path, *, lang: str = 'chi_sim+eng', psm: str = '6') -> str:
    tesseract_bin = ensure_bin('tesseract')
    cmd = [tesseract_bin, str(image_path), 'stdout', '-l', lang, '--psm', psm]
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
            backend=args.stt_backend,
            model=args.whisper_model,
            local_model=args.local_whisper_model,
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
            ocr_lang=args.ocr_lang,
            ocr_psm=args.ocr_psm,
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
        'frame_selection_mode': 'rule_based_adaptive_no_model',
    }
    meta_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return meta


def main():
    parser = argparse.ArgumentParser(description='Batch process local videos in sequence: extract audio, transcribe, adaptively extract frames, OCR, and save raw materials.')
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument('--input-dir', help='Directory containing video files.')
    src.add_argument('--manifest', help='JSON array of absolute/relative video paths in desired order.')
    parser.add_argument('--files', nargs='*', help='Explicit video file list.')
    parser.add_argument('--recursive', action='store_true', help='Recursively scan --input-dir.')
    parser.add_argument('--order', choices=['name', 'mtime', 'manifest'], default='name', help='Video ordering rule when scanning a directory or files.')
    parser.add_argument('--out-dir', required=True, help='Output directory for batch artifacts.')
    parser.add_argument('--frame-interval', type=int, default=BASELINE_FRAME_INTERVAL, help='Legacy baseline interval knob; adaptive mode still keeps a 25s baseline by default.')
    parser.add_argument('--max-frames', type=int, default=20, help='Maximum frames kept per video (default: 20; 0 means unlimited).')
    parser.add_argument('--stt-backend', choices=['api', 'local'], default=os.environ.get('VIDEO_BATCH_STT_BACKEND', 'api'), help='Speech-to-text backend: api or local (default: env VIDEO_BATCH_STT_BACKEND or api).')
    parser.add_argument('--whisper-model', default='whisper-1', help='OpenAI transcription model when --stt-backend api (default: whisper-1).')
    parser.add_argument('--local-whisper-model', default=os.environ.get('VIDEO_BATCH_LOCAL_WHISPER_MODEL', 'medium'), help='Local Whisper model when --stt-backend local (default: env VIDEO_BATCH_LOCAL_WHISPER_MODEL or medium).')
    parser.add_argument('--language', default='zh', help='Hint language for transcription (default: zh).')
    parser.add_argument('--transcript-prompt', default='', help='Optional prompt sent to the transcription API.')
    parser.add_argument('--ocr-lang', default='chi_sim+eng', help='Tesseract OCR language pack (default: chi_sim+eng).')
    parser.add_argument('--ocr-psm', default='6', help='Tesseract page segmentation mode (default: 6).')
    parser.add_argument('--skip-transcript', action='store_true', help='Skip audio extraction + transcription.')
    parser.add_argument('--skip-ocr', action='store_true', help='Skip adaptive frame extraction + OCR.')
    args = parser.parse_args()

    if not args.input_dir and not args.manifest and not args.files:
        parser.error('Provide one of --input-dir / --manifest / --files ...')

    if args.order == 'manifest' and not args.manifest:
        parser.error('--order manifest requires --manifest')

    validate_runtime(args)

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
