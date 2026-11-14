"""Shared fixtures.

``host_hour`` (humanness program Task 28, ruling T13-R1): the host's clock
frozen at one of four hours -- 02:00, 09:00, 15:00 and 22:00 -- in
``aura_life.models``, ``aura_life.planner.daily_planner`` and
``aura_life.life_service``, for the length of one test only (``monkeypatch``
puts each module's own ``datetime`` back afterwards). A test that asks for it
runs once per hour. Her day plan is read on the world clock, in her local
time, so nothing such a test checks may move with the hour the host runs at.
Before Task 28, ``DailyPlan.get_current_slot`` read ``datetime.now()``, and
``tests/test_household_npcs.py::test_a_joint_activity_goes_where_the_activity_is``
passed at night and failed in the afternoon.

The frozen instant is on a day none of the tests' worlds is on
(:data:`HOST_DAY`), so a host-clock read of the date shows as well as one of
the hour. Never ask for it in a test that runs a simulation
(``tests/sim_helpers.run_days``): the simulation freezes the ``datetime`` of
every aura_life module that still holds the real class, and would skip the
three this fixture froze.
"""

import importlib
import sqlite3
from datetime import datetime
from typing import Optional

import pytest

#: The host hours ``host_hour`` runs a test at: night, morning, afternoon, evening.
HOST_HOURS = (2, 9, 15, 22)
#: The host's day: a Wednesday no test's world is on.
HOST_DAY = datetime(2026, 9, 16)
#: The modules whose ``datetime`` ``host_hour`` freezes.
HOST_CLOCK_MODULES = ("aura_life.models", "aura_life.planner.daily_planner", "aura_life.life_service")

_REAL_DATETIME = datetime


class _HostClockMeta(type):
    # A real datetime still passes isinstance(x, datetime) inside a frozen
    # module (tests/sim_helpers.py's _SimDateTimeMeta does the same).
    def __instancecheck__(cls, obj):
        return isinstance(obj, _REAL_DATETIME)

    def __subclasscheck__(cls, sub):
        return isinstance(sub, type) and issubclass(sub, _REAL_DATETIME)


class HostClock(_REAL_DATETIME, metaclass=_HostClockMeta):
    """``datetime`` whose ``now()`` is the frozen host instant; everything else
    -- arithmetic, ``fromisoformat``, construction -- is inherited."""

    instant: Optional[datetime] = None

    @classmethod
    def now(cls, tz=None):
        return cls.instant if tz is None else cls.instant.replace(tzinfo=tz)

    @classmethod
    def today(cls):
        return cls.instant


# ``fromisoformat`` on the class above builds instances of it; give sqlite3 the
# text form its default datetime adapter uses, as tests/sim_helpers.py does.
sqlite3.register_adapter(HostClock, lambda value: value.isoformat(" "))


def freeze_host_clock(monkeypatch, instant: datetime) -> None:
    """Freeze the host's clock at ``instant`` in :data:`HOST_CLOCK_MODULES`
    until ``monkeypatch`` undoes it (at the end of the test)."""
    monkeypatch.setattr(HostClock, "instant", instant)
    for name in HOST_CLOCK_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "datetime", HostClock)


@pytest.fixture(params=HOST_HOURS, ids=lambda hour: f"host{hour:02d}00")
def host_hour(request, monkeypatch) -> datetime:
    """The host's clock frozen at the parameter's hour of :data:`HOST_DAY`,
    for this test only (:func:`freeze_host_clock`). Returns the instant."""
    instant = HOST_DAY.replace(hour=request.param)
    freeze_host_clock(monkeypatch, instant)
    return instant
