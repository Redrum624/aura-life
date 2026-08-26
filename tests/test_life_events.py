"""Tests for the Life Event System — specifically the double-templating fix."""

from aura_life.life_events.life_event_system import LifeEventSystem, LIFE_EVENT_TEMPLATES


class TestEmotionEventTemplating:
    """Bug fix: on_emotion_event was pre-formatting title as 'Felt deeply {emotion}',
    then record_event wrapped it in ANOTHER template, producing gibberish like
    'Felt genuinely proud of Felt deeply content'."""

    def test_emotion_event_no_double_template(self):
        """Title should use a template ONCE, not nest 'Felt deeply X' inside another template."""
        system = LifeEventSystem()
        event = system.on_emotion_event("content", intensity=0.6)
        assert event is not None
        assert "Felt deeply" not in event.title

    def test_emotion_event_uses_template(self):
        """Title should come from LIFE_EVENT_TEMPLATES['emotional'], not be raw emotion."""
        system = LifeEventSystem()
        event = system.on_emotion_event("excited", intensity=0.5)
        assert event is not None
        # Template should have expanded — title should contain the emotion word
        assert "excited" in event.title
        # And it should be a full phrase from the template, not just the raw word
        assert len(event.title) > len("excited")

    def test_emotion_event_below_threshold_returns_none(self):
        system = LifeEventSystem()
        event = system.on_emotion_event("content", intensity=0.3)
        assert event is None

    def test_emotion_event_description_preserved(self):
        system = LifeEventSystem()
        event = system.on_emotion_event("proud", intensity=0.5)
        assert event is not None
        assert "proud" in event.description


class TestActivityEventTemplating:
    """Ensure on_activity also doesn't double-template."""

    def test_activity_event_uses_template(self):
        system = LifeEventSystem()
        event = system.on_activity(
            "painting a landscape",
            emotions={"awed": 0.5},
            share_worthy=True,
        )
        assert event is not None
        # Should contain the activity name via template
        assert "painting a landscape" in event.title


class TestRecordEvent:
    def test_unknown_type_no_template(self):
        """Unknown event types should use the raw title."""
        system = LifeEventSystem()
        event = system.record_event(
            event_type="unknown_type",
            title="Something happened",
        )
        assert event.title == "Something happened"

    def test_event_list_capped(self):
        system = LifeEventSystem()
        for i in range(25):
            system.record_event(event_type="surprise", title=f"event {i}")
        assert len(system._events) <= 20
