"""Tests for the Behavior Engine."""

from aura_life.behavior.behavior_system import BehaviorSystem


class TestRoutineDetection:
    def test_routine_emerges_after_repetitions(self):
        bs = BehaviorSystem()
        # comfort_level grows by 0.01 per call once count >= 3
        # Need 30+ calls for comfort > 0.3
        for _ in range(35):
            bs.track_activity("reading")
        routines = bs.get_established_routines()
        assert len(routines) == 1
        assert routines[0].name == "reading"

    def test_no_routine_for_rare_activity(self):
        bs = BehaviorSystem()
        bs.track_activity("stargazing")
        bs.track_activity("yoga")
        assert bs.get_established_routines() == []

    def test_staleness_grows_with_repetition(self):
        bs = BehaviorSystem()
        for _ in range(15):
            bs.track_activity("reading")
        routine = bs._routines.get("reading")
        assert routine is not None
        assert routine.staleness > 0

    def test_non_practiced_routines_decay(self):
        bs = BehaviorSystem()
        for _ in range(5):
            bs.track_activity("reading")
        initial_streak = bs._routines["reading"].consistency_streak
        bs.track_activity("yoga")  # Different activity
        assert bs._routines["reading"].consistency_streak < initial_streak


class TestCreativeOutput:
    def test_creative_activity_may_produce_artifact(self):
        import random
        random.seed(42)
        bs = BehaviorSystem()
        # Run many times to ensure at least one artifact (30% chance)
        for _ in range(20):
            bs.on_creative_activity("writing poetry", mood="inspired", focus=0.8)
        assert len(bs.get_recent_artifacts()) > 0

    def test_non_creative_activity_produces_nothing(self):
        bs = BehaviorSystem()
        result = bs.on_creative_activity("going for a run")
        assert result is None

    def test_portfolio_capped_at_20(self):
        import random
        random.seed(0)
        bs = BehaviorSystem()
        for i in range(50):
            random.seed(i)
            bs.on_creative_activity("writing poetry", focus=0.9)
        assert len(bs._creative_portfolio) <= 20


class TestAmbientSenses:
    def test_ambient_updates_from_location(self):
        bs = BehaviorSystem()
        bs.tick(location="cafe", weather="clear", time_of_day="morning")
        ambient = bs.get_ambient()
        assert "espresso machine" in ambient.sounds or "quiet chatter" in ambient.sounds
        assert ambient.light_quality == "golden morning light"

    def test_rain_adds_sound(self):
        bs = BehaviorSystem()
        bs.tick(location="home", weather="rainy", time_of_day="afternoon")
        ambient = bs.get_ambient()
        assert any("rain" in s for s in ambient.sounds)

    def test_night_adds_sound(self):
        bs = BehaviorSystem()
        bs.tick(location="home", weather="clear", time_of_day="night")
        ambient = bs.get_ambient()
        assert any("crickets" in s or "traffic" in s for s in ambient.sounds)


class TestPossessions:
    def test_add_and_grow_sentimental_value(self):
        bs = BehaviorSystem()
        bs.add_possession("journal", "leather-bound journal")
        bs.grow_sentimental_value("journal", 0.3)
        p = bs._possessions[0]
        assert p.name == "journal"
        assert p.sentimental_value == 0.3

    def test_no_duplicate_possessions(self):
        bs = BehaviorSystem()
        bs.add_possession("journal")
        bs.add_possession("journal")
        assert len(bs._possessions) == 1

    def test_possessions_capped_at_15(self):
        bs = BehaviorSystem()
        for i in range(20):
            bs.add_possession(f"item_{i}")
        assert len(bs._possessions) <= 15


class TestNeighborhood:
    def test_seed_and_visit(self):
        bs = BehaviorSystem()
        bs.seed_neighborhood([
            {"name": "Luna Cafe", "type": "cafe", "familiarity": 0.5, "emotion": "cozy"},
        ])
        assert "Luna Cafe" in bs._neighborhood
        bs.visit_place("Luna Cafe")
        assert bs._neighborhood["Luna Cafe"].familiarity > 0.5


class TestSerialization:
    def test_roundtrip(self):
        bs = BehaviorSystem()
        bs.track_activity("reading")
        bs.track_activity("reading")
        bs.track_activity("reading")
        bs.tick(location="home", weather="clear", time_of_day="morning")
        bs.add_possession("mug")

        data = bs.to_dict()
        bs2 = BehaviorSystem.from_dict(data)
        assert "reading" in bs2._routines
        assert len(bs2._possessions) == 1

    def test_from_empty_dict(self):
        bs = BehaviorSystem.from_dict({})
        assert bs._routines == {}
        assert bs._possessions == []

    def test_export_state(self):
        bs = BehaviorSystem()
        state = bs.export_state()
        assert "routines" in state
        assert "recent_creations" in state
        assert "ambient" in state
