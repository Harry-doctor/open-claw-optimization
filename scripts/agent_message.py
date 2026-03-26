from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
SCHEMA_PATH = WORKSPACE_DIR / 'agent_message_schema.json'


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def make_agent_message(msg_type: str, payload: dict[str, Any], context_id: str | None = None):
    message = {
        'msg_type': msg_type,
        'payload': payload,
        'timestamp': int(time.time()),
    }
    if context_id:
        message['context_id'] = context_id
    return message


def validate_agent_message(message: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = load_schema()
    required = schema.get('required', [])
    for field in required:
        if field not in message:
            errors.append(f'Missing required field: {field}')
    if message.get('msg_type') not in {'task', 'result', 'status'}:
        errors.append('msg_type must be one of task/result/status')
    if not isinstance(message.get('payload'), dict):
        errors.append('payload must be an object')
    return errors
