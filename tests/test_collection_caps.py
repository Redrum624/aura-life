"""Bounded-growth tests for the engine's in-memory collections.

Every collection here used to grow for the lifetime of the persona: each one is
also serialized into SQLite on save, so an unbounded list is both a memory leak
and an ever-growing DB row.  These tests pin the caps so a future append site
cannot quietly reintroduce the growth.

Also covers the teardown paths added alongside the caps (scheduler shutdown,
per-persona cache eviction), which exist to drop references rather than to
bound a list.
"""
from datetime import datetime

import pytest

from aura_life.affect.affect_system import AffectSystem
from aura_life.continuity.continuity_system import ContinuitySystem
from aura_life.goals.goal_engine import GoalEngine
from aura_life.models import DailyPlan, Goal, GoalTimeframe
from aura_life.planner.daily_planner import DailyPlanner
from aura_life.shadow.shadow_system import ShadowSystem


# ============= Bounded collections =============

def test_stress_sources_are_capped():
    """affect_system.on_stressor_added: per-tick callers push free-form strings
    ('avoiding: x', 'overdue: y') whose content rotates, and on_stressor_resolved
    is never called for them."""
    affect = AffectSystem()
    for i in range(200):
        affect.on_stressor_added(f"overdue: chore-{i}")
    assert len(affect._stress.sources) <= AffectSystem.MAX_STRESS_SOURCES
    # Newest kept, oldest dropped.
    assert "overdue: chore-199" in affect._stress.sources
    assert "overdue: chore-0" not in affect._stress.sources


def test_stress_sources_still_dedupe():
    affect = AffectSystem()
    for _ in range(5):
        affect.on_stressor_added("hunger")
    assert affect._stress.sources.count("hunger") == 1


def test_completed_and_abandoned_goals_are_capped():
    """goal_engine: readers only ever take the last 3/5/10."""
    engine = GoalEngine()
    for i in range(100):
        goal = Goal(title=f"goal-{i}", timeframe=GoalTimeframe.WEEKLY)
        engine._active_goals.append(goal)
        engine._complete_goal(goal)
        other = Goal(title=f"dropped-{i}", timeframe=GoalTimeframe.WEEKLY)
        engine._active_goals.append(other)
        engine._abandon_goal(other, "lost interest")
    assert len(engine.completed_goals) <= GoalEngine.MAX_GOAL_HISTORY
    assert len(engine.abandoned_goals) <= GoalEngine.MAX_GOAL_HISTORY
    assert engine.completed_goals[-1].title == "goal-99"
    assert engine.abandoned_goals[-1].title == "dropped-99"


def test_load_goals_caps_history_from_db():
    """A DB written before the cap existed must not reinflate the lists."""
    engine = GoalEngine()
    goals = []
    for i in range(100):
        done = Goal(title=f"done-{i}", timeframe=GoalTimeframe.WEEKLY)
        done.is_active = False
        done.completed_at = datetime.now()
        goals.append(done)
        gone = Goal(title=f"gone-{i}", timeframe=GoalTimeframe.WEEKLY)
        gone.is_active = False
        gone.abandoned_at = datetime.now()
        goals.append(gone)
    engine.load_goals(goals)
    assert len(engine.completed_goals) <= GoalEngine.MAX_GOAL_HISTORY
    assert len(engine.abandoned_goals) <= GoalEngine.MAX_GOAL_HISTORY


def test_anniversaries_are_capped():
    """continuity: siblings _growth_snapshots (20) and _life_chapters (12) are
    capped; _anniversaries was the outlier."""
    continuity = ContinuitySystem()
    for i in range(100):
        continuity.add_anniversary(f"event-{i}", "01-01")
    assert len(continuity._anniversaries) <= ContinuitySystem.MAX_ANNIVERSARIES
    assert continuity._anniversaries[-1].name == "event-99"


def test_anniversaries_still_dedupe_by_name():
    continuity = ContinuitySystem()
    for _ in range(5):
        continuity.add_anniversary("first message", "03-14")
    assert len(continuity._anniversaries) == 1


def test_secrets_are_capped():
    """shadow: only confess() shrinks secrets, and it is never called in-repo."""
    shadow = ShadowSystem()
    for i in range(100):
        shadow.add_secret(f"secret-{i}")
    assert len(shadow._state.secrets) <= ShadowSystem.MAX_SECRETS
    assert shadow._state.secrets[-1] == "secret-99"


def test_revision_notes_are_capped():
    """daily_planner: one note per user schedule command, all JSON-serialized
    into the life_daily_plan row."""
    planner = DailyPlanner()
    planner.load_state(DailyPlan(date="2026-08-27"), [])
    for i in range(100):
        planner.override_current_location(f"place-{i}")
    notes = planner._current_plan.revision_notes
    assert len(notes) <= DailyPlanner.MAX_REVISION_NOTES
    assert notes[-1] == "Moved to place-99"


# ============= Teardown paths =============

def test_scheduler_stop_drops_its_reference():
    """life_scheduler.stop() used to leave _scheduler pointing at the dead
    scheduler, keeping every job (and what it closes over) reachable."""
    from aura_life.scheduler.life_scheduler import LifeScheduler

    calls = []

    class _FakeScheduler:
        def shutdown(self, wait=True):
            calls.append(wait)

    scheduler = LifeScheduler(on_world_tick=lambda: None)
    scheduler._scheduler = _FakeScheduler()
    scheduler._is_running = True

    scheduler.stop()

    assert scheduler._scheduler is None
    assert scheduler.is_running is False
    assert calls == [True], "in-flight ticks must be waited on, not dropped"
    # Idempotent: a second stop must not raise or shut down again.
    scheduler.stop()
    assert calls == [True]


def test_remove_personality_stops_and_evicts():
    """personality_manager._instances only ever grew; each retained instance
    pins a LifeService and its scheduler jobs."""
    from aura_life.personas.personality_manager import (
        MultiPersonalityManager,
        PersonalityInstance,
    )

    stopped = []

    class _FakeLifeService:
        def stop(self):
            stopped.append(True)

    class _FakeDefinition:
        name = "Ada"

    manager = MultiPersonalityManager()
    manager._instances["ada"] = PersonalityInstance(
        definition=_FakeDefinition(),
        memory_service=object(),
        emotion_engine=object(),
        life_service=_FakeLifeService(),
    )
    manager.set_current("ada")

    assert manager.remove_personality("ADA") is True
    assert stopped == [True]
    assert manager.get_instance("ada") is None
    assert manager.current_id is None
    assert manager.get_current() is None
    assert manager.remove_personality("ada") is False


def test_manager_has_no_hardcoded_current_persona():
    """A fresh manager pointed at a persona nobody registered."""
    from aura_life.personas.personality_manager import MultiPersonalityManager

    manager = MultiPersonalityManager()
    assert manager.current_id is None
    assert manager.get_current() is None
    assert manager.current_name == "Unknown"


def test_persona_schedule_cache_can_be_cleared():
    """schedule._schedules is a process-global with no eviction."""
    from aura_life import schedule as schedule_mod

    schedule_mod.clear_persona_schedule()
    first = schedule_mod.get_persona_schedule("ada")
    assert schedule_mod.get_persona_schedule("ada") is first

    schedule_mod.get_persona_schedule("grace")
    assert schedule_mod.clear_persona_schedule("ada") is True
    assert schedule_mod.get_persona_schedule("ada") is not first
    assert schedule_mod.clear_persona_schedule("nobody") is False

    schedule_mod.clear_persona_schedule()
    assert schedule_mod._schedules == {}


# ============= Privacy contract enforcement =============

def test_device_location_is_coarsened_on_write(tmp_path):
    """device_location's stated precision floor must hold whatever the caller
    passes in, not only when the client remembered to fuzz."""
    from aura_life.location import device_location as dl

    store = tmp_path / ".device_location.json"
    dl.save_device_location(45.502736, -73.573992, path=store)
    got = dl.get_device_location(path=store)
    assert got["lat"] == round(45.502736, dl.STORED_PRECISION)
    assert got["lon"] == round(-73.573992, dl.STORED_PRECISION)


def test_device_location_rejects_out_of_range(tmp_path):
    from aura_life.location import device_location as dl

    store = tmp_path / ".device_location.json"
    dl.save_device_location(191.0, 0.0, path=store)
    assert dl.get_device_location(path=store) is None
    dl.save_device_location(0.0, -200.0, path=store)
    assert dl.get_device_location(path=store) is None


def test_device_location_never_logs_coordinates(tmp_path, caplog):
    """The module's whole reason to exist is that the point stays in one file."""
    from aura_life.location import device_location as dl

    store = tmp_path / ".device_location.json"
    with caplog.at_level(0):
        dl.save_device_location(45.51, -73.57, path=store)
    text = caplog.text
    assert "45.5" not in text and "73.5" not in text, text


def test_timezone_resolution_failure_does_not_log_coordinates(caplog):
    """place_service._resolve_tz_for_point fires whenever the network hook errors."""
    from aura_life.location.place_service import PlaceService

    def _boom(lat, lon):
        raise RuntimeError("network down")

    service = PlaceService(forecast_tz=_boom)
    with caplog.at_level(0):
        assert service._resolve_tz_for_point(45.51, -73.57) == ""
    text = caplog.text
    assert "network down" in text
    assert "45.5" not in text and "73.5" not in text, text


# ============= Configurable defaults (no baked-in locale / character) =============

def test_default_languages_ship_unchanged_and_are_configurable():
    """P-12: the EN/FR pair was hardcoded in five places. It stays the shipped
    default — persona generation must not change — but a host can now move it."""
    from aura_life.personas import personality_config as pc
    from aura_life.personas.profile_parser import ParsedProfile

    assert pc.get_default_languages() == ("English", "French")
    assert pc.PersonalityDefinition(id="x", name="X").languages == ["English", "French"]
    assert ParsedProfile().languages == ["English", "French"]
    assert pc.ensure_bilingual(["Spanish"]) == ["English", "French", "Spanish"]
    assert pc.native_language_for("France", ["English", "French"]) == "French"
    assert pc.native_language_for("Germany", []) == "English"

    try:
        pc.set_default_languages("Japanese", "English")
        assert pc.get_default_languages() == ("Japanese", "English")
        assert ParsedProfile().languages == ["Japanese", "English"]
        assert pc.ensure_bilingual(["Spanish"]) == ["Japanese", "English", "Spanish"]
        # French is no longer a default, so the francophone heuristic stands down.
        assert pc.native_language_for("France", []) == "Japanese"
        with pytest.raises(ValueError):
            pc.set_default_languages()
    finally:
        pc.set_default_languages("English", "French")

    assert pc.get_default_languages() == ("English", "French")


def test_emotion_baseline_default_is_neutral_not_one_character():
    """M-01: the OCEAN fallback used to be one specific character's profile,
    silently inherited by every host that omitted a baseline."""
    from aura_life.emotion.emotion_engine import (
        DEFAULT_OCEAN_TRAITS,
        EmotionEngine,
    )

    assert set(DEFAULT_OCEAN_TRAITS.values()) == {0.5}

    neutral = EmotionEngine()
    curious = EmotionEngine(ocean_traits={"openness": 1.0, "extraversion": 1.0})

    def _intensity(engine, name):
        for emotion in engine._baseline_emotions:
            if emotion.emotion == name:
                return emotion.intensity
        return 0.0

    assert _intensity(curious, "curious") > _intensity(neutral, "curious")
    # A partial profile still fills the remaining traits from the neutral default.
    assert curious._ocean_traits["agreeableness"] == 0.5
