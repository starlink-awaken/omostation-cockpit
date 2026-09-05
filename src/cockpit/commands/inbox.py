"""cockpit.commands.inbox — 邮箱 3 档拟复命令面 (BET-Y1Q3-T10-113).

调用 agora BOS 服务 ``bos://inbox/mail/draft``（经 agora.server.tools_bos.mail
实现），展示简要确认 / 详尽批复 / 委婉谢绝三档草稿与附件表格还原。
确定性模板实现，文风精调由 LoRA 适配层在推理侧叠加。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _ws() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "docs" / "project-registry.yaml").is_file():
            return parent
    return Path.cwd()


def _agora_python(code: str, timeout: float = 120.0) -> tuple[int, str]:
    """Run a snippet inside the agora project env; snippet prints one JSON line."""
    agora_root = _ws() / "projects" / "agora"
    if not (agora_root / "pyproject.toml").is_file():
        return 127, "agora checkout not found"
    res = subprocess.run(
        ["uv", "run", "python", "-c", code],
        cwd=str(agora_root), capture_output=True, text=True, timeout=timeout, check=False,
    )
    return res.returncode, (res.stdout or res.stderr).strip()


def _read_input(args: argparse.Namespace, body_attr: str = "body") -> str:
    inline = getattr(args, body_attr, "") or ""
    file_attr = getattr(args, f"{body_attr}_file", None)
    if file_attr and Path(file_attr).is_file():
        inline = Path(file_attr).read_text(encoding="utf-8")
    return inline


def cmd_inbox_draft(args: argparse.Namespace) -> int:
    """Draft 3-tier reply for an inbound mail via BOS mail service."""
    body = _read_input(args)
    if not body:
        console.print("[red]缺少 --body / --body-file[/red]")
        return 1
    subject = getattr(args, "subject", "") or None
    att_text = getattr(args, "attachment", "") or ""
    att_fmt = getattr(args, "attachment_fmt", "csv")

    snippet = (
        "import json\n"
        "from agora.server.tools_bos.mail import bos_mail_draft\n"
        f"att_text = {att_text!r}\n"
        "atts = [{'fmt': " + repr(att_fmt) + ", 'text': att_text, 'name': 'attachment'}] if att_text else []\n"
        f"print(json.dumps(bos_mail_draft(body={body!r}, subject={subject!r}, attachments=atts), ensure_ascii=False))\n"
    )
    rc, out = _agora_python(snippet)
    if rc != 0:
        console.print(f"[red]BOS 服务调用失败: {out[:300]}[/red]")
        return 1
    try:
        payload = json.loads(out.splitlines()[-1])
    except Exception:
        console.print(f"[red]输出解析失败: {out[:300]}[/red]")
        return 1

    is_json = getattr(args, "json", False)
    if is_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    t = Table(title=f"📧 3 档拟复 · {payload.get('subject', '')}", header_style="bold cyan")
    t.add_column("档位", style="bold", width=14)
    t.add_column("草稿", ratio=1)
    names = {"brief_confirm": "简要确认", "verbose_reply": "详尽批复", "polite_decline": "委婉谢绝"}
    for tier, text in payload.get("tiers", {}).items():
        t.add_row(names.get(tier, tier), text)
    console.print(t)

    for att in payload.get("attachments", []):
        if att.get("ok"):
            console.print(Panel(att["markdown"][:2000], title=f"📎 {att['name']} (Markdown 还原 {att.get('fidelity', 0):.0%})"))
    console.print(
        f"[dim]延迟 {payload.get('latency_ms', 0)}ms (预算 {payload.get('ttft_budget_ms', 0)}ms) | "
        "审阅与外发: cockpit spine review / spine send[/dim]"
    )
    return 0
