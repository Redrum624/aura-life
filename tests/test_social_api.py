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

import json
import random
from datetime import datetime, timedelta

import pytest

from aura_life.life_service import LifeService
from aura_life.models import SocialEvent
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

#: The world, years from any host clock, at 09:00.
WORLD_NOW = datetime(2031, 3, 10, 9, 0)

CIRCLE = [
    {"name": "Maya", "relationship": "best friend", "shared_interests": "climbing, ramen"},
    {"name": "Leo", "relationship": "coworker", "shared_interests": "chess"},
    {"name": "Nora", "relationship": "sister", "shared_interests": ""},
]


def _service(tmp_path, pid="social", circle=CIRCLE, now=WORLD_NOW) -> LifeService:
    clock = {"now": now}
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
    svc._social.tick = lambda: event
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
