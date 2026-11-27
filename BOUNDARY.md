---
type: ssot
last_updated: 2026-11-27
last-reviewed: 2026-11-27
owner: governance-team
lifecycle: entry
status: active
---

# cockpit — System Boundary

> 本文档描述 cockpit 与 eCOS 系统其他部分的边界：暴露的接口、依赖的上游、影响的下游。
>
> 系统全景参见：[`../../docs/PANORAMA.md`](../../docs/PANORAMA.md)

---

## 1. 暴露接口

### BOS URI

- `bos://cockpit/context`

> BOS 登记面是 `projects/agora/etc/bos-services.yaml`（投影见 `docs/generated/capability-registry.yaml`）；
> 本节只列已登记的 URI，不列推测值。

### 入口

- **CLI**: `cockpit / workspace` 25+ 子命令
- **MCP stdio**: `cockpit-mcp`（入口模块 `cockpit.agent_runtime_mcp_server:main`，见 `pyproject.toml`）
- **HTTP**: `cockpit-dashboard` :8090

## 2. 上游依赖

- agora (I0)
- l4-kernel (L4)

## 3. 下游影响

- kairon
- omo
- runtime

## 4. 配置 / SSOT

- 项目源码：`projects/cockpit/`
- 入口定义：`projects/cockpit/pyproject.toml` 或 `package.json`
- 测试：`cd projects/cockpit && uv run pytest tests/ -q`

## 架构演进与项目边界索引

参见工作区架构演进与项目边界：[`../../docs/ARCHITECTURE-EVOLUTION.md`](../../docs/ARCHITECTURE-EVOLUTION.md)
