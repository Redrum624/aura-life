"""Sleep is a state with a duration, and fatigue runs in hours awake.

Measured before this change (``docs/analyses/aura-life-humanness_2026-09-25.html``,
section 2, and ``tests/sim_helpers.py`` reproduces it): personas "slept" about
ten times a day at any hour and spent 78-82% of their own sleep window doing
something awake, because ``EnergySystem.sleep()`` restored energy instantly and
falling asleep also needed effective energy below 0.4; and fatigue rose 0.005
per minute, crossing the 0.7 rest threshold about 2h20m after waking, so rest
was forced on 55-66% of ticks.

The model now (``aura_life.energy.energy_system``): sleep pressure rises per
hour awake and falls per hour asleep; each night's bedtime and wake time are
drawn once from the service rng around the persona's own schedule, with its
variances and weekend shifts; she falls asleep inside that window once the
pressure allows, stays asleep until the drawn wake time (earlier on a night
``wake_up_chance`` picks), and recovers energy across those hours. Rest is
forced once she has been up longer than her usual waking day.

"Her own sleep window" in the acceptance measures is each night's effective
window: her schedule's bedtime and wake time, with the weekend shifts on Friday
and Saturday nights (controller ruling R1, Task 3 fix round 1). The nightly
variance is not part of it and has to fit in the threshold's slack.

Two halves: three-day simulations of three schedules -- over weekday nights
and over a weekend -- for the acceptance measures, then the engine's rules one
at a time on a scripted clock.

The simulations run at the production cadence (``sim_helpers.PRODUCTION``:
each tick at ``LifeScheduler``'s own interval), which is what hosts run
(ruling T4-R3); ruling T4-R4 moved them there once Task 10 made hunger and its
energy drain per-hour rates with no drain while she sleeps -- per energy tick,
at the production cadence, the drain beat sleep's recovery. Rest is forced or
not on an activity tick, so the forced-rest measures count the steps whose
activity tick ran.
"""

import random
from datetime import date, datetime, time, timedelta

import pytest

from aura_life.activities import ActivityEngine
from aura_life.energy import EnergySystem
from aura_life.life_service import LifeService
from aura_life.models import TimeOfDay, Weather
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.scheduler.life_scheduler import LifeScheduler
from aura_life.world import WorldEnvironment

from sim_helpers import (
    PRODUCTION, SimPersona, effective_nights, in_sleep_window, in_windows, nominal_nights, run_days,
    sleep_episodes,
)


def _schedule(bed: int, wake: int, **overrides) -> dict:
    """A parsed ``sleep_schedule`` dict (the shape ``ParsedProfile`` emits)."""
    schedule = {
        "bedtime_hour": bed, "bedtime_minute": 0,
        "wake_hour": wake, "wake_minute": 0,
        "wake_up_chance": 0.05,
        "bedtime_variance": 60, "wake_variance": 45,
        "weekend_bedtime_shift": 60, "weekend_wake_shift": 60,
    }
    schedule.update(overrides)
    return schedule


#: Nothing random about the night: no variance, no weekend shift, no early wake.
FIXED = dict(bedtime_variance=0, wake_variance=0, weekend_bedtime_shift=0,
             weekend_wake_shift=0, wake_up_chance=0.0)

# ======================================================================
# 1. Three simulated days, three schedules -- the acceptance measures
# ======================================================================

SEED = 3
DAYS = 3
#: The production cadence's step: its smallest tick interval.
STEP_MINUTES = min(LifeScheduler.TICK_INTERVAL_MINUTES.values())
PERSONAS = [
    # No profile at all: the library default, 23:00-07:00.
    SimPersona("control"),
    # The two authored schedules the program's personas use.
    SimPersona("night_owl", sleep_schedule=_schedule(3, 11)),
    SimPersona("late_sleeper", sleep_schedule=_schedule(5, 13)),
]
IDS = [p.persona_id for p in PERSONAS]


@pytest.fixture(scope="module")
def trace(tmp_path_factory):
    """Monday 15:00 to Thursday 15:00: three weekday nights."""
    return run_days(PERSONAS, days=DAYS, seed=SEED, cadence=PRODUCTION,
                    data_dir=tmp_path_factory.mktemp("sleep_state"))


#: Thursday 15:00: the three nights are Thursday's, Friday's and Saturday's.
THURSDAY_1500 = datetime(2026, 10, 8, 15, 0)


@pytest.fixture(scope="module")
def weekend_trace(tmp_path_factory):
    """Thursday 15:00 to Sunday 15:00: a weekday night, then Friday's and
    Saturday's, which the weekend shifts move."""
    return run_days(PERSONAS, days=DAYS, seed=SEED, cadence=PRODUCTION,
                    start=THURSDAY_1500, data_dir=tmp_path_factory.mktemp("sleep_state_weekend"))


def _overlaps(episode, night) -> bool:
    onset, end = episode
    bedtime, wake = night
    return onset < wake and (end is None or end > bedtime)


def _asleep_share_of_effective_nights(trace, pid) -> tuple:
    nights = effective_nights(trace, pid)
    in_window = [r for r in trace.records[pid] if in_windows(r.t, nights)]
    return sum(r.asleep for r in in_window), len(in_window)


def test_the_run_is_clean_and_whole(trace):
    """No tick failed (force_tick only logs), and every step was recorded."""
    assert trace.errors == []
    assert trace.schedules["control"]["bedtime_hour"] == 23
    for pid in IDS:
        assert len(trace.records[pid]) == DAYS * 24 * 60 // STEP_MINUTES
        # Weekday nights: each night's effective window is her nominal one.
        assert effective_nights(trace, pid) == nominal_nights(trace, pid)


@pytest.mark.parametrize("pid", IDS)
def test_asleep_through_at_least_90_percent_of_her_own_window(trace, pid):
    schedule = trace.schedules[pid]
    in_window = [r for r in trace.records[pid] if in_sleep_window(r.t, schedule)]
    # Three whole eight-hour nights, one record per step.
    assert len(in_window) == DAYS * 8 * 60 // STEP_MINUTES
    asleep = sum(r.asleep for r in in_window)
    assert asleep / len(in_window) >= 0.90, f"{pid}: asleep {asleep}/{len(in_window)} in-window ticks"


@pytest.mark.parametrize("pid", IDS)
def test_exactly_one_main_sleep_episode_per_night(trace, pid):
    episodes = sleep_episodes(trace.records[pid])
    nights = nominal_nights(trace, pid)
    assert len(nights) == DAYS
    per_night = [sum(_overlaps(e, night) for e in episodes) for night in nights]
    assert per_night == [1] * DAYS, f"{pid}: episodes {episodes}"
    # ...and none anywhere else: every episode is some night's.
    assert len(episodes) == DAYS, f"{pid}: episodes {episodes}"


def test_the_weekend_run_spans_a_friday_and_a_saturday_night(weekend_trace):
    assert weekend_trace.errors == []
    for pid in IDS:
        schedule = weekend_trace.schedules[pid]
        nights = effective_nights(weekend_trace, pid)
        nominal = nominal_nights(weekend_trace, pid)
        assert len(nights) == len(nominal) == DAYS
        # Thursday's night as scheduled; Friday's and Saturday's shifted by
        # the schedule's weekend fields.
        shifts = [(bed - nominal_bed, wake - nominal_wake)
                  for (bed, wake), (nominal_bed, nominal_wake) in zip(nights, nominal)]
        weekend = (timedelta(minutes=schedule["weekend_bedtime_shift"]),
                   timedelta(minutes=schedule["weekend_wake_shift"]))
        assert shifts == [(timedelta(0), timedelta(0)), weekend, weekend], pid


@pytest.mark.parametrize("pid", IDS)
def test_asleep_through_at_least_90_percent_of_each_nights_window_over_a_weekend(weekend_trace, pid):
    asleep, in_window = _asleep_share_of_effective_nights(weekend_trace, pid)
    assert in_window == DAYS * 8 * 60 // STEP_MINUTES
    assert asleep / in_window >= 0.90, f"{pid}: asleep {asleep}/{in_window} in-window ticks"


@pytest.mark.parametrize("pid", IDS)
def test_exactly_one_main_sleep_episode_per_night_over_a_weekend(weekend_trace, pid):
    episodes = sleep_episodes(weekend_trace.records[pid])
    nights = effective_nights(weekend_trace, pid)
    per_night = [sum(_overlaps(e, night) for e in episodes) for night in nights]
    assert per_night == [1] * DAYS, f"{pid}: episodes {episodes}"
    assert len(episodes) == DAYS, f"{pid}: episodes {episodes}"


def _activity_ticks(records):
    """The steps whose activity tick ran (every fourth step at the production
    cadence): the only ones that decide on rest."""
    return [r for r in records if "activity" in r.ticks]


@pytest.mark.parametrize("pid", IDS)
def test_rest_is_forced_on_at_most_a_quarter_of_waking_ticks(trace, pid):
    waking = [r for r in _activity_ticks(trace.records[pid]) if not r.asleep]
    # Every waking step's activity tick took the decision -- a record with no
    # decision would count as "not forced" and flatter the measure.
    assert all(r.forced_rest is not None for r in waking)
    forced = sum(r.forced_rest for r in waking)
    assert forced / len(waking) <= 0.25, f"{pid}: rest forced on {forced}/{len(waking)} waking ticks"


@pytest.mark.parametrize("pid", IDS)
def test_the_variance_fields_move_the_nightly_times(trace, pid):
    """Not the same bedtime and wake time every night: the analysis found every
    sleep-variance field inert. That it is those fields that move the nights,
    and within their bounds, is pinned exactly by
    ``test_zero_variance_repeats_the_night_and_the_variance_fields_move_it``;
    here a night may also start early, when she carries a short night's
    pressure into an exhausted evening and collapses (``EnergySystem._collapsing``)."""
    episodes = sleep_episodes(trace.records[pid])
    assert len(episodes) == DAYS, f"{pid}: episodes {episodes}"
    nightly = {(onset.time(), end.time()) for onset, end in episodes}
    assert len(nightly) > 1, f"{pid}: every night ran {nightly}"


@pytest.mark.parametrize("pid", IDS)
def test_sleeping_is_logged_once_per_episode_at_its_onset(trace, pid):
    """One "sleeping" entry per night (it was ~10 a day), and never an
    ordinary activity choice: no entry that does not open an episode."""
    records = trace.records[pid]
    logged = [r.t for r in records if r.activity == "sleeping"]
    onsets = [onset for onset, _ in sleep_episodes(records)]
    assert logged == onsets


@pytest.mark.parametrize("pid", IDS)
def test_energy_recovers_across_the_night_not_at_once(trace, pid):
    step_hours = STEP_MINUTES / 60
    per_step = EnergySystem.SLEEP_ENERGY_RECOVERY_PER_HOUR * step_hours
    records = trace.records[pid]
    for onset, end in sleep_episodes(records):
        night = [r.energy for r in records if onset <= r.t and (end is None or r.t < end)]
        rises = [b - a for a, b in zip(night, night[1:])]
        # Never more than one step's recovery at a time: sleep() used to jump
        # straight to its end state.
        assert max(rises) <= per_step + 1e-9, f"{pid} {onset}: {night}"
        # ...and across the night it adds up: at least three hours' worth.
        assert night[-1] - night[0] >= 3 * EnergySystem.SLEEP_ENERGY_RECOVERY_PER_HOUR, f"{pid} {onset}: {night}"


@pytest.mark.parametrize("pid", IDS)
def test_naps_only_when_tired_and_at_most_one_per_waking_day(trace, pid):
    records = trace.records[pid]
    episodes = sleep_episodes(records)
    wakes = [trace.start] + [end for _, end in episodes if end is not None]
    naps = [r for r in records if r.activity == "napping"]
    for nap in naps:
        assert nap.activity_energy_before < EnergySystem.NAP_ENERGY_BELOW, f"{pid}: napped at {nap}"
    for day_start, day_end in zip(wakes, wakes[1:] + [None]):
        in_day = [n for n in naps if n.t >= day_start and (day_end is None or n.t < day_end)]
        assert len(in_day) <= 1, f"{pid}: naps {[n.t for n in in_day]}"


def test_an_ai_persona_never_sleeps_and_rest_is_forced_on_at_most_a_quarter_of_its_ticks(tmp_path):
    """Controller ruling R2: an AI runs on the same hours-scale fatigue and
    hours-awake rest threshold as a human, and never sleeps or naps."""
    companion = SimPersona(
        "companion",
        service_kwargs={"definition": PersonalityDefinition(persona_type="ai")},
    )
    ai_trace = run_days([companion], days=2, seed=SEED, cadence=PRODUCTION, data_dir=tmp_path)
    records = ai_trace.records["companion"]
    assert ai_trace.errors == []
    assert len(records) == 2 * 24 * 60 // STEP_MINUTES
    assert not any(r.asleep for r in records)
    assert not {"sleeping", "napping"} & {r.activity for r in records}
    assert not ai_trace.services["companion"].energy.is_asleep()
    ticks = _activity_ticks(records)
    assert all(r.forced_rest is not None for r in ticks)
    forced = sum(r.forced_rest for r in ticks)
    assert forced / len(ticks) <= 0.25, f"rest forced on {forced}/{len(ticks)} ticks"


# ======================================================================
# 2. The engine's rules, one at a time, on a scripted clock
# ======================================================================

class ScriptedClock:
    """A clock that advances only when told to (see tests/test_energy_clock.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


#: A Tuesday -- the night that follows is a weekday night.
TUESDAY = date(2026, 10, 6)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def _tick_until(energy: EnergySystem, clock: ScriptedClock, until: datetime,
                phase: TimeOfDay = TimeOfDay.AFTERNOON, step_hours: float = 0.25) -> None:
    while clock.instant < until:
        clock.advance(min(step_hours, (until - clock.instant).total_seconds() / 3600))
        energy.tick(phase)


def _woke_at(instant: datetime, schedule: dict = None) -> tuple:
    """An energy system whose last night's sleep has just ended at ``instant``."""
    clock = ScriptedClock(instant)
    energy = EnergySystem(sleep_schedule=schedule, now=clock)
    energy.sleep(hours=8.0)
    return energy, clock


def test_sleep_pressure_rises_per_hour_awake_whatever_the_tick_cadence():
    hourly, quarterly = ScriptedClock(_at(TUESDAY, 12)), ScriptedClock(_at(TUESDAY, 12))
    a, b = EnergySystem(now=hourly), EnergySystem(now=quarterly)
    start = a.sleep_pressure
    for _ in range(3):
        hourly.advance(1)
        a.tick(TimeOfDay.AFTERNOON)
    for _ in range(12):
        quarterly.advance(0.25)
        b.tick(TimeOfDay.AFTERNOON)
    assert a.sleep_pressure == pytest.approx(start + 3 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)
    assert b.sleep_pressure == pytest.approx(a.sleep_pressure)
    # Fatigue is that pressure: one number, on an hours scale.
    assert a.state.fatigue == a.sleep_pressure


def test_rest_is_not_forced_in_the_hours_after_waking():
    """The defect: fatigue crossed 0.7 about 2h20m after waking."""
    energy, clock = _woke_at(_at(TUESDAY, 7))
    for _ in range(4 * 12):  # twelve hours, through her morning and afternoon
        clock.advance(0.25)
        energy.tick(TimeOfDay.AFTERNOON)
        assert not energy.should_rest(), f"rest forced at {clock.instant.time()}"
    assert energy.state.fatigue == pytest.approx(12 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)


def test_rest_is_forced_once_she_is_up_longer_than_her_usual_day():
    energy, clock = _woke_at(_at(TUESDAY, 7))
    assert energy.usual_awake_hours == pytest.approx(16.0)  # 07:00 -> 23:00
    _tick_until(energy, clock, _at(TUESDAY, 22, 45), TimeOfDay.EVENING)
    assert not energy.should_rest()
    _tick_until(energy, clock, _at(TUESDAY, 23, 15), TimeOfDay.EVENING)
    assert energy.should_rest()


def test_she_falls_asleep_inside_her_window_once_the_pressure_allows():
    energy, clock = _woke_at(_at(TUESDAY, 7), _schedule(23, 7, **FIXED))
    rng = random.Random(1)
    _tick_until(energy, clock, _at(TUESDAY, 22, 45), TimeOfDay.EVENING)
    assert energy.update_sleep(rng=rng) is None  # sleepy, but not her bedtime yet
    _tick_until(energy, clock, _at(TUESDAY, 23), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) == "fell_asleep"
    assert energy.is_asleep()
    assert energy.hours_awake == 0.0


def test_inside_her_window_she_still_waits_for_enough_pressure():
    """Up at 20:00 (a long nap, a late shift): not sleepy at 23:00."""
    energy, clock = _woke_at(_at(TUESDAY, 20), _schedule(23, 7, **FIXED))
    rng = random.Random(1)
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 3), TimeOfDay.LATE_NIGHT)
    assert energy.sleep_pressure < EnergySystem.SLEEP_PRESSURE_TO_FALL_ASLEEP
    assert energy.update_sleep(rng=rng) is None
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 5, 30), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) == "fell_asleep"


def test_she_sleeps_until_her_wake_time_and_recovers_by_the_hour():
    energy, clock = _woke_at(_at(TUESDAY, 7), _schedule(23, 7, **FIXED))
    rng = random.Random(1)
    _tick_until(energy, clock, _at(TUESDAY, 23), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) == "fell_asleep"
    pressure, level = energy.sleep_pressure, energy.level
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 1), TimeOfDay.LATE_NIGHT)
    # Two hours asleep: pressure down two hours' fall, energy up two hours' recovery.
    assert energy.sleep_pressure == pytest.approx(pressure - 2 * energy.sleep_pressure_fall_per_hour)
    assert energy.level == pytest.approx(min(1.0, level + 2 * EnergySystem.SLEEP_ENERGY_RECOVERY_PER_HOUR))
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 6, 45), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) is None
    assert energy.is_asleep()
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 7), TimeOfDay.DAWN)
    assert energy.update_sleep(rng=rng) == "woke"
    assert not energy.is_asleep()
    assert energy.state.last_sleep_time == clock.instant
    # A usual night cleared a usual day's pressure.
    assert energy.sleep_pressure == pytest.approx(0.0, abs=1e-9)


def test_a_conversation_keeps_her_up_but_does_not_wake_her():
    """Sleep is a soft cap while the user chats; waking her is the host's call
    (``LifeService.force_wake``), so a message alone never ends her sleep."""
    energy, clock = _woke_at(_at(TUESDAY, 7), _schedule(23, 7, **FIXED))
    rng = random.Random(1)
    _tick_until(energy, clock, _at(TUESDAY, 23), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(in_conversation=True, rng=rng) is None
    _tick_until(energy, clock, _at(TUESDAY, 23, 15), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) == "fell_asleep"
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 2), TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(in_conversation=True, rng=rng) is None
    assert energy.is_asleep()


def _nights(schedule: dict, first: date, days: int, rng: random.Random) -> list:
    """The night drawn for each of ``days`` evenings from ``first``."""
    clock = ScriptedClock(_at(first, 16))
    energy = EnergySystem(sleep_schedule=schedule, now=clock)
    drawn = []
    for n in range(days):
        clock.instant = _at(first + timedelta(days=n), 16)
        energy.update_sleep(rng=rng)
        drawn.append(energy.night)
    return drawn


def test_each_night_is_drawn_once_from_the_rng_it_is_given():
    before = random.getstate()
    a = _nights(_schedule(23, 7), TUESDAY, 3, random.Random(5))
    b = _nights(_schedule(23, 7), TUESDAY, 3, random.Random(5))
    assert a == b
    assert [n.night for n in a] == [TUESDAY + timedelta(days=d) for d in range(3)]
    assert random.getstate() == before, "a night was drawn from module random"

    # Asking again the same evening draws nothing more.
    rng = random.Random(5)
    clock = ScriptedClock(_at(TUESDAY, 16))
    energy = EnergySystem(sleep_schedule=_schedule(23, 7), now=clock)
    energy.update_sleep(rng=rng)
    state = rng.getstate()
    clock.advance(3)
    energy.update_sleep(rng=rng)
    assert rng.getstate() == state


def test_zero_variance_repeats_the_night_and_the_variance_fields_move_it():
    fixed = _nights(_schedule(23, 7, **FIXED), TUESDAY, 3, random.Random(5))
    assert {(n.bedtime.time(), n.wake.time()) for n in fixed} == {(time(23), time(7))}

    varied = _nights(_schedule(23, 7, wake_up_chance=0.0), TUESDAY, 3, random.Random(5))
    assert len({n.bedtime.time() for n in varied}) == 3
    assert len({n.wake.time() for n in varied}) == 3
    for n in varied:
        nominal_bed = _at(n.night, 23)
        assert abs(n.bedtime - nominal_bed) <= timedelta(minutes=60)
        assert abs(n.wake - (nominal_bed + timedelta(hours=8))) <= timedelta(minutes=45)


def test_friday_and_saturday_nights_take_the_weekend_shifts():
    schedule = _schedule(23, 7, **dict(FIXED, weekend_bedtime_shift=90, weekend_wake_shift=60))
    thursday = date(2026, 10, 8)
    nights = _nights(schedule, thursday, 4, random.Random(5))
    assert [(n.bedtime, n.wake) for n in nights] == [
        (_at(thursday, 23), _at(thursday + timedelta(days=1), 7)),                 # Thu
        (_at(thursday + timedelta(days=2), 0, 30), _at(thursday + timedelta(days=2), 8)),  # Fri
        (_at(thursday + timedelta(days=3), 0, 30), _at(thursday + timedelta(days=3), 8)),  # Sat
        (_at(thursday + timedelta(days=3), 23), _at(thursday + timedelta(days=4), 7)),     # Sun
    ]


def test_wake_up_chance_can_end_her_night_early():
    calm = _nights(_schedule(23, 7, wake_up_chance=0.0), TUESDAY, 1, random.Random(9))[0]
    restless = _nights(_schedule(23, 7, wake_up_chance=1.0), TUESDAY, 1, random.Random(9))[0]
    assert not calm.early_wake and restless.early_wake
    assert restless.bedtime == calm.bedtime
    assert calm.wake - timedelta(minutes=45) <= restless.wake < calm.wake

    # ...and a night she woke early from is over: she does not go back to sleep.
    energy, clock = _woke_at(_at(TUESDAY, 7), _schedule(23, 7, wake_up_chance=1.0))
    rng = random.Random(9)
    _tick_until(energy, clock, _at(TUESDAY, 16), TimeOfDay.AFTERNOON)
    energy.update_sleep(rng=rng)
    night = energy.night
    _tick_until(energy, clock, night.bedtime, TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) == "fell_asleep"
    _tick_until(energy, clock, night.wake, TimeOfDay.LATE_NIGHT)
    assert energy.update_sleep(rng=rng) == "woke"
    _tick_until(energy, clock, night.wake + timedelta(minutes=30), TimeOfDay.DAWN)
    assert energy.update_sleep(rng=rng) is None
    assert not energy.is_asleep()


def test_an_ai_energy_system_never_sleeps():
    clock = ScriptedClock(_at(TUESDAY, 2))
    energy = EnergySystem(sleep_schedule=_schedule(23, 7, **FIXED), is_ai=True, now=clock)
    energy.state.fatigue = 1.0
    assert energy.update_sleep(rng=random.Random(0)) is None
    assert not energy.is_asleep()
    assert not energy.should_sleep()
    assert not energy.can_nap(TimeOfDay.AFTERNOON)


def test_an_ai_runs_on_the_same_hours_scale_and_rests_through_its_night_awake():
    """Ruling R2: the same fatigue per hour awake and the same rest threshold
    as a human. It never sleeps, so its night is a rest: awake and reachable,
    its pressure falling at the sleep rate, its day starting over at dawn."""
    clock = ScriptedClock(_at(TUESDAY, 7))
    energy = EnergySystem(sleep_schedule=_schedule(23, 7, **FIXED), is_ai=True, now=clock)
    energy.start_on_schedule()
    assert energy.hours_awake == 0.0 and energy.sleep_pressure == 0.0
    rng = random.Random(0)
    before = rng.getstate()

    _tick_until(energy, clock, _at(TUESDAY, 19), TimeOfDay.EVENING)
    assert energy.sleep_pressure == pytest.approx(12 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)
    energy.state.level = 0.6
    assert not energy.should_rest()  # twelve hours up: not its line

    # Kept past its usual day, it is forced to rest, as a human is.
    _tick_until(energy, clock, _at(TUESDAY, 23), TimeOfDay.NIGHT)
    energy.state.level = 0.6
    assert energy.should_rest()

    # Its night: awake, never asleep, the pressure falling and energy back.
    assert energy.update_sleep(rng=rng) is None
    level = energy.level
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 3), TimeOfDay.LATE_NIGHT)
    assert not energy.is_asleep()
    assert not energy.should_rest()
    assert energy.hours_awake == 0.0
    assert energy.sleep_pressure == pytest.approx(
        16 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR - 4 * energy.sleep_pressure_fall_per_hour)
    assert energy.level == pytest.approx(min(1.0, level + 4 * EnergySystem.SLEEP_ENERGY_RECOVERY_PER_HOUR))

    # Dawn: its day starts over.
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 7), TimeOfDay.DAWN)
    assert energy.update_sleep(rng=rng) is None
    _tick_until(energy, clock, _at(TUESDAY + timedelta(days=1), 10), TimeOfDay.MORNING)
    assert energy.hours_awake == pytest.approx(3.0)
    assert rng.getstate() == before, "an AI's night drew from the rng"


def test_a_nap_needs_her_tired_outside_her_night_and_once_per_waking_day():
    energy, clock = _woke_at(_at(TUESDAY, 7))
    _tick_until(energy, clock, _at(TUESDAY, 14), TimeOfDay.AFTERNOON)
    energy.state.level = EnergySystem.NAP_ENERGY_BELOW + 0.2
    assert not energy.can_nap(TimeOfDay.AFTERNOON)            # not tired
    energy.state.level = EnergySystem.NAP_ENERGY_BELOW - 0.1
    assert energy.can_nap(TimeOfDay.AFTERNOON)
    assert not energy.can_nap(TimeOfDay.LATE_NIGHT)           # that close to bed she waits
    pressure = energy.sleep_pressure
    energy.nap(30)
    # A nap is sleep: the pressure falls at the sleep rate for its length.
    assert energy.sleep_pressure == pytest.approx(pressure - 0.5 * energy.sleep_pressure_fall_per_hour)
    energy.state.level = EnergySystem.NAP_ENERGY_BELOW - 0.1
    assert not energy.can_nap(TimeOfDay.AFTERNOON)            # one a day
    energy.sleep(hours=8.0)                                   # a new day
    energy.state.level = EnergySystem.NAP_ENERGY_BELOW - 0.1
    assert energy.can_nap(TimeOfDay.AFTERNOON)


def test_rest_does_not_clear_sleep_pressure():
    """Only sleep does: relaxing all evening must not keep her up at bedtime."""
    energy, clock = _woke_at(_at(TUESDAY, 7))
    _tick_until(energy, clock, _at(TUESDAY, 20), TimeOfDay.EVENING)
    pressure, level = energy.sleep_pressure, energy.level
    energy.restore_energy(0.1)
    assert energy.level == pytest.approx(min(1.0, level + 0.1))
    assert energy.sleep_pressure == pressure


def test_catching_up_inside_her_window_puts_her_to_sleep():
    """``adjust_for_time`` (downtime catch-up) sets the sleep state as well."""
    clock = ScriptedClock(_at(TUESDAY, 2))
    energy = EnergySystem(sleep_schedule=_schedule(23, 7, **FIXED), now=clock)
    energy.adjust_for_time(TimeOfDay.LATE_NIGHT)
    assert energy.is_asleep()
    assert energy.hours_awake == 0.0
    clock.instant = _at(TUESDAY, 7)
    assert energy.update_sleep(rng=random.Random(0)) == "woke"

    clock = ScriptedClock(_at(TUESDAY, 21))
    energy = EnergySystem(sleep_schedule=_schedule(23, 7, **FIXED), now=clock)
    energy.adjust_for_time(TimeOfDay.NIGHT)
    assert not energy.is_asleep()
    assert energy.sleep_pressure == pytest.approx(14 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)
    clock.advance(1)
    energy.tick(TimeOfDay.NIGHT)
    assert energy.hours_awake == pytest.approx(15.0)


def test_select_activity_never_returns_an_excluded_activity():
    engine = ActivityEngine()
    random.seed(11)
    picked = {
        engine.select_activity(
            energy_level=0.1, time_of_day=TimeOfDay.LATE_NIGHT, weather=Weather.CLEAR_NIGHT,
            current_location="home", force_rest=True, exclude={"sleeping", "napping"},
        ).name
        for _ in range(200)
    }
    assert picked and not picked & {"sleeping", "napping"}


def test_is_asleep_follows_her_sleep_not_the_clock(tmp_path):
    """The host's sleep guard reads ``LifeService.is_asleep()``. It answered
    from the clock -- inside the window's hours meant asleep -- and now answers
    from her sleep."""
    clock = ScriptedClock(_at(TUESDAY, 22))
    svc = LifeService(
        db_path=str(tmp_path / "life.db"), persona_id="sleeper",
        world_environment=WorldEnvironment(now=clock),
        sleep_schedule=_schedule(23, 7, **dict(FIXED, wake_minute=30)),
    )
    rng = random.Random(0)
    assert not svc.is_asleep()
    # Up late with the user: inside her window, and awake.
    clock.instant = _at(TUESDAY, 23)
    assert svc.energy.update_sleep(in_conversation=True, rng=rng) is None
    assert not svc.is_asleep()
    clock.instant = _at(TUESDAY, 23, 30)
    assert svc.energy.update_sleep(rng=rng) == "fell_asleep"
    assert svc.is_asleep()
    # 07:15 is past the hour her window names, but her night runs to 07:30.
    clock.instant = _at(TUESDAY + timedelta(days=1), 7, 15)
    assert svc.energy.update_sleep(rng=rng) is None
    assert svc.is_asleep()
    clock.instant = _at(TUESDAY + timedelta(days=1), 7, 30)
    assert svc.energy.update_sleep(rng=rng) == "woke"
    assert not svc.is_asleep()


def test_the_sleep_state_survives_a_save_and_a_reload(tmp_path):
    clock = ScriptedClock(_at(TUESDAY, 20))
    world = WorldEnvironment(now=clock)
    kwargs = dict(db_path=str(tmp_path / "life.db"), persona_id="sleeper", world_environment=world,
                  sleep_schedule=_schedule(23, 7))
    svc = LifeService(**kwargs)
    svc._load_state()  # inserts the energy row, as start() does
    rng = random.Random(0)
    svc.energy.update_sleep(rng=rng)
    clock.instant = svc.energy.night.bedtime + timedelta(minutes=5)
    assert svc.energy.update_sleep(rng=rng) == "fell_asleep"
    svc._save_state()

    # A brand-new persona has no drawn night yet (start_on_schedule): this one
    # has it only if it was loaded.
    again = LifeService(**kwargs)
    assert again.energy.night is None
    again._load_state()
    assert again.energy.is_asleep()
    assert again.energy.night == svc.energy.night
    clock.instant = svc.energy.night.wake
    assert again.energy.update_sleep(rng=random.Random(0)) == "woke"


# ----------------------------------------------------------------------
# A brand-new persona starts on her own schedule (ruling R3)
# ----------------------------------------------------------------------

def _new_persona(tmp_path, instant: datetime) -> tuple:
    """A persona created at ``instant`` on the world clock, with nothing saved."""
    clock = ScriptedClock(instant)
    svc = LifeService(
        db_path=str(tmp_path / "life.db"), persona_id="newcomer",
        world_environment=WorldEnvironment(now=clock), sleep_schedule=_schedule(23, 7),
    )
    return svc, clock


def test_a_new_persona_created_inside_her_night_is_asleep_at_once(tmp_path):
    svc, _ = _new_persona(tmp_path, _at(TUESDAY + timedelta(days=1), 2))  # Wednesday 02:00
    assert svc.is_asleep()
    energy = svc.energy
    # Three hours into her night: a usual day's pressure, three hours slept off.
    assert energy.sleep_pressure == pytest.approx(
        16 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR - 3 * energy.sleep_pressure_fall_per_hour)
    assert energy.hours_awake == 0.0
    # ...and so is the fresh-state path of start(): no saved energy, same answer.
    svc._load_state()
    assert svc.is_asleep()
    # She sleeps on until that night's wake time, not back up on her first tick.
    assert svc.energy.update_sleep(rng=random.Random(0)) is None
    assert svc.is_asleep()


def test_a_new_persona_created_in_the_afternoon_has_been_up_since_her_wake_time(tmp_path):
    svc, clock = _new_persona(tmp_path, _at(TUESDAY, 15))
    assert not svc.is_asleep()
    assert svc.energy.hours_awake == pytest.approx(8.0)
    assert svc.energy.sleep_pressure == pytest.approx(8 * EnergySystem.SLEEP_PRESSURE_RISE_PER_HOUR)
    # The next tick keeps counting from that wake time.
    clock.advance(0.25)
    svc.energy.tick(TimeOfDay.AFTERNOON)
    assert svc.energy.hours_awake == pytest.approx(8.25)


def test_a_new_persona_reads_her_own_timezone_when_she_has_one(tmp_path, monkeypatch):
    """Persona-local 02:00 while the world clock (the server's) says 11:00."""
    from aura_life import hooks

    saved = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}
    hooks.configure(persona_now=lambda timezone=None: _at(TUESDAY + timedelta(days=1), 2))
    try:
        svc, _ = _new_persona(tmp_path, _at(TUESDAY + timedelta(days=1), 11))
        assert not svc.is_asleep()  # built before her place (and zone) loaded
        monkeypatch.setattr(svc, "_persona_timezone", lambda: "Pacific/Kiritimati")
        svc._load_state()  # no saved energy: starts her again, in her own zone
        assert svc.is_asleep()
    finally:
        hooks.reset()
        hooks.configure(**{name: p for name, p in saved.items() if p is not None})


def test_a_loaded_persona_keeps_the_state_she_saved(tmp_path):
    """Starting on the schedule is for a persona with nothing saved."""
    clock = ScriptedClock(_at(TUESDAY, 15))
    kwargs = dict(db_path=str(tmp_path / "life.db"), persona_id="returning",
                  world_environment=WorldEnvironment(now=clock), sleep_schedule=_schedule(23, 7))
    svc = LifeService(**kwargs)
    svc._load_state()
    svc.energy.state.fatigue = 0.123  # a value no schedule would give her
    svc._save_state()

    clock.instant = _at(TUESDAY + timedelta(days=1), 2)  # inside her night
    again = LifeService(**kwargs)
    assert again.is_asleep()  # what a brand-new persona gets at 02:00...
    again._load_state()
    assert not again.is_asleep()  # ...replaced by what she saved
    assert again.energy.state.fatigue == pytest.approx(0.123)


# ----------------------------------------------------------------------
# Each night from a stream of its own (controller ruling T4-R1)
# ----------------------------------------------------------------------

def _tonights_night(tmp_path, name: str, rng, burn: int = 0):
    """The night a service draws on its first activity tick at Tuesday 16:00,
    after ``burn`` values were drawn from its injected rng by something else."""
    clock = ScriptedClock(_at(TUESDAY, 16))
    svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                      world_environment=WorldEnvironment(now=clock),
                      sleep_schedule=_schedule(23, 7), rng=rng)
    for _ in range(burn):
        rng.random()
    svc._on_activity_tick()
    return svc.energy.night


def test_other_draws_on_the_service_rng_do_not_move_her_nights(tmp_path):
    """Her nights come from a stream derived from the injected rng: the same
    seed gives the same nights, and how many values anything else draws from
    that rng cannot move her bedtime (as a mood change once did, through the
    life-event draws)."""
    quiet = _tonights_night(tmp_path, "quiet", random.Random(7))
    busy = _tonights_night(tmp_path, "busy", random.Random(7), burn=250)
    assert quiet is not None
    assert busy == quiet
    other_seed = _tonights_night(tmp_path, "other", random.Random(8))
    assert other_seed != quiet


def test_without_an_injected_rng_her_nights_still_come_from_module_random(tmp_path):
    svc = LifeService(db_path=str(tmp_path / "plain.db"), persona_id="plain",
                      sleep_schedule=_schedule(23, 7))
    assert svc._sleep_rng is random
