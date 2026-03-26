from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
DEFAULT_LOG_PATH = WORKSPACE_DIR / 'out' / 'token_usage_log.jsonl'

token_usage_log = deque(maxlen=100)


def log_usage(usage: dict[str, Any], task_id: str, *, log_path: str | Path | None = None, extra: dict[str, Any] | None = None):
    total_tokens = int(usage.get('total_tokens', 0) or 0)
    prompt_tokens = int(usage.get('prompt_tokens', 0) or 0)
    completion_tokens = int(usage.get('completion_tokens', 0) or 0)
    record = {
        'task_id': task_id,
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': total_tokens,
        'extra': extra or {},
    }
    token_usage_log.append(record)
    out_path = Path(log_path or DEFAULT_LOG_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + '\n')
    if total_tokens > 8000:
        logging.warning('High token usage for task %s: %s', task_id, total_tokens)
    return record
