"""Task 1 of the aura-humanness program: ten small, independent crash and
correctness bugs, fixed before the larger humanness work starts. One test (or
a small group) per item; each targets the exact defect named in the brief
rather than the surrounding machinery.
"""

import logging
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta

import pytest

from aura_life.affect.affect_system import AFFECT_CONVERSATION_TRIGGERS
from aura_life.identity.identity_system import IdentitySystem
from aura_life.life_service import CONVERSATION_KEYWORD_MAP, LifeService
from aura_life.models import ActivityCategory, DailyPlan, NPC, PlannedSlot, SocialEvent
from aura_life.personas.profile_parser import ParsedProfile, ProfileParser
from aura_life.shadow.shadow_system import ShadowSystem


def _errors(caplog):
    """Every ERROR-or-worse record captured so far (see test_multi_instance.py)."""
    return [f"{r.name}: {r.getMessage()}" for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------------------
# 1. NPC value-alignment loop iterated dict keys (str), not NPC objects.
# ---------------------------------------------------------------------------

def test_activity_tick_with_social_event_and_circle_has_no_error(tmp_path, caplog, monkeypatch):
    """`_social._npcs` is a Dict[str, NPC]; iterating it yielded names, and
    `n.name` on a str raised AttributeError on every social event -- silently,
    since the scheduler's tick wrapper only logs it.

    The world is pinned to an afternoon: a new persona starts on her own sleep
    schedule, so on the wall clock this test would find her asleep -- and her
    activity tick idle -- whenever the suite ran at night."""
    from aura_life.world import WorldEnvironment

    caplog.set_level(logging.WARNING)
    svc = LifeService(
        db_path=str(tmp_path / "life1.db"),
        persona_id="p1",
        occupation="baker",
        social_circle=[{"name": "Shirley", "relationship": "friend"}],
        world_environment=WorldEnvironment(now=lambda: datetime(2026, 3, 11, 14, 0)),
    )
    fixed_event = SocialEvent(
        npc_name="Shirley", event_type="text_received",
        description="Shirley texted about the weekend",
    )
    monkeypatch.setattr(svc._social, "tick", lambda *args, **kw: fixed_event)

    # Spy on the value-alignment call itself: a wrong "fix" that merely
    # swallows the AttributeError (never actually finding the NPC) would
    # still pass a no-ERROR-record check, but would never reach this call.
    calls = []
    real_alignment = svc._identity.get_npc_value_alignment

    def _spy_alignment(npc):
        calls.append(npc)
        return real_alignment(npc)

    monkeypatch.setattr(svc._identity, "get_npc_value_alignment", _spy_alignment)

    svc._scheduler.force_tick("activity")

    assert _errors(caplog) == []
    assert len(calls) == 1
    assert calls[0].name == "Shirley"


# ---------------------------------------------------------------------------
# 2. Catch-up category mapping returned ActivityCategory.PHYSICAL, which does
#    not exist on the enum -- AttributeError on every physical catch-up slot.
# ---------------------------------------------------------------------------

def test_categorize_activity_maps_physical_group_without_crashing(tmp_path):
    svc = LifeService(db_path=str(tmp_path / "life2.db"), persona_id="p2", occupation="baker")
    for name in ("going for a run", "yoga", "gym workout", "gentle_walk"):
        category = svc._categorize_activity(name)
        assert isinstance(category, ActivityCategory)
    # Each activity's own category (main's released 0.5.0 fix wins over the branch's one-mapping choice): yoga REST.
    assert svc._categorize_activity("yoga") == ActivityCategory.REST
    assert svc._categorize_activity("going for a run") == ActivityCategory.EXPLORATION


def test_catch_up_over_a_gap_with_a_physical_slot_completes(tmp_path):
    """The acceptance scenario end-to-end: a downtime catch-up whose planned
    slots include a physical activity must not crash."""
    svc = LifeService(db_path=str(tmp_path / "life2b.db"), persona_id="p2b", occupation="baker")
    # AI personas skip the sleep-hour activity override, so the physical slot
    # below survives untouched regardless of what hour it lands on.
    svc._is_ai = True

    def _fake_plan(*args, **kwargs):
        return DailyPlan(
            date="2000-01-01",
            slots=[PlannedSlot(hour=h, activity_name="yoga", location="home") for h in range(24)],
        )

    svc._daily_planner.generate_daily_plan = _fake_plan

    # 24h exactly: `days_to_plan` covers gap_start's day and the next, and a
    # full day always covers `now` (it is gap_start + exactly one day).
    result = svc.catch_up_from_downtime(24.0)

    assert result["activities_generated"] > 0
    assert "yoga" in result["activities"]


# ---------------------------------------------------------------------------
# 3. "persona type" matched "ai" as a substring, not a whole normalised value.
# ---------------------------------------------------------------------------

def test_persona_type_requires_an_exact_match_not_a_substring():
    cases = [
        ("Human (Haitian)", "human"),      # contains "ai" in "Hai..."
        ("human, trained sailor", "human"),  # contains "ai" in "tr-ai-ned"
        ("AI", "ai"),
        ("a.i.", "ai"),
        ("artificial intelligence", "ai"),
    ]
    for value, expected in cases:
        profile = ParsedProfile()
        ProfileParser._parse_basic_info(f"Persona Type: {value}", profile)
        assert profile.persona_type == expected, value


# ---------------------------------------------------------------------------
# 4. Planner day-chaos seeds used the built-in hash(), randomised per process.
# ---------------------------------------------------------------------------

_SEED_CAPTURE_SCRIPT = textwrap.dedent(
    """
    import random

    _captured = {}
    _orig_init = random.Random.__init__

    def _spy_init(self, seed=None):
        _captured["seed"] = seed
        _orig_init(self, seed)

    random.Random.__init__ = _spy_init

    from aura_life.planner.daily_planner import DailyPlanner

    planner = DailyPlanner(occupation="engineer", nationality="")
    planner._roll_day_chaos("2026-09-25", 2)  # Wednesday: a workday for OCC_STANDARD
    print(_captured["seed"])
    """
)


def _run_seed_subprocess() -> str:
    result = subprocess.run(
        [sys.executable, "-c", _SEED_CAPTURE_SCRIPT],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_planner_seed_for_a_fixed_date_is_equal_across_subprocesses():
    """`hash(str)` is salted per-process; two subprocesses almost certainly
    disagreed on it. `zlib.crc32` has no process-dependent state."""
    first = _run_seed_subprocess()
    second = _run_seed_subprocess()
    assert first != ""
    assert first == second

    # Not just equal across processes -- equal to the documented formula
    # itself, for the exact date + occupation key `_roll_day_chaos` seeds
    # with ("2026-09-25" + "engineer", per `_SEED_CAPTURE_SCRIPT` above).
    import zlib
    expected = zlib.crc32("2026-09-25engineer".encode("utf-8"))
    assert int(first) == expected


# ---------------------------------------------------------------------------
# 5. Shadow confession matched filler cues ("honestly", "truth is", "to be
#    honest") that appear in ordinary sentences, clearing secrets on a false
#    trigger. The explicit cues ("i have to tell you", "i lied", "confess")
#    must keep working.
# ---------------------------------------------------------------------------

def test_filler_honesty_cue_no_longer_clears_secrets_but_explicit_cues_still_do():
    shadow = ShadowSystem()
    shadow.add_secret("something she is hiding")

    # All three dropped filler cues are ordinary sentences with no confession
    # in them; none may clear the secret.
    for message in ("honestly I'm tired", "the truth is I'm tired", "to be honest, I'm tired"):
        shadow.on_user_message(message)
        assert shadow._state.secrets == ["something she is hiding"], message

    # The explicit cues still work.
    shadow.on_user_message("i lied about it")
    assert shadow._state.secrets == []

    shadow.add_secret("another one")
    shadow.on_user_message("I need to confess something")
    assert shadow._state.secrets == []


# ---------------------------------------------------------------------------
# 8. The intrusive-pull pick always returned pool[0] -- never rotated despite
#    its own docstring's claim. Must rotate least-recently-used, and persist.
# ---------------------------------------------------------------------------

def test_intrusive_pull_rotates_and_the_rotation_survives_a_reload():
    shadow = ShadowSystem(intrusive_thought_themes=["betrayal", "escape", "rage"])

    picks = [shadow._pick_intrusive_theme() for _ in range(5)]
    assert set(picks) == {"betrayal", "escape", "rage"}
    for a, b in zip(picks, picks[1:]):
        assert a != b, picks

    # Persistence: a reload continues the rotation instead of restarting it.
    # 5 picks consumed indices 0-4 (betrayal, escape, rage, betrayal, escape);
    # the next one, index 5, is pool[5 % 3] == "rage".
    restored = ShadowSystem.from_dict(shadow.to_dict())
    assert restored._pick_intrusive_theme() == "rage"


# ---------------------------------------------------------------------------
# 6. Conversation-derived goals/wants were built from a random long word of
#    the user's message. The whole mechanism is deleted.
# ---------------------------------------------------------------------------

def test_no_conversation_derived_goal_or_want_from_a_random_word(tmp_path, monkeypatch):
    import random as random_module

    svc = LifeService(db_path=str(tmp_path / "life6.db"), persona_id="p6")
    # Force the old 10% branch, if anything like it still existed.
    monkeypatch.setattr(random_module, "random", lambda: 0.0)

    before_goals = list(svc._goal_engine.active_goals)
    before_desires = list(svc._daily_planner.all_desires)

    message = "I keep thinking about philosophy and consciousness and where it leads for us."
    assert len(message) >= 60

    svc.on_user_message(message)

    assert list(svc._goal_engine.active_goals) == before_goals
    assert list(svc._daily_planner.all_desires) == before_desires
    assert not hasattr(svc._goal_engine, "generate_goal_from_conversation")
    assert not hasattr(svc._daily_planner, "generate_desire_from_conversation")


# ---------------------------------------------------------------------------
# 7. Tendency thoughts could render a literal "{npc}" placeholder.
# ---------------------------------------------------------------------------

def test_tendency_thought_never_leaks_a_template_placeholder():
    # No one in the social circle: must fall back to a nameless variant.
    identity = IdentitySystem()
    identity._active_tendency = "gossip"
    for _ in range(30):
        thought = identity.get_active_tendency_thought()
        assert thought is not None
        assert "{" not in thought

    # A real NPC in the circle: the placeholder is filled, not left literal.
    identity = IdentitySystem(npcs=[NPC(name="Shirley", relationship="friend")])
    identity._active_tendency = "gossip"
    filled = [identity.get_active_tendency_thought() for _ in range(30)]
    assert all("{" not in t for t in filled)
    assert any("Shirley" in t for t in filled)


# ---------------------------------------------------------------------------
# 9. Disagreement cues applied healthy_debate's positive mood shift; a
#    contradiction is not, on its own, a positive event. "you're wrong" reads
#    as criticism instead. conflict_topic keeps its stress effect only.
# ---------------------------------------------------------------------------

_DISAGREEMENT_CUES = (
    "i disagree", "you're wrong", "no way", "don't you think",
    "but what about", "agree to disagree", "that's not",
)


def test_disagreement_cues_drop_healthy_debate_and_your_wrong_gets_criticism():
    for cue in _DISAGREEMENT_CUES:
        if cue == "you're wrong":
            continue
        engines = [engine for engine, _trigger in CONVERSATION_KEYWORD_MAP[cue]]
        assert "affect" not in engines, cue
        assert engines, cue  # kept its non-affect (cognitive/identity) effect

    triggers = dict(CONVERSATION_KEYWORD_MAP["you're wrong"])
    assert triggers["affect"] == "criticism"
    assert triggers["cognitive"] == "defending_opinion"


def test_conflict_topic_keeps_stress_effect_loses_positive_mood_shift():
    effects = AFFECT_CONVERSATION_TRIGGERS["conflict_topic"]
    assert effects.get("stress_add") == 0.05
    assert effects.get("mood_shift", 0.0) <= 0.0


def test_you_re_wrong_lowers_mood_no_way_does_not_raise_it(tmp_path):
    # Mood is a (valence, arousal) point now (tests/test_mood_model.py); the
    # retired "blue"/"raw" labels were how a lowered mood read before it.
    svc = LifeService(db_path=str(tmp_path / "life9.db"), persona_id="p9")
    assert svc._affect.mood.current_mood == "neutral"
    before = svc._affect.mood.valence

    svc.on_user_message("you're wrong")
    assert svc._affect.mood.valence < before

    # "no way" adds nothing to her mood: since Task 16a she appraises the
    # user's "amazing" (she is glad for them), so the control is the same
    # turn without the cue, not her mood before it.
    svc2 = LifeService(db_path=str(tmp_path / "life9b.db"), persona_id="p9b")
    svc2.on_user_message("no way, that's amazing")
    control = LifeService(db_path=str(tmp_path / "life9c.db"), persona_id="p9c")
    control.on_user_message("that's amazing")
    assert svc2._affect.mood.valence == control._affect.mood.valence
    assert svc2._affect.mood.current_mood == control._affect.mood.current_mood == "neutral"


# ---------------------------------------------------------------------------
# 10. Nothing persisted inner state on a tick; only stop()/reset/catch-up did.
#     A started service (one that has loaded its state) must save at most
#     once per simulated hour, on the world clock, so a restore after a crash
#     finds the state a fresh service wrote. A service that never loaded its
#     state must never let its own periodic save overwrite a row a *previous*
#     run's `start()` already wrote (the controller's binding ruling on the
#     review's Important finding: `_save_state()`'s energy write is a plain
#     `UPDATE ... WHERE id=1`, so it is only ever a no-op or a genuine
#     overwrite -- it can never "create" a row, but it can clobber one that
#     already exists if the service writing it never loaded its own state).
# ---------------------------------------------------------------------------

class _ScriptedClock:
    """A clock that advances only when told to (see tests/test_energy_clock.py)."""

    def __init__(self, start: datetime):
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, hours: float) -> None:
        self.instant += timedelta(hours=hours)


def _start_equivalent(svc: LifeService) -> None:
    """What `start()` does for state-loading, minus the background thread it
    also spawns (`force_all_ticks` on a daemon thread -- see
    `test_multi_instance.py`), which would race a test's own synchronous
    ticks on a scripted clock. Sets the same `_is_initialized` flag the new
    periodic-save gate checks."""
    svc._load_state()
    svc._goal_engine.initialize_goals()
    svc._is_initialized = True


def test_periodic_save_restores_state_written_during_the_first_hour(tmp_path):
    from aura_life.world import WorldEnvironment

    clock = _ScriptedClock(datetime(2026, 3, 14, 6, 0, 0))
    world = WorldEnvironment(now=clock)
    db_path = str(tmp_path / "life10.db")
    svc = LifeService(db_path=db_path, persona_id="p10", world_environment=world, occupation="baker")
    _start_equivalent(svc)  # a loaded, started service: the periodic save's gate is open

    clock.advance(1.0)
    svc._on_energy_tick()  # >= 1 simulated hour since construction: saves now

    clock.advance(1.0)
    svc._on_energy_tick()  # a second simulated hour of ticks, per the scenario

    level_after_two_hours = svc._energy.state.level
    assert level_after_two_hours != 0.7  # moved off the untouched constructor default

    restored = LifeService(
        db_path=db_path, persona_id="p10",
        world_environment=WorldEnvironment(now=clock), occupation="baker",
    )
    restored._load_state()  # the same read path a real restart would use
    assert restored._energy.state.level == pytest.approx(level_after_two_hours)


def test_periodic_save_is_gated_to_at_most_once_per_simulated_hour(tmp_path):
    clock = _ScriptedClock(datetime(2026, 3, 14, 6, 0, 0))
    from aura_life.world import WorldEnvironment

    world = WorldEnvironment(now=clock)
    svc = LifeService(
        db_path=str(tmp_path / "life10b.db"), persona_id="p10b",
        world_environment=world, occupation="baker",
    )
    _start_equivalent(svc)

    calls = []
    real_save_state = svc._save_state

    def _counting_save_state():
        calls.append(clock.instant)
        return real_save_state()

    svc._save_state = _counting_save_state

    clock.advance(0.1)
    svc._on_energy_tick()
    clock.advance(0.1)
    svc._on_energy_tick()
    clock.advance(0.1)
    svc._on_energy_tick()

    assert calls == []  # under an hour total: no periodic save fired yet

    clock.advance(1.0)
    svc._on_energy_tick()

    assert len(calls) == 1


def test_a_never_loaded_service_never_overwrites_a_loaded_ones_saved_state(tmp_path):
    """The controller's binding ruling on the review's Important finding.

    Service A loads, ticks an hour, and stops -- row 1 now holds A's
    non-default state. Service B, on the same db, is never started or
    loaded (`_is_initialized` stays False) and ticks across several
    simulated hours. B's own periodic save must never fire, so the row A
    wrote must still read back unchanged -- not overwritten with B's
    in-memory (fresh-default-seeded) state.
    """
    import sqlite3

    from aura_life.world import WorldEnvironment

    db_path = str(tmp_path / "life10c.db")

    clock_a = _ScriptedClock(datetime(2026, 3, 14, 6, 0, 0))
    svc_a = LifeService(
        db_path=db_path, persona_id="p10c",
        world_environment=WorldEnvironment(now=clock_a), occupation="baker",
    )
    _start_equivalent(svc_a)
    clock_a.advance(1.0)
    svc_a._on_energy_tick()
    saved_level = svc_a._energy.state.level
    assert saved_level != 0.7
    svc_a.stop()  # the existing, unconditional explicit save -- not this task's gate

    # Service B: same db, never loaded/started.
    clock_b = _ScriptedClock(datetime(2026, 3, 14, 6, 0, 0))
    svc_b = LifeService(
        db_path=db_path, persona_id="p10c",
        world_environment=WorldEnvironment(now=clock_b), occupation="baker",
    )
    assert svc_b._is_initialized is False

    for _ in range(3):  # 3 simulated hours -- comfortably "2+"
        clock_b.advance(1.0)
        svc_b._on_energy_tick()

    # Read the row back directly -- not through svc_b, which never loaded it
    # and so has no idea what (if anything) is really on disk.
    con = sqlite3.connect(db_path)
    row = con.execute("SELECT level FROM life_energy_state WHERE id = 1").fetchone()
    con.close()
    assert row[0] == pytest.approx(saved_level)
