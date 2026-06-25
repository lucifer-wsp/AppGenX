"""流水线后台任务登记（同进程内防止重复 resume）。"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_active_run_ids: set[str] = set()


def mark_pipeline_active(run_id: str) -> None:
    with _lock:
        _active_run_ids.add(run_id)


def mark_pipeline_inactive(run_id: str) -> None:
    with _lock:
        _active_run_ids.discard(run_id)


def is_pipeline_active(run_id: str) -> bool:
    with _lock:
        return run_id in _active_run_ids
