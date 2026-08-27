"""Retention and thread-lifecycle regressions in ``life_service``.

Every case here is a collection or a table that only ever grew: rows written on a
fixed tick cadence and read back with a hard ``LIMIT``, lists appended to with no
dedupe or cap, and daemon threads spawned per tick with no handle and no join.
None of it is fast growth — which is exactly why none of it was noticed.

The caps are module constants so a host can see them, and so these tests can
shrink them with ``monkeypatch`` instead of writing five hundred rows to prove a
five-hundred-row bound.

``svc.start()`` is called in two tests here. That is safe in this suite:
``apscheduler`` is an optional dependency and ``LifeScheduler`` degrades to a
no-op without it, so ``start()`` spawns no scheduler thread — only the init-tick
thread that two of these tests are about.
"""

import contextlib
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.life_service import LifeService
from aura_life import life_service as life_service_module
from aura_life.models import ActivityLog, CalendarEntry, Goal


@pytest.fixture
def restore_hooks():
    """Snapshot and restore the process-wide hook registry."""
    saved = dict(hooks._registry)
    yield
    hooks._registry.clear()
    hooks._registry.update(saved)


def _svc(tmp_path, **kwargs):
    return LifeService(
        db_path=str(tmp_path / "life.db"),
        persona_id="testpersona",
        **kwargs,
    )


def _rows(tmp_path, sql, params=()):
    with contextlib.closing(sqlite3.connect(str(tmp_path / "life.db"))) as conn:
        return conn.execute(sql, params).fetchall()


def _count(tmp_path, table):
    return _rows(tmp_path, f"SELECT COUNT(*) FROM {table}")[0][0]  # noqa: S608


# --------------------------------------------------------------------------
# activity_logs — written every activity tick, read back with LIMIT 20
# --------------------------------------------------------------------------

def test_activity_logs_are_pruned_to_the_retention_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "ACTIVITY_LOG_RETENTION", 5)
    svc = _svc(tmp_path)

    base = datetime.now() - timedelta(hours=12)
    for i in range(12):
        svc._record_activity(
            ActivityLog(
                activity_name=f"activity_{i:02d}",
                started_at=base + timedelta(minutes=20 * i),
            )
        )

    assert _count(tmp_path, "activity_logs") == 5


def test_activity_log_prune_keeps_the_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "ACTIVITY_LOG_RETENTION", 3)
    svc = _svc(tmp_path)

    base = datetime.now() - timedelta(hours=12)
    for i in range(8):
        svc._record_activity(
            ActivityLog(
                activity_name=f"activity_{i:02d}",
                started_at=base + timedelta(minutes=20 * i),
            )
        )

    kept = [
        r[0] for r in _rows(
            tmp_path, "SELECT activity_name FROM activity_logs ORDER BY started_at"
        )
    ]
    assert kept == ["activity_05", "activity_06", "activity_07"]


# --------------------------------------------------------------------------
# shareable_experiences — inserted per share-worthy activity, never deleted
# --------------------------------------------------------------------------

def test_shared_experiences_are_pruned_past_the_retention_window(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "SHAREABLE_RETENTION_DAYS", 7)
    svc = _svc(tmp_path)

    svc._create_shareable_from_text("old and shared", context="ctx")
    svc._create_shareable_from_text("recent and shared", context="ctx")
    svc._create_shareable_from_text("never shared", context="ctx")

    # Mark them the way the runtime does — on the queued objects. _save_shareable
    # writes the queue back over the rows, so setting `shared` in SQL first would
    # simply be overwritten.
    by_content = {e.content: e for e in svc._shareable_queue}
    by_content["old and shared"].shared = True
    by_content["old and shared"].shared_at = datetime.now() - timedelta(days=30)
    by_content["recent and shared"].shared = True
    by_content["recent and shared"].shared_at = datetime.now() - timedelta(days=1)

    svc._save_shareable()

    surviving = {r[0] for r in _rows(tmp_path, "SELECT content FROM shareable_experiences")}
    assert surviving == {"recent and shared", "never shared"}


def test_unshared_experiences_are_never_pruned_however_old(tmp_path, monkeypatch):
    """An unshared row is still queued work — age alone must not delete it."""
    monkeypatch.setattr(life_service_module, "SHAREABLE_RETENTION_DAYS", 1)
    svc = _svc(tmp_path)
    svc._create_shareable_from_text("ancient but unshared", context="ctx")

    long_ago = (datetime.now() - timedelta(days=400)).isoformat()
    with contextlib.closing(sqlite3.connect(str(tmp_path / "life.db"))) as conn:
        conn.execute(
            "UPDATE shareable_experiences SET created_at = ? WHERE content = ?",
            (long_ago, "ancient but unshared"),
        )
        conn.commit()

    svc._save_shareable()
    assert _count(tmp_path, "shareable_experiences") == 1


# --------------------------------------------------------------------------
# life_goals — DELETE + full reinsert on every goal tick
# --------------------------------------------------------------------------

def test_persisted_goal_history_is_bounded(tmp_path, monkeypatch):
    """``_save_goals`` rewrites the whole table each save. The rows it writes must
    be bounded here, not left to depend on GoalEngine's own in-memory cap."""
    monkeypatch.setattr(life_service_module, "GOAL_HISTORY_PERSISTED_MAX", 3)
    svc = _svc(tmp_path)

    svc._goal_engine._completed_goals = [
        Goal(title=f"done_{i:02d}", completed_at=datetime.now()) for i in range(10)
    ]
    svc._goal_engine._abandoned_goals = [
        Goal(title=f"gave_up_{i:02d}", abandoned_at=datetime.now()) for i in range(10)
    ]
    active = len(svc._goal_engine.active_goals)

    svc._save_goals()

    assert _count(tmp_path, "life_goals") == active + 3 + 3
    titles = {r[0] for r in _rows(tmp_path, "SELECT title FROM life_goals")}
    assert "done_09" in titles and "done_00" not in titles
    assert "gave_up_09" in titles and "gave_up_00" not in titles


# --------------------------------------------------------------------------
# books_finished — appended on every completed book, re-reads included
# --------------------------------------------------------------------------

def test_finished_books_do_not_accumulate_duplicates(tmp_path):
    """``_pick_new_book`` deliberately re-picks a read title once everything is
    read, so the same title comes back around forever."""
    svc = _svc(tmp_path)
    for _ in range(25):
        svc._record_finished_book("A Novel")
    assert svc._media.books_finished == ["A Novel"]


def test_finished_books_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "BOOKS_FINISHED_MAX", 4)
    svc = _svc(tmp_path)
    for i in range(10):
        svc._record_finished_book(f"Title {i}")
    assert svc._media.books_finished == ["Title 6", "Title 7", "Title 8", "Title 9"]


# --------------------------------------------------------------------------
# user-registered locations — one row per slug parsed out of free text
# --------------------------------------------------------------------------

def test_user_registered_locations_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "USER_LOCATION_MAX", 3)
    svc = _svc(tmp_path)
    seeded = len(svc._location_registry)

    for i in range(9):
        svc._register_user_location(f"place number {i}")

    user_keys = [
        k for k, p in svc._location_registry.items() if p.source == "user"
    ]
    assert len(user_keys) == 3
    # Non-user locations (profile/occupation/interest seeds) are untouched.
    assert len(svc._location_registry) == seeded + 3
    # The planner's key set does not keep the evicted ones either.
    assert "place_number_0" not in svc._daily_planner._available_location_keys


def test_evicted_user_locations_are_deleted_from_the_table(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "USER_LOCATION_MAX", 2)
    svc = _svc(tmp_path)
    for i in range(6):
        svc._register_user_location(f"spot {i}")

    persisted = {
        r[0] for r in _rows(
            tmp_path, "SELECT key FROM life_locations WHERE source = 'user'"
        )
    }
    assert persisted == {"spot_4", "spot_5"}


def test_visited_user_locations_survive_eviction(tmp_path, monkeypatch):
    """Eviction drops never-visited entries first — a place she has actually been
    is part of her history, not conversational noise."""
    monkeypatch.setattr(life_service_module, "USER_LOCATION_MAX", 2)
    svc = _svc(tmp_path)

    svc._register_user_location("the old pier")
    svc._location_registry["the_old_pier"].visit_count = 4

    for i in range(5):
        svc._register_user_location(f"mentioned {i}")

    assert "the_old_pier" in svc._location_registry


# --------------------------------------------------------------------------
# user_calendar — one row per event extracted from conversation
# --------------------------------------------------------------------------

def test_dead_calendar_rows_are_pruned_by_the_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(life_service_module, "CALENDAR_RETENTION_DAYS", 30)
    svc = _svc(tmp_path)

    def _add(name, days, recurring=False):
        when = datetime.now() + timedelta(days=days)
        svc.add_calendar_entry(CalendarEntry(
            event_name=name, event_date=when,
            date_str=when.strftime("%Y-%m-%d"), recurring=recurring,
        ))

    _add("long gone", -90)
    _add("recent past", -1)
    _add("still coming", 2)
    _add("yearly, long gone", -90, recurring=True)

    svc._scan_calendar_for_triggers()

    names = {r[0] for r in _rows(tmp_path, "SELECT event_name FROM user_calendar")}
    assert names == {"recent past", "still coming", "yearly, long gone"}


def test_calendar_prune_does_not_touch_the_follow_up_window(tmp_path, monkeypatch):
    """A just-passed event is still owed a check-in; only rows that can never fire
    again are dropped."""
    monkeypatch.setattr(life_service_module, "CALENDAR_RETENTION_DAYS", 30)
    svc = _svc(tmp_path)
    when = datetime.now() - timedelta(hours=6)
    svc.add_calendar_entry(CalendarEntry(
        event_name="yesterday's thing", event_date=when,
        date_str=when.strftime("%Y-%m-%d"),
    ))

    svc._scan_calendar_for_triggers()
    assert _count(tmp_path, "user_calendar") == 1


# --------------------------------------------------------------------------
# Threads
# --------------------------------------------------------------------------

def test_visual_description_update_does_not_stack_threads(tmp_path, restore_hooks):
    """One in-flight generation at a time. The hook is host LLM + image work; the
    trigger fires at the end of every activity tick, so a hook slower than the
    tick interval used to stack a new daemon thread per tick, each pinning the
    service and the world."""
    started = threading.Event()
    release = threading.Event()
    calls = []

    def _slow_hook(persona_id, definition, life_service=None, world=None, image_dir=None):
        calls.append(persona_id)
        started.set()
        release.wait(5)

    hooks.configure(generate_and_update=_slow_hook)
    svc = _svc(tmp_path)

    svc._trigger_visual_description_update()
    assert started.wait(5), "first visual update never ran"

    for _ in range(5):
        svc._trigger_visual_description_update()

    release.set()
    svc._visual_thread.join(5)
    assert len(calls) == 1


def test_visual_description_thread_is_joined_on_stop(tmp_path, restore_hooks):
    release = threading.Event()

    def _slow_hook(persona_id, definition, life_service=None, world=None, image_dir=None):
        release.wait(5)

    hooks.configure(generate_and_update=_slow_hook)
    svc = _svc(tmp_path)
    svc._trigger_visual_description_update()
    thread = svc._visual_thread
    assert thread is not None

    release.set()
    svc.stop()
    assert not thread.is_alive(), "stop() returned with the visual thread still running"


def test_start_spawns_one_init_tick_thread_however_often_it_is_called(tmp_path):
    """``_scheduler.start()`` guards against a double start; this spawn did not,
    so every extra ``start()`` added an orphan thread that could still be mutating
    engine state after ``stop()`` had already saved."""
    svc = _svc(tmp_path)
    before = {t.name for t in threading.enumerate()}

    svc.start()
    svc.start()
    svc.start()

    spawned = [
        t for t in threading.enumerate()
        if t.name.startswith("life-init-ticks-") and t.name not in before
    ]
    assert len(spawned) <= 1
    svc.stop()


def test_stop_joins_the_init_tick_thread_before_saving(tmp_path):
    svc = _svc(tmp_path)
    svc.start()
    thread = svc._init_ticks_thread
    svc.stop()
    if thread is not None:
        assert not thread.is_alive(), "stop() returned with the init-tick thread running"


def test_the_location_cap_is_applied_to_what_is_loaded_from_disk(tmp_path, monkeypatch):
    """A database written before the cap existed would otherwise reload its whole
    registry on every start, so the cap has to bite on the load path too."""
    monkeypatch.setattr(life_service_module, "USER_LOCATION_MAX", 50)
    svc = _svc(tmp_path)
    with contextlib.closing(sqlite3.connect(str(tmp_path / "life.db"))) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO life_locations "
            "(key, name, place_type, description, source, familiarity, visit_count, last_visit) "
            "VALUES (?, ?, 'other', '', 'user', 0.3, 0, NULL)",
            [(f"legacy_{i:03d}", f"Legacy {i}") for i in range(120)],
        )
        conn.commit()

    monkeypatch.setattr(life_service_module, "USER_LOCATION_MAX", 5)
    reloaded = _svc(tmp_path)
    reloaded._load_state()

    user_keys = [k for k, p in reloaded._location_registry.items() if p.source == "user"]
    assert len(user_keys) == 5
    assert _count(tmp_path, "life_locations") <= 5 + len(
        [p for p in reloaded._location_registry.values() if p.source != "user"]
    )
