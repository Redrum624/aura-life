"""Her life is decided on the world clock (humanness program Task 19, rulings
T11-R3, T19-R1, T19-R2, T19-R4).

Every read below used to be ``datetime.now()``: the host's clock, which a
simulation (tests/sim_helpers.run_days) freezes at the world's instant -- so
no simulation could see it -- but which a host whose world clock is not its
wall clock (one that simulates time, or pauses it) reads as a different hour,
day or year. Each engine now takes the instant as an optional keyword
(``now=``; without it, the host's clock as before) and ``LifeService`` passes
the world's (``_world_clock()()``), or her local world time where the decision
is about her day.

Every test here puts the host's clock more than four years away from the
world's (:data:`HOST`, in every ``aura_life`` module, by :func:`far_host`):

* section 1 -- each engine decides by the instant it is given, not the host's;
* section 2 -- ``LifeService`` hands each one the world's instant on its tick
  path (a spy on the engine's method records the ``now`` it was called with);
* section 3 -- what she lives through, end to end, on the service's ticks.
"""

import importlib
import pkgutil
import random
from datetime import datetime, timedelta

import pytest

import aura_life
from aura_life import hooks
from aura_life.emotion.appraisal import SUCCESS
from aura_life.life_service import LifeService
from aura_life.models import (
    ActivityLog, Anniversary, Anticipation, AvoidanceItem, Goal, GoalTimeframe, InnerMonologueEntry,
    RelationshipArc, SocialConflict, SocialEvent, SocialObligation,
)
from aura_life.world import WorldEnvironment

from conftest import HostClock

#: The world's instant: Tuesday 2026-10-06, 14:00.
WORLD = datetime(2026, 10, 6, 14, 0)
#: The host's clock, more than four years on, at 03:00.
HOST = datetime(2031, 3, 3, 3, 0)


class ScriptedClock:
    """The world's clock: moves only when told to."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant


def _aura_life_modules():
    for info in pkgutil.walk_packages(aura_life.__path__, "aura_life."):
        yield importlib.import_module(info.name)


@pytest.fixture
def far_host(monkeypatch) -> datetime:
    """The host's clock at :data:`HOST` in every aura_life module that reads
    ``datetime`` (its module attribute), for this test only."""
    monkeypatch.setattr(HostClock, "instant", HOST)
    for module in _aura_life_modules():
        if getattr(module, "datetime", None) is datetime:
            monkeypatch.setattr(module, "datetime", HostClock)
    return HOST


@pytest.fixture
def world():
    """Her local clock (the ``persona_now`` hook) and her world's on
    :data:`WORLD`; the previous provider is put back afterwards."""
    saved = hooks.provider_for("persona_now")
    clock = ScriptedClock(WORLD)
    hooks.configure(persona_now=lambda timezone=None: clock.instant)
    yield clock
    hooks.configure(persona_now=saved)


#: Her people (tests/test_social_api.py's form).
CIRCLE = [{"name": "Maya", "relationship": "best friend", "shared_interests": "climbing, ramen"},
          {"name": "Jo", "relationship": "coworker"}]


def _service(tmp_path, clock, name="w", seed=7, **kwargs) -> LifeService:
    kwargs.setdefault("social_circle", CIRCLE)
    return LifeService(db_path=str(tmp_path / f"{name}.db"), persona_id=name,
                       world_environment=WorldEnvironment(now=clock, seed=seed), rng=random.Random(seed), **kwargs)


class _Always:
    """An engine stream whose roll always passes and takes the first choice."""

    def random(self) -> float:
        return 0.0

    def choice(self, seq):
        return list(seq)[0]

    def choices(self, seq, weights=None, k=1):
        return [list(seq)[0]] * k

    def uniform(self, a, b):
        return a


# ----------------------------------------------------------------------
# 1. Each engine decides by the instant it is given
# ----------------------------------------------------------------------

def test_a_relationship_arc_cools_after_a_week_of_the_world_s_days(tmp_path, world, far_host):
    social = _service(tmp_path, world)._social
    social._arcs = {"Maya": RelationshipArc(npc_name="Maya", last_meaningful_interaction=WORLD - timedelta(days=1)),
                    "Jo": RelationshipArc(npc_name="Jo", last_meaningful_interaction=WORLD - timedelta(days=8))}
    social.tick_arcs(now=WORLD)
    assert (social._arcs["Maya"].trend, social._arcs["Jo"].trend) == ("stable", "cooling")
    social.update_arc("Maya", now=WORLD)
    assert social._arcs["Maya"].last_meaningful_interaction == WORLD


def test_an_obligation_is_overdue_past_its_deadline_on_the_world_clock(tmp_path, world, far_host):
    social = _service(tmp_path, world)._social
    social._obligations = [SocialObligation(description="call back", deadline=WORLD + timedelta(days=1)),
                           SocialObligation(description="return the book", deadline=WORLD - timedelta(hours=1))]
    social.tick_obligations(now=WORLD)
    assert [o.overdue for o in social._obligations] == [False, True]
    social.add_obligation("help moving", "Jo", now=WORLD)
    plan = social.add_plan(["Maya"], "coffee", WORLD + timedelta(hours=2), 60, now=WORLD)
    assert social._obligations[-2].created_at == plan.created_at == WORLD


def test_a_resolved_conflict_is_kept_three_of_the_world_s_days(tmp_path, world, far_host):
    social = _service(tmp_path, world)._social
    social._conflicts = [
        SocialConflict(parties=["Jo"], cause="the rent", status="resolved", resolved_at=WORLD - timedelta(days=1)),
        SocialConflict(parties=["Jo"], cause="the dishes", status="resolved", resolved_at=WORLD - timedelta(days=4))]
    social.tick_conflicts(now=WORLD)
    assert [c.cause for c in social._conflicts] == ["the rent"]
    social.trigger_conflict(["Maya"], "the plan", now=WORLD)
    social.resolve_conflict("the plan", now=WORLD)
    assert social._conflicts[-1].created_at == social._conflicts[-1].resolved_at == WORLD


def test_an_npc_s_contact_cooldown_runs_on_the_world_clock(tmp_path, world, far_host):
    social = _service(tmp_path, world)._social
    social._rng = _Always()
    name = sorted(social._npcs)[0]
    social._npcs = {name: social._npcs[name]}
    social._last_contact = {name: WORLD - timedelta(minutes=1)}
    assert social.tick(now=WORLD) is None  # contacted a minute ago, by the world's clock
    social._last_contact = {}
    event = social.tick(now=WORLD)
    assert event is not None and event.timestamp == WORLD and social._last_contact[name] == WORLD


def _goals(tmp_path, world):
    engine = _service(tmp_path, world)._goal_engine
    engine._active_goals, engine._abandoned_goals, engine._goalless_since = [], [], None
    return engine


def test_a_goal_stalls_by_the_world_s_hours_and_the_goalless_spell_with_it(tmp_path, world, far_host):
    engine = _goals(tmp_path, world)
    goal = Goal(title="Learn the bass", timeframe=GoalTimeframe.WEEKLY, created_at=WORLD - timedelta(hours=1))
    goal.motivation_level = 0.7
    engine._active_goals = [goal]
    assert engine.evaluate_motivation(now=WORLD) == []
    assert goal.motivation_level == pytest.approx(0.71)  # not stagnant: it recovers
    engine._active_goals = []
    engine._goalless_since = WORLD - timedelta(hours=1)
    assert engine.goalless_hours(WORLD) == pytest.approx(1.0)
    assert engine.get_emotional_context(now=WORLD) == "You recently let go of a goal and feel a bit adrift."
    assert engine.get_status(now=WORLD)["goalless_hours"] == 1.0
    assert engine.export_state(now=WORLD)["emotional_context"].startswith("You recently let go")


def test_her_day_s_goal_is_for_the_world_s_day_and_ends_with_it(tmp_path, world, far_host):
    engine = _goals(tmp_path, world)
    goal = engine.generate_daily_goal(now=WORLD)
    assert goal is not None and goal.created_at == WORLD
    assert goal.target_date == datetime(2026, 10, 6, 23, 59, 59, 999999)
    assert engine.generate_daily_goal(now=WORLD + timedelta(hours=2)) is None  # one a day
    goal.progress = 0.5
    assert engine.check_goal_completion(now=WORLD) == [] and goal in engine._active_goals
    assert engine.check_goal_completion(now=WORLD + timedelta(days=1)) == [goal] and goal.completed_at == WORLD + timedelta(days=1)


def test_a_goal_given_up_waits_the_world_s_days(tmp_path, world, far_host):
    engine = _goals(tmp_path, world)
    engine._rng = _Always()
    template = engine._setting.personality_goals[0]
    given_up = Goal(title=template["title"], timeframe=GoalTimeframe.WEEKLY)
    given_up.abandoned_at = WORLD - timedelta(days=1)
    engine._abandoned_goals = [given_up]
    activity = (template.get("related_activities") or ["reading"])[0]
    assert engine.generate_goal_from_activity(ActivityLog(activity_name=activity), now=WORLD) is None
    assert template["title"] not in {g.title for g in [engine._pick_up_new_goal(now=WORLD)] if g}
    recent = engine.get_emotional_context(now=WORLD + timedelta(hours=1))
    assert recent == "" or "gave up" in recent or "adrift" in recent
    engine.load_goals([], now=WORLD)
    assert engine._goalless_since == WORLD


def test_progress_and_its_end_are_stamped_on_the_world_clock(tmp_path, world, far_host):
    engine = _goals(tmp_path, world)
    goal = Goal(title="Finish the novel", timeframe=GoalTimeframe.DAILY, related_activities=["writing"],
                created_at=WORLD)
    engine._active_goals = [goal]
    engine.update_progress_from_activity(ActivityLog(activity_name="writing"), now=WORLD)
    assert goal.last_progress_at == WORLD
    engine.update_progress_from_activity(ActivityLog(activity_name="writing"), now=WORLD)
    assert goal.completed_at == WORLD
    other = Goal(title="Run", timeframe=GoalTimeframe.WEEKLY)
    engine._abandon_goal(other, "life got busy", now=WORLD)
    assert other.abandoned_at == WORLD


def test_a_passing_thought_is_fresh_for_ten_of_the_world_s_minutes(tmp_path, world, far_host):
    cognitive = _service(tmp_path, world)._cognitive
    cognitive._rng = _Always()
    cognitive.tick("reading", stress_level=0.1, sleep_quality=0.8, hunger=0.1, now=WORLD)
    assert cognitive._monologue.timestamp == WORLD and cognitive._monologue.thought
    assert cognitive.get_inner_monologue(now=WORLD + timedelta(minutes=5)) == cognitive._monologue.thought
    assert cognitive.get_inner_monologue(now=WORLD + timedelta(minutes=11)) is None


def test_a_persisted_emotion_decays_by_the_world_s_hours(tmp_path, world, far_host):
    from aura_life.emotion.emotion_persistence import EmotionPersistence

    store = EmotionPersistence("w", db_path=tmp_path / "emotions.db")
    store.save_emotion("content", 0.8, caused_by="the walk", now=WORLD)
    assert store.get_current_emotions(now=WORLD + timedelta(hours=10)) == {"content": pytest.approx(0.7)}
    assert store.get_dominant_emotion(now=WORLD) == "content"
    assert "This is recent—the walk." in store.get_emotional_context(now=WORLD + timedelta(minutes=30))
    reloaded = EmotionPersistence("w", db_path=tmp_path / "emotions.db", now=WORLD + timedelta(hours=10))
    assert reloaded._emotions["content"].intensity == pytest.approx(0.7)


def test_her_emotions_status_is_read_at_the_instant_it_is_given(tmp_path, world, far_host):
    """``EmotionPersistence.get_status()``, a host's read, decays her emotions
    by the instant it is given, as the reads it is made of do (Task 19 fix
    round 1, M1). On the host's clock (four years on) the walk's contentment
    had decayed away -- and been deleted."""
    from aura_life.emotion.emotion_persistence import EmotionPersistence

    store = EmotionPersistence("w", db_path=tmp_path / "emotions.db")
    store.save_emotion("content", 0.8, caused_by="the walk", now=WORLD)
    assert store.get_status(now=WORLD + timedelta(hours=10)) == {
        "current_emotions": {"content": pytest.approx(0.7)}, "dominant": "content", "emotion_count": 1}
    assert "content" in store._emotions


def test_an_ailment_and_a_workout_are_timed_on_the_world_clock(tmp_path, world, far_host):
    body = _service(tmp_path, world)._body
    body._rng = _Always()
    body._health.active_conditions = []
    body.on_new_day(now=WORLD)
    assert body._health.active_conditions[0]["started_at"] == WORLD.isoformat()
    from aura_life.body.body_system import CARDIO_ACTIVITIES

    body.on_activity(sorted(CARDIO_ACTIVITIES)[0], now=WORLD - timedelta(days=1))
    cardio = body._fitness.cardio
    body.tick("reading", "clear", hours_awake=2.0, stress_level=0.1, now=WORLD)
    assert len(body._health.active_conditions) == 1 and body._fitness.cardio == cardio
    body.on_substance_activity("having a beer", now=WORLD)
    assert body._inebriation.started_at == body._inebriation.last_drink_at == WORLD


def test_the_chaos_cap_is_per_world_day(tmp_path, world, far_host):
    chaos = _service(tmp_path, world)._chaos
    chaos._last_date, chaos._events_today = "2026-10-06", [{}] * 5
    assert chaos.roll("reading", energy=0.8, regulation=0.7, now=WORLD) is None
    assert len(chaos._events_today) == 5  # the same day: not reset


def test_an_anniversary_is_upcoming_in_the_world_s_week(tmp_path, world, far_host):
    continuity = _service(tmp_path, world)._continuity
    continuity._anniversaries = [Anniversary(name="moving in", date="10-09"), Anniversary(name="first job", date="03-05")]
    assert [a.name for a in continuity.get_upcoming_anniversaries(7, now=WORLD)] == ["moving in"]
    assert continuity.export_state(now=WORLD)["upcoming_anniversaries"] == [{"name": "moving in", "date": "10-09"}]


def test_an_avoidance_is_overdue_on_the_world_clock(tmp_path, world, far_host):
    drive = _service(tmp_path, world)._drive
    drive._avoidances = [AvoidanceItem(description="call the dentist", deadline=WORLD + timedelta(days=2))]
    drive.tick(now=WORLD)
    first = drive._avoidances[0].guilt_accumulated
    drive._avoidances = [AvoidanceItem(description="call the dentist", deadline=WORLD - timedelta(days=2))]
    drive.tick(now=WORLD)
    assert drive._avoidances[0].guilt_accumulated == pytest.approx(first + 0.01)


def test_frustration_waits_a_world_day_without_release(tmp_path, world, far_host):
    from aura_life.models import TimeOfDay, Weather

    desire = _service(tmp_path, world)._desire_system

    def after(last_release):
        desire._state.arousal, desire._state.frustration, desire._state.last_release = 0.9, 0.0, last_release
        desire.tick(TimeOfDay.AFTERNOON, Weather.SUNNY, now=WORLD)
        return desire._state.frustration

    assert after(WORLD - timedelta(hours=25)) - after(WORLD - timedelta(hours=1)) == pytest.approx(0.02)


def test_an_anticipation_is_live_until_its_world_date(tmp_path, world, far_host):
    memory_time = _service(tmp_path, world)._memory_time
    memory_time._anticipations = [Anticipation(event="the gig", date=WORLD + timedelta(days=1)),
                                  Anticipation(event="the exam", date=WORLD - timedelta(hours=1))]
    assert [a.event for a in memory_time.get_anticipations(now=WORLD)] == ["the gig"]


# ----------------------------------------------------------------------
# 2. LifeService hands each engine the world's instant
# ----------------------------------------------------------------------

def _spy(monkeypatch, engine, name: str) -> list:
    """Record the ``now`` each call of ``engine.name`` gets."""
    seen = []
    original = getattr(engine, name)

    def spy(*args, **kwargs):
        seen.append(kwargs.get("now"))
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, name, spy)
    return seen


ENERGY_TICK = [("_social", "tick_arcs"), ("_social", "tick_obligations"), ("_social", "tick_conflicts"),
               ("_drive", "tick"), ("_body", "tick"), ("_cognitive", "tick"), ("_desire_system", "tick"),
               ("_memory_time", "get_anticipations")]
GOAL_TICK = [("_goal_engine", "generate_daily_goal"), ("_goal_engine", "check_goal_completion"),
             ("_goal_engine", "evaluate_motivation")]
ACTIVITY_TICK = [("_social", "tick"), ("_chaos", "roll"), ("_body", "on_activity")]


@pytest.mark.parametrize("tick,engine,method", [("_on_energy_tick", *c) for c in ENERGY_TICK]
                         + [("_on_goal_tick", *c) for c in GOAL_TICK]
                         + [("_on_activity_tick", *c) for c in ACTIVITY_TICK],
                         ids=lambda v: v if isinstance(v, str) else "")
def test_her_ticks_hand_each_engine_the_world_s_instant(tmp_path, world, far_host, monkeypatch, tick, engine, method):
    svc = _service(tmp_path, world)
    svc._on_plan_tick()
    seen = _spy(monkeypatch, getattr(svc, engine), method)
    getattr(svc, tick)()
    assert seen and all(now == WORLD for now in seen), seen


@pytest.mark.parametrize("read,engine,method", [
    (lambda svc: svc.export_inner_state(), "_goal_engine", "export_state"),
    (lambda svc: svc.export_inner_state(), "_memory_time", "export_state"),
    (lambda svc: svc.export_inner_state(), "_continuity", "export_state"),
    (lambda svc: svc.get_status(), "_goal_engine", "get_status"),
    (lambda svc: svc.get_life_context(), "_goal_engine", "get_emotional_context"),
    (lambda svc: svc.get_life_context(), "_continuity", "export_state"),
], ids=["inner-goals", "inner-memory_time", "inner-continuity", "status-goals", "context-goals",
        "context-continuity"])
def test_what_she_reads_out_is_on_the_world_s_instant(tmp_path, world, far_host, monkeypatch, read, engine, method):
    svc = _service(tmp_path, world)
    svc._on_plan_tick()
    seen = _spy(monkeypatch, getattr(svc, engine), method)
    read(svc)
    assert seen and all(now == WORLD for now in seen), seen


def test_a_social_plan_is_made_at_the_world_s_instant(tmp_path, world, far_host):
    svc = _service(tmp_path, world)
    name = sorted(svc._social._npcs)[0]
    svc.add_social_plan([name], "coffee", WORLD + timedelta(hours=2), 60)
    plan = [o for o in svc._social._obligations if o.duration_min][-1]
    assert plan.created_at == WORLD


class _Host:
    """A host's follow-up manager: takes every trigger."""

    def create_trigger(self, *args, **kwargs):
        pass


def _company(svc):
    """Maya's company in an activity she joined (a housemate's)."""
    from aura_life.social.household import JointSide

    svc._on_housemate_company(JointSide(with_name="Maya", npc_names=("Maya",), line=""), "cooking a meal")


def _contact(svc):
    """Maya calls while she reads."""
    svc._on_social_event(SocialEvent(npc_name="Maya", event_type="call", description="Maya called", valence=1.0),
                         ActivityLog(activity_name="reading"), "reading")


def _triggers(svc):
    """Her proactive triggers are weighed (a host takes them), with a goal of
    hers to feel something about."""
    svc._on_plan_tick()
    svc._goal_engine._active_goals.append(Goal(title="Learn the bass", timeframe=GoalTimeframe.WEEKLY,
                                               created_at=WORLD))
    svc._follow_up_provider = lambda persona_id: _Host()
    svc._evaluate_life_triggers()


def _intimacy(svc):
    """Her activity tick, at an hour that allows it, finds her wanting to."""
    svc._on_plan_tick()
    svc._daily_planner.is_commitment = lambda slot: False
    svc._desire_system._state.arousal = 1.0
    svc._desire_system.should_do_intimate_activity = lambda *args, **kwargs: True
    svc._on_activity_tick()


def _activity(svc):
    """She reads, and it goes well (a step for her goals)."""
    engine = svc._activity_engine
    real = engine.roll_outcome
    engine.roll_outcome = lambda activity, **kwargs: (SUCCESS, real(activity, **kwargs)[1])
    svc._perform_activity(engine.get_activity("reading"), None)


#: Each hand-over of the world's instant outside the three ticks above (Task
#: 19 fix round 1, I1): what LifeService does, the engine and its method.
HAND_OVERS = [
    (_company, "_social", "update_arc"),
    (_contact, "_social", "update_arc"),
    (lambda svc: svc._on_plan_tick(), "_body", "on_new_day"),  # her first plan: a new day
    (_triggers, "_cognitive", "get_inner_monologue"),
    (_triggers, "_goal_engine", "get_emotional_context"),
    (_intimacy, "_desire_system", "execute_intimate_activity"),
    (_activity, "_goal_engine", "update_progress_from_activity"),
    (_activity, "_goal_engine", "generate_goal_from_activity"),
    (lambda svc: svc._load_state(), "_goal_engine", "load_goals"),
]


@pytest.mark.parametrize("act,engine,method", HAND_OVERS,
                         ids=["company-arc", "contact-arc", "new_day-body", "triggers-monologue", "triggers-goals",
                              "intimacy-desire", "activity-progress", "activity-new_goal", "reload-goals"])
def test_what_she_lives_through_hands_each_engine_the_world_s_instant(tmp_path, world, far_host, monkeypatch,
                                                                       act, engine, method):
    svc = _service(tmp_path, world)
    seen = _spy(monkeypatch, getattr(svc, engine), method)
    act(svc)
    assert seen and all(now == WORLD for now in seen), seen


@pytest.mark.parametrize("engine,method,activity", [
    ("_body", "on_activity", "reading"),
    ("_body", "on_substance_activity", "having a pint"),
    ("_goal_engine", "update_progress_from_activity", "reading"),
], ids=["workout-body", "drink-body", "progress-goals"])
def test_a_catch_up_hands_her_body_and_her_goals_the_instant_of_what_it_backfills(tmp_path, world, far_host,
                                                                                   monkeypatch, engine, method,
                                                                                   activity):
    """Ruling T19a-R1: an activity the catch-up backfills stamps her last
    workout, her drink and her goal's last progress with its own backdated
    instant, as it already stamps her money, work, meals and errands -- the
    reads that age those stamps (her fitness, how drunk she still is, her
    motivation) are on the world's clock: a stamp from the host's read as
    years old or years ahead, and a drink of five hours ago as one just had."""
    backfilled = WORLD - timedelta(hours=5)
    svc = _service(tmp_path, world)
    seen = _spy(monkeypatch, getattr(svc, engine), method)
    svc._tick_engines_for_catchup(activity, backfilled, "clear", "autumn")
    assert seen == [backfilled], seen


def test_an_activity_s_emotions_are_persisted_at_the_world_s_instant(tmp_path, world, far_host, monkeypatch):
    """What an activity made her feel is saved (EmotionPersistence, for her
    multi-day arcs) stamped with the world's instant, which their reads decay
    them by (Task 19 fix round 1, I1)."""
    from aura_life.emotion import emotion_persistence

    seen = []

    class _Store:
        def save_emotion(self, **kwargs):
            seen.append(kwargs.get("now"))

    monkeypatch.setattr(emotion_persistence, "get_emotion_persistence",
                        lambda persona_id, datastore=None, **kwargs: seen.append(kwargs.get("now")) or _Store())
    _service(tmp_path, world)._persist_activity_emotions("reading", {"content": 0.5, "calm": 0.3})
    assert seen == [WORLD, WORLD, WORLD]


# ----------------------------------------------------------------------
# 3. What she lives through, on the service's ticks
# ----------------------------------------------------------------------

def test_her_people_and_her_body_keep_the_world_s_time_across_an_energy_tick(tmp_path, world, far_host):
    """A friend seen yesterday, a debt due tomorrow, a quarrel made up
    yesterday, a cold since an hour ago, a run yesterday: on the world's clock
    none has changed by her next energy tick. On the host's (four years on)
    the arc cooled, the debt was overdue, the quarrel was forgotten, the cold
    was over and her fitness waned."""
    svc = _service(tmp_path, world)
    svc._on_plan_tick()
    social, body = svc._social, svc._body
    social._arcs["Maya"] = RelationshipArc(npc_name="Maya", last_meaningful_interaction=WORLD - timedelta(days=1))
    social._obligations.append(SocialObligation(description="call back", deadline=WORLD + timedelta(days=1)))
    social._conflicts = [SocialConflict(parties=["Maya"], cause="the rent", status="resolved",
                                        resolved_at=WORLD - timedelta(days=1))]
    body._health.active_conditions = [{"name": "a cold", "severity": 0.1, "duration_hours": 6,
                                       "started_at": (WORLD - timedelta(hours=1)).isoformat()}]
    body._fitness.last_cardio_session = WORLD - timedelta(days=1)
    cardio = body._fitness.cardio
    svc._on_energy_tick()
    assert social._arcs["Maya"].trend != "cooling"
    assert not social._obligations[-1].overdue
    assert [c.cause for c in social._conflicts] == ["the rent"]
    assert [c["name"] for c in body._health.active_conditions] == ["a cold"]
    assert body._fitness.cardio == cardio


def test_her_goals_keep_the_world_s_day_across_a_goal_tick(tmp_path, world, far_host):
    """Her day's goal is made for the world's day and still hers at its 14:00;
    a goal due tomorrow is looked forward to. On the host's clock the goal
    was for another day and the one due tomorrow was years past."""
    svc = _service(tmp_path, world)
    engine = svc._goal_engine
    engine._active_goals = [g for g in engine._active_goals if g.timeframe != GoalTimeframe.DAILY]
    engine._last_daily_generation = None
    due = Goal(title="Send the demo", timeframe=GoalTimeframe.WEEKLY, created_at=WORLD,
               target_date=WORLD + timedelta(days=1))
    engine._active_goals.append(due)
    svc._on_goal_tick()
    daily = [g for g in engine._active_goals if g.timeframe == GoalTimeframe.DAILY]
    assert daily and daily[0].created_at == WORLD and daily[0].target_date.date() == WORLD.date()
    assert "Send the demo" in [a.event for a in svc._memory_time._anticipations]


def test_a_place_s_visit_counts_for_her_world_day(tmp_path, world, far_host):
    svc = _service(tmp_path, world)
    svc._apply_location_effects("park")
    assert svc._location._visited_today_date == "2026-10-06"


def test_the_trip_s_return_is_checked_on_the_world_clock(tmp_path, world, far_host, monkeypatch):
    svc = _service(tmp_path, world)
    seen = []
    monkeypatch.setattr(svc, "_update_trip", lambda _now=None, _rng=None: seen.append(_now))
    svc._on_world_tick()
    assert seen == [WORLD]


@pytest.mark.parametrize("returns_in,still_away", [(timedelta(days=1), True), (timedelta(hours=-1), False)],
                         ids=["due_tomorrow_on_the_world_clock", "overdue_on_the_world_clock"])
def test_a_reload_ends_her_trip_only_when_the_world_s_clock_says_she_is_back(tmp_path, world, far_host,
                                                                             returns_in, still_away):
    """_load_place_state's catch-up compares the trip's return with the
    world's instant, as _update_trip stamps it (moved by Task 19a with its
    pair; ruling T19b-R7a). The host's clock is years past both returns: on
    it, every trip would be over at the reload."""
    svc = _service(tmp_path, world, name="trip")
    svc._place_location.on_trip = True
    svc._place_location.trip_destination = "the coast"
    svc._place_location.trip_returns_at = (WORLD + returns_in).isoformat()
    svc._save_place_state()
    reloaded = _service(tmp_path, world, name="trip")
    reloaded._load_state()
    assert reloaded._place_location.on_trip is still_away
    assert (reloaded._place_location.trip_destination == "the coast") is still_away
