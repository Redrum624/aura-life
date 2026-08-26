"""Tests for the Expression & Perception Engine."""

from datetime import datetime, timedelta

from aura_life.expression.expression_system import ExpressionSystem


class TestConnectionAwareness:
    def test_online_after_message(self):
        es = ExpressionSystem()
        es.on_user_message()
        assert es._connection.is_online is True

    def test_offline_after_tick_gap(self):
        es = ExpressionSystem()
        es.on_user_message()
        # Simulate 1 hour gap
        es._connection.last_message_at = datetime.now() - timedelta(hours=1)
        es.tick()
        assert es._connection.is_online is False

    def test_interaction_count_increments(self):
        es = ExpressionSystem()
        es.on_user_message()
        es.on_user_message()
        es.on_user_message()
        assert es._interaction_count == 3

    def test_response_time_tracking(self):
        es = ExpressionSystem()
        es._connection.last_message_at = datetime.now() - timedelta(seconds=30)
        es.on_user_message()
        assert len(es._response_times) == 1
        assert es._connection.avg_response_time_seconds > 0


class TestRelationshipStages:
    def test_starts_early(self):
        es = ExpressionSystem()
        assert es._style.relationship_stage == "early"

    def test_transitions_to_comfortable(self):
        es = ExpressionSystem()
        for _ in range(50):
            es.on_user_message()
        assert es._style.relationship_stage == "comfortable"

    def test_transitions_to_deep(self):
        es = ExpressionSystem()
        for _ in range(200):
            es.on_user_message()
        assert es._style.relationship_stage == "deep"

    def test_formality_decreases_with_stage(self):
        es = ExpressionSystem()
        initial_formality = es._style.formality
        for _ in range(50):
            es.on_user_message()
        assert es._style.formality < initial_formality


class TestStyleHint:
    def test_early_style_hint(self):
        es = ExpressionSystem()
        hint = es.get_style_hint()
        assert "complete sentences" in hint.lower()

    def test_deep_style_hint(self):
        es = ExpressionSystem()
        es._style.relationship_stage = "deep"
        hint = es.get_style_hint()
        assert "inside jokes" in hint.lower() or "shorthand" in hint.lower()


class TestConnectionContext:
    def test_no_context_initially(self):
        es = ExpressionSystem()
        assert es.get_connection_context() is None

    def test_long_gap_context(self):
        es = ExpressionSystem()
        es._connection.last_message_at = datetime.now() - timedelta(hours=10)
        es._connection.time_since_last_message_hours = 10.0
        ctx = es.get_connection_context()
        assert ctx is not None
        assert "while" in ctx.lower()


class TestSerialization:
    def test_roundtrip(self):
        es = ExpressionSystem()
        for _ in range(10):
            es.on_user_message()

        data = es.to_dict()
        es2 = ExpressionSystem.from_dict(data)
        assert es2._interaction_count == 10
        assert es2._style.relationship_stage == es._style.relationship_stage

    def test_from_empty_dict(self):
        es = ExpressionSystem.from_dict({})
        assert es._interaction_count == 0

    def test_export_state(self):
        es = ExpressionSystem()
        state = es.export_state()
        assert "style_hint" in state
        assert "relationship_stage" in state
