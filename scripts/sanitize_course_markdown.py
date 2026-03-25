#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

HEADING_RE = re.compile(r'^#{1,6}\s+\S')
TRAILING_PATTERNS = [
    re.compile(r'^(如果你需要|如果您需要|如果需要|若你需要|若您需要|若需要)\b'),
    re.compile(r'^(以上为|以上就是|希望这些整理|希望这些内容|如需进一步|后续如果需要)\b'),
    re.compile(r'^(我可以继续帮您|我还可以帮您|欢迎继续|随时告诉我)\b'),
]
FORBIDDEN_TAIL_HEADINGS = [
    re.compile(r'^#{1,6}\s*(重点总结|主要时间点及机构|常考重点提醒|重要定义)\s*$'),
]


def sanitize_markdown(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip('\ufeff')
    lines = text.split('\n')

    first_heading = next((idx for idx, line in enumerate(lines) if HEADING_RE.match(line.strip())), None)
    if first_heading is not None:
        lines = lines[first_heading:]

    cut = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in FORBIDDEN_TAIL_HEADINGS:
            if pattern.search(stripped):
                cut = idx
                break
        if cut is not None:
            break
        for pattern in TRAILING_PATTERNS:
            if pattern.search(stripped):
                cut = idx
                break
        if cut is not None:
            break
    if cut is not None:
        lines = lines[:cut]

    while lines and not lines[-1].strip():
        lines.pop()
    while lines and lines[-1].strip() in {'---', '***'}:
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()

    return '\n'.join(lines).strip() + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='Trim common AI preambles/outros from generated markdown notes.')
    parser.add_argument('path')
    args = parser.parse_args()

    path = Path(args.path)
    text = path.read_text(encoding='utf-8', errors='ignore')
    path.write_text(sanitize_markdown(text), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
