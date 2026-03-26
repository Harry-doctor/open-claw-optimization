# Token Optimization Report

## Summary

- Benchmark sample: 5 typical tasks
  - `simple_qa`
  - `info_extract`
  - `format_convert`
  - `code_gen`
  - `multi_step_plan`
- Baseline average total tokens: **67.8**
- Optimized average total tokens: **54.4**
- Average reduction: **13.4 tokens / 19.8%**

## Step-by-step implementation results

| Step | Status | Before | After | Delta | Notes |
|---|---|---:|---:|---:|---|
| 1. 精简系统提示词与角色定义 | Skipped | N/A | N/A | N/A | 仓库内未找到 `system_prompt.md` / `system_prompt.txt` / `config.yml`，按要求跳过，未强改其他配置文件。 |
| 2. 动态模型路由与简单任务降级 | Done | 67.8 | 54.4 | -13.4 | 路由规则已接入主调用层；5 个典型任务中，规则层命中低模型 `gpt-3.5-turbo` 的比例为 **60%**。但由于当前上游渠道不提供 `gpt-3.5-turbo`，运行时实际都会自动回退到 `gpt-5.4`。 |
| 3. 上下文压缩与历史管理 | Done | 2149* | 1195* | -954 / -44.4% | 典型 5 任务中未触发压缩；额外长历史探针中，压缩前 token 估算 **2149**，压缩后 **1195**。 |
| 4. Function Calling 替代自由文本 | Done (兼容模式) | 136** | 153** | +17 / +12.5% | 对 manager-agent 场景已支持 `tools` + `tool_choice=required`。该改动主要提升结构化可控性，不一定降低 token；实测工具模式比自由文本略增。为避免打断现有课程笔记链路，默认仍保持 legacy 文本模式，manager/tool 场景再显式开启。 |
| 5. 错误重试与熔断机制 | Done | 0 retries | 0 retries | 0 | 已接入重试、上下文超限压缩重试、熔断和模型不可用自动回退。当前健康网络样本中未触发真实重试。 |
| 6. 多 Agent 通信优化 | Partial | N/A | N/A | N/A | 当前仓库没有现成的多-agent消息总线/Redis状态同步代码，因此新增了 `agent_message_schema.json` 和 helper，先把 schema 与校验契约补齐。 |
| 7. 缓存层实现 | Done (Redis-first, file fallback) | 54.4*** | ~0*** | ~-54.4 | 重复相同请求的第二次缓存命中率 **100%**。本机未安装 Redis 服务，因此自动降级为本地文件缓存；重复请求不再消耗远端模型调用。 |
| 8. 监控与自适应调整 | Done | None | Enabled | N/A | 新增 token usage 日志与高 token 告警，输出到 `out/token_usage_log.jsonl`。 |
| 9. 验证与测试 | Done | N/A | `5 passed` | N/A | 新增 `tests/test_token_optimization.py`，`pytest` 通过。另做了真实 API smoke test 与课程脚本 `course_note_rewrite.ps1` 回归。 |

\* Step 3 为长历史压缩专项探针，不是 5 个典型单轮任务平均值。  
\** Step 4 为 manager-agent 场景专项对比：同一请求在自由文本模式与强制工具调用模式下的 token 对比。  
\*** Step 7 的“After”指重复请求命中缓存后的**新增远端模型 token 消耗**近似为 0；日志中仍会保留原响应 usage 以便对账，因此缓存命中后的日志 token 不等于“再次真实请求模型的 token”。

## 5-task benchmark details

| Task | Baseline total tokens | Optimized total tokens | Change | Selected model | Final model |
|---|---:|---:|---:|---|---|
| simple_qa | 20 | 15 | -5 | gpt-3.5-turbo | gpt-5.4 |
| info_extract | 60 | 44 | -16 | gpt-3.5-turbo | gpt-5.4 |
| format_convert | 58 | 36 | -22 | gpt-3.5-turbo | gpt-5.4 |
| code_gen | 83 | 81 | -2 | gpt-5.4 | gpt-5.4 |
| multi_step_plan | 118 | 96 | -22 | gpt-5.4 | gpt-5.4 |
| **Average** | **67.8** | **54.4** | **-13.4** | — | — |

## Required delivery metrics

- **系统提示词最终长度（token）**：**0**
  - 说明：仓库未找到独立系统提示词文件，因此该项按“无独立文件”记为 0；未擅自篡改其他配置。

- **模型路由命中率（简单任务使用 gpt-3.5 的比例）**
  - 规则命中率（selected model）：**60%**
  - 实际成功落到低模型（final model）：**0%**
  - 原因：当前上游渠道对 `gpt-3.5-turbo` 无可用 distributor，已自动回退到 `gpt-5.4`。

- **压缩触发频率**
  - 5 个典型任务：**0%**
  - 长历史专项探针：**100%**（1/1）

- **缓存命中率**
  - 预热后第二次重复请求：**100%**
  - 当前后端：**file fallback**（Redis service unavailable）

- **异常重试次数变化**
  - Baseline benchmark：**0**
  - Optimized benchmark：**0**
  - 说明：当前样本在健康网络下未触发网络重试；但已新增上下文超限压缩重试、熔断和模型不可用自动回退逻辑。

## Validation log

### Static / unit validation

- `python -m py_compile scripts/n1n_chat.py ...`：通过
- `pytest tests/test_token_optimization.py -q`：**5 passed**

### Runtime smoke validation

- `scripts/n1n_chat.py` 基础调用：通过
- `scripts/n1n_chat.ps1` 包装器调用：通过
- `tool_mode=required` 强制函数调用：通过，返回 `tool_calls`
- 长历史压缩探针：通过
- 课程工作流脚本 `scripts/course_note_rewrite.ps1` 小样本回归：通过

## Files added / changed

### Added

- `model_routing.yaml`
- `tools.json`
- `agent_message_schema.json`
- `scripts/model_router.py`
- `scripts/context_compressor.py`
- `scripts/retry_wrapper.py`
- `scripts/cache_wrapper.py`
- `scripts/monitor.py`
- `scripts/agent_message.py`
- `scripts/token_optimization_benchmark.py`
- `tests/test_token_optimization.py`
- `token_optimization_report.md`

### Updated

- `scripts/n1n_chat.py`
- `scripts/n1n_chat.ps1`

## Compatibility notes

1. **显式指定模型优先**：如果调用方明确传 `gpt-5.4` / `gemini-*` / `claude-*` 等，路由不会偷偷改模型；只有 `auto/default/router` 才走自动路由。
2. **函数调用采用兼容模式**：已支持 `tools` 与 `tool_choice=required`，但未对所有文本型课程脚本强制开启，否则会直接打断现有产物形态。
3. **缓存为 Redis-first + file fallback**：本机 Python `redis` 客户端已安装，但机器上没有 Redis service，因此实际使用本地文件缓存。
4. **低模型不可用自动回退**：路由命中 `gpt-3.5-turbo` 时，如上游无可用渠道，会自动 fallback 到 `gpt-5.4`，避免核心流程直接炸掉。
