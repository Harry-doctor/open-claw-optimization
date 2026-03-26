from __future__ import annotations

import json
from typing import Any, Callable

import tiktoken

DEFAULT_MODEL = 'gpt-5.4'


class CompressionResult(dict):
    @property
    def messages(self):
        return self['messages']

    @property
    def meta(self):
        return self['meta']


def _encoding_for_model(model_hint: str):
    try:
        return tiktoken.encoding_for_model(model_hint)
    except Exception:
        return tiktoken.get_encoding('cl100k_base')


def count_tokens(messages: list[dict[str, Any]], model_hint: str = DEFAULT_MODEL) -> int:
    enc = _encoding_for_model(model_hint)
    total = 0
    for msg in messages or []:
        total += 4
        total += len(enc.encode(str(msg.get('role', ''))))
        content = msg.get('content', '')
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        total += len(enc.encode(str(content)))
    return total + 2


def summarize(messages: list[dict[str, Any]], summarizer: Callable[[list[dict[str, Any]]], str] | None = None) -> str:
    if not messages:
        return '无旧历史需要摘要。'
    if summarizer is not None:
        text = (summarizer(messages) or '').strip()
        if text:
            return text
    preview_lines = []
    for item in messages[-8:]:
        role = item.get('role', 'unknown')
        content = item.get('content', '')
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        preview_lines.append(f"{role}: {str(content)[:240]}")
    return ' | '.join(preview_lines)[:1600] or '历史过长，但摘要生成失败。'


def compress_history(
    history: list[dict[str, Any]],
    max_tokens: int = 4000,
    model_hint: str = DEFAULT_MODEL,
    recent_turns: int = 5,
    summarizer: Callable[[list[dict[str, Any]]], str] | None = None,
):
    history = list(history or [])
    total = count_tokens(history, model_hint=model_hint)
    meta = {
        'triggered': False,
        'before_tokens': total,
        'after_tokens': total,
        'summary_used': False,
        'recent_turns': recent_turns,
    }
    if total <= max_tokens:
        return CompressionResult(messages=history, meta=meta)
    if len(history) <= recent_turns:
        meta['triggered'] = True
        meta['reason'] = 'token_limit_exceeded_but_not_enough_turns_to_summarize'
        return CompressionResult(messages=history, meta=meta)

    recent = history[-recent_turns:]
    old = history[:-recent_turns]
    summary = summarize(old, summarizer=summarizer)
    compressed = [{"role": "system", "content": f"历史摘要：{summary}"}] + recent
    after_tokens = count_tokens(compressed, model_hint=model_hint)
    meta.update({
        'triggered': True,
        'summary_used': True,
        'after_tokens': after_tokens,
        'dropped_messages': len(old),
    })
    return CompressionResult(messages=compressed, meta=meta)
