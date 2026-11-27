"""Anti-corruption adapter for projects/runtime (L1).

Re-exports the runtime symbols used by cockpit so downstream interface changes
are absorbed here rather than scattered through L3 code.

When the runtime package (or the executor/i0/arch_health modules it needs) is
not importable — e.g. runtime is not installed, or its current tree only ships
the registry subset — every symbol degrades to None so L3 callers keep working.
Callers must guard with `sym if sym else <fallback>` (already done at all
dashboard / API call sites).
"""

import sys
from pathlib import Path

# Dynamically add sibling projects/runtime/src to sys.path if not present
_runtime_src = Path(__file__).resolve().parents[4] / "runtime" / "src"
if _runtime_src.is_dir() and str(_runtime_src) not in sys.path:
    sys.path.insert(0, str(_runtime_src))

try:
    from runtime.arch_health import load_arch_health  # type: ignore[import-not-found]
except ImportError:
    load_arch_health = None  # type: ignore[assignment]

try:
    from runtime.executor.config import (  # type: ignore[import-not-found]
        AUTH_TOKEN,
        DEFAULT_MODEL,
        EXEC_LOG_FILE,
        log,
        setup_logging,
    )
except ImportError:
    AUTH_TOKEN = None  # type: ignore[assignment]
    DEFAULT_MODEL = None  # type: ignore[assignment]
    EXEC_LOG_FILE = None  # type: ignore[assignment]
    log = None  # type: ignore[assignment]

    def setup_logging(*_args, **_kwargs) -> None:  # type: ignore[no-redef]
        """No-op fallback so cockpit entry points survive without runtime."""
        return None

# Safe fallback for removed upstream AGENT_RUNTIME_PORT
try:
    from runtime.executor.config import AGENT_RUNTIME_PORT  # type: ignore[import-not-found]
except (ImportError, AttributeError):
    AGENT_RUNTIME_PORT = 0  # type: ignore[assignment]

try:
    from runtime.executor.engine import (  # type: ignore[import-not-found]
        AgentRuntime,
        _build_alert_message,
        _log_execution,
    )
except ImportError:
    AgentRuntime = None  # type: ignore[assignment]
    _build_alert_message = None  # type: ignore[assignment]
    _log_execution = None  # type: ignore[assignment]

try:
    from runtime.i0 import (  # type: ignore[import-not-found]
        i0_events,
        i0_protocols,
        i0_services,
        i0_status,
    )
except ImportError:
    i0_events = None  # type: ignore[assignment]
    i0_protocols = None  # type: ignore[assignment]
    i0_services = None  # type: ignore[assignment]
    i0_status = None  # type: ignore[assignment]


try:
    from runtime.executor.server import create_app  # type: ignore[import-not-found]
except ImportError:
    create_app = None  # type: ignore[assignment]

try:
    from runtime.executor.sandbox import Sandbox  # type: ignore[import-not-found]
except ImportError:
    Sandbox = None  # type: ignore[assignment]


__all__ = [
    "AGENT_RUNTIME_PORT",
    "AUTH_TOKEN",
    "DEFAULT_MODEL",
    "EXEC_LOG_FILE",
    "AgentRuntime",
    "Sandbox",
    "_build_alert_message",
    "_log_execution",
    "create_app",
    "i0_events",
    "i0_protocols",
    "i0_services",
    "i0_status",
    "load_arch_health",
    "log",
    "setup_logging",
]
