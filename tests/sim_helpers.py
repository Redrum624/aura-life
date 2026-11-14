"""Drive LifeServices on a simulated clock and record what each step did.

Shared by the humanness tests. ``run_days(personas, days, step_minutes, seed)``
builds one :class:`~aura_life.life_service.LifeService` per :class:`SimPersona`
on a single shared :class:`~aura_life.world.WorldEnvironment` whose clock is
simulated, then advances that clock for ``days`` simulated days and appends one
:class:`StepRecord` per persona per step to the returned :class:`SimTrace`.
Two cadences:

* ``cadence=LEGACY`` (the default): the clock steps ``step_minutes`` at a time
  and each step ticks the world once and calls every service's
  ``_scheduler.force_all_ticks()`` once -- the same cadence as the reference
  probe in ``docs/analyses/aura-life-humanness_2026-09-25_harness/run_sim.py``,
  which is where the measurements this program answers came from.
* ``cadence=PRODUCTION``: each tick runs at its own interval in
  ``LifeScheduler.TICK_INTERVAL_MINUTES``, the way the scheduler runs a live
  service, and the clock steps at the smallest of them (``step_minutes`` is
  then that, and may be left out). A tick is due on a step when a whole number
  of its intervals has passed since the start; due ticks run in
  ``LifeScheduler.TICK_ORDER``. The shared world is ticked on the steps its
  world tick is due.

Every persona starts in step with her own schedule because a new
``LifeService`` does (``EnergySystem.start_on_schedule``): awake since that
day's wake time, or asleep if the run starts inside her night.

The acceptance measures read her *effective* nights (:func:`effective_nights`):
her schedule's bedtime and wake time, with the weekend shifts on Friday and
Saturday nights -- the window her own schedule gives that night. The nightly
variance is not in it; it has to fit in the slack of the threshold.

For the length of the run, and restored afterwards:

* the hooks are local fakes: ``get_config`` answers a tmp ``data_dir`` with
  ``place_enabled=False``, and ``persona_now`` answers the simulated instant;
* module ``random`` is seeded with ``seed``, and each service gets its own
  ``random.Random`` derived from ``seed`` and its persona id;
* every ``aura_life`` module that imported the ``datetime`` class sees one whose
  ``now()`` is the simulated instant, so a host-clock read somewhere in the
  library (the daily planner's "today", say) agrees with the world clock the
  way it does in a real host, and a run is reproducible whatever the date and
  time the suite happens to run at;
* the process-wide ``EmotionPersistence`` cache holds nothing for the simulated
  persona ids, so a second run never writes into the first run's directory;
* every SQLite connection opened runs with ``PRAGMA synchronous=OFF`` and keeps
  its rollback journal in memory. The library opens a connection and commits
  several times per tick, and on Windows each commit's fsync and journal file
  made a three-persona, three-day run take over half a minute; durability is
  not something a simulation measures.

Adding a measured field: give :class:`StepRecord` a new field with a default and
fill it in :func:`_record_step`.

Personas who live together (Task 11) take ``household=`` in their
``service_kwargs`` -- one ``aura_life.social.Household`` for all of them, a
fresh one per run. A step's records are taken after every service has ticked,
and every probe is reset before any does, so the one who joins another's
activity -- during the other's tick -- has it in her record.
"""

from __future__ import annotations

import logging
import random
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from aura_life import hooks
from aura_life.emotion.emotion_persistence import clear_emotion_persistence
from aura_life.energy import EnergySystem
from aura_life.life_service import LifeService
from aura_life.scheduler.life_scheduler import LifeScheduler
from aura_life.world import WorldEnvironment

#: Every tick every step, ``step_minutes`` apart (see the module docstring).
LEGACY = "legacy"
#: Each tick at LifeScheduler's own interval (see the module docstring).
PRODUCTION = "production"

#: A Monday, 15:00. Every sleep schedule the humanness program tests
#: (23:00-07:00, 03:00-11:00, 05:00-13:00, each +/- its variance) is awake at
#: this hour, and the nights that follow are weekday nights, so no weekend
#: shift moves the first three.
DEFAULT_START = datetime(2026, 10, 5, 15, 0)

#: The nights a weekend shift moves: Friday's and Saturday's, by the date of the
#: evening (``date.weekday()``). Written out here rather than read from the
#: library, so the measure is the definition, not the code under test.
WEEKEND_NIGHTS = (4, 5)


@dataclass
class SimPersona:
    """One persona to simulate: its id, its sleep schedule, and any other
    ``LifeService`` keyword arguments (``definition=``, ``occupation=`` ...)."""

    persona_id: str
    sleep_schedule: Optional[dict] = None
    service_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepRecord:
    """What one persona looked like after one simulated step."""

    t: datetime
    #: Asleep through the step: ``LifeService.is_asleep()`` says so after the
    #: step's ticks *and* the step recorded no waking activity (nothing, or
    #: only a "sleeping" entry). A persona the host would call asleep while her
    #: activity tick has her stretching was not asleep.
    asleep: bool
    #: The activity the step's ticks recorded, if any (the last one).
    activity: Optional[str]
    #: That activity's ``ActivityLog.energy_before``.
    activity_energy_before: Optional[float]
    #: Effective energy after the step's ticks.
    energy: float
    #: The activity tick's forced-rest decision -- the first
    #: ``EnergySystem.should_rest()`` it asked. ``None`` when it asked none
    #: (asleep, or a tick that failed before deciding).
    forced_rest: Optional[bool]
    #: Her mood after the step's ticks: the label (``mood.current_mood``) and
    #: the (valence, arousal) pair it is read from.
    mood: Optional[str] = None
    valence: Optional[float] = None
    arousal: Optional[float] = None
    #: The ticks that ran this step, in the order they ran.
    ticks: Tuple[str, ...] = ()
    #: Every ``LifeEvent`` the step's ticks recorded (via
    #: ``LifeEventSystem.record_event``, whatever the call path -- on_activity,
    #: on_mood_change, a goal/skill/milestone/chaos hook), as (title,
    #: description) pairs, in the order recorded. The engine's own ``_events``
    #: list is capped (MAX_EVENTS) and, for shareables, reload excludes shared
    #: rows -- so a test that needs every event a multi-day run ever produced
    #: (not just what survives at the end) reads this instead.
    new_life_events: Tuple[Tuple[str, str], ...] = ()
    #: Her hunger after the step's ticks (``SustenanceSystem.hunger``, 0..1).
    hunger: Optional[float] = None
    #: The activity her day's plan has for the hour of this step's activity
    #: tick (``DailyPlanner.get_planned_activity`` at her local hour, read
    #: after the step's ticks), or ``None`` when no activity tick ran this
    #: step or the plan has no slot for that hour.
    planned_activity: Optional[str] = None
    #: How the step's recorded activity went (``ActivityLog.outcome``:
    #: "success", "mixed" or "fail"; Task 14), or ``None`` when the step
    #: recorded none. Her sleep and her intimate activities are logged as
    #: "success" -- they have no outcome roll; a measure of outcomes leaves
    #: them out by name.
    outcome: Optional[str] = None
    #: Her stress after the step's ticks (``AffectSystem.stress.level``) and
    #: what she is stressed about (``stress.sources``, heaviest first; Task 15).
    stress: Optional[float] = None
    stress_sources: Tuple[str, ...] = ()


@dataclass
class SimTrace:
    """Everything :func:`run_days` recorded."""

    start: datetime
    step_minutes: int
    #: persona id -> the sleep schedule its energy system actually uses (the
    #: library default when the persona gave none).
    schedules: Dict[str, dict]
    #: persona id -> one record per step, in order.
    records: Dict[str, List[StepRecord]]
    #: Every ERROR log record the library emitted during the run.
    errors: List[str]
    #: persona id -> the service, for tests that inspect end state.
    services: Dict[str, LifeService]
    #: LEGACY or PRODUCTION.
    cadence: str = LEGACY


# ----------------------------------------------------------------------
# The simulated clock
# ----------------------------------------------------------------------

class _SimClock:
    """The one simulated instant every clock in the run reads."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


_CLOCK: Optional[_SimClock] = None
_REAL_DATETIME = datetime


class _SimDateTimeMeta(type):
    # A real datetime must still pass isinstance(x, datetime) inside the
    # library while its ``datetime`` name is the class below.
    def __instancecheck__(cls, obj):
        return isinstance(obj, _REAL_DATETIME)

    def __subclasscheck__(cls, sub):
        return isinstance(sub, type) and issubclass(sub, _REAL_DATETIME)


class _SimDateTime(_REAL_DATETIME, metaclass=_SimDateTimeMeta):
    """``datetime`` whose ``now()`` is the simulated instant. Everything else --
    arithmetic, ``fromisoformat``, construction -- is inherited."""

    @classmethod
    def now(cls, tz=None):
        instant = _CLOCK.instant
        return instant if tz is None else instant.replace(tzinfo=tz)

    @classmethod
    def today(cls):
        return _CLOCK.instant

    @classmethod
    def utcnow(cls):
        return _CLOCK.instant


# ``fromisoformat`` on the class above builds instances of it; give sqlite3 the
# same text form its default datetime adapter uses, so one of those reaching a
# query binds instead of raising.
sqlite3.register_adapter(_SimDateTime, lambda value: value.isoformat(" "))


_REAL_CONNECT = sqlite3.connect


def _unsynced_connect(*args, **kwargs):
    connection = _REAL_CONNECT(*args, **kwargs)
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA journal_mode=MEMORY")
    return connection


class _ErrorCollector(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(f"{record.name}: {record.getMessage()}")


# ----------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------

def run_days(
    personas: Sequence[SimPersona],
    days: float,
    step_minutes: Optional[int] = None,
    seed: Optional[int] = None,
    *,
    cadence: str = LEGACY,
    start: datetime = DEFAULT_START,
    data_dir: Optional[Path] = None,
) -> SimTrace:
    """Simulate ``days`` days of every persona in ``personas`` at ``cadence``
    (LEGACY: one step, and every tick, every ``step_minutes``; PRODUCTION:
    LifeScheduler's intervals) and return the :class:`SimTrace`. ``seed`` is
    required.

    ``data_dir`` holds each persona's ``life.db``; without one, a temporary
    directory is used and removed when the run ends (the services in the trace
    then keep only their in-memory state).
    """
    if seed is None:
        raise ValueError("run_days needs a seed")
    if cadence == PRODUCTION:
        smallest = min(LifeScheduler.TICK_INTERVAL_MINUTES.values())
        if step_minutes not in (None, smallest):
            raise ValueError(f"the production cadence steps at {smallest} minutes, not {step_minutes}")
        step_minutes = smallest
    elif cadence != LEGACY:
        raise ValueError(f"unknown cadence {cadence!r}")
    elif step_minutes is None:
        raise ValueError("the legacy cadence needs step_minutes")

    if data_dir is None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            return run_days(personas, days, step_minutes, seed, cadence=cadence, start=start,
                            data_dir=Path(tmp))

    global _CLOCK
    clock = _SimClock(start)
    _CLOCK = clock
    data_dir = Path(data_dir)
    n_steps = int(round(days * 24 * 60 / step_minutes))

    saved_hooks = {name: hooks.provider_for(name) for name in hooks.HOOK_NAMES}
    saved_random = random.getstate()
    patched = [
        module for name, module in list(sys.modules.items())
        if name.startswith("aura_life") and getattr(module, "datetime", None) is _REAL_DATETIME
    ]
    collector = _ErrorCollector()
    library_logger = logging.getLogger("aura_life")

    config = SimpleNamespace(data_dir=data_dir, place_enabled=False)
    hooks.configure(
        get_config=lambda: config,
        persona_now=lambda timezone=None: clock.instant,
    )
    for module in patched:
        module.datetime = _SimDateTime
    for persona in personas:
        clear_emotion_persistence(persona.persona_id)
    sqlite3.connect = _unsynced_connect
    library_logger.addHandler(collector)
    random.seed(seed)
    try:
        # WorldEnvironment owns its own rng (ruling T26-R2: it is shared
        # across every persona in this run, so it is never derived from any
        # one persona's stream) -- seeded here so "same seed -> same trace"
        # covers weather too, not only the per-persona streams below.
        world = WorldEnvironment(now=clock, seed=seed)
        services: Dict[str, LifeService] = {}
        for persona in personas:
            (data_dir / persona.persona_id).mkdir(parents=True, exist_ok=True)
            services[persona.persona_id] = LifeService(
                db_path=str(data_dir / persona.persona_id / "life.db"),
                persona_id=persona.persona_id,
                world_environment=world,
                sleep_schedule=persona.sleep_schedule,
                rng=random.Random(f"{seed}:{persona.persona_id}"),
                **persona.service_kwargs,
            )

        probes = {pid: _Probe(svc) for pid, svc in services.items()}
        records: Dict[str, List[StepRecord]] = {pid: [] for pid in services}
        try:
            for step in range(1, n_steps + 1):
                clock.instant = start + timedelta(minutes=step_minutes * step)
                due = _due_ticks(cadence, step_minutes * step)
                if "world" in due:
                    world.tick()
                # Every probe is reset before any service ticks: a housemate
                # who joins another's activity (Task 11) has it recorded
                # during the other's tick, before her own.
                for probe in probes.values():
                    probe.reset()
                for pid, svc in services.items():
                    if cadence == LEGACY:
                        svc._scheduler.force_all_ticks()
                    else:
                        for tick in due:
                            svc._scheduler.force_tick(tick)
                    records[pid].append(_record_step(clock.instant, svc, probes[pid], due))
        finally:
            for probe in probes.values():
                probe.remove()

        return SimTrace(
            start=start,
            step_minutes=step_minutes,
            schedules={pid: dict(svc.energy.sleep_schedule) for pid, svc in services.items()},
            records=records,
            errors=list(collector.messages),
            services=services,
            cadence=cadence,
        )
    finally:
        library_logger.removeHandler(collector)
        sqlite3.connect = _REAL_CONNECT
        for persona in personas:
            clear_emotion_persistence(persona.persona_id)
        for module in patched:
            module.datetime = _REAL_DATETIME
        random.setstate(saved_random)
        hooks.reset()
        hooks.configure(**{name: p for name, p in saved_hooks.items() if p is not None})
        _CLOCK = None


class _Probe:
    """Watches one service for a step: the activity it records and the
    forced-rest decision its activity tick takes."""

    def __init__(self, svc: LifeService):
        self._svc = svc
        self._scheduler = svc._scheduler
        self._original_record = svc._record_activity
        self._original_activity_tick = self._scheduler._on_activity_tick
        self._life_events = svc._life_events
        self._original_record_event = self._life_events.record_event
        svc._record_activity = self._record
        self._scheduler._on_activity_tick = self._activity_tick
        self._life_events.record_event = self._record_event
        self.reset()

    def reset(self) -> None:
        self.activity: Optional[str] = None
        self.activity_energy_before: Optional[float] = None
        self.outcome: Optional[str] = None
        self.rest_decisions: List[bool] = []
        self.new_life_events: List[Tuple[str, str]] = []

    def remove(self) -> None:
        self._svc.__dict__.pop("_record_activity", None)
        self._scheduler._on_activity_tick = self._original_activity_tick
        self._life_events.__dict__.pop("record_event", None)

    def _record(self, log) -> None:
        self._original_record(log)
        self.activity = log.activity_name
        self.activity_energy_before = log.energy_before
        self.outcome = getattr(log, "outcome", None)

    def _record_event(self, *args, **kwargs):
        event = self._original_record_event(*args, **kwargs)
        self.new_life_events.append((event.title, event.description))
        return event

    def _activity_tick(self) -> None:
        energy = self._svc._energy
        should_rest = energy.should_rest

        def spy():
            decision = should_rest()
            self.rest_decisions.append(decision)
            return decision

        energy.should_rest = spy
        try:
            self._original_activity_tick()
        finally:
            energy.__dict__.pop("should_rest", None)


def _due_ticks(cadence: str, minutes_since_start: int) -> Tuple[str, ...]:
    """The ticks that run on the step ``minutes_since_start`` into the run:
    every tick in LEGACY; in PRODUCTION, each tick a whole number of whose
    intervals has passed."""
    if cadence == LEGACY:
        return LifeScheduler.TICK_ORDER
    return tuple(
        tick for tick in LifeScheduler.TICK_ORDER
        if minutes_since_start % LifeScheduler.TICK_INTERVAL_MINUTES[tick] == 0
    )


def _planned_activity(svc: LifeService, ticks: Tuple[str, ...]) -> Optional[str]:
    """The plan's activity for her local hour, when this step ran an activity tick."""
    if "activity" not in ticks:
        return None
    slot = svc._daily_planner.get_planned_activity(svc.persona_local_hour())
    return slot.activity_name if slot is not None else None


def _record_step(t: datetime, svc: LifeService, probe: _Probe, ticks: Tuple[str, ...]) -> StepRecord:
    mood = svc._affect.mood
    return StepRecord(
        t=t,
        asleep=svc.is_asleep() and probe.activity in (None, "sleeping"),
        activity=probe.activity,
        activity_energy_before=probe.activity_energy_before,
        energy=svc.energy.effective_level,
        forced_rest=probe.rest_decisions[0] if probe.rest_decisions else None,
        mood=mood.current_mood,
        valence=mood.valence,
        arousal=mood.arousal,
        ticks=ticks,
        new_life_events=tuple(probe.new_life_events),
        hunger=svc._sustenance.hunger,
        planned_activity=_planned_activity(svc, ticks),
        outcome=probe.outcome,
        stress=svc._affect.stress.level,
        stress_sources=tuple(svc._affect.stress.sources),
    )


# ----------------------------------------------------------------------
# Measures over a trace
# ----------------------------------------------------------------------

def _minute_of_day(hour: int, minute: int) -> int:
    return (hour * 60 + minute) % (24 * 60)


def in_sleep_window(t: datetime, schedule: dict) -> bool:
    """True when ``t`` falls inside the schedule's nominal [bedtime, wake)
    window -- the persona's own window, with no variance or weekend shift."""
    bed = _minute_of_day(schedule.get("bedtime_hour", 23), schedule.get("bedtime_minute", 0))
    wake = _minute_of_day(schedule.get("wake_hour", 7), schedule.get("wake_minute", 0))
    now = _minute_of_day(t.hour, t.minute)
    if bed < wake:
        return bed <= now < wake
    return now >= bed or now < wake


def nominal_nights(trace: SimTrace, persona_id: str) -> List[Tuple[datetime, datetime]]:
    """Every nominal sleep window (bedtime, wake) lying wholly inside the run."""
    schedule = trace.schedules[persona_id]
    first, last = trace.records[persona_id][0].t, trace.records[persona_id][-1].t
    bed_minutes = _minute_of_day(schedule.get("bedtime_hour", 23), schedule.get("bedtime_minute", 0))
    wake_minutes = _minute_of_day(schedule.get("wake_hour", 7), schedule.get("wake_minute", 0))
    length = timedelta(minutes=(wake_minutes - bed_minutes) % (24 * 60) or 24 * 60)
    nights = []
    day: date = first.date() - timedelta(days=1)
    while True:
        bedtime = datetime.combine(day, datetime.min.time()) + timedelta(minutes=bed_minutes)
        if bedtime > last:
            return nights
        if bedtime >= first and bedtime + length <= last:
            nights.append((bedtime, bedtime + length))
        day += timedelta(days=1)


def effective_nights(trace: SimTrace, persona_id: str) -> List[Tuple[datetime, datetime]]:
    """Every night's effective window (bedtime, wake) lying wholly inside the run.

    A night is her schedule's bedtime and wake time for the evening it starts
    on, moved later by ``weekend_bedtime_shift`` / ``weekend_wake_shift`` when
    that evening is a Friday or a Saturday (:data:`WEEKEND_NIGHTS`); a field
    the schedule leaves out takes ``EnergySystem.DEFAULT_SLEEP_SCHEDULE``'s
    value. No variance: a night's own draw is not part of her window.
    """
    schedule = dict(EnergySystem.DEFAULT_SLEEP_SCHEDULE, **trace.schedules[persona_id])
    first, last = trace.records[persona_id][0].t, trace.records[persona_id][-1].t
    bed_minutes = _minute_of_day(schedule["bedtime_hour"], schedule["bedtime_minute"])
    wake_minutes = _minute_of_day(schedule["wake_hour"], schedule["wake_minute"])
    length = timedelta(minutes=(wake_minutes - bed_minutes) % (24 * 60) or 24 * 60)
    nights = []
    evening: date = first.date() - timedelta(days=2)
    while True:
        wake = datetime.combine(evening + timedelta(days=1), datetime.min.time()) + timedelta(minutes=wake_minutes)
        bedtime = wake - length
        if evening.weekday() in WEEKEND_NIGHTS:
            bedtime += timedelta(minutes=schedule["weekend_bedtime_shift"])
            wake += timedelta(minutes=schedule["weekend_wake_shift"])
        if bedtime > last:
            return nights
        if bedtime >= first and wake <= last:
            nights.append((bedtime, wake))
        evening += timedelta(days=1)


def in_windows(t: datetime, windows: Sequence[Tuple[datetime, datetime]]) -> bool:
    """True when ``t`` falls inside one of the [bedtime, wake) ``windows``."""
    return any(bedtime <= t < wake for bedtime, wake in windows)


def sleep_episodes(records: Sequence[StepRecord]) -> List[Tuple[datetime, Optional[datetime]]]:
    """Contiguous runs of asleep steps: (first asleep step, first awake step
    after it -- ``None`` when the run ends asleep)."""
    episodes = []
    onset = None
    for record in records:
        if record.asleep and onset is None:
            onset = record.t
        elif not record.asleep and onset is not None:
            episodes.append((onset, record.t))
            onset = None
    if onset is not None:
        episodes.append((onset, None))
    return episodes
