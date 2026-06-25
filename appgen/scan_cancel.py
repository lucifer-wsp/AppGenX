"""扫描任务取消：内存信号 + 与 scan 状态联动。"""

from __future__ import annotations

import asyncio
import threading


class ScanCancelledError(Exception):
    """用户请求停止扫描/分析。"""


_lock = threading.RLock()
_cancelled: set[str] = set()
_events: dict[str, asyncio.Event] = {}


def register(scan_id: str) -> None:
    with _lock:
        _cancelled.discard(scan_id)
        _events[scan_id] = asyncio.Event()


def unregister(scan_id: str) -> None:
    with _lock:
        _cancelled.discard(scan_id)
        _events.pop(scan_id, None)


def request(scan_id: str) -> None:
    with _lock:
        _cancelled.add(scan_id)
        ev = _events.get(scan_id)
        if ev is not None:
            ev.set()


def is_requested(scan_id: str) -> bool:
    with _lock:
        return scan_id in _cancelled


def event(scan_id: str) -> asyncio.Event | None:
    with _lock:
        return _events.get(scan_id)
