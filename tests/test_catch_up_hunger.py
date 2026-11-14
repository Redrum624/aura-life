"""Task 34c: a gap the process lived through charges her hunger once.

aura-desk calls ``catch_up_from_downtime`` for a PC that slept while the process
lived on (its poll), beside the scheduler's live ticks, so either may come
first. The live tick charges her hunger every world hour since its stamp
(``_sustenance_ticked_at``), and the catch-up charged "the whole gap" again:
after 8 hours her hunger gained +0.7720 with the live tick first, where a host
that stayed on gains +0.3880 (the controller's probe). A restart is another
matter: the reload takes the stamp again ("downtime is not charged as lived
time"), so there the catch-up alone charges the downtime, in either order.

The rule, in Task 34b's terms (her affect's gap ends where her live ticks
began): the catch-up charges her hunger only the hours of the gap her live
tick never charges -- the downtime before where her live hunger ticks began
(``_sustenance_live_since``: her reload), and of a gap she lived through, the
hours after the live tick's stamp, which the catch-up then takes. The
catch-up's slots still feed her: a meal slot is a meal, in either order.

Each test runs with the host's clock frozen at four hours (``host_hour``), as
the catch-up picks its slots on it.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from aura_life.sustenance.sustenance_system import (
    HUNGER_RISE_PER_HOUR,
    MEAL_HUNGER_REDUCTION,
    TICK_HOURS,
)
from sim_helpers import DEFAULT_START
from test_affect_catch_up import (  # noqa: F401 -- ``clock`` is a fixture
    GAP_HOURS,
    ORDERS,
    TICKS_BEFORE_SAVE,
    _no_plan,
    _service,
    _ticks,
    clock,
)

#: One default tick's hunger: her hunger's rise over one energy interval.
ONE_TICK_HUNGER = HUNGER_RISE_PER_HOUR * TICK_HOURS
#: Her hunger at the start of the meal tests: high enough that the meal's
#: relief is never cut short at 0 in either order (asserted where it is used),
#: so the hours and the meal account for her hunger exactly.
MEAL_START_HUNGER = 0.3
#: Where the meal slot lies in the gap, in hours from its start.
MEAL_AT_HOURS = GAP_HOURS // 2

RESTARTS = pytest.mark.parametrize("restart", (False, True), ids=("lived through", "restart"))


def _first_hour(folder, clock, hunger=None):
    """A new service at DEFAULT_START (her hunger set to ``hunger`` if given)
    and an hour of 5-minute ticks. Returns it and her hunger then."""
    clock.instant = DEFAULT_START
    svc = _service(folder, clock)
    if hunger is not None:
        svc._basic_needs.hunger = hunger
    _ticks(svc, clock, TICKS_BEFORE_SAVE)
    return svc, svc._basic_needs.hunger


def _meal_slot(hour):
    """The catch-up plans one slot, at the host's ``hour``: a meal. None of
    her hours is a sleep hour here, so the slot stays a meal at every host
    hour (a slot in her sleep hours is lived as sleep)."""
    def install(svc):
        name = sorted(svc._setting.names_tagged("meal"))[0]
        plan = SimpleNamespace(slots=[SimpleNamespace(hour=hour, activity_name=name, location="home")])
        svc._daily_planner.generate_daily_plan = lambda **kwargs: plan
        svc._is_sleep_hour = lambda hour: False
    return install


def _after_gap(folder, clock, live_first, restart, plan, hunger=None):
    """An hour of ticks, then GAP_HOURS with no tick: the process lives
    through them (a PC that slept), or the host goes down after a save and
    comes back on the same database (``restart``). Then the first live tick 5
    minutes on and the catch-up, in the order given. Returns her hunger and
    meals_today before the gap, and the service."""
    svc, before = _first_hour(folder, clock, hunger)
    meals = svc._basic_needs.meals_today
    clock.instant += timedelta(hours=GAP_HOURS)
    if restart:
        svc._save_state()
        svc = _service(folder, clock)
        svc._load_state()
        assert svc._basic_needs.hunger == before
    plan(svc)
    if live_first:
        _ticks(svc, clock, 1)
        svc.catch_up_from_downtime(float(GAP_HOURS))
    else:
        svc.catch_up_from_downtime(float(GAP_HOURS))
        _ticks(svc, clock, 1)
    return before, meals, svc


@ORDERS
def test_a_gap_she_lived_through_charges_her_hunger_what_a_host_that_stayed_on_gains_in_both_orders(
        tmp_path, clock, host_hour, live_first):
    """The probe's rows: a host that stayed on gains +0.3880 over the gap and
    one tick more; a process that lived through the gap gained +0.7720 with
    the live tick first (the catch-up charged the hours again) and +0.3880 with
    the catch-up first. Now +0.3880 in both orders."""
    stayed, stayed_before = _first_hour(tmp_path / "stayed", clock)
    _ticks(stayed, clock, GAP_HOURS * 12 + 1)
    stayed_gain = stayed._basic_needs.hunger - stayed_before
    assert stayed_gain == pytest.approx(HUNGER_RISE_PER_HOUR * (GAP_HOURS + TICK_HOURS), abs=1e-9)
    before, _, svc = _after_gap(tmp_path / "slept", clock, live_first, restart=False, plan=_no_plan)
    assert svc._basic_needs.hunger - before == pytest.approx(stayed_gain, abs=ONE_TICK_HUNGER)


@ORDERS
def test_a_restart_charges_her_hunger_the_whole_downtime_once_in_both_orders(
        tmp_path, clock, host_hour, live_first):
    """After a restart the reload took the live tick's stamp again, so the
    catch-up charges the downtime and the live tick its 5 minutes, in either
    order (right before this task; it stays so)."""
    before, _, svc = _after_gap(tmp_path, clock, live_first, restart=True, plan=_no_plan)
    expected = before + HUNGER_RISE_PER_HOUR * (GAP_HOURS + TICK_HOURS)
    assert svc._basic_needs.hunger == pytest.approx(expected, abs=1e-9)


@RESTARTS
@ORDERS
def test_a_meal_slot_feeds_her_once_and_the_gap_is_charged_once_in_both_orders(
        tmp_path, clock, host_hour, live_first, restart):
    """A meal slot in the gap is one meal (meals_today + 1, one relief), and
    the gap's hours are charged once, for a gap she lived through and for a
    restart, in both orders: her hunger is her hunger before the gap, plus
    the gap and the live tick's 5 minutes at HUNGER_RISE_PER_HOUR, less one
    MEAL_HUNGER_REDUCTION. (Before: 0.7200 for the gap she lived through with
    the live tick first, its hours charged twice; 0.3360 is expected.)"""
    plan = _meal_slot((host_hour.hour - MEAL_AT_HOURS) % 24)
    before, meals, svc = _after_gap(tmp_path, clock, live_first, restart, plan, hunger=MEAL_START_HUNGER)
    # The relief is never cut short at 0 (the meal comes after MEAL_AT_HOURS of
    # the gap, or after all of it), nor her hunger at 1.
    assert before + HUNGER_RISE_PER_HOUR * MEAL_AT_HOURS >= MEAL_HUNGER_REDUCTION
    assert before + HUNGER_RISE_PER_HOUR * (GAP_HOURS + TICK_HOURS) <= 1.0
    assert svc._basic_needs.meals_today == meals + 1
    expected = before + HUNGER_RISE_PER_HOUR * (GAP_HOURS + TICK_HOURS) - MEAL_HUNGER_REDUCTION
    assert svc._basic_needs.hunger == pytest.approx(expected, abs=1e-9)


#: The meals of the time-order test, in hours from the gap's start: two early
#: in it, while her hunger is low, so each relief is cut short at 0 when it
#: comes after the hours before it -- and not when it comes after all of the
#: gap's hours (fix round 1, I-1 / I-2).
EARLY_MEALS = (1, 3)


def _early_meals(host_hour, gap):
    """The catch-up plans a meal slot at EARLY_MEALS hours into the gap, on
    every day it plans (a 30-hour gap: two days, so also a day later), and no
    other slot. Returns the installer and the meals' hours into the gap."""
    hours = [(host_hour.hour - gap + m) % 24 for m in EARLY_MEALS]
    at = [m + 24 * day for day in range(2) for m in EARLY_MEALS if m + 24 * day <= gap]

    def install(svc):
        name = sorted(svc._setting.names_tagged("meal"))[0]
        plan = SimpleNamespace(slots=[SimpleNamespace(hour=h, activity_name=name, location="home") for h in hours])
        svc._daily_planner.generate_daily_plan = lambda **kwargs: plan
        svc._is_sleep_hour = lambda hour: False
    return install, at


def _in_time_order(before, gap, meals_at):
    """Her hunger after ``gap`` hours from ``before`` with a meal at each of
    ``meals_at`` (hours into the gap): the hours before each meal, then its
    relief, in time order -- the clamps at 1 and at 0 where they fall."""
    hunger, charged_to = before, 0.0
    for at in meals_at:
        hunger = min(1.0, hunger + HUNGER_RISE_PER_HOUR * (at - charged_to))
        hunger = max(0.0, hunger - MEAL_HUNGER_REDUCTION)
        charged_to = at
    return min(1.0, hunger + HUNGER_RISE_PER_HOUR * (gap - charged_to))


@pytest.mark.parametrize("gap", (8, 30), ids=("8 h", "30 h"))
@ORDERS
def test_a_gap_she_lived_through_lives_its_meals_and_hours_in_time_order_in_both_orders(
        tmp_path, clock, host_hour, live_first, gap):
    """Fix round 1 (I-1): with the live tick first, the live tick had charged
    all of a gap she lived through, and the catch-up's meals came after all of
    its hours: her hunger after 8 hours with meals 1 h and 3 h in was 0.0000
    with the live tick first and 0.2400 with the catch-up first (30 h, and the
    same meals a day later: 0.0000 and 0.4400). Now, in both orders, the hours before each meal, then the
    meal, in time order -- her hunger and her nutrition the same in both
    orders. The live tick comes at the wake, at the catch-up's instant, so the
    two orders see the same gap."""
    plan, meals_at = _early_meals(host_hour, gap)
    svc, before = _first_hour(tmp_path, clock)
    meals = svc._basic_needs.meals_today
    # The relief of the first meal is cut short at 0 in time order, and her
    # hunger reaches 1 before the second day's meals (30 h): the clamps matter.
    assert before + HUNGER_RISE_PER_HOUR * EARLY_MEALS[0] < MEAL_HUNGER_REDUCTION
    clock.instant += timedelta(hours=gap)
    plan(svc)
    if live_first:
        svc._on_energy_tick()
        svc.catch_up_from_downtime(float(gap))
    else:
        svc.catch_up_from_downtime(float(gap))
        svc._on_energy_tick()
    assert svc._basic_needs.meals_today == meals + len(meals_at)
    assert svc._basic_needs.hunger == pytest.approx(_in_time_order(before, gap, meals_at), abs=1e-9)
    # The other order, on a second service: the same hunger and nutrition.
    other, _ = _first_hour(tmp_path / "other", clock)
    clock.instant += timedelta(hours=gap)
    plan(other)
    if live_first:
        other.catch_up_from_downtime(float(gap))
        other._on_energy_tick()
    else:
        other._on_energy_tick()
        other.catch_up_from_downtime(float(gap))
    assert svc._basic_needs.hunger == pytest.approx(other._basic_needs.hunger, abs=1e-12)
    assert svc._basic_needs.nutrition == pytest.approx(other._basic_needs.nutrition, abs=1e-12)


def test_a_live_meal_between_the_wake_and_the_catch_up_is_not_undone(tmp_path, clock, host_hour):
    """The catch-up lives a gap's hours again only while nothing but the live
    tick has fed on them: a meal she ate live after the wake stays eaten, and
    the gap's hours are not charged again (fix round 1)."""
    svc, before = _first_hour(tmp_path, clock)
    clock.instant += timedelta(hours=GAP_HOURS)
    _no_plan(svc)
    svc._on_energy_tick()
    gained = before + HUNGER_RISE_PER_HOUR * GAP_HOURS
    assert svc._basic_needs.hunger == pytest.approx(gained, abs=1e-9)
    meal = svc._activity_engine.get_activity(sorted(svc._setting.names_tagged("meal"))[0])
    svc._perform_activity(meal, None)
    fed = svc._basic_needs.hunger
    assert fed == pytest.approx(gained - MEAL_HUNGER_REDUCTION, abs=1e-9)
    svc.catch_up_from_downtime(float(GAP_HOURS))
    assert svc._basic_needs.hunger == pytest.approx(fed, abs=1e-9)


def test_a_gap_she_lived_through_charges_every_hour_since_the_live_tick_with_the_catch_up_first(
        tmp_path, clock, host_hour):
    """The catch-up first, of a gap she lived through: every hour since the
    live tick's stamp, those before the gap it is told of too (aura-desk's
    poll measures from its own last poll), as the live tick would charge
    them -- so the two orders charge the same hours, a gap over the 48 hours
    the catch-up plans included (fix round 1)."""
    svc, before = _first_hour(tmp_path, clock)
    clock.instant += timedelta(hours=GAP_HOURS)
    _no_plan(svc)
    svc.catch_up_from_downtime(GAP_HOURS - 0.5)
    svc._on_energy_tick()
    assert svc._basic_needs.hunger == pytest.approx(before + HUNGER_RISE_PER_HOUR * GAP_HOURS, abs=1e-9)
