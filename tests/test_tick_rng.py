"""The energy tick is replayable from an injected rng -- and untouched without one.

Before `LifeService(rng=...)` existed, every draw on the energy-tick path
(identity's struggle and defect rolls, desire's arousal drift, cognitive's
monologue, drive's avoidance roll, career/finance/errands, memory-time's
nostalgia, the service's own struggle-to-rumination coin) came from the
module-level `random`. A host that seeded its own `random.Random` per persona
could not replay a run: the library kept drawing from a stream it did not
own, so two loops of one seed diverged on the first hour a struggle surfaced.

This file proves the seam three ways:

1. two services built from one definition and two `Random(7)`s, driven 200
   simulated hours on a scripted world clock, end with every engine's status
   and both rng states identical (and the rngs were actually consumed);
2. while an rng is injected, the energy tick takes *no* draw from module
   `random` -- the whole audit in one assertion;
3. with `rng=None` the tick still reads module `random` exactly as before
   (two runs under the same module seed agree), so every existing consumer and
   the golden fixtures are untouched.
"""

import random
from datetime import datetime, timedelta

from aura_life import LifeService
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment

EPOCH = datetime(2026, 3, 14, 6, 0, 0)
HOURS = 200

# Every engine that draws on the energy-tick path, plus the ones that consume
# those draws through the service's routing. Compared one by one so a
# divergence names its engine.
ENGINES = (
    "_energy", "_desire_system", "_identity", "_affect", "_cognitive",
    "_shadow", "_sanity", "_drive", "_habitation", "_sustenance",
    "_career", "_finance", "_errands", "_memory_time", "_life_events",
    "_social", "_behavior", "_body",
)


class ScriptedClock:
    """A clock that advances only when told to (see tests/test_energy_clock.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


def _burdened() -> PersonalityDefinition:
    """A human persona with every burden the tick path rolls on: struggles
    (identity -> affect/cognitive), defects (self-esteem drain), intrusive
    themes (cognitive monologue), tendencies (surfacing roll), a job and a
    home (career, finance, errands, habitation all tick for a human)."""
    return PersonalityDefinition(
        core_traits=["curious", "anxious"],
        struggles=["money", "sleep", "being seen"],
        character_defects=["pride", "envy"],
        intrusive_thought_themes=["failure", "being found out"],
        behavioral_tendencies={"gossip": 0.6, "sloth": 0.5},
        occupation="baker",
        home_type="studio",
    )


def _svc(tmp_path, pid, clock, rng, world=None):
    """One service on `world` (built on `clock` when not given). Two services
    meant to replay each other share one world: the world's own tick draws
    weather from module `random` and is not on the energy-tick path, so two
    worlds would rain on different hours and desire's rain branch would
    diverge by an ulp for a reason that is not the seam under test."""
    world = world if world is not None else WorldEnvironment(now=clock)
    svc = LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
        definition=_burdened(),
        rng=rng,
    )
    return svc, world


def _strip_wall_clock(obj):
    """Drop ISO-datetime strings from a status dict (continuity's last-tick
    markers and the like stamp `datetime.now()`; two services built a few
    milliseconds apart differ there by construction)."""
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


def _engine_statuses(svc) -> dict:
    return {name: _strip_wall_clock(getattr(svc, name).get_status()) for name in ENGINES}


def _drive(svcs, world, clock, *, hours=HOURS, on_tick=None):
    """Advance the scripted clock hour by hour, tick the world once, then tick
    every service in lockstep (so their wall-clock views stay as close as two
    calls can be), with eight hours of sleep once a day."""
    for hour in range(1, hours + 1):
        clock.advance(1)
        world.tick()
        for svc in svcs:
            if hour % 24 == 0:
                svc.energy.sleep(hours=8)
            if on_tick is None:
                svc._on_energy_tick()
            else:
                on_tick(svc)


# ----------------------------------------------------------------------
# 1. Two rngs, one seed, one clock: two identical runs
# ----------------------------------------------------------------------

def test_two_services_from_one_seed_replay_identically_for_200_hours(tmp_path):
    clock = ScriptedClock(EPOCH)
    rng_a, rng_b = random.Random(7), random.Random(7)
    world = WorldEnvironment(now=clock)
    a, _ = _svc(tmp_path, "a", clock, rng_a, world)
    b, _ = _svc(tmp_path, "b", clock, rng_b, world)

    _drive([a, b], world, clock)

    got_a, got_b = _engine_statuses(a), _engine_statuses(b)
    for name in ENGINES:
        assert got_a[name] == got_b[name], name
    assert _strip_wall_clock(a.get_status()) == _strip_wall_clock(b.get_status())

    # Both streams ended at the same point -- and moved: a routed seam that
    # took no draw would pass the equality above for the wrong reason.
    assert rng_a.getstate() == rng_b.getstate()
    assert rng_a.getstate() != random.Random(7).getstate()


def test_the_tick_takes_no_draw_from_module_random_while_an_rng_is_injected(tmp_path):
    """The audit as one assertion: across 200 ticks, module `random`'s state
    never moves between entering and leaving `_on_energy_tick`. Any draw on
    the path still reading the module would fail this on its first hour it
    fires. The world's own tick (weather) is outside the window on purpose --
    it is not on the energy-tick path and was not routed."""
    clock = ScriptedClock(EPOCH)
    svc, world = _svc(tmp_path, "sealed", clock, random.Random(7))

    def sealed_tick(s):
        before = random.getstate()
        s._on_energy_tick()
        assert random.getstate() == before, f"module random drawn at {clock.instant}"

    _drive([svc], world, clock, on_tick=sealed_tick)


def test_the_injected_rng_survives_reset_state(tmp_path):
    """`reset_state()` rebuilds every engine; the rebuilt ones must draw from
    the same injected rng, not fall back to the module."""
    clock = ScriptedClock(EPOCH)
    rng = random.Random(7)
    svc, world = _svc(tmp_path, "reset", clock, rng)
    svc.reset_state()
    state_before = rng.getstate()

    def sealed_tick(s):
        b = random.getstate()
        s._on_energy_tick()
        assert random.getstate() == b

    _drive([svc], world, clock, hours=48, on_tick=sealed_tick)
    assert rng.getstate() != state_before


# ----------------------------------------------------------------------
# 2. rng=None: byte-identical to before
# ----------------------------------------------------------------------

def _run_on_module_random(tmp_path, pid, seed):
    """No rng injected; the module stream reseeded identically before every
    tick so two runs consume the same draws -- the only way a consumer could
    replay before `rng=` existed, and the way the sanity tests still do."""
    clock = ScriptedClock(EPOCH)
    random.seed(seed)
    svc, world = _svc(tmp_path, pid, clock, None)
    for hour in range(1, 49):
        clock.advance(1)
        world.tick()
        if hour % 24 == 0:
            svc.energy.sleep(hours=8)
        random.seed(seed * 1000 + hour)
        svc._on_energy_tick()
    return svc


def test_without_an_rng_the_tick_still_reads_module_random(tmp_path):
    a = _run_on_module_random(tmp_path, "m1", 3)
    b = _run_on_module_random(tmp_path, "m2", 3)
    got_a, got_b = _engine_statuses(a), _engine_statuses(b)
    for name in ENGINES:
        assert got_a[name] == got_b[name], name
    # Sanity: the default takes no construction draw (the sanity_rng contract).
    assert a.sanity.intensity == b.sanity.intensity


def test_sanity_rng_defaults_to_rng_when_only_rng_is_given(tmp_path):
    """One injected source replays the whole persona, baseline jitter
    included; `sanity_rng=` given as well keeps the two apart."""
    clock = ScriptedClock(EPOCH)
    only_rng, _ = _svc(tmp_path, "only", clock, random.Random(7))
    assert only_rng._sanity_rng is only_rng._rng

    class OneDraw:
        def __init__(self):
            self.calls = 0

        def random(self):
            self.calls += 1
            return 0.5

    jitter = OneDraw()
    world = WorldEnvironment(now=clock)
    both = LifeService(
        db_path=str(tmp_path / "both.db"), persona_id="both", world_environment=world,
        definition=_burdened(), rng=random.Random(7), sanity_rng=jitter,
    )
    assert both._sanity_rng is jitter
    assert jitter.calls == 1

    plain, _ = _svc(tmp_path, "plain", clock, None)
    assert plain._sanity_rng is None


# ----------------------------------------------------------------------
# 3. The host wall clock is not an input to the tick's draw count
# ----------------------------------------------------------------------

class _HostClock:
    """The host wall clock, owned by the test: frozen or dragged forward."""

    def __init__(self):
        self.instant = EPOCH

    def now(self):
        return self.instant


_HOST = _HostClock()


class _StoppableDatetime(datetime):
    """``datetime`` whose ``now`` answers from :data:`_HOST`; everything else
    (arithmetic, ``fromisoformat``, ``isinstance``) is inherited."""

    @classmethod
    def now(cls, tz=None):
        return _HOST.now()

    @classmethod
    def utcnow(cls):
        return _HOST.now()

    @classmethod
    def today(cls):
        return _HOST.now()


def test_the_host_wall_clock_does_not_move_the_injected_rng(tmp_path, monkeypatch):
    """Career, finance and errands tick on the *world* clock, not the host's.

    ``CareerSystem.tick`` registers a workday off ``now``'s date and hour and
    only then draws, and ``_on_energy_tick`` used to call it bare, so
    ``datetime.now()`` decided how many values the injected rng gave up: a
    service ticked on a scripted world clock drew nothing while the host sat
    before the shift start and four values a day once it moved past it -- a
    run and its replay, hours apart on the host, consumed different counts
    from one seed. Two services on one scripted world clock and two equal
    rngs, the host clock frozen for one and dragged an hour per simulated
    hour for the other, must end at the same rng state with the same career.
    The guard asserts the host clock was genuinely read.
    """
    import sys

    readers = [
        module for name, module in list(sys.modules.items())
        if name.startswith("aura_life") and getattr(module, "datetime", None) is datetime
    ]
    assert len(readers) > 10, "the perturbation cannot reach the modules it is aimed at"
    for module in readers:
        monkeypatch.setattr(module, "datetime", _StoppableDatetime)

    reads = {"n": 0}
    real_now = _HostClock.now

    def counted_now(self):
        reads["n"] += 1
        return real_now(self)

    monkeypatch.setattr(_HostClock, "now", counted_now)

    def run(pid, per_hour):
        # The host sits in another month than the world, so a finance
        # baseline stamped off the host would see a month boundary on the
        # first world-clock tick and pay a month that never passed.
        _HOST.instant = EPOCH + timedelta(days=45)
        # The world's weather is drawn from module ``random`` (not routed --
        # see ``_svc``), and desire's rain branch draws from the injected rng
        # only when it rains, so the two runs must see one weather stream.
        random.seed(20260829)
        clock = ScriptedClock(EPOCH)
        rng = random.Random(7)
        world = WorldEnvironment(now=clock)
        svc, _ = _svc(tmp_path, pid, clock, rng, world)
        for hour in range(1, 73):
            clock.advance(1)
            world.tick()
            if hour % 24 == 0:
                svc.energy.sleep(hours=8)
            svc._on_energy_tick()
            _HOST.instant += per_hour
        assert svc._finance.state.last_payday == EPOCH, (
            "finance's baseline was stamped off the host clock, not the world's"
        )
        return rng.getstate(), _strip_wall_clock(svc._career.get_status()), \
            _strip_wall_clock(svc._finance.get_status())

    frozen = run("frozen", timedelta(0))
    assert reads["n"] > 0, "nothing read the host clock; this proves nothing"
    moving = run("moving", timedelta(hours=1))

    assert frozen[1]["days_worked"] > 0, "no workday registered on the world clock; empty comparison"
    assert frozen == moving, "the host wall clock moved the injected rng"
