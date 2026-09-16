# Cockpit Console — 交互式控制台

> 从只读监控仪表板升级为可交互的控制平面。

## 概述

Console 是 Cockpit 仪表板的交互控制层，提供三大功能域：

| 标签页 | 功能 | 入口 |
|--------|------|------|
| **BOS** | BOS URI 调用 REPL，带风险分级和确认令牌 | `/console` → BOS |
| **MOF** | MOF 约束审计、评估、规则目录、价值循环概览 | `/console` → MOF |
| **Harness** | Harness 流水线执行、SSE 事件流、8 阶段 DAG | `/console` → Harness |

## 风险分级

| 级别 | 触发条件 | 确认要求 |
|------|----------|----------|
| `read` | 只读操作（health/list/query/audit/check） | 无需确认 |
| `write` | 写入操作（write/create/submit/run/infer/compile/patch） | `X-Console-Confirm` 请求头 |
| `dangerous` | 危险操作（delete/reset/closeout/trip/sediment/enforce）或 harness 域 | `X-Console-Confirm` 请求头 |

**确认令牌格式**: `X-Console-Confirm: {uri}:sha256(body)[:16]`

## 后端 API

### BOS Console (`/api/console/bos/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/console/bos/invoke` | POST | 调用 BOS URI（带风险检查） |
| `/api/console/bos/schema` | GET | 获取 BOS URI 参数 schema |
| `/api/console/bos/catalog` | GET | 已知服务目录 |
| `/api/console/bos/history` | GET | 调用历史（JSONL） |

### MOF Console (`/api/console/mof/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/console/mof/audit` | POST | 完整 L3 约束审计 |
| `/api/console/mof/evaluate` | POST | 单条约束评估 |
| `/api/console/mof/rules` | GET | 规则目录（126 条） |
| `/api/console/mof/dimensions` | GET | 维度系统 |
| `/api/console/mof/value-loop` | GET | 价值循环概览 |

### Harness Console (`/api/console/harness/*`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/console/harness/runs` | GET | 运行列表 |
| `/api/console/harness/runs/{id}` | GET | 单次运行详情 |
| `/api/console/harness/runs/{id}/events` | GET (SSE) | 实时事件流 |
| `/api/console/harness/runs` | POST | 提交新运行 |
| `/api/console/harness/cancel` | POST | 取消运行 |
| `/api/console/harness/confirm` | POST | 确认令牌验证 |
| `/api/console/harness/stages` | GET | 8 阶段 DAG 定义 |
| `/api/console/harness/profiles` | GET | 可用 profile 列表 |

### Console Meta (`/api/console/meta`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/console/meta` | GET | Console 版本、阶段、标签页、活跃运行数 |

## 前端架构

```
src/api/console/
  endpoints.ts    — 端点常量
  types.ts        — TypeScript 类型定义
  index.ts        — barrel 导出

src/api/hooks/
  console.ts      — 手写 hooks（非 factory.ts）
    useBosCatalog / useBosSchema / useBosHistory / useBosInvoke
    useMofRules / useMofAudit / useMofEvaluate
    useHarnessRuns / useHarnessSubmit / useHarnessEventStream

src/components/console/
  ConsolePage.tsx — 三标签页布局
    BosRepl: Ctrl+Enter 执行，↑/↓ 历史，localStorage 200 条
    MofConsoleTab: audit/evaluate/rules/value 四子标签
    HarnessConsoleTab: composer + run list + SSE + DAG
```

## 关键技术决策

- **SSE 传输**: 使用 `fetch` + `ReadableStream`（非 `EventSource`），因为需要自定义 `X-API-Key` 请求头（Vite proxy）
- **风险分类**: 子域名扫描危险关键词，仅末段匹配 read/write 关键词
- **确认令牌**: SHA256 前 16 位，服务端重算校验
- **Harness 执行**: 子进程 `bin/harness run --json`，stdout 逐行 JSON 解析 → RunEventHub
- **事件存储**: 每运行 500 条 replay buffer，TTL 1 小时 GC
