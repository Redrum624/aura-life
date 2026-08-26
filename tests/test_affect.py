"""Tests for the Affect System — stress accumulation fix and general behavior."""

import json

from aura_life.affect.affect_system import AffectSystem


class TestStressAccumulation:
    """Bug fix: on_stressor_added was bumping +0.05 every call even for existing
    stressors, causing stress to hit 1.0 ('overwhelmed') within minutes."""

    def test_duplicate_stressor_no_double_bump(self):
        affect = AffectSystem()
        initial = affect.stress.level
        affect.on_stressor_added("work deadline")
        after_first = affect.stress.level
        affect.on_stressor_added("work deadline")  # same stressor again
        after_second = affect.stress.level
        # First add should bump by 0.05
        assert after_first == initial + 0.05
        # Second add of same stressor should NOT bump
        assert after_second == after_first

    def test_different_stressors_both_bump(self):
        affect = AffectSystem()
        initial = affect.stress.level
        affect.on_stressor_added("work deadline")
        affect.on_stressor_added("argument with friend")
        assert affect.stress.level == initial + 0.10

    def test_stress_sources_no_duplicates(self):
        affect = AffectSystem()
        affect.on_stressor_added("hunger")
        affect.on_stressor_added("hunger")
        affect.on_stressor_added("hunger")
        assert affect.stress.sources.count("hunger") == 1

    def test_stressor_resolved_gives_relief(self):
        affect = AffectSystem()
        affect.on_stressor_added("big test")
        level_with_stress = affect.stress.level
        affect.on_stressor_resolved("big test")
        assert affect.stress.level < level_with_stress
        assert "big test" not in affect.stress.sources

    def test_many_repeated_stressors_dont_overwhelm(self):
        """Simulates what was happening during catch-up ticks."""
        affect = AffectSystem()
        # 50 ticks all adding the same 3 stressors
        for _ in range(50):
            affect.on_stressor_added("hunger")
            affect.on_stressor_added("sleep_deprivation")
            affect.on_stressor_added("overdue: call mom")
        # Should be 3 * 0.05 = 0.15, NOT 150 * 0.05 = 7.5 (capped at 1.0)
        assert affect.stress.level <= 0.20


class TestStressDecay:
    def test_natural_decay_per_tick(self):
        affect = AffectSystem()
        affect._stress.level = 0.5
        affect.tick(body_state={"hunger": 0.0, "hours_awake": 8.0},
                    social_state={"hours_since_contact": 1.0},
                    weather="clear", season="summer")
        assert affect.stress.level < 0.5

    def test_activity_provides_stress_relief(self):
        affect = AffectSystem()
        affect._stress.level = 0.5
        affect.on_activity("yoga")
        assert affect.stress.level < 0.5


class TestStressDescription:
    def test_low_stress_returns_empty(self):
        """Stress below 0.2 returns empty string (not notable enough to mention)."""
        affect = AffectSystem()
        affect._stress.level = 0.1
        assert affect.get_stress_description() == ""

    def test_high_stress_overwhelmed(self):
        affect = AffectSystem()
        affect._stress.level = 0.8
        desc = affect.get_stress_description()
        assert "overwhelm" in desc.lower()


class TestSerialization:
    def test_stress_roundtrip(self):
        affect = AffectSystem()
        affect.on_stressor_added("deadline")
        affect.on_stressor_added("argument")
        data = affect.to_dict()
        restored = AffectSystem.from_dict(data)
        assert restored.stress.level == affect.stress.level
        assert restored.stress.sources == affect.stress.sources
