"""Tests for the Chaos & Entropy Engine."""

import random

from aura_life.chaos.chaos_engine import ChaosEngine


class TestChaosRoll:
    def test_roll_can_produce_event(self):
        random.seed(42)
        ce = ChaosEngine()
        events = []
        for _ in range(50):
            e = ce.roll("reading", energy=0.5, regulation=0.5)
            if e:
                events.append(e)
        assert len(events) > 0

    def test_event_has_required_fields(self):
        random.seed(1)
        ce = ChaosEngine()
        for _ in range(50):
            e = ce.roll("reading", energy=0.5, regulation=0.5)
            if e:
                assert "type" in e
                assert "text" in e
                assert "emotions" in e
                assert "share_worthy" in e
                break

    def test_daily_cap_at_5(self):
        random.seed(0)
        ce = ChaosEngine()
        events = []
        for i in range(200):
            random.seed(i)
            e = ce.roll("reading", energy=0.5, regulation=0.0)
            if e:
                events.append(e)
        assert len(events) <= 5

    def test_low_regulation_increases_chaos(self):
        events_low_reg = 0
        events_high_reg = 0
        for seed in range(100):
            random.seed(seed)
            ce = ChaosEngine()
            if ce.roll("reading", energy=0.5, regulation=0.0):
                events_low_reg += 1
            random.seed(seed)
            ce = ChaosEngine()
            if ce.roll("reading", energy=0.5, regulation=1.0):
                events_high_reg += 1
        assert events_low_reg >= events_high_reg

    def test_no_event_when_daily_cap_reached(self):
        ce = ChaosEngine()
        ce._events_today = [{"text": f"event_{i}"} for i in range(5)]
        ce._last_date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        result = ce.roll("reading", energy=0.5, regulation=0.5)
        assert result is None


class TestActivityChaos:
    def test_activity_specific_events(self):
        random.seed(10)
        ce = ChaosEngine()
        e = ce._activity_chaos("reading")
        assert e is not None
        assert e["activity"] == "reading"

    def test_unknown_activity_falls_back(self):
        random.seed(10)
        ce = ChaosEngine()
        e = ce._activity_chaos("flying a plane")
        # Should fall back to universal chaos
        assert e is not None
        assert e["type"] == "universal"


class TestSerendipity:
    def test_serendipity_always_share_worthy(self):
        random.seed(42)
        ce = ChaosEngine()
        e = ce._serendipity()
        assert e["share_worthy"] is True
        assert e["type"] == "serendipity"


class TestMessageDelay:
    def test_delay_can_occur(self):
        random.seed(42)
        ce = ChaosEngine()
        delays = []
        for _ in range(50):
            d = ce.roll_message_delay("reading", energy=0.2, regulation=0.3)
            if d:
                delays.append(d)
        assert len(delays) > 0

    def test_delay_has_required_fields(self):
        random.seed(1)
        ce = ChaosEngine()
        for _ in range(50):
            d = ce.roll_message_delay("reading", energy=0.1, regulation=0.1)
            if d:
                assert "reason" in d
                assert "delay_minutes" in d
                assert "explanation" in d
                break


class TestSerialization:
    def test_roundtrip(self):
        random.seed(42)
        ce = ChaosEngine()
        ce.roll("reading", energy=0.5, regulation=0.5)
        ce.roll("reading", energy=0.5, regulation=0.5)

        data = ce.to_dict()
        ce2 = ChaosEngine.from_dict(data)
        assert ce2._total_events == ce._total_events

    def test_from_empty_dict(self):
        ce = ChaosEngine.from_dict({})
        assert ce._total_events == 0

    def test_export_state(self):
        ce = ChaosEngine()
        state = ce.export_state()
        assert "events_today" in state
