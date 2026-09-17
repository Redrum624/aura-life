"""The energy tick's calendar and cadence reads follow the world clock.

Found by the audit behind ``tests/test_career_clock.py``: with a world clock
injected, two more reads on the ``_on_energy_tick`` path still asked the host
what time it was, and both *decide* something rather than stamp it.

* The continuity block. ``_on_energy_tick`` gated the daily, weekly and monthly
  cycles (anniversaries and the calendar scan, growth snapshots, character
  evolution, life chapters) on ``datetime.now()`` minus stamps that
  ``ContinuitySystem`` and ``CharacterEvolution`` also took from the host. On a
  simulated clock the cycles fired once, on the first tick, and then only when
  the host process had lived a real day -- so a replay and its original run
  (seconds apart, or a day apart) disagreed on how many chapters a persona had.
* ``MemoryTimeSystem._detect_weekly_rhythm`` read the host's weekday and month,
  so "Monday heaviness" arrived on the host's Mondays, not the world's.

The seam is the career one: an optional ``now`` on the engine methods,
``datetime.now()`` when it is omitted, and ``LifeService`` passing
``self._world_clock()()`` -- which is the wall clock when nothing is injected.
"""

import importlib
import random
from datetime import datetime, timedelta

import pytest

from aura_life.continuity.continuity_system import ContinuitySystem
from aura_life.life_service import LifeService
from aura_life.memory_time.memory_time_system import MemoryTimeSystem
from aura_life.persona_evolution.character_evolution import CharacterEvolution
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

#: A simulated Monday, years from any host clock.
WORLD_MONDAY = datetime(2031, 3, 10, 9, 0)
#: The host, frozen to a Saturday so no weekday rhythm can come from it.
HOST_SATURDAY = datetime(2026, 9, 19, 2, 0)

ROUTED_MODULES = (
    "aura_life.life_service",
    "aura_life.continuity.continuity_system",
    "aura_life.persona_evolution.character_evolution",
    "aura_life.memory_time.memory_time_system",
)


def _frozen(instant: datetime) -> type:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.replace(tzinfo=tz)

        @classmethod
        def today(cls):
            return instant

    return FrozenDateTime


def _freeze_host(monkeypatch, instant: datetime, modules=ROUTED_MODULES) -> None:
    frozen = _frozen(instant)
    for name in modules:
        monkeypatch.setattr(importlib.import_module(name), "datetime", frozen)


class ScriptedClock:
    """A clock that advances only when told to (see tests/test_energy_clock.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


# ----------------------------------------------------------------------
# 1. The engines answer from the instant they are given
# ----------------------------------------------------------------------

def test_continuity_cycles_stamp_and_match_the_given_instant(monkeypatch):
    _freeze_host(monkeypatch, HOST_SATURDAY)
    continuity = ContinuitySystem()
    continuity.add_anniversary("the day we met", WORLD_MONDAY.strftime("%m-%d"))

    events = continuity.daily_tick(now=WORLD_MONDAY)
    assert events == ["anniversary: the day we met"]
    assert continuity._last_daily_tick == WORLD_MONDAY

    continuity.weekly_tick({}, {}, 0.5, now=WORLD_MONDAY)
    assert continuity._last_weekly_tick == WORLD_MONDAY
    assert continuity._growth_snapshots[-1].date == WORLD_MONDAY

    chapter = continuity.monthly_tick(
        activity_summary={"reading": 3}, dominant_mood="content", avg_energy=0.6,
        goals_completed=[], goals_abandoned=[], identity_shifts=[], now=WORLD_MONDAY,
    )
    assert chapter.period_start == WORLD_MONDAY.replace(day=1)
    assert continuity._last_monthly_tick == WORLD_MONDAY


def test_character_evolution_stamps_the_given_instant(monkeypatch):
    _freeze_host(monkeypatch, HOST_SATURDAY)
    evolution = CharacterEvolution(original_baseline={"warmth": 0.5})

    evolution.monthly_evolution(identity_facets={}, relationship_trust=0.9, avg_mood="content", now=WORLD_MONDAY)

    assert evolution._last_evolution == WORLD_MONDAY
    assert evolution._drift_history[-1]["date"] == WORLD_MONDAY.isoformat()


def test_memory_time_notices_the_worlds_weekday_not_the_hosts(monkeypatch):
    _freeze_host(monkeypatch, HOST_SATURDAY)
    memory_time = MemoryTimeSystem(rng=random.Random(3))

    for _ in range(20):  # the rhythm check runs every 20th tick
        memory_time.tick(current_activity="", mood="neutral", season="spring", time_of_day="morning", now=WORLD_MONDAY)

    assert [(r.pattern, r.first_noticed) for r in memory_time._rhythms] == [("Monday heaviness", WORLD_MONDAY)]
    assert memory_time._time_perception.last_assessment == WORLD_MONDAY

    memory_time.add_life_chapter("a new job", "started at the bakery", now=WORLD_MONDAY)
    assert memory_time.get_current_chapter().period_start == WORLD_MONDAY


def test_without_an_instant_the_engines_still_read_the_wall_clock(monkeypatch):
    _freeze_host(monkeypatch, HOST_SATURDAY)
    continuity = ContinuitySystem()
    evolution = CharacterEvolution()
    memory_time = MemoryTimeSystem(rng=random.Random(3))

    continuity.daily_tick()
    continuity.weekly_tick({}, {}, 0.5)
    evolution.monthly_evolution(identity_facets={}, relationship_trust=0.5, avg_mood="neutral")
    for _ in range(20):
        memory_time.tick(current_activity="", mood="neutral", season="autumn", time_of_day="night")

    assert continuity._last_daily_tick == HOST_SATURDAY
    assert continuity._last_weekly_tick == HOST_SATURDAY
    assert evolution._last_evolution == HOST_SATURDAY
    assert memory_time._time_perception.last_assessment == HOST_SATURDAY
    assert memory_time._rhythms == []  # a Saturday has no weekday rhythm


# ----------------------------------------------------------------------
# 2. The service runs the cycles on the world clock
# ----------------------------------------------------------------------

def _service(tmp_path, pid, world=None) -> LifeService:
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
        definition=PersonalityDefinition(core_traits=["curious"], occupation="baker", home_type="studio"),
        rng=random.Random(5),
    )


def test_the_daily_cycle_fires_on_simulated_days_while_the_host_clock_stands_still(monkeypatch, tmp_path):
    """Frozen host, moving world: every stamp is the world's instant, and the
    daily cycle re-fires once a simulated day has passed -- which it never
    could on a host clock that does not move."""
    _freeze_host(monkeypatch, HOST_SATURDAY)
    clock = ScriptedClock(WORLD_MONDAY)
    svc = _service(tmp_path, "cycles", WorldEnvironment(now=clock))

    svc._on_energy_tick()
    first = clock.instant
    status = svc.get_status()
    assert status["continuity"]["last_daily_tick"] == first.isoformat()
    assert status["continuity"]["last_weekly_tick"] == first.isoformat()
    assert status["continuity"]["last_monthly_tick"] == first.isoformat()
    assert status["character_evolution"]["last_evolution"] == first.isoformat()
    assert svc._memory_time._time_perception.last_assessment == first

    clock.advance(23)
    svc._on_energy_tick()
    assert svc._continuity._last_daily_tick == first  # not a day yet
    assert svc._memory_time._time_perception.last_assessment == clock.instant  # every tick

    clock.advance(2)
    svc._on_energy_tick()
    assert svc._continuity._last_daily_tick == clock.instant
    assert svc._continuity._last_weekly_tick == first
    assert svc._memory_time._time_perception.last_assessment == clock.instant


def test_a_service_with_no_injected_clock_runs_the_cycles_on_the_wall_clock(monkeypatch, tmp_path):
    _freeze_host(monkeypatch, HOST_SATURDAY, ROUTED_MODULES + ("aura_life.world.environment",))
    svc = _service(tmp_path, "private")

    svc._on_energy_tick()

    assert svc._continuity._last_daily_tick == HOST_SATURDAY
    assert svc._character_evolution._last_evolution == HOST_SATURDAY
