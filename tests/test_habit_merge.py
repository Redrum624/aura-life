"""One habit mechanism after the merge of aura-life 0.5.0 into the humanness branch (Task 31).

0.5.0's dated habits are pairs ``(raise, damp)`` per activity and part of her day
(``BehaviorSystem.habit_factors``). They act where 0.5.0 puts them, around the top-k cut, now on the branch's choice
weights: her own picks (``ActivityEngine.select_activity``: context x exp(utility / TEMPERATURE), cut to
``TOP_CANDIDATES``) and the planner's slots (``DailyPlanner._select_activity_for_slot``: score x exp(plan preference /
TEMPERATURE), cut to ``SLOT_DRAW_SIZE``). The raise multiplies a weight before the cut, the damp a weight after it, and a
damped one of the habit-free best keeps its place. The branch's undated habit term is out of the utility, so a habit
counts once.
"""
import random
from datetime import datetime, timedelta

import pytest

from aura_life import hooks
from aura_life.activities.activity_engine import ActivityEngine
from aura_life.activities.choice import TOP_CANDIDATES, choice_weight
from aura_life.behavior.behavior_system import HABIT_MAX_RATIO
from aura_life.life_service import LifeService
from aura_life.models import TimeOfDay, Weather
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner import daily_planner
from aura_life.planner.daily_planner import SLOT_DRAW_SIZE, DailyPlanner
from aura_life.world import WorldEnvironment

#: Main's own-pick scenario (tests/test_habits.py, test_her_own_picks_between_slots_lean_the_same_way_before_their_cut).
ENERGY = 0.8
MOMENT = dict(energy_level=ENERGY, time_of_day=TimeOfDay.MORNING, weather=Weather.CLOUDY, current_location="home")


def habit_free_weights(engine: ActivityEngine, energy_level: float, time_of_day: TimeOfDay, weather: Weather,
                       current_location: str) -> dict:
    """Every candidate's choice weight in ``engine.select_activity`` with no habit, no state, no goals: the calls that
    method makes (``ActivityEngine._score_activity`` for the context, ``ActivityPreferences.utility`` of
    ``ActivityEngine._complete_state`` for the utility, ``choice_weight`` of the two). Reads her recent picks, as the
    method does: reset ``engine._recent_activities`` first."""
    state = engine._complete_state(None, energy_level, None)
    weights = {}
    for activity in engine.get_all_activities():
        if activity.tags & engine._plan_only:
            continue
        context = engine._score_activity(activity, energy_level, time_of_day, weather, current_location, None, False)
        if context > 0:
            weights[activity.name] = choice_weight(context, engine._preferences.utility(activity, state))
    return weights


def _spied_engine(monkeypatch, seed=3):
    """An engine whose pick draws are recorded: each ``(population, weights)`` its rng chooses from."""
    engine = ActivityEngine(rng=random.Random(seed))
    seen = []
    real = engine._rng.choices
    monkeypatch.setattr(engine._rng, "choices",
                        lambda pop, weights: seen.append((list(pop), list(weights))) or real(pop, weights=weights))

    def pick(habit=None):
        engine._recent_activities = []          # the variety fit reads her recent picks: the same moment each time
        engine._rng.seed(seed)                  # the same draw each time (_score_activity draws on no rng)
        chosen = engine.select_activity(**MOMENT, habit=habit)
        pop, weights = seen[-1]
        return [a.name for a in pop], weights, chosen

    return engine, pick


def _outsiders(engine, base_names):
    """Main's outsiders: morning activities at home within her energy that the habit-free five leaves out."""
    return [a.name for a in engine.get_all_activities() if a.name not in base_names
            and TimeOfDay.MORNING in a.preferred_times and "home" in a.suitable_locations and a.min_energy <= ENERGY]


def test_no_habit_is_the_branchs_own_draw(monkeypatch):
    engine, pick = _spied_engine(monkeypatch)
    names, weights, chosen = pick()
    engine._recent_activities = []
    free = habit_free_weights(engine, **MOMENT)
    best = sorted(free, key=free.get, reverse=True)[:TOP_CANDIDATES]
    # The branch's draw: its best TOP_CANDIDATES by choice weight, each its share of their weights.
    assert names == best
    total = sum(free[n] for n in best)
    assert weights == pytest.approx([free[n] / total for n in best], rel=1e-12)
    # No habit and an empty one are that draw exactly, on one seed.
    for habit in (None, {}):
        assert pick(habit) == (names, weights, chosen)


def test_a_raised_outsider_enters_her_five_exactly_when_its_raised_weight_beats_the_fifth(monkeypatch):
    engine, pick = _spied_engine(monkeypatch)
    base_names, _, _ = pick()
    engine._recent_activities = []
    free = habit_free_weights(engine, **MOMENT)
    fifth = free[base_names[-1]]
    outsiders = _outsiders(engine, base_names)
    entered, stayed_out = [], []
    for name in outsiders:
        names, _, _ = pick({name: (HABIT_MAX_RATIO, 1.0)})
        (entered if name in names else stayed_out).append(name)
        # The raise multiplies her weight before the cut: in exactly when it then beats the fifth's (one that is no
        # candidate at all -- a plan-only anchor, or nothing the moment allows -- has no weight to raise).
        assert (name in names) == (free.get(name, 0.0) * HABIT_MAX_RATIO > fifth), name
    # Both happen in this moment, so the rule is tested both ways (the raise is x1.5 at most, not a pass).
    assert entered and stayed_out


def test_a_stale_one_of_her_five_stays_and_its_weight_falls_by_exactly_the_damp(monkeypatch):
    engine, pick = _spied_engine(monkeypatch)
    base_names, base_weights, _ = pick()
    engine._recent_activities = []
    free = habit_free_weights(engine, **MOMENT)
    stale = base_names[-1]
    # An outsider her comfort brings in: without the kept rule it would push the stale fifth out of the five.
    comfort = next(n for n in _outsiders(engine, base_names) if free[n] * HABIT_MAX_RATIO > free[stale])
    names, weights, _ = pick({comfort: (HABIT_MAX_RATIO, 1.0), stale: (1.0, 1 / HABIT_MAX_RATIO)})
    assert comfort in names and stale in names and len(names) == TOP_CANDIDATES
    habit_w, base_w = dict(zip(names, weights)), dict(zip(base_names, base_weights))
    plain = base_names[0]
    assert plain in habit_w
    ratio = (habit_w[stale] / habit_w[plain]) / (base_w[stale] / base_w[plain])
    assert ratio == pytest.approx(1 / HABIT_MAX_RATIO, rel=1e-9)


# ---------------------------------------------------------------- the planner's slots, on her plan weights

def test_a_slot_draw_on_her_plan_weights_keeps_the_bound(monkeypatch):
    # A persona with interests: her plan weights are score x exp(plan preference / TEMPERATURE), not flat.
    planner = DailyPlanner(occupation="", interests=["reading", "sketching", "meditating"], rng=random.Random(5))
    inputs, drawn = [], []
    real_draw = daily_planner._slot_draw
    monkeypatch.setattr(daily_planner, "_slot_draw",
                        lambda candidates, habit: inputs.append(list(candidates)) or real_draw(candidates, habit))
    real_choices = planner._rng.choices
    monkeypatch.setattr(planner._rng, "choices",
                        lambda pop, weights: drawn.append(([c[0] for c in pop], list(weights)))
                        or real_choices(pop, weights=weights))
    activity_map = {a.name: a for a in ActivityEngine().get_all_activities()}

    def slot(habit=None):
        planner._select_activity_for_slot(preferred_times=[TimeOfDay.MORNING], goals=[], desires=[],
                                          activity_map=activity_map, recent=[], weather=Weather.CLOUDY, used=[],
                                          habit=habit)
        return {name: w for name, w, _ in inputs[-1]}, drawn[-1]

    plan_w, (base_names, base_weights) = slot()
    assert len(base_names) == SLOT_DRAW_SIZE
    assert len(set(round(w, 9) for w in plan_w.values())) > 2        # her plan weights are spread, not flat
    stale = base_names[-1]
    within_reach = [n for n in plan_w if n not in base_names and plan_w[n] * HABIT_MAX_RATIO > plan_w[stale]]
    assert within_reach
    raised = within_reach[0]
    _, (names, weights) = slot({raised: (HABIT_MAX_RATIO, 1.0), stale: (1.0, 1 / HABIT_MAX_RATIO)})
    assert raised in names and stale in names and len(names) == SLOT_DRAW_SIZE
    habit_w, base_w = dict(zip(names, weights)), dict(zip(base_names, base_weights))
    plain = next(n for n in base_names if n in habit_w and n != stale)
    # The raise is on her plan weight; the stale one stays at /1.5 exactly against a plain one.
    assert habit_w[raised] / habit_w[plain] == pytest.approx(HABIT_MAX_RATIO * plan_w[raised] / plan_w[plain], rel=1e-9)
    assert (habit_w[stale] / habit_w[plain]) / (base_w[stale] / base_w[plain]) == pytest.approx(1 / HABIT_MAX_RATIO,
                                                                                                rel=1e-9)


# ---------------------------------------------------------------- the hour a habit is learned and read on

#: M8's clocks (tests/test_planner_clock.py): the host late in the evening, the world in the morning, years apart.
HOST_LATE = datetime(2026, 9, 16, 22, 45)
WORLD_MORNING = datetime(2031, 3, 10, 9, 0)


@pytest.fixture
def host_late():
    """The host's persona clock (``persona_now``) at :data:`HOST_LATE`, in any zone asked for: what
    ``persona_local_hour`` reads. The previous provider is put back afterwards."""
    saved = hooks.provider_for("persona_now")
    hooks.configure(persona_now=lambda timezone=None: HOST_LATE)
    yield
    hooks.configure(persona_now=saved)


def test_her_habits_are_learned_and_read_on_her_local_world_hour(tmp_path, monkeypatch, host_late):
    svc = LifeService(db_path=str(tmp_path / "hour.db"), persona_id="hour",
                      world_environment=WorldEnvironment(now=lambda: WORLD_MORNING),
                      definition=PersonalityDefinition(core_traits=["curious"], home_type="studio"),
                      rng=random.Random(5))
    # The clocks disagree: the host's hour is 22, her local world hour -- the one her plan runs on -- is 9.
    assert svc.persona_local_hour() == 22 and svc._local_world_now() == WORLD_MORNING
    yesterday = WORLD_MORNING - timedelta(hours=20)
    for name, n, hour in (("journaling", 40, 9), ("reading", 20, 9), ("daydreaming", 40, 22), ("people watching", 20, 22)):
        for _ in range(n):
            svc._behavior.track_activity(name, at=yesterday, hour=hour)
    monkeypatch.setattr(svc._energy, "should_sleep", lambda **kw: False)
    monkeypatch.setattr(svc._energy, "should_rest", lambda: False)
    monkeypatch.setattr(svc._desire_system, "should_do_intimate_activity", lambda *a, **k: False)
    seen = []
    real = svc._activity_engine.select_activity
    monkeypatch.setattr(svc._activity_engine, "select_activity", lambda **kw: seen.append(kw) or real(**kw))
    morning = svc._habit_factors()["morning"]   # before the tick dates what she picks
    assert "journaling" in morning and "daydreaming" not in morning

    svc._on_activity_tick()   # no plan yet: her own pick

    # Her own pick reads her morning's habits, and what she lived is dated at her hour 9, not the host's 22.
    assert len(seen) == 1 and seen[0]["habit"] == morning
    done = svc._recent_activities[0].activity_name
    assert svc._behavior.activity_log[-1] == (done, WORLD_MORNING, 9)
