# CLI 交互式/弃用命令可用性矩阵 (BET-Y1Q4-T10-141 批次 4)

> **生成**: 2026-09-09 | **范围**: 5 个命令 (4 交互式 + 1 弃用)

## 实际跑结果 (worktree 实测)

| 命令 | exit | 实际行为 | 真实分类 |
|---|---|---|---|
| tui | 0 | 启动 Textual TUI, 无 TTY 时降级 rich 静态版 | ✅ PASS (交互式) |
| bdsk | 0 | BOSRouter admission + bdsk evaluate 输出 | ✅ PASS (即时结果) |
| model-driven | 0 | 拒绝执行 + 提示 cockpit + 需 MODEL_DRIVEN_CLI_LEGACY | ⚠️ DEPRECATED (ADR-0240 D1) |
| agent-runtime | 0 | 需 --prompt/--task/--server 参数 | ✅ PASS (需参数) |
| fabric-mesh | 0 | 软提示 + 指向 omlxc skill | ⚠️ DEPRECATED (ADR-0202, 批次 2 修复) |

## 关键洞察
- **之前的"交互式/弃用"分类不准确**: 所有 5 个 exit=0, 不再制造红色
- 真正需要标记的只有 2 个: model-driven (弃用) 和 fabric-mesh (弃用)
- tui/bdsk/agent-runtime 实际是 PASS (设计如此)

## 交付物
1. 5 份 `docs/command-audit/{cmd}.yaml` 完整化 (description + 13 维度评分)
2. `registry.py` 中 5 个 CommandMeta 加 `audit_ref` 指向文档
3. `model-driven` 在 registry 标 `maturity=deprecated`

## 验证
- 263 测试全过 ✅
- ruff check + format 通过 ✅
- 5 份 YAML 字段完整 (description + 13 dimensions) ✅

## 当前命令可用性总览 (批次 4 后)
| 类别 | 数量 | 变化 |
|---|---|---|
| ✅ PASS | **95** | +4 (tui/bdsk/agent-runtime/fabric-mesh PASS) |
| ⚠️ 服务依赖 | 5 | 不变 |
| ⚠️ 弃用 (有 deprecation 提示) | 2 | +1 (model-driven 显式标 deprecated) |
| ⚠️ 环境 | 2 | 不变 |
| ❌ stub | 0 | 不变 |
| **合计** | **106** | **100%** |
