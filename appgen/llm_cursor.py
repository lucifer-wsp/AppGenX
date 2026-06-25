from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from appgen.config import settings
from appgen.constants import (
    CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN,
    CURSOR_CHAT_TIMEOUT_SEC_MIN,
    DEFAULT_CURSOR_MODEL,
    PLACEHOLDER_CURSOR_KEY,
)
from appgen.runtime_settings import LLMProviderConfig, runtime_settings

_cursor_disabled: str | None = None

_launch_slot_lock = threading.Lock()
_launch_slot = 0
_stagger_wave_depth = 0

StreamProgressCallback = Callable[[str, int], None]


def is_cursor_disabled() -> bool:
    return _cursor_disabled is not None


def disable_cursor(reason: str) -> None:
    global _cursor_disabled
    _cursor_disabled = reason


def reset_cursor_launch_stagger() -> None:
    global _launch_slot
    with _launch_slot_lock:
        _launch_slot = 0


@contextmanager
def cursor_launch_wave():
    global _stagger_wave_depth
    reset_cursor_launch_stagger()
    with _launch_slot_lock:
        _stagger_wave_depth += 1
    try:
        yield
    finally:
        with _launch_slot_lock:
            _stagger_wave_depth = max(0, _stagger_wave_depth - 1)


def _wait_launch_stagger() -> None:
    global _launch_slot
    if _stagger_wave_depth <= 0:
        return

    rc = runtime_settings.get()
    stagger_ms = max(0, rc.cursor_launch_stagger_ms)
    jitter_ms = max(0, rc.cursor_launch_jitter_ms)
    with _launch_slot_lock:
        slot = _launch_slot
        _launch_slot += 1

    delay_ms = slot * stagger_ms
    if jitter_ms > 0:
        delay_ms += random.randint(0, jitter_ms)
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)


def _resolve_agent_bin() -> str | None:
    configured = os.environ.get("CURSOR_AGENT_BIN", "").strip()
    if configured and Path(configured).exists():
        return configured
    for candidate in (
        shutil.which("agent"),
        str(Path.home() / ".local/bin/agent"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _resolve_api_key(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return (settings.cursor_api_key or os.environ.get("CURSOR_API_KEY", "")).strip()


def cursor_available_with(api_key: str | None = None) -> bool:
    if is_cursor_disabled():
        return False
    key = _resolve_api_key(api_key)
    return bool(key and key != PLACEHOLDER_CURSOR_KEY and _resolve_agent_bin())


def cursor_available() -> bool:
    return cursor_available_with(None)


def _is_keychain_error(stderr: str) -> bool:
    lower = stderr.lower()
    return "password not found" in lower or "access-token" in lower or "security command failed" in lower


def _build_agent_cmd(
    *,
    agent_bin: str,
    api_key: str,
    model: str,
    prompt: str,
    stream: bool,
) -> list[str]:
    cmd: list[str] = [
        agent_bin,
        "-p",
        "--trust",
        "--force",
        "--output-format",
        "stream-json" if stream else "text",
        "--api-key",
        api_key,
    ]
    if stream:
        cmd.append("--stream-partial-output")
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    return cmd


def _assistant_text_from_event(event: dict[str, Any]) -> str:
    message = event.get("message") or {}
    content = message.get("content") or []
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _consume_stream_event(
    event: dict[str, Any],
    *,
    assistant_buf: list[str],
    received_chars: int,
    on_progress: StreamProgressCallback | None,
) -> tuple[int, str | None]:
    """处理 stream-json 行，返回 (received_chars, final_result|None)。"""
    etype = event.get("type")
    if etype == "thinking" and event.get("subtype") == "delta":
        delta = str(event.get("text") or "")
        received_chars += len(delta)
        if on_progress and delta:
            on_progress("推理中", received_chars)
        return received_chars, None

    if etype == "assistant":
        text = _assistant_text_from_event(event)
        if text:
            if not assistant_buf or len(text) >= len(assistant_buf[-1]):
                if assistant_buf:
                    assistant_buf[-1] = text
                else:
                    assistant_buf.append(text)
            else:
                assistant_buf.append(text)
            received_chars += len(text)
            if on_progress:
                on_progress("生成中", received_chars)
        return received_chars, None

    if etype == "result":
        if event.get("subtype") == "success":
            result = str(event.get("result") or "")
            if result:
                return received_chars, result
            if assistant_buf:
                return received_chars, assistant_buf[-1]
            return received_chars, ""
        err = str(event.get("result") or event.get("error") or "Cursor CLI 返回错误")
        raise RuntimeError(err)

    return received_chars, None


def _run_agent_stream(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    wall_timeout_sec: int,
    idle_timeout_sec: int,
    on_progress: StreamProgressCallback | None,
) -> str:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    started = time.monotonic()
    last_activity = started
    received_chars = 0
    assistant_buf: list[str] = []
    final_text: str | None = None

    while True:
        now = time.monotonic()
        if now - started > wall_timeout_sec:
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(
                f"Cursor CLI 总时长超限（{wall_timeout_sec}s）：任务过大或模型过慢，"
                f"请减少 DevCode 每批屏幕数。"
            )
        if now - last_activity > idle_timeout_sec:
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(
                f"Cursor CLI 无输出超时（{idle_timeout_sec}s 无新 token）："
                f"模型可能已卡住，请重试或换模型。"
            )

        line = proc.stdout.readline()
        if line:
            last_activity = time.monotonic()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            received_chars, maybe_final = _consume_stream_event(
                event,
                assistant_buf=assistant_buf,
                received_chars=received_chars,
                on_progress=on_progress,
            )
            if maybe_final is not None:
                final_text = maybe_final
            continue

        if proc.poll() is not None:
            break
        time.sleep(0.05)

    stderr_thread.join(timeout=1.0)
    stderr = "".join(stderr_chunks).strip()

    if proc.returncode != 0:
        hint = ""
        if _is_keychain_error(stderr):
            hint = (
                "（CLI 启动时钥匙串竞态：已启用错峰启动；若仍失败请增大 "
                "cursor_launch_stagger_ms 或在设置中添加 OpenAI 提供商）"
            )
        raise RuntimeError(
            f"Cursor CLI 失败 (exit {proc.returncode}): {stderr[:500]}{hint}"
        )

    if final_text is not None:
        return final_text.strip()
    if assistant_buf:
        return assistant_buf[-1].strip()
    raise RuntimeError("Cursor CLI 未返回有效内容")


def cursor_chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    json_mode: bool = False,
    provider: LLMProviderConfig | None = None,
    on_progress: StreamProgressCallback | None = None,
) -> str:
    return cursor_chat_with(
        provider,
        system,
        user,
        temperature=temperature,
        json_mode=json_mode,
        on_progress=on_progress,
    )


def cursor_chat_with(
    provider: LLMProviderConfig | None,
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    json_mode: bool = False,
    on_progress: StreamProgressCallback | None = None,
) -> str:
    del temperature

    if is_cursor_disabled():
        raise RuntimeError(_cursor_disabled or "Cursor CLI 已禁用")

    api_key = _resolve_api_key(provider.api_key if provider else None)
    if not api_key or api_key == PLACEHOLDER_CURSOR_KEY:
        raise RuntimeError("未配置 CURSOR_API_KEY")

    agent_bin = _resolve_agent_bin()
    if not agent_bin:
        raise RuntimeError(
            "未找到 Cursor CLI（agent）。请安装：curl -fsSL https://cursor.com/install | bash\n"
            "并确保 ~/.local/bin 在 PATH 中，或设置 CURSOR_AGENT_BIN"
        )

    rc = runtime_settings.get()
    cwd = str(settings.cursor_cwd or rc.cursor_cwd or Path(__file__).resolve().parent.parent)
    suffix = "只输出上述任务要求的正文内容，不要加前言、解释或 markdown 包裹。"
    if json_mode:
        suffix = (
            "你的回复有且仅有一个 JSON 对象：以 { 开头、以 } 结尾。"
            "禁止输出 JSON 数组。禁止 markdown。禁止任何解释文字。"
        )

    prompt = f"{system}\n\n---\n\n{user}\n\n---\n\n{suffix}"

    env = os.environ.copy()
    env["CURSOR_API_KEY"] = api_key

    model = (provider.model if provider and provider.model else settings.cursor_model or DEFAULT_CURSOR_MODEL).strip()
    wall_timeout_sec = max(CURSOR_CHAT_TIMEOUT_SEC_MIN, rc.cursor_chat_timeout_sec)
    idle_timeout_sec = max(CURSOR_CHAT_IDLE_TIMEOUT_SEC_MIN, rc.cursor_chat_idle_timeout_sec)

    last_error = ""
    for attempt in range(3):
        _wait_launch_stagger()
        if attempt > 0:
            time.sleep(rc.cursor_launch_stagger_ms / 1000.0)

        cmd = _build_agent_cmd(
            agent_bin=agent_bin,
            api_key=api_key,
            model=model,
            prompt=prompt,
            stream=True,
        )
        try:
            return _run_agent_stream(
                cmd,
                cwd=cwd,
                env=env,
                wall_timeout_sec=wall_timeout_sec,
                idle_timeout_sec=idle_timeout_sec,
                on_progress=on_progress,
            )
        except RuntimeError as exc:
            last_error = str(exc)
            if _is_keychain_error(last_error) and attempt < 2:
                continue
            raise

    hint = ""
    if _is_keychain_error(last_error):
        hint = (
            "（CLI 启动时钥匙串竞态：已启用错峰启动；若仍失败请增大 "
            "cursor_launch_stagger_ms 或在设置中添加 OpenAI 提供商）"
        )
    raise RuntimeError(f"Cursor CLI 失败: {last_error[:500]}{hint}")
