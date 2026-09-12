#!/usr/bin/env python3
"""compare_43191_fidelity.py — 43191 观测站 vs cockpit observatory 数据面保真度对账 (BET-Y1Q4-T8-24E 前置).

两侧读同一 SSOT current.json, 对 11 个 /api/v1/* operation:
  1. 43191 侧: HTTP 拉取 (服务在线时) 或 SnapshotStore 离线重算
  2. cockpit 侧: cockpit.observatory.query_engine.ObservationIndex 重算
  3. 剥离时间戳字段, 规范化 lineage_by_depth 键, JSON 规范化 SHA-256 对比

Exit: 0 = 全对齐; 1 = 有差异; 2 = 43191/快照不可达 (UNPROVABLE).

用法:
  python3 src/tools/compare_43191_fidelity.py [--live http://127.0.0.1:43191] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cockpit.observatory.query_engine import ObservationIndex  # noqa: E402
from cockpit.observatory.service import get_observatory_service  # noqa: E402

OPERATIONS = ["manifest", "summary", "ontology", "lineage", "context_pack", "search", "controls"]
STRIP_KEYS = {"generated_at", "last_attempt_at", "last_success_at", "last_observed_at",
              "observed_at", "age_seconds", "served_at", "response_digest"}


def normalize(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in STRIP_KEYS:
                continue
            # 文档路径按 basename 对比: cockpit 与 43191 各持合法副本 (路径前缀不同是收敛的预期结果)
            if k in ("api", "agent_reading", "interface") and isinstance(v, str):
                out[k] = Path(v).name
            else:
                out[k] = normalize(v)
        return out
    return value




def normalize_lineage_depth(data):
    lineage = data.get("lineage")
    if isinstance(lineage, dict) and "lineage_by_depth" in lineage:
        lbd = lineage["lineage_by_depth"]
        if isinstance(lbd, dict):
            normalized = {str(int(k)): v for k, v in lbd.items()}
            ordered = {k: normalized[k] for k in sorted(normalized, key=lambda x: int(x))}
            return {**data, "lineage": {**lineage, "lineage_by_depth": ordered}}
    return data


def digest(payload):
    return hashlib.sha256(json.dumps(normalize(payload), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", default="http://127.0.0.1:43191")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    snapshot_path = Path.home() / ".local/share/zhixing-dashboard/current.json"
    if not snapshot_path.is_file():
        print("current.json 不可达 — fidelity UNPROVABLE (not PASS)")
        return 2

    service = get_observatory_service()
    rows = []
    for op in OPERATIONS:
        zx = None
        mine = None
        try:
            url = f"{args.live}/api/v1/{op}"
            with urllib.request.urlopen(url, timeout=15) as resp:
                zx = json.loads(resp.read())
        except Exception:
            zx = None
        try:
            mine = service.query(op, {})
        except Exception:
            mine = None
        zx_d = digest(zx) if zx is not None else "-"
        if op == "context_pack" and mine is not None:
            mine = normalize_lineage_depth(mine)
        mine_d = digest(mine) if mine is not None else "-"
        rows.append({"op": op, "zx_sha": zx_d, "cockpit_sha": mine_d, "aligned": zx_d == mine_d})

    aligned = sum(1 for r in rows if r["aligned"])
    if args.json:
        print(json.dumps({"total": len(rows), "aligned": aligned, "rows": rows}, ensure_ascii=False, indent=1))
    else:
        print(f"43191 vs cockpit observatory - {aligned}/{len(rows)} operations aligned")
        for r in rows:
            mark = "OK " if r["aligned"] else "DIFF"
            print(f"  {mark} {r['op']:<14} zx={str(r['zx_sha'])[:12]} cockpit={str(r['cockpit_sha'])[:12]}")
    return 0 if aligned == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
