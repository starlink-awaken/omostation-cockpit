# workspace-cli — 研究对象管理系统
# CLI entry in cli.py. Run: python -m cockpit

__version__ = "0.4.0"

# Lazy import: env_resolver 加载 16ms (含 urllib.request), 改为 attribute proxy
# 这样 `from cockpit import env_resolver` 仍能工作, 但 import cockpit 不触发
def __getattr__(name):
    if name == "env_resolver":
        import importlib
        return importlib.import_module("cockpit.env_resolver")
    raise AttributeError(f"module 'cockpit' has no attribute {name!r}")

__all__ = ("__version__", "env_resolver")
