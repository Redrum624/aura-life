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

The schedule overrides had the same guard: ``cancel_work_today``,
``stay_at_current_location`` and ``schedule_rendezvous`` rewrite only the slots
from the current hour on, and read that hour from the host. They take the same
optional ``now``, and ``apply_schedule_override``, ``schedule_meeting_arrival``
and ``advance_transit_phase`` hand it the world instant.

Every one of those service methods can run bound to a duck-typed stand-in
rather than a ``LifeService`` -- a downstream host tests
``LifeService.add_conversation_plan`` that way, on an object with no
``_world_clock`` -- so the service asks
``getattr(self, "_world_clock", None)`` and, with no clock, passes no instant:
the host's wall clock, exactly as before.
"""

import importlib
import random
from datetime import datetime

import pytest

from aura_life.life_service import LifeService
from aura_life.models import DailyPlan, PlannedSlot, TransitPhase, TransitState
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


# ----------------------------------------------------------------------
# 3. A duck-typed stand-in with no world clock keeps the host's hour
# ----------------------------------------------------------------------

#: A host afternoon: 15:00 is still ahead of it.
HOST_AFTERNOON = datetime(2026, 9, 16, 13, 30)


class _PlanOnlyStandIn:
    """The contract a downstream host tests ``add_conversation_plan`` against.

    aura's ``server/tests/test_conversation_plan_tag.py`` binds the real
    ``LifeService.add_conversation_plan`` to an object carrying only
    ``_daily_planner``, ``_location_registry``, ``_register_user_location`` and
    ``_save_plan`` -- no ``_world_clock``, no world, no database.
    """

    def __init__(self, planner: DailyPlanner):
        self._daily_planner = planner
        self._location_registry = {}
        self.saved = 0

    def _register_user_location(self, location):
        self._location_registry[location.lower().replace(" ", "_")] = location

    def _save_plan(self):
        self.saved += 1


def test_a_stand_in_with_no_world_clock_still_plans_the_activity(monkeypatch):
    _freeze_host(monkeypatch, HOST_AFTERNOON)
    stand_in = _PlanOnlyStandIn(_planner_with_an_empty_plan())

    LifeService.add_conversation_plan(stand_in, "15:30 pilates @ studio")

    slot = stand_in._daily_planner.current_plan.get_slot_for_hour(15)
    assert slot is not None
    assert (slot.activity_name, slot.location, slot.reason) == ("pilates", "studio", "agreed with user")
    assert stand_in.saved == 1
    assert "studio" in stand_in._location_registry


def test_a_stand_in_with_no_world_clock_judges_a_passed_hour_on_the_host_clock(monkeypatch):
    _freeze_host(monkeypatch, HOST_LATE)
    stand_in = _PlanOnlyStandIn(_planner_with_an_empty_plan())

    LifeService.add_conversation_plan(stand_in, "21:00 sentinel")
    LifeService.add_conversation_plan(stand_in, "23:00 reading before bed")

    assert _activities(stand_in._daily_planner.current_plan) == {"reading before bed": 23}


# ----------------------------------------------------------------------
# 4. The schedule overrides rewrite the slots still ahead of the world's hour
# ----------------------------------------------------------------------
#
# Host frozen at 22:45, world at 09:00. The 21:00 slot is behind the host's
# hour and ahead of the world's, so it is the slot that shows which hour an
# override judged; 08:00 is behind both and must never move. The planner's
# "current slot" (``DailyPlan.get_current_slot``) stays on the host clock by
# scope, so ``aura_life.models`` is frozen at the same host instant: staying put
# keeps the location of the host's 22:00 slot, "bar".

PLAN_SLOTS = (
    (8, "working", "bakery"),
    (21, "working", "market"),
    (22, "working", "bar"),
    (23, "working", "club"),
)


def _plan_for_overrides() -> DailyPlan:
    return DailyPlan(
        date=WORLD_MORNING.strftime("%Y-%m-%d"),
        slots=[PlannedSlot(hour=h, activity_name=a, location=loc, reason="routine") for h, a, loc in PLAN_SLOTS],
    )


def _slots(plan: DailyPlan) -> dict:
    return {slot.hour: (slot.activity_name, slot.location) for slot in plan.slots}


def _skip_work(host) -> None:
    LifeService.apply_schedule_override(host, "skip work")


def _stay_here(host) -> None:
    LifeService.apply_schedule_override(host, "stay here")


def _meet_at_the_park(host) -> None:
    LifeService.schedule_meeting_arrival(host, "the park")


def _arrive_at_the_park(host) -> None:
    host._transit = TransitState(phase=TransitPhase.IN_TRANSIT, origin="home", destination="the park")
    LifeService.advance_transit_phase(host, TransitPhase.ARRIVED)


KEPT = {8: ("working", "bakery")}

#: route -> (slots after it, judged at the world's 09:00; slots after it, judged at the host's 22:00)
OVERRIDES = {
    "cancel_work_today": (
        _skip_work,
        {**KEPT, 21: ("relaxing", "home"), 22: ("relaxing", "home"), 23: ("relaxing", "home")},
        {**KEPT, 21: ("working", "market"), 22: ("relaxing", "home"), 23: ("relaxing", "home")},
    ),
    "stay_at_current_location": (
        _stay_here,
        {**KEPT, 21: ("working", "bar"), 22: ("working", "bar"), 23: ("working", "bar")},
        {**KEPT, 21: ("working", "market"), 22: ("working", "bar"), 23: ("working", "bar")},
    ),
    "schedule_rendezvous via schedule_meeting_arrival": (
        _meet_at_the_park,
        {**KEPT, 21: ("meeting up", "the park"), 22: ("meeting up", "the park"), 23: ("working", "club")},
        {**KEPT, 21: ("working", "market"), 22: ("meeting up", "the park"), 23: ("meeting up", "the park")},
    ),
    "schedule_rendezvous via advance_transit_phase": (
        _arrive_at_the_park,
        {**KEPT, 21: ("meeting up", "the park"), 22: ("meeting up", "the park"), 23: ("working", "club")},
        {**KEPT, 21: ("working", "market"), 22: ("meeting up", "the park"), 23: ("meeting up", "the park")},
    ),
}


@pytest.mark.parametrize("route", list(OVERRIDES))
def test_a_service_on_an_injected_clock_overrides_the_slots_ahead_of_the_worlds_hour(route, monkeypatch, tmp_path):
    override, on_world_hour, _ = OVERRIDES[route]
    _freeze_host(monkeypatch, HOST_LATE, (PLANNER_MODULE, "aura_life.models"))
    svc = _service(tmp_path, "override", WorldEnvironment(now=lambda: WORLD_MORNING))
    svc._daily_planner._current_plan = _plan_for_overrides()

    override(svc)

    assert _slots(svc._daily_planner.current_plan) == on_world_hour


@pytest.mark.parametrize("route", list(OVERRIDES))
def test_a_service_with_no_injected_clock_overrides_from_the_wall_clock_hour(route, monkeypatch, tmp_path):
    override, _, on_host_hour = OVERRIDES[route]
    _freeze_host(monkeypatch, HOST_LATE, (PLANNER_MODULE, "aura_life.models", "aura_life.world.environment"))
    svc = _service(tmp_path, "override-wallclock")
    svc._daily_planner._current_plan = _plan_for_overrides()

    override(svc)

    assert _slots(svc._daily_planner.current_plan) == on_host_hour


class _WorldStandIn:
    def move_to(self, location):
        self.location = location


class _ScheduleStandIn(_PlanOnlyStandIn):
    """A duck-typed service for the override routes: still no ``_world_clock``."""

    def __init__(self, planner: DailyPlanner):
        super().__init__(planner)
        self._world = _WorldStandIn()
        self._persona_locations = {}
        self._transit = None

    def _save_transit(self):
        pass


@pytest.mark.parametrize("route", list(OVERRIDES))
def test_a_stand_in_with_no_world_clock_overrides_from_the_host_hour(route, monkeypatch):
    override, _, on_host_hour = OVERRIDES[route]
    _freeze_host(monkeypatch, HOST_LATE, (PLANNER_MODULE, "aura_life.models"))
    planner = DailyPlanner()
    planner._current_plan = _plan_for_overrides()
    stand_in = _ScheduleStandIn(planner)

    override(stand_in)

    assert _slots(planner.current_plan) == on_host_hour
    assert stand_in.saved == 1
