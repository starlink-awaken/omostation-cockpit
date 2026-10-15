"""Compute Governance Summary API endpoints.

提供 AetherForge 算力大盘并网自愈与网络唤醒接口。

Routes:
    GET  /api/governance/compute/status  → 算力网格与网关状态概览
    POST /api/governance/compute/wakeup  → 网络唤醒物理从机节点 (WoL)
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import socket as socket_module
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection
from http.client import HTTPException as HTTPClientException
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from cockpit.web.auth import ApiAuthenticationError, ApiAuthorizationError, authenticate_api_principal

router = APIRouter()


class WakeupRequest(BaseModel):
    node_id: str


def get_workspace_root() -> Path | None:
    """动态定位 workspace 根目录"""
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / "docs" / "project-registry.yaml").is_file():
            return parent
    return None


def get_aetherforge_env(workspace_root: Path) -> dict[str, str]:
    """生成包含 aetherforge 路径的 PYTHONPATH 环境变量"""
    env = os.environ.copy()
    aether_src = workspace_root / "projects" / "aetherforge" / "src"
    gateway_src = workspace_root / "projects" / "aetherforge" / "packages" / "gateway" / "src"
    mesh_src = workspace_root / "projects" / "aetherforge" / "packages" / "mesh" / "src"

    paths = []
    if aether_src.is_dir():
        paths.append(str(aether_src))
    if gateway_src.is_dir():
        paths.append(str(gateway_src))
    if mesh_src.is_dir():
        paths.append(str(mesh_src))

    if paths:
        existing = env.get("PYTHONPATH", "")
        if existing:
            env["PYTHONPATH"] = os.pathsep.join(paths) + os.pathsep + existing
        else:
            env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


@router.get("/api/governance/compute/status")
async def get_compute_status():
    """获取算力网格、LiteLLM 路由与凭据额度并网状态。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=503, detail="Compute workspace is unavailable.")

    onboard_script = root / "bin" / "gac-compute-onboard.py"
    if not onboard_script.is_file():
        raise HTTPException(status_code=503, detail="Compute onboarding capability is not mounted.")

    # 运行 bin/gac-compute-onboard.py --json
    cmd = [sys.executable, str(onboard_script), "--json"]
    env = get_aetherforge_env(root)

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            raise HTTPException(status_code=503, detail=f"Compute onboarding is unavailable: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Compute status check timed out.")
    except HTTPException:
        raise
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Compute onboarding returned invalid JSON: {exc}") from exc
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Compute status is unavailable: {str(e)}") from e


@router.post("/api/governance/compute/wakeup")
async def wakeup_compute_node(req: WakeupRequest):
    """通过 Wake-on-LAN 发送 Magic Packet 唤醒离线从机节点。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")

    # 优先将 node_id 映射到项目注册表 compute_nodes
    # 比如如果是 'ENG-OLLAMA-MACMINI'，底层 wakeup_node 会自动解析包含 'MACMINI' 的硬件并发出 WoL
    # 我们可以直接调用 cockpit compute mesh wakeup <node_id>

    # 构造执行命令: python3 -m aetherforge.cli mesh wakeup <node_id>
    cmd = [sys.executable, "-m", "aetherforge.cli", "mesh", "wakeup", req.node_id]
    env = get_aetherforge_env(root)

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return {
                "success": True,
                "message": f"Wakeup packet successfully sent to node '{req.node_id}'.",
                "stdout": result.stdout.strip(),
            }
        else:
            return {
                "success": False,
                "message": f"Wakeup script failed for node '{req.node_id}'.",
                "stderr": result.stderr.strip(),
                "stdout": result.stdout.strip(),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute wakeup: {str(e)}")


class ComputeGenerateRequest(BaseModel):
    prompt: str
    model: str = "coder"


@router.post("/api/governance/compute/generate")
async def compute_generate(req: ComputeGenerateRequest):
    """经本地算力集群生成文本 — bos://capability/compute/generate → AetherForge → omlx。

    model 为网关模型名 (裸名如 coder / mini-9b 优先本地 omlx; 或 ENG-*/model 全名)。
    """
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")

    # 用 uv run 跑 aetherforge 自己的 venv (依赖齐全), 调 gateway.rpc.run_generate = BOS compute/generate 同一入口
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    code = (
        "import json,sys;"
        "from aetherforge.gateway.rpc import run_generate;"
        "print(json.dumps(run_generate(sys.argv[1], model=sys.argv[2]), ensure_ascii=False))"
    )
    cmd = [
        "uv",
        "run",
        "--directory",
        str(root / "projects" / "aetherforge"),
        "python",
        "-c",
        code,
        req.prompt,
        req.model,
    ]

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip().splitlines()[-1])
        raise HTTPException(
            status_code=500,
            detail=f"Compute generate failed: {result.stderr.strip()[-300:] or 'no output'}",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Compute generate timed out.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compute generate error: {str(e)}")

# The strict operation is a distinct route: old deployed servers return 404 before
# reaching the legacy alias/fallback handler.
_STRICT_MODEL_RE = re.compile(r"^(?:ENG-OMLX-|ENG-LMSTUDIO-|ENG-OLLAMA-)[^/\s]+/[^/\s]+(?:/[^/\s]+)*$")
_STRICT_SLOT = threading.BoundedSemaphore(1)
_STRICT_RATE_LOCK = threading.Lock()
_STRICT_CALLS: dict[str, list[float]] = {}
_STRICT_MAX_TOKENS = 512
_STRICT_MAX_TIMEOUT = 30.0
_STRICT_TRANSPORT_MARGIN = 1.0
_STRICT_SOCKET_MARGIN = 2.0


class StrictComputeGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: Any
    model: Any
    max_tokens: Any
    timeout: Any
    strict_model: Any


def _strict_gateway_url() -> tuple[str, int] | None:
    """Only an explicitly configured numeric loopback HTTP endpoint is accepted."""
    raw = os.environ.get("LLM_GATEWAY_URL", "")
    try:
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/", "/v1", "/v1/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        return parsed.hostname, parsed.port
    except ValueError:
        return None


def _strict_gateway_key(deadline: float) -> str | None:
    """Read the existing server-only Keychain item, never putting its value in argv."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "aetherforge-gateway", "-w"],
            capture_output=True,
            text=True,
            timeout=min(3.0, remaining),
        )
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _strict_rate_allowed(principal_ref: str) -> bool:
    now = time.monotonic()
    with _STRICT_RATE_LOCK:
        recent = [t for t in _STRICT_CALLS.get(principal_ref, ()) if now - t < 60.0]
        if len(recent) >= 6:
            _STRICT_CALLS[principal_ref] = recent
            return False
        recent.append(now)
        _STRICT_CALLS[principal_ref] = recent
        return True


def _strict_provider_request(
    endpoint: tuple[str, int], payload: dict[str, Any], deadline: float,
) -> tuple[int, dict[str, Any]]:
    """One stdlib HTTP attempt. The worker owns the slot until its socket exits."""
    connection: HTTPConnection | None = None
    active_socket: socket_module.socket | None = None
    watchdog: threading.Timer | None = None
    try:
        key = _strict_gateway_key(deadline)
        if not key:
            return 503, {"status": "failed", "error": "gateway_key_unavailable"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 504, {"status": "failed", "error": "deadline_exceeded", "provider_outcome": "unknown"}
        payload["timeout"] = min(payload["timeout"], remaining)
        connection = HTTPConnection(endpoint[0], endpoint[1], timeout=remaining + _STRICT_SOCKET_MARGIN)

        def abort_overdue_socket() -> None:
            sock = active_socket or connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket_module.SHUT_RDWR)
                except OSError:
                    pass

        watchdog = threading.Timer(
            max(0.0, deadline + _STRICT_SOCKET_MARGIN - time.monotonic()), abort_overdue_socket,
        )
        watchdog.daemon = True
        watchdog.start()
        connection.request(
            "POST", "/v1/chat/completions", body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        active_socket = connection.sock
        response = connection.getresponse()
        chunks: list[bytes] = []
        size = 0
        # read1 returns available bytes; resetting the socket timeout per chunk
        # prevents a slow drip from extending this worker indefinitely.
        while True:
            remaining = deadline + _STRICT_SOCKET_MARGIN - time.monotonic()
            if remaining <= 0:
                return 504, {"status": "failed", "error": "deadline_exceeded", "provider_outcome": "unknown"}
            if active_socket is not None:
                active_socket.settimeout(remaining)
            chunk = response.read1(min(8192, 65537 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 65536:
                return 502, {"status": "failed", "error": "gateway_response_too_large"}
            if response.isclosed():
                break
        raw = b"".join(chunks)
        if time.monotonic() > deadline + _STRICT_TRANSPORT_MARGIN:
            return 504, {"status": "failed", "error": "deadline_exceeded", "provider_outcome": "unknown"}
        if response.status != 200:
            return 502, {"status": "failed", "error": f"gateway_http_{response.status}"}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("invalid gateway payload")
        choice = (data.get("choices") or [{}])[0]
        if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
            return 502, {"status": "failed", "error": "gateway_incomplete_response"}
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            return 502, {"status": "failed", "error": "gateway_empty_response"}
        actual_model = data.get("model")
        if actual_model != payload["model"]:
            return 502, {"status": "failed", "error": "gateway_model_mismatch",
                         "requested_model": payload["model"],
                         "reported_model": actual_model if isinstance(actual_model, str) else None}
        trace = data.get("id")
        usage = data.get("usage")
        return 200, {
            "status": "success", "content": content, "requested_model": payload["model"],
            "model": actual_model, "trace_id": trace if isinstance(trace, str) and len(trace) <= 128 else None,
            "usage": usage if isinstance(usage, dict) else None,
        }
    except (OSError, HTTPClientException, ValueError, json.JSONDecodeError):
        return 502, {"status": "failed", "error": "gateway_transport_error",
                     "provider_outcome": "unknown"}
    finally:
        try:
            if watchdog is not None:
                watchdog.cancel()
            if connection is not None:
                connection.close()
        finally:
            _STRICT_SLOT.release()


@router.post("/api/governance/compute/generate-strict")
async def compute_generate_strict(req: StrictComputeGenerateRequest, request: Request):
    """Authenticated, bounded, exact local model operation via AetherForge."""
    try:
        principal = authenticate_api_principal(
            dict(request.headers), any_scope=frozenset({"compute-generate"}),
        )
    except ApiAuthenticationError:
        return JSONResponse({"status": "denied", "error": "operator_auth_required"}, status_code=401)
    except ApiAuthorizationError:
        return JSONResponse({"status": "denied", "error": "compute_scope_required"}, status_code=403)

    if (
        req.strict_model is not True
        or not isinstance(req.prompt, str)
        or not (1 <= len(req.prompt.strip()) <= 4000)
        or not isinstance(req.model, str)
        or _STRICT_MODEL_RE.fullmatch(req.model) is None
        or type(req.max_tokens) is not int
        or not (1 <= req.max_tokens <= _STRICT_MAX_TOKENS)
        or type(req.timeout) not in (int, float)
        or not math.isfinite(req.timeout)
        or not (0 < req.timeout <= _STRICT_MAX_TIMEOUT)
    ):
        return JSONResponse({"status": "failed", "error": "invalid_strict_request"}, status_code=400)
    try:
        if request.headers.get("content-length") and int(request.headers["content-length"]) > 16384:
            return JSONResponse({"status": "failed", "error": "request_too_large"}, status_code=413)
    except ValueError:
        return JSONResponse({"status": "failed", "error": "invalid_content_length"}, status_code=400)

    endpoint = _strict_gateway_url()
    if endpoint is None:
        return JSONResponse({"status": "failed", "error": "strict_gateway_unconfigured"}, status_code=503)
    if not _STRICT_SLOT.acquire(blocking=False):
        return JSONResponse({"status": "busy", "error": "strict_inflight"}, status_code=429)
    if not _strict_rate_allowed(principal.principal_ref):
        _STRICT_SLOT.release()
        return JSONResponse({"status": "busy", "error": "strict_rate_limited"}, status_code=429)

    deadline = time.monotonic() + float(req.timeout)
    payload: dict[str, Any] = {
        "model": req.model, "messages": [{"role": "user", "content": req.prompt}],
        "max_tokens": req.max_tokens, "timeout": float(req.timeout),
        "strict_model": True, "routing_mode": "local", "stream": False,
    }
    loop = asyncio.get_running_loop()
    try:
        worker = loop.run_in_executor(None, _strict_provider_request, endpoint, payload, deadline)
    except RuntimeError:
        _STRICT_SLOT.release()
        return JSONResponse({"status": "failed", "error": "worker_unavailable"}, status_code=503)
    try:
        status, result = await asyncio.wait_for(
            asyncio.shield(worker), timeout=float(req.timeout) + _STRICT_TRANSPORT_MARGIN,
        )
        return JSONResponse(result, status_code=status)
    except TimeoutError:
        # The thread may still be in the socket. It releases the slot on exit.
        return JSONResponse(
            {"status": "failed", "error": "deadline_exceeded", "provider_outcome": "unknown"},
            status_code=504,
        )


# OMLX_ROOT 约定与 aetherforge gateway 相同(见 gateway.py omlx 动态对接注释):
# 默认 ~/omlx(内置盘, launchd TCC 可执行), 不再指向外接卷
OMLX_BIN = os.path.join(
    os.environ.get("OMLX_ROOT", os.path.expanduser("~/omlx")), "bin", "omlx"
)


class ModelActionRequest(BaseModel):
    model: str
    action: str = "load"  # load | unload


def _omlx_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    return env


@router.get("/api/governance/compute/models")
async def list_compute_models():
    """三机本地算力模型清单 —— 来自 SSOT(能力/位置/成本)+ omlx 实时 loaded 态。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")

    # 1) SSOT: 能力 / runs_on / 成本(omlxc ssot-sync 生成)
    ssot_models: list[dict[str, Any]] = []
    ssot_path = root / "projects/ecos/src/ecos/ssot/mof/m1/model" / "MODEL-BREW-OMLX-LOCAL.yaml"
    if ssot_path.is_file():
        try:
            import yaml

            data = yaml.safe_load(ssot_path.read_text(encoding="utf-8")) or {}
            ssot_models = data.get("models", []) or []
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读 SSOT 失败: {e}")

    # 2) omlx: 各节点实时加载态
    loaded: dict[str, list[str]] = {}
    try:
        r = subprocess.run([OMLX_BIN, "node", "ps"], env=_omlx_env(), capture_output=True, text=True, timeout=30)
        cur = None
        for line in (r.stdout or "").splitlines():
            raw = re.sub(r"\x1b\[[0-9;]*m", "", line)
            s = raw.strip()
            if not s:
                continue
            if not raw.startswith(" "):  # 节点行
                cur = s.split("—")[0].strip()
                loaded.setdefault(cur, [])
            elif cur:
                # "● key :port (engine)" 或 "lmstudio :1234 — a, b"
                if "—" in s:
                    tail = s.split("—", 1)[1].strip()
                    if tail and "空闲" not in tail and "down" not in tail:
                        loaded[cur].extend(x.strip() for x in tail.split(","))
                elif s.startswith("●"):
                    parts = s.replace("●", "").strip().split()
                    if parts:
                        loaded[cur].append(parts[0])
    except Exception:
        pass  # 实时态拿不到不影响清单

    return {
        "status": "success",
        "total": len(ssot_models),
        "models": ssot_models,
        "loaded_by_node": loaded,
    }


@router.post("/api/governance/compute/model-action")
async def compute_model_action(req: ModelActionRequest):
    """加载/卸载模型 —— 自动判断本地或远程节点(经 omlxc load/unload)。"""
    if req.action not in ("load", "unload"):
        raise HTTPException(status_code=400, detail="action 必须是 load 或 unload")
    try:
        r = subprocess.run(
            [OMLX_BIN, req.action, req.model], env=_omlx_env(), capture_output=True, text=True, timeout=300
        )
        out = re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + (r.stderr or ""))
        return {
            "status": "success" if r.returncode == 0 else "failed",
            "action": req.action,
            "model": req.model,
            "output": out.strip()[-400:],
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"{req.action} 超时(大模型加载较慢)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{req.action} 失败: {e}")


class FabricTriageRequest(BaseModel):
    prompt: str


class FabricVRAMRequest(BaseModel):
    model_id: str = "coding"
    context_tokens: int = 32768


class FabricWarmRequest(BaseModel):
    model_id: str = "coding"


class FabricCompactRequest(BaseModel):
    model_id: str = "coding"
    tokens: int = 32768
    available_mb: float = 8192.0


@router.get("/api/governance/compute/fabric")
async def get_compute_fabric():
    """获取 omlxc 算力织网实时全景（温控、分诊分级、显存预算与两级缓存）。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")
    omlxc_root = root / "projects" / "omlxc"
    try:
        r = subprocess.run(
            ["uv", "run", "omlxc", "fabric", "inspect", "--json"],
            cwd=str(omlxc_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        raise HTTPException(status_code=500, detail=f"Fabric inspect failed: {r.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fabric error: {e}")


@router.post("/api/governance/compute/fabric/warm")
async def compute_fabric_warm(req: FabricWarmRequest):
    """预热系统 Prompt 前缀缓存以实现 0ms TTFT。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")
    omlxc_root = root / "projects" / "omlxc"
    try:
        r = subprocess.run(
            ["uv", "run", "omlxc", "fabric", "warm", "--model", req.model_id, "--json"],
            cwd=str(omlxc_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        raise HTTPException(status_code=500, detail=f"Fabric warm failed: {r.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fabric warm error: {e}")


@router.post("/api/governance/compute/fabric/triage")
async def compute_fabric_triage(req: FabricTriageRequest):
    """意图复杂度分诊分析。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")
    omlxc_root = root / "projects" / "omlxc"
    try:
        r = subprocess.run(
            ["uv", "run", "omlxc", "fabric", "triage", req.prompt, "--json"],
            cwd=str(omlxc_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        raise HTTPException(status_code=500, detail=f"Fabric triage failed: {r.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fabric triage error: {e}")


@router.post("/api/governance/compute/fabric/vram")
async def compute_fabric_vram(req: FabricVRAMRequest):
    """动态 KV Cache 显存预算评估与准入判定。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")
    omlxc_root = root / "projects" / "omlxc"
    try:
        r = subprocess.run(
            ["uv", "run", "omlxc", "fabric", "vram", req.model_id, str(req.context_tokens), "--json"],
            cwd=str(omlxc_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        raise HTTPException(status_code=500, detail=f"Fabric vram failed: {r.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fabric vram error: {e}")


@router.post("/api/governance/compute/fabric/compact")
async def compute_fabric_compact(req: FabricCompactRequest):
    """评估 KV Cache 显存预算并模拟滑动上下文蒸馏压缩自愈。"""
    root = get_workspace_root()
    if not root:
        raise HTTPException(status_code=500, detail="Cannot locate workspace root.")
    omlxc_root = root / "projects" / "omlxc"
    try:
        r = subprocess.run(
            [
                "uv",
                "run",
                "omlxc",
                "fabric",
                "compact",
                "--model",
                req.model_id,
                "--tokens",
                str(req.tokens),
                "--available-mb",
                str(req.available_mb),
                "--json",
            ],
            cwd=str(omlxc_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return json.loads(r.stdout)
        raise HTTPException(status_code=500, detail=f"Fabric compact failed: {r.stderr}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fabric compact error: {e}")
