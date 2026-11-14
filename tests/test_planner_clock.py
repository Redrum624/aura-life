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

Task 28 (ruling T13-R1) moves the rest of the plan: every ``DailyPlan`` slot
lookup takes the instant it is asked about, the planner's dating, silent
revision and export take it too, and every caller inside aura-life passes her
local world time (``LifeService._local_world_now``) -- the routes above
included, through ``life_service._plan_instant``, which still gives a
stand-in no instant. Section 5 is the pin, at every hour of
``tests/conftest.py``'s ``host_hour``.
"""

import contextlib
import importlib
import inspect
import random
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from aura_life import hooks
from aura_life.life_service import LifeService
from aura_life.models import DailyPlan, PlannedSlot, TransitPhase, TransitState, Weather
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.settings import get_setting
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
# override judged; 08:00 is behind both and must never move. Staying put keeps
# the location of her current slot (``DailyPlan.get_current_slot``), read at
# the same instant since Task 28: the world's 08:00 slot, "bakery" -- the
# host's 22:00 slot, "bar", for a service with no injected clock or a
# stand-in with no world clock.

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
        {**KEPT, 21: ("working", "bakery"), 22: ("working", "bakery"), 23: ("working", "bakery")},
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


# ----------------------------------------------------------------------
# 5. Her day plan is read on the world clock, in her local time (Task 28)
# ----------------------------------------------------------------------
#
# Ruling T13-R1. ``host_hour`` (tests/conftest.py) freezes the host's clock at
# 02:00, 09:00, 15:00 and 22:00 on a day of 2026; her world is at 12:30 on a
# Monday of 2031. Each of those host hours has a different slot of her day
# than the world's 12:00, so every answer below that is the world's is one no
# host-clock read could give.

#: A world Monday, 12:30.
WORLD_NOON = datetime(2031, 3, 10, 12, 30)

#: Her day, (hour, activity, place): a shift behind her, a run behind her, her
#: noon hour, and an afternoon, an evening and a night still ahead.
DAY = (
    (8, "working", "workplace"),
    (10, "going for a run", "park"),
    (12, "sketching ideas", "cafe"),
    (13, "going for a walk", "street"),
    (18, "gym workout", "gym"),
    (21, "people watching", "rooftop"),
    (23, "getting ready for bed", "home"),
)

#: Her shift, Monday to Friday.
WEEKDAYS = {"employed": True, "work_days": [0, 1, 2, 3, 4], "shift_start_hour": 9, "shift_end_hour": 17}


def _day() -> DailyPlan:
    return DailyPlan(date=WORLD_NOON.strftime("%Y-%m-%d"), slots=[
        PlannedSlot(hour=hour, activity_name=activity, location=place, reason="routine")
        for hour, activity, place in DAY])


def _hours(slots) -> list:
    return [slot.hour for slot in slots]


def _generate(planner: DailyPlanner, now: datetime) -> DailyPlan:
    return planner.generate_daily_plan(goals=[], weather=Weather.SUNNY,
                                       available_activities=get_setting().resolved_activities(),
                                       recent_activity_names=[], work_schedule=WEEKDAYS, now=now)


def test_a_plans_slot_lookups_answer_for_the_instant_they_are_asked_about(host_hour):
    plan = _day()
    assert plan.get_current_slot(WORLD_NOON).hour == 12
    assert plan.get_next_slot(WORLD_NOON).hour == 13
    assert _hours(plan.get_remaining_slots(WORLD_NOON)) == [12, 13, 18, 21, 23]
    plan.get_slot_for_hour(13).completed = True
    assert plan.get_next_slot(WORLD_NOON).hour == 18
    assert _hours(plan.get_remaining_slots(WORLD_NOON)) == [12, 18, 21, 23]

    # Asked with no instant -- a host outside aura-life reading the plan
    # itself -- it answers for the host's wall clock, as it always did.
    host = host_hour.hour
    assert plan.get_current_slot() is next((s for s in reversed(plan.slots) if s.hour <= host), None)
    assert _hours(plan.get_remaining_slots()) == [s.hour for s in plan.slots if s.hour >= host and not s.completed]


def test_the_planner_plans_the_day_and_weekday_of_the_instant_it_is_given(host_hour):
    """The host's day is a Wednesday in 2026: her plan is dated, and her shift
    planned, by her world's Monday -- and not on its Saturday."""
    planner = DailyPlanner(occupation="baker", rng=random.Random(3))
    monday = _generate(planner, WORLD_NOON)
    assert monday.date == "2031-03-10"
    assert "working" in {slot.activity_name for slot in monday.slots}
    assert not planner.needs_new_plan(now=WORLD_NOON)
    assert planner.needs_new_plan()  # the host's day is another

    saturday = WORLD_NOON + timedelta(days=5)
    assert planner.needs_new_plan(now=saturday)
    weekend = _generate(planner, saturday)
    assert weekend.date == "2031-03-15"
    assert "working" not in {slot.activity_name for slot in weekend.slots}


def test_the_planner_revises_only_the_slots_ahead_of_the_instant_it_is_given(host_hour):
    """Too tired to keep her plans: every free slot still ahead of her hour
    becomes rest; her own hour, the ones behind her and the anchors stay."""
    planner = DailyPlanner(rng=random.Random(3))
    planner._current_plan = _day()
    planner.revise_upcoming(Weather.SUNNY, energy_level=0.01, now=WORLD_NOON)
    after = {slot.hour: slot.activity_name for slot in planner.current_plan.slots}
    kept = {8: "working", 10: "going for a run", 12: "sketching ideas", 23: "getting ready for bed"}
    assert {hour: after[hour] for hour in kept} == kept
    assert {after[hour] for hour in (13, 18, 21)} <= get_setting().names_tagged("restful"), after


def test_the_planner_exports_the_slot_of_the_instant_it_is_given(host_hour):
    planner = DailyPlanner()
    planner._current_plan = _day()
    planner.mark_slot_completed(10, "going for a run")
    assert planner.export_state(now=WORLD_NOON) == {
        "current_slot": {"activity": "sketching ideas", "location": "cafe", "reason": "routine"},
        "next_slot": {"activity": "going for a walk", "hour": 13},
        "completed_today": 1,
        "remaining": 4,
    }


def test_staying_put_takes_the_place_of_the_slot_of_the_instant_it_is_given(host_hour):
    planner = DailyPlanner()
    planner._current_plan = _day()
    planner.stay_at_current_location(now=WORLD_NOON)
    assert [(slot.hour, slot.location) for slot in planner.current_plan.slots] == [
        (8, "workplace"), (10, "park"), (12, "cafe"), (13, "cafe"), (18, "cafe"), (21, "cafe"), (23, "cafe")]


def test_joining_takes_the_hour_she_is_in_and_leaves_the_rest_of_her_day(host_hour):
    """``DailyPlanner.join_activity``: the slot of her hour becomes the joint
    activity where it is, not done yet (an hour she has started too), and
    says why; an hour her plan left empty gains a slot; every other hour is
    as she planned it; with no plan there is nothing to rewrite."""
    planner = DailyPlanner()
    planner._current_plan = _day()
    planner.mark_slot_completed(12, "sketching ideas")
    planner.join_activity("cooking a meal", "home", reason="with Lina", now=WORLD_NOON)
    slot = planner.get_planned_activity(12)
    assert (slot.activity_name, slot.location, slot.reason, slot.completed, slot.actual_activity) == (
        "cooking a meal", "home", "with Lina", False, None)

    planner.join_activity("going for a run", "park", reason="with Roberta", now=WORLD_NOON.replace(hour=15))
    assert _hours(planner.current_plan.slots) == [8, 10, 12, 13, 15, 18, 21, 23]
    added = planner.get_planned_activity(15)
    assert (added.activity_name, added.location, added.reason, added.completed) == (
        "going for a run", "park", "with Roberta", False)
    assert [(s.hour, s.activity_name, s.location) for s in planner.current_plan.slots if s.hour not in (12, 15)] == [
        (hour, activity, place) for hour, activity, place in DAY if hour != 12]

    alone = DailyPlanner()
    alone.join_activity("cooking a meal", "home", reason="with Lina", now=WORLD_NOON)
    assert alone.current_plan is None


def _day_service(tmp_path, pid: str) -> LifeService:
    """A persona of a world whose clock stands at :data:`WORLD_NOON`, her day
    planned as :data:`DAY`."""
    svc = _service(tmp_path, pid, WorldEnvironment(now=lambda: WORLD_NOON))
    svc._daily_planner._current_plan = _day()
    return svc


def test_her_status_context_and_export_read_her_plan_at_the_worlds_hour(host_hour, tmp_path):
    """The acceptance: get_status(), get_life_context(), the state export and
    the location sync never read the host's hour for her plan."""
    svc = _day_service(tmp_path, "noon")
    assert svc.get_current_location() == "cafe"
    assert svc._current_location == "cafe"
    assert svc.current_activity_name == "sketching ideas"
    status = svc.get_status()
    assert (status["current_activity"], status["location"]) == ("Sketching ideas", "cafe")
    context = svc.get_life_context()
    assert "- Right now: sketching ideas (at the cafe)" in context
    assert "- Coming up: going for a walk" in context
    assert "- Later: gym workout, people watching" in context
    assert svc.export_inner_state()["drive"]["plan"] == {
        "current_slot": {"activity": "sketching ideas", "location": "cafe", "reason": "routine"},
        "next_slot": {"activity": "going for a walk", "hour": 13},
        "completed_today": 0,
        "remaining": 4,
    }


@pytest.mark.parametrize("phase, where", [(TransitPhase.PREPARING, "home"), (TransitPhase.IN_TRANSIT, "in transit")])
def test_on_the_way_somewhere_reading_her_state_never_moves_her(phase, where, host_hour, tmp_path):
    """The location sync (get_current_location) puts her at her plan's place
    for the hour -- never while a transit is getting ready or under way: she
    is where she is (still at the origin, or on the way), whatever
    get_status(), the visual check or a resumed plan read. Once the transit
    is over, her plan's place again (Task 28 fix round 1)."""
    svc = _day_service(tmp_path, f"leaving-{phase.value}")
    svc._current_location = where
    svc._transit = TransitState(phase=phase, origin="home", destination="park")
    assert svc.get_current_location() == where
    assert svc.get_status()["location"] == where
    svc._check_visual_transition()
    svc.resume_planned_activity()
    assert svc._current_location == where

    svc._transit = None
    assert svc.get_current_location() == "cafe"
    assert svc._current_location == "cafe"


def test_her_activity_tick_follows_the_slot_of_the_worlds_hour(host_hour, tmp_path):
    """No persona clock of the host's is asked: the slot she follows, the one
    she marks done and the one her location is synced to are the world's."""
    svc = _day_service(tmp_path, "tick")
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "sketching ideas"
    assert svc._current_location == "cafe"
    assert [slot.hour for slot in svc._daily_planner.current_plan.slots if slot.completed] == [12]


def test_her_plan_tick_plans_once_a_world_day(host_hour, tmp_path):
    """A new plan for the world's day; the same day, no new plan; the next
    world day, a new one -- while the host's day never moves."""
    clock = {"now": WORLD_NOON}
    svc = _service(tmp_path, "days", WorldEnvironment(now=lambda: clock["now"]))
    svc._on_plan_tick()
    first = svc._daily_planner.current_plan
    assert first.date == "2031-03-10"
    svc._on_plan_tick()
    assert svc._daily_planner.current_plan is first
    clock["now"] = WORLD_NOON + timedelta(days=1)
    svc._on_plan_tick()
    assert svc._daily_planner.current_plan.date == "2031-03-11"


#: Her local time where she lives, seven hours ahead of the world's clock.
LOCAL_EVENING = datetime(2031, 3, 10, 19, 30, tzinfo=timezone(timedelta(hours=7)))


@pytest.fixture
def abroad():
    """The host's persona clock (``persona_now``) seven hours ahead of the
    world's in the zone asked for: 19:30 where she lives (a persona given a
    timezone) while the world's clock reads 12:30. The previous provider is
    put back afterwards."""
    saved = hooks.provider_for("persona_now")
    hooks.configure(persona_now=lambda timezone=None: LOCAL_EVENING if timezone else WORLD_NOON)
    yield
    hooks.configure(persona_now=saved)


def _abroad(svc: LifeService) -> LifeService:
    """``svc`` living where it is :data:`LOCAL_EVENING` (with ``abroad``)."""
    svc._place_location.current_timezone = "Asia/Bangkok"
    assert svc._local_world_now() == LOCAL_EVENING
    return svc


def test_a_persona_with_a_timezone_reads_her_plan_at_her_own_hour(host_hour, abroad, tmp_path):
    """Her plan's hours are her local hours: with a timezone, her local world
    time is the host's persona clock in that zone (``persona_now``) -- 19:30
    there while the world's own clock reads 12:30 -- and her plan is read at
    it: the 18:00 slot, where neither the world's hour nor any host hour
    would land."""
    svc = _abroad(_day_service(tmp_path, "abroad"))
    assert svc.get_current_location() == "gym"
    assert svc.get_status()["current_activity"] == "Gym workout"
    assert svc.export_inner_state()["drive"]["plan"]["next_slot"] == {"activity": "people watching", "hour": 21}
    assert "- Right now: gym workout (at the gym)" in svc.get_life_context()


#: Her shifts, (hour, activity, place), around her local 19:00. Judged from
#: her hour, each route below rewrites other slots than it would from the
#: world's 12:00 or from any ``host_hour``.
SHIFTS = ((8, "working", "workplace"), (13, "working", "cafe"), (18, "working", "gym"),
          (20, "working", "bar"), (22, "working", "club"))
SHIFT_SLOTS = {hour: (activity, place) for hour, activity, place in SHIFTS}


def _plan_two_things(svc: LifeService) -> None:
    svc.add_conversation_plan("15:00 sketching ideas")   # passed at her 19:00
    svc.add_conversation_plan("21:00 reading @ library")  # still ahead of it


def _arrive_at_the_beach(svc: LifeService) -> None:
    svc._transit = TransitState(phase=TransitPhase.IN_TRANSIT, origin="home", destination="beach")
    svc.advance_transit_phase(TransitPhase.ARRIVED)


#: route -> (what it does, her shifts after it, judged from her 19:00)
LOCAL_HOUR_ROUTES = {
    "skip work": (lambda svc: svc.apply_schedule_override("skip work"),
                  {**SHIFT_SLOTS, 20: ("relaxing", "home"), 22: ("relaxing", "home")}),
    "stay here": (lambda svc: svc.apply_schedule_override("stay here"),
                  {**SHIFT_SLOTS, 20: ("working", "gym"), 22: ("working", "gym")}),
    "go to": (lambda svc: svc.apply_schedule_override("go to library"),
              {**SHIFT_SLOTS, 18: ("working", "library"), 20: ("working", "library")}),
    "a meeting arrival": (lambda svc: svc.schedule_meeting_arrival("park"),
                          {**SHIFT_SLOTS, 20: ("meeting up", "park"), 22: ("meeting up", "park")}),
    "a conversation plan": (_plan_two_things, {**SHIFT_SLOTS, 21: ("reading", "library")}),
    "a transit arrival": (_arrive_at_the_beach,
                          {**SHIFT_SLOTS, 20: ("meeting up", "beach"), 22: ("meeting up", "beach")}),
}


@pytest.mark.parametrize("route", list(LOCAL_HOUR_ROUTES))
def test_the_schedule_routes_rewrite_her_day_from_her_own_local_hour(route, host_hour, abroad, tmp_path):
    """The four routes a host may bind to a stand-in -- apply_schedule_override
    ("skip work", "stay here", "go to ..."), schedule_meeting_arrival,
    add_conversation_plan and advance_transit_phase -- judge her plan at her
    local world time (``_plan_instant``): 19:30 where she lives, while the
    world's clock reads 12:30 and the host's is at a ``host_hour``. The slots
    each rewrites are the ones from her 19:00 on; "stay here" keeps her 18:00
    slot's place; a plan for 15:00 has passed for her, one for 21:00 has not."""
    override, after = LOCAL_HOUR_ROUTES[route]
    svc = _abroad(_service(tmp_path, "shifts", WorldEnvironment(now=lambda: WORLD_NOON)))
    svc._daily_planner._current_plan = DailyPlan(date="2031-03-10", slots=[
        PlannedSlot(hour=hour, activity_name=activity, location=place, reason="routine")
        for hour, activity, place in SHIFTS])

    override(svc)

    assert _slots(svc._daily_planner.current_plan) == after


#: Every plan read that takes an instant.
PLAN_READS = {
    DailyPlan: ("get_current_slot", "get_next_slot", "get_remaining_slots"),
    DailyPlanner: ("needs_new_plan", "generate_daily_plan", "revise_upcoming", "export_state",
                   "cancel_work_today", "override_current_location", "stay_at_current_location",
                   "schedule_rendezvous", "set_planned_activity", "join_activity"),
}
#: Every plan read that takes her hour instead.
HOUR_READS = ("get_planned_activity", "mark_slot_completed")


class _Triggers:
    """A follow-up store that takes every trigger (``LifeService``'s
    ``follow_up_provider``), so the energy tick evaluates her life triggers."""

    def create_trigger(self, *args, **kwargs):
        return None


def _spy_on_the_plan(monkeypatch) -> list:
    """Every plan read, as (method, the instant or hour it was asked at)."""
    seen = []
    for cls, names in PLAN_READS.items():
        for name in names:
            original = getattr(cls, name)

            def spy(*args, _original=original, _name=name, **kwargs):
                bound = inspect.signature(_original).bind(*args, **kwargs)
                seen.append((_name, bound.arguments.get("now")))
                return _original(*args, **kwargs)

            monkeypatch.setattr(cls, name, spy)
    for name in HOUR_READS:
        original = getattr(DailyPlanner, name)

        def hour_spy(self, hour, *args, _original=original, _name=name, **kwargs):
            seen.append((_name, hour))
            return _original(self, hour, *args, **kwargs)

        monkeypatch.setattr(DailyPlanner, name, hour_spy)
    return seen


def test_no_plan_read_in_the_library_falls_back_to_the_host_clock(monkeypatch, tmp_path):
    """Every route into her plan -- the ticks, the status, the context, the
    exports, the location sync, the schedule overrides, a conversation plan,
    an arrival, a catch-up and a reload -- asks it at her local world time
    (here the world's clock: she has no timezone), never with no instant."""
    seen = _spy_on_the_plan(monkeypatch)
    svc = LifeService(db_path=str(tmp_path / "spied.db"), persona_id="spied",
                      world_environment=WorldEnvironment(now=lambda: WORLD_NOON), occupation="baker",
                      definition=PersonalityDefinition(core_traits=["curious"], occupation="baker", home_type="studio"),
                      rng=random.Random(5), follow_up_provider=lambda persona_id: _Triggers())
    svc._on_plan_tick()  # a new plan
    svc._on_plan_tick()  # the same day: a silent revision
    svc._daily_planner._current_plan = _day()
    svc._on_energy_tick()
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._on_activity_tick()
    svc.get_status()
    svc.get_life_context()
    svc.export_inner_state()
    svc.export_outer_state()
    svc.get_current_location()
    assert svc.current_activity_name
    svc.resume_planned_activity()
    svc._next_activity_info()
    svc.apply_schedule_override("go to library")
    svc.apply_schedule_override("stay here")
    svc.apply_schedule_override("skip work")
    svc.schedule_meeting_arrival("park")
    svc.add_conversation_plan("23:00 reading")
    svc._transit = TransitState(phase=TransitPhase.IN_TRANSIT, origin="park", destination="cafe")
    svc.advance_transit_phase(TransitPhase.ARRIVED)
    svc.catch_up_from_downtime(3)
    with contextlib.closing(sqlite3.connect(svc._db_path)) as conn:
        conn.execute("DELETE FROM life_world_state")  # her place is then her plan's (_load_world)
        conn.commit()
    svc._load_state()

    reached = {name for name, _ in seen}
    assert reached >= {name for names in PLAN_READS.values() for name in names} - {"join_activity"}
    assert reached >= set(HOUR_READS)
    assert [(name, asked) for name, asked in seen
            if asked != (WORLD_NOON.hour if name in HOUR_READS else WORLD_NOON)] == []
