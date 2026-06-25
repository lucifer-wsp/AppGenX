"""pytest 全局 fixture：避免测试写入 workspace/settings.json。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_runtime_settings_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "pytest_workspace"
    ws.mkdir()
    monkeypatch.setenv("APPGEN_WORKSPACE", str(ws))

    from appgen.config import settings
    from appgen.runtime_settings import runtime_settings

    settings.appgen_workspace = ws
    runtime_settings._bootstrapped = False
    runtime_settings.bootstrap_from_env(settings)
    yield
    runtime_settings._bootstrapped = False
