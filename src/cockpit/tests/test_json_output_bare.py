"""--json 输出必须是合法 JSON: rich console.print 会按终端宽度折行, 把长字符串拆出裸换行(2026-09-27 场景实测)。"""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from cockpit.commands import research


def test_research_list_json_survives_long_values(monkeypatch, capsys):
    topic = "本地大模型网关的高可用设计: 主备切换与自愈" * 6  # 远超 80 列
    fake = SimpleNamespace(list_research=lambda limit, include_archived: [{"id": 1, "topic": topic}])
    monkeypatch.setattr(research, "_get_data_access", lambda: fake)
    args = argparse.Namespace(limit=1, status="active", json=True)
    research.cmd_research_list(args)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["topic"] == topic
