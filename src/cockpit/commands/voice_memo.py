"""cockpit.commands.voice_memo — 语音便签命令面 (BET-Y2Q1-T2-01).

调用 agora BOS 服务 ``bos://voice/memo/ingest``（可插拔 ASR + 规则润色），
展示润色稿与分拣结果；``--to-spine`` 将随笔/任务追加进 Spine 备选池
（``.omo/state/spine-draft-pool.jsonl``，原子追加）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

SPINE_POOL_REL = ".omo/state/spine-draft-pool.jsonl"


def _ws() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "docs" / "project-registry.yaml").is_file():
            return parent
    return Path.cwd()


def _agora_python(code: str, timeout: float = 180.0) -> tuple[int, str]:
    agora_root = _ws() / "projects" / "agora"
    if not (agora_root / "pyproject.toml").is_file():
        return 127, "agora checkout not found"
    res = subprocess.run(
        ["uv", "run", "python", "-c", code],
        cwd=str(agora_root), capture_output=True, text=True, timeout=timeout, check=False,
    )
    return res.returncode, (res.stdout or res.stderr).strip()


def cmd_voice_memo(args: argparse.Namespace) -> int:
    """音频 → 转录 → 润色分拣 → (可选) Spine 备选池入库。"""
    audio = getattr(args, "audio", "") or ""
    engine = getattr(args, "engine", "") or None
    if not audio or not Path(audio).is_file():
        console.print("[red]缺少或不存在 --audio <file>[/red]")
        return 1

    snippet = (
        "import json\n"
        "from agora.server.tools_bos.voice import ingest_memo\n"
        f"print(json.dumps(ingest_memo({audio!r}, engine={engine!r}), ensure_ascii=False))\n"
    )
    rc, out = _agora_python(snippet)
    if rc != 0:
        console.print(f"[red]BOS voice 服务调用失败: {out[:300]}[/red]")
        return 1
    try:
        payload = json.loads(out.splitlines()[-1])
    except Exception:
        console.print(f"[red]输出解析失败: {out[:300]}[/red]")
        return 1

    if not payload.get("ok"):
        console.print(Panel(
            f"[yellow]{payload.get('error_code')}[/yellow]\n{payload.get('detail', '')}\n"
            f"[dim]{payload.get('install_hint', '')}[/dim]",
            title="🎙 语音便签 — 诚实失败",
        ))
        return 1

    if getattr(args, "to_spine", False):
        pool = _ws() / ".omo" / "state" / "spine-draft-pool.jsonl"
        pool.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "kind": payload.get("kind"),
            "polished": payload.get("polished", "")[:2000],
            "task_items": payload.get("task_items", []),
            "source": "voice-memo",
        }
        tmp = pool.with_suffix(".tmp")
        with tmp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(pool)

    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    console.print(Panel(payload.get("polished", "")[:1500], title="🎙 润色稿"))
    if payload.get("task_items"):
        t = Table(title="分拣 · 任务项", header_style="bold cyan")
        t.add_column("任务", ratio=1)
        t.add_column("责任人", style="cyan")
        t.add_column("时限", style="yellow")
        for task in payload["task_items"]:
            t.add_row(task["task"], task["owner"], task["deadline"])
        console.print(t)
    meta = f"引擎: {payload.get('engine')} | 耗时: {payload.get('elapsed_s')}s (预算 {payload.get('budget_s')}s)"
    if getattr(args, "to_spine", False):
        meta += " | 已入库 Spine 备选池"
    console.print(f"[dim]{meta}[/dim]")
    return 0
