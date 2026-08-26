"""Tests for the Memory & Time Engine."""

import random

from aura_life.memory_time.memory_time_system import MemoryTimeSystem


class TestTimePerception:
    def test_flow_activity_speeds_time(self):
        mt = MemoryTimeSystem()
        mt._time_perception.subjective_speed = 0.5
        for _ in range(10):
            mt._update_time_perception("reading", "content")
        assert mt._time_perception.subjective_speed > 0.5

    def test_boring_activity_slows_time(self):
        mt = MemoryTimeSystem()
        mt._time_perception.subjective_speed = 0.5
        for _ in range(10):
            mt._update_time_perception("waiting", "bored")
        assert mt._time_perception.subjective_speed < 0.5

    def test_speed_clamped_0_to_1(self):
        mt = MemoryTimeSystem()
        for _ in range(100):
            mt._update_time_perception("reading", "joyful")
        assert 0.0 <= mt._time_perception.subjective_speed <= 1.0


class TestSeasonalConsciousness:
    def test_season_feeling_develops(self):
        mt = MemoryTimeSystem()
        for _ in range(15):
            mt._update_seasonal("autumn")
        assert mt._seasonal.current_season_feeling != ""
        assert "autumn" in mt._seasonal.current_season_feeling.lower() or mt._seasonal.current_season_feeling in [
            "autumn melancholy", "cozy nostalgia", "reflective calm"
        ]

    def test_season_memory_count_increments(self):
        mt = MemoryTimeSystem()
        mt._update_seasonal("winter")
        mt._update_seasonal("winter")
        assert mt._seasonal.season_memory_count.get("winter", 0) == 2

    def test_years_experienced_grows(self):
        mt = MemoryTimeSystem()
        for season in ("spring", "summer", "autumn", "winter"):
            for _ in range(35):
                mt._update_seasonal(season)
        assert mt._seasonal.years_experienced >= 1


class TestNostalgia:
    def test_nostalgia_can_trigger(self):
        random.seed(1)
        mt = MemoryTimeSystem()
        triggered = False
        for _ in range(100):
            result = mt._check_nostalgia("listening to music", "autumn")
            if result is not None:
                triggered = True
                break
        assert triggered

    def test_nostalgia_log_capped(self):
        random.seed(0)
        mt = MemoryTimeSystem()
        for i in range(100):
            random.seed(i)
            mt._check_nostalgia("listening to music", "autumn")
        assert len(mt._nostalgia_log) <= 20


class TestLifeNarrative:
    def test_add_chapter(self):
        mt = MemoryTimeSystem()
        mt.add_life_chapter("The Quiet Start", "She's finding her rhythm")
        assert mt.get_current_chapter() is not None
        assert mt.get_current_chapter().title == "The Quiet Start"

    def test_previous_chapter_closed(self):
        mt = MemoryTimeSystem()
        mt.add_life_chapter("Chapter 1", "First chapter")
        mt.add_life_chapter("Chapter 2", "Second chapter")
        assert mt._life_chapters[0].period_end is not None


class TestAnticipation:
    def test_add_anticipation(self):
        mt = MemoryTimeSystem()
        mt.add_anticipation("weekend trip", "excited", 0.7)
        assert len(mt.get_anticipations()) == 1

    def test_anticipations_capped(self):
        mt = MemoryTimeSystem()
        for i in range(10):
            mt.add_anticipation(f"event_{i}")
        assert len(mt._anticipations) <= 5


class TestTick:
    def test_tick_increments_counter(self):
        mt = MemoryTimeSystem()
        mt.tick("reading", "content", "autumn", "afternoon")
        assert mt._tick_count == 1

    def test_tick_returns_nostalgia_or_none(self):
        mt = MemoryTimeSystem()
        result = mt.tick("reading", "content", "autumn", "afternoon")
        assert result is None or hasattr(result, "trigger")


class TestSerialization:
    def test_roundtrip(self):
        mt = MemoryTimeSystem()
        mt.tick("reading", "content", "autumn", "afternoon")
        mt.add_life_chapter("Test", "Testing roundtrip")
        mt.add_anticipation("party", "excited")

        data = mt.to_dict()
        mt2 = MemoryTimeSystem.from_dict(data)
        assert mt2._tick_count == 1
        assert len(mt2._life_chapters) == 1
        assert len(mt2._anticipations) == 1

    def test_from_empty_dict(self):
        mt = MemoryTimeSystem.from_dict({})
        assert mt._tick_count == 0

    def test_export_state_keys(self):
        mt = MemoryTimeSystem()
        state = mt.export_state()
        assert isinstance(state, dict)
