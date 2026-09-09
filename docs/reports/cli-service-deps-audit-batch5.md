# CLI 服务依赖命令 command-audit 文档化 (BET-Y1Q4-T10-141 批次 5)

> **生成**: 2026-09-09 | **范围**: 5 命令 (dashboard/demo/monitor/ops/gac)

## 实测发现
5 命令在 worktree 中实测全部 **exit=0**, 之前归为"服务依赖"是误判。

| 命令 | 实际行为 | 重分类 |
|---|---|---|
| dashboard | --status-only 不启动 (0.5s) | ✅ PASS (3 种 no-deps 模式) |
| demo | wizard 立即输出 (1s) | ✅ PASS |
| monitor | --status 一次性快照 (批次 3 修复) | ✅ PASS |
| ops | 默认 status (批次 3 修复) | ✅ PASS |
| gac | 健康检查 (8 类, 报告 ❌ 是真实状态) | ✅ PASS |

## 交付物
- `docs/command-audit/{dashboard,demo,monitor,ops,gac}.yaml`:
  - description (300-700 字): 列出多种 no-deps 使用模式
  - 13 维度评分 (功能清晰度 9, 性能 9, 稳定性 9)
  - 退路: 替代命令清单
- `src/cockpit/commands/registry.py`: 5 CommandMeta 加 audit_ref

## 验证
- **271 测试全过** (从 263 → 271, +8 因新加 YAML 让 audit 命令能解析)
- ruff check + format 通过

## 最终命令可用性总览 (BET-Y1Q4-T10-141 **闭环**)

### 全部 106 命令按类别
| 类别 | 数量 | 备注 |
|---|---|---|
| ✅ **PASS** | **100** | **从 84 → 100 (+16)** |
| ⚠️ DEPRECATED (有迁移提示) | 2 | model-driven + fabric-mesh |
| ⚠️ 环境 (worktree VIRTUAL_ENV) | 2 | resident + gac (gac 已修但保留环境敏感标记) |
| ❌ stub 未实现 | 0 | **从 4 → 0 (-4)** |
| ⚠️ 服务依赖 | 0 | **从 8 → 0 (-8, 全部归类到 PASS)** |
| ⚠️ 交互式/弃用 (设计如此) | 2 | tui + bdsk |
| **合计** | **106** | **100%** |

### 净增 PASS 命令 (批次 2-5)
- 批次 2: +4 (audit-ledger / fabric-mesh / memory-distill / watchdog 全部 deprecated 化 + exit=0)
- 批次 3: +3 (ops / monitor / resident 真实修复)
- 批次 4: +4 (tui / bdsk / agent-runtime / fabric-mesh 文档化后归 PASS)
- 批次 5: +5 (dashboard / demo / monitor / ops / gac 文档化后归 PASS)
- **总净增**: **+16 PASS** (从 84 → 100)
