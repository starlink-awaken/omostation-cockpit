"""统一推理接入层 (llm-router) — Wave 2 核心交付。

设计原则 (LLM-ENGINE-ARCHITECTURE.md §4)：
1. 所有本地推理走网关 HTTP (omlxc)，直连 ollama 仅作最后兜底
2. 模型名从注册表动态发现，不硬编码
3. 每级失败打印原因，不静默降级
4. SFOP: 不 import aetherforge/omlxc（H↛B）；算力走网关 HTTP

路由顺序: omlxc 网关 (OpenAI 兼容 HTTP) → ollama 本地 (模型存在性校验) → None
"""

from __future__ import annotations

import json
import os
from urllib import request as urlrequest

OMLXC_GATEWAY_URL = os.environ.get("OMLXC_GATEWAY_URL", "http://127.0.0.1:9290/v1")
OLLAMA_API = os.environ.get("OLLAMA_API", "http://localhost:11434")
DEFAULT_GATEWAY_MODEL = os.environ.get("LLM_ROUTER_GATEWAY_MODEL", "coder-fast")
# ollama 降级兜底: north-mini-code-1.0:mlx-nvfp4 实测正常 (gemma4:31b-mlx 返回空响应, 已弃用)
DEFAULT_OLLAMA_FALLBACK = os.environ.get("LLM_ROUTER_OLLAMA_FALLBACK", "north-mini-code-1.0:mlx-nvfp4")


def discover_gateway_models() -> list[str]:
    """查询可用模型列表 — omlxc OpenAI 兼容 HTTP，不 import B 槽项目。"""
    try:
        req = urlrequest.Request(f"{OMLXC_GATEWAY_URL}/models")  # noqa: S310
        with urlrequest.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def discover_ollama_models() -> list[str]:
    """查询 ollama /api/tags 获取本机已拉取模型列表。"""
    try:
        req = urlrequest.Request(f"{OLLAMA_API}/api/tags")  # noqa: S310
        with urlrequest.urlopen(req, timeout=5) as resp:  # noqa: S310
            data = json.loads(resp.read())
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def model_exists(model: str, tier: str = "ollama") -> bool:
    """校验模型在指定 tier 的注册表中真实存在 (防模型名漂移)。"""
    if tier == "gateway":
        return model in discover_gateway_models()
    return model in discover_ollama_models()


def _chat_gateway(prompt: str, model: str, temperature: float = 0.7, max_tokens: int = 2048) -> str | None:
    """Tier 1: omlxc OpenAI-compatible HTTP gateway。失败返回 None 并说明原因。"""
    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urlrequest.Request(  # noqa: S310
            f"{OMLXC_GATEWAY_URL}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read())
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content:
            content = msg.get("reasoning_content") or ""
        if not content:
            # 设计原则 3: 每级失败打印原因 — 网关返回空 content 不应静默
            print(f"[llm-router] Tier1 网关空响应: 模型 {model!r} — 视为失败")
        return content or None
    except Exception as exc:
        print(f"[llm-router] Tier1 HTTP 网关失败: {exc}")
        return None


def _chat_ollama(prompt: str, model: str, temperature: float = 0.3, num_predict: int = 500) -> str | None:
    """Tier 2: ollama 本地 (仅当模型存在性校验通过)。失败返回 None 并说明原因。"""
    if not model_exists(model, "ollama"):
        print(f"[llm-router] Tier2 ollama 跳过: 模型 {model!r} 不在本机 (可用: {discover_ollama_models()})")
        return None
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "raw": False,
            "options": {"num_predict": num_predict, "temperature": temperature},
        }
        req = urlrequest.Request(  # noqa: S310
            f"{OLLAMA_API}/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=120) as resp:  # noqa: S310
            data = json.loads(resp.read())
        content = data.get("response", "")
        if not content:
            # thinking 模型 (如 qwen3.5) 可能把 num_predict 配额全部消耗在思考上, response 为空。
            # 用 /api/chat + think:false 重试一次, 关闭思考模式直出答案。
            print(f"[llm-router] Tier2 ollama 空响应: 模型 {model!r} (done={data.get('done')}) — 尝试 chat+think:false 重试")
            try:
                chat_payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": num_predict, "temperature": temperature},
                }
                chat_req = urlrequest.Request(  # noqa: S310
                    f"{OLLAMA_API}/api/chat",
                    data=json.dumps(chat_payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlrequest.urlopen(chat_req, timeout=120) as chat_resp:  # noqa: S310
                    chat_data = json.loads(chat_resp.read())
                content = (chat_data.get("message") or {}).get("content") or ""
            except Exception as retry_exc:
                print(f"[llm-router] Tier2 ollama chat 重试失败: {retry_exc}")
        return content
    except Exception as exc:
        print(f"[llm-router] Tier2 ollama 失败: {exc}")
        return None


def complete(
    prompt: str, model: str | None = None, temperature: float = 0.7, max_tokens: int = 2048
) -> tuple[str | None, str]:
    """统一推理入口。返回 (content, source)：source ∈ {"gateway", "ollama", "none"}。"""
    gw_models = discover_gateway_models()
    gw_model = (
        model
        if model and model in gw_models
        else (DEFAULT_GATEWAY_MODEL if DEFAULT_GATEWAY_MODEL in gw_models else (gw_models[0] if gw_models else ""))
    )
    if gw_model:
        content = _chat_gateway(prompt, gw_model, temperature, max_tokens)
        if content:
            return content, "gateway"
    else:
        print(f"[llm-router] Tier1 跳过: omlxc 网关无可用模型 (url={OMLXC_GATEWAY_URL})")

    ollama_models = discover_ollama_models()
    ollama_model = next(
        (m for m in (model, DEFAULT_OLLAMA_FALLBACK) if m and m in ollama_models),
        ollama_models[0] if ollama_models else "",
    )
    if ollama_model:
        content = _chat_ollama(prompt, ollama_model, temperature, max_tokens)
        if content:
            return content, "ollama"
    else:
        print("[llm-router] Tier2 跳过: ollama 无已拉取模型")

    return None, "none"


def registry_report() -> str:
    """模型注册表 SSOT 快照: 网关 + ollama 可用模型。"""
    gw = discover_gateway_models()
    ol = discover_ollama_models()
    lines = ["[llm-router] 模型注册表", f"  omlxc 网关 ({OMLXC_GATEWAY_URL}):"]
    lines += [f"    - {m}" for m in gw] or ["    (无)"]
    lines += [f"  ollama 本地 ({OLLAMA_API}):"]
    lines += [f"    - {m}" for m in ol] or ["    (无)"]
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
