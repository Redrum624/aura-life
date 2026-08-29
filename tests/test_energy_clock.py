"""The energy engine's clock is injectable, and by default it is the wall clock.

Why this file exists -- the defect, measured downstream. ``EnergySystem`` read
``datetime.now()`` for ``hours_awake``. That is correct for a companion app that
lives as long as the person using it, and wrong for anything that *simulates*
time: the same state, ticked by two processes of different age, produced two
different energies. Hollow (the sandbox consumer) feeds energy into a compliance
score that can end an agent's life, and a shorter roster changes how many random
draws the next hour spends -- so a run replayed from its own manifest buried a
different set of people than the run it was replaying. Same seed, same epoch,
same roster, same directives; the only difference was how long the server had
been up. 2 of 8 seeds diverged inside 8 simulated days.

An energy engine that reads the host wall clock cannot be simulated, replayed, or
unit-tested by any consumer without freezing global state. That is a library
defect, not a consumer's inconvenience, which is why the seam is here.

The seam. ``WorldEnvironment`` carries the clock (``now=`` at construction,
``WorldEnvironment.now()`` to read it, overridable in a subclass), and
``LifeService`` hands that bound method to ``EnergySystem``. Nothing was removed
and no signature changed incompatibly: ``now`` defaults to ``datetime.now``
everywhere, so a caller that passes nothing gets exactly what it got before.

The two properties asserted here are the ones the fix has to be worth:
  1. the same simulated clock gives the same energy twice, and
  2. the default still reads the wall clock.
"""

from datetime import datetime, timedelta

import pytest

from aura_life.energy import EnergySystem
from aura_life.life_service import LifeService
from aura_life.models import TimeOfDay
from aura_life.world import WorldEnvironment


class ScriptedClock:
    """A clock that advances only when told to -- the sandbox's clock in miniature.

    Deliberately not ``freezegun`` or a ``datetime`` monkeypatch: the point of the
    seam is that a consumer needs no global state surgery to drive simulated
    time, so the test drives it the way a consumer would.
    """

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


EPOCH = datetime(2026, 3, 14, 6, 0, 0)

#: One simulated day, an hour at a time, through the circadian buckets.
DAY = [
    (1, TimeOfDay.DAWN), (2, TimeOfDay.MORNING), (4, TimeOfDay.MORNING),
    (3, TimeOfDay.AFTERNOON), (4, TimeOfDay.EVENING), (3, TimeOfDay.NIGHT),
    (5, TimeOfDay.LATE_NIGHT), (2, TimeOfDay.DAWN),
]


def _run_a_simulated_day(clock: ScriptedClock) -> EnergySystem:
    """Build a system on *clock* and tick it through ``DAY``."""
    energy = EnergySystem(now=clock)
    for hours, phase in DAY:
        clock.advance(hours)
        energy.tick(phase)
    return energy


# ----------------------------------------------------------------------
# 1. The same simulated clock gives the same energy twice
# ----------------------------------------------------------------------

def test_the_same_simulated_clock_gives_the_same_energy_twice():
    """Two systems, two independent clocks over the same script, one answer.

    The equality alone would be weak: on Windows ``datetime.now()`` moves in
    ~16ms steps, so two wall-clock runs of a script this short can easily land
    inside one tick and agree by accident. So the absolute value is pinned too
    -- ``DAY`` advances exactly 24 simulated hours on top of the 8 the initial
    state is seeded with. A system reading the host clock cannot produce 32.
    """
    first = _run_a_simulated_day(ScriptedClock(EPOCH))
    second = _run_a_simulated_day(ScriptedClock(EPOCH))

    assert sum(hours for hours, _ in DAY) == 24
    assert first.hours_awake == pytest.approx(32.0)

    assert first.to_dict() == second.to_dict()
    assert first.get_status() == second.get_status()
    assert first.export_state() == second.export_state()


def test_the_same_simulated_clock_gives_the_same_energy_however_old_the_process_is():
    """The measured defect, as an assertion.

    Two runs of the identical script, separated by a simulated *year* of clock --
    the stand-in for "this process has been alive for ten hours" versus "this is
    a fresh replay". On the wall clock these two disagreed; on an injected clock
    they cannot, because nothing in the engine can see how old the process is.
    """
    fresh = _run_a_simulated_day(ScriptedClock(EPOCH))
    aged = _run_a_simulated_day(ScriptedClock(EPOCH + timedelta(days=365)))

    assert fresh.to_dict()["hours_awake"] == aged.to_dict()["hours_awake"]
    assert fresh.to_dict()["level"] == aged.to_dict()["level"]
    assert fresh.to_dict()["fatigue"] == aged.to_dict()["fatigue"]
    assert fresh.export_state() == aged.export_state()


def test_hours_awake_counts_simulated_hours_not_real_ones():
    """The specific quantity that fed the downstream compliance score.

    ``EnergySystem`` seeds ``last_sleep_time`` at eight hours before its clock's
    "now", so twelve ticked hours later she has been awake twenty -- past
    ``MAX_HOURS_AWAKE``, which is exactly where the fatigue penalty starts to
    move p(comply). Asserted to the second, because a wall-clock read would put
    this within a rounding error of eight no matter how many hours were ticked.
    """
    clock = ScriptedClock(EPOCH)
    energy = EnergySystem(now=clock)
    clock.advance(12)
    energy.tick(TimeOfDay.EVENING)

    assert energy.hours_awake == pytest.approx(20.0)
    assert energy.hours_awake > EnergySystem.MAX_HOURS_AWAKE


def test_every_clock_read_in_the_system_follows_the_injected_one():
    """Not just ``tick`` -- sleep, the hour fallbacks, and the catch-up helper.

    A seam that covers one of eight call sites still leaves the engine reading
    the host clock, so each one is pinned. ``sleep()`` stamps the clock,
    ``should_sleep``/``is_asleep`` read its *hour* when no override is given,
    ``adjust_for_time`` reads both, and ``hours_since_wake`` measures against it.
    """
    # 02:00 -- inside the default sleep window (bed 23:00, wake 07:00).
    clock = ScriptedClock(datetime(2026, 3, 14, 2, 0, 0))
    energy = EnergySystem(now=clock)

    assert energy.is_asleep() is True
    energy.sleep(hours=8.0)
    assert energy.state.last_sleep_time == clock.instant

    # Awake for 19 simulated hours -> 21:00, outside the window.
    clock.advance(19)
    energy.tick(TimeOfDay.NIGHT)
    assert energy.is_asleep() is False
    assert energy.hours_awake == pytest.approx(19.0)

    # hours_since_wake measures against the schedule's wake hour on the
    # injected clock's calendar day: 07:00 -> 21:00 is 14 hours.
    assert energy.hours_since_wake() == pytest.approx(14.0)

    energy.adjust_for_time(TimeOfDay.NIGHT)
    assert energy.state.last_update == clock.instant
    assert energy.hours_awake == pytest.approx(14.0)  # 21:00 minus wake_hour 7


def test_an_aware_clock_is_self_consistent_but_breaks_on_restored_state():
    """Pins the naivety contract the CHANGELOG states, rather than asserting it in prose.

    Every persisted ``datetime`` in this library is naive. A timezone-aware clock
    is fine while the state it built stays in memory, and raises the moment it
    meets a row loaded from SQLite. Documented so a consumer picks a naive clock
    on purpose; asserted so the documentation cannot drift away from the code.
    """
    from datetime import timezone

    aware = lambda: datetime(2026, 3, 14, 6, 0, 0, tzinfo=timezone.utc)  # noqa: E731

    all_aware = EnergySystem(now=aware)
    all_aware.tick(TimeOfDay.MORNING)
    assert all_aware.hours_awake == pytest.approx(8.0)

    mixed = EnergySystem.from_dict(
        {"level": 0.5, "last_update": "2026-03-14T06:00:00",
         "last_sleep_time": "2026-03-13T22:00:00"},
        now=aware,
    )
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        mixed.tick(TimeOfDay.MORNING)


def test_from_dict_restores_onto_the_injected_clock():
    """A restore must not stamp the host's wall time into rehydrated state."""
    clock = ScriptedClock(EPOCH)
    restored = EnergySystem.from_dict({"level": 0.5}, now=clock)

    assert restored.clock is clock
    assert restored.state.last_update == EPOCH


# ----------------------------------------------------------------------
# 2. The default still reads the wall clock
# ----------------------------------------------------------------------

def test_the_default_clock_is_the_wall_clock():
    """No argument -> ``datetime.now``, for ``EnergySystem`` and the world alike.

    Compared with ``==`` rather than ``is``: ``datetime.now`` is a bound builtin
    and each access on the class yields a fresh object, so
    ``datetime.now is datetime.now`` is already ``False``.
    """
    assert EnergySystem().clock == datetime.now
    assert EnergySystem.from_dict({"level": 0.5}).clock == datetime.now
    assert WorldEnvironment()._now == datetime.now


def test_the_default_energy_system_still_tracks_real_time():
    """Behavioural half of the above -- the state it builds is the wall clock's."""
    before = datetime.now()
    energy = EnergySystem()
    after = datetime.now()

    assert before <= energy.state.last_update <= after
    # Seeded eight hours back, as it always was.
    assert abs(
        (energy.state.last_update - energy.state.last_sleep_time)
        - timedelta(hours=8)
    ) < timedelta(seconds=1)

    energy.tick(TimeOfDay.MORNING)
    assert energy.hours_awake == pytest.approx(8.0, abs=0.01)
    assert datetime.now() - energy.state.last_update < timedelta(seconds=5)


def test_the_default_world_still_tracks_real_time():
    world = WorldEnvironment()
    assert datetime.now() - world.now() < timedelta(seconds=5)
    assert datetime.now() - world.state.virtual_time < timedelta(seconds=5)


# ----------------------------------------------------------------------
# 3. The clock is reachable from the world, which is the point
# ----------------------------------------------------------------------

def test_the_world_carries_the_clock_and_energy_follows_it(tmp_path):
    """A shared world on a simulated clock hands that clock to every agent.

    This is the seam that matters to a consumer: it injects one world (the
    sandbox already does -- one settlement, one sky) and the engines that measure
    elapsed time come along, with no per-engine wiring and no global patching.
    """
    clock = ScriptedClock(EPOCH)
    world = WorldEnvironment(now=clock)
    svc = LifeService(
        db_path=str(tmp_path / "agent.db"),
        persona_id="agent0",
        world_environment=world,
        occupation="baker",
    )

    assert svc.energy.clock == world.now
    assert svc.energy.state.last_update == EPOCH

    clock.advance(6)
    world.tick()
    svc.energy.tick(world.time_of_day)

    assert world.state.virtual_time == EPOCH + timedelta(hours=6)
    assert svc.energy.hours_awake == pytest.approx(14.0)


def test_a_subclass_may_override_now_instead_of_passing_a_callable(tmp_path):
    """The shape Hollow's ``DeterministicWorld`` uses: time from a tick counter.

    It derives the instant from ``epoch + day/hour`` rather than holding a
    callable, so the seam has to be a *method* it can override -- not only a
    constructor argument. ``LifeService`` binds ``world.now``, so the override
    reaches the energy system too.
    """

    class TickWorld(WorldEnvironment):
        def __init__(self, **kw):
            self.hours = 0
            super().__init__(**kw)

        def now(self) -> datetime:
            return EPOCH + timedelta(hours=self.hours)

    world = TickWorld()
    assert world.state.virtual_time == EPOCH

    svc = LifeService(
        db_path=str(tmp_path / "agent.db"),
        persona_id="agent0",
        world_environment=world,
        occupation="baker",
    )
    world.hours = 9
    svc.energy.tick(TimeOfDay.AFTERNOON)

    assert svc.energy.hours_awake == pytest.approx(17.0)


def test_a_duck_typed_world_without_a_clock_does_not_lose_the_engine(tmp_path):
    """A host may inject something that is not a ``WorldEnvironment``.

    ``LifeService`` reaches into the injected world by attribute already. If that
    object has no ``now``, energy must fall back to the wall clock rather than
    raise -- an engine that loses its clock entirely is a worse failure than one
    reading the host's.
    """

    class BareWorld:
        _persona_locations = {}
        _sleep_schedule = None

        def tick(self):
            pass

    svc = LifeService(
        db_path=str(tmp_path / "agent.db"),
        persona_id="agent0",
        world_environment=BareWorld(),
        occupation="baker",
    )
    assert svc.energy.clock == datetime.now
