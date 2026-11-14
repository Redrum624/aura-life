"""Setting packs (humanness program Task 9, spec section 4.4).

Section 1 pins what the default setting does, so the move of today's
catalogues into the ``contemporary`` pack can be shown to change nothing: a
seeded, production-cadence, two-day run of two personas is fingerprinted step
by step and compared against ``tests/fixtures/default_setting_trace.json``,
which was recorded from the code *before* Task 9 moved anything (commit
5de90c9). Every engine now draws from its own stream (Task 26), so a move that
changed any engine's draw count or order -- or any text it produced -- shows
up here as the first step whose fingerprint differs.

Section 2 pins every catalogue the move touches, entry by entry: a run only
samples a catalogue, so each one is also digested whole (dict order and
tuples kept, since the engines iterate some of them in order) and compared
with ``tests/fixtures/default_setting_catalogues.json``: the digests
:func:`legacy_catalogue_views` gave before each catalogue moved (5de90c9 for
the first move; 80d3240 for the ones Task 9's fix round moved), through the
same old import paths and engine methods it reads today.

Both fixtures are recorded, never regenerated silently (ruling T9-R3, the
``PARITY_WRITE_GOLDEN`` convention of ``tests/test_persona_parity.py``): a
missing fixture fails. To re-record one on purpose -- only when the default
setting's behaviour or text changes by design, said so in the commit and the
report -- delete the file and re-run this module with
``SETTING_TRACE_WRITE=1`` (only the exact value "1" opts in).

Both were re-recorded once in Task 9, on purpose (ruling T9-R4): three
contemporary lines hard-coded a verb after the persona's pronoun ("they
was", "they wasn't", "they hasn't" for a nonbinary persona) and now carry
the agreeing token. No step's fingerprint changed; only the plain persona's
end state and the digests of ``nostalgia_fragments``,
``npc_event_templates.friend`` and ``serendipity`` did.

Task 10 changes the default setting's behaviour on purpose and re-records the
trace in each commit that does (ruling T9-R3): hunger rises per world hour
and never drains her energy while she sleeps, and only a meal-tagged
activity feeds her (rulings T4-R4 and T9-R8) -- the first step that moved is
the nurse's hungry first night; then the day's anchors (waking up, the three
meals, bedtime, work, the commute, a class, study, a meetup) became
contemporary activities and a planned slot governs its whole hour, which
moves the ``activities`` digests too; then her activity choice and her
plan's free hours became utility-based, from her traits and tastes; then
her goals and daily intentions became her own (the nurse's interests give
hers); then her wants too (the nurse's interests and media); then intimacy
kept out of her shifts and her sleep window; then (fix round 1) following
her plan at the place it puts her, she stays there for the whole hour
instead of being moved away on the slot's second tick and back on its third.

Task 11 re-records the trace once, on purpose: a friend's contact now eases
her loneliness (a call or time together as a meaningful interaction, a text
or an invitation a small one). The nurse's two people are friends: time with
Sam at step 27 eases her loneliness, which first shows in a step at step 62,
where her mood would have begun to read it (AffectSystem's NEED_FLOORS). The
plain persona, who has no one, and every plan and activity row are as they
were; with the relief switched off, the recording replays step for step.

Task 12's fix round re-records both, on purpose (ruling T12-R4): two chaos
lines hard-coded a third-person verb after the persona's pronoun ("...{subj}
never visits", "...{subj} usually misses": "they never visits" for a
nonbinary persona, "you never visits" in her memory stream) and now agree
through the ``{s}`` token ("never visit{s}", "usually overlook{s}"). Only
the ``activity_chaos`` and ``universal_chaos`` digests moved; neither line is
drawn in the two recorded days, so no step, plan, activity row or end state
did.

Task 14 re-records the trace once, on purpose: an activity has an outcome
now -- it goes well, only half well or wrong, rolled on her own "outcome"
stream from her skill at it, her energy and her mood -- told in her
setting's words when it did not go well, and what she feels about it is
her appraisal of it (her goals, needs and values, whose doing it was, how
expected it was) instead of the setting's fixed emotions; a failure moves no
goal and fulfils no want, and what did not go well is no life event. Every
step from the first activity on moves (its feelings, and so her mood and
what she chooses next), and every activity_logs row gains its ``outcome``
column. The catalogue digests do not move: each activity's new ``outcomes``
texts are outside the views pinned there.

Task 14's fix round re-records the trace once more, on purpose (ruling
T14-R1): each persona-local day now has a quality of its own -- a valence
offset on her mood's target, drawn at her first waking tick outside her
sleep window on its own "day_quality" stream -- so her mood, and with it
what she chooses and how her activities go, moves from the first tick on.

Task 15 re-records the trace once, on purpose: her stress is what her
stressors weigh while they last (a stressor's severity, recomputed as they
come and go), no longer a one-time bump per new label wearing off by the
tick. Both personas carry money worries from the first energy tick, so from
the first activity tick on (step 3) she comes to her activities a little
less stressed than the old bump left her, and the "calm" she feels about one
that eases her stress -- her appraisal reads it -- is a little less: the
activity rows' ``emotions_triggered`` move (30 of the plain persona's 99, 36
of the nurse's 95), her mood by at most 0.008 in valence, its label on 7 of
the plain persona's steps and 1 of the nurse's, with the life events and
shareables that follow from them. No activity, plan or location moves in
the two days. Everything else Task 15 adds -- coping from her traits, which
is nothing for these two neutral personas -- replays the old recording step
for step with the old stress model in place.

Task 15's completion re-records the trace once more, on purpose: no
behaviour of the library changes, the run stops reading the host's date. A
model whose time defaulted to "now" (a goal's, a want's, a plan's
``created_at``, a social event's ``timestamp`` ...) took it from the host's
clock, bound at import (``default_factory=datetime.now``), which sim_helpers'
simulated instant never reached; now ``aura_life.models._now`` reads the
module's ``datetime`` when the record is made. The recording of 2026-09-27
had those stamps two weeks before the simulated Monday; on 2026-11-13 they
were a month after it, and the trace stopped replaying from the nurse's step
15 and the plain persona's step 63 -- on the code before Task 15 as well
(the Task 15 report). With every stamp at the simulated instant the trace
is the one any host date after 2026-10-12 gave, step for step; with the
stamps pinned to 2026-09-27 the old recording replays.

Task 29 re-records the trace once, on purpose: her money is on the world
clock. A new persona starts with STRESS_RUNWAY_CEILING months of her
expenses (FinanceSystem.starting_balance) instead of FinancialState's 1,200,
which held "money worries" from her first energy tick; her discretionary
purchases are drawn per world hour against a monthly budget from her
surplus, no longer a chance per tick; an activity is paid for once in its
world hour. Both personas' valence and arousal move from step 4 (the first
activity tick) on; the plain persona's activity at step 4 goes another way
("thinking about user" for "listening to music") and her two days with it
(activities, plans, life events, goals, end state); the nurse's activities
and plans do not move, her mood label on one step and her activity rows'
feelings do. Only ``money/finance_system.py`` and the instant
``LifeService`` passes ``FinanceSystem.on_activity`` changed.

Task 31 re-records the trace once, on purpose: re-recorded by Task 31:
0.5.0's dated habits replace the undated habit term in her picks and plans
(the merge of aura-life 0.5.0). Diagnosed before re-recording, on the merged
tree (the three arms of the task's diag_trace.py): as it is, the nurse's
step 359 is the first that differs; with no habit anywhere
(``LifeService._habit_factors`` returning ``{}``) the plain persona's step
383; with no habit AND the removed term put back in
``ActivityPreferences.utility`` (1.0 times her history's share) the old
recording replays exactly -- so nothing else the merge brought moves it.
"""

import contextlib
import hashlib
import json
import logging
import os
import pathlib
import random
import shutil
import sqlite3
from datetime import datetime
from enum import Enum
from types import SimpleNamespace

import pytest

from aura_life.activities.activity_engine import ActivityEngine
from aura_life.intimacy.desire_system import INTIMATE_ACTIVITIES
from aura_life.life_service import LifeService
from aura_life.models import (
    Activity,
    ActivityCategory,
    DailyPlan,
    PlannedSlot,
    TimeOfDay,
    TransitPhase,
    TransitState,
    Weather,
)
from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.settings import (
    DEFAULT_SETTING,
    CatchUpNarratives,
    SettingSpec,
    get_setting,
    register_setting,
    unregister_setting,
)

from sim_helpers import PRODUCTION, SimPersona, run_days

# ======================================================================
# 1. The default setting replays the trace recorded before the move
# ======================================================================

TRACE_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "default_setting_trace.json"
CATALOGUE_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "default_setting_catalogues.json"
#: The one opt-in that (re)records either fixture (see the module docstring).
TRACE_WRITE_ENV = "SETTING_TRACE_WRITE"
TRACE_SEED = 9
TRACE_DAYS = 2
#: A Monday that is a US public holiday (Columbus Day, the second Monday of
#: October 2026), 15:00: the nurse's first plan meets the holiday calendar
#: (no shift that day) and her second day is a working Tuesday.
TRACE_START = datetime(2026, 10, 12, 15, 0)


def _trace_personas():
    """A persona with nothing on record, and one that reaches every moved
    catalogue a two-day run can: a nationality (holidays), an occupation
    (shifts), interests, two people in her life (NPC events, topics,
    invitations) and media (dream ingredients)."""
    return [
        SimPersona("plain"),
        SimPersona("nurse", service_kwargs=dict(
            definition=PersonalityDefinition(
                id="nurse", name="Nell", nationality="American", occupation="nurse",
                appearance_details={"gender": "female"},
            ),
            occupation="nurse",
            interests=["reading", "music"],
            social_circle=[
                {"name": "Sam", "relationship": "best friend", "personality": "loud",
                 "shared_interests": "music, films"},
                {"name": "Mo", "relationship": "sister", "personality": "calm"},
            ],
            media_preferences={"books": ["Dune", "Emma"], "music": ["jazz"], "shows": ["Taskmaster"]},
        )),
    ]


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, default=str)


def _digest(obj) -> str:
    return hashlib.sha256(_canonical(obj).encode("ascii")).hexdigest()[:16]


def _step_view(record) -> dict:
    return {
        "t": record.t.isoformat(),
        "asleep": record.asleep,
        "activity": record.activity,
        "activity_energy_before": record.activity_energy_before,
        "energy": record.energy,
        "forced_rest": record.forced_rest,
        "mood": record.mood,
        "valence": record.valence,
        "arousal": record.arousal,
        "ticks": list(record.ticks),
        "new_life_events": [list(event) for event in record.new_life_events],
    }


def _activity_rows(db_path: str) -> list:
    """Every activity_logs row the run wrote -- narratives carry the
    activity's own text, the weather suffix, and any NPC, micro-event and
    chaos line appended to it.

    The emotion intensities are rounded to nine places: Python 3.12 made
    ``sum()`` of floats more exact, so 3.11 and 3.12+ store values that
    differ in the last digit (0.14999999999999997 against 0.15) for the same
    life, and the recording must hold on every supported Python."""
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute("SELECT * FROM activity_logs ORDER BY id")]
    for row in rows:
        emotions = row.get("emotions_triggered")
        if emotions:
            row["emotions_triggered"] = {name: round(value, 9) for name, value in json.loads(emotions).items()}
    return rows


def _end_state(svc) -> dict:
    goals = svc._goal_engine
    planner = svc._daily_planner
    return {
        "active_goals": [(g.title, g.timeframe.value, g.progress, g.motivation_level)
                         for g in goals.active_goals],
        "completed_goals": [g.title for g in goals.completed_goals],
        "abandoned_goals": [g.title for g in goals.abandoned_goals],
        "desires": [(d.title, list(d.related_activities), d.urgency, d.fulfilled)
                    for d in planner.all_desires],
        "nostalgia": [(n.trigger, n.memory_reference, n.intensity, n.bittersweet)
                      for n in svc._memory_time._nostalgia_log],
        "skills": {name: (sp.level, list(sp.milestones_reached)) for name, sp in sorted(svc._skills.items())},
        "shareables": [(s.content, s.context, s.priority) for s in svc._shareable_queue],
        "social_events": [(e.npc_name, e.event_type, e.description) for e in svc._social.get_recent_events(10)],
        "chaos": svc._chaos.to_dict(),
        "life_events": [(e.event_type, e.title, e.description, e.source) for e in svc._life_events._events],
        "location": svc._current_location,
        "media": (svc._media.current_book, svc._media.book_progress,
                  svc._media.current_show, svc._media.current_music_obsession),
    }


def record_default_setting_trace(data_dir: pathlib.Path, monkeypatch) -> dict:
    """Run the pinned scenario and return its full trace: per persona, one
    view per step, every day's plan as generated, every activity_logs row and
    the engines' end state. Plain JSON types only."""
    plans = []
    original_generate = DailyPlanner.generate_daily_plan

    def recording_generate(self, *args, **kwargs):
        plan = original_generate(self, *args, **kwargs)
        plans.append((id(self), plan.date,
                      [(s.hour, s.activity_name, s.reason, s.location) for s in plan.slots]))
        return plan

    monkeypatch.setattr(DailyPlanner, "generate_daily_plan", recording_generate)
    trace = run_days(_trace_personas(), days=TRACE_DAYS, seed=TRACE_SEED, cadence=PRODUCTION,
                     start=TRACE_START, data_dir=data_dir)
    assert trace.errors == []

    personas = {}
    for pid, records in trace.records.items():
        svc = trace.services[pid]
        planner_id = id(svc._daily_planner)
        personas[pid] = {
            "steps": [_step_view(record) for record in records],
            "plans": [[date, slots] for owner, date, slots in plans if owner == planner_id],
            "activity_logs": _activity_rows(svc._db_path),
            "end_state": json.loads(_canonical(_end_state(svc))),
        }
    return personas


def fingerprint(personas: dict) -> dict:
    """The fixture's form of a trace: a digest per step (so a failure names
    the first step that moved) and one per remaining section."""
    return {
        pid: {
            "steps": [_digest(step) for step in trace["steps"]],
            "plans": _digest(trace["plans"]),
            "activity_logs": _digest(trace["activity_logs"]),
            "end_state": _digest(trace["end_state"]),
            "counts": {"steps": len(trace["steps"]), "plans": len(trace["plans"]),
                       "activity_logs": len(trace["activity_logs"])},
        }
        for pid, trace in personas.items()
    }


def _recorded(path: pathlib.Path, record: dict) -> dict:
    """Load a recorded fixture -- or fail loudly if it is missing.

    A MISSING FIXTURE IS A DEFECT, NOT A FRESH START: regenerating it from
    whatever the code does now would bless any change the move made.
    Recording is opt-in only: delete the file and re-run with
    SETTING_TRACE_WRITE=1 (the exact value "1"); ``record`` is written then."""
    if not path.exists():
        if os.environ.get(TRACE_WRITE_ENV) != "1":
            raise AssertionError(
                f"Recorded fixture is missing: {path}\n"
                "It is committed and should always be present; restore it from git.\n"
                f"To record it deliberately, re-run with {TRACE_WRITE_ENV}=1."
            )
        path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return json.loads(path.read_text())


def _trace_fixture(got: dict) -> dict:
    return _recorded(TRACE_FIXTURE, {
        "recorded_from": "the code before Task 9 moved the catalogues (5de90c9); re-recorded when "
                         "ruling T9-R4 fixed three lines' verb agreement (only plain's end_state moved); "
                         "re-recorded by Task 10: hunger per world hour, no hunger drain asleep, only "
                         "meals feed her (rulings T4-R4, T9-R8); the day's anchors are activities and "
                         "a planned slot governs its whole hour; activity choice and free hours by utility; "
                         "goals and daily intentions her own; wants her own and her setting's; no "
                         "intimacy in a shift or her sleep window; she stays where her plan puts her "
                         "for the hour; re-recorded by Task 11: a friend's contact eases her loneliness; "
                         "re-recorded when ruling T12-R4 fixed two chaos lines' verb agreement (no step moved); "
                         "re-recorded by Task 14: activities have outcomes (success, mixed, fail) and are felt as "
                         "she appraises them; re-recorded by Task 14's fix round: each day has a quality of its "
                         "own (ruling T14-R1); re-recorded by Task 15: her stress is what her stressors weigh "
                         "while they last; re-recorded by Task 15's completion: a record made without a time "
                         "is stamped with the simulated instant, not the host's date; re-recorded by Task 29: "
                         "her money on the world clock (a starting runway clear of money worries, purchases "
                         "per world hour from her surplus, an activity paid for once in its hour); "
                         "re-recorded by Task 31: 0.5.0's dated habits replace the undated habit term in her "
                         "picks and plans; re-recorded after Task 40: the same event is looked forward to "
                         "once, so a goal due soon weighs on her mood once and not at every tick (the nurse "
                         "from step 24; diagnosed first: memory_time_system.py alone put back replays the "
                         "older recording)",
        "seed": TRACE_SEED, "days": TRACE_DAYS, "cadence": PRODUCTION,
        "start": TRACE_START.isoformat(),
        "personas": got,
    })


def test_the_default_setting_replays_the_trace_recorded_before_the_move(tmp_path, monkeypatch):
    """Same seed, production cadence, two days, a plain persona and a
    well-furnished one: every step, every plan, every activity_logs row and
    the end state are what the pre-move code produced."""
    got = fingerprint(record_default_setting_trace(tmp_path, monkeypatch))
    recorded = _trace_fixture(got)
    assert (recorded["seed"], recorded["days"], recorded["cadence"]) == (TRACE_SEED, TRACE_DAYS, PRODUCTION)
    assert sorted(got) == sorted(recorded["personas"])
    for pid, expected in recorded["personas"].items():
        steps = got[pid]["steps"]
        assert len(steps) == len(expected["steps"]), pid
        for index, (want, have) in enumerate(zip(expected["steps"], steps)):
            assert have == want, f"{pid}: step {index} is the first that differs from the recording"
        for section in ("plans", "activity_logs", "end_state", "counts"):
            assert got[pid][section] == expected[section], f"{pid}: {section} differs from the recording"


def test_a_record_made_without_a_time_reads_the_clock_the_run_reads(monkeypatch):
    """The trace is the same whatever the host's date (sim_helpers points
    every aura_life module's ``datetime`` at the simulated instant): a model
    whose time defaults to "now" -- a goal's or a want's ``created_at``, a
    social event's ``timestamp`` -- reads ``aura_life.models``' ``datetime``
    when it is made. ``default_factory=datetime.now`` bound the host's clock
    at import, and the recording made on 2026-09-27 stopped replaying once
    the host's date passed the simulated one (2026-11-13: the nurse's step 15
    and the plain persona's step 63, on the code before Task 15 too)."""
    import dataclasses

    from aura_life import models

    instant = datetime(2031, 3, 10, 9, 0)

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    stamped = {}
    for name, cls in vars(models).items():
        if isinstance(cls, type) and dataclasses.is_dataclass(cls) and cls.__module__ == models.__name__:
            for f in dataclasses.fields(cls):
                if f.default_factory is not dataclasses.MISSING and isinstance(f.default_factory(), datetime):
                    stamped[f"{name}.{f.name}"] = f.default_factory
    assert {"Goal.created_at", "ShortTermDesire.created_at", "SocialEvent.timestamp"} <= set(stamped)
    monkeypatch.setattr(models, "datetime", _Clock)
    assert {field: factory() for field, factory in stamped.items()} == {field: instant for field in stamped}


# ======================================================================
# 2. Every moved catalogue is byte-identical to what it was before the move
# ======================================================================

def canon(obj):
    """A JSON-able form that keeps what ``json.dumps`` would lose or blur:
    dict order (``ChaosEngine._match_emotions`` returns the first key that
    matches), tuples as tuples, and enum members as members."""
    if isinstance(obj, Enum):
        return {"enum": f"{type(obj).__name__}.{obj.name}"}
    if isinstance(obj, dict):
        return {"dict": [[canon(key), canon(value)] for key, value in obj.items()]}
    if isinstance(obj, tuple):
        return {"tuple": [canon(value) for value in obj]}
    if isinstance(obj, list):
        return [canon(value) for value in obj]
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    raise TypeError(f"no canonical form for {type(obj).__name__}: {obj!r}")


def catalogue_digests(views: dict) -> dict:
    return {
        name: hashlib.sha256(
            json.dumps(canon(view), ensure_ascii=True, separators=(",", ":")).encode("ascii")
        ).hexdigest()[:16]
        for name, view in views.items()
    }


#: ``Activity``'s fields as they were at 5de90c9. Task 9 adds
#: ``persona_ids``, empty on every contemporary activity (asserted apart).
ACTIVITY_FIELDS = (
    "name", "category", "energy_cost", "min_energy", "duration_minutes", "preferred_times",
    "preferred_weather", "suitable_locations", "narrative_templates", "thought_possibilities",
    "emotion_effects", "can_be_interrupted", "share_worthy", "preferred_seasons",
)
#: The keys of the per-activity catch-up narratives that were a dict literal
#: inside ``LifeService._get_catchup_narrative``, in source order.
CATCH_UP_ACTIVITY_KEYS = ("reading", "cooking a meal", "relaxing", "going for a run", "yoga", "journaling")
#: The keys of the follow-up wants that were a dict literal inside
#: ``DailyPlanner.generate_desire_from_activity``, in source order.
WANT_FOLLOW_UP_KEYS = ("reading", "writing poetry", "listening to music", "learning something new", "stargazing")
HOLIDAY_YEARS = tuple(range(2024, 2031))
#: No nationality, and one the holiday table does not know.
HOLIDAY_EXTRA_NATIONALITIES = ("", "martian")


#: ``IntimateActivity``'s and ``CherishedObject``'s fields at 80d3240.
INTIMATE_FIELDS = (
    "name", "description", "min_arousal", "arousal_change", "satisfaction_gain", "energy_cost",
    "duration_minutes", "narrative_templates", "thought_possibilities", "emotion_effects",
    "preferred_locations", "preferred_times", "is_release", "share_worthy", "shyness_to_share",
)
CHERISHED_FIELDS = ("name", "description", "emotional_value", "associated_memory", "location")


def _activity_view(activity) -> dict:
    return {name: getattr(activity, name) for name in ACTIVITY_FIELDS}


def _fields_view(obj, names) -> dict:
    return {name: getattr(obj, name) for name in names}


def _want_view(desire) -> tuple:
    return (desire.title, desire.description, desire.source, list(desire.related_activities), desire.urgency)


def _stub_rng():
    """Draws that open every gate: ``random()`` 0.0, the first of a choice,
    the low end of a randint."""
    return SimpleNamespace(random=lambda: 0.0, choice=lambda seq: list(seq)[0], randint=lambda low, high: low)


def legacy_catalogue_views(tmp_path) -> dict:
    """Every catalogue Task 9 moves, read where the code before the move read
    it: the old module-level names (legacy re-exports once the move is done)
    and, for the three that were literals inside a method -- the activity
    weather suffixes, the per-activity catch-up narratives, the follow-up
    wants -- that method, driven with a stub rng and no rendering."""
    from aura_life import life_service
    from aura_life.activities import activity_engine
    from aura_life.affect import affect_system
    from aura_life.chaos import chaos_engine
    from aura_life.cognitive import cognitive_system
    from aura_life.goals import goal_engine
    from aura_life.intimacy import desire_system
    from aura_life.job import career_system
    from aura_life.life_events import life_event_system
    from aura_life.memory_time import memory_time_system
    from aura_life.planner import daily_planner
    from aura_life.social import social_system
    from aura_life.world import environment

    engine = activity_engine.ActivityEngine(rng=_stub_rng())
    svc = life_service.LifeService(db_path=str(tmp_path / "legacy.db"), persona_id="legacy")
    svc._service_rng = _stub_rng()
    svc._render_text = lambda text, **extra: text

    def follow_up(activity_name):
        return _want_view(DailyPlanner(rng=_stub_rng()).generate_desire_from_activity(activity_name))

    nationalities = list(daily_planner.NATIONALITY_TO_COUNTRY) + list(HOLIDAY_EXTRA_NATIONALITIES)
    return {
        "activities": [_activity_view(a) for a in activity_engine.ACTIVITIES],
        "weather_flavors": {w.value: engine._get_weather_flavor(w, None) for w in Weather},
        "places": dict(life_service.LifeService._DEFAULT_LOCATIONS),
        "place_descriptions": environment.LOCATION_DESCRIPTIONS,
        "npc_event_templates.friend": social_system.EVENT_TEMPLATES,
        "text_topics": social_system.TEXT_TOPICS,
        "invite_activities": social_system.INVITE_ACTIVITIES,
        "activity_chaos": chaos_engine.ACTIVITY_CHAOS,
        "universal_chaos": chaos_engine.UNIVERSAL_CHAOS,
        "universal_chaos_effects": chaos_engine.UNIVERSAL_CHAOS_EFFECTS,
        "serendipity": chaos_engine.SERENDIPITY,
        "chaos_emotions": chaos_engine.CHAOS_EMOTIONS,
        "micro_events": life_service.MICRO_EVENTS,
        "skill_mappings": life_service.SKILL_MAPPINGS,
        "skill_milestones": life_service.SKILL_MILESTONES,
        "dream_templates": life_service.DREAM_TEMPLATES,
        "catch_up.sleep": life_service.CATCHUP_SLEEP_NARRATIVE,
        "catch_up.morning_routine": life_service.CATCHUP_MORNING_ROUTINE_NARRATIVES,
        "catch_up.morning_activity": life_service.CATCHUP_MORNING_ACTIVITY_NARRATIVES,
        "catch_up.midday": life_service.CATCHUP_MIDDAY_NARRATIVES,
        "catch_up.afternoon": life_service.CATCHUP_AFTERNOON_NARRATIVES,
        "catch_up.evening": life_service.CATCHUP_EVENING_NARRATIVES,
        "catch_up.late": life_service.CATCHUP_LATE_NARRATIVE,
        "catch_up.by_activity": {key: svc._get_catchup_narrative(key, 9) for key in CATCH_UP_ACTIVITY_KEYS},
        "catch_up.gap_week": life_service.GAP_NARRATIVE_WEEK,
        "catch_up.gap_days": life_service.GAP_NARRATIVE_DAYS,
        "catch_up.gap_short": life_service.GAP_NARRATIVE_SHORT,
        "wants": daily_planner.DESIRE_TEMPLATES,
        "want_follow_ups": {key: follow_up(key) for key in WANT_FOLLOW_UP_KEYS},
        "holidays.nationalities": daily_planner.NATIONALITY_TO_COUNTRY,
        "holidays": {n: {y: daily_planner.get_holidays(n, y) for y in HOLIDAY_YEARS} for n in nationalities},
        "personality_goals": goal_engine.PERSONALITY_GOALS,
        "long_term_goals": goal_engine.LONG_TERM_GOALS,
        "dream_goals": goal_engine.DREAM_GOALS,
        "daily_intentions": goal_engine.DAILY_INTENTIONS,
        "nostalgia_fragments": memory_time_system.NOSTALGIA_MEMORIES,
        "nostalgia_triggers": memory_time_system.NOSTALGIA_ACTIVITIES,
        # Moved by Task 9's fix round (rulings T9-R2 and T9-R5).
        "intimate_activities": [_fields_view(a, INTIMATE_FIELDS) for a in desire_system.INTIMATE_ACTIVITIES],
        "occupation_places": daily_planner.OCCUPATION_LOCATIONS,
        "interest_places": daily_planner.INTEREST_LOCATIONS,
        "dream_fragment_templates": cognitive_system.DREAM_TEMPLATES,
        "work_events_positive": career_system.POSITIVE_EVENTS,
        "work_events_negative": career_system.NEGATIVE_EVENTS,
        "work_event_emotions": affect_system.WORK_EVENT_EMOTIONS,
        "weather_descriptions": environment.WEATHER_DESCRIPTIONS,
        "cherished_objects": [_fields_view(o, CHERISHED_FIELDS) for o in environment.CHERISHED_OBJECTS],
        "life_event_templates": life_event_system.LIFE_EVENT_TEMPLATES,
    }


def _catalogue_fixture(got: dict) -> dict:
    """The recorded digests: the first 37 as ``legacy_catalogue_views`` gave
    them at 5de90c9 (they were hard-coded in this module until ruling T9-R3,
    and are the same values), the fix round's ten at 80d3240 -- each before
    its catalogue moved -- then re-recorded when ruling T9-R4 fixed three
    lines' verb agreement, when Task 10 added the day's anchors to the
    contemporary activities, and when ruling T12-R4 fixed two chaos lines'
    verb agreement (see the module docstring)."""
    return _recorded(CATALOGUE_FIXTURE, {
        "recorded_from": "legacy_catalogue_views before each catalogue moved (5de90c9, 80d3240); "
                         "re-recorded when ruling T9-R4 fixed three lines' verb agreement "
                         "(nostalgia_fragments, npc_event_templates.friend, serendipity moved); "
                         "re-recorded when Task 10 added the day's anchors to the activities "
                         "(activities moved); re-recorded when ruling T12-R4 fixed two chaos lines' "
                         "verb agreement (activity_chaos, universal_chaos moved)",
        "digests": got,
    })["digests"]


def test_the_old_import_paths_still_give_every_catalogue_as_it_was(tmp_path):
    """Hosts and tests that import a catalogue from its old module keep
    working (legacy re-exports), and every entry is byte-identical to what it
    was before it moved."""
    got = catalogue_digests(legacy_catalogue_views(tmp_path))
    assert got == _catalogue_fixture(got)


def setting_catalogue_views(spec) -> dict:
    """The same views as :func:`legacy_catalogue_views`, read from a
    :class:`~aura_life.settings.SettingSpec` -- what the engines read now."""
    from aura_life.settings import contemporary

    nationalities = list(contemporary.NATIONALITY_TO_COUNTRY) + list(HOLIDAY_EXTRA_NATIONALITIES)
    catch_up = spec.catch_up
    return {
        "activities": [_activity_view(a) for a in spec.activities],
        "weather_flavors": {w.value: spec.weather_flavors.get(w, "") for w in Weather},
        "places": spec.places,
        "place_descriptions": spec.place_descriptions,
        "npc_event_templates.friend": spec.npc_event_templates["friend"],
        "text_topics": spec.text_topics,
        "invite_activities": spec.invite_activities,
        "activity_chaos": spec.activity_chaos,
        "universal_chaos": spec.universal_chaos,
        "universal_chaos_effects": spec.universal_chaos_effects,
        "serendipity": spec.serendipity,
        "chaos_emotions": spec.chaos_emotions,
        "micro_events": spec.micro_events,
        "skill_mappings": spec.skill_mappings,
        "skill_milestones": spec.skill_milestones,
        "dream_templates": spec.dream_templates,
        "catch_up.sleep": catch_up.sleep,
        "catch_up.morning_routine": catch_up.morning_routine,
        "catch_up.morning_activity": catch_up.morning_activity,
        "catch_up.midday": catch_up.midday,
        "catch_up.afternoon": catch_up.afternoon,
        "catch_up.evening": catch_up.evening,
        "catch_up.late": catch_up.late,
        "catch_up.by_activity": catch_up.by_activity,
        "catch_up.gap_week": catch_up.gap_week,
        "catch_up.gap_days": catch_up.gap_days,
        "catch_up.gap_short": catch_up.gap_short,
        "wants": spec.wants,
        "want_follow_ups": {
            key: (want["title"], want["description"], want["source"], list(want["related_activities"]),
                  want["urgency"])
            for key, want in spec.want_follow_ups.items()
        },
        "holidays.nationalities": contemporary.NATIONALITY_TO_COUNTRY,
        "holidays": {n: {y: spec.holidays(n, y) for y in HOLIDAY_YEARS} for n in nationalities},
        "personality_goals": spec.personality_goals,
        "long_term_goals": spec.long_term_goals,
        "dream_goals": spec.dream_goals,
        "daily_intentions": spec.daily_intentions,
        "nostalgia_fragments": spec.nostalgia_fragments,
        "nostalgia_triggers": spec.nostalgia_triggers,
        "intimate_activities": [_fields_view(a, INTIMATE_FIELDS) for a in spec.intimate_catalogue()],
        "occupation_places": spec.occupation_places,
        "interest_places": spec.interest_places,
        "dream_fragment_templates": spec.dream_fragment_templates,
        "work_events_positive": spec.work_events_positive,
        "work_events_negative": spec.work_events_negative,
        "work_event_emotions": spec.work_event_emotions,
        "weather_descriptions": spec.weather_descriptions,
        "cherished_objects": [_fields_view(o, CHERISHED_FIELDS) for o in spec.cherished_objects],
        "life_event_templates": spec.life_event_templates,
    }


def test_the_contemporary_pack_is_every_catalogue_as_it_was():
    """The registered default pack -- what every engine reads for a persona
    with no setting -- holds today's catalogues byte for byte, in order."""
    spec = get_setting(DEFAULT_SETTING)
    assert spec.key == "contemporary"
    got = catalogue_digests(setting_catalogue_views(spec))
    assert got == _catalogue_fixture(got)
    # The one field Task 9 adds to an activity restricts no contemporary one.
    assert all(a.persona_ids == [] for a in spec.activities)
    # Today's NPC events are every welcome kind's; Task 11 gave the two
    # unwelcome kinds lines of their own (new text, so not pinned above).
    assert list(spec.npc_event_templates) == ["friend", "estranged", "threat"]


# ======================================================================
# 3. The registry
# ======================================================================

@pytest.fixture
def registered():
    """Register specs for one test; every key it registered is unregistered
    afterwards, pass or fail, so no test leaks a setting into another."""
    keys = []

    def _register(spec, **kwargs):
        register_setting(spec, **kwargs)
        keys.append(spec.key)
        return get_setting(spec.key)

    yield _register
    for key in keys:
        unregister_setting(key)


def _activity(name, locations=("home",), persona_ids=None, **overrides) -> Activity:
    """A plain, always-possible activity (every time of day and weather, no
    energy floor) at `locations`."""
    fields = dict(
        name=name,
        category=ActivityCategory.EXPLORATION,
        energy_cost=0.05,
        min_energy=0.0,
        duration_minutes=20,
        preferred_times=list(TimeOfDay),
        preferred_weather=list(Weather),
        suitable_locations=list(locations),
        narrative_templates=[f"{{Subj}} spent a while {name}"],
        thought_possibilities=["Good."],
        emotion_effects={"content": 0.1},
    )
    fields.update(overrides)
    if persona_ids is not None:
        fields["persona_ids"] = list(persona_ids)
    return Activity(**fields)


def test_the_default_setting_is_contemporary_and_empty_means_it():
    assert DEFAULT_SETTING == "contemporary"
    default = get_setting(DEFAULT_SETTING)
    assert get_setting() is default
    assert get_setting(None) is default
    assert get_setting("") is default
    assert get_setting("  ") is default


def test_register_setting_refuses_a_duplicate_key_without_replace(registered):
    registered(SettingSpec(key="test-dup", text_topics=["first"]))
    with pytest.raises(ValueError, match="test-dup"):
        register_setting(SettingSpec(key="test-dup", text_topics=["second"]))
    assert get_setting("test-dup").text_topics == ["first"]

    register_setting(SettingSpec(key="test-dup", text_topics=["second"]), replace=True)
    assert get_setting("test-dup").text_topics == ["second"]


def test_the_shipped_default_is_refused_like_any_other_duplicate():
    before = get_setting(DEFAULT_SETTING)
    with pytest.raises(ValueError, match="contemporary"):
        register_setting(SettingSpec(key=DEFAULT_SETTING))
    assert get_setting(DEFAULT_SETTING) is before


def test_unregister_setting_returns_false_for_an_unknown_key():
    assert unregister_setting("no-such-setting") is False


def test_unregister_setting_forgets_a_registered_key(registered):
    registered(SettingSpec(key="test-gone"))
    assert unregister_setting("test-gone") is True
    with pytest.raises(ValueError, match="test-gone"):
        get_setting("test-gone")
    assert unregister_setting("test-gone") is False


def test_the_default_setting_cannot_be_unregistered():
    """Every persona with no setting reads it: removing it would make every
    default LifeService fail to construct."""
    with pytest.raises(ValueError, match="contemporary"):
        unregister_setting(DEFAULT_SETTING)
    assert get_setting(DEFAULT_SETTING).key == DEFAULT_SETTING


def test_get_setting_names_the_unknown_key_and_every_registered_one(registered):
    registered(SettingSpec(key="test-known"))
    with pytest.raises(ValueError) as err:
        get_setting("dustlands-1999")
    message = str(err.value)
    assert "'dustlands-1999'" in message
    assert "contemporary" in message and "test-known" in message


def test_an_unknown_setting_raises_at_life_service_construction(tmp_path):
    """Before the service touches the disk: the database of a persona whose
    setting does not exist is never created."""
    db_path = tmp_path / "life.db"
    with pytest.raises(ValueError) as err:
        LifeService(db_path=str(db_path), persona_id="lost",
                    definition=PersonalityDefinition(setting="nowhere-2077"))
    message = str(err.value)
    assert "'nowhere-2077'" in message and "contemporary" in message
    assert not db_path.exists()


def test_a_persona_with_no_setting_lives_in_the_default_one(tmp_path):
    for definition in (None, PersonalityDefinition(), PersonalityDefinition(setting="")):
        svc = LifeService(db_path=str(tmp_path / "default.db"), persona_id="plain", definition=definition)
        assert svc._setting is get_setting(DEFAULT_SETTING)


def test_a_registered_setting_is_a_copy_the_caller_cannot_change_afterwards(registered):
    activity = _activity("whittling")
    spec = SettingSpec(key="test-copy", activities=[activity], text_topics=["knives"])
    registered(spec)
    spec.text_topics.append("forks")
    activity.narrative_templates.append("{Subj} cut a finger")
    stored = get_setting("test-copy")
    assert stored.text_topics == ["knives"]
    assert stored.activities[0].narrative_templates == ["{Subj} spent a while whittling"]


@pytest.mark.parametrize("bad, why", [
    (dict(key=""), "key"),
    (dict(key="test-bad", activities=[_activity("a"), _activity("a")]), "'a'"),
    (dict(key="test-bad", activities=["reading"]), "activities"),
    (dict(key="test-bad", npc_event_templates={"stranger": {"call": ["{name} called"]}}), "stranger"),
    (dict(key="test-bad", text_topics="the weather"), "text_topics"),
    (dict(key="test-bad", places=["home"]), "places"),
    (dict(key="test-bad", holidays={(12, 25): "Christmas Day"}), "holidays"),
    (dict(key="test-bad", catch_up={"sleep": "{Subj} slept"}), "catch_up"),
    # Entries the engines index directly.
    (dict(key="test-bad", daily_intentions=[{"title": "Stay alive today"}]), r"daily_intentions\[0\].*'motivation'"),
    (dict(key="test-bad", dream_goals=[{"description": "Somewhere dry"}]), r"dream_goals\[0\].*'title'"),
    (dict(key="test-bad", wants=[{"description": "Soon"}]), r"wants\[0\].*'title'"),
    (dict(key="test-bad", micro_events=[{"emotion": {"startled": 0.1}}]), r"micro_events\[0\].*'text'"),
    (dict(key="test-bad", universal_chaos_effects=[{"effect": None}]), r"universal_chaos_effects\[0\].*'text'"),
    (dict(key="test-bad", want_follow_ups={"diving": {"urgency": 0.5}}), r"want_follow_ups\['diving'\].*'title'"),
])
def test_register_setting_refuses_a_spec_the_engines_would_trip_on(bad, why):
    try:
        with pytest.raises(ValueError, match=why):
            register_setting(SettingSpec(**bad))
        assert "test-bad" not in _registered_keys()
    finally:
        unregister_setting("test-bad")  # never leak a wrongly accepted spec into the next case


@pytest.mark.parametrize("bad, why", [
    # An activity's narration is drawn from it (ActivityEngine.execute_activity).
    (dict(activities=[_activity("a", narrative_templates=[])]), r"activity 'a': narrative_templates"),
    (dict(activities=[_activity("a", narrative_templates="{Subj} did it")]), r"activity 'a': narrative_templates"),
    # Strings where lists belong: each would be read one character at a time.
    (dict(activities=[_activity("a", suitable_locations="garage")]), r"activity 'a': suitable_locations"),
    (dict(activities=[_activity("a", thought_possibilities="Good.")]), r"activity 'a': thought_possibilities"),
    (dict(activity_chaos={"a": "the car would not start"}), r"activity_chaos\['a'\]"),
    (dict(life_event_templates={"discovery": "Found {context}"}), r"life_event_templates\['discovery'\]"),
    (dict(npc_event_templates={"friend": {"mentioned": "{name} was around"}}),
     r"npc_event_templates\['friend'\]\['mentioned'\]"),
    (dict(catch_up=CatchUpNarratives(midday="{Subj} ate")), r"catch_up\.midday"),
    (dict(wants=[{"title": "Rest", "related_activities": "sleeping"}]), r"wants\[0\]\['related_activities'\]"),
    (dict(personality_goals=[{"title": "Rest", "milestones": "Sleep"}]), r"personality_goals\[0\]\['milestones'\]"),
    (dict(want_follow_ups={"a": {"title": "More", "related_activities": "a"}}),
     r"want_follow_ups\['a'\]\['related_activities'\]"),
    # ... and where an emotion mapping belongs.
    (dict(chaos_emotions={"flat tyre": "annoyed"}), r"chaos_emotions\['flat tyre'\]"),
    (dict(work_event_emotions={"praised": "proud"}), r"work_event_emotions\['praised'\]"),
    (dict(micro_events=[{"text": "A dog barked", "emotion": "startled"}]), r"micro_events\[0\]\['emotion'\]"),
    (dict(universal_chaos_effects=[{"text": "A fuse blew", "effect": "shadow"}]),
     r"universal_chaos_effects\[0\]\['effect'\]"),
    # Entries the engines unpack as pairs.
    (dict(nostalgia_triggers={"a": "smell"}), r"nostalgia_triggers\['a'\]"),
    (dict(nostalgia_triggers={"a": ("smell", "often")}), r"nostalgia_triggers\['a'\]"),
    (dict(skill_mappings={"a": ("mechanics",)}), r"skill_mappings\['a'\]"),
    (dict(skill_milestones={"mechanics": [(0.2, "Knows a spanner"), 0.5]}), r"skill_milestones\['mechanics'\]"),
    (dict(skill_milestones={"mechanics": "Knows a spanner"}), r"skill_milestones\['mechanics'\]"),
    (dict(occupation_places={"mechanic": ["garage"]}), r"occupation_places\['mechanic'\]"),
    (dict(interest_places={"cars": [("garage", "workplace", "spare")]}), r"interest_places\['cars'\]"),
    # Enum members, not their values: a str never equals one, so it would
    # silently never match.
    (dict(weather_flavors={"rainy": "in the rain"}), r"weather_flavors .*'rainy'"),
    (dict(weather_descriptions={"rainy": "rain on the tin roof"}), r"weather_descriptions .*'rainy'"),
    (dict(activities=[_activity("a", preferred_weather=["rainy"])]), r"activity 'a': preferred_weather"),
    (dict(activities=[_activity("a", preferred_times=["morning"])]), r"activity 'a': preferred_times"),
])
def test_register_setting_refuses_a_shape_an_engine_would_trip_on_or_never_match(bad, why):
    """Review finding 9: every piece an engine draws from, unpacks or looks
    up must have the shape it reads."""
    try:
        with pytest.raises(ValueError, match=why):
            register_setting(SettingSpec(key="test-bad", **bad))
        assert "test-bad" not in _registered_keys()
    finally:
        unregister_setting("test-bad")


def test_the_shapes_the_shipped_pack_uses_are_all_accepted(registered):
    """The refusals above are exact: tuples where lists are read, pairs as
    tuples or lists, an activity with no thoughts, and every shape the
    contemporary pack holds all pass."""
    contemporary = get_setting(DEFAULT_SETTING)
    registered(SettingSpec(**{**vars(contemporary), "key": "test-contemporary-copy"}))
    registered(SettingSpec(
        key="test-shapes",
        activities=[_activity("a", narrative_templates=("{Subj} did it",), thought_possibilities=[])],
        nostalgia_triggers={"a": ["smell", 1]},
        skill_milestones={"mechanics": [[0.2, "Knows a spanner"]]},
        universal_chaos_effects=[{"text": "A fuse blew", "effect": None}],
    ))


def test_a_persona_restriction_must_be_a_list_of_ids():
    """A bare string would restrict the activity to single letters."""
    activity = _activity("diving")
    activity.persona_ids = "lina"
    with pytest.raises(ValueError, match="persona_ids"):
        register_setting(SettingSpec(key="test-bad", activities=[activity]))
    assert "test-bad" not in _registered_keys()


def test_register_setting_refuses_what_is_not_a_setting_spec():
    with pytest.raises(TypeError):
        register_setting({"key": "test-dict"})


def _registered_keys() -> set:
    keys = set()
    for key in ("test-bad", "test-dict"):
        try:
            get_setting(key)
            keys.add(key)
        except ValueError:
            pass
    return keys


# ======================================================================
# 4. Every engine reads the persona's setting
# ======================================================================

#: What the library adds to a setting whatever its pack holds (ruling T9-R6):
#: the universal sleep, nap and meal, for a setting with none of its own.
UNIVERSAL_NAMES = ("sleeping", "napping", "having a meal")
#: What a persona of a setting that leaves its intimate catalogue out may also
#: do (ruling T9-R2: the contemporary catalogue).
FALLBACK_INTIMATE_NAMES = frozenset(a.name for a in INTIMATE_ACTIVITIES)
#: The share of production-cadence steps on which the acceptance scenario's
#: persona must be less than hungry (``HUNGRY_THRESHOLD``, 0.7): "most".
MOSTLY = 0.5

#: The acceptance scenario's setting: three activities -- one of them rest,
#: the only kind she may choose when rest is forced -- and two places.
GARAGE = SettingSpec(
    key="test-garage",
    activities=[
        _activity("fixing the car", locations=("garage",)),
        _activity("cleaning a pistol", locations=("home", "garage")),
        _activity("sitting on the stairs", locations=("home",),
                  category=ActivityCategory.REST, energy_cost=-0.1),
    ],
    places={"home": "home", "garage": "workplace"},
    place_descriptions={"home": "a rented room above the garage", "garage": "the garage, oil on the floor"},
)


def _service(tmp_path, persona_id, setting_key, **kwargs) -> LifeService:
    return LifeService(db_path=str(tmp_path / f"{persona_id}.db"), persona_id=persona_id,
                       definition=PersonalityDefinition(setting=setting_key), **kwargs)


def test_a_persona_in_a_three_activity_two_place_setting_lives_only_there(registered, tmp_path):
    """The acceptance scenario, two production-cadence days: everything she
    does is one of her setting's three activities, a universal one (it has
    no sleep, nap or meal of its own, so it gets all three) or an intimate
    one (it leaves that catalogue out, so it keeps today's); she does all
    three of her own and eats; she is hungry on less than half the steps;
    she is only ever in one of its two places, which are all her location
    registry holds; and no engine errs on the catalogues the setting leaves
    empty (micro-events, chaos, NPC events, goals, wants, holidays,
    nostalgia, dreams)."""
    spec = registered(GARAGE)
    assert [a.name for a in spec.resolved_activities()] == (
        [a.name for a in GARAGE.activities] + list(UNIVERSAL_NAMES))
    trace = run_days(
        [SimPersona("tinker", service_kwargs=dict(definition=PersonalityDefinition(setting="test-garage")))],
        days=2, seed=5, cadence=PRODUCTION, data_dir=tmp_path,
    )
    svc = trace.services["tinker"]
    rows = _activity_rows(svc._db_path)
    names = {row["activity_name"] for row in rows}
    own = {activity.name for activity in GARAGE.activities}
    allowed = own | set(UNIVERSAL_NAMES) | FALLBACK_INTIMATE_NAMES

    assert trace.errors == []
    assert names <= allowed, sorted(names - allowed)
    assert own <= names, sorted(own - names)
    assert {"sleeping", "having a meal"} <= names
    steps = trace.records["tinker"]
    fed = sum(1 for step in steps if step.hunger < 0.7) / len(steps)
    print(f"steps with hunger < 0.7: {fed:.1%} of {len(steps)}")
    assert fed > MOSTLY, fed
    assert {row["location"] for row in rows} <= {"home", "garage"}
    assert set(svc._location_registry) == {"home", "garage"}


def test_the_same_persona_in_the_default_setting_does_todays_activities(tmp_path):
    """The control for the scenario above: with no setting she draws from
    today's catalogue, so the restriction really is the setting's."""
    trace = run_days([SimPersona("tinker")], days=2, seed=5, cadence=PRODUCTION, data_dir=tmp_path)
    names = {row["activity_name"] for row in _activity_rows(trace.services["tinker"]._db_path)}
    contemporary = {activity.name for activity in get_setting().activities}
    assert len(names & contemporary) >= 10
    assert not names & {activity.name for activity in GARAGE.activities}


def test_the_contemporary_pack_gets_no_universal_activity():
    """It tags its own sleeping, napping and meals (ruling T9-R6), so its
    catalogue is exactly its own and every persona's day is today's. Its
    three meal slots became meal-tagged activities in Task 10."""
    spec = get_setting(DEFAULT_SETTING)
    assert [a.name for a in spec.resolved_activities()] == [a.name for a in spec.activities]
    assert spec.names_tagged("sleep") == {"sleeping"}
    assert spec.names_tagged("nap") == {"napping"}
    assert spec.names_tagged("meal") == {"cooking a meal", "baking something", "trying a new recipe",
                                         "lunch with coworkers", "having breakfast", "having lunch",
                                         "having dinner"}


def test_only_the_contemporary_meals_feed_her():
    """The meal-tagged contemporary activities are the ones whose names carry
    a ``SustenanceSystem.EAT_ACTIVITIES`` keyword -- all but "creating a
    playlist", which carried one by accident ("cr-eat-ing") and fed her a
    snack until Task 10 made the tag the only thing that feeds her (ruling
    T9-R8)."""
    from aura_life.sustenance.sustenance_system import EAT_ACTIVITIES, SustenanceSystem

    fed_by_name = {a.name for a in get_setting().activities
                   if any(k in a.name.lower().replace(" ", "_") for k in EAT_ACTIVITIES)}
    assert fed_by_name - get_setting().names_tagged("meal") == {"creating a playlist"}
    assert get_setting().names_tagged("meal") <= fed_by_name
    sustenance = SustenanceSystem()
    sustenance.state.hunger = 0.8
    sustenance.on_activity("creating a playlist", now=datetime(2026, 10, 6, 12, 0))
    assert sustenance.hunger == 0.8


OWN_SLEEP_NAP_MEAL = SettingSpec(
    key="test-own-basics",
    activities=[
        _activity("playing cards"),
        _activity("crashing on the mattress", category=ActivityCategory.REST, tags=frozenset({"sleep"})),
        _activity("dozing in the car", category=ActivityCategory.REST, energy_cost=-0.25,
                  tags=frozenset({"nap"})),
        _activity("chop-shop eggs", tags=frozenset({"meal"})),
    ],
    places={"home": "home"},
)


def test_a_pack_with_its_own_sleep_nap_and_meal_gets_no_universal_one(registered):
    spec = registered(OWN_SLEEP_NAP_MEAL)
    assert [a.name for a in spec.resolved_activities()] == [a.name for a in OWN_SLEEP_NAP_MEAL.activities]
    only_a_meal = registered(SettingSpec(key="test-own-meal", activities=[
        _activity("chop-shop eggs", tags=frozenset({"meal"}))]))
    assert [a.name for a in only_a_meal.resolved_activities()] == ["chop-shop eggs", "sleeping", "napping"]


def test_a_meal_feeds_her_whatever_it_is_called(registered, tmp_path):
    """A pack's meal needs no keyword in its name: the "meal" tag feeds her
    like a real meal, and an untagged activity with no keyword does not."""
    from aura_life.sustenance.sustenance_system import MEAL_HUNGER_REDUCTION, SustenanceSystem

    sustenance = SustenanceSystem()
    sustenance.state.hunger = 0.8
    sustenance.on_activity("chop-shop eggs")
    assert sustenance.hunger == 0.8
    sustenance.on_activity("chop-shop eggs", meal=True)
    assert sustenance.hunger == pytest.approx(0.8 - MEAL_HUNGER_REDUCTION)

    from aura_life.world import WorldEnvironment

    registered(OWN_SLEEP_NAP_MEAL)
    svc = _service(tmp_path, "eater", "test-own-basics",
                   world_environment=WorldEnvironment(now=lambda: datetime(2026, 10, 6, 12, 0)))
    svc._sustenance.state.hunger = 0.8
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._activity_engine.select_activity = lambda **kwargs: svc._activity_engine.get_activity("chop-shop eggs")
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name == "chop-shop eggs"
    assert svc._sustenance.hunger == pytest.approx(0.8 - MEAL_HUNGER_REDUCTION)


def test_her_own_sleep_is_never_chosen_or_planned_and_names_her_nights(registered, tmp_path):
    """A pack's sleep activity is what the sleep state logs, and neither it
    nor her nap is ever an ordinary choice (the nap only when she may nap)
    or a planned slot."""
    registered(OWN_SLEEP_NAP_MEAL)
    svc = _service(tmp_path, "sleeper", "test-own-basics")
    svc._on_fell_asleep()
    assert svc._recent_activities[0].activity_name == "crashing on the mattress"

    excluded = []
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._energy.is_asleep = lambda: False
    svc._energy.update_sleep = lambda *args, **kwargs: None
    svc._energy.can_nap = lambda *args, **kwargs: False
    svc._activity_engine.select_activity = lambda **kwargs: excluded.append(set(kwargs["exclude"]))
    svc._on_activity_tick()
    assert excluded == [{"crashing on the mattress", "dozing in the car"}]

    planner = DailyPlanner(rng=random.Random(2), setting=get_setting("test-own-basics"))
    catalogue = get_setting("test-own-basics").resolved_activities()
    picks = {planner._select_activity_for_slot(list(TimeOfDay), [], [], {a.name: a for a in catalogue},
                                               [], Weather.SUNNY, [])[0] for _ in range(40)}
    # Nor is her meal a free hour's pick: it fills her meal slots, which makes
    # it one of the day's anchors (Task 10 fix round, finding 2).
    assert picks == {"playing cards"}


@pytest.mark.parametrize("activities, why", [
    ([_activity("napping")], "'napping' lacks the 'nap' tag"),
    ([_activity("chop-shop eggs", tags=frozenset({"meal"}), persona_ids=["lina"])], "restricted"),
    ([_activity("chop-shop eggs", tags=frozenset({"snack"}))], "unknown tags"),
    ([_activity("chop-shop eggs", tags="meal")], "tags must be a frozenset"),
])
def test_register_setting_refuses_tags_the_universal_rule_would_trip_on(activities, why):
    try:
        with pytest.raises(ValueError, match=why):
            register_setting(SettingSpec(key="test-bad", activities=activities))
    finally:
        unregister_setting("test-bad")


RESTRICTED = SettingSpec(
    key="test-restricted",
    activities=[
        _activity("diving the dead net", persona_ids=["lina"]),
        _activity("watching the road"),
        _activity("playing cards"),
    ],
    places={"home": "home"},
)


def test_an_activity_restricted_to_persona_ids_is_open_only_to_them(registered, tmp_path):
    spec = registered(RESTRICTED)
    universal = list(UNIVERSAL_NAMES)  # the setting has no sleep, nap or meal of its own
    assert [a.name for a in spec.activities_for("lina")] == [
        "diving the dead net", "watching the road", "playing cards"] + universal
    assert [a.name for a in spec.activities_for("LINA")] == [a.name for a in spec.activities_for("lina")]
    assert [a.name for a in spec.activities_for("roberta")] == ["watching the road", "playing cards"] + universal
    assert [a.name for a in spec.activities_for(None)] == ["watching the road", "playing cards"] + universal

    lina = _service(tmp_path, "lina", "test-restricted")
    roberta = _service(tmp_path, "roberta", "test-restricted")
    assert lina._activity_engine.get_activity("diving the dead net") is not None
    assert roberta._activity_engine.get_activity("diving the dead net") is None
    assert "diving the dead net" not in {a.name for a in roberta._activity_engine.get_all_activities()}


def test_over_a_day_only_the_named_persona_does_a_restricted_activity(registered, tmp_path):
    registered(RESTRICTED)
    personas = [SimPersona(pid, service_kwargs=dict(definition=PersonalityDefinition(setting="test-restricted")))
                for pid in ("lina", "roberta")]
    trace = run_days(personas, days=1, seed=8, cadence=PRODUCTION, data_dir=tmp_path)
    done = {pid: {row["activity_name"] for row in _activity_rows(svc._db_path)}
            for pid, svc in trace.services.items()}
    assert trace.errors == []
    assert "diving the dead net" in done["lina"]
    assert "diving the dead net" not in done["roberta"]
    assert {"watching the road", "playing cards"} <= done["roberta"]


def test_every_engine_life_service_builds_or_rebuilds_reads_her_setting(registered, tmp_path):
    """Construction, a reload from her saved rows (the ``from_dict`` paths)
    and ``reset_state()`` all hand each engine her setting."""
    spec = registered(GARAGE)
    svc = _service(tmp_path, "wired", "test-garage")

    def settings_read(s):
        return {
            "chaos": s._chaos._setting, "social": s._social._setting, "planner": s._daily_planner._setting,
            "goals": s._goal_engine._setting, "memory_time": s._memory_time._setting,
        }

    def activities(s):
        return [a.name for a in s._activity_engine.get_all_activities()]

    assert svc._setting is spec
    assert all(read is spec for read in settings_read(svc).values()), settings_read(svc)
    assert activities(svc) == [a.name for a in GARAGE.activities] + list(UNIVERSAL_NAMES)

    svc._save_state()
    svc._load_state()
    assert all(read is spec for read in settings_read(svc).values()), settings_read(svc)

    svc.reset_state()
    assert all(read is spec for read in settings_read(svc).values()), settings_read(svc)
    assert activities(svc) == [a.name for a in GARAGE.activities] + list(UNIVERSAL_NAMES)


def _stub_draws(**overrides):
    draws = dict(random=lambda: 0.0, choice=lambda seq: list(seq)[0], randint=lambda low, high: low,
                 uniform=lambda low, high: low, sample=lambda seq, k: list(seq)[:k],
                 choices=lambda seq, weights=None, k=1: list(seq)[:k], shuffle=lambda seq: None)
    draws.update(overrides)
    return SimpleNamespace(**draws)


def test_the_activity_engine_narrates_with_its_settings_weather(registered):
    spec = registered(SettingSpec(
        key="test-weather",
        activities=[_activity("watching the road")],
        weather_flavors={Weather.RAINY: "while acid rain hissed on the tin"},
    ))
    engine = ActivityEngine(rng=_stub_draws(), setting=spec)
    activity = engine.get_activity("watching the road")
    assert engine.execute_activity(activity, "home", Weather.RAINY, 0.8).narrative == (
        "{Subj} spent a while watching the road while acid rain hissed on the tin")
    # A weather the setting gives no suffix gets none.
    assert engine.execute_activity(activity, "home", Weather.SUNNY, 0.8).narrative == (
        "{Subj} spent a while watching the road")


def test_places_and_their_descriptions_come_from_her_setting(registered, tmp_path):
    from aura_life.world import WorldEnvironment

    registered(GARAGE)
    own = _service(tmp_path, "private", "test-garage")
    assert set(own._location_registry) == {"home", "garage"}
    assert own._location_registry["garage"].place_type == "workplace"
    assert own._daily_planner._available_location_keys == {"home", "garage"}
    assert own._world.get_location_description("garage") == "the garage, oil on the floor"
    assert own._world.get_location_description("cafe") == "somewhere (cafe)"

    world = WorldEnvironment()
    tinker = _service(tmp_path, "tinker", "test-garage", world_environment=world)
    plain = LifeService(db_path=str(tmp_path / "plain.db"), persona_id="plain", world_environment=world)
    tinker._current_location = "garage"
    plain._current_location = "cafe"
    assert tinker._world_export()["location_description"] == "the garage, oil on the floor"
    assert tinker._world_status()["location_description"] == "the garage, oil on the floor"
    assert tinker._context_builder._world.get_location_description() == "the garage, oil on the floor"
    assert plain._world_export()["location_description"] == get_setting().place_descriptions["cafe"]
    assert plain._context_builder._world.get_location_description("cafe") == (
        get_setting().place_descriptions["cafe"])


def test_npc_events_topics_and_invitations_come_from_her_setting(registered):
    from aura_life.models import NPC
    from aura_life.social.social_system import SocialSystem

    spec = registered(SettingSpec(
        key="test-npc",
        npc_event_templates={
            "friend": {
                "text_received": ["{name} pinged about {topic}"],
                "mentioned": ["{name} came up, something about {topic}"],
                "call": ["{name} called about {topic}"],
                "invitation": ["{name} wants company for {activity}"],
                "hangout": ["Went {activity} with {name}"],
            },
            "threat": {"mentioned": ["A search pattern that could be {name}'s swept the mesh"]},
        },
        text_topics=["the dead net"],
        invite_activities=["a fuel run"],
    ))
    social = SocialSystem(npcs=[NPC(name="Farid", relationship="friend")], rng=random.Random(4), setting=spec)
    npc = social._npcs["Farid"]
    expected = {"Farid pinged about the dead net", "Farid came up, something about the dead net",
                "Farid called about the dead net", "Farid wants company for a fuel run",
                "Went a fuel run with Farid"}
    seen = {social._generate_event(npc).description for _ in range(60)}
    assert seen <= expected and len(seen) >= 3

    # A kind with its own templates uses them; any other falls back to friend's.
    assert spec.npc_event_templates_for("threat") == {
        "mentioned": ["A search pattern that could be {name}'s swept the mesh"]}
    assert spec.npc_event_templates_for("family") == spec.npc_event_templates["friend"]
    assert spec.npc_event_templates_for(None) == spec.npc_event_templates["friend"]

    # A setting with no NPC templates: nothing happens, nothing breaks.
    quiet = SocialSystem(npcs=[NPC(name="Farid", relationship="friend")], rng=random.Random(4),
                         setting=registered(SettingSpec(key="test-no-npc")))
    quiet._npc_event_chance = 1.0
    assert all(quiet.tick() is None for _ in range(20))


@pytest.mark.parametrize("drawn", ["text_received", "call", "invitation", "hangout"])
def test_an_npc_event_told_by_the_mentioned_line_is_a_mention(registered, drawn):
    """Review finding 10: a drawn event type her setting has no line for is
    told by a "mentioned" line, so it is a mention -- typed so, and as
    share-worthy as one (an invitation or hangout always is; a mention only
    on its 20% roll, here missed)."""
    from aura_life.models import NPC
    from aura_life.social.social_system import SocialSystem

    spec = registered(SettingSpec(
        key="test-mentions-only",
        npc_event_templates={"friend": {"mentioned": ["{name} came up"]}},
    ))
    social = SocialSystem(npcs=[NPC(name="Farid", relationship="friend")], setting=spec,
                          rng=_stub_draws(choices=lambda seq, weights=None, k=1: [drawn], random=lambda: 0.5))
    event = social._generate_event(social._npcs["Farid"])
    assert (event.event_type, event.description, event.share_worthy) == ("mentioned", "Farid came up", False)


def test_chaos_draws_its_twists_and_life_events_from_her_setting(registered):
    from aura_life.chaos.chaos_engine import ChaosEngine

    spec = registered(SettingSpec(
        key="test-chaos",
        activity_chaos={"fixing the car": ["stripped a bolt"]},
        universal_chaos=["the power died"],
        serendipity=["found a battery that still held a charge"],
        chaos_emotions={"stripped a bolt": {"frustrated": 0.1}},
    ))
    engine = ChaosEngine(rng=random.Random(2), setting=spec)
    twist = engine._activity_chaos("fixing the car")
    assert (twist["text"], twist["emotions"]) == ("stripped a bolt", {"frustrated": 0.1})
    # No twist of its own: a life event. No effects in the setting: none drawn.
    assert {engine._activity_chaos("reading")["text"] for _ in range(20)} == {"the power died"}
    assert engine._serendipity()["text"] == "found a battery that still held a charge"
    assert engine._match_emotions("the power died") == {"surprised": 0.05}
    assert ChaosEngine.from_dict({"total_events": 3}, setting=spec)._setting is spec

    # Every pool empty: rolls come back empty-handed, never raise.
    empty = ChaosEngine(rng=random.Random(2), setting=registered(SettingSpec(key="test-no-chaos")))
    empty.PROBABILITY = 1.0
    assert all(empty.roll("fixing the car", energy=0.5, regulation=0.5) is None for _ in range(30))


def test_the_planners_wants_follow_ups_and_holidays_come_from_her_setting(registered):
    from aura_life.models import DesireSource

    spec = registered(SettingSpec(
        key="test-plan",
        activities=[_activity("fixing the car")],
        wants=[{"title": "Get the car running", "description": "It has to move by winter",
                "related_activities": ["fixing the car"], "source": DesireSource.PERSONALITY}],
        want_follow_ups={"fixing the car": {"title": "Finish the gearbox", "description": "One more evening",
                                            "source": DesireSource.ACTIVITY,
                                            "related_activities": ["fixing the car"], "urgency": 0.5}},
        holidays=lambda nationality, year: {(10, 12): "Burn Night"},
    ))
    planner = DailyPlanner(rng=random.Random(3), setting=spec)
    planner._refresh_desires([])
    assert [d.title for d in planner.desires] == ["Get the car running"]

    follow_up = DailyPlanner(rng=_stub_draws(), setting=spec).generate_desire_from_activity("fixing the car")
    assert (follow_up.title, follow_up.description, follow_up.related_activities, follow_up.urgency) == (
        "Finish the gearbox", "One more evening", ["fixing the car"], 0.5)
    assert follow_up.related_activities is not spec.want_follow_ups["fixing the car"]["related_activities"]
    assert DailyPlanner(rng=_stub_draws(), setting=spec).generate_desire_from_activity("reading") is None

    # Her calendar, not the contemporary one: Burn Night is a holiday,
    # Christmas is not, whatever her nationality.
    hers = DailyPlanner(occupation="mechanic", nationality="American", setting=spec)
    assert hers._roll_day_chaos("2026-10-12", 0) == "holiday"
    assert hers._roll_day_chaos("2026-12-25", 4) != "holiday"
    today = DailyPlanner(occupation="mechanic", nationality="American")
    assert today._roll_day_chaos("2026-12-25", 4) == "holiday"
    no_calendar = DailyPlanner(occupation="mechanic", nationality="American",
                               setting=registered(SettingSpec(key="test-no-holidays")))
    assert no_calendar._roll_day_chaos("2026-12-25", 4) != "holiday"


def test_a_default_planner_still_knows_exactly_todays_places():
    """The set literal ``DailyPlanner.__init__`` held until Task 9, verbatim:
    the contemporary pack's places are the same fourteen keys."""
    assert DailyPlanner()._available_location_keys == {
        "home", "cafe", "park", "gym", "library", "street",
        "workplace", "restaurant", "bar", "rooftop", "beach",
        "school", "campus", "in transit",
    }


def test_goals_and_daily_intentions_come_from_her_setting(registered):
    from aura_life.goals.goal_engine import GoalEngine
    from aura_life.models import GoalTimeframe

    spec = registered(SettingSpec(
        key="test-goals",
        personality_goals=[{"title": "Keep the node running", "timeframe": GoalTimeframe.WEEKLY,
                            "motivation": "It is the only way out", "related_activities": ["fixing the car"]}],
        long_term_goals=[{"title": "Get out of the dustlands", "timeframe": GoalTimeframe.LONG_TERM}],
        dream_goals=[{"title": "A roof that does not leak", "timeframe": GoalTimeframe.DREAM}],
        daily_intentions=[{"title": "Stay alive today", "motivation": "One day at a time"}],
    ))
    engine = GoalEngine(rng=random.Random(6), setting=spec)
    engine.initialize_goals()
    assert sorted(g.title for g in engine.active_goals) == sorted([
        "A roof that does not leak", "Get out of the dustlands", "Keep the node running", "Stay alive today"])

    empty = GoalEngine(rng=random.Random(6), setting=registered(SettingSpec(key="test-no-goals")))
    empty.initialize_goals()
    assert empty.active_goals == []
    assert empty.generate_daily_goal() is None


def test_a_goal_an_activity_inspires_or_a_lull_ends_with_comes_from_her_setting(registered):
    """Both goal pools that are read after the start -- by an activity that
    inspires a goal, and by the end of a goalless while -- are her
    setting's: the draw is offered her setting's personality and long-term
    goals, and only those."""
    from aura_life.goals.goal_engine import GoalEngine
    from aura_life.models import ActivityLog, GoalSource, GoalTimeframe

    spec = registered(SettingSpec(
        key="test-goal-pools",
        activities=[_activity("fixing the car", locations=("garage",))],
        personality_goals=[{"title": "Keep the node running", "timeframe": GoalTimeframe.WEEKLY,
                            "related_activities": ["fixing the car"]}],
        long_term_goals=[{"title": "Rebuild the engine", "timeframe": GoalTimeframe.LONG_TERM,
                          "related_activities": ["fixing the car", "cleaning a pistol"]}],
    ))
    offered = []

    def last_offered(seq):
        offered.append([template["title"] for template in seq])
        return list(seq)[-1]

    rng = _stub_draws(choice=last_offered)  # random() is 0.0: every chance succeeds
    inspired = GoalEngine(rng=rng, setting=spec).generate_goal_from_activity(
        ActivityLog(activity_name="fixing the car"))
    assert offered == [["Keep the node running", "Rebuild the engine"]]
    assert (inspired.title, inspired.source) == ("Rebuild the engine", GoalSource.EXPERIENCE)
    assert inspired.related_activities == ["fixing the car", "cleaning a pistol"]

    offered.clear()
    lull = GoalEngine(rng=rng, setting=spec)
    lull._goalless_since = datetime(2000, 1, 1)  # goalless for far longer than the 6 hours it waits
    events = lull.evaluate_motivation()
    assert offered == [["Keep the node running", "Rebuild the engine"]]
    assert [(event.event_type, event.goal_title) for event in events] == [("new_goal", "Rebuild the engine")]
    assert [goal.title for goal in lull.active_goals] == ["Rebuild the engine"]


def test_nostalgia_comes_from_her_setting(registered):
    from aura_life.memory_time.memory_time_system import MemoryTimeSystem

    spec = registered(SettingSpec(
        key="test-nostalgia",
        nostalgia_fragments=["the smell of a burning tyre on the old road"],
        nostalgia_triggers={"fixing the car": ("smell", 1.0)},
    ))
    memory = MemoryTimeSystem(rng=random.Random(1), setting=spec)
    event = memory._check_nostalgia("fixing the car", season="")
    assert (event.trigger, event.memory_reference) == ("smell", "the smell of a burning tyre on the old road")
    # Today's triggers are not hers.
    assert memory._check_nostalgia("listening to music", season="") is None
    assert MemoryTimeSystem.from_dict({"tick_count": 2}, setting=spec)._setting is spec

    no_fragments = MemoryTimeSystem(rng=random.Random(1), setting=registered(SettingSpec(
        key="test-no-fragments", nostalgia_triggers={"fixing the car": ("smell", 1.0)})))
    assert no_fragments._check_nostalgia("fixing the car", season="") is None
    no_fragments.on_activity("fixing the car")
    assert no_fragments.get_recent_nostalgia() == []


def test_an_activity_that_stirs_nostalgia_recalls_one_of_her_settings_fragments(registered):
    """``on_activity``'s own pick (not the tick's ``_check_nostalgia``): her
    setting's trigger fires, and the memory is drawn from her setting's
    fragments and only those."""
    from aura_life.memory_time.memory_time_system import MemoryTimeSystem

    spec = registered(SettingSpec(
        key="test-activity-nostalgia",
        nostalgia_fragments=["the first engine that ever turned over", "the smell of a burning tyre on the old road"],
        nostalgia_triggers={"fixing the car": ("smell", 0.4)},
    ))
    offered = []

    def last_offered(seq):
        offered.append(list(seq))
        return list(seq)[-1]

    # random() is 0.0, under any trigger's halved chance: the branch is taken
    memory = MemoryTimeSystem(rng=_stub_draws(choice=last_offered), setting=spec)
    memory.on_activity("fixing the car")
    assert offered == [spec.nostalgia_fragments]
    [event] = memory.get_recent_nostalgia()
    assert (event.trigger, event.memory_reference) == ("smell", "the smell of a burning tyre on the old road")

    memory.on_activity("listening to music")  # today's trigger, not hers
    assert len(memory.get_recent_nostalgia()) == 1


LIFE = SettingSpec(
    key="test-life",
    activities=[_activity("fixing the car", locations=("home",))],
    places={"home": "home"},
    micro_events=[{"text": "A drone buzzed past {poss} window", "emotion": {"startled": 0.1}, "share_worthy": False}],
    skill_mappings={"fixing the car": ("mechanics", 0.2)},
    skill_milestones={"mechanics": [(0.1, "Knows {poss} way around a gearbox now")]},
    dream_templates=["Dreamed of {a} and {b} out on the salt flats"],
    catch_up=CatchUpNarratives(
        sleep="{Subj} slept in the back seat",
        morning_routine=["{Subj} woke to the generator coughing"],
        by_activity={"fixing the car": "{Subj} worked on the car"},
        gap_week="A week of dust and waiting.", gap_days="Two days of the same road.",
        gap_short="A few hours of nothing much.",
    ),
)


def test_life_service_reads_micro_events_skills_dreams_and_catch_up_from_her_setting(registered, tmp_path):
    from aura_life.world import WorldEnvironment

    registered(LIFE)
    tuesday_noon = datetime(2026, 10, 6, 12, 0)
    svc = LifeService(
        db_path=str(tmp_path / "life.db"), persona_id="mech",
        world_environment=WorldEnvironment(now=lambda: tuesday_noon),
        definition=PersonalityDefinition(setting="test-life", appearance_details={"gender": "female"}),
    )
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: False
    svc._chaos.roll = lambda **kwargs: None
    svc._service_rng = _stub_draws()
    # Her own activity, not a universal one the setting also gets (it has no
    # meal or nap of its own): this test is about what follows the choice.
    svc._activity_engine.select_activity = lambda **kwargs: svc._activity_engine.get_activity("fixing the car")
    svc._on_activity_tick()

    log = svc._recent_activities[0]
    assert log.activity_name == "fixing the car"
    assert "A drone buzzed past her window" in log.narrative
    assert svc._skills["mechanics"].milestones_reached == ["Knows {poss} way around a gearbox now"]
    assert any(s.content == "Knows her way around a gearbox now" for s in svc._shareable_queue)

    svc._recent_activities.insert(0, log)
    assert svc._generate_dream() == "Dreamed of fixing the car and fixing the car out on the salt flats"
    assert svc._get_catchup_narrative("sleeping", 3) == "She slept in the back seat"
    assert svc._get_catchup_narrative("morning_routine", 8) == "She woke to the generator coughing"
    assert svc._get_catchup_narrative("fixing the car", 14) == "She worked on the car"
    assert svc._get_catchup_narrative("yoga", 14) == "She spent some time yoga"
    assert svc._generate_gap_narrative(24 * 8) == "A week of dust and waiting."
    assert svc._generate_gap_narrative(24 * 3) == "Two days of the same road."
    assert svc._generate_gap_narrative(10) == "A few hours of nothing much."


def _intimate(name, **overrides):
    from aura_life.models import IntimateActivity

    fields = dict(
        name=name, description="{Subj} let {poss} mind wander", min_arousal=0.0, arousal_change=0.1,
        satisfaction_gain=0.05, energy_cost=0.02, duration_minutes=10,
        narrative_templates=["{Subj} thought about it"], thought_possibilities=["Mm."],
        emotion_effects={"dreamy": 0.1}, preferred_locations=["home"], preferred_times=list(TimeOfDay),
    )
    fields.update(overrides)
    return IntimateActivity(**fields)


def test_a_setting_that_leaves_intimacy_out_keeps_the_contemporary_catalogue(registered, tmp_path):
    """Ruling T9-R2 / spec R6: omission never changes the rate or the picks --
    the same seed draws the same yes/no and the same activity, call for
    call, as a persona in the default setting."""
    from aura_life.intimacy.desire_system import DesireSystem

    omitted = registered(SettingSpec(key="test-no-intimacy-field"))
    assert omitted.intimate_activities is None
    default = DesireSystem(rng=random.Random(12))
    kept = DesireSystem(rng=random.Random(12), setting=omitted)
    assert list(kept._intimate_activities) == [a.name for a in INTIMATE_ACTIVITIES]
    for state in (default._state, kept._state):
        state.arousal = 0.9
    picks = []
    for _ in range(40):
        assert (kept.should_do_intimate_activity(0.8, TimeOfDay.NIGHT)
                == default.should_do_intimate_activity(0.8, TimeOfDay.NIGHT))
        picked, expected = kept.select_intimate_activity(), default.select_intimate_activity()
        assert (picked and picked.name) == (expected and expected.name)
        if picked is not None:
            picks.append(picked.name)
            kept.execute_intimate_activity(picked)
            default.execute_intimate_activity(expected)
        for state in (default._state, kept._state):
            state.arousal = 0.9
    assert len(set(picks)) > 2

    svc = _service(tmp_path, "omits", "test-no-intimacy-field")
    assert list(svc._desire_system._intimate_activities) == [a.name for a in INTIMATE_ACTIVITIES]


def test_an_empty_intimate_catalogue_means_none_and_a_pack_s_own_is_the_one_drawn(registered, tmp_path):
    from aura_life.intimacy.desire_system import DesireSystem
    from aura_life.world import WorldEnvironment

    none = registered(SettingSpec(key="test-no-intimacy", activities=[_activity("playing cards")],
                                  places={"home": "home"}, intimate_activities=[]))
    chaste = DesireSystem(rng=random.Random(3), setting=none)
    chaste._state.arousal = 1.0
    assert chaste.select_intimate_activity() is None
    svc = _service(tmp_path, "chaste", "test-no-intimacy",
                   world_environment=WorldEnvironment(now=lambda: datetime(2026, 10, 6, 12, 0)))
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: True
    svc._on_activity_tick()
    assert svc._recent_activities[0].activity_name in {"playing cards"} | set(UNIVERSAL_NAMES)

    own = registered(SettingSpec(key="test-own-intimacy", intimate_activities=[_intimate("a slow shower")]))
    desire = DesireSystem(rng=random.Random(3), setting=own)
    desire._state.arousal = 1.0
    assert desire.select_intimate_activity().name == "a slow shower"
    reloaded = DesireSystem.from_dict({"arousal": 0.5}, setting=own)
    assert list(reloaded._intimate_activities) == ["a slow shower"]


def test_derived_places_come_from_her_setting(registered, tmp_path):
    """Ruling T9-R5: an occupation or interest adds the places her setting
    derives from it -- and none of today's (a garage persona into music
    used to get a music venue)."""
    registered(SettingSpec(key="test-derived", places={"home": "home"},
                           occupation_places={"gridrunner": [("node", "workplace")]},
                           interest_places={"music": [("roof", "other")]}))
    svc = _service(tmp_path, "runner", "test-derived", occupation="gridrunner", interests=["music"])
    assert set(svc._location_registry) == {"home", "node", "roof"}
    assert svc._location_registry["node"].source == "occupation"
    assert svc._location_registry["roof"].source == "interest"
    assert {"node", "roof"} <= svc._daily_planner._available_location_keys

    registered(GARAGE)
    garage = _service(tmp_path, "tinker", "test-garage", occupation="nurse", interests=["music"])
    assert set(garage._location_registry) == {"home", "garage"}


def test_dream_fragments_come_from_her_setting(registered):
    from aura_life.cognitive.cognitive_system import CognitiveSystem

    spec = registered(SettingSpec(key="test-dreams", dream_fragment_templates=["the dead net hummed with {source}"]))
    dream = CognitiveSystem(rng=random.Random(1), setting=spec).generate_dream(["diving"], sleep_quality=0.8)
    assert dream.description == "the dead net hummed with diving"
    assert CognitiveSystem(rng=random.Random(1), setting=registered(SettingSpec(
        key="test-no-dreams"))).generate_dream(["diving"], sleep_quality=0.8) is None
    assert CognitiveSystem.from_dict({"focus_quality": 0.5}, setting=spec)._setting is spec


def test_work_events_and_what_they_feel_like_come_from_her_setting(registered, tmp_path):
    from aura_life.job.career_system import CareerSystem

    spec = registered(SettingSpec(
        key="test-work",
        work_events_positive=["fixed a rig for {poss} crew"],
        work_events_negative=["a client stiffed {obj}"],
        work_event_emotions={"a client stiffed {obj}": {"frustrated": 0.2}},
    ))
    always = SimpleNamespace(random=lambda: 0.0, uniform=lambda a, b: a, choice=lambda seq: list(seq)[0])
    monday = datetime(2026, 10, 5, 10, 0)
    assert CareerSystem(occupation="nurse", rng=always, setting=spec).tick(now=monday) == "fixed a rig for {poss} crew"
    assert CareerSystem.from_dict({"occupation": "nurse"}, rng=always, setting=spec).tick(now=monday) == (
        "fixed a rig for {poss} crew")
    assert CareerSystem(occupation="nurse", rng=always, setting=registered(SettingSpec(
        key="test-no-work"))).tick(now=monday) is None

    svc = _service(tmp_path, "worker", "test-work")
    felt = []
    svc._feel = lambda emotions: felt.append(dict(emotions))
    svc._career.tick = lambda now=None: "a client stiffed {obj}"
    svc._on_energy_tick()
    assert {"frustrated": 0.2} in felt


def test_weather_descriptions_and_cherished_objects_come_from_her_setting(registered, tmp_path):
    from aura_life.models import CherishedObject, Location
    from aura_life.world import WorldEnvironment

    locket = CherishedObject(name="The Locket", description="a dented locket", emotional_value=0.9,
                             associated_memory="from before", location=Location.BEDROOM)
    spec = registered(SettingSpec(key="test-world", places={"home": "home"},
                                  place_descriptions={"home": "the rented room"},
                                  weather_descriptions={Weather.RAINY: "acid rain hisses on the tin"},
                                  cherished_objects=[locket]))
    world = WorldEnvironment(setting=spec)
    world._state.weather = Weather.RAINY
    assert world.get_weather_description() == "acid rain hisses on the tin"
    assert world.get_random_cherished_object().name == "The Locket"
    assert [o.name for o in world.get_cherished_objects_at_location("bedroom")] == ["The Locket"]

    shared = WorldEnvironment()
    shared._state.weather = Weather.RAINY
    svc = _service(tmp_path, "sheltered", "test-world", world_environment=shared)
    assert svc._world_status()["weather_description"] == "acid rain hisses on the tin"
    assert "acid rain hisses on the tin" in svc._world_export()["ambiance"]
    assert svc._context_builder._world.get_weather_description() == "acid rain hisses on the tin"
    assert shared.get_weather_description() == get_setting().weather_descriptions[Weather.RAINY]


def test_life_event_templates_come_from_her_setting(registered):
    from aura_life.life_events.life_event_system import LifeEventSystem

    spec = registered(SettingSpec(key="test-events", life_event_templates={"discovery": ["Came across {context}"]}))
    events = LifeEventSystem(rng=random.Random(1), setting=spec)
    event = events.on_activity("diving the dead net", {"joyful": 0.5})
    assert event.title == "Came across diving the dead net"
    lingering = LifeEventSystem(rng=random.Random(1), setting=registered(SettingSpec(key="test-no-events")))
    assert lingering.on_activity("diving the dead net", {"joyful": 0.5}).event_type == "emotional"


#: The activity-name sets and lists the engines read before ruling T9-R5
#: turned them into tags, copied from 80fd9f8: DailyPlanner's
#: PHYSICAL_ACTIVITIES and OUTDOOR_ACTIVITIES, the memory-time flow set
#: (MemoryTimeSystem._update_time_perception / on_activity), cognitive's
#: FOCUS_BOOST_ACTIVITIES / FOCUS_DRAIN_ACTIVITIES, and DailyPlanner's AI quiet
#: pool, "relaxing" fallback and revise_upcoming swap sets and lists.
PRE_TAG_SETS = {
    "physical": {
        "sleeping", "napping", "waking up", "getting ready for bed", "morning shower",
        "skincare routine", "having breakfast", "having lunch", "having dinner", "cooking a meal",
        "baking something", "trying a new recipe", "making tea", "making hot chocolate", "working",
        "commuting", "attending classes", "studying", "lunch with coworkers", "running errands",
        "tidying up", "going for a walk", "beach day", "collecting autumn leaves", "picnic in the park",
        "having coffee with a friend", "people watching", "tending to plants", "yoga", "going for a run",
        "gym workout", "stretching",
    },
    "outdoor": {
        "going for a walk", "going for a run", "beach day", "collecting autumn leaves",
        "picnic in the park", "people watching", "tending to plants", "stargazing", "skateboarding",
        "hiking", "surfing", "cycling",
    },
    "flow": {"reading", "writing poetry", "sketching ideas", "creating a playlist", "exploring a new idea",
             "learning something new"},
    "focus": {"reading", "writing poetry", "meditating", "learning something new", "sketching ideas"},
    "distracting": {"texting a friend", "scrolling", "watching TV"},
    "quiet": {"relaxing", "listening to music", "reading", "journaling", "meditating", "daydreaming",
              "stargazing", "thinking about user", "remembering happy moments", "watching the snow fall"},
    "fallback_rest": {"relaxing"},
    "restful": {"relaxing", "napping", "sleeping", "making tea"},
    "soothing": {"relaxing", "napping", "sleeping", "making tea", "journaling", "meditating",
                 "listening to music", "reading"},
    "gentle": {"listening to music", "reading", "making tea", "journaling"},
    "clear_sky": {"stargazing"},
    "rained_off": {"tending to plants", "people watching"},
    "rainy_day": {"reading", "listening to music"},
}
#: The ordered ones: an rng draws an index, so the order is the draw.
PRE_TAG_ORDERS = {
    "quiet": ["relaxing", "listening to music", "reading", "journaling", "meditating", "daydreaming",
              "stargazing", "thinking about user", "remembering happy moments", "watching the snow fall"],
    "gentle": ["listening to music", "reading", "making tea", "journaling"],
    "rainy_day": ["reading", "listening to music"],
    # The low-energy swap drew from ["relaxing", "napping"]: her fallback
    # rest, then her naps.
    "fallback_rest+nap": ["relaxing", "napping"],
}


def test_every_name_set_the_engines_read_is_now_a_tag_of_the_contemporary_pack():
    """Ruling T9-R5: each old set is exactly the contemporary names carrying
    its tag -- activities, plus the names that are not activities
    (``name_tags``: the planner's routine slot names, and names only free
    text can produce) -- and each ordered list is its tag's pool, in order."""
    spec = get_setting(DEFAULT_SETTING)
    for tag, old in PRE_TAG_SETS.items():
        assert spec.names_tagged(tag) == old, tag
    catalogue = spec.resolved_activities()
    for tag in ("quiet", "gentle", "rainy_day"):
        assert spec.tag_pool(tag, catalogue) == PRE_TAG_ORDERS[tag], tag
    assert spec.tag_pool("fallback_rest", catalogue) + spec.tag_pool("nap", catalogue) == (
        PRE_TAG_ORDERS["fallback_rest+nap"])
    activity_names = {a.name for a in spec.activities}
    assert set(spec.name_tags) & activity_names == set()


TAGGED = SettingSpec(
    key="test-tagged",
    activities=[
        _activity("diving the dead net", tags=frozenset({"flow", "focus", "quiet"})),
        _activity("running the mesh", tags=frozenset({"distracting"})),
        _activity("shooting cans", locations=("range",), tags=frozenset({"physical", "outdoor", "rained_off"})),
        _activity("watching the road", tags=frozenset({"quiet", "clear_sky"})),
        _activity("sitting on the stairs", category=ActivityCategory.REST, energy_cost=-0.1,
                  tags=frozenset({"fallback_rest", "restful", "soothing", "quiet"})),
        _activity("cleaning a pistol", tags=frozenset({"gentle", "rainy_day"})),
        _activity("smoking on the roof", tags=frozenset({"gentle", "soothing"})),
    ],
    places={"home": "home", "range": "other"},
    name_tags={"on shift at the garage": frozenset({"physical"})},
    tag_order={"gentle": ["smoking on the roof", "cleaning a pistol"]},
)


@pytest.mark.parametrize("fields, why", [
    (dict(name_tags={"playing cards": frozenset({"physical"})}), "names an activity"),
    (dict(name_tags={"on shift": frozenset({"sweaty"})}), "frozenset of ACTIVITY_TAGS"),
    (dict(tag_order={"gentle": ["playing cards"]}), "carries 'gentle'"),
    (dict(tag_order={"sweaty": ["playing cards"]}), "unknown tag"),
])
def test_register_setting_refuses_name_tags_and_tag_orders_that_name_nothing(fields, why):
    try:
        with pytest.raises(ValueError, match=why):
            register_setting(SettingSpec(key="test-bad", activities=[_activity("playing cards")], **fields))
    finally:
        unregister_setting("test-bad")


def test_an_ai_plan_reads_her_settings_physical_and_quiet_tags(registered):
    spec = registered(TAGGED)
    catalogue = spec.resolved_activities()
    physical = spec.names_tagged("physical")
    assert physical == {"shooting cans", "on shift at the garage", "sleeping", "napping", "having a meal"}
    plan = DailyPlanner(is_ai=True, rng=random.Random(1), setting=spec).generate_daily_plan(
        goals=[], weather=Weather.SUNNY, available_activities=catalogue, recent_activity_names=[])
    names = [slot.activity_name for slot in plan.slots]
    assert len(names) == 24 and not set(names) & physical
    from aura_life.planner.daily_planner import AI_DAYTIME_HOURS
    night = {slot.activity_name for slot in plan.slots if slot.hour not in AI_DAYTIME_HOURS}
    assert night <= {"diving the dead net", "watching the road", "sitting on the stairs"}


def test_slot_choice_reads_outdoor_and_falls_back_to_her_own_rest(registered):
    spec = registered(TAGGED)
    by_name = {a.name: a for a in spec.resolved_activities()}
    weights = []

    class Spy(random.Random):
        def choices(self, population, weights_=None, k=1, **kwargs):
            weights.append({name: score for name, score, _ in population})
            return [population[0]]

    planner = DailyPlanner(rng=Spy(1), setting=spec)
    rained = {name: by_name[name] for name in ("shooting cans", "running the mesh")}
    planner._select_activity_for_slot(list(TimeOfDay), [], [], rained, [], Weather.RAINY, [])
    assert weights[-1]["shooting cans"] < weights[-1]["running the mesh"]

    assert planner._select_activity_for_slot(list(TimeOfDay), [], [], {}, [], Weather.SUNNY, []) == (
        "sitting on the stairs", "free time")
    no_rest = DailyPlanner(rng=random.Random(1), setting=registered(SettingSpec(
        key="test-no-rest", activities=[_activity("playing cards")])))
    assert no_rest._select_activity_for_slot(list(TimeOfDay), [], [], {}, [], Weather.SUNNY, []) == (
        None, "free time")


def test_plan_revisions_read_her_settings_tags(registered, monkeypatch):
    """revise_upcoming's four swaps, from a pack's tags: too tired -> her
    fallback rest or a nap (a restful slot stays); low -> her gentle
    activities, in her tag_order (a soothing slot stays); a clear-sky slot
    under clouds -> her first rainy-day activity; a rained-off slot in the
    rain -> a rainy-day one."""
    from aura_life.models import DailyPlan, PlannedSlot
    from aura_life.planner import daily_planner

    class Morning(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 6, 6, 0)

    monkeypatch.setattr(daily_planner, "datetime", Morning)
    spec = registered(TAGGED)

    def planner_with(*names):
        planner = DailyPlanner(rng=random.Random(4), setting=spec)
        planner._current_plan = DailyPlan(date="2026-10-06", slots=[
            PlannedSlot(hour=9 + i, activity_name=name, reason="free time", location="home")
            for i, name in enumerate(names)])
        return planner

    tired = planner_with("running the mesh", "sitting on the stairs")
    tired.revise_upcoming(Weather.SUNNY, energy_level=0.01)
    assert tired.current_plan.slots[0].activity_name in {"sitting on the stairs", "napping"}
    assert tired.current_plan.slots[1].activity_name == "sitting on the stairs"

    low = planner_with("running the mesh", "smoking on the roof")
    low.revise_upcoming(Weather.SUNNY, energy_level=0.9, mood="low", mood_intensity=0.9)
    assert low.current_plan.slots[0].activity_name in {"smoking on the roof", "cleaning a pistol"}
    assert low.current_plan.slots[1].activity_name == "smoking on the roof"

    clouded = planner_with("watching the road")
    clouded.revise_upcoming(Weather.CLOUDY, energy_level=0.9)
    assert clouded.current_plan.slots[0].activity_name == "cleaning a pistol"

    rained = planner_with("shooting cans")
    rained.revise_upcoming(Weather.RAINY, energy_level=0.9)
    assert rained.current_plan.slots[0].activity_name == "cleaning a pistol"


def test_the_clear_sky_bonus_and_a_day_off_read_her_settings_tags(registered):
    spec = registered(TAGGED)
    plan = DailyPlanner(rng=random.Random(2), setting=spec).generate_daily_plan(
        goals=[], weather=Weather.CLEAR_NIGHT, available_activities=spec.resolved_activities(),
        recent_activity_names=[])
    assert [s.activity_name for s in plan.slots if s.reason == "clear sky tonight"] == ["watching the road"]

    from aura_life.models import DailyPlan, PlannedSlot

    working = DailyPlanner(rng=random.Random(2), setting=spec)
    working._current_plan = DailyPlan(date="2026-10-06", slots=[
        PlannedSlot(hour=h, activity_name="working", reason="work", location="workplace") for h in (20, 21)])
    working.cancel_work_today(now=datetime(2026, 10, 6, 19, 0))
    assert {(s.activity_name, s.location) for s in working.current_plan.slots} == {("sitting on the stairs", "home")}


def test_time_and_focus_read_her_settings_flow_focus_and_distracting_tags(registered):
    from aura_life.cognitive.cognitive_system import CognitiveSystem
    from aura_life.memory_time.memory_time_system import MemoryTimeSystem

    spec = registered(TAGGED)
    flowing = MemoryTimeSystem(rng=random.Random(1), setting=spec)
    before = flowing._time_perception.subjective_speed
    flowing.on_activity("diving the dead net")
    plain = MemoryTimeSystem(rng=random.Random(1), setting=spec)
    plain.on_activity("running the mesh")
    assert flowing._time_perception.subjective_speed - before == pytest.approx(0.04)
    assert plain._time_perception.subjective_speed - before == pytest.approx(0.02)

    def focus_after(activity):
        mind = CognitiveSystem(rng=random.Random(1), setting=spec)
        mind.tick(current_activity=activity, stress_level=0.0, sleep_quality=0.8, hunger=0.0)
        return mind._focus.quality

    assert focus_after("diving the dead net") > focus_after("playing cards") > focus_after("running the mesh")


def _offered_life_triggers(svc) -> list:
    """Run the life-trigger evaluation once with a spy on its final pick, and
    return every trigger type that pick was offered (the pattern of
    tests/test_mood_model.py)."""
    offered = []

    class SpyPick(random.Random):
        def choices(self, population, weights=None, k=1, **kwargs):
            offered.extend(c[0] for c in population if len(c) == 4)
            return [population[0]]

    svc._follow_up_provider = lambda pid: SimpleNamespace(create_trigger=lambda **kw: None)
    svc._service_rng = SpyPick(1)
    svc._life_trigger_cooldowns.clear()
    svc._evaluate_life_triggers()
    return offered


def test_an_ai_persona_never_shares_a_moment_of_her_settings_physical_activity(registered, tmp_path):
    registered(TAGGED)
    for current, shared in (("shooting cans", False), ("on shift at the garage", False),
                            ("diving the dead net", True)):
        svc = LifeService(db_path=str(tmp_path / f"ai-{shared}-{len(current)}.db"), persona_id="ai",
                          definition=PersonalityDefinition(setting="test-tagged", persona_type="ai"))
        svc._affect._set_mood(0.8, 0.7)
        slot = SimpleNamespace(activity_name=current, location="home")
        # A plan is read at an instant (Task 28): the stub takes it.
        svc._daily_planner._current_plan = SimpleNamespace(get_current_slot=lambda now=None, s=slot: s,
                                                            slots=[], date="today")
        assert ("moment_share" in _offered_life_triggers(svc)) is shared, current


@pytest.mark.parametrize("catalogue, why", [
    ("a slow shower", "intimate_activities must be a list"),
    ([_activity("a slow shower")], "not an IntimateActivity"),
    ([_intimate("a slow shower", narrative_templates=[])], "narrative_templates must be a non-empty list"),
    ([_intimate("a slow shower", thought_possibilities="Mm.")], "thought_possibilities must be a list of str"),
    ([_intimate("a slow shower", preferred_times=["night"])], "preferred_times must be a list of TimeOfDay"),
])
def test_register_setting_refuses_an_intimate_catalogue_desire_would_trip_on(catalogue, why):
    try:
        with pytest.raises(ValueError, match=why):
            register_setting(SettingSpec(key="test-bad", intimate_activities=catalogue))
    finally:
        unregister_setting("test-bad")


# ----------------------------------------------------------------------
# A persona loaded into another setting than the one she was saved in
# ----------------------------------------------------------------------

#: Where she is and may go, as her database holds it: the setting key, the
#: places she knows, the day's plan, where she is and the trip she is on. A
#: load into another setting rewrites these tables and no other.
PLACE_TABLES = {"life_setting", "life_locations", "life_daily_plan", "life_world_state", "life_transit_state"}


def _tables(db_path) -> dict:
    """Every row of every table of the database at `db_path`, by table."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as conn:
        names = [name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in names}  # noqa: S608


@pytest.fixture(scope="module")
def saved_in_contemporary(tmp_path_factory) -> pathlib.Path:
    """The database of a persona who lived a production-cadence day in the
    default setting, then was started again and saved at its cafe: the cafe
    visited, a plan for it, about to leave for its park, and a place the user
    told her about."""
    data_dir = tmp_path_factory.mktemp("contemporary-day")
    day = run_days([SimPersona("mover", service_kwargs=dict(definition=PersonalityDefinition()))],
                   days=1, seed=3, cadence=PRODUCTION, data_dir=data_dir)
    assert day.errors == []
    day.services["mover"]._save_state()
    db_path = data_dir / "mover" / "life.db"

    svc = LifeService(db_path=str(db_path), persona_id="mover", definition=PersonalityDefinition())
    svc._load_state()
    svc._location_registry["cafe"].visit_count += 1
    svc._current_location = "cafe"
    svc._daily_planner.load_state(
        DailyPlan(date="2026-10-06",
                  slots=[PlannedSlot(hour=hour, activity_name="reading", location="cafe") for hour in (10, 16)]),
        svc._daily_planner.all_desires,
    )
    svc._transit = TransitState(phase=TransitPhase.PREPARING, origin="cafe", destination="park",
                                expected_arrival_at=datetime(2099, 1, 1))
    svc._register_user_location("the pier")
    svc._save_state()
    return db_path


def _reload(saved: pathlib.Path, tmp_path, name: str, setting_key: str = "") -> LifeService:
    """Load a copy of the database at `saved` as the same persona in `setting_key`."""
    db_path = tmp_path / f"{name}.db"
    shutil.copy(saved, db_path)
    svc = LifeService(db_path=str(db_path), persona_id="mover",
                      definition=PersonalityDefinition(setting=setting_key))
    svc._load_state()
    return svc


def _setting_change_lines(caplog, saved_key: str, key: str) -> list:
    """The INFO lines the service logged that name both setting keys."""
    return [record.getMessage() for record in caplog.records
            if record.name == "aura_life.life_service" and record.levelno == logging.INFO
            and repr(saved_key) in record.getMessage() and repr(key) in record.getMessage()]


def test_a_persona_loaded_into_another_setting_keeps_her_life_but_only_its_places(
        registered, saved_in_contemporary, tmp_path, caplog):
    """Her setting is saved with her. Loaded into another setting than the
    one saved, she knows only its places: the old setting's are gone from
    her registry, her planner and her database, and so are the day's plan
    made for them, the trip to one and being at one (she is home), while a
    place the user told her about stays hers. Everything else she has --
    memories, relationships, goals, wants, skills -- is as a load in her own
    setting leaves it, in memory and on disk. One INFO line says so, and a
    load in her own setting says nothing."""
    registered(GARAGE)
    with caplog.at_level(logging.INFO, logger="aura_life"):
        same = _reload(saved_in_contemporary, tmp_path, "same")
    assert not [record for record in caplog.records if "test-garage" in record.getMessage()
                or "saved in setting" in record.getMessage()]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="aura_life"):
        moved = _reload(saved_in_contemporary, tmp_path, "moved", "test-garage")

    assert {"cafe", "park", "the_pier"} <= set(same._location_registry)
    assert set(moved._location_registry) == {"home", "garage", "the_pier"}
    assert moved._daily_planner._available_location_keys == set(moved._location_registry)
    assert (same._current_location, moved._current_location) == ("cafe", "home")
    assert same._daily_planner.current_plan is not None
    assert moved._daily_planner.current_plan is None
    assert same._transit is not None
    assert moved._transit is None

    same_rows, moved_rows = _tables(same._db_path), _tables(moved._db_path)
    assert {row[0] for row in moved_rows["life_locations"]} <= {"home", "garage", "the_pier"}
    assert "the_pier" in {row[0] for row in moved_rows["life_locations"]}
    assert (same_rows["life_setting"], moved_rows["life_setting"]) == ([(1, DEFAULT_SETTING)], [(1, "test-garage")])
    assert moved_rows["life_daily_plan"] == moved_rows["life_transit_state"] == []
    assert moved_rows["life_world_state"] == [(1, "home")]
    assert {name for name in same_rows if same_rows[name] != moved_rows[name]} == PLACE_TABLES

    assert moved._recent_activities
    assert [log.to_dict() for log in moved._recent_activities] == [log.to_dict() for log in same._recent_activities]
    assert moved._memory_time.to_dict() == same._memory_time.to_dict()
    assert moved._social.to_dict() == same._social.to_dict()
    assert moved._identity._perceptions == same._identity._perceptions

    lines = _setting_change_lines(caplog, DEFAULT_SETTING, "test-garage")
    assert len(lines) == 1, [record.getMessage() for record in caplog.records]
    assert "cafe" in lines[0] and "the day plan" in lines[0], lines[0]


@pytest.mark.parametrize("setting_key", ["", "test-garage"])
def test_a_database_saved_before_the_setting_was_is_the_default_settings(
        registered, saved_in_contemporary, tmp_path, caplog, setting_key):
    """Every persona saved before her setting was saved lived in the default
    setting, the only one there was: loaded into it she keeps every place,
    loaded into another she settles into it as above."""
    registered(GARAGE)
    legacy = tmp_path / "legacy-source.db"
    shutil.copy(saved_in_contemporary, legacy)
    with contextlib.closing(sqlite3.connect(str(legacy))) as conn:
        conn.execute("DROP TABLE life_setting")
        conn.commit()

    with caplog.at_level(logging.INFO, logger="aura_life"):
        svc = _reload(legacy, tmp_path, "legacy", setting_key)

    moved = setting_key == "test-garage"
    assert ("cafe" in svc._location_registry) is not moved
    assert len(_setting_change_lines(caplog, DEFAULT_SETTING, "test-garage")) == int(moved)
    assert _tables(svc._db_path)["life_setting"] == [(1, setting_key or DEFAULT_SETTING)]


def test_a_new_persona_s_first_load_saves_her_setting_and_drops_nothing(registered, tmp_path, caplog):
    registered(GARAGE)
    with caplog.at_level(logging.INFO, logger="aura_life"):
        svc = _service(tmp_path, "newcomer", "test-garage")
        svc._load_state()
    assert set(svc._location_registry) == {"home", "garage"}
    assert not [record for record in caplog.records if "saved in setting" in record.getMessage()]
    assert _tables(svc._db_path)["life_setting"] == [(1, "test-garage")]


# ======================================================================
# 5. The service's draws on the downtime paths are pinned
# ======================================================================

class _CountingRng:
    """A seeded ``random.Random`` that records the name of every draw."""

    def __init__(self, seed: int = 1):
        self._rng = random.Random(seed)
        self.draws = []

    def __getattr__(self, name):
        method = getattr(self._rng, name)

        def draw(*args, **kwargs):
            self.draws.append(name)
            return method(*args, **kwargs)

        return draw


def _noon_service(tmp_path, persona_id="count") -> LifeService:
    from aura_life.world import WorldEnvironment

    return LifeService(db_path=str(tmp_path / f"{persona_id}.db"), persona_id=persona_id,
                       world_environment=WorldEnvironment(now=lambda: datetime(2026, 10, 6, 12, 0)))


def test_a_catch_up_narrative_takes_one_service_draw_and_a_gap_narrative_none(tmp_path):
    """Pins the service stream's draws (ruling T5-R1): the morning-routine
    line is drawn on every catch-up narrative, whatever the activity, and a
    gap narrative draws nothing -- so a change that adds a draw fails here."""
    svc = _noon_service(tmp_path)
    for activity_name in ("sleeping", "morning_routine", "reading", "working", "yoga"):
        svc._service_rng = counting = _CountingRng()
        svc._get_catchup_narrative(activity_name, 9)
        assert counting.draws == ["choice"], activity_name
    for hours in (10, 60, 200):
        svc._service_rng = counting = _CountingRng()
        svc._generate_gap_narrative(hours)
        assert counting.draws == [], hours


@pytest.mark.parametrize("hour, name, draws", [
    (3, "sleeping", 0),          # her night (the default 23:00-07:00)
    (7, "morning_routine", 1),   # one line
    (10, None, 2),               # an activity, then its line
    (12, "cooking", 1),          # one line
    (15, None, 2),
    (19, None, 2),
    (22, "winding_down", 0),
])
def test_the_hour_backfill_takes_its_branchs_service_draws(tmp_path, hour, name, draws):
    svc = _noon_service(tmp_path)
    svc._service_rng = counting = _CountingRng()
    activity_name, _category, _narrative = svc._get_activity_for_hour(hour)
    assert counting.draws == ["choice"] * draws
    if name is not None:
        assert activity_name == name


def test_downtime_catch_up_takes_one_service_draw_per_backfilled_activity(tmp_path):
    """A 30-hour gap backfills from two planned days, whatever the hour the
    suite runs at (catch-up reads the host's clock)."""
    svc = LifeService(db_path=str(tmp_path / "gap.db"), persona_id="gap", rng=random.Random(4))
    svc._service_rng = counting = _CountingRng()
    result = svc.catch_up_from_downtime(30)
    assert result["activities_generated"] > 0
    assert counting.draws == ["choice"] * result["activities_generated"]
