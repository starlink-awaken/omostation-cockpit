"""Automated conformance and smoke test suite for Cockpit command ecosystem (PSC v1)."""

from __future__ import annotations

import pytest

from cockpit.cli import main
from cockpit.commands.registry import (
    CATEGORY_GROUPS,
    COMMAND_CATALOG,
    LEGACY_COMMAND_MAPPING,
    ORTHOGONAL_DOMAINS,
)
from cockpit.domain.exit_codes import ExitCode


def test_command_catalog_metadata_integrity():
    """Verify that every registered command in COMMAND_CATALOG has valid metadata."""
    assert len(COMMAND_CATALOG) > 100, f"Expected >100 commands, got {len(COMMAND_CATALOG)}"

    for name, meta in COMMAND_CATALOG.items():
        assert meta.name == name, f"Mismatch in CommandMeta.name: {meta.name} vs key {name}"
        assert meta.summary and len(meta.summary.strip()) > 0, f"Command {name} missing summary"
        assert meta.category in CATEGORY_GROUPS, f"Command {name} has unregistered category: {meta.category}"
        assert meta.maturity in {"stable", "beta", "experimental", "deprecated"}
        assert meta.risk in {"low", "medium", "high"}


def test_orthogonal_domains_integrity():
    """Verify the 8 orthogonal domain definitions and legacy mappings."""
    assert len(ORTHOGONAL_DOMAINS) == 8
    expected_domains = {
        "governance",
        "workflow",
        "memory",
        "compute",
        "bus",
        "scene",
        "system",
        "user",
    }
    assert set(ORTHOGONAL_DOMAINS.keys()) == expected_domains

    # Check legacy mapping targets
    for legacy_cmd, (domain, canonical_sub) in LEGACY_COMMAND_MAPPING.items():
        assert domain in expected_domains, f"Legacy command {legacy_cmd} maps to unknown domain {domain}"
        assert canonical_sub, f"Legacy command {legacy_cmd} missing canonical subcommand target"


def _run_help(args: list[str]) -> int:
    try:
        return main(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0


@pytest.mark.parametrize("domain", [
    "governance",
    "workflow",
    "memory",
    "compute",
    "bus",
    "scene",
    "system",
    "user",
])
def test_domain_help_smoke(domain: str, capsys):
    """Smoke test ensuring every orthogonal domain responds cleanly."""
    rc = _run_help([domain, "--help"])
    assert rc == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 20


@pytest.mark.parametrize("cmd", [
    "quickstart",
    "dashboard",
    "journey",
    "capabilities",
    "docs",
    "telemetry",
    "completion",
    "workflow",
    "compass",
    "brain",
])
def test_modernized_commands_help_smoke(cmd: str, capsys):
    """Smoke test ensuring all modernized P0 commands respond cleanly to --help."""
    rc = _run_help([cmd, "--help"])
    assert rc == 0
    captured = capsys.readouterr()
    assert len(captured.out) > 20



def test_every_command_module_imports():
    """全量 import cockpit.commands 下每个模块。

    防御回归: 未被任何测试引用的模块一旦有语法错误/缺失符号, 现有测试套件
    不会发现 (batch 13 曾在 importer.py 引入该类错误并合入 main)。
    """
    import importlib
    import pkgutil

    import cockpit.commands as pkg

    failures: list[str] = []
    count = 0
    for mod in pkgutil.iter_modules(pkg.__path__):
        name = f"{pkg.__name__}.{mod.name}"
        try:
            importlib.import_module(name)
            count += 1
        except Exception as exc:
            failures.append(f"{mod.name}: {type(exc).__name__}: {exc}")

    assert count > 80, f"只 import 到 {count} 个模块, 疑似发现机制失效"
    assert not failures, "以下命令模块 import 失败:\n" + "\n".join(failures)
