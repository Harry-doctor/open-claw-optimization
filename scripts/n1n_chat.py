#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cache_wrapper import cached_api_call
from context_compressor import compress_history, count_tokens
from model_router import route_model
from monitor import log_usage
from retry_wrapper import APINetworkError, CircuitBreaker, ContextLengthExceededError, ModelUnavailableError, call_with_retry

DEFAULT_CONFIG_PATH = WORKSPACE_DIR / 'config' / 'n1n.local.json'
DEFAULT_TOOLS_PATH = WORKSPACE_DIR / 'tools.json'
PLACEHOLDER_KEYS = {'', 'PASTE_YOUR_KEY_HERE', 'REPLACE_ME'}


def read_text_arg(value: str | None, file_path: str | None) -> str:
    if file_path:
        return Path(file_path).read_text(encoding='utf-8-sig')
    return value or ''


def load_history(history_file: str | None) -> list[dict[str, Any]]:
    if not history_file:
        return []
    raw = Path(history_file).read_text(encoding='utf-8-sig').strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError('History file must contain a JSON array of messages.')
    return data


def load_tools(tools_file: str | None) -> list[dict[str, Any]]:
    path = Path(tools_file or DEFAULT_TOOLS_PATH)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, list):
        raise RuntimeError(f'Invalid tools file: {path}')
    return data


def extract_output(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    choices = payload.get('choices') or []
    if choices:
        msg = choices[0].get('message') or {}
        tool_calls = msg.get('tool_calls') or []
        if tool_calls:
            tool_payload = {
                'type': 'tool_calls',
                'data': tool_calls,
            }
            return json.dumps(tool_payload, ensure_ascii=False), {'tool_calls': True, 'tool_call_count': len(tool_calls)}
        content = msg.get('content')
        if isinstance(content, str):
            return content, {'tool_calls': False, 'tool_call_count': 0}
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text' and item.get('text'):
                    parts.append(item['text'])
            if parts:
                return ''.join(parts), {'tool_calls': False, 'tool_call_count': 0}
    if payload.get('output_text'):
        return str(payload['output_text']), {'tool_calls': False, 'tool_call_count': 0}
    output = payload.get('output') or []
    parts = []
    for block in output:
        for item in block.get('content') or []:
            if item.get('type') == 'output_text' and item.get('text'):
                parts.append(item['text'])
    if parts:
        return ''.join(parts), {'tool_calls': False, 'tool_call_count': 0}
    raise RuntimeError(f'Unable to extract text from API response: {json.dumps(payload, ensure_ascii=False)[:1000]}')


def load_local_config() -> dict:
    config_path = Path(os.environ.get('N1N_CONFIG_FILE', str(DEFAULT_CONFIG_PATH))).expanduser()
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding='utf-8-sig'))
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


def make_api_callable(api_key: str, base: str, timeout: int):
    def _call(*, messages: list[dict[str, Any]], model: str, temperature: float, max_tokens: int, tools=None, tool_choice=None):
        body: dict[str, Any] = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if tools:
            body['tools'] = tools
        if tool_choice:
            body['tool_choice'] = tool_choice
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            url=f'{base}/chat/completions',
            data=data,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json; charset=utf-8',
                'Accept': 'application/json',
                'Accept-Charset': 'utf-8',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) OpenClaw-N1N/2.0',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode('utf-8', errors='replace')
            except Exception:
                detail = ''
            detail_lower = detail.lower()
            if 'context length' in detail_lower or 'maximum context' in detail_lower or 'too many tokens' in detail_lower:
                raise ContextLengthExceededError(detail[:2000]) from exc
            if exc.code in {503, 404} and ('无可用渠道' in detail or 'no available' in detail_lower or 'distributor' in detail_lower):
                raise ModelUnavailableError(detail[:2000]) from exc
            raise RuntimeError(f'HTTP {exc.code} calling {base}/chat/completions :: {detail[:1000]}') from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise APINetworkError(str(exc)) from exc
    return _call


def summarize_with_small_model(history_messages: list[dict[str, Any]], timeout: int) -> str:
    prompt = [
        {'role': 'system', 'content': '请将以下对话历史总结为一段简短摘要，保留关键约束、结论、待办与上下文。只输出摘要正文。'},
        *history_messages,
    ]
    for candidate_model in ('gpt-3.5-turbo', 'gpt-5.4'):
        try:
            api_key, base = resolve_credentials(candidate_model)
            api_callable = make_api_callable(api_key, base, min(timeout, 90))
            payload = api_callable(messages=prompt, model=candidate_model, temperature=0.1, max_tokens=300, tools=None, tool_choice=None)
            text, _ = extract_output(payload)
            text = text.strip()
            if text:
                return text
        except ModelUnavailableError:
            continue
    fallback_lines = []
    for item in history_messages[-6:]:
        content = item.get('content', '')
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        fallback_lines.append(f"{item.get('role', 'unknown')}: {str(content)[:160]}")
    return ' | '.join(fallback_lines)[:1200]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Call OpenAI-compatible chat/completions endpoint via unified N1N API.')
    parser.add_argument('--model', required=True)
    parser.add_argument('--system')
    parser.add_argument('--system-file')
    parser.add_argument('--user')
    parser.add_argument('--user-file')
    parser.add_argument('--history-file')
    parser.add_argument('--task-type')
    parser.add_argument('--temperature', type=float, default=0.2)
    parser.add_argument('--max-tokens', type=int, default=1800)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--max-context-tokens', type=int, default=4000)
    parser.add_argument('--routing-file')
    parser.add_argument('--disable-routing', action='store_true')
    parser.add_argument('--disable-cache', action='store_true')
    parser.add_argument('--cache-ttl', type=int, default=1800)
    parser.add_argument('--tools-file')
    parser.add_argument('--tool-mode', choices=['off', 'auto', 'required'], default='off')
    parser.add_argument('--task-id')
    parser.add_argument('--out-file')
    parser.add_argument('--meta-out-file')
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    system_text = read_text_arg(args.system, args.system_file).strip()
    user_text = read_text_arg(args.user, args.user_file).strip()
    history_messages = load_history(args.history_file)
    if not user_text and not history_messages:
        raise RuntimeError('Missing user prompt content.')

    messages = list(history_messages)
    if system_text:
        messages.append({'role': 'system', 'content': system_text})
    if user_text:
        messages.append({'role': 'user', 'content': user_text})

    task_id = args.task_id or f'task-{int(time.time())}'
    requested_model = args.model
    if args.disable_routing:
        selected_model = requested_model
        routing_meta = {
            'requested_model': requested_model,
            'selected_model': selected_model,
            'task_type': args.task_type,
            'input_tokens': count_tokens(messages, model_hint=requested_model),
            'matched_rule': None,
            'routing_config': args.routing_file,
            'preserved_explicit_model': True,
        }
    else:
        selected_model, routing_meta = route_model(requested_model, messages, task_type=args.task_type, routing_path=args.routing_file)

    compression = compress_history(
        messages,
        max_tokens=args.max_context_tokens,
        model_hint=selected_model,
        summarizer=lambda old: summarize_with_small_model(old, timeout=args.timeout),
    )
    effective_messages = compression.messages

    tools = load_tools(args.tools_file) if args.tool_mode != 'off' else []
    tool_choice = None
    if tools:
        tool_choice = 'required' if args.tool_mode == 'required' else 'auto'

    api_key, base = resolve_credentials(selected_model)
    api_callable = make_api_callable(api_key, base, args.timeout)
    circuit_breaker = CircuitBreaker(failure_threshold=3, reset_timeout=30)

    def run_retry(model_name: str):
        model_api_key, model_base = resolve_credentials(model_name)
        model_callable = make_api_callable(model_api_key, model_base, args.timeout)
        return call_with_retry(
            effective_messages,
            model_name,
            model_callable,
            max_attempts=3,
            base_delay=2,
            compress_callable=lambda hist, model: (
                lambda result: (result.messages, result.meta)
            )(compress_history(hist, max_tokens=max(2000, args.max_context_tokens - 500), model_hint=model, summarizer=lambda old: summarize_with_small_model(old, timeout=args.timeout))),
            circuit_breaker=circuit_breaker,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )

    def invoke_api():
        try:
            payload, retry_meta = run_retry(selected_model)
            invoke_api.retry_meta = retry_meta
            invoke_api.fallback_model = None
            return payload
        except ModelUnavailableError:
            fallback_model = requested_model if requested_model and requested_model not in {'auto', 'default', 'router'} else 'gpt-5.4'
            if fallback_model == selected_model:
                raise
            payload, retry_meta = run_retry(fallback_model)
            retry_meta['fallback_model'] = fallback_model
            invoke_api.retry_meta = retry_meta
            invoke_api.fallback_model = fallback_model
            return payload

    invoke_api.retry_meta = {'retry_count': 0, 'compression_meta': None}
    invoke_api.fallback_model = None

    extra_cache_payload = {
        'temperature': args.temperature,
        'max_tokens': args.max_tokens,
        'tool_choice': tool_choice,
        'tools': tools,
    }

    if args.disable_cache:
        payload = invoke_api()
        cache_meta = {'cache_hit': False, 'cache_key': None, 'cache_backend': 'disabled'}
    else:
        payload, cache_meta = cached_api_call(
            effective_messages,
            selected_model,
            invoke_api,
            ttl_seconds=args.cache_ttl,
            extra_cache_payload=extra_cache_payload,
        )

    text, output_meta = extract_output(payload)
    text = text.strip()
    usage = payload.get('usage') or {}
    if not usage:
        prompt_tokens = count_tokens(effective_messages, model_hint=selected_model)
        completion_tokens = count_tokens([{'role': 'assistant', 'content': text}], model_hint=selected_model)
        usage = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
        }

    final_model = invoke_api.fallback_model or payload.get('model') or selected_model
    monitor_record = log_usage(
        usage,
        task_id,
        extra={
            'requested_model': requested_model,
            'selected_model': selected_model,
            'final_model': final_model,
            'cache_hit': cache_meta.get('cache_hit'),
            'cache_backend': cache_meta.get('cache_backend'),
            'tool_mode': args.tool_mode,
            'compression_triggered': compression.meta.get('triggered'),
        },
    )

    meta = {
        'task_id': task_id,
        'routing': {**routing_meta, 'final_model': final_model},
        'compression': compression.meta,
        'retry': invoke_api.retry_meta,
        'cache': cache_meta,
        'usage': usage,
        'monitor': monitor_record,
        'tools': {
            'enabled': bool(tools),
            'tool_mode': args.tool_mode,
            'tool_choice': tool_choice,
            'tool_count': len(tools),
        },
        'output': output_meta,
    }

    if args.meta_out_file:
        Path(args.meta_out_file).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')

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
