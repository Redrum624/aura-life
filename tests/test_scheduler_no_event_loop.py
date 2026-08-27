"""`start()` must degrade, not crash, when there is no running event loop.

APScheduler's `AsyncIOScheduler` binds to the *running* loop at `start()`.
The origin host always called `start()` from inside an async server, so this
never surfaced there. A general-purpose library has no such guarantee: a
synchronous host that installs the `[scheduler]` extra and calls `start()`
got `RuntimeError: no running event loop` — while a host that installed
*nothing* got the documented "run manually" fallback. The stricter dependency
produced the worse failure, which is backwards.

These tests pin the fallback so the two paths behave alike.
"""
import threading

import pytest

from aura_life.scheduler import life_scheduler as ls


class _FakeAsyncIOScheduler:
    """Stands in for APScheduler, raising exactly what it raises off-loop."""

    def __init__(self):
        self.jobs = []

    def add_job(self, *a, **k):
        self.jobs.append(k.get("id"))

    def start(self, paused=False):
        raise RuntimeError("no running event loop")

    def shutdown(self, wait=True):
        pass


@pytest.fixture
def apscheduler_present(monkeypatch):
    monkeypatch.setattr(ls, "HAS_APSCHEDULER", True)
    monkeypatch.setattr(ls, "AsyncIOScheduler", _FakeAsyncIOScheduler, raising=False)
    monkeypatch.setattr(ls, "IntervalTrigger", lambda **k: object(), raising=False)


def _sched():
    return ls.LifeScheduler(on_world_tick=lambda: None)


def test_start_does_not_raise_without_a_running_loop(apscheduler_present):
    s = _sched()
    s.start()  # must not raise


def test_start_reports_not_running_after_the_fallback(apscheduler_present):
    s = _sched()
    s.start()
    assert s.is_running is False, (
        "a scheduler that could not bind a loop must not claim to be running"
    )


def test_stop_is_safe_after_a_failed_start(apscheduler_present):
    s = _sched()
    s.start()
    s.stop()  # must not raise


def test_the_fallback_says_why(apscheduler_present, caplog):
    s = _sched()
    with caplog.at_level("WARNING"):
        s.start()
    assert any("event loop" in r.message for r in caplog.records), (
        "the warning must name the real cause, not just say 'failed'"
    )


def test_a_real_loop_still_starts_normally(apscheduler_present):
    """The fallback must not swallow the success path."""
    import asyncio

    class _Works(_FakeAsyncIOScheduler):
        def start(self, paused=False):
            self.started = True

    ls.AsyncIOScheduler = _Works
    s = _sched()
    s.start()
    assert s.is_running is True
    s.stop()
