"""cockpit.handlers.scene_lifecycle — 场景生命周期状态聚合 (BET-Y1Q4-T7-05).

为 Cockpit 呈现场景卡生命周期状态与样本积累雷达图的纯函数聚合层。
不新增路由, 只供现有 CLI/handler 消费; 零模型调用。
"""

from __future__ import annotations

from typing import Any

ORDER = ("draft", "shadow", "assisted", "supervised", "routine")

PROMOTE_GAPS = {
    "draft": {"need_samples": 3, "need_calibration": 0.0, "next": "shadow"},
    "shadow": {"need_samples": 30, "need_calibration": 0.6, "next": "assisted"},
    "assisted": {"need_samples": 30, "need_calibration": 0.6, "next": "supervised"},
    "supervised": {"need_samples": 30, "need_calibration": 0.6, "next": "routine"},
    "routine": {"need_samples": 0, "need_calibration": 0.0, "next": None},
}


def lifecycle_status(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合场景卡生命周期分布与每档晋级缺口雷达.

    输入每张卡: {scene_id, lifecycle, n_samples, calibration}。
    非法 lifecycle 的卡计入 unknown, 不抛异常。
    """
    dist: dict[str, int] = {lv: 0 for lv in ORDER}
    unknown = 0
    gaps: list[dict[str, Any]] = []
    for card in cards:
        lv = card.get("lifecycle", "")
        if lv not in ORDER:
            unknown += 1
            continue
        dist[lv] += 1
        gate = PROMOTE_GAPS[lv]
        if gate["next"] is None:
            continue
        n = int(card.get("n_samples", 0))
        c = float(card.get("calibration", 0.0))
        gaps.append(
            {
                "scene_id": card.get("scene_id", ""),
                "lifecycle": lv,
                "next": gate["next"],
                "samples_gap": max(int(gate["need_samples"]) - n, 0),
                "calibration_gap": round(max(float(gate["need_calibration"]) - c, 0.0), 4),
                "ready": n >= int(gate["need_samples"])
                and c >= float(gate["need_calibration"]),
            }
        )
    return {
        "total": len(cards),
        "distribution": dist,
        "unknown": unknown,
        "promotion_gaps": gaps,
    }
