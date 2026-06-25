import json

import pytest
from pydantic import ValidationError

from appgen.constants import (
    ANALYZE_MAX_SNAPSHOTS_MAX,
    ANALYZE_MAX_SNAPSHOTS_MIN,
    DEFAULT_ANALYZE_MAX_SNAPSHOTS,
)
from appgen.runtime_settings import RuntimeSettings, RuntimeSettingsManager
from appgen.analyze_limits import normalize_analyze_max_snapshots


def test_normalize_analyze_max_snapshots_ok():
    assert normalize_analyze_max_snapshots(40) == 40
    assert normalize_analyze_max_snapshots(ANALYZE_MAX_SNAPSHOTS_MIN) == ANALYZE_MAX_SNAPSHOTS_MIN
    assert normalize_analyze_max_snapshots(ANALYZE_MAX_SNAPSHOTS_MAX) == ANALYZE_MAX_SNAPSHOTS_MAX


def test_normalize_analyze_max_snapshots_rejects_out_of_range():
    with pytest.raises(ValueError, match="10–120"):
        normalize_analyze_max_snapshots(ANALYZE_MAX_SNAPSHOTS_MIN - 1)
    with pytest.raises(ValueError, match="10–120"):
        normalize_analyze_max_snapshots(ANALYZE_MAX_SNAPSHOTS_MAX + 1)


def test_normalize_analyze_max_snapshots_clamp():
    assert normalize_analyze_max_snapshots(500, clamp=True) == ANALYZE_MAX_SNAPSHOTS_MAX
    assert normalize_analyze_max_snapshots(1, clamp=True) == ANALYZE_MAX_SNAPSHOTS_MIN


def test_runtime_settings_model_bounds():
    ok = RuntimeSettings(analyze_max_snapshots=80)
    assert ok.analyze_max_snapshots == 80

    with pytest.raises(ValidationError):
        RuntimeSettings(analyze_max_snapshots=500)


def test_runtime_settings_load_clamps_legacy_value(tmp_path, monkeypatch):
    from appgen.config import settings

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "settings.json").write_text(
        json.dumps({"analyze_max_snapshots": 500}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "appgen_workspace", str(ws))

    mgr = RuntimeSettingsManager()
    mgr.bootstrap_from_env(settings)
    assert mgr.get().analyze_max_snapshots == ANALYZE_MAX_SNAPSHOTS_MAX


def test_runtime_settings_public_dict_exposes_bounds():
    from appgen.runtime_settings import runtime_settings

    pub = runtime_settings.to_public_dict()
    assert pub["analyze_max_snapshots_min"] == ANALYZE_MAX_SNAPSHOTS_MIN
    assert pub["analyze_max_snapshots_max"] == ANALYZE_MAX_SNAPSHOTS_MAX
    assert pub["analyze_max_snapshots"] == DEFAULT_ANALYZE_MAX_SNAPSHOTS
