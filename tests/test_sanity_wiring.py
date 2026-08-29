"""SanitySystem wired into LifeService -- the glue, not the engine.

`tests/test_sanity.py` proves the engine alone. This file proves the seams a
consumer actually touches: `LifeService` builds the engine from the definition,
ticks it on the world clock the way it ticks energy, couples its state word to
affect and shadow through their public methods, persists it beside the other
engines, and -- the property every existing consumer relies on -- changes
nothing anywhere else while the persona is sound.

The couplings are asserted as functions of the *word* (strained, fraying,
breaking), never of the numbers, because that is the contract the engine
publishes and the only one a host is meant to build on.
"""

import random
from datetime import datetime, timedelta

import pytest

from aura_life import LifeService, SanitySystem
from aura_life.life_service import (
    SANITY_BREAKING_REGULATION_COLLAPSE,
    SANITY_FRAYING_RESTRAINT_PRESSURE,
    SANITY_STRESS_SOURCE,
    SANITY_STRESSED_LEVEL,
)
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.sanity.sanity_system import (
    BLOW_WEIGHT,
    DRIFT_DOWN_STRESSED_PER_HOUR,
    DRIFT_UP_PER_HOUR,
    RECOVERY_WEIGHT,
    STATES,
)
from aura_life.world import WorldEnvironment

EPOCH = datetime(2026, 3, 14, 6, 0, 0)


class ScriptedClock:
    """A clock that advances only when told to (see tests/test_energy_clock.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


class CountingRng:
    def __init__(self, seed: int = 7):
        self._r = random.Random(seed)
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self._r.random()


def _stress_to_level(svc, level=None):
    """Push affect's stress level to at least `level` (default: the sanity
    tick's floor) through affect's own public seam, one label at a time."""
    target = SANITY_STRESSED_LEVEL if level is None else level
    n = 0
    while svc.affect.stress.level < target:
        svc.affect.on_stressor_added(f"deadline {n}")
        n += 1


def _svc(tmp_path, pid="agent0", definition=None, clock=None, **kw):
    world = WorldEnvironment(now=clock) if clock is not None else WorldEnvironment()
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
        definition=definition,
        **kw,
    ), world


def _strip_wall_clock(obj):
    """Drop ISO-datetime strings from a status dict.

    Several engines stamp ``datetime.now()`` into their status (continuity's
    last-tick markers, character evolution's ``last_evolution``). Two services
    built a few milliseconds apart differ there by construction, and those
    fields are not what this file is about.
    """
    if isinstance(obj, dict):
        return {k: _strip_wall_clock(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_wall_clock(v) for v in obj]
    if isinstance(obj, str) and len(obj) >= 19 and obj[4] == "-" and obj[10] == "T":
        try:
            datetime.fromisoformat(obj)
            return "<wall-clock>"
        except ValueError:
            return obj
    return obj


# ----------------------------------------------------------------------
# 1. Sound and unstressed: sanity holds, and nothing else moves
# ----------------------------------------------------------------------

def _run_two_days(tmp_path, pid, *, disable_sanity_tick: bool):
    """Forty-eight simulated hours through the real energy tick.

    An AI-typed persona carrying no burdens, put to bed every eight hours: no
    hunger (an AI does not eat), no sleep deprivation, no struggle stressors.
    That is the only way to hold "nothing is stressed" for two days through
    the *real* tick rather than by clearing affect behind its back. The global
    rng is reseeded identically before every tick so the two runs consume the
    same draws.
    """
    clock = ScriptedClock(EPOCH)
    random.seed(1)
    svc, world = _svc(tmp_path, pid, definition=PersonalityDefinition(persona_type="ai"), clock=clock)
    if disable_sanity_tick:
        svc._tick_sanity = lambda: None
    baseline = svc.sanity.baseline
    for hour in range(1, 49):
        clock.advance(1)
        world.tick()
        if hour % 8 == 0:
            svc.energy.sleep(hours=8)
        random.seed(100 + hour)
        svc._on_energy_tick()
        assert svc.affect.stress.sources == [], f"stressor appeared at hour {hour}"
        assert svc.sanity.value == baseline, f"sanity moved at hour {hour}"
        assert svc.sanity.state == "sound"
    return svc


def test_no_blows_and_no_stress_keeps_sanity_at_baseline_for_48_hours(tmp_path):
    svc = _run_two_days(tmp_path, "held", disable_sanity_tick=False)
    assert svc.sanity.value == svc.sanity.baseline
    assert svc.sanity.pending_events == []
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources
    assert svc._shadow.restraint_pressure == 0.0


def test_a_sound_persona_leaves_every_other_engine_byte_identical(tmp_path):
    """Same clock, same seeds, one service with the sanity tick disabled: every
    other engine's status must agree to the last digit."""
    with_sanity = _run_two_days(tmp_path, "with", disable_sanity_tick=False).get_status()
    without = _run_two_days(tmp_path, "without", disable_sanity_tick=True).get_status()

    assert set(with_sanity) == set(without)
    for key in with_sanity:
        if key == "sanity":
            continue
        assert _strip_wall_clock(with_sanity[key]) == _strip_wall_clock(without[key]), key


# ----------------------------------------------------------------------
# 2. Construction: from the definition, opt-in draw
# ----------------------------------------------------------------------

def test_the_engine_is_built_from_the_definition_and_takes_no_draw_by_default(tmp_path):
    plain, _ = _svc(tmp_path, "plain")
    assert isinstance(plain.sanity, SanitySystem)
    assert plain.sanity.baseline == pytest.approx(0.92)
    assert plain.sanity.intensity == pytest.approx(1.0)

    burdened, _ = _svc(tmp_path, "burdened", definition=PersonalityDefinition(
        struggles=["money", "sleep"], character_defects=["pride"], intrusive_thought_themes=["failure"],
    ))
    assert burdened.sanity.baseline < plain.sanity.baseline
    assert burdened.sanity.intensity > plain.sanity.intensity
    assert burdened.sanity.baseline == SanitySystem(
        ["money", "sleep"], ["pride"], ["failure"]
    ).baseline


def test_sanity_rng_is_opt_in_and_costs_exactly_one_draw(tmp_path):
    rng = CountingRng()
    svc, _ = _svc(tmp_path, "jitter", sanity_rng=rng)
    assert rng.calls == 1
    assert svc.sanity.intensity != pytest.approx(1.0) or svc.sanity.baseline != pytest.approx(0.92)
    svc._on_energy_tick()
    svc.on_sanity_blow("grief", 0.5)
    assert rng.calls == 1


def test_a_persona_that_starts_strained_is_not_coupled_for_existing(tmp_path):
    """The couplings fire on a *change* of word. Most shipped genre personas
    carry enough burden to start `strained`; if the word were coupled the
    moment it existed, every one of them would gain a `"sanity"` stressor
    (and +0.05 stress) at construction with no blow ever sent -- a visible
    change for every existing consumer."""
    heavy = PersonalityDefinition(
        struggles=["a", "b", "c", "d", "e"], character_defects=["f", "g", "h"],
    )
    svc, _ = _svc(tmp_path, "heavy", definition=heavy)
    assert svc.sanity.state == "strained"
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources
    assert svc.affect.stress.level == 0.0
    assert svc._shadow.restraint_pressure == 0.0

    # A tick that moves nothing keeps it that way...
    svc._on_energy_tick()
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources
    # ...and the first change of word couples.
    svc.on_sanity_blow("witnessed", 1.0)      # fraying
    assert svc.sanity.state == "fraying"
    assert SANITY_STRESS_SOURCE in svc.affect.stress.sources
    assert svc._shadow.restraint_pressure == SANITY_FRAYING_RESTRAINT_PRESSURE


def test_stressed_is_read_from_affects_level_not_its_labels(tmp_path):
    """`stress.sources` is a capped summary the service never resolves
    (`struggle:*`, `money worries`); a persona read as stressed by a label
    would erode to `broken` in days with no blow. The tick reads the level."""
    clock = ScriptedClock(EPOCH)
    svc, _ = _svc(tmp_path, clock=clock)
    baseline = svc.sanity.value
    svc.affect.on_stressor_added("struggle:something permanent")   # +0.05, one label
    assert svc.affect.stress.level < SANITY_STRESSED_LEVEL
    clock.advance(24)
    svc._tick_sanity()
    assert svc.sanity.value == baseline

    _stress_to_level(svc)
    clock.advance(24)
    svc._tick_sanity()
    assert svc.sanity.value < baseline


# ----------------------------------------------------------------------
# 3. Couplings, by the word
# ----------------------------------------------------------------------

def test_a_blow_into_strained_adds_the_affect_stress_source_and_sound_removes_it(tmp_path):
    svc, _ = _svc(tmp_path)
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources
    level_before = svc.affect.stress.level

    loss = svc.on_sanity_blow("grief", 1.0)
    assert loss == pytest.approx(BLOW_WEIGHT["grief"])
    assert svc.sanity.state == "strained"
    assert SANITY_STRESS_SOURCE in svc.affect.stress.sources
    assert svc.affect.stress.level > level_before

    gain = svc.on_sanity_recovery("answered", 1.0)
    assert gain == pytest.approx(RECOVERY_WEIGHT["answered"])
    assert svc.sanity.state == "sound"
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources


def test_fraying_moves_shadow_and_climbing_above_it_restores(tmp_path):
    svc, _ = _svc(tmp_path)
    inhibition_before = svc.get_status()["shadow"]["inhibition"]

    svc.on_sanity_blow("grief", 1.0)        # 0.62 strained
    assert svc._shadow.restraint_pressure == 0.0
    assert svc.get_status()["shadow"]["inhibition"] == inhibition_before

    svc.on_sanity_blow("witnessed", 1.0)    # 0.42 fraying
    assert svc.sanity.state == "fraying"
    assert svc._shadow.restraint_pressure == SANITY_FRAYING_RESTRAINT_PRESSURE
    assert svc.get_status()["shadow"]["inhibition"] == pytest.approx(
        max(0.0, inhibition_before - SANITY_FRAYING_RESTRAINT_PRESSURE), abs=1e-3
    )
    assert SANITY_STRESS_SOURCE in svc.affect.stress.sources

    svc.on_sanity_recovery("answered", 1.0)  # 0.57 strained
    assert svc.sanity.state == "strained"
    assert svc._shadow.restraint_pressure == 0.0
    assert svc.get_status()["shadow"]["inhibition"] == pytest.approx(inhibition_before, abs=1e-3)
    assert SANITY_STRESS_SOURCE in svc.affect.stress.sources


def test_the_held_pull_survives_shadows_own_tick(tmp_path):
    """Shadow recovers inhibition toward its baseline every tick; the pull has
    to lower that baseline, or the coupling would be a blip."""
    svc, _ = _svc(tmp_path)
    resting = svc.get_status()["shadow"]["inhibition"]
    svc.on_sanity_blow("grief", 1.0)
    svc.on_sanity_blow("witnessed", 1.0)
    for _ in range(60):
        svc._shadow.tick(stress=0.0, loneliness=0.0, mood=0.5)
    assert svc.get_status()["shadow"]["inhibition"] < resting - SANITY_FRAYING_RESTRAINT_PRESSURE / 2


def test_breaking_collapses_regulation_once_on_the_way_in(tmp_path):
    svc, _ = _svc(tmp_path)
    svc.on_sanity_blow("grief", 1.0)        # 0.62
    svc.on_sanity_blow("witnessed", 1.0)    # 0.42
    capacity_before = svc.affect.regulation.capacity
    assert capacity_before > 0.0

    svc.on_sanity_blow("grief", 1.0)        # 0.12 breaking
    assert svc.sanity.state == "breaking"
    assert svc.affect.regulation.capacity == pytest.approx(
        max(0.0, capacity_before - SANITY_BREAKING_REGULATION_COLLAPSE)
    )
    assert svc.affect.regulation.last_depletion_event == "sanity: breaking"
    assert svc.sanity.pending_events == ["breaking"]   # the host drains it

    # Holding the state does not fire it again (the sanity tick alone: the
    # full energy tick also runs affect's own 2%-per-tick recharge).
    svc.affect.recharge_regulation(0.3)
    svc._tick_sanity()
    assert svc.sanity.state == "breaking"
    assert svc.affect.regulation.capacity == pytest.approx(0.3)

    # Climbing out and falling back in does.
    svc.on_sanity_recovery("answered", 1.0)  # 0.27 fraying
    assert svc.sanity.state == "fraying"
    svc.on_sanity_blow("grief", 1.0)         # 0.0 broken, through breaking
    assert svc.sanity.state == "broken"
    assert svc.sanity.broken
    assert svc.affect.regulation.capacity == pytest.approx(0.0)
    assert svc.sanity.pending_events == ["breaking", "breaking"]


def test_a_host_that_calls_the_engine_directly_is_coupled_at_the_next_tick(tmp_path):
    svc, _ = _svc(tmp_path)
    svc.sanity.on_blow("grief", 1.0)
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources
    svc._on_energy_tick()
    assert SANITY_STRESS_SOURCE in svc.affect.stress.sources


# ----------------------------------------------------------------------
# 4. Time, on the world clock
# ----------------------------------------------------------------------

def test_the_tick_measures_hours_on_the_world_clock(tmp_path):
    clock = ScriptedClock(EPOCH)
    svc, _ = _svc(tmp_path, clock=clock)
    baseline, intensity = svc.sanity.baseline, svc.sanity.intensity

    _stress_to_level(svc)
    clock.advance(10)
    svc._tick_sanity()
    assert svc.sanity.value == pytest.approx(baseline - 10 * DRIFT_DOWN_STRESSED_PER_HOUR * intensity)

    while svc.affect.stress.level >= SANITY_STRESSED_LEVEL:
        svc.affect.on_stressor_resolved("deadline 0")
    clock.advance(5)
    svc._tick_sanity()
    assert svc.sanity.value == pytest.approx(
        baseline - 10 * DRIFT_DOWN_STRESSED_PER_HOUR * intensity + 5 * DRIFT_UP_PER_HOUR / intensity
    )

    clock.advance(1000)
    svc._tick_sanity()
    assert svc.sanity.value == pytest.approx(baseline)


def test_the_sanity_stressor_does_not_feed_its_own_erosion(tmp_path):
    """Strained opens a stressor in affect (+0.05); that alone must not read
    as 'stressed', or the state that opens it would be the state that keeps
    eroding and no strained persona could climb back by time alone."""
    clock = ScriptedClock(EPOCH)
    svc, _ = _svc(tmp_path, clock=clock)
    svc.on_sanity_blow("grief", 1.0)
    assert svc.affect.stress.sources == [SANITY_STRESS_SOURCE]
    low = svc.sanity.value

    clock.advance(24)
    svc._tick_sanity()
    assert svc.sanity.value > low


def test_the_engine_reads_no_clock_of_its_own(tmp_path):
    """A world whose clock never moves gives a persona who never erodes, even
    stressed -- the hours are the world's, not the process's."""
    clock = ScriptedClock(EPOCH)
    svc, _ = _svc(tmp_path, clock=clock)
    _stress_to_level(svc)
    before = svc.sanity.value
    for _ in range(5):
        svc._tick_sanity()
    assert svc.sanity.value == before


# ----------------------------------------------------------------------
# 5. Status and persistence
# ----------------------------------------------------------------------

def test_get_status_carries_the_number_and_the_word(tmp_path):
    svc, _ = _svc(tmp_path)
    status = svc.get_status()["sanity"]
    assert status["sanity"] == pytest.approx(svc.sanity.value, abs=1e-3)
    assert status["state"] in STATES
    assert svc.export_inner_state()["sanity"]["state"] == svc.sanity.state


def test_a_restart_resumes_the_number_the_word_and_the_couplings(tmp_path):
    clock = ScriptedClock(EPOCH)
    svc, _ = _svc(tmp_path, "resume", clock=clock)
    svc.on_sanity_blow("grief", 1.0)
    svc.on_sanity_blow("witnessed", 1.0)
    svc.on_sanity_blow("grief", 1.0)          # breaking: regulation collapsed
    svc.affect.recharge_regulation(0.3)       # ...and partly recharged since
    svc.sanity.on_recovery("rest", 0.2)       # a little back, stays breaking
    assert svc.sanity.state == "breaking"
    value, events = svc.sanity.value, svc.sanity.pending_events
    svc._save_state()

    again, _ = _svc(tmp_path, "resume", clock=ScriptedClock(EPOCH + timedelta(days=3)))
    assert again.sanity.state == "sound"      # a fresh construction, before the load
    again._load_state()

    assert again.sanity.value == value
    assert again.sanity.state == "breaking"
    assert again.sanity.baseline == svc.sanity.baseline
    assert again.sanity.intensity == svc.sanity.intensity
    assert again.sanity.pending_events == events
    assert SANITY_STRESS_SOURCE in again.affect.stress.sources
    assert again._shadow.restraint_pressure == SANITY_FRAYING_RESTRAINT_PRESSURE
    # The pull is in shadow's row and was already applied to inhibition before
    # the save: a load must not lower inhibition a second time.
    assert again.get_status()["shadow"]["inhibition"] == svc.get_status()["shadow"]["inhibition"]
    # The entry event is not re-fired by a load: capacity is affect's row, not zero.
    assert again.affect.regulation.capacity == pytest.approx(0.3)


def test_a_fresh_database_keeps_the_constructed_engine(tmp_path):
    rng = CountingRng()
    svc, _ = _svc(tmp_path, "fresh", sanity_rng=rng)
    built = svc.sanity
    svc._load_state()
    assert svc.sanity is built
    assert rng.calls == 1


def test_reset_state_rebuilds_the_engine_at_its_baseline(tmp_path):
    svc, _ = _svc(tmp_path)
    svc.on_sanity_blow("grief", 1.0)
    svc.on_sanity_blow("witnessed", 1.0)
    assert svc._shadow.restraint_pressure == SANITY_FRAYING_RESTRAINT_PRESSURE
    svc.reset_state()
    assert svc.sanity.value == svc.sanity.baseline
    assert svc.sanity.state == "sound"
    assert SANITY_STRESS_SOURCE not in svc.affect.stress.sources
    assert svc._shadow.restraint_pressure == 0.0
