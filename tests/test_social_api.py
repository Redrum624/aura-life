"""The social circle and the plans she makes with it are public, persisted API.

``_on_activity_tick`` looked an NPC up with ``next(n for n in self._social._npcs
if n.name == ...)`` -- but ``_npcs`` is a ``Dict[str, NPC]``, so iterating it
yields names and the whole tick died on ``'str' object has no attribute 'name'``
after every social event. Beyond the crash, a host had no way to read who is in
her circle or to commit her to a plan with someone, so these tests pin the read
API (``get_social_circle``), the write/read pair for commitments
(``add_social_plan`` / ``get_upcoming_social_plans``) and the ``export_outer_state``
keys that carry both.
"""

import importlib
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from aura_life import hooks
from aura_life.life_service import LifeService
from aura_life.models import SocialEvent, Weather
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

#: The world, years from any host clock, at 09:00.
WORLD_NOW = datetime(2031, 3, 10, 9, 0)

CIRCLE = [
    {"name": "Maya", "relationship": "best friend", "shared_interests": "climbing, ramen"},
    {"name": "Leo", "relationship": "coworker", "shared_interests": "chess"},
    {"name": "Nora", "relationship": "sister", "shared_interests": ""},
]


#: One mutable instant: the world's clock and, frozen into the planner, the host's.
#: The planner dates and judges its daily plan on the host clock (it is not on the
#: world clock yet), so the tests pin both to the same moment.
_CLOCK = {"now": WORLD_NOW}


@pytest.fixture(autouse=True)
def _world_and_host_agree(monkeypatch):
    _CLOCK["now"] = WORLD_NOW

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return _CLOCK["now"]

    monkeypatch.setattr(importlib.import_module("aura_life.planner.daily_planner"), "datetime", Frozen)


def _service(tmp_path, pid="social", circle=CIRCLE, now=WORLD_NOW) -> LifeService:
    clock = _CLOCK
    clock["now"] = now
    svc = LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=WorldEnvironment(now=lambda: clock["now"]),
        occupation="baker",
        definition=PersonalityDefinition(core_traits=["curious"], occupation="baker", home_type="studio"),
        rng=random.Random(5),
        social_circle=circle,
    )
    svc._test_clock = clock
    return svc


# ----------------------------------------------------------------------
# 1. The tick no longer dies on a social event
# ----------------------------------------------------------------------

def test_an_activity_tick_with_a_social_event_completes(tmp_path):
    svc = _service(tmp_path, "tick")
    svc._on_plan_tick()
    event = SocialEvent(npc_name="Maya", event_type="text_received", description="Maya texted her")
    svc._social.tick = lambda *args, **kw: event
    seen = []
    svc._identity.get_npc_value_alignment = lambda npc: seen.append(npc.name) or 1.0
    before = svc._social.arcs["Maya"].closeness

    svc._on_activity_tick()  # raised AttributeError: 'str' object has no attribute 'name'

    assert seen == ["Maya"]
    # +0.01 for the interaction, +0.01 for the value alignment of the NPC
    assert svc._social.arcs["Maya"].closeness == pytest.approx(before + 0.02)


# ----------------------------------------------------------------------
# 2. get_social_circle
# ----------------------------------------------------------------------

def test_the_social_circle_is_plain_dicts_ordered_by_closeness(tmp_path):
    svc = _service(tmp_path)
    svc._social.arcs["Leo"].closeness = 0.9
    svc._social.arcs["Leo"].trend = "deepening"

    circle = svc.get_social_circle()

    assert circle[0] == {"name": "Leo", "relationship": "coworker", "closeness": 0.9, "trend": "deepening"}
    assert all(type(p) is dict and set(p) == {"name", "relationship", "closeness", "trend"} for p in circle)
    closeness = [p["closeness"] for p in circle]
    assert closeness == sorted(closeness, reverse=True)
    assert {p["name"] for p in circle} == {"Maya", "Leo", "Nora"}


def test_a_person_with_no_arc_has_no_closeness_or_trend(tmp_path):
    svc = _service(tmp_path)
    del svc._social.arcs["Nora"]

    circle = svc.get_social_circle()

    assert circle[-1] == {"name": "Nora", "relationship": "sister", "closeness": None, "trend": None}


def test_an_empty_circle_is_an_empty_list(tmp_path):
    assert _service(tmp_path, "nobody", circle=[]).get_social_circle() == []


# ----------------------------------------------------------------------
# 3. add_social_plan / get_upcoming_social_plans
# ----------------------------------------------------------------------

def test_a_plan_with_a_friend_fills_the_daily_plan_slot_and_reads_back(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    at = WORLD_NOW.replace(hour=19)

    svc.add_social_plan(["Maya"], "climbing", at, 90)

    plan = svc._daily_planner.current_plan
    assert plan.get_slot_for_hour(19).activity_name == "climbing"
    assert plan.get_slot_for_hour(20).activity_name == "climbing"
    assert svc.get_upcoming_social_plans(24) == [
        {"people": ["Maya"], "what": "climbing", "at": at, "duration_min": 90}
    ]
    assert svc.get_upcoming_social_plans(5) == []  # 19:00 is ten hours away


def test_names_match_case_insensitively_and_come_back_canonical(tmp_path):
    svc = _service(tmp_path)
    svc.add_social_plan(["maya", "LEO"], "ramen", WORLD_NOW.replace(hour=12), 60)

    assert svc.get_upcoming_social_plans(24)[0]["people"] == ["Maya", "Leo"]


@pytest.mark.parametrize("people", [["Stranger"], ["Maya", "Stranger"], []])
def test_unknown_or_missing_people_are_rejected(tmp_path, people):
    svc = _service(tmp_path)
    svc._on_plan_tick()

    with pytest.raises(ValueError):
        svc.add_social_plan(people, "climbing", WORLD_NOW.replace(hour=19), 60)

    assert svc.get_upcoming_social_plans(48) == []
    assert svc._daily_planner.current_plan.get_slot_for_hour(19).activity_name != "climbing"


def test_a_plan_is_judged_on_the_world_clock_not_the_host(tmp_path):
    svc = _service(tmp_path)

    with pytest.raises(ValueError):
        svc.add_social_plan(["Maya"], "breakfast", WORLD_NOW.replace(hour=7), 60)  # the world is at 09:00
    svc.add_social_plan(["Maya"], "brunch", WORLD_NOW.replace(hour=9, minute=30), 60)

    assert [p["what"] for p in svc.get_upcoming_social_plans(1)] == ["brunch"]


def test_a_plan_under_way_is_still_upcoming_until_it_ends(tmp_path):
    svc = _service(tmp_path)
    svc.add_social_plan(["Maya"], "brunch", WORLD_NOW.replace(minute=30), 60)

    svc._test_clock["now"] = WORLD_NOW + timedelta(hours=1)  # 10:00, half way through
    assert [p["what"] for p in svc.get_upcoming_social_plans(1)] == ["brunch"]
    svc._test_clock["now"] = WORLD_NOW + timedelta(hours=2)  # 11:00, over
    assert svc.get_upcoming_social_plans(24) == []


def test_a_plan_on_another_day_is_kept_but_takes_no_slot_today(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    tomorrow = (WORLD_NOW + timedelta(days=1)).replace(hour=19)

    svc.add_social_plan(["Maya"], "climbing", tomorrow, 60)

    assert svc._daily_planner.current_plan.get_slot_for_hour(19).activity_name != "climbing"
    assert svc.get_upcoming_social_plans(48)[0]["at"] == tomorrow
    assert svc.get_upcoming_social_plans(12) == []


@pytest.mark.parametrize("what,duration", [("", 60), ("   ", 60), ("x", 0), ("x", -5)])
def test_a_plan_needs_a_thing_to_do_and_a_duration(tmp_path, what, duration):
    with pytest.raises(ValueError):
        _service(tmp_path).add_social_plan(["Maya"], what, WORLD_NOW.replace(hour=19), duration)


def test_plans_survive_a_save_and_reload(tmp_path):
    svc = _service(tmp_path, "persist")
    svc._on_plan_tick()
    at = WORLD_NOW.replace(hour=19)
    svc.add_social_plan(["Maya", "Leo"], "climbing", at, 90)

    reloaded = _service(tmp_path, "persist")
    reloaded._load_state()  # what start() does, without starting the scheduler

    assert reloaded.get_upcoming_social_plans(24) == [
        {"people": ["Maya", "Leo"], "what": "climbing", "at": at, "duration_min": 90}
    ]


def test_plans_are_not_overdue_debts_and_outlive_the_obligation_cap(tmp_path):
    svc = _service(tmp_path)
    svc.add_social_plan(["Maya"], "brunch", WORLD_NOW.replace(hour=10), 60)
    for i in range(8):
        svc._social.add_obligation(f"favour {i}", "Leo", urgency=0.5)

    assert any(o.description == "brunch" for o in svc._social.obligations)
    # tick_obligations judges on the host clock; the plan sits years in the past of it
    svc._social.tick_obligations()
    assert "brunch" not in svc._social.get_overdue_obligations()


# ----------------------------------------------------------------------
# 4. export_state
# ----------------------------------------------------------------------

def test_export_state_carries_the_top_five_people_and_the_next_day_of_plans(tmp_path):
    circle = [{"name": f"P{i}", "relationship": "friend"} for i in range(7)]
    svc = _service(tmp_path, "export", circle=circle)
    for i in range(7):
        svc._social.arcs[f"P{i}"].closeness = 0.1 * (i + 1)
    svc.add_social_plan(["P6"], "tea", WORLD_NOW.replace(hour=15), 60)
    svc.add_social_plan(["P5"], "later", WORLD_NOW + timedelta(days=3), 60)

    social = svc.export_outer_state()["social"]

    assert [p["name"] for p in social["people"]] == ["P6", "P5", "P4", "P3", "P2"]
    assert set(social["people"][0]) == {"name", "rel", "close", "trend"}
    assert social["people"][0]["close"] == 0.7
    assert social["plans"] == [{"who": "P6", "what": "tea", "at": "2031-03-10T15:00", "min": 60}]
    for key in ("recent_events", "npc_count", "social_battery", "arcs", "obligations", "conflicts"):
        assert key in social


def test_export_state_social_is_json_primitives(tmp_path):
    svc = _service(tmp_path, "json")
    svc.add_social_plan(["Maya"], "tea", WORLD_NOW.replace(hour=15), 60)

    json.dumps(svc.export_outer_state()["social"])


# ----------------------------------------------------------------------
# 5. Plans are re-applied when the daily plan is (re)generated
# ----------------------------------------------------------------------

def _next_day(svc):
    _CLOCK["now"] = (WORLD_NOW + timedelta(days=1)).replace(hour=0, minute=5)
    svc._on_plan_tick()  # the planner sees a new date and generates the day's plan


def test_a_plan_for_tomorrow_gets_its_slot_when_tomorrows_plan_is_generated(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    tomorrow = (WORLD_NOW + timedelta(days=1)).replace(hour=19)
    svc.add_social_plan(["Maya"], "climbing", tomorrow, 60)

    _next_day(svc)

    slot = svc._daily_planner.current_plan.get_slot_for_hour(19)
    assert slot is not None and slot.activity_name == "climbing"


def test_a_plan_added_before_any_daily_plan_exists_is_applied_when_one_is_made(tmp_path):
    svc = _service(tmp_path)
    assert svc._daily_planner.current_plan is None
    svc.add_social_plan(["Maya"], "climbing", WORLD_NOW.replace(hour=19), 60)

    svc._on_plan_tick()

    assert svc._daily_planner.current_plan.get_slot_for_hour(19).activity_name == "climbing"


def test_a_plan_across_midnight_puts_its_after_midnight_hours_in_the_next_days_plan(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    svc.add_social_plan(["Maya"], "movie night", WORLD_NOW.replace(hour=23), 120)

    assert svc._daily_planner.current_plan.get_slot_for_hour(23).activity_name == "movie night"
    _next_day(svc)

    assert svc._daily_planner.current_plan.get_slot_for_hour(0).activity_name == "movie night"


def test_reapplying_a_plan_does_not_reopen_a_finished_slot(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    svc.add_social_plan(["Maya"], "climbing", WORLD_NOW.replace(hour=10), 60)
    svc._daily_planner.current_plan.get_slot_for_hour(10).completed = True

    svc._on_plan_tick()

    assert svc._daily_planner.current_plan.get_slot_for_hour(10).completed is True


def test_a_plan_is_placed_by_the_daily_plans_own_date_not_the_world_date(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    svc._daily_planner.current_plan.date = "2031-03-11"  # the planner is a day ahead of the world
    svc.add_social_plan(["Maya"], "climbing", WORLD_NOW.replace(hour=19), 60)

    assert svc._daily_planner.current_plan.get_slot_for_hour(19).activity_name != "climbing"
    svc.add_social_plan(["Leo"], "chess", (WORLD_NOW + timedelta(days=1)).replace(hour=20), 60)
    assert svc._daily_planner.current_plan.get_slot_for_hour(20).activity_name == "chess"


# ----------------------------------------------------------------------
# 6. Pruning, and plans versus debts sharing a description
# ----------------------------------------------------------------------

def test_a_plan_is_forgotten_a_day_after_it_ends_on_the_world_clock(tmp_path):
    svc = _service(tmp_path)
    svc.add_social_plan(["Maya"], "brunch", WORLD_NOW.replace(hour=10), 60)  # ends 11:00

    _CLOCK["now"] = WORLD_NOW.replace(hour=10) + timedelta(hours=1 + 23)  # 23 h after it ended
    svc._on_energy_tick()
    assert any(o.duration_min for o in svc._social.obligations)

    _CLOCK["now"] = WORLD_NOW.replace(hour=10) + timedelta(hours=1 + 25)  # 25 h after
    svc._on_energy_tick()
    assert not any(o.duration_min for o in svc._social.obligations)


def test_a_plan_and_a_debt_with_the_same_words_do_not_collide(tmp_path):
    svc = _service(tmp_path)
    svc.add_social_plan(["Maya"], "brunch", WORLD_NOW.replace(hour=10), 60)

    svc._social.add_obligation("brunch", "Leo")  # not blocked by the plan
    assert [o.person for o in svc._social.obligations if o.description == "brunch"] == ["Maya", "Leo"]

    svc._social.fulfill_obligation("brunch")  # clears the debt only
    assert [o.person for o in svc._social.obligations] == ["Maya"]
    assert svc.get_upcoming_social_plans(24)[0]["what"] == "brunch"


def test_an_overlapping_plan_is_rejected_and_the_same_plan_again_is_a_no_op(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    svc.add_social_plan(["Maya"], "climbing", WORLD_NOW.replace(hour=19), 90)
    with pytest.raises(ValueError):
        svc.add_social_plan(["Leo"], "ramen", WORLD_NOW.replace(hour=20), 60)  # 20:00 is inside 19:00-20:30
    svc.add_social_plan(["Maya"], "climbing", WORLD_NOW.replace(hour=19), 90)  # identical: kept once, no error
    assert len(svc.get_upcoming_social_plans(24)) == 1
    svc.add_social_plan(["Leo"], "ramen", WORLD_NOW.replace(hour=20, minute=30), 60)  # starts as climbing ends
    assert len(svc.get_upcoming_social_plans(24)) == 2


def test_a_low_mood_or_low_energy_revision_keeps_a_promise_to_people(tmp_path):
    svc = _service(tmp_path)
    svc._on_plan_tick()
    svc.add_social_plan(["Maya"], "climbing", WORLD_NOW.replace(hour=19), 60)
    planner = svc._daily_planner
    planner.revise_upcoming(energy_level=0.1, mood="sad", mood_intensity=0.9, weather=Weather.RAINY)
    assert planner.current_plan.get_slot_for_hour(19).activity_name == "climbing"


# ----------------------------------------------------------------------
# 7. On the branch: the plan's day and hour are her local world ones (Task 31)
# ----------------------------------------------------------------------

#: The host frozen late in the evening, years from the world (tests/test_planner_clock.py's HOST_LATE).
HOST_LATE = datetime(2026, 9, 16, 22, 45)


def _freeze_host_late(monkeypatch):
    """The host's wall clock at :data:`HOST_LATE` in the planner, the service and the social system (overrides the
    autouse fixture, which keeps the host and the world together)."""
    class HostLate(datetime):
        @classmethod
        def now(cls, tz=None):
            return HOST_LATE if tz is None else HOST_LATE.replace(tzinfo=tz)

    for name in ("aura_life.planner.daily_planner", "aura_life.life_service", "aura_life.social.social_system"):
        monkeypatch.setattr(importlib.import_module(name), "datetime", HostLate)


def test_a_plan_lands_on_her_world_day_and_hour_when_the_host_clock_disagrees(tmp_path, monkeypatch):
    # 0.4.0 dated the daily plan on the host's day, so with the host at 22:45 on 2026-09-16 a plan for the world's
    # 21:00 on 2031-03-10 landed nowhere; on the branch every plan is made on her local world time (_plan_instant).
    _freeze_host_late(monkeypatch)
    svc = _service(tmp_path, "hostlate")   # the world at 09:00 on 2031-03-10
    svc._on_plan_tick()
    assert svc._daily_planner.current_plan.date == "2031-03-10"

    svc.add_social_plan(["Maya"], "having dinner", WORLD_NOW.replace(hour=21), 60)

    slot = svc._daily_planner.current_plan.get_slot_for_hour(21)
    assert (slot.activity_name, slot.reason) == ("having dinner", "plan with Maya")
    assert [p["at"] for p in svc.get_upcoming_social_plans(24)] == [WORLD_NOW.replace(hour=21)]


#: tests/test_planner_clock.py's ``abroad`` convention (its WORLD_NOON, LOCAL_EVENING, ``abroad`` and ``_abroad`` lines,
#: copied): the world's clock at 12:30, her local time 19:30, seven hours ahead. Her local instant is held in a dict
#: here so a test can move it with the world's clock. Her zone is +03:00, not +07:00 (fix round 1): the world's clock
#: here is a host's own wall clock at UTC-4, not UTC, so her lead on it (7 h) is not her zone's UTC offset (3 h), and
#: only a shift by the lead passes.
WORLD_NOON = datetime(2031, 3, 10, 12, 30)
HER_ZONE = timezone(timedelta(hours=3))
LOCAL_EVENING = datetime(2031, 3, 10, 19, 30, tzinfo=HER_ZONE)
_LOCAL = {"now": LOCAL_EVENING}


@pytest.fixture
def abroad():
    """The host's persona clock (``persona_now``) seven hours ahead of the world's in the zone asked for (her local
    time, a persona given a timezone) while the world's clock reads 12:30. The previous provider is put back."""
    _LOCAL["now"] = LOCAL_EVENING
    saved = hooks.provider_for("persona_now")
    hooks.configure(persona_now=lambda timezone=None: _LOCAL["now"] if timezone else WORLD_NOON)
    yield
    hooks.configure(persona_now=saved)


def _abroad(svc: LifeService) -> LifeService:
    """``svc`` living where it is :data:`LOCAL_EVENING` (with ``abroad``)."""
    svc._place_location.current_timezone = "Europe/Moscow"   # +03:00 all year
    assert svc._local_world_now() == LOCAL_EVENING
    return svc


def test_a_plan_for_a_persona_with_a_timezone_lands_on_her_own_hour(tmp_path, abroad):
    # ``at`` is a naive instant on the world clock (add_social_plan; aura converts her clock to the world's before
    # the call): her plan carries it at HER local hour of that instant (ruling T31-R3).
    svc = _abroad(_service(tmp_path, "abroad", now=WORLD_NOON))
    svc._on_plan_tick()
    assert svc._daily_planner.current_plan.date == "2031-03-10"

    svc.add_social_plan(["Maya"], "having dinner", datetime(2031, 3, 10, 15, 0), 60)     # her 22:00 today
    svc.add_social_plan(["Leo"], "watching a film", datetime(2031, 3, 10, 21, 0), 60)    # her 04:00 tomorrow

    def hours(plan, what, who):
        return [s.hour for s in plan.slots if s.activity_name == what and s.reason == "plan with " + who]

    plan = svc._daily_planner.current_plan
    assert hours(plan, "having dinner", "Maya") == [22]      # not her hour 15, already past for her
    assert hours(plan, "watching a film", "Leo") == []       # not her hour 21 today: it is her tomorrow
    # The stored instants and the contract are the world's.
    assert [(p["what"], p["at"]) for p in svc.get_upcoming_social_plans(24)] == [
        ("having dinner", datetime(2031, 3, 10, 15, 0)), ("watching a film", datetime(2031, 3, 10, 21, 0))]

    # Her next local day (her 01:00 on 2031-03-11, the world's 18:00): its plan carries the film on her hour 4.
    svc._test_clock["now"] = datetime(2031, 3, 10, 18, 0)
    _LOCAL["now"] = datetime(2031, 3, 11, 1, 0, tzinfo=HER_ZONE)
    svc._on_plan_tick()
    plan = svc._daily_planner.current_plan
    assert plan.date == "2031-03-11"
    assert hours(plan, "watching a film", "Leo") == [4]
    assert hours(plan, "having dinner", "Maya") == []


# ----------------------------------------------------------------------
# 8. On the branch: no whim, pressing need or housemate takes a promise to people (Task 31, fix round 1)
# ----------------------------------------------------------------------
# 0.4.0 keeps a social plan "whatever her mood or the weather" and 0.5.0 follows its slot unless she is too tired;
# the branch's free-time predicate (DailyPlanner.is_free_time) let her whim, her hunger and a housemate's joint
# activity take it. Each test has its control: the same slot as an ordinary free-time one IS taken.

def test_a_whim_never_drops_a_plan_with_people():
    from aura_life.personas.parameters import PersonaParameters
    from aura_life.planner.daily_planner import DailyPlanner, PlannedSlot

    planner = DailyPlanner(rng=random.Random(11), params=PersonaParameters(impulsivity=1.0))
    promise = PlannedSlot(hour=19, activity_name="climbing", reason="plan with Maya")
    whim = PlannedSlot(hour=19, activity_name="climbing", reason="routine")
    assert planner.is_free_time(whim) and sum(planner.abandons_slot(whim) for _ in range(1000)) > 0   # control
    assert not planner.is_free_time(promise)
    assert not any(planner.abandons_slot(promise) for _ in range(1000))


def _seven_pm(tmp_path, pid, what, reason=None) -> LifeService:
    """A service with a plan with Maya for ``what`` at the world's 19:00 (its slot's reason replaced by ``reason``
    when given, for a control), the world's clock at 19:05."""
    svc = _service(tmp_path, pid)
    svc._on_plan_tick()
    svc.add_social_plan(["Maya"], what, WORLD_NOW.replace(hour=19), 60)
    slot = svc._daily_planner.current_plan.get_slot_for_hour(19)
    assert (slot.activity_name, slot.reason) == (what, "plan with Maya")
    if reason is not None:
        slot.reason = reason
    svc._test_clock["now"] = WORLD_NOW.replace(hour=19, minute=5)
    return svc


@pytest.mark.parametrize("reason, kept", [(None, True), ("routine", False)])
def test_a_pressing_need_never_takes_a_plan_with_people(tmp_path, reason, kept):
    # Hungry (0.85, past HUNGRY_THRESHOLD) in the hour of a plan with Maya for reading, which feeds no one: she reads.
    svc = _seven_pm(tmp_path, f"hungry-{reason}", "reading", reason)
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._sustenance.state.hunger = 0.85
    svc._on_activity_tick()
    assert (svc._recent_activities[0].activity_name == "reading") is kept


@pytest.mark.parametrize("reason, kept", [(None, True), ("routine", False)])
def test_a_housemates_joint_activity_never_takes_a_plan_with_people(tmp_path, reason, kept):
    # A housemate reading where she is, in the hour of her plan with Maya to go climbing: she is not free to join.
    svc = _seven_pm(tmp_path, f"housemate-{reason}", "climbing", reason)
    free = svc._free_to_join("reading", svc._current_location, WORLD_NOW.replace(hour=19, minute=5))
    assert (free is None) is kept
