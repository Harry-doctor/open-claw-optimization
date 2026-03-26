from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import tiktoken
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
DEFAULT_ROUTING_PATH = WORKSPACE_DIR / 'model_routing.yaml'
DEFAULT_MODEL = 'gpt-5.4'
ROUTABLE_PREFIXES = ('auto', 'default', 'router')


class SafeExprEvaluator(ast.NodeVisitor):
    ALLOWED_NODES = (
        ast.Expression,
        ast.BoolOp,
        ast.UnaryOp,
        ast.BinOp,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.List,
        ast.Tuple,
        ast.Set,
        ast.And,
        ast.Or,
        ast.Not,
        ast.In,
        ast.NotIn,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
    )

    def __init__(self, variables: dict[str, Any]):
        self.variables = variables

    def visit(self, node):
        if not isinstance(node, self.ALLOWED_NODES):
            raise ValueError(f'Unsupported routing expression node: {type(node).__name__}')
        return super().visit(node)

    def visit_Expression(self, node: ast.Expression):
        return self.visit(node.body)

    def visit_BoolOp(self, node: ast.BoolOp):
        values = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError('Unsupported boolean operator.')

    def visit_UnaryOp(self, node: ast.UnaryOp):
        value = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not value
        raise ValueError('Unsupported unary operator.')

    def visit_Name(self, node: ast.Name):
        if node.id not in self.variables:
            raise ValueError(f'Unknown routing variable: {node.id}')
        return self.variables[node.id]

    def visit_Constant(self, node: ast.Constant):
        return node.value

    def visit_List(self, node: ast.List):
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple):
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Set(self, node: ast.Set):
        return {self.visit(elt) for elt in node.elts}

    def visit_BinOp(self, node: ast.BinOp):
        raise ValueError('Binary arithmetic is not supported in routing expressions.')

    def visit_Compare(self, node: ast.Compare):
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            elif isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            else:
                raise ValueError('Unsupported comparison operator.')
            if not ok:
                return False
            left = right
        return True


def _encoding_for_model(model_hint: str):
    try:
        return tiktoken.encoding_for_model(model_hint)
    except Exception:
        return tiktoken.get_encoding('cl100k_base')


def estimate_tokens(messages: list[dict[str, Any]], model_hint: str = DEFAULT_MODEL) -> int:
    enc = _encoding_for_model(model_hint)
    total = 0
    for message in messages or []:
        total += 4
        total += len(enc.encode(str(message.get('role', ''))))
        content = message.get('content', '')
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        total += len(enc.encode(str(content)))
    return total + 2


def infer_task_type(messages: list[dict[str, Any]]) -> str:
    text_parts: list[str] = []
    for message in messages or []:
        content = message.get('content', '')
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            text_parts.append(json.dumps(content, ensure_ascii=False))
    text = '\n'.join(text_parts).lower()
    if any(token in text for token in ('extract', '提取', '抽取', '字段', 'json')):
        return 'info_extract'
    if any(token in text for token in ('format', 'markdown', 'yaml', 'xml', 'csv', '格式转换', '改写成表格')):
        return 'format_convert'
    if any(token in text for token in ('plan', '步骤', '方案', '拆解', 'workflow', 'multi-step', '多步')):
        return 'multi_step_plan'
    if any(token in text for token in ('code', 'python', 'javascript', 'shell', '脚本', '函数', '实现')):
        return 'code_gen'
    if any(token in text for token in ('reason', '推理', '比较', '论证', '分析原因', 'why')):
        return 'complex_reasoning'
    return 'simple_qa'


def load_routing_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path or DEFAULT_ROUTING_PATH)
    if not config_path.exists():
        return {'rules': [], 'default': DEFAULT_MODEL, 'path': str(config_path)}
    data = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f'Invalid routing config: {config_path}')
    data.setdefault('rules', [])
    data.setdefault('default', DEFAULT_MODEL)
    data['path'] = str(config_path)
    return data


def is_routable_model(model: str | None) -> bool:
    if not model:
        return True
    normalized = str(model).strip().lower()
    return any(normalized.startswith(prefix) for prefix in ROUTABLE_PREFIXES)


def evaluate_condition(condition: str, variables: dict[str, Any]) -> bool:
    expr = ast.parse(condition, mode='eval')
    evaluator = SafeExprEvaluator(variables)
    return bool(evaluator.visit(expr))


def route_model(
    requested_model: str | None,
    messages: list[dict[str, Any]],
    task_type: str | None = None,
    routing_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    config = load_routing_config(routing_path)
    explicit_model = (requested_model or '').strip() or config.get('default', DEFAULT_MODEL)
    input_tokens = estimate_tokens(messages, explicit_model)
    inferred_task_type = (task_type or infer_task_type(messages)).strip() or 'simple_qa'
    matched_rule = None
    selected_model = explicit_model
    preserved_explicit_model = False

    if is_routable_model(explicit_model):
        selected_model = config.get('default', DEFAULT_MODEL)
        variables = {'task_type': inferred_task_type, 'input_tokens': input_tokens}
        for rule in config.get('rules', []):
            condition = str(rule.get('condition', '')).strip()
            if not condition:
                continue
            if evaluate_condition(condition, variables):
                selected_model = str(rule.get('model') or selected_model)
                matched_rule = condition
                break
        if explicit_model.lower() not in {'', 'auto', 'default', 'router'} and explicit_model.lower().startswith(('gpt', 'openai/gpt')):
            selected_model = selected_model or explicit_model
    else:
        selected_model = explicit_model
        preserved_explicit_model = True

    meta = {
        'requested_model': requested_model,
        'selected_model': selected_model,
        'task_type': inferred_task_type,
        'input_tokens': input_tokens,
        'matched_rule': matched_rule,
        'routing_config': config.get('path'),
        'preserved_explicit_model': preserved_explicit_model,
    }
    return selected_model, meta
