"""Task 41: a long downtime does not bring her back starving, nor as tired as
she was the evening the host went down.

Found by the branch's whole-branch review (2026-11-13). The catch-up charges
her hunger for every hour of the gap (Tasks 34b and 34c) and lives her affect
through all of it, but:

* it executed the FIRST ``max_activities`` slots of its window (12 for a gap
  over a day) and planned two calendar days where 48 hours from an evening
  touch three: after 72 hours away it backfilled one morning-to-evening (two
  or three meals) and charged the other day and a half with no meal. Measured
  (the review's ``gap_recovery.py``, down Monday 22:00, back Thursday 22:00):
  hunger 1.000 after the catch-up, 0.144 for the host that stayed on. Now
  every meal she planned in the gap is eaten, the rest of the budget is spread
  over the whole window, and every day the window touches is planned: 0.144;
* its affect ticks read her sleep pressure and her hours awake from the energy
  state as the reload left it, for the whole gap (0.833 and 15 hours in that
  run: the evening the host went down, for three days). Now each span's tick
  reads what her schedule gives at the span's start
  (``EnergySystem.pressure_on_schedule``).

Not fixed here, measured after both (same run): her mood still ends at -0.79
where the host that stayed on has +0.26 -- her loneliness at its top through
the gap (the owner's open question on its growth) and no activity of the gap
felt as one she lived (``AffectSystem.on_activity`` does not move her mood).

Each test runs with the host's clock frozen at four hours (``host_hour``): the
catch-up picks its slots on it.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from aura_life.energy.energy_system import EnergySystem
from aura_life.sustenance.sustenance_system import HUNGRY_THRESHOLD
from test_affect_catch_up import (  # noqa: F401 -- ``clock`` is a fixture
    TICKS_BEFORE_SAVE,
    _service,
    _ticks,
    clock,
)
from sim_helpers import DEFAULT_START

#: Three meals and ten other slots a day, none in her sleep hours here.
MEAL_HOURS = (8, 12, 19)
OTHER_HOURS = (9, 10, 11, 13, 14, 15, 16, 17, 18, 20)
#: The catch-up's window and its budget of slots for a gap over a day.
WINDOW_HOURS = 48
BUDGET = 12


def _full_days(svc):
    """The planner gives the same thirteen slots for every day asked."""
    meal = sorted(svc._setting.names_tagged("meal"))[0]
    slots = [SimpleNamespace(hour=h, activity_name=meal, location="home") for h in MEAL_HOURS]
    slots += [SimpleNamespace(hour=h, activity_name="making tea", location="home") for h in OTHER_HOURS]
    plan = SimpleNamespace(slots=slots)
    svc._daily_planner.generate_daily_plan = lambda **kwargs: plan
    svc._is_sleep_hour = lambda hour: False
    return meal


def _in_window(now, hours):
    """Every instant of ``hours`` (hours of the day) inside the catch-up's window ending at ``now``."""
    start = now - timedelta(hours=WINDOW_HOURS)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    found = []
    while day <= now:
        found += [day.replace(hour=h) for h in hours if start <= day.replace(hour=h) <= now]
        day += timedelta(days=1)
    return found


def _restart_after(folder, clock, gap_hours, plan=None):
    """An hour of ticks, a save, ``gap_hours`` with the host down, a new service on the same database."""
    clock.instant = DEFAULT_START
    svc = _service(folder, clock)
    _ticks(svc, clock, TICKS_BEFORE_SAVE)
    svc._save_state()
    clock.instant += timedelta(hours=gap_hours)
    again = _service(folder, clock)
    again._load_state()
    meal = plan(again) if plan is not None else None
    return again, meal


def _executed(svc):
    """Record the (instant, activity) of every slot the catch-up executes."""
    seen, real = [], svc._tick_engines_for_catchup

    def record(activity_name, timestamp, **kwargs):
        seen.append((timestamp, activity_name))
        return real(activity_name=activity_name, timestamp=timestamp, **kwargs)

    svc._tick_engines_for_catchup = record
    return seen


def test_every_meal_planned_in_the_gap_is_eaten_and_the_rest_is_spread_over_it(tmp_path, clock, host_hour):
    """Three days away: all the meals of the 48-hour window, on every day it
    touches, and the other slots from its first day to its last. Before: the
    first twelve slots in time order, of two days."""
    svc, meal = _restart_after(tmp_path, clock, 72, _full_days)
    seen = _executed(svc)
    svc.catch_up_from_downtime(72.0)
    meals = [at for at, name in seen if name == meal]
    others = [at for at, name in seen if name != meal]
    planned = _in_window(host_hour, MEAL_HOURS)
    assert len(planned) in (6, 7), planned      # two days of meals, a seventh when the window's ends both hold one
    assert meals == planned
    assert [at for at, _ in seen] == sorted(at for at, _ in seen)
    assert len(others) == BUDGET - len(planned)
    assert others[0] - (host_hour - timedelta(hours=WINDOW_HOURS)) < timedelta(hours=14)
    assert host_hour - others[-1] < timedelta(hours=24)
    assert len({at.date() for at in others}) >= 2


def test_three_days_away_do_not_bring_her_back_starving(tmp_path, clock, host_hour):
    """Her hunger after the catch-up is what the hours since her last planned
    meal built, under the level she is hungry at -- at every host hour. Before:
    1.0 at each (a day and a half charged with no meal)."""
    svc, _ = _restart_after(tmp_path, clock, 72, _full_days)
    svc.catch_up_from_downtime(72.0)
    assert svc._basic_needs.hunger < HUNGRY_THRESHOLD, svc._basic_needs.hunger
    last_meal = max(_in_window(host_hour, MEAL_HOURS))
    assert svc._basic_needs.last_meal_time == last_meal


def test_a_gap_under_a_day_keeps_its_meals_too(tmp_path, clock, host_hour):
    """Twenty hours away, a budget of eight slots among up to thirteen: its
    meals are all eaten. Before: the first eight slots, so a dinner late in
    the gap was dropped and its hours charged."""
    svc, meal = _restart_after(tmp_path, clock, 20, _full_days)
    seen = _executed(svc)
    svc.catch_up_from_downtime(20.0)
    start = host_hour - timedelta(hours=20)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    planned = sorted(d.replace(hour=h) for d in (day, day + timedelta(days=1)) for h in MEAL_HOURS
                     if start <= d.replace(hour=h) <= host_hour)
    assert [at for at, name in seen if name == meal] == planned
    assert len(seen) == 8


def test_the_catch_up_s_affect_ticks_read_the_sleep_pressure_her_schedule_gives(tmp_path, clock, host_hour):
    """Each affect tick of the gap is handed the sleep pressure and the hours
    awake her schedule gives at its span's start, not the energy state the
    reload left for the whole gap. Before: one pair for every tick (set here
    to 0.9 and 20 hours: a persona saved late in her evening)."""
    svc, _ = _restart_after(tmp_path, clock, 72)
    svc._energy._state.fatigue, svc._energy._state.hours_awake = 0.9, 20.0
    asked, real_tick, real_affect = [], svc._tick_affect, svc._affect.tick

    def tick(hours, now, asleep, on_schedule_at=None):
        asked.append((on_schedule_at, asleep))
        return real_tick(hours, now, asleep, on_schedule_at=on_schedule_at)

    bodies = []

    def affect_tick(**kwargs):
        bodies.append(kwargs["body_state"])
        return real_affect(**kwargs)

    svc._tick_affect, svc._affect.tick = tick, affect_tick
    svc.catch_up_from_downtime(72.0)
    assert len(asked) == len(bodies) >= 6
    for (at, asleep), body in zip(asked, bodies):
        assert at is not None
        assert (body["sleep_pressure"], body["hours_awake"]) == svc._energy.pressure_on_schedule(at)
        if asleep:
            assert body["hours_awake"] == 0.0
    assert len({body["sleep_pressure"] for body in bodies}) > 1
    assert all(body["sleep_pressure"] != 0.9 for body in bodies)


def test_a_live_tick_still_reads_her_energy_state(tmp_path, clock):
    """Outside the catch-up nothing changed: the live affect tick reads the
    energy system's own pressure and hours awake."""
    clock.instant = DEFAULT_START
    svc = _service(tmp_path, clock)
    svc._energy._state.fatigue, svc._energy._state.hours_awake = 0.37, 6.5
    bodies, real_affect = [], svc._affect.tick

    def affect_tick(**kwargs):
        bodies.append(kwargs["body_state"])
        return real_affect(**kwargs)

    svc._affect.tick = affect_tick
    svc._tick_affect(1 / 12, clock.instant, False)
    assert (bodies[0]["sleep_pressure"], bodies[0]["hours_awake"]) == (0.37, 6.5)


@pytest.mark.parametrize("hour, minute", [(3, 0), (6, 59), (7, 0), (12, 30), (22, 59), (23, 0)])
def test_pressure_on_schedule_is_what_a_new_persona_starts_with_and_changes_nothing(hour, minute):
    """The query and ``start_on_schedule`` give one pair at every hour of a
    23:00 to 07:00 sleeper's Tuesday; the query leaves her state alone."""
    at = datetime(2026, 9, 22, hour, minute)
    energy = EnergySystem(now=lambda: at)
    energy._state.fatigue, energy._state.hours_awake = 0.123, 4.5
    asleep_before = energy._asleep
    pair = energy.pressure_on_schedule(at)
    assert (energy._state.fatigue, energy._state.hours_awake, energy._asleep) == (0.123, 4.5, asleep_before)
    energy.start_on_schedule(at)
    assert pair == (energy._state.fatigue, energy._state.hours_awake)
    inside = hour >= 23 or hour < 7
    assert energy._asleep is inside
    if inside:
        # Sixteen hours awake built it, eight asleep clear it: an hour of the night clears two of the day.
        slept = ((hour - 23) % 24) + minute / 60
        day = min(1.0, 16 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)
        assert pair == (pytest.approx(max(0.0, day - slept * 2 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)), 0.0)
    else:
        assert pair[0] == pytest.approx(pair[1] * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)
