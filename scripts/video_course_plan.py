#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.wmv', '.m4v', '.flv', '.webm'}
CN_NUM = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
SEGMENT_RE = re.compile(r'[\(（]\s*([一二三四五六七八九十0-9]+)\s*[\)）]\s*$')
LEADING_NO_RE = re.compile(r'^\s*(\d{1,3})\s*[-_.、\s]*')
CHAPTER_AR_RE = re.compile(r'第\s*(\d{1,2})\s*章')
CHAPTER_CN_RE = re.compile(r'第\s*([一二三四五六七八九十两零]{1,3})\s*章')


def cn_to_int(text: str) -> Optional[int]:
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == '十':
        return 10
    if '十' in text:
        parts = text.split('十')
        left = CN_NUM.get(parts[0], 1 if parts[0] == '' else None)
        right = CN_NUM.get(parts[1], 0 if len(parts) > 1 and parts[1] == '' else None)
        if left is None or right is None:
            return None
        return left * 10 + right
    return CN_NUM.get(text)


def extract_chapter_no(name: str) -> Optional[int]:
    m = CHAPTER_AR_RE.search(name)
    if m:
        return int(m.group(1))
    m = CHAPTER_CN_RE.search(name)
    if m:
        return cn_to_int(m.group(1))
    return None


def clean_spaces(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def parse_video_name(path: Path) -> dict:
    stem = path.stem.strip()
    order = 10**9
    display = stem
    m = LEADING_NO_RE.match(stem)
    if m:
        order = int(m.group(1))
        display = stem[m.end():].strip()
    seg_idx = None
    seg_label = None
    title = display
    m2 = SEGMENT_RE.search(display)
    if m2:
        seg_label = m2.group(1)
        seg_idx = cn_to_int(seg_label)
        title = display[:m2.start()].strip()
    title = clean_spaces(title)
    display = clean_spaces(display)
    return {
        'file_name': path.name,
        'file_path': str(path),
        'order': order,
        'segment_title': display,
        'document_title': title or display,
        'segment_label': seg_label,
        'segment_index': seg_idx,
    }


def chapter_sort_key(p: Path):
    no = extract_chapter_no(p.name)
    return (no if no is not None else 10**6, p.name)


def video_sort_key(item: dict):
    seg = item['segment_index'] if item['segment_index'] is not None else 10**6
    return (item['order'], seg, item['file_name'].lower())


def build_plan(root: Path) -> dict:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f'Input root not found or not a directory: {root}')

    chapters = [p for p in root.iterdir() if p.is_dir()]
    chapters.sort(key=chapter_sort_key)

    plan = {
        'root': str(root),
        'chapters': [],
    }

    for chapter_dir in chapters:
        video_files = [p for p in chapter_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        items = [parse_video_name(p) for p in video_files]
        items.sort(key=video_sort_key)

        doc_map = defaultdict(list)
        for item in items:
            doc_map[item['document_title']].append(item)

        documents = []
        for title, docs in doc_map.items():
            docs.sort(key=video_sort_key)
            documents.append({
                'document_title': title,
                'chapter_folder_local': chapter_dir.name,
                'chapter_no': extract_chapter_no(chapter_dir.name),
                'target_folder_hint': chapter_dir.name,
                'parts': docs,
                'part_count': len(docs),
                'first_order': docs[0]['order'] if docs else None,
            })
        documents.sort(key=lambda d: (d['first_order'] if d['first_order'] is not None else 10**6, d['document_title']))

        plan['chapters'].append({
            'chapter_folder_local': chapter_dir.name,
            'chapter_no': extract_chapter_no(chapter_dir.name),
            'document_count': len(documents),
            'documents': documents,
        })

    return plan


def main():
    parser = argparse.ArgumentParser(description='Build offline processing plan from chapter folders and video naming rules.')
    parser.add_argument('--input-root', required=True, help='Root folder containing chapter subfolders.')
    parser.add_argument('--out', help='Write JSON plan to this file.')
    args = parser.parse_args()

    plan = build_plan(Path(args.input_root).expanduser().resolve())
    text = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding='utf-8')
        print(str(out))
    else:
        print(text)


if __name__ == '__main__':
    main()
