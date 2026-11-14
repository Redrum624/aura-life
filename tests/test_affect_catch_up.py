"""Task 34b: the hours she was away are lived hours for her affect.

After a reload, the live tick charges her affect only the time since the reload
("downtime is not charged as lived time", ruling T34-R1), and before this task
``catch_up_from_downtime`` never ticked her affect: after an 8-hour gap her
loneliness had gained 0.0019 where a host that stayed on gains 0.0591 (0.0025
against 0.2425 with no interaction ever; Task 34's step 4). Now the catch-up
ticks her affect for the gap, as it already charges her hunger for it: once
per slot it executes (the hours since the gap's start or the previous slot,
asleep in a sleep slot) and once more for the rest of the gap, on the world
clock, ending where her live ticks began (the reload), so the first live tick
and the catch-up may come in either order. A gap inside her live ticks' span
(the PC slept, the process lived on) is the live tick's to charge.

Each test runs with the host's clock frozen at four hours (``host_hour``): the
catch-up's slots are picked on it, so their number moves with it.
"""
import pathlib
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from aura_life import hooks
from aura_life.affect.affect_system import (
    DEFAULT_TICK_HOURS,
    EMPATHIC_FATIGUE_FADE_PER_TICK,
    LONELINESS_GROWTH_PER_TICK,
    REGULATION_RETURN_PER_TICK,
)
from aura_life.life_service import LifeService
from aura_life.world import WorldEnvironment
from sim_helpers import DEFAULT_START

#: The host's downtime in these tests: Task 34's step-4 setup.
GAP_HOURS = 8
#: The energy ticks before the save (one hour at the scheduler's 5 minutes).
TICKS_BEFORE_SAVE = 12


class ScriptedClock:
    def __init__(self, start):
        self.instant = start

    def __call__(self):
        return self.instant


@pytest.fixture
def clock():
    saved = hooks.provider_for("persona_now")
    scripted = ScriptedClock(DEFAULT_START)
    hooks.configure(persona_now=lambda timezone=None: scripted.instant)
    yield scripted
    hooks.configure(persona_now=saved)


def _service(folder, clock):
    pathlib.Path(folder).mkdir(parents=True, exist_ok=True)
    return LifeService(db_path=str(pathlib.Path(folder) / "nova.db"), persona_id="nova",
                       world_environment=WorldEnvironment(now=clock, seed=1), rng=random.Random(1))


def _ticks(svc, clock, n):
    for _ in range(n):
        clock.instant += timedelta(minutes=5)
        svc._on_energy_tick()


def _state(svc):
    aff = svc._affect
    return {"loneliness": aff.loneliness.level, "regulation": aff._regulation.capacity,
            "fatigue": aff._empathy.empathic_fatigue}


def _first_hour(folder, clock, interaction):
    """A new service at DEFAULT_START: a meaningful interaction (or none), her
    regulation drained and her empathic fatigue raised (so both have somewhere
    to go), an hour of 5-minute ticks, a save. Returns it and its state."""
    clock.instant = DEFAULT_START
    svc = _service(folder, clock)
    if interaction:
        svc._affect.on_social_interaction(True, now=clock.instant)
    svc._affect.deplete_regulation(0.3, "test")
    svc._affect._empathy.empathic_fatigue = 0.6
    _ticks(svc, clock, TICKS_BEFORE_SAVE)
    svc._save_affect()
    return svc, _state(svc)


def _stayed_on(folder, clock, interaction, gap=GAP_HOURS):
    """The host stays on through the gap and one tick more."""
    svc, saved = _first_hour(folder, clock, interaction)
    _ticks(svc, clock, gap * 12 + 1)
    return saved, _state(svc)


def _no_plan(svc):
    """The catch-up plans no slot at all (its planner returns no plan)."""
    svc._daily_planner.generate_daily_plan = lambda **kwargs: None


def _hourly_plan(svc):
    """A slot at every hour of the day, of an activity that neither recharges
    her regulation nor is a meal."""
    plan = SimpleNamespace(slots=[SimpleNamespace(hour=h, activity_name="making tea", location="home")
                                  for h in range(24)])
    svc._daily_planner.generate_daily_plan = lambda **kwargs: plan


def _restarted(folder, clock, interaction, live_first, gap=GAP_HOURS, plan=None):
    """The host goes down at the save and comes back ``gap`` hours on: a new
    service on the same database, then its first live tick 5 minutes on and
    the catch-up, in the order given. Returns the state at the save, after, and
    the reload instant."""
    _, saved = _first_hour(folder, clock, interaction)
    clock.instant += timedelta(hours=gap)
    again = _service(folder, clock)
    again._load_state()
    reload_at = clock.instant
    if plan is not None:
        plan(again)
    if live_first:
        _ticks(again, clock, 1)
        again.catch_up_from_downtime(float(gap))
    else:
        again.catch_up_from_downtime(float(gap))
        _ticks(again, clock, 1)
    return saved, _state(again), reload_at, again


ORDERS = pytest.mark.parametrize("live_first", (True, False), ids=("live tick first", "catch-up first"))
INTERACTIONS = pytest.mark.parametrize("interaction", (True, False),
                                       ids=("interaction at the start", "no interaction"))


@INTERACTIONS
def test_after_an_8_hour_gap_her_loneliness_gained_what_a_host_that_stayed_on_gains_in_both_orders(
        tmp_path, clock, host_hour, interaction):
    """Acceptance (a) and (c): within 0.01 of the stayed-on host's gain
    (0.0591 with an interaction at the start, 0.2425 with none; before: 0.0019
    and 0.0025), and the two orders the same to 1e-6, loneliness and empathic
    fatigue (her regulation: see the no-slot test, a slot's recharge does not
    commute with the live tick's pull)."""
    stayed_saved, stayed = _stayed_on(tmp_path / "stayed", clock, interaction)
    gained = stayed["loneliness"] - stayed_saved["loneliness"]
    after = {}
    for live_first in (True, False):
        saved, state, _, _ = _restarted(tmp_path / f"restart-{live_first}", clock, interaction, live_first)
        assert state["loneliness"] - saved["loneliness"] == pytest.approx(gained, abs=0.01), live_first
        after[live_first] = state
    assert after[True]["loneliness"] == pytest.approx(after[False]["loneliness"], abs=1e-6)
    assert after[True]["fatigue"] == pytest.approx(after[False]["fatigue"], abs=1e-6)


@pytest.mark.parametrize("plan", (_no_plan, _hourly_plan), ids=("no slot", "a slot every hour"))
@INTERACTIONS
def test_after_an_8_hour_gap_her_regulation_and_fatigue_are_within_a_default_tick_of_a_host_that_stayed_on(
        tmp_path, clock, host_hour, interaction, plan):
    """Acceptance (b) and (c), and the gap with no slot to execute (the
    reviewer's run of Task 34's script had none): the whole gap is still
    charged, by the catch-up's one tick for the rest of it."""
    _, stayed = _stayed_on(tmp_path / "stayed", clock, interaction)
    baseline = None
    after = {}
    for live_first in (True, False):
        saved, state, _, again = _restarted(tmp_path / f"restart-{live_first}", clock, interaction, live_first,
                                            plan=plan)
        baseline = again._affect._regulation.baseline
        after[live_first] = state
        one_tick_regulation = REGULATION_RETURN_PER_TICK * abs(baseline - stayed["regulation"])
        assert state["regulation"] == pytest.approx(stayed["regulation"], abs=one_tick_regulation), live_first
        assert state["fatigue"] == pytest.approx(stayed["fatigue"], abs=EMPATHIC_FATIGUE_FADE_PER_TICK), live_first
        assert state["regulation"] != pytest.approx(saved["regulation"], abs=0.1)   # it did come back
    for key in ("loneliness", "regulation", "fatigue"):
        assert after[True][key] == pytest.approx(after[False][key], abs=1e-6), key


def _catch_up_recorded(svc, hours):
    """Run the catch-up of ``hours``, recording in order each affect tick (its
    hours, now, whether asleep and the hunger it sees) and each slot it
    executes (its activity and her hunger after it)."""
    events = []
    real_tick = svc._affect.tick
    real_slot = svc._tick_engines_for_catchup

    def tick(*args, **kwargs):
        body = kwargs["body_state"]
        events.append(("tick", kwargs["hours"], kwargs["now"], body["asleep"], body["hunger"]))
        return real_tick(*args, **kwargs)

    def slot(*args, **kwargs):
        result = real_slot(*args, **kwargs)
        events.append(("slot", kwargs["activity_name"], svc._basic_needs.hunger))
        return result

    svc._affect.tick = tick
    svc._tick_engines_for_catchup = slot
    try:
        svc.catch_up_from_downtime(hours)
    finally:
        del svc._affect.tick
        del svc._tick_engines_for_catchup
    return events


@pytest.mark.parametrize("plan", (None, _no_plan, _hourly_plan), ids=("her planner", "no slot", "a slot every hour"))
@ORDERS
def test_the_catch_up_ticks_her_affect_once_before_each_slot_and_once_for_the_rest_the_hours_summing_to_the_gap(
        tmp_path, clock, host_hour, live_first, plan):
    """The hours each slot stands for (since the gap's start or the previous
    slot), then the rest of the gap: contiguous on the world clock, from the
    reload's instant less the gap to the reload's instant, whichever order;
    asleep exactly in a sleep slot."""
    _first_hour(tmp_path, clock, True)
    clock.instant += timedelta(hours=GAP_HOURS)
    again = _service(tmp_path, clock)
    again._load_state()
    reload_at = clock.instant
    if plan is not None:
        plan(again)
    if live_first:
        _ticks(again, clock, 1)
    events = _catch_up_recorded(again, float(GAP_HOURS))
    ticks = [e for e in events if e[0] == "tick"]
    slots = [e for e in events if e[0] == "slot"]
    # At least one tick before each slot, and after the last (a span is split
    # where her sleep hours begin or end: the asleep test below).
    groups = "".join("t" if e[0] == "tick" else "s" for e in events).split("s")
    assert len(groups) == len(slots) + 1 and all(groups), groups
    if plan is _hourly_plan:
        assert len(slots) == 4   # the catch-up's own cap for an 8-hour gap
    assert sum(e[1] for e in ticks) == pytest.approx(GAP_HOURS, abs=1e-9)
    edge = reload_at - timedelta(hours=GAP_HOURS)
    for _, hours, now, *_ in ticks:
        assert hours >= 0
        assert abs(now - timedelta(hours=hours) - edge) <= timedelta(microseconds=1)
        edge = now
    assert edge == reload_at


def _reloaded(folder, clock, gap, live_first, plan):
    """The host goes down at the save and comes back ``gap`` hours on: a new
    service on the same database, its plan replaced (``plan``), and its first
    live tick 5 minutes on when ``live_first``. Returns it and the reload's
    instant."""
    _first_hour(folder, clock, True)
    clock.instant += timedelta(hours=gap)
    again = _service(folder, clock)
    again._load_state()
    reload_at = clock.instant
    if plan is not None:
        plan(again)
    if live_first:
        _ticks(again, clock, 1)
    return again, reload_at


PLANS = pytest.mark.parametrize("plan", (None, _no_plan, _hourly_plan),
                                ids=("her planner", "no slot", "a slot every hour"))


@PLANS
@ORDERS
def test_each_catch_up_affect_tick_sees_her_hunger_as_it_was_at_the_start_of_its_hours(
        tmp_path, clock, host_hour, live_first, plan):
    """Fix round 1 (34b-M1): a tick lives its hours with the body state they
    began with, as the slot ticks always did (hours first, then the activity),
    the rest of the gap's tick included -- it sees her hunger as the last slot
    left it, or as the reload did with no slot, not as charged for the rest of
    the gap (the review's 72-hour trace, host 15:00: 1.0 where its hours began
    at 0.32 with her planner and at 0.0 with no slot)."""
    again, _ = _reloaded(tmp_path, clock, GAP_HOURS, live_first, plan)
    expected = again._basic_needs.hunger
    events = _catch_up_recorded(again, float(GAP_HOURS))
    assert again._basic_needs.hunger != expected   # the gap's hours did charge her hunger
    for event in events:
        if event[0] == "tick":
            assert event[4] == expected, events
        else:
            expected = event[2]


@pytest.mark.parametrize("gap, plan", ((GAP_HOURS, None), (GAP_HOURS, _no_plan), (GAP_HOURS, _hourly_plan),
                                       (72, _no_plan)),
                         ids=("8 h her planner", "8 h no slot", "8 h a slot every hour", "72 h no slot"))
@ORDERS
def test_each_hour_of_the_gap_is_lived_asleep_exactly_when_it_is_one_of_her_sleep_hours(
        tmp_path, clock, host_hour, live_first, gap, plan):
    """Fix round 1 (34b-M2): a span of the gap is split where her sleep hours
    begin or end, each part asleep exactly when its hours are her sleep hours,
    on the host's hour as the catch-up's sleep slots are (before: a span took
    the flag of the slot that ended it, and the rest of the gap that of the
    host's hour at its end -- an overnight gap with no sleep slot was lived
    awake, 72 hours with no slot all asleep at host 02:00 and all awake at
    15:00). A part that does not end at a slot ends where the flag changes."""
    again, reload_at = _reloaded(tmp_path, clock, gap, live_first, plan)
    events = _catch_up_recorded(again, float(gap))
    to_wall = host_hour - reload_at
    edge = reload_at - timedelta(hours=gap)
    previous = None
    for event in events:
        if event[0] == "slot":
            previous = None
            continue
        _, hours, now, asleep, _ = event
        hour = (edge + to_wall).replace(minute=0, second=0, microsecond=0)
        while True:
            assert again._is_sleep_hour(hour.hour) == asleep, (edge + to_wall, now + to_wall, hour)
            hour += timedelta(hours=1)
            if hour >= now + to_wall:
                break
        if previous is not None:
            assert asleep != previous, (edge + to_wall, now + to_wall)
        previous = asleep
        edge = now


def test_a_gap_under_an_hour_and_a_second_catch_up_of_no_hours_change_nothing(tmp_path, clock, host_hour):
    """Acceptance (e)."""
    _first_hour(tmp_path, clock, True)
    clock.instant += timedelta(minutes=50)
    again = _service(tmp_path, clock)
    again._load_state()
    before = again._affect.to_dict()
    again.catch_up_from_downtime(50 / 60)
    assert again._affect.to_dict() == before
    again.catch_up_from_downtime(float(GAP_HOURS))
    once = again._affect.to_dict()
    again.catch_up_from_downtime(0.0)
    assert again._affect.to_dict() == once


@pytest.mark.parametrize("plan", (None, _hourly_plan), ids=("her planner", "a slot every hour"))
@ORDERS
def test_a_72_hour_gap_charges_all_72_hours_not_the_48_the_catch_up_plans(
        tmp_path, clock, host_hour, live_first, plan):
    """Step 3: the affect hours follow the real gap. With a desired contact of
    0.1 and no interaction ever her loneliness gains 0.005 x 0.1 a default
    tick (LONELINESS_GROWTH_PER_TICK): 72 hours and the live tick's 5 minutes
    are 865 of them, 0.4325 -- the 48 hours planned would give 0.2885. Every
    value stays inside its bounds."""
    _, saved = _first_hour(tmp_path, clock, False)
    clock.instant += timedelta(hours=72)
    again = _service(tmp_path, clock)
    again._load_state()
    again._affect._loneliness.desired_contact_baseline = 0.1
    level = again._affect.loneliness.level
    if plan is not None:
        plan(again)
    if live_first:
        _ticks(again, clock, 1)
    events = _catch_up_recorded(again, 72.0)
    if not live_first:
        _ticks(again, clock, 1)
    assert sum(e[1] for e in events if e[0] == "tick") == pytest.approx(72.0, abs=1e-9)
    expected = LONELINESS_GROWTH_PER_TICK * 0.1 * (72 * 12 + 1)
    assert again._affect.loneliness.level - level == pytest.approx(expected, abs=1e-6)
    aff = again._affect
    assert 0.0 <= aff.loneliness.level <= 1.0
    assert 0.0 <= aff._regulation.capacity <= 1.0
    assert 0.0 <= aff._empathy.empathic_fatigue <= 1.0
    assert -1.0 <= aff.mood.valence <= 1.0
    assert 0.0 <= aff.mood.arousal <= 1.0
    assert 0.0 <= aff.stress.level <= 1.0


@ORDERS
def test_a_gap_she_lived_through_is_charged_once_by_the_live_tick_not_again_by_the_catch_up(
        tmp_path, clock, host_hour, live_first):
    """aura-desk's poll calls the catch-up for a forward jump with the process
    alive (the PC slept): her live ticks' span holds the gap, and the live
    tick charges it (Task 34), so the catch-up charges her affect nothing."""
    stayed_saved, stayed = _stayed_on(tmp_path / "stayed", clock, True)
    svc, saved = _first_hour(tmp_path / "slept", clock, True)
    clock.instant += timedelta(hours=GAP_HOURS)   # no reload: the process lived on
    if live_first:
        _ticks(svc, clock, 1)
        events = _catch_up_recorded(svc, float(GAP_HOURS))
    else:
        events = _catch_up_recorded(svc, float(GAP_HOURS))
        _ticks(svc, clock, 1)
    assert [e for e in events if e[0] == "tick"] == []
    # (Her regulation left out: a slot's recharge is the catch-up's activity, not its hours.)
    for key in ("loneliness", "fatigue"):
        assert _state(svc)[key] - saved[key] == pytest.approx(stayed[key] - stayed_saved[key], abs=1e-5), key


def test_a_live_tick_and_a_catch_up_tick_never_interleave_inside_her_affect(tmp_path, clock, host_hour):
    """Ruling T34b-R3. LifeService.start() runs its first ticks on a thread of
    its own while the host runs the catch-up on another, and an affect tick
    reads then writes her loneliness, mood and regulation: interleaved, one
    would write over the other's change (the hours of a whole gap). Every
    affect tick -- the live energy tick's and each of the catch-up's -- runs
    under LifeService._affect_tick_lock."""
    _first_hour(tmp_path, clock, True)
    clock.instant += timedelta(hours=GAP_HOURS)
    again = _service(tmp_path, clock)
    again._load_state()
    _no_plan(again)
    held = []
    real = again._affect.tick

    def spy(*args, **kwargs):
        held.append(again._affect_tick_lock.locked())
        return real(*args, **kwargs)

    again._affect.tick = spy
    try:
        _ticks(again, clock, 1)
        live = len(held)
        again.catch_up_from_downtime(float(GAP_HOURS))
    finally:
        del again._affect.tick
    assert live == 1 and len(held) > live
    assert all(held), held
