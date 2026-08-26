"""Tests for the Character Evolution Engine."""

from aura_life.persona_evolution.character_evolution import (
    CharacterEvolution,
    MAX_DRIFT,
)


class TestActivityTracking:
    def test_track_activity(self):
        ce = CharacterEvolution()
        ce.track_activity("reading")
        ce.track_activity("reading")
        assert ce._activity_counts["reading"] == 2

    def test_multiple_activities_tracked(self):
        ce = CharacterEvolution()
        ce.track_activity("reading")
        ce.track_activity("yoga")
        assert len(ce._activity_counts) == 2


class TestMonthlyEvolution:
    def test_drift_occurs_with_activities(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5, "calm": 0.5, "energy": 0.5, "creativity": 0.5},
        )
        # Accumulate calm activities
        for _ in range(50):
            ce.track_activity("meditating")
            ce.track_activity("yoga")

        changes = ce.monthly_evolution(
            identity_facets={},
            relationship_trust=0.5,
            avg_mood="content",
        )
        assert len(changes) > 0
        assert "calm" in changes

    def test_drift_bounded_by_max(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5, "calm": 0.5},
        )
        # Run many evolution cycles
        for cycle in range(50):
            for _ in range(100):
                ce.track_activity("meditating")
            ce.monthly_evolution(identity_facets={}, relationship_trust=0.5, avg_mood="content")

        original = 0.5
        current = ce._current_baseline.get("calm", 0.5)
        assert abs(current - original) <= MAX_DRIFT + 0.001

    def test_no_drift_without_activities(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5, "calm": 0.5},
        )
        changes = ce.monthly_evolution(identity_facets={}, relationship_trust=0.5, avg_mood="neutral")
        # Without tracked activities, there's no dominant direction
        assert all(abs(v) < 0.02 for v in changes.values())

    def test_activity_counts_reset_after_evolution(self):
        ce = CharacterEvolution()
        ce.track_activity("reading")
        ce.monthly_evolution(identity_facets={}, relationship_trust=0.5, avg_mood="neutral")
        assert len(ce._activity_counts) == 0

    def test_high_trust_boosts_warmth(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5},
        )
        ce.monthly_evolution(identity_facets={}, relationship_trust=0.9, avg_mood="content")
        assert ce._current_baseline["warmth"] >= 0.5


class TestDriftSummary:
    def test_no_drift_initially(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5},
        )
        assert ce.get_drift_summary() == {}

    def test_drift_shows_after_evolution(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5, "calm": 0.5, "energy": 0.5, "creativity": 0.5},
        )
        for _ in range(50):
            ce.track_activity("yoga")
        ce.monthly_evolution(identity_facets={}, relationship_trust=0.5, avg_mood="calm")
        drift = ce.get_drift_summary()
        assert len(drift) > 0


class TestSerialization:
    def test_roundtrip(self):
        ce = CharacterEvolution(
            original_baseline={"warmth": 0.5, "calm": 0.6},
            core_traits=["warm", "curious"],
        )
        ce.track_activity("reading")
        ce.monthly_evolution(identity_facets={}, relationship_trust=0.5, avg_mood="neutral")

        data = ce.to_dict()
        ce2 = CharacterEvolution.from_dict(data)
        assert ce2._original_baseline == {"warmth": 0.5, "calm": 0.6}
        assert ce2._core_traits == ["warm", "curious"]
        assert ce2._last_evolution is not None

    def test_from_empty_dict(self):
        ce = CharacterEvolution.from_dict({})
        assert ce._original_baseline == {}

    def test_export_state(self):
        ce = CharacterEvolution(original_baseline={"warmth": 0.5})
        state = ce.export_state()
        assert isinstance(state, dict)
