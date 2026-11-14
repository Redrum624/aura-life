"""Task 34: her loneliness, regulation and empathic fatigue on the hours scale.

The controller's probe of 2026-11-13 (one AffectSystem per tick interval,
default traits, 72 world hours, no interaction) found the three updates
ignoring ``hours``: each added or removed a fixed amount PER TICK, so at the
15-minute cadence of the simulation harness she had a third of the
loneliness, regulation came back three times slower and her empathic
fatigue lasted three times longer than at the scheduler's 5-minute energy
tick, and at 60- or 120-minute ticks a twelfth or a twenty-fourth.

Now a tick of ``hours`` does what ``hours / DEFAULT_TICK_HOURS`` default
ticks ending at its ``now`` did, and one default tick (and ``hours=None``)
does bit for bit what a tick always did: the production cadence does not
move (ruling R18; the trace pin in test_settings.py stays byte-identical).
"""

from datetime import datetime, timedelta

import pytest

from aura_life.affect.affect_system import DEFAULT_TICK_HOURS, AffectSystem

START = datetime(2031, 3, 10, 8, 0)
#: Awake, fed, rested and well: nothing in her body raises a stressor or
#: pulls her mood (the probe's body).
BODY = {"hunger": 0.2, "hours_awake": 4.0, "sleep_pressure": 0.1, "illness": 0.0, "asleep": False}
#: The production energy tick, the harness's 15 minutes, two long ones, and
#: two that are not a whole number of default ticks (0.4 and 1.4 of them):
#: the host passes the world clock's real-valued gap between two scheduler
#: fires, so a count of default ticks rounded or cut to a whole number would
#: let a 2-minute tick move nothing (fix round 1, T34-R1).
INTERVALS = (2, 5, 7, 15, 60, 120)


def _engine(level=0.0, last=None, capacity=None, fatigue=0.0, absorbed=0.0, emotion=None):
    aff = AffectSystem()
    aff._loneliness.level = level
    aff._loneliness.lifetime_peak = level
    aff._loneliness.last_meaningful_interaction = last
    if capacity is not None:
        aff._regulation.capacity = capacity
    aff._empathy.empathic_fatigue = fatigue
    aff._empathy.absorbed_intensity = absorbed
    aff._empathy.current_absorbed_emotion = emotion if absorbed else None
    return aff


def _tick(aff, hours, now):
    aff.tick(BODY, {}, "clear", "spring", hours=hours, now=now)


def _run(aff, minutes, total_hours, start=START, stops=()):
    """Tick ``aff`` every ``minutes`` for ``total_hours`` from ``start``,
    passing ``hours`` and ``now`` as LifeService does; yield the world hour
    after each tick. Where the cadence does not land on ``total_hours`` or on
    a world hour in ``stops`` (7-minute ticks on 24 h), one more tick lands
    there and splits that gap in two, as a scheduler fire in between would."""
    end = round(total_hours * 60)
    marks = set(range(minutes, end + 1, minutes)) | {end} | {round(stop * 60) for stop in stops}
    previous = 0
    for mark in sorted(marks):
        _tick(aff, (mark - previous) / 60, start + timedelta(minutes=mark))
        previous = mark
        yield mark / 60


def _within_a_tick(minutes):
    """How far apart this cadence's first tick at or past a world instant and
    the 5-minute cadence's can be: each lands less than its own tick after
    it, so less than the longer of the two ticks apart."""
    return max(minutes, 5) / 60 + 1e-9


def _first_hour(aff, minutes, total_hours, reached):
    for hour in _run(aff, minutes, total_hours):
        if reached(aff):
            return hour
    return None


def _state(aff):
    return (aff._loneliness.level, aff._loneliness.lifetime_peak, aff._regulation.capacity,
            aff._empathy.empathic_fatigue, aff._empathy.absorbed_intensity,
            aff._empathy.current_absorbed_emotion)


# ---------------------------------------------------------------------------
# (a) loneliness
# ---------------------------------------------------------------------------

def test_loneliness_with_no_interaction_is_the_same_at_24_hours_at_every_interval():
    """Before: 0.72 / 0.24 / 0.06 / 0.03 at 5 / 15 / 60 / 120-minute ticks.
    A tick count rounded to a whole number gives 0 at 2 minutes and 0.515 at
    7 (T34-R1)."""
    levels = {}
    for minutes in INTERVALS:
        aff = _engine()
        for _ in _run(aff, minutes, 24):
            pass
        levels[minutes] = aff._loneliness.level
    assert levels[5] == pytest.approx(0.72, abs=1e-9)
    for minutes in INTERVALS:
        assert levels[minutes] == pytest.approx(levels[5], abs=1e-9), levels


def test_loneliness_from_a_last_interaction_is_full_within_a_tick_of_25_hours_at_every_interval():
    """Before: first at 0.99 or more at 25.0 / 40.25 h, never in 72 h at 60 and
    120 minutes."""
    firsts, at_24 = {}, {}
    for minutes in INTERVALS:
        aff = _engine(last=START)
        for hour in _run(aff, minutes, 72, stops=(24,)):
            if hour == 24:
                at_24[minutes] = aff._loneliness.level
            if aff._loneliness.level >= 0.99 and minutes not in firsts:
                firsts[minutes] = hour
    assert firsts[5] == pytest.approx(25.0, abs=1e-9)
    for minutes in INTERVALS:
        assert minutes in firsts, firsts
        assert abs(firsts[minutes] - 25.0) <= _within_a_tick(minutes), firsts
        assert at_24[minutes] == pytest.approx(at_24[5], abs=1e-9), at_24


# ---------------------------------------------------------------------------
# (b) regulation, empathic fatigue, an absorbed emotion
# ---------------------------------------------------------------------------

def test_regulation_is_half_way_back_within_a_tick_of_its_production_time_at_every_interval():
    """From 0.2: before, 2.92 / 8.75 / 35 / 70 h."""
    firsts = {}
    for minutes in INTERVALS:
        aff = _engine(capacity=0.2)
        half = 0.2 + (aff._regulation.baseline - 0.2) / 2
        firsts[minutes] = _first_hour(aff, minutes, 72, lambda a: a._regulation.capacity >= half)
    assert firsts[5] == pytest.approx(35 * DEFAULT_TICK_HOURS, abs=1e-9)  # 2.92 h
    for minutes in INTERVALS:
        assert firsts[minutes] is not None, firsts
        assert abs(firsts[minutes] - firsts[5]) <= _within_a_tick(minutes), firsts


def test_empathic_fatigue_is_gone_within_a_tick_of_8_33_hours_at_every_interval():
    """0.5 -> 0: before, 8.33 / 25 h, never in 72 h at 60 and 120 minutes."""
    firsts = {}
    for minutes in INTERVALS:
        aff = _engine(fatigue=0.5)
        firsts[minutes] = _first_hour(aff, minutes, 72, lambda a: a._empathy.empathic_fatigue <= 0.0)
    assert firsts[5] == pytest.approx(100 * DEFAULT_TICK_HOURS, abs=1e-9)  # 8.33 h
    for minutes in INTERVALS:
        assert firsts[minutes] is not None, firsts
        assert abs(firsts[minutes] - firsts[5]) <= _within_a_tick(minutes), firsts


def test_an_absorbed_emotion_fades_over_the_same_world_time_at_every_interval():
    """0.8 fades by 0.24 an hour (0.02 a 5-minute tick) and is let go under
    0.01: the same intensity two hours on, and gone within a tick of the
    same hour, at every interval."""
    at_2, gone = {}, {}
    for minutes in INTERVALS:
        aff = _engine(absorbed=0.8, emotion="sad")
        for hour in _run(aff, minutes, 12, stops=(2,)):
            if hour == 2:
                at_2[minutes] = aff._empathy.absorbed_intensity
            if aff._empathy.current_absorbed_emotion is None and minutes not in gone:
                gone[minutes] = hour
                assert aff._empathy.absorbed_intensity == 0.0
    assert at_2[5] == pytest.approx(0.8 - 24 * 0.02, abs=1e-9)
    assert gone[5] == pytest.approx(40 * DEFAULT_TICK_HOURS, abs=1e-9)  # 3.33 h
    for minutes in INTERVALS:
        assert at_2[minutes] == pytest.approx(at_2[5], abs=1e-9), at_2
        assert abs(gone[minutes] - gone[5]) <= _within_a_tick(minutes), gone


# ---------------------------------------------------------------------------
# (c) one long tick is that many default ticks
# ---------------------------------------------------------------------------

#: (name, _engine kwargs, span in hours). The loneliness rows cover no
#: interaction yet, the 4-hour mark inside the span (on the 5-minute grid and
#: off it, between two default ticks) and the whole span past it.
LONG_TICK_CASES = [
    ("no interaction yet", dict(level=0.1), 6),
    ("no interaction yet", dict(level=0.1), 0.5),
    ("last interaction at the start", dict(level=0.1, last=START), 6),
    ("last interaction 3.75 h before", dict(level=0.1, last=START - timedelta(hours=3, minutes=45)), 0.5),
    ("last interaction 10 h before", dict(level=0.1, last=START - timedelta(hours=10)), 6),
    ("last interaction 10 h before", dict(level=0.1, last=START - timedelta(hours=10)), 0.5),
    ("last interaction off the grid", dict(level=0.1, last=START + timedelta(minutes=2, seconds=30)), 6),
    ("last interaction off the grid", dict(level=0.1, last=START - timedelta(hours=3, minutes=47, seconds=30)),
     0.5),
    ("regulation from 0.2", dict(capacity=0.2), 6),
    ("regulation from 0.2", dict(capacity=0.2), 0.5),
    ("regulation from above its baseline", dict(capacity=0.95), 6),
    ("regulation from above its baseline", dict(capacity=0.95), 0.5),
    ("empathic fatigue 0.5", dict(fatigue=0.5), 6),
    ("empathic fatigue 0.5", dict(fatigue=0.5), 0.5),
    ("absorbed 0.9", dict(absorbed=0.9, emotion="sad"), 6),
    ("absorbed 0.9", dict(absorbed=0.9, emotion="sad"), 0.5),
]


@pytest.mark.parametrize("name, state, span_hours", LONG_TICK_CASES,
                         ids=[f"{n}-{s}" for n, _, s in LONG_TICK_CASES])
def test_one_long_tick_does_what_that_many_default_ticks_did(name, state, span_hours):
    """(c) One 6-hour tick equals 72 five-minute ticks (and a half-hour tick
    6) for loneliness, regulation, empathic fatigue and an absorbed emotion."""
    stepped = _engine(**state)
    for _ in _run(stepped, 5, span_hours):
        pass
    long = _engine(**state)
    _tick(long, span_hours, START + timedelta(hours=span_hours))
    for got, want in zip(_state(long), _state(stepped)):
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=1e-9), (_state(long), _state(stepped))
        else:
            assert got == want


# ---------------------------------------------------------------------------
# (d) one default tick is bit for bit what a tick always did
# ---------------------------------------------------------------------------

NOW = START + timedelta(hours=30)
#: Three starting states, each of the four quantities somewhere else: the
#: second has her last interaction one minute past the 4-hour mark (inside one
#: default tick), fatigue that floors at 0 and an absorbed emotion let go. The
#: first and third capacities (0.1, 0.05) are ones where the pull written
#: ``diff * (1 - 0.98)`` -- the same math -- lands one ulp off ``diff * 0.02``
#: (measured: from 0.2 to 0.95 by 0.05 the two round to the same sum).
DEFAULT_TICK_STATES = [
    dict(level=0.3, capacity=0.1, fatigue=0.5, absorbed=0.8, emotion="sad"),
    dict(level=0.6, last=NOW - timedelta(hours=4, minutes=1), capacity=0.95, fatigue=0.003,
         absorbed=0.015, emotion="anxious"),
    dict(level=0.97, last=NOW - timedelta(hours=29, minutes=17), capacity=0.05, fatigue=0.0, absorbed=0.0),
]


def _old_tick(state, baseline, desired):
    """The per-tick expressions as the code had them at 4767a6e."""
    level = state["level"]
    last = state.get("last")
    if not last:
        level = min(1.0, level + 0.005 * desired)
    else:
        hours_since = (NOW - last).total_seconds() / 3600
        level = min(1.0, level + desired * 0.003 * max(0, hours_since - 4) / 4)
    capacity = state["capacity"]
    capacity += (baseline - capacity) * 0.02
    fatigue = max(0.0, state["fatigue"] - 0.005)
    absorbed, emotion = state["absorbed"], state.get("emotion") if state["absorbed"] else None
    if absorbed > 0:
        absorbed = max(0.0, absorbed - 0.02)
        if absorbed < 0.01:
            absorbed, emotion = 0.0, None
    return level, capacity, fatigue, absorbed, emotion


@pytest.mark.parametrize("hours", [DEFAULT_TICK_HOURS, None], ids=["DEFAULT_TICK_HOURS", "None"])
@pytest.mark.parametrize("state", DEFAULT_TICK_STATES, ids=["first", "second", "third"])
def test_one_default_tick_moves_each_quantity_by_exactly_its_old_amount(state, hours):
    aff = _engine(**state)
    want = _old_tick(state, aff._regulation.baseline, aff._loneliness.desired_contact_baseline)
    _tick(aff, hours, NOW)
    got = (aff._loneliness.level, aff._regulation.capacity, aff._empathy.empathic_fatigue,
           aff._empathy.absorbed_intensity, aff._empathy.current_absorbed_emotion)
    assert got == want
    assert aff._loneliness.lifetime_peak == max(state["level"], want[0])


# ---------------------------------------------------------------------------
# (e) the limits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hours", [0.0, -3.0], ids=["zero", "negative"])
@pytest.mark.parametrize("state", DEFAULT_TICK_STATES + [dict(level=0.4, capacity=0.3, fatigue=0.2,
                                                              absorbed=0.005, emotion="sad")],
                         ids=["first", "second", "third", "absorbed under 0.01"])
def test_no_world_time_moves_nothing(state, hours):
    aff = _engine(**state)
    before = _state(aff)
    _tick(aff, hours, NOW)
    assert _state(aff) == before


@pytest.mark.parametrize("state", DEFAULT_TICK_STATES + [dict(level=0.0, last=NOW - timedelta(days=40),
                                                              capacity=0.0, fatigue=1.0, absorbed=1.0,
                                                              emotion="sad")],
                         ids=["first", "second", "third", "extremes"])
def test_a_thirty_day_tick_keeps_every_value_inside_its_bounds(state):
    aff = _engine(**state)
    start_capacity, baseline = aff._regulation.capacity, aff._regulation.baseline
    _tick(aff, 30 * 24, NOW)
    assert 0.0 <= aff._loneliness.level <= 1.0
    assert aff._loneliness.level <= aff._loneliness.lifetime_peak <= 1.0
    assert 0.0 <= aff._regulation.capacity <= 1.0
    assert min(start_capacity, baseline) <= aff._regulation.capacity <= max(start_capacity, baseline)
    assert 0.0 <= aff._empathy.empathic_fatigue <= 1.0
    assert 0.0 <= aff._empathy.absorbed_intensity <= 1.0
