#!/usr/bin/env python3
"""cockpit cli — compatibility re-exports (tests monkeypatch via cli.xxx).

Moved from cli.py to control god module line count.
"""

from __future__ import annotations

__all__ = [
    "cmd_agora",
    "cmd_audit",
    "cmd_bos_backends",
    "cmd_bos_capability",
    "cmd_bos_discover",
    "cmd_bos_health",
    "cmd_bos_list",
    "cmd_bos_mutate",
    "cmd_bos_read",
    "cmd_bos_register",
    "cmd_bos_reload",
    "cmd_bos_resolve",
    "cmd_bos_status",
    "cmd_bos_workflow",
    "cmd_brain",
    "cmd_bus",
    "cmd_capabilities",
    "cmd_contracts_export_event",
    "cmd_contracts_export_identity",
    "cmd_contracts_export_research",
    "cmd_contracts_list",
    "cmd_contracts_validate",
    "cmd_daily",
    "cmd_dashboard",
    "cmd_data_gc",
    "cmd_data_index",
    "cmd_data_types",
    "cmd_demo",
    "cmd_family_hub",
    "cmd_gac",
    "cmd_gbrain",
    "cmd_governance",
    "cmd_help",
    "cmd_import",
    "cmd_kairon",
    "cmd_mcp",
    "cmd_mesh",
    "cmd_model_driven",
    "cmd_mof",
    "cmd_observe",
    "cmd_profile",
    "cmd_research",
    "cmd_research_agent",
    "cmd_research_archive",
    "cmd_research_ask",
    "cmd_research_audit",
    "cmd_research_backup",
    "cmd_research_backup_restore",
    "cmd_research_compare",
    "cmd_research_digest",
    "cmd_research_dossier",
    "cmd_research_export",
    "cmd_research_follow_up",
    "cmd_research_health",
    "cmd_research_heatmap",
    "cmd_research_list",
    "cmd_research_merge",
    "cmd_research_open",
    "cmd_research_publish",
    "cmd_research_quarantine",
    "cmd_research_rename",
    "cmd_research_restore",
    "cmd_research_search",
    "cmd_research_tag",
    "cmd_research_timeline",
    "cmd_research_unarchive",
    "cmd_research",
    "cmd_spine",
    "cmd_ssb",
    "cmd_status",
]

def cmd_agora(*args, **kwargs):  # T8-15 lazy
    from .commands.agora import cmd_agora as _f

    return _f(*args, **kwargs)


def cmd_audit(*args, **kwargs):  # T8-15 lazy
    from .commands.audit import cmd_audit as _f

    return _f(*args, **kwargs)


# ── T8-15: lazy base symbols (commands.base pulls rich.markdown/urllib chain) ──
def _script_dir():
    from .commands.base import _SCRIPT_DIR

    return _SCRIPT_DIR


def _find_cli(name):
    from .commands.base import _find_cli as _f

    return _f(name)


def cmd_bos_backends(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_backends as _f

    return _f(*args, **kwargs)


def cmd_bos_capability(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_capability as _f

    return _f(*args, **kwargs)


def cmd_bos_discover(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_discover as _f

    return _f(*args, **kwargs)


def cmd_bos_health(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_health as _f

    return _f(*args, **kwargs)


def cmd_bos_list(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_list as _f

    return _f(*args, **kwargs)


def cmd_bos_mutate(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_mutate as _f

    return _f(*args, **kwargs)


def cmd_bos_read(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_read as _f

    return _f(*args, **kwargs)


def cmd_bos_register(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_register as _f

    return _f(*args, **kwargs)


def cmd_bos_reload(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_reload as _f

    return _f(*args, **kwargs)


def cmd_bos_resolve(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_resolve as _f

    return _f(*args, **kwargs)


def cmd_bos_status(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_status as _f

    return _f(*args, **kwargs)


def cmd_bos_workflow(*args, **kwargs):  # T8-15 lazy
    from .commands.bos import cmd_bos_workflow as _f

    return _f(*args, **kwargs)


def cmd_brain(*args, **kwargs):  # T8-15 lazy
    from .commands.brain import cmd_brain as _f

    return _f(*args, **kwargs)


def _cmd_brief(*args, **kwargs):  # T8-15 lazy
    from .commands.brief import _cmd_brief as _f

    return _f(*args, **kwargs)


def _cmd_brief_morning(*args, **kwargs):  # T8-15 lazy
    from .commands.brief import _cmd_brief_morning as _f

    return _f(*args, **kwargs)


def cmd_bus(*args, **kwargs):  # T8-15 lazy
    from .commands.bus import cmd_bus as _f

    return _f(*args, **kwargs)


def cmd_capabilities(*args, **kwargs):  # T8-15 lazy
    from .commands.capabilities import cmd_capabilities as _f

    return _f(*args, **kwargs)


def cmd_contracts_export_event(*args, **kwargs):  # T8-15 lazy
    from .commands.contracts import cmd_contracts_export_event as _f

    return _f(*args, **kwargs)


def cmd_contracts_export_identity(*args, **kwargs):  # T8-15 lazy
    from .commands.contracts import cmd_contracts_export_identity as _f

    return _f(*args, **kwargs)


def cmd_contracts_export_research(*args, **kwargs):  # T8-15 lazy
    from .commands.contracts import cmd_contracts_export_research as _f

    return _f(*args, **kwargs)


def cmd_contracts_list(*args, **kwargs):  # T8-15 lazy
    from .commands.contracts import cmd_contracts_list as _f

    return _f(*args, **kwargs)


def cmd_contracts_validate(*args, **kwargs):  # T8-15 lazy
    from .commands.contracts import cmd_contracts_validate as _f

    return _f(*args, **kwargs)


def cmd_data_gc(*args, **kwargs):  # T8-15 lazy
    from .commands.data import cmd_data_gc as _f

    return _f(*args, **kwargs)


def cmd_data_index(*args, **kwargs):  # T8-15 lazy
    from .commands.data import cmd_data_index as _f

    return _f(*args, **kwargs)


def cmd_data_types(*args, **kwargs):  # T8-15 lazy
    from .commands.data import cmd_data_types as _f

    return _f(*args, **kwargs)


def _cmd_discover(*args, **kwargs):  # T8-15 lazy
    from .commands.discover import _cmd_discover as _f

    return _f(*args, **kwargs)


def cmd_family_hub(*args, **kwargs):  # T8-15 lazy
    from .commands.family_hub import cmd_family_hub as _f

    return _f(*args, **kwargs)


def cmd_gbrain(*args, **kwargs):  # T8-15 lazy
    from .commands.gbrain import cmd_gbrain as _f

    return _f(*args, **kwargs)


def cmd_governance(*args, **kwargs):  # T8-15 lazy
    from .commands.governance import cmd_governance as _f

    return _f(*args, **kwargs)


def _cmd_health(*args, **kwargs):  # T8-15 lazy
    from .commands.health import _cmd_health as _f

    return _f(*args, **kwargs)


def cmd_import(*args, **kwargs):  # T8-15 lazy
    from .commands.importer import cmd_import as _f

    return _f(*args, **kwargs)


def cmd_kairon(*args, **kwargs):  # T8-15 lazy
    from .commands.kairon import cmd_kairon as _f

    return _f(*args, **kwargs)


def cmd_mcp(*args, **kwargs):  # T8-15 lazy
    from .commands.mcp import cmd_mcp as _f

    return _f(*args, **kwargs)


def cmd_mesh(*args, **kwargs):  # T8-15 lazy
    from .commands.mesh import cmd_mesh as _f

    return _f(*args, **kwargs)


def cmd_model_driven(*args, **kwargs):  # T8-15 lazy
    from .commands.model_driven import cmd_model_driven as _f

    return _f(*args, **kwargs)


def cmd_observe(*args, **kwargs):  # T8-15 lazy
    from .commands.observe import cmd_observe as _f

    return _f(*args, **kwargs)


def cmd_profile(*args, **kwargs):  # T8-15 lazy
    from .commands.profile import cmd_profile as _f

    return _f(*args, **kwargs)


def _cmd_research_batch(*args, **kwargs):  # T8-15 lazy
    from .commands.research import _cmd_research_batch as _f

    return _f(*args, **kwargs)


def _notify_research_complete(*args, **kwargs):  # T8-15 lazy
    from .commands.research import _notify_research_complete as _f

    return _f(*args, **kwargs)


def _research_progress(*args, **kwargs):  # T8-15 lazy
    from .commands.research import _research_progress as _f

    return _f(*args, **kwargs)


def cmd_research(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research as _f

    return _f(*args, **kwargs)


def cmd_research_agent(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_agent as _f

    return _f(*args, **kwargs)


def cmd_research_archive(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_archive as _f

    return _f(*args, **kwargs)


def cmd_research_ask(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_ask as _f

    return _f(*args, **kwargs)


def cmd_research_audit(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_audit as _f

    return _f(*args, **kwargs)


def cmd_research_backup(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_backup as _f

    return _f(*args, **kwargs)


def cmd_research_backup_restore(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_backup_restore as _f

    return _f(*args, **kwargs)


def cmd_research_compare(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_compare as _f

    return _f(*args, **kwargs)


def cmd_research_digest(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_digest as _f

    return _f(*args, **kwargs)


def cmd_research_dossier(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_dossier as _f

    return _f(*args, **kwargs)


def cmd_research_export(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_export as _f

    return _f(*args, **kwargs)


def cmd_research_follow_up(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_follow_up as _f

    return _f(*args, **kwargs)


def cmd_research_health(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_health as _f

    return _f(*args, **kwargs)


def cmd_research_heatmap(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_heatmap as _f

    return _f(*args, **kwargs)


def cmd_research_list(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_list as _f

    return _f(*args, **kwargs)


def cmd_research_merge(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_merge as _f

    return _f(*args, **kwargs)


def cmd_research_open(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_open as _f

    return _f(*args, **kwargs)


def cmd_research_publish(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_publish as _f

    return _f(*args, **kwargs)


def cmd_research_quarantine(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_quarantine as _f

    return _f(*args, **kwargs)


def cmd_research_rename(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_rename as _f

    return _f(*args, **kwargs)


def cmd_research_restore(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_restore as _f

    return _f(*args, **kwargs)


def cmd_research_search(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_search as _f

    return _f(*args, **kwargs)


def cmd_research_tag(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_tag as _f

    return _f(*args, **kwargs)


def cmd_research_timeline(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_timeline as _f

    return _f(*args, **kwargs)


def cmd_research_unarchive(*args, **kwargs):  # T8-15 lazy
    from .commands.research import cmd_research_unarchive as _f

    return _f(*args, **kwargs)


def _cmd_search(*args, **kwargs):  # T8-15 lazy
    from .commands.search import _cmd_search as _f

    return _f(*args, **kwargs)


def cmd_spine(*args, **kwargs):  # T8-15 lazy
    from .commands.spine import cmd_spine as _f

    return _f(*args, **kwargs)


def _render_workbench(*args, **kwargs):  # T8-15 lazy
    from .commands.status import _render_workbench as _f

    return _f(*args, **kwargs)


def cmd_daily(*args, **kwargs):  # T8-15 lazy
    from .commands.status import cmd_daily as _f

    return _f(*args, **kwargs)


def cmd_dashboard(*args, **kwargs):  # T8-15 lazy
    from .commands.status import cmd_dashboard as _f

    return _f(*args, **kwargs)


def cmd_demo(*args, **kwargs):  # T8-15 lazy
    from .commands.status import cmd_demo as _f

    return _f(*args, **kwargs)


def cmd_help(*args, **kwargs):  # T8-15 lazy
    from .commands.status import cmd_help as _f

    return _f(*args, **kwargs)


def cmd_status(*args, **kwargs):  # T8-15 lazy
    from .commands.status import cmd_status as _f

    return _f(*args, **kwargs)


def cmd_ssb(a):
    from cockpit.commands.ssb import cmd_ssb as _c

    return _c(a)


def cmd_mof(a):
    from cockpit.commands.mof import cmd_mof as _c

    return _c(a)


def cmd_gac(a):
    """GaC 治理健康检查 (ADR-0106, 调 bin/gac-healthcheck.py). cockpit GaC 集成入口 (第4项).

    跨 worktree/主仓兼容: 用 env_resolver 找 workspace root (含 projects/ + AGENTS.md),
    不再用 parents[4] (worktree 子模块层级下不准)。
    """
    import subprocess
    from cockpit.env_resolver import get_workspace_root

    workspace = get_workspace_root()
    r = subprocess.run(
        ["python3", str(workspace / "bin" / "gac" / "gac-healthcheck.py")],
        capture_output=True,
        text=True,
        cwd=str(workspace),
    )
    print(r.stdout or r.stderr or "(无输出)")
    return 0 if r.returncode == 0 else 1


def _c_context(a):
    from cockpit.commands.l4bridge import cmd_context as _c

    return _c(a)


def _c_cards(a):
    from cockpit.commands.l4bridge import cmd_cards as _c

    return _c(a)


def _c_vault(a):
    from cockpit.commands.l4bridge import cmd_vault as _c

    return _c(a)


def _c_domains(a):
    from cockpit.commands.l4bridge import cmd_domains as _c

    return _c(a)


def _c_domain_status(a):
    from cockpit.commands.l4bridge import cmd_domain_status as _c

    return _c(a)


def _c_facts_audit(a):
    from cockpit.commands.l4bridge import cmd_facts_audit as _c

    return _c(a)


def _c_facts_validation(a):
    from cockpit.commands.l4bridge import cmd_facts_validation as _c

    return _c(a)


def _c_model_freshness(a):
    from cockpit.commands.l4bridge import cmd_model_freshness as _c

    return _c(a)


def _c_sanyi_status(a):
    from cockpit.commands.l4bridge import cmd_sanyi_status as _c

    return _c(a)


def _c_controller_shadow(a):
    from cockpit.commands.l4bridge import cmd_controller_shadow as _c

    return _c(a)


def _c_skill(a):
    from cockpit.commands.l4bridge import cmd_skill as _c

    return _c(a)


def _c_events(a):
    from cockpit.commands.events import run_events_dashboard

    url = getattr(a, "url", "http://127.0.0.1:7431/v1/events")
    run_events_dashboard(url)
    return 0


def _c_version(a):
    from cockpit import __version__

    console.print(f"[bold cyan]cockpit[/] v[bold]{__version__}[/]")
    console.print("[dim]L3 统一入口 · 5+4+1+1 架构[/]")
    return 0

