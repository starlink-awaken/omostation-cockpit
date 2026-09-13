"""Unit tests for cockpit-observatory FastMCP server and compact LLM projections."""

from __future__ import annotations

import asyncio
import json
import unittest

from cockpit.observatory.mcp_server import (
    check_path_collisions,
    check_workspace_collisions,
    get_callchain_contract,
    get_project_perception,
    get_recent_events,
    get_submodule_sentinel,
    get_system_overview,
    mcp,
    probe_live_status,
)
from cockpit.observatory.topology_engine import TopologyEngine


class TestObservatoryMCP(unittest.TestCase):
    def test_get_project_perception_compact(self):
        """Verify get_project_perception produces clean, compact JSON (< 800 tokens)."""
        raw = get_project_perception("omo")
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["project_id"], "omo")
        self.assertEqual(data["layer"], "L2")
        self.assertIn("upstream_dependencies", data)
        self.assertIn("downstream_consumers", data)
        self.assertIn("collision_status", data)
        self.assertIn("runtime_interfaces", data)

        # Token efficiency check: must be compact (< 2500 chars, ~600 tokens)
        self.assertLess(len(raw), 2500, f"Context too large for LLM: {len(raw)} chars")

    def test_get_project_perception_fuzzy_and_unknown(self):
        """Test fuzzy matching and safe fallback for unknown projects."""
        raw_fuzzy = get_project_perception("cockpit")
        data_fuzzy = json.loads(raw_fuzzy)
        self.assertTrue(data_fuzzy["ok"])
        self.assertEqual(data_fuzzy["project_id"], "cockpit")

        raw_unknown = get_project_perception("non_existent_proj_xyz")
        data_unknown = json.loads(raw_unknown)
        self.assertFalse(data_unknown["ok"])
        self.assertIn("available_projects", data_unknown)

    def test_check_workspace_collisions(self):
        """Verify check_workspace_collisions returns live worktrees & collision metrics."""
        raw = check_workspace_collisions()
        data = json.loads(raw)
        self.assertIn("collisions_count", data)
        self.assertIn("total_active_worktrees", data)
        self.assertGreaterEqual(data["total_active_worktrees"], 1)
        self.assertIn("collisions", data)
        self.assertIn("layer_heatmap", data)

    def test_get_submodule_sentinel(self):
        """Verify sentinel status for 16 submodules and registered host ports."""
        raw = get_submodule_sentinel()
        data = json.loads(raw)
        self.assertIn("submodules_summary", data)
        self.assertEqual(data["submodules_summary"]["total"], 16)
        self.assertIn("ports_summary", data)
        self.assertGreater(data["ports_summary"]["listening"], 0)

    def test_get_callchain_contract(self):
        """Verify callchain retrieval (single chain by id and all chains)."""
        # All chains
        raw_all = get_callchain_contract()
        all_chains = json.loads(raw_all)
        self.assertEqual(len(all_chains), 4)

        # Single chain
        raw_single = get_callchain_contract("chain_agora_bos")
        chain = json.loads(raw_single)
        self.assertEqual(chain["id"], "chain_agora_bos")
        self.assertEqual(len(chain["steps"]), 9)
        self.assertEqual(chain["steps"][0]["actor"], "MCP Client")

    def test_get_system_overview(self):
        """Verify 8-layer overview schema and assets."""
        raw = get_system_overview()
        data = json.loads(raw)
        self.assertIn("ecos_version", data)
        self.assertIn("layers", data)
        self.assertEqual(len(data["layers"]), 8)
        self.assertGreaterEqual(data["total_projects"], 18)

    def test_check_path_collisions(self):
        """Verify check_path_collisions tool returns valid decision JSON."""
        raw = check_path_collisions(["projects/cockpit/src", "projects/agora/etc"])
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertIn("safe", data)
        self.assertIn("max_severity", data)
        self.assertIn("summary", data)
        self.assertIn("affected_projects", data)

    def test_get_recent_events(self):
        """Verify get_recent_events returns structured envelope."""
        raw = get_recent_events(limit=5)
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertIn("count", data)
        self.assertIn("events", data)

    def test_probe_live_status(self):
        """Verify probe_live_status returns compact heartbeat metrics (< 500 tokens)."""
        raw = probe_live_status()
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertIn("active_worktrees", data)
        self.assertIn("collisions_count", data)
        self.assertIn("submodules_state", data)
        self.assertIn("ports_listening", data)
        self.assertIn("recent_critical_events", data)
        self.assertLess(len(raw), 1500)

    def test_mcp_server_tools_registered(self):
        """Verify all 8 tools are properly registered on FastMCP instance."""
        tools = [t.name for t in asyncio.run(mcp.list_tools())]
        self.assertIn("get_project_perception", tools)
        self.assertIn("check_workspace_collisions", tools)
        self.assertIn("check_path_collisions", tools)
        self.assertIn("get_submodule_sentinel", tools)
        self.assertIn("get_callchain_contract", tools)
        self.assertIn("get_system_overview", tools)
        self.assertIn("get_recent_events", tools)
        self.assertIn("probe_live_status", tools)
        self.assertEqual(len(tools), 8)


if __name__ == "__main__":
    unittest.main()


