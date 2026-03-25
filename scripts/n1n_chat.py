#!/usr/bin/env python3
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = WORKSPACE_DIR / 'config' / 'n1n.local.json'
PLACEHOLDER_KEYS = {'', 'PASTE_YOUR_KEY_HERE', 'REPLACE_ME'}


def read_text_arg(value: str | None, file_path: str | None) -> str:
    if file_path:
        return Path(file_path).read_text(encoding='utf-8')
    return value or ''


def extract_text(payload: dict) -> str:
    choices = payload.get('choices') or []
    if choices:
        msg = choices[0].get('message') or {}
        content = msg.get('content')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text' and item.get('text'):
                    parts.append(item['text'])
            if parts:
                return ''.join(parts)
    if payload.get('output_text'):
        return str(payload['output_text'])
    output = payload.get('output') or []
    parts = []
    for block in output:
        for item in block.get('content') or []:
            if item.get('type') == 'output_text' and item.get('text'):
                parts.append(item['text'])
    if parts:
        return ''.join(parts)
    raise RuntimeError(f'Unable to extract text from API response: {json.dumps(payload, ensure_ascii=False)[:1000]}')


def load_local_config() -> dict:
    config_path = Path(os.environ.get('N1N_CONFIG_FILE', str(DEFAULT_CONFIG_PATH))).expanduser()
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return data
    except Exception as exc:
        raise RuntimeError(f'Failed to read local config: {config_path} ({exc})')
    return {}


def pick_api_key(local: dict, model: str) -> str:
    model_lower = (model or '').strip().lower()
    env_override = os.environ.get('N1N_API_KEY') or ''
    if env_override.strip():
        return env_override.strip()

    candidates = []
    if model_lower.startswith('gemini'):
        candidates.extend([local.get('gemini_api_key'), local.get('api_key')])
    elif model_lower.startswith('claude'):
        candidates.extend([local.get('claude_api_key'), local.get('api_key')])
    elif model_lower.startswith('qwen'):
        candidates.extend([local.get('qwen_api_key'), local.get('api_key')])
    elif model_lower.startswith('gpt') or model_lower.startswith('openai/gpt'):
        candidates.extend([local.get('gpt_api_key'), local.get('api_key')])
    else:
        candidates.extend([local.get('api_key')])

    candidates.append(os.environ.get('OPENAI_API_KEY'))
    for value in candidates:
        if not value:
            continue
        value = str(value).strip()
        if value and value not in PLACEHOLDER_KEYS:
            return value
    return ''


def resolve_credentials(model: str) -> tuple[str, str]:
    local = load_local_config()
    api_key = pick_api_key(local, model)
    if not api_key:
        raise RuntimeError('Missing API key. Set N1N_API_KEY or fill config/n1n.local.json.')

    base = os.environ.get('N1N_API_BASE') or local.get('api_base') or 'https://api.n1n.ai/v1'
    base = str(base).strip().rstrip('/')
    return api_key, base


def main() -> int:
    parser = argparse.ArgumentParser(description='Call OpenAI-compatible chat/completions endpoint via unified N1N API.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--system')
    parser.add_argument('--system-file')
    parser.add_argument('--user')
    parser.add_argument('--user-file')
    parser.add_argument('--temperature', type=float, default=0.2)
    parser.add_argument('--max-tokens', type=int, default=1800)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--out-file')
    args = parser.parse_args()

    api_key, base = resolve_credentials(args.model)
    system_text = read_text_arg(args.system, args.system_file).strip()
    user_text = read_text_arg(args.user, args.user_file).strip()
    if not user_text:
        raise RuntimeError('Missing user prompt content.')

    messages = []
    if system_text:
        messages.append({'role': 'system', 'content': system_text})
    messages.append({'role': 'user', 'content': user_text})

    body = {
        'model': args.model,
        'messages': messages,
        'temperature': args.temperature,
        'max_tokens': args.max_tokens,
    }
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url=f'{base}/chat/completions',
        data=data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
            'Accept-Charset': 'utf-8',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) OpenClaw-N1N/1.0',
        },
        method='POST',
    )

    raw = None
    last_exc = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
            break
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode('utf-8', errors='replace')
            except Exception:
                detail = ''
            raise RuntimeError(f'HTTP {exc.code} calling {base}/chat/completions :: {detail[:1000]}') from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_exc = exc
            if attempt >= 3:
                raise
            time.sleep(min(2 * attempt, 8))
    if raw is None:
        raise RuntimeError(f'No response body received from {base}/chat/completions: {last_exc}')
    payload = json.loads(raw)
    text = extract_text(payload).strip()

    if args.out_file:
        Path(args.out_file).write_text(text, encoding='utf-8')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise
