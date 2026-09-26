"""统一推理接入层 (llm-router) — Wave 2 核心交付。

设计原则 (LLM-ENGINE-ARCHITECTURE.md §4)：
1. 所有推理走 aetherforge 门面 HTTP(OpenAI 兼容), 不直连运行时
2. 模型名从门面的 /v1/models 动态发现, 不硬编码
3. 每级失败打印原因，不静默降级
4. SFOP: 不 import aetherforge/omlxc（H↛B）；算力走门面 HTTP

路由顺序: 主门面(本机) → 备用门面(macmini) → None

2026-09-26: 原 Tier1 不带 key(门面 /v1/* 恒 401 → 发现 0 个模型 → 跳过), Tier2 直连本机
Ollama 且兜底模型 north-mini-code-1.0:mlx-nvfp4 并未安装 —— 两层都走不通, research/ask
实际一直返回 none。现两层都经门面并带 Keychain 密钥; 备用层是双站点的 macmini 门面
(与 mbp 同版本, 由 aetherforge-gw-deploy --all 统一推进)。
"""

from __future__ import annotations

import json
import os
import subprocess
from urllib import request as urlrequest

OMLXC_GATEWAY_URL = (
    os.environ.get("LLM_GATEWAY_URL") or os.environ.get("OMLXC_GATEWAY_URL") or "http://127.0.0.1:4000"
).rstrip("/").removesuffix("/v1") + "/v1"
STANDBY_GATEWAY_URL = (
    os.environ.get("LLM_GATEWAY_STANDBY_URL", "http://100.99.210.78:4000").rstrip("/").removesuffix("/v1") + "/v1"
)
DEFAULT_GATEWAY_MODEL = os.environ.get("LLM_ROUTER_GATEWAY_MODEL", "coder-fast")
_KEY: str | None = None


def _gateway_key() -> str:
    """门面密钥: 环境变量优先, 否则 Keychain(aetherforge-gateway)。结果缓存。"""
    global _KEY
    if _KEY is None:
        key = next(
            (os.environ[n] for n in ("LLM_GATEWAY_KEY", "AETHERFORGE_API_KEY", "OMLX_API_KEY") if os.environ.get(n)),
            "",
        )
        if not key:
            try:
                out = subprocess.run(
                    ["security", "find-generic-password", "-s", "aetherforge-gateway", "-w"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                key = out.stdout.strip() if out.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                key = ""
        _KEY = key
    return _KEY


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if key := _gateway_key():
        h["Authorization"] = f"Bearer {key}"
    return h


def discover_gateway_models(base_url: str = OMLXC_GATEWAY_URL) -> list[str]:
    """查询门面可用模型列表(含别名) — OpenAI 兼容 HTTP，不 import B 槽项目。"""
    try:
        req = urlrequest.Request(f"{base_url}/models", headers=_headers())  # noqa: S310
        with urlrequest.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception as exc:
        print(f"[llm-router] 模型发现失败 ({base_url}): {exc}")
        return []


def model_exists(model: str, tier: str = "gateway") -> bool:
    """校验模型在门面注册表中真实存在 (防模型名漂移)。"""
    url = STANDBY_GATEWAY_URL if tier == "standby" else OMLXC_GATEWAY_URL
    return model in discover_gateway_models(url)


def _chat_gateway(
    prompt: str, model: str, temperature: float = 0.7, max_tokens: int = 2048, base_url: str = OMLXC_GATEWAY_URL
) -> str | None:
    """经门面 /v1/chat/completions。失败返回 None 并说明原因。"""
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urlrequest.Request(  # noqa: S310
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers=_headers(),
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read())
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content:
            content = msg.get("reasoning_content") or ""
        if not content:
            # 设计原则 3: 每级失败打印原因 — 门面返回空 content 不应静默
            print(f"[llm-router] 门面空响应: 模型 {model!r} ({base_url}) — 视为失败")
        served = data.get("model")
        if content and served and served != model:
            print(f"[llm-router] 注意: 请求 {model!r} 实际由 {served!r} 承接(门面兜底)")
        return content or None
    except Exception as exc:
        print(f"[llm-router] 门面调用失败 ({base_url}): {exc}")
        return None


def _pick_model(requested: str | None, available: list[str]) -> str:
    """门面自己解析别名, /v1/models 只列真实模型不列别名 —— 这里不拿列表做存在性校验,
    否则 coder-fast 这类别名会被判"不存在"而误选列表首项(实测挑中了 TTS 模型)。
    列表为空说明门面不可达, 由调用方跳过该层。"""
    if not available:
        return ""
    return requested or DEFAULT_GATEWAY_MODEL


def complete(
    prompt: str, model: str | None = None, temperature: float = 0.7, max_tokens: int = 2048
) -> tuple[str | None, str]:
    """统一推理入口。返回 (content, source)：source ∈ {"gateway", "standby", "none"}。"""
    for source, base in (("gateway", OMLXC_GATEWAY_URL), ("standby", STANDBY_GATEWAY_URL)):
        available = discover_gateway_models(base)
        chosen = _pick_model(model, available)
        if not chosen:
            print(f"[llm-router] {source} 跳过: 门面无可用模型 (url={base})")
            continue
        content = _chat_gateway(prompt, chosen, temperature, max_tokens, base_url=base)
        if content:
            return content, source
    return None, "none"


def registry_report() -> str:
    """模型注册表 SSOT 快照: 主门面 + 备用门面可用模型。"""
    lines = ["[llm-router] 模型注册表"]
    for label, base in (("主门面", OMLXC_GATEWAY_URL), ("备用门面", STANDBY_GATEWAY_URL)):
        models = discover_gateway_models(base)
        lines.append(f"  {label} ({base}): {len(models)} 个")
        lines += [f"    - {m}" for m in models[:40]] or ["    (无)"]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if "--list" in sys.argv:
        print(registry_report())
    elif "--test" in sys.argv:
        content, source = complete("1+1=?", max_tokens=50)
        print(f"test complete: source={source!r} content={content!r}")
    else:
        print(__doc__)
