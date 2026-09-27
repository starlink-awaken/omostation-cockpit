"""cockpit rag / see / speak: 本地算力命令(门面调用全部 mock)。"""

from __future__ import annotations

import argparse
import json

import pytest

from cockpit.commands import local_ai


class FakeGateway:
    """按路径返回门面响应, 并记录调用了哪些档。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path, body, *, raw=False):
        self.calls.append((path, body))
        if path == "/embeddings":
            # 向量: 含"切换"的文本与问题同向, 其余正交
            vecs = [[1.0, 0.0] if "切换" in t else [0.0, 1.0] for t in body["input"]]
            return {"data": [{"index": i, "embedding": v} for i, v in enumerate(vecs)]}, "gateway"
        if path == "/rerank":
            docs = body["documents"]
            scores = [0.9 if "macmini" in d else 0.1 for d in docs]
            return {"results": [{"index": i, "relevance_score": s} for i, s in enumerate(scores)]}, "gateway"
        if path == "/chat/completions":
            return {"model": body["model"], "choices": [{"message": {"content": "备用站点是 macmini [1]"}}]}, "gateway"
        if path == "/audio/speech":
            return b"RIFF" + b"\0" * 2000, "gateway"
        raise AssertionError(path)


@pytest.fixture
def gw(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(local_ai, "_post", fake)
    return fake


def test_rag_answer_runs_embed_rerank_answer_with_citations(tmp_path, gw):
    (tmp_path / "a.md").write_text("门面故障切换: 本机挂了切到 macmini 备用站点。")
    (tmp_path / "b.md").write_text("与问题无关的长城历史。")
    res = local_ai.rag_answer("门面怎么故障切换?", [str(tmp_path)], top_k=1)

    assert [c[0] for c in gw.calls] == ["/embeddings", "/rerank", "/chat/completions"]
    assert gw.calls[0][1]["model"] == local_ai.EMBED_MODEL
    assert gw.calls[1][1]["model"] == local_ai.RERANK_MODEL
    assert gw.calls[2][1]["model"] == local_ai.ANSWER_MODEL
    assert res["sources"] == [str(tmp_path / "a.md")]
    assert "[1]" in res["answer"]
    # 作答提示词里必须带上重排选中的资料
    assert "macmini" in gw.calls[2][1]["messages"][1]["content"]


def test_rag_without_docs_is_an_error(tmp_path, gw):
    with pytest.raises(local_ai.GatewayError):
        local_ai.rag_answer("q", [str(tmp_path / "missing")])


def test_see_sends_image_to_vision_or_ocr(tmp_path, gw):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG fake")
    res = local_ai.see(str(img), "合计多少")
    body = gw.calls[-1][1]
    assert body["model"] == local_ai.VISION_MODEL
    parts = body["messages"][0]["content"]
    assert parts[0]["text"] == "合计多少" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert res["answer"]

    local_ai.see(str(img), ocr=True)
    assert gw.calls[-1][1]["model"] == "ocr"


def test_speak_picks_voice_by_language(tmp_path, gw):
    out = tmp_path / "s.wav"
    res = local_ai.speak("下周三开会", str(out))
    assert gw.calls[-1][1]["model"] == "tts-zh" and gw.calls[-1][1]["voice"] == "vivian"
    assert out.stat().st_size == res["bytes"] > 1000
    local_ai.speak("hello there", str(out))
    assert gw.calls[-1][1]["model"] == "tts-en"


def test_cli_parser_registers_local_ai_commands():
    from cockpit._subcommands import register_subcommands

    parser = argparse.ArgumentParser()
    register_subcommands(parser.add_subparsers(dest="command"), argparse.ArgumentParser)
    a = parser.parse_args(["rag", "ask", "问题", "--docs", "d1", "d2", "--top-k", "3", "--json"])
    assert a.rag_command == "ask" and a.docs == ["d1", "d2"] and a.top_k == 3 and a.json
    a = parser.parse_args(["see", "img.png", "合计", "--ocr"])
    assert a.image == "img.png" and a.question == ["合计"] and a.ocr
    a = parser.parse_args(["speak", "你好", "--play"])
    assert a.text == ["你好"] and a.play
    a = parser.parse_args(["brain", "ask", "--cloud", "问题"])
    assert a.cloud and a.question == ["问题"]


def test_cmd_rag_json_output(tmp_path, gw, capsys):
    (tmp_path / "a.md").write_text("门面故障切换到 macmini。")
    args = argparse.Namespace(
        rag_command="ask", question=["切换?"], docs=[str(tmp_path)], kos=False, top_k=2, json=True
    )
    assert local_ai.cmd_rag(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stages"]["embed"]["model"] == local_ai.EMBED_MODEL and out["answer"]
