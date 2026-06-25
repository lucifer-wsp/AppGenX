import random

import pytest

from appgen.constants import SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE
from appgen.scan_fetch_concurrency import (
    ScanFetchConcurrencyGovernor,
    build_concurrency_ladder,
    rate_limit_threshold_for,
)


def test_build_concurrency_ladder_default():
    assert build_concurrency_ladder(10) == (10, 6, 2, 1)


def test_build_concurrency_ladder_custom_initial():
    assert build_concurrency_ladder(6) == (6, 2, 1)


def test_rate_limit_threshold_is_half_concurrency():
    assert rate_limit_threshold_for(10) == 5
    assert rate_limit_threshold_for(6) == 3
    assert rate_limit_threshold_for(2) == 1
    assert rate_limit_threshold_for(1) == 1


def test_batch_rate_limits_step_down_at_ten(monkeypatch):
    monkeypatch.setattr(random, "choice", lambda xs: xs[0])

    gov = ScanFetchConcurrencyGovernor.create(10)
    assert gov.rate_limit_threshold() == 5

    for _ in range(4):
        adj = gov.on_rate_limited()
        assert not adj.changed
        assert gov.active_limit == 10

    adj = gov.on_rate_limited()
    assert adj.changed
    assert gov.active_limit == 6
    assert gov.max_allowed == 6
    assert adj.delay_sec == 1.0


def test_batch_rate_limits_step_down_at_six(monkeypatch):
    monkeypatch.setattr(random, "choice", lambda xs: 800)

    gov = ScanFetchConcurrencyGovernor(ladder=(10, 6, 2, 1), current=6, max_allowed=10)
    assert gov.rate_limit_threshold() == 3

    for _ in range(3):
        gov.on_rate_limited()
    assert gov.active_limit == 2


def test_batch_rate_limits_continue_to_one(monkeypatch):
    monkeypatch.setattr(random, "choice", lambda xs: 800)

    gov = ScanFetchConcurrencyGovernor.create(10)
    for target in (6, 2, 1):
        threshold = gov.rate_limit_threshold()
        for _ in range(threshold):
            gov.on_rate_limited()
        assert gov.active_limit == target

    assert gov.max_allowed == 1


def test_wave_success_streak_requires_full_rounds():
    gov = ScanFetchConcurrencyGovernor.create(10)

    for _ in range(2):
        adj = gov.on_wave_complete(dispatched=10, successes=10, had_rate_limit=False)
        assert not adj.changed
        assert gov.active_limit == 10

    adj = gov.on_wave_complete(dispatched=10, successes=10, had_rate_limit=False)
    assert not adj.changed  # already at top


def test_wave_success_streak_raises_after_drop():
    gov = ScanFetchConcurrencyGovernor(ladder=(10, 6, 2, 1), current=6, max_allowed=10)

    for _ in range(SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE - 1):
        adj = gov.on_wave_complete(dispatched=6, successes=6, had_rate_limit=False)
        assert not adj.changed

    adj = gov.on_wave_complete(dispatched=6, successes=6, had_rate_limit=False)
    assert adj.changed
    assert gov.active_limit == 10


def test_wave_rate_limit_resets_streak():
    gov = ScanFetchConcurrencyGovernor(ladder=(10, 6, 2, 1), current=6, max_allowed=10)

    gov.on_wave_complete(dispatched=6, successes=6, had_rate_limit=False)
    gov.on_wave_complete(dispatched=6, successes=6, had_rate_limit=False)

    gov.on_rate_limited()
    adj = gov.on_wave_complete(dispatched=6, successes=6, had_rate_limit=False)
    assert not adj.changed
    assert gov.active_limit == 6

    for _ in range(SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE):
        gov.on_wave_complete(dispatched=6, successes=6, had_rate_limit=False)
    assert gov.active_limit == 10


def test_wave_partial_success_does_not_count():
    gov = ScanFetchConcurrencyGovernor(ladder=(10, 6, 2, 1), current=6, max_allowed=10)

    for _ in range(SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE):
        gov.on_wave_complete(dispatched=6, successes=5, had_rate_limit=False)
    assert gov.active_limit == 6


def test_wave_success_cannot_exceed_cap():
    gov = ScanFetchConcurrencyGovernor(ladder=(10, 6, 2, 1), current=2, max_allowed=2)

    for _ in range(SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE):
        adj = gov.on_wave_complete(dispatched=2, successes=2, had_rate_limit=False)
    assert not adj.changed
    assert gov.active_limit == 2


def test_wave_success_raises_from_two_to_six_when_cap_allows():
    gov = ScanFetchConcurrencyGovernor(ladder=(10, 6, 2, 1), current=2, max_allowed=6)

    for _ in range(SCAN_FETCH_SUCCESS_STREAK_FOR_RAISE - 1):
        adj = gov.on_wave_complete(dispatched=2, successes=2, had_rate_limit=False)
        assert not adj.changed

    adj = gov.on_wave_complete(dispatched=2, successes=2, had_rate_limit=False)
    assert adj.changed
    assert gov.active_limit == 6


def test_full_wave_success_resets_batch_counter():
    gov = ScanFetchConcurrencyGovernor.create(10)
    for _ in range(4):
        gov.on_rate_limited()
    gov.on_wave_complete(dispatched=10, successes=10, had_rate_limit=False)
    for _ in range(4):
        gov.on_rate_limited()
    assert gov.active_limit == 10
    gov.on_rate_limited()
    assert gov.active_limit == 6
