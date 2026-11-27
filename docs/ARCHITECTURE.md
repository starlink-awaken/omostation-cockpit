---
type: ssot
last_updated: 2026-11-27
last-reviewed: 2026-11-27
owner: governance-team
lifecycle: entry
status: active
---

# Cockpit Architecture

> Architecture overview for **Cockpit**. For the full workspace architecture, see [`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md).

## Responsibilities

Cockpit is part of the eCOS v6 workspace. See [`../README.md`](../README.md) for a one-line description and [`../CAPABILITY-MAP.md`](../CAPABILITY-MAP.md) for capability mapping.

## Key Surfaces

- `src/cockpit/cli.py` — CLI entry
- `src/cockpit/commands/` — command modules
- `src/cockpit/dashboard_server.py` — web dashboard
- `src/cockpit/agent_runtime_mcp_server.py` — MCP bridge（`cockpit-mcp` 入口）

## Design Notes

- Runtime facts (counts, ports, health) are intentionally not maintained here. Use the workspace registries and project source as the truth.
- For boundaries and call chains, read [`../BOUNDARY.md`](../BOUNDARY.md) and [`../CALLCHAIN.md`](../CALLCHAIN.md).
- For developer rules, read [`../AGENTS.md`](../AGENTS.md).

## Component Overview

```mermaid
graph TD
    User([User / Agent])
    N0[CLI]
    N1[Commands]
    N2[Dashboard]
    Core[MCP Bridge]
    N0 --> N1
    N1 --> N2
    N2 --> Core
    User --> Core
```

- Arrows show typical interaction flow, not strict call direction.
- See [`../CALLCHAIN.md`](../CALLCHAIN.md) for detailed call chains.
