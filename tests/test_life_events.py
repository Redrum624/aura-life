"""Tests for the Life Event System.

Task 5 (aura humanness program) removed ``record_event``'s automatic
title-templating: it used to re-run every title through a second template
keyed by ``event_type``, which either double-templated an already-final
title or, when the title was a bare mood label or activity name (as
``on_emotion_event``/``on_activity`` passed), turned it into that template's
noun ("content" -> "Felt genuinely proud of content", "reading" ->
"Couldn't stop thinking about reading"). ``on_emotion_event`` (called from
every energy tick whenever mood intensity crossed a threshold, recording
near-continuously) is replaced by ``on_mood_change`` (fires only on an actual
mood-label change, throttled to MOOD_EVENT_MIN_HOURS).
"""

from datetime import datetime, timedelta

from aura_life.life_events.life_event_system import (
    LIFE_EVENT_TEMPLATES,
    MAX_EVENTS,
    MOOD_EVENT_MIN_HOURS,
    LifeEventSystem,
)
from aura_life.models import LifeEvent


class TestRecordEventNoAutoTemplate:
    """The core Task 5 fix: ``title`` is used exactly as given, whatever
    ``event_type`` is -- there is no second, implicit template lookup."""

    def test_title_used_verbatim_for_every_known_event_type(self):
        system = LifeEventSystem()
        for event_type in LIFE_EVENT_TEMPLATES:
            event = system.record_event(event_type=event_type, title="Something happened")
            assert event.title == "Something happened"

    def test_a_bare_mood_label_is_never_slotted_as_a_template_noun(self):
        """The exact reported defect: passing a mood label as `title` to the
        'emotional' event type used to produce "Felt genuinely proud of
        content"."""
        system = LifeEventSystem()
        event = system.record_event(event_type="emotional", title="content")
        assert event.title == "content"

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


class TestNextShareIdAcrossEviction:
    """A `f"event:{len(self._events) + 1}"` implementation looks right until
    eviction: once _events is capped at MAX_EVENTS, len() stops growing, so
    that implementation would reissue the same id forever past the cap."""

    def test_ids_stay_unique_and_increasing_past_the_cap(self):
        system = LifeEventSystem()
        issued = [
            system.record_event(event_type="surprise", title=f"event {i}").share_id
            for i in range(MAX_EVENTS + 10)
        ]
        # Every id ever issued was unique -- none got reissued after eviction.
        assert len(issued) == len(set(issued))
        # Every currently-live id is unique too.
        live_ids = [e.share_id for e in system._events]
        assert len(live_ids) == len(set(live_ids))

        highest_issued = max(int(s.split(":", 1)[1]) for s in issued)
        new_event = system.record_event(event_type="surprise", title="one more")
        # The new id exceeds every id EVER issued, not just the live ones --
        # a len(self._events) + 1 implementation would fail this once
        # eviction has kicked in (len stays at MAX_EVENTS from then on).
        assert int(new_event.share_id.split(":", 1)[1]) > highest_issued


class TestActivityEventTemplating:
    """on_activity composes its own final title -- never the bare
    activity_name slotted as a template noun."""

    def test_high_intensity_positive_activity_uses_a_discovery_template(self):
        system = LifeEventSystem()
        event = system.on_activity(
            "painting a landscape",
            emotions={"awed": 0.5},
            share_worthy=True,
        )
        assert event is not None
        # Should contain the activity name via template
        assert "painting a landscape" in event.title

    def test_low_intensity_activity_title_never_slots_the_bare_activity_name(self):
        """Before Task 5, this exact input (a non-"positive" top emotion, so
        event_type="emotional") produced "Couldn't stop thinking about
        reading" -- the activity name as the template's noun."""
        system = LifeEventSystem()
        event = system.on_activity("reading", emotions={"bored": 0.3})
        assert event is not None
        assert not event.title.startswith("Couldn't stop thinking about")
        assert not event.title.startswith("Felt genuinely proud of")
        assert not event.title.startswith("Got a little emotional about")
        assert "reading" in event.title

    def test_activity_description_never_starts_with_bare_while(self):
        """"While reading" (event.description before Task 5) is itself one of
        the SLOT_TEMPLATE_RE-flagged prefixes when the filler is the bare
        activity name."""
        system = LifeEventSystem()
        event = system.on_activity("reading", emotions={"bored": 0.3})
        assert event is not None
        assert not event.description.startswith("While ")


class TestMoodChangeEvent:
    """Replaces on_emotion_event: fires only on a mood-label change, at most
    once per MOOD_EVENT_MIN_HOURS simulated hours."""

    def test_first_call_only_seeds_the_baseline(self):
        system = LifeEventSystem()
        event = system.on_mood_change("content", 0.6, datetime(2026, 1, 1, 12, 0))
        assert event is None

    def test_fires_on_the_first_real_change(self):
        system = LifeEventSystem()
        t0 = datetime(2026, 1, 1, 12, 0)
        system.on_mood_change("content", 0.6, t0)  # seeds baseline
        event = system.on_mood_change("happy", 0.5, t0 + timedelta(hours=1))
        assert event is not None
        assert event.event_type == "emotional"

    def test_same_label_again_does_not_fire(self):
        system = LifeEventSystem()
        t0 = datetime(2026, 1, 1, 12, 0)
        system.on_mood_change("content", 0.6, t0)
        assert system.on_mood_change("content", 0.6, t0 + timedelta(hours=1)) is None

    def test_a_second_change_within_the_throttle_window_does_not_fire(self):
        system = LifeEventSystem()
        t0 = datetime(2026, 1, 1, 12, 0)
        system.on_mood_change("content", 0.6, t0)
        system.on_mood_change("happy", 0.5, t0 + timedelta(hours=1))  # fires
        soon_after = t0 + timedelta(hours=1, minutes=1)
        assert system.on_mood_change("calm", 0.4, soon_after) is None

    def test_a_change_at_the_midpoint_of_the_throttle_window_does_not_fire(self):
        """Guards against a unit bug (e.g. dividing seconds by 60 instead of
        3600 and comparing to 6): 3 simulated hours after the last mood event
        is well inside the 6-hour throttle, so this must stay None. A
        seconds/60 bug would see "180" >= 6 and wrongly fire here."""
        system = LifeEventSystem()
        t0 = datetime(2026, 1, 1, 12, 0)
        system.on_mood_change("content", 0.6, t0)  # seeds baseline
        fired_at = t0 + timedelta(hours=1)
        system.on_mood_change("happy", 0.5, fired_at)  # fires
        midpoint = fired_at + timedelta(hours=3)
        assert system.on_mood_change("calm", 0.4, midpoint) is None

    def test_fires_again_once_the_throttle_window_has_elapsed(self):
        system = LifeEventSystem()
        t0 = datetime(2026, 1, 1, 12, 0)
        system.on_mood_change("content", 0.6, t0)
        system.on_mood_change("happy", 0.5, t0 + timedelta(hours=1))  # fires
        later = t0 + timedelta(hours=1) + timedelta(hours=MOOD_EVENT_MIN_HOURS)
        event = system.on_mood_change("calm", 0.4, later)
        assert event is not None

    def test_title_never_slots_the_bare_mood_label(self):
        """The exact reported defect: "Felt genuinely proud of content"."""
        system = LifeEventSystem()
        t0 = datetime(2026, 1, 1, 12, 0)
        system.on_mood_change("content", 0.6, t0)
        event = system.on_mood_change("happy", 0.5, t0 + timedelta(hours=1))
        assert event is not None
        assert not event.title.startswith("Felt genuinely proud of")
        assert not event.description.startswith("A strong wave of")


class TestLifeEventFromDictBackfillsShareId:
    """A row saved before the share_id column existed has it NULL/missing in
    the DB; from_dict must not hand back a permanently blank id for it."""

    def test_missing_share_id_backfills_from_id(self):
        event = LifeEvent.from_dict({
            "id": 7,
            "event_type": "achievement",
            "title": "Old event",
            "created_at": datetime(2026, 1, 1).isoformat(),
        })
        assert event.share_id == "event:7"

    def test_a_real_share_id_is_kept_as_is(self):
        event = LifeEvent.from_dict({
            "id": 7,
            "share_id": "event:3",
            "event_type": "achievement",
            "title": "New event",
            "created_at": datetime(2026, 1, 1).isoformat(),
        })
        assert event.share_id == "event:3"

    def test_no_id_at_all_backfills_to_blank_not_a_crash(self):
        event = LifeEvent.from_dict({
            "event_type": "achievement",
            "title": "No id",
            "created_at": datetime(2026, 1, 1).isoformat(),
        })
        assert event.share_id == ""
