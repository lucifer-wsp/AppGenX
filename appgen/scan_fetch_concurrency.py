"""榜单拉取并发阶梯自适应：403/429 批次降档、连续成功升档、失败档位封顶。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from appgen.constants import (
    SCAN_FETCH_BATCH_BACKOFF_MS,
    SCAN_FETCH_CONCURRENCY_STEPS,
    SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE,
)


def build_concurrency_ladder(initial: int) -> tuple[int, ...]:
    """从初始并发向下构建阶梯，如 10 → [10, 6, 2, 1]。"""
    initial = max(1, initial)
    ladder: list[int] = [initial]
    for step in SCAN_FETCH_CONCURRENCY_STEPS:
        if step < ladder[-1]:
            ladder.append(step)
    if ladder[-1] != 1:
        ladder.append(1)
    return tuple(ladder)


def rate_limit_threshold_for(concurrency: int) -> int:
    """降档阈值 = 当前并发的一半（至少 1）。"""
    return max(1, concurrency // 2)


@dataclass(frozen=True)
class ConcurrencyAdjustment:
    changed: bool
    delay_sec: float = 0.0
    message: str = ""


@dataclass
class ScanFetchConcurrencyGovernor:
    """拉取并发阶梯控制器。

    - 默认从阶梯最高档（通常 10）开始
    - 累计 ``当前并发 / 2`` 次 403/429 → 降一档并随机退避
    - 连续 ``SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE`` 轮：在当前并发下整轮全部成功 → 升一档
    - 在某档位触发批次降档后，后续升档不得超过「严格低于该档位」的并发值
    """

    ladder: tuple[int, ...]
    current: int
    max_allowed: int
    batch_failures: int = 0
    wave_success_streak: int = 0
    min_level_hits: int = 0

    @classmethod
    def create(cls, initial_concurrency: int) -> ScanFetchConcurrencyGovernor:
        ladder = build_concurrency_ladder(initial_concurrency)
        top = ladder[0]
        return cls(ladder=ladder, current=top, max_allowed=top)

    @property
    def active_limit(self) -> int:
        return self.current

    @property
    def initial_limit(self) -> int:
        return self.ladder[0]

    def rate_limit_threshold(self) -> int:
        return rate_limit_threshold_for(self.current)

    def _next_lower(self, value: int) -> int | None:
        idx = self.ladder.index(value)
        if idx + 1 >= len(self.ladder):
            return None
        return self.ladder[idx + 1]

    def _next_higher(self, value: int) -> int | None:
        idx = self.ladder.index(value)
        if idx <= 0:
            return None
        candidate = self.ladder[idx - 1]
        if candidate > self.max_allowed:
            return None
        return candidate

    def _batch_delay_sec(self, *, at_min_level: bool) -> float:
        base = random.choice(SCAN_FETCH_BATCH_BACKOFF_MS) / 1000.0
        if not at_min_level:
            self.min_level_hits = 0
            return base
        self.min_level_hits += 1
        # 已在最低并发：退避逐步加长，避免 200ms 内反复撞墙
        return min(15.0, base + float(2 ** min(self.min_level_hits - 1, 3)))

    def on_rate_limited(self) -> ConcurrencyAdjustment:
        self.wave_success_streak = 0
        self.batch_failures += 1
        threshold = self.rate_limit_threshold()
        if self.batch_failures < threshold:
            return ConcurrencyAdjustment(changed=False)

        self.batch_failures = 0
        failed_at = self.current
        lower = self._next_lower(failed_at)
        idx = self.ladder.index(failed_at)
        if idx + 1 < len(self.ladder):
            cap = self.ladder[idx + 1]
            self.max_allowed = min(self.max_allowed, cap)

        at_min = lower is None
        delay = self._batch_delay_sec(at_min_level=at_min)

        if at_min:
            if self.min_level_hits == 1 or self.min_level_hits % 5 == 0:
                message = (
                    f"限流达 {threshold} 次（403/429，阈值为并发 {failed_at} 的一半），"
                    f"已在最低并发 {failed_at}，退避 {delay:.1f}s 后继续"
                    f"（第 {self.min_level_hits} 次）"
                )
            else:
                message = ""
            return ConcurrencyAdjustment(changed=False, delay_sec=delay, message=message)

        self.min_level_hits = 0
        self.current = lower
        return ConcurrencyAdjustment(
            changed=True,
            delay_sec=delay,
            message=(
                f"限流达 {threshold} 次（403/429，阈值为并发 {failed_at} 的一半），"
                f"并发 {failed_at} → {lower}，后续最高 {self.max_allowed}，"
                f"退避 {delay:.1f}s"
            ),
        )

    def on_wave_complete(
        self,
        *,
        dispatched: int,
        successes: int,
        had_rate_limit: bool,
    ) -> ConcurrencyAdjustment:
        """一轮并发结束：仅当本轮全部成功且无 403/429 时累计升档计数。"""
        if dispatched <= 0 or had_rate_limit:
            return ConcurrencyAdjustment(changed=False)
        if successes < dispatched:
            self.wave_success_streak = 0
            return ConcurrencyAdjustment(changed=False)

        self.batch_failures = 0
        self.wave_success_streak += 1
        if self.wave_success_streak < SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE:
            return ConcurrencyAdjustment(changed=False)

        self.wave_success_streak = 0
        at_level = self.current
        higher = self._next_higher(at_level)
        if higher is None:
            return ConcurrencyAdjustment(changed=False)

        self.current = higher
        return ConcurrencyAdjustment(
            changed=True,
            message=(
                f"连续 {SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE} 轮并发 {at_level} 全部成功，"
                f"并发 {at_level} → {higher}（封顶 {self.max_allowed}）"
            ),
        )
