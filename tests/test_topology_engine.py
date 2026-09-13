"""Tests for TopologyEngine and cockpit topology CLI in projects/cockpit."""

from __future__ import annotations

import unittest
from pathlib import Path

from cockpit.observatory.topology_engine import TopologyEngine


class TestTopologyEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = TopologyEngine()

    def test_overview(self):
        ov = self.engine.get_overview()
        self.assertIn("ecos_version", ov)
        self.assertIn("layers", ov)
        self.assertEqual(len(ov["layers"]), 8)
        self.assertGreaterEqual(ov["total_projects"], 15)
        self.assertGreaterEqual(ov["total_mcp_tools"], 400)
        self.assertGreaterEqual(ov["total_bos_services"], 300)

    def test_graph(self):
        graph = self.engine.get_graph()
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        self.assertGreaterEqual(len(graph["nodes"]), 15)
        self.assertGreaterEqual(len(graph["edges"]), 20)

    def test_projects(self):
        projs = self.engine.get_projects()
        self.assertGreaterEqual(len(projs), 15)
        cockpit = next((p for p in projs if p["id"] == "cockpit"), None)
        self.assertIsNotNone(cockpit)
        self.assertEqual(cockpit["layer"], "L3")

    def test_interfaces(self):
        ifaces = self.engine.get_interfaces()
        self.assertIn("summary", ifaces)
        summary = ifaces["summary"]
        self.assertGreater(summary["cli_count"], 10)
        self.assertGreater(summary["mcp_count"], 5)
        self.assertGreater(summary["port_count"], 3)
        self.assertGreater(summary["bos_count"], 50)
        
        # Query filter
        q_ifaces = self.engine.get_interfaces(query="search")
        self.assertGreater(len(q_ifaces["cli"]) + len(q_ifaces["bos"]), 0)

    def test_sentinel(self):
        sentinel = self.engine.get_sentinel_status()
        self.assertIn("submodules", sentinel)
        self.assertIn("submodules_summary", sentinel)
        self.assertIn("ports", sentinel)
        self.assertIn("ports_summary", sentinel)
        self.assertEqual(sentinel["submodules_summary"]["total"], 16)
        self.assertIn(sentinel["submodules_summary"]["overall_state"], ["ALL_ALIGNED", "DRIFT_DETECTED"])
        self.assertGreater(sentinel["ports_summary"]["listening"], 0)

    def test_callchains(self):
        chains = self.engine.get_callchains()
        self.assertEqual(len(chains), 4)
        chain_ids = {c["id"] for c in chains}
        self.assertIn("chain_agora_bos", chain_ids)
        self.assertIn("chain_aetherforge_infer", chain_ids)
        self.assertIn("chain_kos_memory", chain_ids)
        self.assertIn("chain_omo_gac", chain_ids)

    def test_workspace_agents(self):
        ag = self.engine.get_workspace_agents()
        self.assertIn("total_worktrees", ag)
        self.assertIn("collisions_count", ag)
        self.assertIn("collisions", ag)
        self.assertIn("layer_heatmap", ag)
        self.assertIn("project_heatmap", ag)
        self.assertGreaterEqual(ag["total_worktrees"], 1)
        self.assertGreaterEqual(ag["total_claims"], 0)

    def test_check_path_collisions(self):
        # 1. Empty paths
        empty_res = self.engine.check_path_collisions([])
        self.assertTrue(empty_res["ok"])
        self.assertTrue(empty_res["safe"])
        self.assertEqual(empty_res["max_severity"], "CLEAN")

        # 2. Specific project paths
        res = self.engine.check_path_collisions([
            "projects/cockpit/src/cockpit/commands/topology.py",
            "projects/agora/etc/bos-services.yaml",
            "bin/gac/gac-worktree.sh"
        ])
        self.assertTrue(res["ok"])
        self.assertIn("cockpit", res["affected_projects"])
        self.assertIn("agora", res["affected_projects"])
        self.assertIn("governance", res["affected_projects"])
        self.assertIn("summary", res)
        self.assertIn("recommendation", res)
        self.assertIn(res["max_severity"], ["CLEAN", "LOW", "MEDIUM", "HIGH", "CRITICAL"])


if __name__ == "__main__":
    unittest.main()
