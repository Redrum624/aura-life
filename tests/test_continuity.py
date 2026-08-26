"""Tests for the Continuity Engine."""

from datetime import datetime

from aura_life.continuity.continuity_system import ContinuitySystem


class TestAnniversaries:
    def test_add_anniversary(self):
        cs = ContinuitySystem()
        cs.add_anniversary("first meeting", "02-14")
        assert len(cs._anniversaries) == 1

    def test_no_duplicate_anniversary(self):
        cs = ContinuitySystem()
        cs.add_anniversary("first meeting", "02-14")
        cs.add_anniversary("first meeting", "02-14")
        assert len(cs._anniversaries) == 1

    def test_daily_tick_detects_today_anniversary(self):
        cs = ContinuitySystem()
        today_str = datetime.now().strftime("%m-%d")
        cs.add_anniversary("today's event", today_str)
        events = cs.daily_tick()
        assert len(events) == 1
        assert "today's event" in events[0]

    def test_daily_tick_skips_other_dates(self):
        cs = ContinuitySystem()
        cs.add_anniversary("other date", "01-01")
        events = cs.daily_tick()
        # Only matches if today is Jan 1
        if datetime.now().strftime("%m-%d") != "01-01":
            assert len(events) == 0


class TestGrowthSnapshots:
    def test_weekly_tick_creates_snapshot(self):
        cs = ContinuitySystem()
        cs.weekly_tick(
            skill_levels={"cooking": 0.5},
            identity_facets={"creative": 0.4},
            relationship_trust=0.6,
        )
        assert len(cs._growth_snapshots) == 1

    def test_notable_changes_detected(self):
        cs = ContinuitySystem()
        # First snapshot (no comparison)
        cs.weekly_tick(
            skill_levels={"cooking": 0.3},
            identity_facets={"creative": 0.2},
            relationship_trust=0.5,
        )
        # Second snapshot with improvements
        result = cs.weekly_tick(
            skill_levels={"cooking": 0.5},
            identity_facets={"creative": 0.5},
            relationship_trust=0.7,
        )
        assert result is not None
        assert len(result.notable_changes) > 0

    def test_snapshots_capped_at_20(self):
        cs = ContinuitySystem()
        for i in range(25):
            cs.weekly_tick(
                skill_levels={"cooking": i * 0.01},
                identity_facets={},
                relationship_trust=0.5,
            )
        assert len(cs._growth_snapshots) <= 20


class TestMilestones:
    def test_first_hundred_messages(self):
        cs = ContinuitySystem()
        m = cs.check_milestones(interaction_count=100, vulnerability_openness=0.2, inside_joke_count=0)
        assert m is not None
        assert "100" in m.name

    def test_milestone_only_triggers_once(self):
        cs = ContinuitySystem()
        m1 = cs.check_milestones(interaction_count=100, vulnerability_openness=0.2, inside_joke_count=0)
        m2 = cs.check_milestones(interaction_count=150, vulnerability_openness=0.2, inside_joke_count=0)
        assert m1 is not None
        assert m2 is None  # Already detected

    def test_first_inside_joke(self):
        cs = ContinuitySystem()
        m = cs.check_milestones(interaction_count=10, vulnerability_openness=0.2, inside_joke_count=1)
        assert m is not None
        assert "joke" in m.name.lower()

    def test_first_vulnerability(self):
        cs = ContinuitySystem()
        m = cs.check_milestones(interaction_count=10, vulnerability_openness=0.6, inside_joke_count=0)
        assert m is not None
        assert "vulnerability" in m.name.lower()

    def test_no_milestone_below_thresholds(self):
        cs = ContinuitySystem()
        m = cs.check_milestones(interaction_count=10, vulnerability_openness=0.2, inside_joke_count=0)
        assert m is None


class TestSerialization:
    def test_roundtrip(self):
        cs = ContinuitySystem()
        cs.add_anniversary("test date", "06-15")
        cs.check_milestones(interaction_count=100, vulnerability_openness=0.2, inside_joke_count=0)
        cs.weekly_tick(skill_levels={"a": 0.5}, identity_facets={}, relationship_trust=0.5)

        data = cs.to_dict()
        cs2 = ContinuitySystem.from_dict(data)
        assert len(cs2._anniversaries) == 1
        assert len(cs2._milestones) == 1
        assert len(cs2._growth_snapshots) == 1
        assert "first_hundred_messages" in cs2._milestones_detected

    def test_from_empty_dict(self):
        cs = ContinuitySystem.from_dict({})
        assert len(cs._anniversaries) == 0

    def test_export_state(self):
        cs = ContinuitySystem()
        state = cs.export_state()
        assert isinstance(state, dict)
