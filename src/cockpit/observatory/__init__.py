"""Cockpit Observatory package (BET-Y1Q4-T8-24A).

Unified data plane for architecture, capabilities, and strategic ledger observations.
"""
from __future__ import annotations

from cockpit.observatory.catalog_sources import collect_catalog
from cockpit.observatory.query_engine import ObservationIndex, QueryError
from cockpit.observatory.service import ObservatoryService, get_observatory_service
from cockpit.observatory.strategy_sources import collect_strategy_sources

__all__ = [
    "collect_catalog",
    "collect_strategy_sources",
    "ObservationIndex",
    "QueryError",
    "ObservatoryService",
    "get_observatory_service",
]
