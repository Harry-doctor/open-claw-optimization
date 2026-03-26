from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import mean

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from context_compressor import count_tokens

PYTHON = Path(sys.executable)
CURRENT_CLIENT = SCRIPT_DIR / 'n1n_chat.py'
ROUTING_FILE = WORKSPACE_DIR / 'model_routing.yaml'

TASKS = [
    {
        'id': 'simple_qa',
        'task_type': 'simple_qa',
        'system': None,
        'user': '只回复：ok',
    },
    {
        'id': 'info_extract',
        'task_type': 'info_extract',
        'system': None,
        'user': '从这句里提取姓名和电话并输出 JSON：张三，13800138000。',
    },
    {
        'id': 'format_convert',
        'task_type': 'format_convert',
        'system': None,
        'user': '把这三项转换成 markdown 列表：苹果、香蕉、梨。',
    },
    {
        'id': 'code_gen',
        'task_type': 'code_gen',
        'system': None,
        'user': '写一个 Python 函数，返回列表中最大值；只给代码。',
    },
    {
        'id': 'multi_step_plan',
        'task_type': 'multi_step_plan',
        'system': None,
        'user': '把“整理本周待办并按优先级排好”拆成三步执行计划，简洁输出。',
    },
]


def run_command(cmd: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, env=env)


def write_baseline_client(target_path: Path):
    content = subprocess.run(
        ['git', 'show', 'HEAD:scripts/n1n_chat.py'],
        cwd=WORKSPACE_DIR,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
    ).stdout
    target_path.write_text(content, encoding='utf-8')


def baseline_run(client_path: Path, task: dict) -> dict:
    cmd = [
        str(PYTHON),
        str(client_path),
        '--model',
        'gpt-5.4',
        '--user',
        task['user'],
        '--max-tokens',
        '220',
        '--timeout',
        '120',
    ]
    if task.get('system'):
        cmd.extend(['--system', task['system']])
    env = dict(**os.environ)
    env['N1N_CONFIG_FILE'] = str(WORKSPACE_DIR / 'config' / 'n1n.local.json')
    result = run_command(cmd, env=env)
    output = result.stdout.strip()
    messages = []
    if task.get('system'):
        messages.append({'role': 'system', 'content': task['system']})
    messages.append({'role': 'user', 'content': task['user']})
    prompt_tokens = count_tokens(messages, model_hint='gpt-5.4')
    completion_tokens = count_tokens([{'role': 'assistant', 'content': output}], model_hint='gpt-5.4')
    return {
        'task_id': task['id'],
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': prompt_tokens + completion_tokens,
        'model': 'gpt-5.4',
    }


def optimized_run(task: dict, *, disable_cache: bool = True) -> dict:
    tmp_dir = WORKSPACE_DIR / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_file = tmp_dir / f"benchmark_{task['id']}.txt"
    meta_file = tmp_dir / f"benchmark_{task['id']}.meta.json"
    cmd = [
        str(PYTHON),
        str(CURRENT_CLIENT),
        '--model',
        'auto',
        '--task-type',
        task['task_type'],
        '--user',
        task['user'],
        '--out-file',
        str(out_file),
        '--meta-out-file',
        str(meta_file),
        '--max-tokens',
        '220',
        '--timeout',
        '120',
        '--routing-file',
        str(ROUTING_FILE),
    ]
    if disable_cache:
        cmd.append('--disable-cache')
    if task.get('system'):
        cmd.extend(['--system', task['system']])
    run_command(cmd)
    meta = json.loads(meta_file.read_text(encoding='utf-8'))
    return {
        'task_id': task['id'],
        'prompt_tokens': int(meta['usage']['prompt_tokens']),
        'completion_tokens': int(meta['usage']['completion_tokens']),
        'total_tokens': int(meta['usage']['total_tokens']),
        'selected_model': meta['routing']['selected_model'],
        'final_model': meta['routing']['final_model'],
        'cache_hit': bool(meta['cache']['cache_hit']),
        'compression_triggered': bool(meta['compression']['triggered']),
        'retry_count': int(meta['retry']['retry_count']),
    }


def compression_probe() -> dict:
    tmp_dir = WORKSPACE_DIR / 'tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    history = []
    for idx, ch in enumerate(['A', 'B', 'C', 'D', 'E']):
        history.append({'role': 'user', 'content': f'第{idx + 1}轮'})
        history.append({'role': 'assistant', 'content': ch * 1500})
    history.append({'role': 'user', 'content': '最后请你只回复：done'})
    history_file = tmp_dir / 'benchmark_history.json'
    history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')
    meta_file = tmp_dir / 'benchmark_history.meta.json'
    out_file = tmp_dir / 'benchmark_history.out.txt'
    cmd = [
        str(PYTHON),
        str(CURRENT_CLIENT),
        '--model', 'gpt-5.4',
        '--history-file', str(history_file),
        '--max-context-tokens', '500',
        '--out-file', str(out_file),
        '--meta-out-file', str(meta_file),
        '--max-tokens', '20',
        '--timeout', '120',
        '--disable-cache',
    ]
    run_command(cmd)
    meta = json.loads(meta_file.read_text(encoding='utf-8'))
    return meta


def main() -> int:
    results = {
        'baseline': [],
        'optimized': [],
        'cache_second_pass': [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        baseline_client = Path(tmp) / 'n1n_chat_baseline.py'
        write_baseline_client(baseline_client)
        for task in TASKS:
            results['baseline'].append(baseline_run(baseline_client, task))
        for task in TASKS:
            results['optimized'].append(optimized_run(task, disable_cache=True))
        for task in TASKS:
            optimized_run(task, disable_cache=False)
        for task in TASKS:
            results['cache_second_pass'].append(optimized_run(task, disable_cache=False))

    compression_meta = compression_probe()
    baseline_avg = mean(item['total_tokens'] for item in results['baseline'])
    optimized_avg = mean(item['total_tokens'] for item in results['optimized'])
    routing_selected_hits = sum(1 for item in results['optimized'] if item['selected_model'] == 'gpt-3.5-turbo')
    routing_final_hits = sum(1 for item in results['optimized'] if item['final_model'] == 'gpt-3.5-turbo')
    cache_hit_rate = sum(1 for item in results['cache_second_pass'] if item['cache_hit']) / len(results['cache_second_pass'])
    compression_trigger_rate = sum(1 for item in results['optimized'] if item['compression_triggered']) / len(results['optimized'])
    retry_total = sum(item['retry_count'] for item in results['optimized'])

    report = {
        'tasks': TASKS,
        'baseline': results['baseline'],
        'optimized': results['optimized'],
        'cache_second_pass': results['cache_second_pass'],
        'summary': {
            'baseline_avg_total_tokens': round(baseline_avg, 2),
            'optimized_avg_total_tokens': round(optimized_avg, 2),
            'delta_total_tokens': round(optimized_avg - baseline_avg, 2),
            'routing_selected_low_model_ratio': round(routing_selected_hits / len(results['optimized']), 4),
            'routing_final_low_model_ratio': round(routing_final_hits / len(results['optimized']), 4),
            'cache_hit_rate': round(cache_hit_rate, 4),
            'compression_trigger_rate_on_typical_tasks': round(compression_trigger_rate, 4),
            'retry_total': retry_total,
        },
        'compression_probe': compression_meta,
        'system_prompt_final_tokens': 0,
        'notes': [
            '仓库中未找到 system_prompt.md / system_prompt.txt / config.yml，因此系统提示词精简步骤按规则跳过。',
            '路由规则可命中简单任务，但当前上游渠道对 gpt-3.5-turbo 不可用，因此运行时会自动回退到 gpt-5.4。',
            'Redis Python 客户端已安装，但本机未发现 Redis 服务，因此缓存后端自动降级为本地文件缓存。',
        ],
    }
    out_path = WORKSPACE_DIR / 'out' / 'token_optimization_metrics.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out_path))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
