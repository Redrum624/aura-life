"""The career engine answers from the world clock, not the host's.

Why this file exists -- the defect, measured downstream. 0.3.0 made the world
clock injectable, and ``LifeService`` ticks the career engine on it
(``self._career.tick(now=...)``). One line later the same tick asked
``self._career.work_stress()`` with no instant, so ``is_working_now`` fell back
to ``datetime.now()``: on a host weekday inside shift hours work stress read
the full workload, crossed 0.5, and added the ``"work stress"`` stressor to
affect -- a stressor sanity reads. Hollow (the sandbox consumer) replays ten
simulated days from one seed; the same seed produced one digest when the test
ran at 13:30 on a Wednesday and another at 22:45, because the hour the process
ran decided a persona's stress. The status and export blocks (``on_shift``,
``work_stress``) and the context builder's work line read the host clock the
same way.

The seam is the one the tick already used: ``now`` on
``CareerSystem.work_stress`` / ``export_state`` / ``get_status``, and the
service passes ``self._world_clock()()`` at every call site. With no injected
world that is ``datetime.now``, so a host that injects nothing is unchanged.

Three properties are pinned:
  1. the engine answers from the instant it is given, whatever the host says;
  2. with no instant it still reads the wall clock;
  3. two services on one injected clock, one seed and one rng stay identical
     whether the host thinks it is a Wednesday afternoon or a Saturday night.
"""

import importlib
import random
from datetime import datetime

import pytest

from aura_life.job import career_system
from aura_life.job.career_system import CareerSystem
from aura_life.life_service import LifeService
from aura_life.models import CareerState
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

#: Wednesday, inside the default 09:00-17:00 shift.
WEDNESDAY_IN_SHIFT = datetime(2026, 9, 16, 13, 30)
#: Saturday at the same hour: shift hours, but not a work day.
SATURDAY_SAME_HOUR = datetime(2026, 9, 19, 13, 30)

#: The two host instants the service-level test runs under (brief: Wed 13:30,
#: Sat 02:00) -- one on shift, one as far off shift as a clock can be.
HOST_WEDNESDAY = datetime(2026, 9, 16, 13, 30)
HOST_SATURDAY_NIGHT = datetime(2026, 9, 19, 2, 0)

#: Simulated instants, years from any host clock on purpose.
WORLD_ON_SHIFT = datetime(2031, 3, 12, 10, 0)     # Wednesday 10:00
WORLD_OFF_SHIFT = datetime(2031, 3, 15, 10, 0)    # Saturday 10:00

#: Every module whose clock reads the fix routed. The service-level test
#: freezes all of them, so a read left on the host clock in any of them shows.
ROUTED_MODULES = (
    "aura_life.job.career_system",
    "aura_life.life_service",
    "aura_life.context.context_builder",
    "aura_life.continuity.continuity_system",
    "aura_life.persona_evolution.character_evolution",
    "aura_life.memory_time.memory_time_system",
)

SEED = 11
TICKS = 30
WORKLOAD = 0.8


def _frozen(instant: datetime) -> type:
    """A ``datetime`` whose ``now()`` is ``instant`` -- the host clock, pinned."""

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.replace(tzinfo=tz)

        @classmethod
        def today(cls):
            return instant

    return FrozenDateTime


def _freeze_host(monkeypatch, instant: datetime, modules=ROUTED_MODULES) -> None:
    frozen = _frozen(instant)
    for name in modules:
        monkeypatch.setattr(importlib.import_module(name), "datetime", frozen)


def _career() -> CareerSystem:
    return CareerSystem(initial_state=CareerState(occupation="baker", workload=WORKLOAD))


def _stress(on_shift: bool) -> float:
    return round(WORKLOAD * (1.0 if on_shift else 0.35), 2)


# ----------------------------------------------------------------------
# 1. The engine answers from the instant it is given
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "instant, host, on_shift",
    [
        (WEDNESDAY_IN_SHIFT, SATURDAY_SAME_HOUR, True),
        (SATURDAY_SAME_HOUR, WEDNESDAY_IN_SHIFT, False),
    ],
    ids=["weekday-in-shift", "saturday"],
)
def test_the_career_engine_answers_from_the_instant_it_is_given(monkeypatch, instant, host, on_shift):
    """The host is frozen to the opposite case, so a read that slipped back to
    the wall clock would give the opposite answer -- the first assertion proves
    the freeze took, which is what keeps the rest from passing vacuously."""
    monkeypatch.setattr(career_system, "datetime", _frozen(host))
    career = _career()

    assert career.is_working_now() is (not on_shift)

    assert career.is_working_now(instant) is on_shift
    assert career.work_stress(now=instant) == _stress(on_shift)
    assert career.export_state(now=instant)["on_shift"] is on_shift
    status = career.get_status(now=instant)
    assert status["on_shift"] is on_shift
    assert status["work_stress"] == _stress(on_shift)


@pytest.mark.parametrize(
    "host, on_shift",
    [(WEDNESDAY_IN_SHIFT, True), (SATURDAY_SAME_HOUR, False)],
    ids=["host-weekday-in-shift", "host-saturday"],
)
def test_without_an_instant_the_engine_still_reads_the_wall_clock(monkeypatch, host, on_shift):
    """Every existing call form keeps its meaning: no ``now`` is the host clock."""
    monkeypatch.setattr(career_system, "datetime", _frozen(host))
    career = _career()

    assert career.work_stress() == _stress(on_shift)
    assert career.export_state()["on_shift"] is on_shift
    status = career.get_status()
    assert status["on_shift"] is on_shift
    assert status["work_stress"] == _stress(on_shift)


# ----------------------------------------------------------------------
# 2. The service passes the world clock at every career call site
# ----------------------------------------------------------------------

def _worker() -> PersonalityDefinition:
    """A human with a job and a home, so career, finance and errands all tick."""
    return PersonalityDefinition(
        core_traits=["diligent", "anxious"],
        struggles=["money", "sleep"],
        intrusive_thought_themes=["failure"],
        occupation="baker",
        home_type="studio",
    )


def _service(tmp_path, pid, world, rng=None) -> LifeService:
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
        definition=_worker(),
        rng=rng,
    )


def _run_under_host_clock(monkeypatch, tmp_path, pid, world, host):
    """Build and drive one service while every routed module's host clock reads
    ``host``. Everything observed is read before the freeze is lifted."""
    rng = random.Random(SEED)
    with monkeypatch.context() as m:
        _freeze_host(m, host)
        svc = _service(tmp_path, pid, world, rng)
        for _ in range(TICKS):
            svc._on_energy_tick()
        return {
            "stress_sources": list(svc._affect._stress.sources),
            "career": svc.get_status()["career"],
            "sanity": svc.sanity.value,
            "rng": rng.getstate(),
            "workload": svc._career.state.workload,
        }


@pytest.mark.parametrize(
    "world_instant, on_shift",
    [(WORLD_ON_SHIFT, True), (WORLD_OFF_SHIFT, False)],
    ids=["world-on-shift", "world-off-shift"],
)
def test_the_host_hour_cannot_reach_a_service_on_an_injected_clock(monkeypatch, tmp_path, world_instant, on_shift):
    """The invariant that broke Hollow.

    One world (so both runs share its weather, which the world's constructor
    draws from module ``random``), fixed at a simulated instant; two services
    from one seed on two ``Random(SEED)`` streams, the same number of ticks
    through ``_on_energy_tick`` -- the callback Hollow drives. The only
    difference is the host clock: a Wednesday afternoon for one, a Saturday
    night for the other. Stress sources, the career status block, sanity and
    the rng position must not be able to tell them apart.
    """
    world = WorldEnvironment(now=lambda: world_instant)

    wednesday = _run_under_host_clock(monkeypatch, tmp_path, "wed", world, HOST_WEDNESDAY)
    saturday = _run_under_host_clock(monkeypatch, tmp_path, "sat", world, HOST_SATURDAY_NIGHT)

    assert wednesday["stress_sources"] == saturday["stress_sources"]
    assert wednesday["career"] == saturday["career"]
    assert wednesday["sanity"] == saturday["sanity"]
    assert wednesday["rng"] == saturday["rng"]

    # And the world decided it, not a coincidence of the two host instants.
    assert wednesday["career"]["on_shift"] is on_shift
    assert wednesday["career"]["work_stress"] == round(
        wednesday["workload"] * (1.0 if on_shift else 0.35), 2
    )
    assert wednesday["rng"] != random.Random(SEED).getstate()


def test_the_export_and_the_context_builder_read_the_world_clock(monkeypatch, tmp_path):
    """The two other career call sites: the outer-state export and the
    context builder's work line (which reaches the clock through its
    ``life_service``)."""
    world = WorldEnvironment(now=lambda: WORLD_ON_SHIFT)
    _freeze_host(monkeypatch, HOST_SATURDAY_NIGHT)
    svc = _service(tmp_path, "export", world)

    assert svc.export_outer_state()["career"]["on_shift"] is True
    assert "you're at work right now" in svc._context_builder._build_career_section()


@pytest.mark.parametrize(
    "host, on_shift",
    [(HOST_WEDNESDAY, True), (HOST_SATURDAY_NIGHT, False)],
    ids=["host-wednesday", "host-saturday-night"],
)
def test_a_service_with_no_injected_clock_still_follows_the_wall_clock(monkeypatch, tmp_path, host, on_shift):
    """No world injected: the service builds its own on ``datetime.now``, and
    every career read follows the host exactly as before the fix. The world
    module is frozen too, because that is where the private world's clock
    comes from."""
    _freeze_host(monkeypatch, host, ROUTED_MODULES + ("aura_life.world.environment",))
    svc = LifeService(
        db_path=str(tmp_path / "private.db"),
        persona_id="private",
        occupation="baker",
        definition=_worker(),
        rng=random.Random(SEED),
    )

    assert svc.get_status()["career"]["on_shift"] is on_shift
    assert svc.export_outer_state()["career"]["on_shift"] is on_shift
    assert ("you're at work right now" in svc._context_builder._build_career_section()) is on_shift
