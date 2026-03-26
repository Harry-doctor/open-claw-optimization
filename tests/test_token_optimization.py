from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agent_message import make_agent_message, validate_agent_message
from cache_wrapper import cached_api_call
from context_compressor import compress_history
from model_router import route_model


def test_route_auto_simple_task_to_low_model():
    messages = [{'role': 'user', 'content': '请提取姓名和手机号并输出 json'}]
    model, meta = route_model('auto', messages, task_type='info_extract', routing_path=ROOT / 'model_routing.yaml')
    assert model == 'gpt-4o-mini'
    assert meta['matched_rule']


def test_explicit_model_is_preserved():
    messages = [{'role': 'user', 'content': '请写一段复杂分析'}]
    model, meta = route_model('gpt-5.4', messages, task_type='complex_reasoning', routing_path=ROOT / 'model_routing.yaml')
    assert model == 'gpt-5.4'
    assert meta['preserved_explicit_model'] is True


def test_history_compression_triggers_when_context_too_large():
    history = []
    for index in range(8):
        history.append({'role': 'user' if index % 2 == 0 else 'assistant', 'content': 'X' * 1200})
    result = compress_history(history, max_tokens=500, model_hint='gpt-5.4', summarizer=lambda msgs: '压缩摘要')
    assert result.meta['triggered'] is True
    assert result.meta['summary_used'] is True
    assert result.meta['after_tokens'] < result.meta['before_tokens']
    assert result.messages[0]['content'].startswith('历史摘要：')


def test_file_cache_hits_on_second_call(tmp_path: Path):
    calls = {'count': 0}

    def fake_call():
        calls['count'] += 1
        return {'choices': [{'message': {'content': 'ok'}}], 'model': 'gpt-5.4'}

    messages = [{'role': 'user', 'content': 'hello'}]
    first, first_meta = cached_api_call(messages, 'gpt-5.4', fake_call, cache_dir=tmp_path)
    second, second_meta = cached_api_call(messages, 'gpt-5.4', fake_call, cache_dir=tmp_path)
    assert first['choices'][0]['message']['content'] == 'ok'
    assert first_meta['cache_hit'] is False
    assert second_meta['cache_hit'] is True
    assert calls['count'] == 1


def test_agent_message_schema_helper():
    message = make_agent_message('task', {'job': 'demo'}, context_id='ctx-1')
    errors = validate_agent_message(message)
    assert errors == []
    assert message['context_id'] == 'ctx-1'
