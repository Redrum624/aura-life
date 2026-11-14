"""Every engine that draws randomness draws from a stream of its own.

Ruling T4-R1 gave the nightly sleep draws their own stream, derived from the
injected ``rng``'s state plus the label "sleep"
(``LifeService._sleep_stream``), so that no other draw on the service's rng
could move her bedtimes (proven by
``tests/test_sleep_state.py::test_other_draws_on_the_service_rng_do_not_move_her_nights``).
Task 26 generalises that pattern (``LifeService._derive_stream``). Ruling
T5-R1 first generalised it to every engine that used to share ``self._rng``
directly (desire, habitation, finance, career, errands, identity, cognitive,
drive, memory-time, life-events) and the service's own direct draws
(``self._service_rng``, "the service keeps its own stream too"). Ruling
T26-R2 (Task 26 fix round 1) went further: T4-R1 only ever decided which
draws sit on *the sleep stream*, never which engines Task 26 would cover, so
every engine that draws randomness at all gets its own stream, not only the
ones already sharing ``self._rng`` -- activity selection, chaos, the daily
planner's bare draws (not its per-day, per-role ``crc32``-seeded ones), the
body's sleep/daily-health rolls, social, behaviour, goals and transport, each
newly given an ``rng`` parameter defaulting to a fresh, unseeded
``random.Random()`` (never the module) so a bare, standalone construction
still works. ``WorldEnvironment`` is excluded on purpose: shared across every
persona in a household, it owns its own ``rng``/``seed`` instead of taking
one from any single persona (see its own constructor docstring, and the
lint test below, which still covers its module for bare-module calls).

This file proves the seam the same ways ``test_tick_rng.py`` and
``test_sleep_state.py`` already do for the paths they cover, generalised to
every engine:

1. a change to how many draws one engine's stream takes -- the acceptance
   scenario -- never moves any other engine's stream, because each is a
   separate ``random.Random`` object;
2. generalising ``test_other_draws_on_the_service_rng_do_not_move_her_nights``:
   however many values something else draws from the *injected* rng after
   construction (this now includes the service's own draws, since nothing --
   not even the service -- reads the raw ``rng`` directly for a draw any
   more), every engine's own derived stream (already seeded then) does not
   move;
3. without an injected rng, every stream is module ``random``, unchanged;
4. the same seed replays the same 3-simulated-day trace at production cadence
   twice, and every derived stream is exactly what ``_derive_stream`` gives
   for its label, so there is no undocumented stream;
5. a lint: no module under ``src/aura_life/`` (besides the two named,
   pre-existing exceptions) calls a global ``random`` drawing function any
   more -- ``random.Random(...)`` construction is fine, a *call* on it is
   not.
"""

import ast
import pathlib
import random

import pytest

from aura_life import LifeService
from aura_life.world import WorldEnvironment

from sim_helpers import PRODUCTION, SimPersona, run_days

#: Every engine with a stream of its own, by the label `_derive_stream` uses
#: -- also the `_<label>_rng` attribute name on the service, except "sleep"
#: (`_sleep_rng`, ruling T4-R1's original name) and "service" (`_service_rng`,
#: the service's own direct draws, not a sub-engine).
ENGINE_LABELS = (
    "desire", "habitation", "finance", "career", "errands",
    "identity", "cognitive", "drive", "memory_time", "life_events",
    "activity", "chaos", "daily_planner", "body", "social", "behavior",
    "goal_engine", "transport",
    # Task 11: her household's joint activities.
    "household",
    # Task 14: how each of her activities goes.
    "outcome",
    # Task 14 fix round (ruling T14-R1): each day's quality.
    "day_quality",
)
#: Every stream `LifeService.__init__` derives: the engines above, sleep
#: (ruling T4-R1) and the service's own direct draws (ruling T5-R1).
#: `WorldEnvironment` is deliberately not here -- see the module docstring.
ALL_LABELS = ENGINE_LABELS + ("sleep", "service")


def _svc(tmp_path, pid: str, rng, **kwargs) -> LifeService:
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=WorldEnvironment(),
        rng=rng,
        **kwargs,
    )


def _stream(svc: LifeService, label: str):
    return getattr(svc, f"_{label}_rng")


def _first_n(stream, n: int) -> list:
    return [stream.random() for _ in range(n)]


# ----------------------------------------------------------------------
# 1. The acceptance scenario: one engine draws N more, nothing else moves.
# ----------------------------------------------------------------------

def test_extra_draws_on_one_engines_stream_do_not_move_any_other_engines_stream(tmp_path):
    """Simulates a future change that makes one engine (desire) draw 41 more
    times than it does today -- exactly the class of change the program's
    rationale names (Task 4 moved bedtimes, Task 5 moved a mood test). Every
    other engine's first 20 draws from its own stream are unaffected, because
    each is derived once, at construction, from the same untouched
    ``rng.getstate()`` read -- not from a position any other engine or the
    service's own draws already advanced it to."""
    baseline = _svc(tmp_path, "baseline", random.Random(7))
    perturbed = _svc(tmp_path, "perturbed", random.Random(7))

    for _ in range(41):
        perturbed._desire_rng.random()

    for label in ALL_LABELS:
        if label == "desire":
            continue
        base_draws = _first_n(_stream(baseline, label), 20)
        moved_draws = _first_n(_stream(perturbed, label), 20)
        assert base_draws == moved_draws, f"{label}'s draws moved when desire took 41 extra draws"


def test_perturbing_each_engine_in_turn_never_moves_any_other(tmp_path):
    """The same property, for every engine as the one perturbed -- not just
    desire -- so a future change to any one of them is covered."""
    for perturbed_label in ALL_LABELS:
        baseline = _svc(tmp_path, f"baseline-{perturbed_label}", random.Random(11))
        perturbed = _svc(tmp_path, f"perturbed-{perturbed_label}", random.Random(11))
        for _ in range(17):
            _stream(perturbed, perturbed_label).random()

        for label in ALL_LABELS:
            if label == perturbed_label:
                continue
            base_draws = _first_n(_stream(baseline, label), 5)
            moved_draws = _first_n(_stream(perturbed, label), 5)
            assert base_draws == moved_draws, (
                f"{label}'s draws moved when {perturbed_label} took 17 extra draws"
            )


# ----------------------------------------------------------------------
# 2. Generalising the sleep-stream regression test to every engine.
# ----------------------------------------------------------------------

def test_other_draws_on_the_injected_rng_do_not_move_any_engines_stream(tmp_path):
    """Generalises
    ``test_sleep_state.py::test_other_draws_on_the_service_rng_do_not_move_her_nights``
    (ruling T4-R1) from the sleep stream to every engine on the energy-tick
    path (ruling T5-R1 / Task 26): however many values something else draws
    from the *injected* rng itself after construction (as the service's own
    direct draws do during ticking), every engine's own stream -- already
    seeded, at construction, from the rng's state at that moment -- does not
    move."""
    quiet_rng = random.Random(7)
    quiet = _svc(tmp_path, "quiet", quiet_rng)
    quiet_draws = {label: _first_n(_stream(quiet, label), 20) for label in ALL_LABELS}

    busy_rng = random.Random(7)
    busy = _svc(tmp_path, "busy", busy_rng)
    for _ in range(250):
        busy_rng.random()
    busy_draws = {label: _first_n(_stream(busy, label), 20) for label in ALL_LABELS}

    assert busy_draws == quiet_draws


# ----------------------------------------------------------------------
# 3. rng=None: every stream is module random, unchanged.
# ----------------------------------------------------------------------

def test_without_an_injected_rng_every_stream_is_module_random(tmp_path):
    svc = _svc(tmp_path, "none", None)
    for label in ALL_LABELS:
        assert _stream(svc, label) is random, label


def test_a_service_without_an_rng_keeps_its_private_world_on_the_module_random(tmp_path):
    """Ruling T35-R1: ``rng=None`` on ``LifeService`` leaves every draw on
    module ``random``, her private world's weather included (as every
    released version did), so a host that seeds the module gets one life from
    one seed. Two services, each built right after ``random.seed(31)``, no
    world handed in, their worlds ticked on the same fixed clock: the same
    weather, draw for draw. A world the host builds itself keeps its own
    stream (``WorldEnvironment``'s own ``rng``/``seed``)."""
    from datetime import datetime, timedelta

    def weather_after_seeding(name):
        random.seed(31)
        svc = LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name, rng=None)
        clock = {"now": datetime(2026, 10, 6, 9, 0)}
        svc._world.now = lambda: clock["now"]
        seen = [svc._world.weather]
        for _ in range(200):
            clock["now"] += timedelta(hours=1)
            svc._world.tick()
            seen.append(svc._world.weather)
        return seen

    assert weather_after_seeding("first") == weather_after_seeding("second")


# ----------------------------------------------------------------------
# 4. Derivation correctness: each stream is exactly _derive_stream(rng, label).
# ----------------------------------------------------------------------

def test_each_stream_matches_derive_stream_for_its_label_with_no_collisions(tmp_path):
    svc = _svc(tmp_path, "labels", random.Random(2026))
    seen = {}
    for label in ALL_LABELS:
        expected = LifeService._derive_stream(random.Random(2026), label)
        got = _stream(svc, label)
        assert got.getstate() == expected.getstate(), label
        state = got.getstate()
        assert state not in seen.values(), f"{label} collides with {seen}"
        seen[label] = state


def test_sleep_stream_is_the_derive_stream_helper_labeled_sleep():
    """Ruling T4-R1's ``_sleep_stream`` is now the label-"sleep" case of the
    same helper every other engine uses (ruling T5-R1 / Task 26); its
    derivation is byte-identical to before, so Task 3's pinned nights do not
    move."""
    rng = random.Random(99)
    assert LifeService._sleep_stream(rng).getstate() == LifeService._derive_stream(rng, "sleep").getstate()


def test_derive_stream_with_no_getstate_shares_the_object_for_every_label(tmp_path):
    """An rng-like object with no ``getstate`` (a test double) is returned
    as-is for every label -- the same degraded-but-working fallback
    ``_sleep_stream`` already had, generalised."""

    class NoGetstateRng:
        def random(self):
            return 0.5

    rng = NoGetstateRng()
    for label in ALL_LABELS:
        assert LifeService._derive_stream(rng, label) is rng


# ----------------------------------------------------------------------
# 5. Same seed, same 3-day trace at production cadence, across two runs.
# ----------------------------------------------------------------------

def test_same_seed_same_three_day_trace_at_production_cadence():
    """The per-engine streams must not cost the service its reproducibility:
    two independent 3-simulated-day runs at ``LifeScheduler``'s own cadence,
    from the same seed, produce byte-identical traces."""
    persona = SimPersona(persona_id="reproducible")
    trace_a = run_days([persona], days=3, cadence=PRODUCTION, seed=4242)
    trace_b = run_days([persona], days=3, cadence=PRODUCTION, seed=4242)

    assert trace_a.errors == []
    assert trace_b.errors == []
    assert trace_a.records["reproducible"] == trace_b.records["reproducible"]


# ----------------------------------------------------------------------
# 6. Lint: no module under src/aura_life/ calls the global random module's
#    drawing functions any more (ruling T26-R2).
# ----------------------------------------------------------------------

#: Drawing functions on the `random` module (or an instance): a call on
#: `random` itself (not on `random.Random(...)`'s result) is what this lint
#: catches. `Random(...)` -- construction -- is deliberately not in this set.
_DRAWING_FUNCS = {
    "random", "choice", "choices", "randint", "randrange", "uniform", "sample",
    "shuffle", "gauss", "triangular", "betavariate", "expovariate",
    "gammavariate", "lognormvariate", "normalvariate", "paretovariate",
    "vonmisesvariate", "weibullvariate", "getrandbits",
}

#: Modules that may call the global random module directly.
#: - personas/genre_randomizer.py, personas/place_generation.py: persona
#:   generation, out of scope for both Task 26 and this fix round (the task
#:   brief and ruling T26-R2 both say so explicitly).
_LINT_EXEMPT = {
    pathlib.PurePosixPath("personas/genre_randomizer.py"),
    pathlib.PurePosixPath("personas/place_generation.py"),
}


def _random_module_call_sites(path: pathlib.Path):
    """Every ``(lineno, alias, func)`` where ``alias`` is a name this file
    binds to the ``random`` module (``import random`` or ``import random as
    alias``, at any scope) and ``func`` is a drawing function called on it --
    i.e. every remaining bare draw from the shared global module. A plain
    ``random.Random(...)`` construction does not match: ``"Random"`` is not
    in ``_DRAWING_FUNCS``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "random"
    }
    return [
        (node.lineno, node.func.value.id, node.func.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _DRAWING_FUNCS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in aliases
    ]


def test_no_module_under_src_calls_the_global_random_module():
    """Every engine that draws randomness draws from an injected or
    self-owned stream (this file's other tests, and each engine's own
    constructor docstring) -- never from the shared global ``random``
    module directly. This is the mechanical guarantee behind that: nothing
    under ``src/aura_life/`` (besides the two modules persona generation
    already exempts) still reaches for it, so a future addition cannot
    reintroduce the exact fragility this program exists to remove."""
    src_root = pathlib.Path(__file__).resolve().parent.parent / "src" / "aura_life"
    violations = []
    for path in sorted(src_root.rglob("*.py")):
        rel = pathlib.PurePosixPath(path.relative_to(src_root).as_posix())
        if rel in _LINT_EXEMPT:
            continue
        for lineno, alias, func in _random_module_call_sites(path):
            violations.append(f"{rel}:{lineno}: {alias}.{func}(...)")
    assert violations == [], "bare global-random draws found:\n" + "\n".join(violations)
