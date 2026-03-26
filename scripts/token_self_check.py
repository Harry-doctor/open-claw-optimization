#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
N1N = WORKSPACE / 'scripts' / 'n1n_chat.py'
LOG = WORKSPACE / 'out' / 'token_usage_log.jsonl'
METRICS = WORKSPACE / 'out' / 'token_optimization_metrics.json'


def has(text: str, needle: str) -> bool:
    return needle in text


def load_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def main() -> int:
    code = N1N.read_text(encoding='utf-8-sig')
    rows = load_jsonl(LOG)
    metrics = json.loads(METRICS.read_text(encoding='utf-8-sig')) if METRICS.exists() else {}

    checks = {
        '压缩模块已接入': has(code, 'from context_compressor import compress_history'),
        '缓存模块已接入': has(code, 'from cache_wrapper import cached_api_call'),
        '路由模块已接入': has(code, 'from model_router import route_model'),
        '重试模块已接入': has(code, 'call_with_retry'),
        '压缩在调用前执行': has(code, 'compression = compress_history(') and has(code, 'effective_messages = compression.messages'),
        'tools 启用时强制 required': has(code, "tool_choice = 'required'"),
        '未发现裸直连调用': ('openai.ChatCompletion.create' not in code and 'client.chat.completions.create' not in code),
    }

    print('=== 真实优化层自检 ===')
    for name, ok in checks.items():
        print(('✅ ' if ok else '❌ ') + name)

    print('\n=== 真实 token 结果 ===')
    if rows:
        latest = rows[-1]
        highest = max(rows, key=lambda r: r.get('total_tokens', 0))
        compressed = sum(1 for r in rows if (r.get('extra') or {}).get('compression_triggered'))
        low_model = sum(1 for r in rows if (r.get('extra') or {}).get('final_model') == 'gpt-4o-mini')
        cache_hits = sum(1 for r in rows if (r.get('extra') or {}).get('cache_hit'))
        print(f"最近一次：{latest.get('total_tokens', 0)} tokens，模型 {((latest.get('extra') or {}).get('final_model') or 'unknown')}")
        print(f"历史最高：{highest.get('total_tokens', 0)} tokens，任务 {highest.get('task_id', 'unknown')}")
        print(f"压缩触发次数：{compressed}")
        print(f"低成本模型实际命中次数：{low_model}")
        print(f"缓存命中次数：{cache_hits}")
    else:
        print('⚠️ 未找到 token 日志')

    summary = metrics.get('summary') or {}
    probe = metrics.get('compression_probe') or {}
    probe_comp = probe.get('compression') or {}
    print('\n=== Benchmark 摘要 ===')
    if summary:
        print(f"平均 tokens：{summary.get('baseline_avg_total_tokens')} -> {summary.get('optimized_avg_total_tokens')}")
        print(f"低成本模型实际比例：{int((summary.get('routing_final_low_model_ratio') or 0) * 100)}%")
        print(f"缓存命中率：{int((summary.get('cache_hit_rate') or 0) * 100)}%")
        print(f"典型任务压缩触发率：{int((summary.get('compression_trigger_rate_on_typical_tasks') or 0) * 100)}%")
    else:
        print('⚠️ 未找到 benchmark 摘要')

    if probe_comp:
        print(f"长历史压缩：{probe_comp.get('before_tokens')} -> {probe_comp.get('after_tokens')} tokens")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
