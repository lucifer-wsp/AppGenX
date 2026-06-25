"""LLM 分析采样上限校验（避免 scan_flow ↔ discovery 循环依赖）。"""

from __future__ import annotations

from appgen.constants import ANALYZE_MAX_SNAPSHOTS_MAX, ANALYZE_MAX_SNAPSHOTS_MIN


def normalize_analyze_max_snapshots(value: int, *, clamp: bool = False) -> int:
    """LLM 分析采样上限：控制送入模型的快照数量与总 token 成本。"""
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("分析采样上限须为整数") from exc
    if clamp:
        return max(ANALYZE_MAX_SNAPSHOTS_MIN, min(ANALYZE_MAX_SNAPSHOTS_MAX, n))
    if n < ANALYZE_MAX_SNAPSHOTS_MIN or n > ANALYZE_MAX_SNAPSHOTS_MAX:
        raise ValueError(
            f"分析采样上限须在 {ANALYZE_MAX_SNAPSHOTS_MIN}–{ANALYZE_MAX_SNAPSHOTS_MAX} 之间"
        )
    return n
