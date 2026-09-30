import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from rich.console import Console

console = Console()


def sha256_dir(directory: Path) -> str:
    hasher = hashlib.sha256()
    for root, _, files in os.walk(directory):
        for name in sorted(files):
            p = Path(root) / name
            if p.is_file() and name != "manifest.json":
                hasher.update(name.encode("utf-8"))
                hasher.update(p.read_bytes())
    return hasher.hexdigest()


def pack_cartridge(source_dir: str, output: str) -> int:
    source = Path(source_dir)
    out = Path(output)

    if not source.is_dir():
        console.print(f"[red]❌ 源码目录不存在: {source_dir}[/]")
        return 1

    console.print(f"[bold blue]📦 正在打包领域卡带: {source}[/]")

    sig = sha256_dir(source)
    console.print(f"🔒 生成密码学签名: [green]{sig}[/]")

    # 签名清单只写进产物: 此前直接覆盖源目录的 manifest.json, 卡带 ID/策略规则/意图模式全被抹掉
    # (全链路场景实测打包 domains/weijian-governance 时发现)。保留原清单字段, 叠加签名。
    src_manifest = source / "manifest.json"
    try:
        manifest = json.loads(src_manifest.read_text(encoding="utf-8")) if src_manifest.is_file() else {}
    except ValueError:
        manifest = {}
    manifest.setdefault("domain", source.name)
    manifest.setdefault("version", "1.0")
    manifest.update(signature=sig, packed_from=str(source_dir))

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source):
            for file in files:
                filepath = Path(root) / file
                arcname = filepath.relative_to(source)
                if str(arcname) == "manifest.json":
                    continue
                zf.write(filepath, arcname)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    console.print(f"[bold green]✅ 卡带已生成: {out} (大小: {out.stat().st_size} bytes)[/]")
    return 0


def _extract_args_llm(intent: str, fields: list[str]) -> dict:
    """本机模型从意图文本抽取规则参数(budget_cny/mlps_grade/...); 失败返回空。"""
    from cockpit.commands.brain import llm_complete

    import json as _json
    import re as _re

    if not fields:
        return {}
    out = llm_complete(
        "从下面这句工作意图中抽取结构化参数, 只输出 JSON。规则:\n"
        "- 数字去掉单位, 「万元」换算成元(1200万元→12000000)\n"
        "- 布尔/枚举字段: 只在意图**明确声明该事实已具备**时才填值; 意图只是在描述要做的事"
        "(如「立项论证」「需满足等保三级」是目标不是现状)或未提及时, 一律设 null\n"
        f"字段: {', '.join(fields)}\n意图: {intent}",
    )
    if not out:
        return {}
    m = _re.search(r"\{.*\}", out, _re.DOTALL)
    if not m:
        return {}
    try:
        d = _json.loads(m.group())
        return {k: v for k, v in d.items() if v is not None}
    except ValueError:
        return {}


def _evaluate_policies(sandbox: Path, manifest: dict, intent: str) -> int:
    """评估卡带 rules/*.yaml 的 constraint: LLM 抽参 → 受限求值 → 按严重度阻断。"""
    import sys as _sys

    import yaml

    _sys.path.insert(0, str(sandbox / "rules"))  # 卡带内若有脚本可扩展; 现仅读规则
    from cockpit.commands.cartridge_policy import evaluate_constraint

    results, blocked = [], []
    for rf in sorted((sandbox / "rules").glob("*.yaml")):
        try:
            doc = yaml.safe_load(rf.read_text(encoding="utf-8"))
        except Exception as exc:
            results.append({"rule": rf.name, "error": str(exc)[:60]})
            continue
        policies = (doc or {}).get("policies", []) if isinstance(doc, dict) else []
        fields = sorted({
            part.strip().replace("action.args.", "")
            for p in policies
            for part in str(p.get("constraint", "")).replace("(", " ").replace(")", " ").split()
            if part.startswith("action.args.")
        })
        args = _extract_args_llm(intent, fields) if policies else {}
        action = {"uri": f"cartridge://{manifest.get('domain', 'run')}", "args": args}
        for p in policies:
            ok = evaluate_constraint(str(p.get("constraint", "")), action)
            rec = {"rule": p.get("id"), "name": p.get("name"), "severity": p.get("severity"), "pass": ok,
                   "message": "" if ok else p.get("message", "")}
            results.append(rec)
            if not ok and str(p.get("severity", "")).upper() in ("CRITICAL", "HIGH", "BLOCK"):
                blocked.append(rec)
    console.print(f"[bold]📋 策略评估: {len(results)} 条规则, 参数抽取自意图(缺失字段视为 null, 保守阻断)[/]")
    for r in results:
        mark = "✅" if r.get("pass") else ("⛔" if r in blocked else "⚠️")
        console.print(f"  {mark} {r.get('severity', '?'):8s} {r.get('rule', '?')}: {r.get('name', '')}")
        if r in blocked:
            console.print(f"     [red]{r.get('message', '')}[/]")
    if blocked:
        console.print(f"[red]⛔ {len(blocked)} 条 HIGH/CRITICAL 规则未通过, 已阻断(需人工论证/整改后重试)[/]")
        return 3
    console.print("[green]✅ 规则全部通过(或无规则)[/]")
    return 0


def run_cartridge(cartridge_file: str, intent: str, workspace_root: Path) -> int:
    cart = Path(cartridge_file)
    if not cart.is_file():
        console.print(f"[red]❌ 卡带文件不存在: {cartridge_file}[/]")
        return 1

    console.print(f"[bold blue]🚀 挂载领域卡带: {cart}[/]")
    console.print(f"🎯 意图: [yellow]{intent}[/]")

    with tempfile.TemporaryDirectory(prefix="cartridge_sandbox_") as tmpdir:
        sandbox = Path(tmpdir)
        console.print(f"📂 创建零信任沙箱: {sandbox}")

        with zipfile.ZipFile(cart, "r") as zf:
            zf.extractall(sandbox)

        manifest_path = sandbox / "manifest.json"
        if not manifest_path.exists():
            console.print("[red]❌ 卡带损坏: 缺失 manifest.json[/]")
            return 1

        manifest = json.loads(manifest_path.read_text())
        expected_sig = manifest.get("signature")

        actual_sig = sha256_dir(sandbox)

        if actual_sig != expected_sig:
            console.print(f"[red]❌ 签名校验失败！存在篡改风险。\n期望: {expected_sig}\n实际: {actual_sig}[/]")
            return 1

        console.print("[green]✅ 密码学完整性校验通过[/]")

        entrypoint = sandbox / "scripts" / "run.py"
        if entrypoint.exists():
            console.print(f"[bold magenta]⚡ 执行卡带入口 scripts/run.py: {intent}[/]")
            res = subprocess.run(["python3", str(entrypoint), "--intent", intent], cwd=str(sandbox))
            return res.returncode
        # 无入口脚本 → 做卡带规则评估(此前只打印完整性校验; 2026-09-29 实测发现空转)
        return _evaluate_policies(sandbox, manifest, intent)
