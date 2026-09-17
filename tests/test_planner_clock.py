"""A plan agreed in conversation is kept or dropped on the world clock's hour.

``DailyPlanner.set_planned_activity`` skips a slot whose hour has already
passed today, and it asked the host what hour that was -- ``datetime.now().hour``
-- even inside a service whose world runs on an injected clock. A simulating
host (a replay, a sandbox, a test) therefore lost a plan for 21:00 whenever the
process happened to run between 22:00 and 23:59, whatever hour its world was
at: ``test_multi_instance``'s 21:00 sentinel failed every night for exactly
that reason.

The seam is the career one (``tests/test_career_clock.py``): an optional ``now``
on the planner method, ``datetime.now()`` when it is omitted, and
``LifeService.add_conversation_plan`` passing ``self._world_clock()()`` -- which
is the wall clock when nothing is injected.
"""

import importlib
import random
from datetime import datetime

from aura_life.life_service import LifeService
from aura_life.models import DailyPlan
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.world import WorldEnvironment

#: The host, frozen late in the evening: 21:00 has passed on its clock.
HOST_LATE = datetime(2026, 9, 16, 22, 45)
#: A simulated morning, years from any host clock: 21:00 is still ahead of it.
WORLD_MORNING = datetime(2031, 3, 10, 9, 0)

PLANNER_MODULE = "aura_life.planner.daily_planner"


def _frozen(instant: datetime) -> type:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.replace(tzinfo=tz)

        @classmethod
        def today(cls):
            return instant

    return FrozenDateTime


def _freeze_host(monkeypatch, instant: datetime, modules=(PLANNER_MODULE,)) -> None:
    frozen = _frozen(instant)
    for name in modules:
        monkeypatch.setattr(importlib.import_module(name), "datetime", frozen)


def _activities(plan: DailyPlan) -> dict:
    return {slot.activity_name: slot.hour for slot in plan.slots}


# ----------------------------------------------------------------------
# 1. The planner judges "already passed" from the instant it is given
# ----------------------------------------------------------------------

def _planner_with_an_empty_plan() -> DailyPlanner:
    planner = DailyPlanner()
    planner._current_plan = DailyPlan(date=WORLD_MORNING.strftime("%Y-%m-%d"))
    return planner


def test_the_planner_judges_a_passed_hour_by_the_instant_it_is_given(monkeypatch):
    _freeze_host(monkeypatch, HOST_LATE)
    planner = _planner_with_an_empty_plan()

    planner.set_planned_activity(21, "sentinel", location="home", now=WORLD_MORNING)
    planner.set_planned_activity(9, "coffee", location="cafe", now=WORLD_MORNING)  # the current hour is open
    planner.set_planned_activity(8, "missed bus", location="street", now=WORLD_MORNING)

    assert _activities(planner.current_plan) == {"coffee": 9, "sentinel": 21}


def test_without_an_instant_the_planner_still_reads_the_wall_clock(monkeypatch):
    _freeze_host(monkeypatch, HOST_LATE)
    planner = _planner_with_an_empty_plan()

    planner.set_planned_activity(21, "sentinel", location="home")
    planner.set_planned_activity(22, "late tea", location="home")
    planner.set_planned_activity(23, "reading", location="home")

    assert _activities(planner.current_plan) == {"late tea": 22, "reading": 23}


# ----------------------------------------------------------------------
# 2. The service hands the planner its world clock
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


def test_a_service_on_an_injected_clock_keeps_a_plan_the_host_hour_has_passed(monkeypatch, tmp_path):
    """Host at 22:45, world at 09:00: 21:00 is ahead, 08:00 is behind."""
    _freeze_host(monkeypatch, HOST_LATE)
    svc = _service(tmp_path, "evening", WorldEnvironment(now=lambda: WORLD_MORNING))
    svc._on_plan_tick()
    assert svc._daily_planner.current_plan is not None

    svc.add_conversation_plan("21:00 sentinel")
    svc.add_conversation_plan("08:00 missed bus")

    planned = _activities(svc._daily_planner.current_plan)
    assert planned.get("sentinel") == 21
    assert "missed bus" not in planned


def test_a_service_with_no_injected_clock_drops_an_hour_the_wall_clock_has_passed(monkeypatch, tmp_path):
    _freeze_host(monkeypatch, HOST_LATE, (PLANNER_MODULE, "aura_life.world.environment"))
    svc = _service(tmp_path, "wallclock")
    svc._on_plan_tick()
    assert svc._daily_planner.current_plan is not None

    svc.add_conversation_plan("21:00 sentinel")
    svc.add_conversation_plan("23:00 reading before bed")

    planned = _activities(svc._daily_planner.current_plan)
    assert "sentinel" not in planned
    assert planned.get("reading before bed") == 23
