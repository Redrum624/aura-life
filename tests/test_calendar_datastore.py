"""Regression tests for the calendar persistence path (``_datastore``).

Background — the defect these tests pin down
--------------------------------------------
Three calendar methods opened their database through ``self._datastore``:

* ``add_calendar_entry``            (public)
* ``get_upcoming_calendar_entries`` (public)
* ``_scan_calendar_for_triggers``   (daily tick)

``LifeService`` never assigned ``self._datastore`` anywhere, and the class had no
such attribute, so the two public methods raised
``AttributeError: 'LifeService' object has no attribute '_datastore'`` on their
very first call, and the daily scan — invoked inside a
``try: ... except Exception: logger.debug(...)`` — failed silently on every tick.
Calendar ``UPCOMING_EVENT`` triggers, post-event ``EMOTIONAL_CHECK_IN`` triggers
and anniversary promotion therefore never fired at all.

The ``user_calendar`` table is created by ``_init_database()`` on
``self._db_path`` like every other table in the module, so "no datastore" is the
normal library shape and must work unaided. A host that *does* supply a
consolidated datastore must get its rows there instead.

Deliberately **no shim**: nothing here monkeypatches ``_datastore`` onto the
instance. Any test that needed to do that would be testing the shim, not the fix.
``svc.start()`` is never called (it spawns scheduler + daemon threads);
``_init_database()`` runs inside ``__init__``, so a freshly constructed service is
enough. ``db_path`` is a real temp file — ``:memory:`` cannot work, because the
schema is created on a connection that is then closed.
"""

import contextlib
import logging
import sqlite3
from datetime import datetime, timedelta

import pytest

from aura_life.life_service import LifeService
from aura_life.models import CalendarEntry


def _svc(tmp_path, **kwargs):
    """A host-free ``LifeService`` on its own temp database."""
    return LifeService(
        db_path=str(tmp_path / "life.db"),
        persona_id="testpersona",
        **kwargs,
    )


def _entry(name="dentist appointment", days=2, **kwargs):
    when = datetime.now() + timedelta(days=days)
    return CalendarEntry(
        event_name=name,
        event_date=when,
        date_str=when.strftime("%Y-%m-%d"),
        feeling=kwargs.pop("feeling", "nervous"),
        importance=kwargs.pop("importance", 0.8),
        **kwargs,
    )


class _FakeTrigger:
    """Stand-in for the host's follow-up manager; records every trigger."""

    def __init__(self):
        self.triggers = []

    def create_trigger(self, **kwargs):
        self.triggers.append(kwargs)


class _FakeDatastore:
    """Minimal stand-in for the host's consolidated ``PersonaDataStore``.

    Same contract the library already relies on in
    ``emotion_persistence.EmotionPersistence._get_connection``: ``get_connection()``
    returns a context manager yielding a live ``sqlite3.Connection`` and commits on
    a clean exit. It starts out *empty* — no ``user_calendar`` table — which is the
    real-world case: the host owns that file and has never heard of this schema.
    """

    def __init__(self, path):
        self.path = str(path)

    @contextlib.contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# --------------------------------------------------------------------------
# The attribute itself
# --------------------------------------------------------------------------

def test_datastore_attribute_exists_and_defaults_to_none(tmp_path):
    """``_datastore`` must be a real attribute, defaulting to None like
    ``memory_service`` — not a name that only appears on the read side."""
    svc = _svc(tmp_path)
    assert hasattr(svc, "_datastore"), (
        "LifeService reads self._datastore but never assigns it"
    )
    assert svc._datastore is None


# --------------------------------------------------------------------------
# The two public methods
# --------------------------------------------------------------------------

def test_add_calendar_entry_no_attribute_error(tmp_path):
    svc = _svc(tmp_path)
    try:
        added = svc.add_calendar_entry(_entry())
    except AttributeError as exc:                       # pragma: no cover
        pytest.fail(f"add_calendar_entry raised AttributeError: {exc}")
    assert added is True


def test_add_calendar_entry_dedupes_on_name_and_date(tmp_path):
    svc = _svc(tmp_path)
    entry = _entry()
    assert svc.add_calendar_entry(entry) is True
    assert svc.add_calendar_entry(entry) is False


def test_get_upcoming_calendar_entries_no_attribute_error(tmp_path):
    svc = _svc(tmp_path)
    try:
        assert svc.get_upcoming_calendar_entries() == []
    except AttributeError as exc:                       # pragma: no cover
        pytest.fail(f"get_upcoming_calendar_entries raised AttributeError: {exc}")


def test_added_entry_is_read_back(tmp_path):
    svc = _svc(tmp_path)
    svc.add_calendar_entry(_entry(name="a family visit", days=3))
    upcoming = svc.get_upcoming_calendar_entries(days_ahead=7)
    assert [e.event_name for e in upcoming] == ["a family visit"]
    assert upcoming[0].id is not None
    assert upcoming[0].importance == pytest.approx(0.8)


def test_entry_outside_window_is_not_returned(tmp_path):
    svc = _svc(tmp_path)
    svc.add_calendar_entry(_entry(name="far off", days=30))
    assert svc.get_upcoming_calendar_entries(days_ahead=7) == []


# --------------------------------------------------------------------------
# The silent one
# --------------------------------------------------------------------------

def test_scan_calendar_for_triggers_no_attribute_error(tmp_path):
    """Called bare — the daily tick wraps this in ``except Exception`` and only
    logs at DEBUG, which is exactly why the defect survived. Call it directly."""
    svc = _svc(tmp_path)
    try:
        svc._scan_calendar_for_triggers()
    except AttributeError as exc:                       # pragma: no cover
        pytest.fail(f"_scan_calendar_for_triggers raised AttributeError: {exc}")


def test_upcoming_event_trigger_actually_fires(tmp_path):
    """The behaviour that had never once happened in production."""
    fake = _FakeTrigger()
    svc = _svc(tmp_path, follow_up_provider=lambda pid: fake)
    svc.add_calendar_entry(_entry(name="a job interview", days=2))

    svc._scan_calendar_for_triggers()

    assert [t["trigger_type"] for t in fake.triggers] == ["UPCOMING_EVENT"]
    assert fake.triggers[0]["topic"] == "a job interview"

    # Marked triggered, so a second scan does not re-fire it.
    fake.triggers.clear()
    svc._life_trigger_cooldowns.clear()
    svc._scan_calendar_for_triggers()
    assert fake.triggers == []


def test_post_event_check_in_fires_for_a_just_passed_event(tmp_path):
    fake = _FakeTrigger()
    svc = _svc(tmp_path, follow_up_provider=lambda pid: fake)
    svc.add_calendar_entry(_entry(name="the recital", days=-1))

    svc._scan_calendar_for_triggers()

    assert [t["trigger_type"] for t in fake.triggers] == ["EMOTIONAL_CHECK_IN"]
    assert fake.triggers[0]["topic"] == "the recital"


def test_passed_recurring_event_is_promoted_to_anniversary(tmp_path):
    svc = _svc(tmp_path)
    svc.add_calendar_entry(_entry(name="a yearly milestone", days=-2, recurring=True))

    svc._scan_calendar_for_triggers()

    names = [a.name for a in svc._continuity._anniversaries]
    assert "a yearly milestone" in names


def test_scan_without_follow_up_provider_is_inert_not_fatal(tmp_path):
    """No host trigger manager configured — the scan must degrade, not raise,
    and must leave the row untriggered so it fires once a host appears."""
    svc = _svc(tmp_path)
    svc.add_calendar_entry(_entry(name="quiet event", days=1))
    svc._scan_calendar_for_triggers()

    with contextlib.closing(sqlite3.connect(str(tmp_path / "life.db"))) as conn:
        triggered = conn.execute(
            "SELECT triggered FROM user_calendar WHERE event_name = ?",
            ("quiet event",),
        ).fetchone()[0]
    assert triggered == 0


# --------------------------------------------------------------------------
# The daily tick that swallowed it
# --------------------------------------------------------------------------

def test_daily_tick_scan_leaves_no_debug_failure(tmp_path, caplog):
    """The daily tick runs the calendar scan inside
    ``try: ... except Exception: logger.debug("Calendar scan failed")``. Driving
    the real tick must not land in that branch — that swallow is the only reason
    the ``_datastore`` defect went unnoticed for the life of the module."""
    svc = _svc(tmp_path)
    svc.add_calendar_entry(_entry(name="tick check", days=1))
    with caplog.at_level(logging.DEBUG, logger="aura_life.life_service"):
        svc._scheduler.force_all_ticks()
    assert "Calendar scan failed" not in caplog.text


# --------------------------------------------------------------------------
# The injected-host shape
# --------------------------------------------------------------------------

def test_injected_datastore_receives_the_rows(tmp_path):
    """When a host supplies a datastore, calendar rows go there — and the library
    creates its own schema rather than assuming the host already has it."""
    store = _FakeDatastore(tmp_path / "consolidated.db")
    svc = _svc(tmp_path, datastore=store)

    assert svc._datastore is store
    assert svc.add_calendar_entry(_entry(name="hosted event", days=2)) is True
    assert [e.event_name for e in svc.get_upcoming_calendar_entries()] == ["hosted event"]

    with contextlib.closing(sqlite3.connect(str(tmp_path / "consolidated.db"))) as conn:
        rows = conn.execute("SELECT event_name FROM user_calendar").fetchall()
    assert rows == [("hosted event",)]

    # ...and NOT into the standalone life.db.
    with contextlib.closing(sqlite3.connect(str(tmp_path / "life.db"))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM user_calendar").fetchone()[0] == 0
