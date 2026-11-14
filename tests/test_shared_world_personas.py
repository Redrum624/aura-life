"""Task 2 of the aura-humanness program: per-persona state in a shared world.

Before this task, ``LifeService.__init__`` wrote its own ``persona_locations``
and ``sleep_schedule`` directly onto a *handed* (shared) ``WorldEnvironment``
(``world_environment._persona_locations = ...``), so whichever persona was
constructed last decided both for every persona sharing that world. A
measured run showed a persona with no profile describing another persona's
room, and one persona's time-of-day disagreeing with her own schedule 46% of
the time.

This module proves two personas sharing one ``WorldEnvironment`` each keep
their own room description and their own sleep-schedule-relative time of
day, regardless of which one was constructed first.

Task 27 (ruling T8-R1) extends the same pattern to ``current_location``: Task
2 fixed room descriptions and sleep phase but left ``PersonaWorldView``
passing ``current_location`` straight through as "genuinely shared physical
state", so one persona's move still relocated every persona sharing the
world (measured: another persona moved the shared world after a persona's
own tick in 82 of 288 steps; Task 8 found one persona's traits changing the
other's trace). The tests below that name Task 27 prove a service sharing a
world keeps its own current location and never writes the shared world's,
while a private world keeps today's behaviour.
"""
from datetime import datetime

from aura_life.life_service import LifeService
from aura_life.models import TimeOfDay
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.world import WorldEnvironment
from aura_life.world.environment import PersonaWorldView

from sim_helpers import PRODUCTION, SimPersona, run_days

# 08:00 on the world clock: Lina's early-riser morning, Roberta's dead of
# night. Chosen so the two schedules disagree about what time it is right
# now -- see the docstrings on the two test functions for the arithmetic.
WORLD_INSTANT = datetime(2031, 3, 10, 8, 0)

LINA_LOCATIONS = {"home": "a sunlit loft with paint-splattered floorboards"}
LINA_SCHEDULE = {"wake_hour": 6, "wake_minute": 0, "bedtime_hour": 22, "bedtime_minute": 0}

ROBERTA_LOCATIONS = {"home": "a below-ground flat that smells of old books and candle wax"}
ROBERTA_SCHEDULE = {"wake_hour": 14, "wake_minute": 0, "bedtime_hour": 6, "bedtime_minute": 0}


class _AdvancingClock:
    """A settable clock: ``.instant`` can be moved without a corresponding tick.

    Used to reproduce the fix-round-1 Critical finding: a private world's
    ``get_status()``/``export_state()`` must return the phase as of the last
    ``tick()``, never recompute it live from wherever the clock has moved to
    since. A private ``LifeService`` world has no public way to inject a
    clock (``LifeService.__init__`` builds it internally on the wall clock),
    so tests needing a controllable one swap ``svc._world._now`` in directly
    after construction -- ``WorldEnvironment.now()`` reads ``self._now()``
    fresh on every call, so this reaches every consumer that captured the
    bound method (e.g. ``EnergySystem``), not just direct callers.
    """

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


def _make(tmp_path, pid, world, locations, schedule):
    """A persona sharing *world*, with her own locations and sleep schedule."""
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
        persona_locations=locations,
        sleep_schedule=schedule,
    )


def _make_no_profile(tmp_path, pid, world):
    """A persona with no profile at all, sharing the same world."""
    return LifeService(
        db_path=str(tmp_path / f"{pid}.db"),
        persona_id=pid,
        world_environment=world,
        occupation="baker",
    )


def test_lina_then_roberta_each_keep_their_own_room_and_sleep_phase(tmp_path):
    """Lina (constructed first) must not lose her room/phase to Roberta.

    Lina wakes at 6, sleeps at 22: at 08:00 she is 2h into a 16h waking
    window (frac=0.125), which ``WorldEnvironment._calculate_time_of_day``
    buckets as MORNING. Roberta wakes at 14, sleeps at 6: at 08:00 she is
    18h since her last wake with only a 16h waking window, i.e. already past
    her bedtime, which the same method buckets as LATE_NIGHT. A third,
    no-profile persona added last must fall back to a generic room, not
    inherit either one's.
    """
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)
    control = _make_no_profile(tmp_path, "control", world)

    lina_world = lina.get_status()["world"]
    roberta_world = roberta.get_status()["world"]
    control_world = control.get_status()["world"]

    assert lina_world["location_description"] == LINA_LOCATIONS["home"]
    assert roberta_world["location_description"] == ROBERTA_LOCATIONS["home"]
    assert control_world["location_description"] not in (
        LINA_LOCATIONS["home"], ROBERTA_LOCATIONS["home"],
    )

    assert lina_world["time_of_day"] == "morning"
    assert roberta_world["time_of_day"] == "late_night"

    # The mechanism behind the measured 46% disagreement: _on_energy_tick (and
    # the desire/habitation/behavior/memory ticks alongside it) reads
    # LifeService._persona_time_of_day, not self._world.time_of_day directly.
    # Asserted on the enum itself, not just its rendered string in get_status().
    assert lina._persona_time_of_day is TimeOfDay.MORNING
    assert roberta._persona_time_of_day is TimeOfDay.LATE_NIGHT

    assert LINA_LOCATIONS["home"] in lina.get_life_context()
    assert ROBERTA_LOCATIONS["home"] in roberta.get_life_context()
    assert LINA_LOCATIONS["home"] not in roberta.get_life_context()
    assert ROBERTA_LOCATIONS["home"] not in lina.get_life_context()


def test_roberta_then_lina_each_keep_their_own_room_and_sleep_phase(tmp_path):
    """Same as above with construction order reversed: Roberta first.

    Proves the fix is not just "the first persona wins" -- the bug was that
    the *last* persona constructed won, so reversing order is what the
    original bug would have flipped.
    """
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)

    lina_world = lina.get_status()["world"]
    roberta_world = roberta.get_status()["world"]

    assert lina_world["location_description"] == LINA_LOCATIONS["home"]
    assert roberta_world["location_description"] == ROBERTA_LOCATIONS["home"]
    assert lina_world["location_description"] != roberta_world["location_description"]

    assert lina_world["time_of_day"] == "morning"
    assert roberta_world["time_of_day"] == "late_night"

    assert lina._persona_time_of_day is TimeOfDay.MORNING
    assert roberta._persona_time_of_day is TimeOfDay.LATE_NIGHT

    assert LINA_LOCATIONS["home"] in lina.get_life_context()
    assert ROBERTA_LOCATIONS["home"] in roberta.get_life_context()
    assert LINA_LOCATIONS["home"] not in roberta.get_life_context()
    assert ROBERTA_LOCATIONS["home"] not in lina.get_life_context()


def test_a_private_world_is_unaffected(tmp_path):
    """A service that builds its own world (no ``world_environment=``) must
    behave exactly as before: its own locations/schedule, nothing shared --
    and (fix round 1, Critical) ``get_status()`` must read the world's
    CACHED phase, never recompute it live.

    Before the fix, ``LifeService.get_status()`` always forwarded
    ``sleep_schedule=self._sleep_schedule`` to the world, and
    ``WorldEnvironment.get_time_of_day`` takes the recompute-at-now branch
    whenever that argument is not ``None`` -- true for a private world too,
    since it has a real schedule. Reproduced here exactly as the reviewer
    found it: tick once at 07:30 (Lina is 1.5h into her 16h waking window,
    frac=0.09375 -> MORNING), then move the clock to 11:45 with no second
    tick (5.75h in, frac=0.359375 -> AFTERNOON if recomputed live) and read
    ``get_status()`` again -- it must still say MORNING.
    """
    svc = LifeService(
        db_path=str(tmp_path / "solo.db"),
        persona_id="solo",
        occupation="baker",
        persona_locations=LINA_LOCATIONS,
        sleep_schedule=LINA_SCHEDULE,
    )
    clock = _AdvancingClock(datetime(2031, 3, 10, 7, 30))
    svc._world._now = clock
    svc._world.tick()

    world_status = svc.get_status()["world"]
    assert world_status["location_description"] == LINA_LOCATIONS["home"]
    assert LINA_LOCATIONS["home"] in svc.get_life_context()
    assert world_status["time_of_day"] == "morning"

    clock.instant = datetime(2031, 3, 10, 11, 45)  # moved on; no second tick

    world_status = svc.get_status()["world"]
    # Still the tick's phase, not a live recompute at the new instant.
    assert world_status["time_of_day"] == "morning"
    # Matches _persona_time_of_day (which never recomputes for a private
    # world) and matches a bare self._world.get_status() -- the pre-Task-2
    # call -- exactly.
    assert world_status["time_of_day"] == svc._persona_time_of_day.value
    assert world_status["time_of_day"] == svc._world.get_status()["time_of_day"]


def test_export_outer_state_shows_each_personas_own_room_and_time(tmp_path):
    """LifeService.export_outer_state() -- the host's digest input -- must
    not leak between personas sharing a world, same as get_status()."""
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)

    lina_world = lina.export_outer_state()["world"]
    roberta_world = roberta.export_outer_state()["world"]

    assert lina_world["location_description"] == LINA_LOCATIONS["home"]
    assert roberta_world["location_description"] == ROBERTA_LOCATIONS["home"]
    assert lina_world["time_of_day"] == "morning"
    assert roberta_world["time_of_day"] == "late_night"

    # Ambiance's location clause must be this persona's own too, not generic.
    assert LINA_LOCATIONS["home"] in lina_world["ambiance"]
    assert ROBERTA_LOCATIONS["home"] in roberta_world["ambiance"]
    assert LINA_LOCATIONS["home"] not in roberta_world["ambiance"]
    assert ROBERTA_LOCATIONS["home"] not in lina_world["ambiance"]


def test_a_private_worlds_export_outer_state_is_unchanged(tmp_path):
    """A private world's export_outer_state()["world"]: time_of_day and
    ambiance still come from the world's own tracked/cached fields (matching
    a bare self._world.export_state() call exactly); location_description is
    a new, additive key."""
    svc = LifeService(
        db_path=str(tmp_path / "solo.db"),
        persona_id="solo",
        occupation="baker",
        persona_locations=LINA_LOCATIONS,
        sleep_schedule=LINA_SCHEDULE,
    )
    world_export = svc.export_outer_state()["world"]
    bare = svc._world.export_state()

    assert world_export["time_of_day"] == bare["time_of_day"]
    assert world_export["ambiance"] == bare["ambiance"]
    assert world_export["location_description"] == LINA_LOCATIONS["home"]


def test_bare_world_none_defaults_return_the_tracked_phase():
    """WorldEnvironment.get_status()/get_time_of_day()/export_state(), called
    with no arguments, all agree with the tracked/cached phase after a tick,
    and none of them recompute it live once the clock moves on without a
    second tick -- the None-default branch every private-world guarantee in
    this task relies on."""
    clock = _AdvancingClock(datetime(2031, 3, 10, 7, 30))
    world = WorldEnvironment(now=clock)
    world.tick()

    assert world.get_time_of_day() == world.time_of_day
    assert world.get_status()["time_of_day"] == world.time_of_day.value
    assert world.export_state()["time_of_day"] == world.time_of_day.value

    tracked = world.time_of_day
    clock.instant = datetime(2031, 3, 10, 11, 45)  # moved on; no second tick

    assert world.get_time_of_day() == tracked
    assert world.get_status()["time_of_day"] == tracked.value
    assert world.export_state()["time_of_day"] == tracked.value


def test_override_location_lookup_is_case_insensitive(tmp_path):
    """A persona's own persona_locations key may differ in case from the
    lookup key ("home"); her override still wins, sharing a world with
    another persona whose own locations must not leak in either direction."""
    mixed_case_locations = {"Home": "her attic studio, skylights and dust"}
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    lina = _make(tmp_path, "lina", world, mixed_case_locations, LINA_SCHEDULE)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)

    assert lina.get_status()["world"]["location_description"] == mixed_case_locations["Home"]
    assert roberta.get_status()["world"]["location_description"] == ROBERTA_LOCATIONS["home"]


def test_a_personas_own_locations_beat_the_shared_worlds_base(tmp_path):
    """A WorldEnvironment constructed with its own baseline persona_locations
    (e.g. built by whichever persona happened to create it) must not leak
    through to a persona sharing it with different text for the same key --
    the override replaces the base outright, it never merges with it."""
    world = WorldEnvironment(
        now=lambda: WORLD_INSTANT,
        persona_locations={"home": "baseline description nobody chose"},
    )
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)

    location_description = lina.get_status()["world"]["location_description"]
    assert location_description == LINA_LOCATIONS["home"]
    assert location_description != "baseline description nobody chose"


def test_persona_world_view_current_location_is_the_personas_own_not_the_worlds():
    """Task 27 (ruling T8-R1) corrects Task 2's ``PersonaWorldView``: weather
    is genuinely shared physical state and still passes through untouched,
    but ``current_location`` does not -- it is this persona's own (the third
    constructor argument, a zero-argument callable), never the wrapped
    world's. Passing straight through is exactly the bug: it is what let one
    persona's move relocate every persona sharing the world."""
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    world.move_to("cafe")
    view = PersonaWorldView(world, LINA_LOCATIONS, lambda: "home")

    assert view.weather == world.weather
    assert view.get_weather_description() == world.get_weather_description()
    assert view.current_location == "home"
    assert view.current_location != world.current_location


def test_persona_world_view_get_location_description_defaults_to_her_own_location():
    """With no explicit ``location`` argument, ``get_location_description()``
    must describe this persona's own current location (from the callable),
    not the wrapped world's -- the mechanism behind
    ``LifeContextBuilder``'s ``**Where you are:**`` line for a shared
    world."""
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    world.move_to("cafe")  # the shared world is physically elsewhere
    view = PersonaWorldView(world, LINA_LOCATIONS, lambda: "home")

    assert view.get_location_description() == LINA_LOCATIONS["home"]


class _LegacyDuckTypedWorld:
    """A handed world whose ``get_status``/``export_state`` take no
    arguments -- the shape every ``WorldEnvironment`` had before this task,
    and the shape any older duck-typed world still has. Everything else a
    ``LifeService`` construction touches (``now``, ``tick``, ``time_of_day``,
    ``weather``, ``current_location``, ``_persona_locations``,
    ``_sleep_schedule``) is stubbed minimally, matching
    ``tests/test_energy_clock.py``'s ``BareWorld``.
    """

    def __init__(self, now):
        self._now = now
        self._persona_locations: dict = {}
        self._sleep_schedule = None

    def now(self):
        return self._now()

    def tick(self):
        pass

    def move_to(self, location):
        pass

    @property
    def time_of_day(self):
        return TimeOfDay.MORNING

    @property
    def weather(self):
        return None

    @property
    def current_location(self):
        return "home"

    def get_location_description(self, location=None):
        return "somewhere, unscoped"

    def get_weather_description(self):
        return ""

    def get_status(self):
        return {
            "location": "home",
            "location_description": "somewhere, unscoped",
            "time_of_day": "morning",
        }

    def export_state(self):
        return {"location": "home", "time_of_day": "morning", "ambiance": "somewhere, unscoped."}


def test_get_status_and_export_state_tolerate_a_legacy_duck_typed_world(tmp_path):
    """A handed world whose get_status/export_state predate the persona
    overrides (took no arguments) must not raise -- LifeService falls back
    to calling them bare, exactly the tolerance _persona_time_of_day already
    has for a world with no get_time_of_day at all."""
    world = _LegacyDuckTypedWorld(now=lambda: WORLD_INSTANT)
    svc = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)

    assert svc.get_status()["world"] == world.get_status()
    assert svc.export_outer_state()["world"]["time_of_day"] == "morning"
    assert svc.export_outer_state()["world"]["ambiance"] == "somewhere, unscoped."


# ----------------------------------------------------------------------
# Task 27 (ruling T8-R1): current_location joins persona_locations/
# sleep_schedule as per-persona state on a shared world.
# ----------------------------------------------------------------------

def test_moving_one_persona_never_relocates_the_other_sharing_the_world(tmp_path):
    """The acceptance scenario: Lina moves (a public call that used to write
    the shared world's ``current_location`` directly); Roberta, sharing the
    same world and untouched, must still read "home" from her own
    ``get_status()``/``export_outer_state()`` -- not wherever Lina went."""
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)

    lina.schedule_meeting_arrival("cafe")

    assert lina.get_status()["world"]["location"] == "cafe"
    assert roberta.get_status()["world"]["location"] == "home"
    assert roberta.get_status()["world"]["location_description"] == ROBERTA_LOCATIONS["home"]

    assert lina.export_outer_state()["world"]["location"] == "cafe"
    assert roberta.export_outer_state()["world"]["location"] == "home"

    # [Fix round 1, Minor] The shared WorldEnvironment's own raw
    # current_location must never be written by a persona's move -- proven
    # directly on the wrapped object, not only through each persona's own
    # view of it, so deleting _move_persona_to's `_shared_world` guard fails
    # this even if a future change happened to keep both personas' own
    # statuses looking right some other way.
    assert world.current_location == "home"

    assert ROBERTA_LOCATIONS["home"] in roberta.get_life_context()


def test_moving_roberta_never_relocates_lina_either(tmp_path):
    """Same property with the mover and the bystander swapped, so the fix is
    not just "whichever persona is built (or moves) first/last wins"."""
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)

    roberta.schedule_meeting_arrival("the park")

    assert roberta.get_status()["world"]["location"] == "the park"
    assert lina.get_status()["world"]["location"] == "home"
    assert lina.get_status()["world"]["location_description"] == LINA_LOCATIONS["home"]
    assert lina.export_outer_state()["world"]["location"] == "home"


def test_get_status_ambiance_reflects_each_personas_own_location_when_shared(tmp_path):
    """[Fix round 1, Important] ``get_status()["world"]["ambiance"]`` must be
    rebuilt from this persona's own location when a location override is
    given -- mirroring ``export_state()`` -- not stay this world's own cached
    sentence. Reproduced: Lina moves to "cafe"; before this fix her
    ``get_status()["world"]`` showed ``location="cafe"`` but ``ambiance``
    still described "home" (the cached sentence, frozen since a shared
    world's own ``current_location`` is never written by a persona's move --
    Task 27 / ruling T8-R1), contradicting itself in the same dict. Roberta,
    untouched, must still see her own home in her ambiance, not Lina's cafe.
    """
    world = WorldEnvironment(now=lambda: WORLD_INSTANT)
    lina = _make(tmp_path, "lina", world, LINA_LOCATIONS, LINA_SCHEDULE)
    roberta = _make(tmp_path, "roberta", world, ROBERTA_LOCATIONS, ROBERTA_SCHEDULE)

    lina.schedule_meeting_arrival("cafe")

    lina_ambiance = lina.get_status()["world"]["ambiance"]
    roberta_ambiance = roberta.get_status()["world"]["ambiance"]

    assert "cafe" in lina_ambiance
    assert LINA_LOCATIONS["home"] not in lina_ambiance

    assert ROBERTA_LOCATIONS["home"] in roberta_ambiance
    assert "cafe" not in roberta_ambiance


def test_a_private_worlds_move_still_moves_the_world_itself(tmp_path):
    """A private (unshared) world keeps today's behaviour: the service may
    still write its own world directly, so the WorldEnvironment's own
    current_location moves too, not just the service's status."""
    svc = LifeService(
        db_path=str(tmp_path / "solo.db"),
        persona_id="solo",
        occupation="baker",
        persona_locations=LINA_LOCATIONS,
        sleep_schedule=LINA_SCHEDULE,
    )
    svc.schedule_meeting_arrival("cafe")

    assert svc.get_status()["world"]["location"] == "cafe"
    assert svc._world.current_location == "cafe"
    assert svc.export_outer_state()["world"]["location"] == "cafe"


def test_bs_production_cadence_trace_is_identical_whatever_as_sociability_is(tmp_path):
    """Acceptance (Task 27 / ruling T8-R1): a production-cadence trace of
    persona B (default traits) must be byte-identical whether her world-mate
    A has traits ``{sociability: 0.1}`` or ``{sociability: 0.9}``, same
    seeds. Task 26 already gave every engine its own random stream, so the
    only way A's traits could still move B's trace is state that leaks
    through the shared ``WorldEnvironment`` -- the current_location bug this
    task fixes (A's activity/location choices differ with her sociability,
    and before this fix every read of ``current_location`` on B's own tick
    path saw wherever A had last moved the shared world).

    Seed 7 over 3 simulated days is the smallest reproduction found probing
    seeds 1/7/42/99/2027 over 2-3 days with default personas: before this
    task's fix, B's step 819 activity diverges ("thinking about user" vs
    "meditating") purely from A's sociability, with no change to B's own
    inputs or rng stream.
    """

    def _traced(sociability: float):
        personas = [
            SimPersona(
                persona_id="a",
                service_kwargs={"definition": PersonalityDefinition(traits={"sociability": sociability})},
            ),
            SimPersona(persona_id="b"),
        ]
        return run_days(personas, days=3, cadence=PRODUCTION, seed=7)

    trace_low = _traced(0.1)
    trace_high = _traced(0.9)

    assert trace_low.errors == []
    assert trace_high.errors == []
    # Sanity: the perturbation must actually reach A, or B's non-difference
    # would prove nothing.
    assert trace_low.records["a"] != trace_high.records["a"]
    assert trace_low.records["b"] == trace_high.records["b"]
