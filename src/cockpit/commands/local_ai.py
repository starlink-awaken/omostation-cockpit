"""Cockpit 本地算力命令 — 全部经 aetherforge 门面(llm_router 同一地址/密钥/主备)。

  cockpit rag ask "问题" --docs DIR|FILE...   本地文档问答: 切块 → 向量召回(embed-bge) → 重排(rerank) → 带引用作答
  cockpit see IMAGE ["问题"] [--ocr]         看图理解(vision) / 文字识别(ocr)
  cockpit speak "文本" [--out f.wav] [--play] 语音合成(tts-zh / tts-en)

此前 cockpit CLI 里只有 chat 走本地算力: 向量/重排/视觉/语音一个都用不到(2026-09-27 盘点)。
每个命令在输出末尾打印"本次用到的门面档", 便于核对真的走了本地算力而不是被兜底。
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from cockpit.llm_router import OMLXC_GATEWAY_URL, STANDBY_GATEWAY_URL, _headers

EMBED_MODEL = os.environ.get("COCKPIT_EMBED_MODEL", "embed-bge")
RERANK_MODEL = os.environ.get("COCKPIT_RERANK_MODEL", "rerank")
ANSWER_MODEL = os.environ.get("COCKPIT_RAG_MODEL", "reasoning")
VISION_MODEL = os.environ.get("COCKPIT_VISION_MODEL", "vision")
TIMEOUT = float(os.environ.get("COCKPIT_LOCAL_AI_TIMEOUT", "600"))  # 冷加载 + 长上下文可超 1 分钟


class GatewayError(RuntimeError):
    pass


def _post(path: str, body: dict, *, raw: bool = False) -> tuple[object, str]:
    """POST 到门面; 主站不可达时试备用站。返回 (响应, 实际站点)。"""
    last: Exception | None = None
    for site, base in (("gateway", OMLXC_GATEWAY_URL), ("standby", STANDBY_GATEWAY_URL)):
        req = urlrequest.Request(f"{base}{path}", json.dumps(body).encode(), _headers(), method="POST")  # noqa: S310
        try:
            with urlrequest.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310
                data = resp.read()
            return (data if raw else json.loads(data)), site
        except urlerror.HTTPError as e:
            # 4xx 是请求本身的问题, 换站点也一样 —— 直接报
            if e.code < 500:
                raise GatewayError(f"门面 HTTP {e.code}: {e.read()[:200]!r}") from e
            last = e
        except (urlerror.URLError, OSError, TimeoutError) as e:
            last = e
        print(f"[local-ai] {site} 失败: {last}, 尝试下一站点", file=sys.stderr)
    raise GatewayError(f"主备门面均不可用: {last}")


def _chat(model: str, messages: list, max_tokens: int = 1500, temperature: float = 0.3) -> tuple[str, str]:
    d, _site = _post(
        "/chat/completions",
        {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
    )
    assert isinstance(d, dict)
    content = (d["choices"][0]["message"].get("content") or "").strip()
    return content, str(d.get("model") or model)


# ── rag ask ──────────────────────────────────────────────────────


def _load_docs(paths: list[str]) -> list[tuple[str, str]]:
    docs = []
    for p in paths:
        path = Path(p).expanduser()
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for f in files:
            if f.is_file() and f.suffix.lower() in {".md", ".txt", ".rst", ".py", ".yaml", ".yml"}:
                try:
                    docs.append((str(f), f.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    return docs


def _chunk(text: str, size: int = 600, overlap: int = 100) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i : i + size])
        i += size - overlap
    return out


def _cos(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _embed(texts: list[str], batch: int = 32) -> list[list[float]]:
    vecs: list[list[float]] = []
    for i in range(0, len(texts), batch):
        d, _ = _post("/embeddings", {"model": EMBED_MODEL, "input": texts[i : i + batch]})
        assert isinstance(d, dict)
        vecs += [row["embedding"] for row in sorted(d["data"], key=lambda r: r.get("index", 0))]
    return vecs


def rag_answer(question: str, doc_paths: list[str], top_k: int = 5, recall: int = 20, use_kos: bool = False) -> dict:
    t0 = time.time()
    docs = _load_docs(doc_paths)
    chunks = [(src, c) for src, text in docs for c in _chunk(text)]
    if use_kos:
        from cockpit.commands.brain import kos_search_sync

        for r in kos_search_sync(question, limit=8).get("results", []):
            chunks.append(
                (r.get("canonical_path") or r.get("doc_id", "kos"), f"{r.get('title', '')}\n{r.get('snippet', '')}")
            )
    if not chunks:
        raise GatewayError("没有可检索的内容(检查 --docs 路径)")
    stages: dict[str, object] = {"docs": len(docs), "chunks": len(chunks)}

    # 1) 向量召回
    t = time.time()
    vecs = _embed([question] + [c for _, c in chunks])
    qv, cv = vecs[0], vecs[1:]
    scored = sorted(range(len(chunks)), key=lambda i: -_cos(qv, cv[i]))[:recall]
    stages["embed"] = {"model": EMBED_MODEL, "dim": len(qv), "recall": len(scored), "secs": round(time.time() - t, 1)}

    # 2) 交叉编码重排
    t = time.time()
    d, _ = _post("/rerank", {"model": RERANK_MODEL, "query": question, "documents": [chunks[i][1] for i in scored]})
    assert isinstance(d, dict)
    ranked = sorted(d.get("results") or [], key=lambda r: -r.get("relevance_score", r.get("score", 0)))[:top_k]
    picked = [scored[r["index"]] for r in ranked]
    stages["rerank"] = {
        "model": RERANK_MODEL,
        "top_k": len(picked),
        "secs": round(time.time() - t, 1),
        "top_score": round(ranked[0].get("relevance_score", 0), 3) if ranked else None,
    }

    # 3) 带引用作答
    t = time.time()
    context = "\n\n".join(f"[{n}] 来源: {chunks[i][0]}\n{chunks[i][1]}" for n, i in enumerate(picked, 1))
    answer, served = _chat(
        ANSWER_MODEL,
        [
            {
                "role": "system",
                "content": "只依据给定资料回答, 用中文; 关键结论后用 [编号] 标注出处; 资料不足时明确说明。",
            },
            {"role": "user", "content": f"资料:\n{context}\n\n问题: {question}"},
        ],
        max_tokens=1500,
    )
    stages["answer"] = {"model": ANSWER_MODEL, "served": served, "secs": round(time.time() - t, 1)}
    return {
        "question": question,
        "answer": answer,
        "sources": [chunks[i][0] for i in picked],
        "stages": stages,
        "secs": round(time.time() - t0, 1),
    }


def cmd_rag(args: argparse.Namespace) -> int:
    if getattr(args, "rag_command", None) != "ask":
        print('用法: cockpit rag ask "问题" --docs DIR|FILE... [--top-k 5] [--kos] [--json]')
        return 2
    question = " ".join(args.question or []).strip()
    if not question or not (args.docs or args.kos):
        print("❌ 需要问题, 以及 --docs 路径或 --kos")
        return 2
    try:
        res = rag_answer(question, args.docs or [], top_k=args.top_k, use_kos=args.kos)
    except GatewayError as e:
        print(f"❌ {e}")
        return 1
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    print(res["answer"])
    print("\n来源:")
    for n, s in enumerate(res["sources"], 1):
        print(f"  [{n}] {s}")
    st = res["stages"]
    print(
        f"\n本次用到的门面档: {st['embed']['model']}(召回 {st['embed']['recall']}/{st['chunks']} 块) → "
        f"{st['rerank']['model']}(取 {st['rerank']['top_k']}) → {st['answer']['served']} · {res['secs']}s"
    )
    return 0


# ── see ──────────────────────────────────────────────────────────


def see(image: str, question: str | None = None, ocr: bool = False, model: str | None = None) -> dict:
    img = Path(image).expanduser()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        img.suffix.lower(), "image/png"
    )
    b64 = base64.b64encode(img.read_bytes()).decode()
    use = model or ("ocr" if ocr else VISION_MODEL)
    prompt = question or (
        "识别图中全部文字, 保留表格结构原样输出。" if ocr else "描述这张图片; 若有文字/表格/数字, 提取要点。用中文。"
    )
    t0 = time.time()
    content, served = _chat(
        use,
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        max_tokens=2000,
        temperature=0.1,
    )
    return {"model": use, "served": served, "answer": content, "secs": round(time.time() - t0, 1)}


def cmd_see(args: argparse.Namespace) -> int:
    if not Path(args.image).expanduser().is_file():
        print(f"❌ 图片不存在: {args.image}")
        return 2
    try:
        res = see(args.image, " ".join(args.question or []) or None, ocr=args.ocr, model=args.model)
    except GatewayError as e:
        print(f"❌ {e}")
        return 1
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(res["answer"])
        print(f"\n本次用到的门面档: {res['served']} · {res['secs']}s")
    return 0


# ── speak ────────────────────────────────────────────────────────


def speak(text: str, out: str | None = None, voice: str | None = None, model: str | None = None) -> dict:
    zh = bool(re.search(r"[一-鿿]", text))
    use = model or ("tts-zh" if zh else "tts-en")
    t0 = time.time()
    audio, _site = _post(
        "/audio/speech", {"model": use, "input": text, "voice": voice or ("vivian" if zh else "af_heart")}, raw=True
    )
    assert isinstance(audio, bytes)
    path = Path(out).expanduser() if out else Path(tempfile.mkdtemp()) / "speech.wav"
    path.write_bytes(audio)
    return {"model": use, "path": str(path), "bytes": len(audio), "secs": round(time.time() - t0, 1)}


def cmd_speak(args: argparse.Namespace) -> int:
    text = " ".join(args.text or []).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    if not text:
        print('用法: cockpit speak "文本" [--out f.wav] [--play]')
        return 2
    try:
        res = speak(text, args.out, args.voice, args.model)
    except GatewayError as e:
        print(f"❌ {e}")
        return 1
    if args.play:
        subprocess.run(["afplay", res["path"]], check=False)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(f"🔊 {res['path']} ({res['bytes'] // 1024}KB) · 门面档 {res['model']} · {res['secs']}s")
    return 0
