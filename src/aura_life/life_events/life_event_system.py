"""
Life Event System

Tracks significant life moments (achievements, discoveries, surprises) that
create an urge to share.  Events are recorded by LifeService from existing
tick hooks — no separate tick method needed.
"""

import logging
import random
from datetime import datetime
from typing import Dict, List, Optional, Union

from ..models import LifeEvent
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
# Legacy name: the life-event title templates moved, unchanged, into the
# contemporary setting pack (aura_life.settings.contemporary) in Task 9's fix
# round (ruling T9-R5) -- the system reads its persona's setting now;
# re-exported so an import from here keeps working.
from ..settings.contemporary import LIFE_EVENT_TEMPLATES  # noqa: F401

logger = logging.getLogger(__name__)


#: Standins for LIFE_EVENT_TEMPLATES["emotional"] when the only available
#: context is a bare activity name (never a real topic) -- on_activity's
#: low-intensity / non-positive branch. The "emotional" templates read
#: fine with a real topic as `{context}` ("Felt genuinely proud of her
#: promotion") but not with a bare activity name ("Felt genuinely proud of
#: reading") -- the exact defect Task 5 removes (see record_event's
#: docstring). Never applied to a raw engine label; always a whole activity
#: description via `{activity}`.
_ACTIVITY_LINGERING_TITLES = (
    "Something about {activity} lingered",
    "There was a quiet pull to {activity}",
)

MAX_EVENTS = 20

#: "record a mood event only when the mood label changes and at most once
#: per 6 simulated hours" (Task 5 / humanness program brief, verbatim value).
#: See :meth:`LifeEventSystem.on_mood_change`.
MOOD_EVENT_MIN_HOURS = 6.0

#: Cap and per-unit-intensity multiplier for a mood-change life event's
#: share_urgency. Unchanged from the removed ``on_emotion_event``'s
#: ``min(0.7, intensity * 0.8)`` (this module, pre-Task-5) -- on_mood_change
#: replaces that method's *trigger condition* but the brief gives no new
#: urgency value, so it keeps that formula rather than inventing one.
MOOD_EVENT_SHARE_URGENCY_CAP = 0.7
MOOD_EVENT_SHARE_URGENCY_PER_INTENSITY = 0.8


class LifeEventSystem:
    """
    Lightweight engine that stores significant life events.

    Events are created reactively by LifeService (goal completion, skill
    milestones, chaos serendipity, etc.), not on a tick schedule.
    """

    def __init__(self, rng=None, setting: Optional[SettingSpec] = None):
        """``setting``: her setting pack (:class:`~aura_life.settings.SettingSpec`),
        whose ``life_event_templates`` titles an activity's life event.
        ``None`` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s."""
        self._events: List[LifeEvent] = []
        self._rng = rng if rng is not None else random
        self._setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        # on_mood_change's throttle state -- in-memory only, like the sibling
        # LifeService._life_trigger_cooldowns (never persisted; a restart
        # simply lets the next tick's mood look like a fresh "first" mood).
        self._last_mood_label: Optional[str] = None
        self._last_mood_event_at: Optional[datetime] = None

    # ============= Public API =============

    def _next_share_id(self) -> str:
        """The next ``"event:<n>"`` id: one past the highest numbered id
        currently in ``self._events``.

        Scanned rather than kept in a separate counter so a reload (which
        restores ``share_id`` per event but not a counter) cannot desync from
        the data: :func:`record_event` calls this before appending, and the
        MAX_EVENTS trim always keeps the most-recently-created (so
        highest-numbered) events, so the true maximum is always visible here.
        """
        highest = 0
        for event in self._events:
            if event.share_id.startswith("event:"):
                suffix = event.share_id.split(":", 1)[1]
                if suffix.isdigit():
                    highest = max(highest, int(suffix))
        return f"event:{highest + 1}"

    def record_event(
        self,
        event_type: str,
        title: str,
        description: str = "",
        emotional_impact: Optional[Dict[str, float]] = None,
        share_urgency: float = 0.7,
        source: str = "",
    ) -> LifeEvent:
        """Record a significant life event.

        ``title`` is used verbatim: the caller owns composing the final text
        (see :data:`LIFE_EVENT_TEMPLATES` for the phrase catalog a caller may
        draw from -- :meth:`on_activity` does). This method used to re-run
        every title through a second, automatic template lookup keyed by
        ``event_type``, which either double-templated an already-final title
        (e.g. "Completed: X" becoming "Nailed it -- Completed: X is done") or,
        worse, turned a bare mood label or activity name passed as `title`
        into the template's noun ("content" -> "Felt genuinely proud of
        content"). Task 5 / humanness program removed that step.

        Returns the created LifeEvent so the caller can inspect it
        (e.g. to decide whether to create a follow-up trigger).
        """
        event = LifeEvent(
            event_type=event_type,
            title=title,
            description=description or title,
            emotional_impact=emotional_impact or {},
            share_urgency=share_urgency,
            created_at=datetime.now(),
            source=source,
            share_id=self._next_share_id(),
        )

        self._events.append(event)

        # Trim oldest events
        if len(self._events) > MAX_EVENTS:
            self._events = self._events[-MAX_EVENTS:]

        logger.info(f"Life event recorded: [{event_type}] {title} (urgency={share_urgency:.2f}, source={source})")
        return event

    def get_unshared_events(self) -> List[LifeEvent]:
        """Return events that haven't been shared yet, newest first."""
        return [e for e in reversed(self._events) if not e.shared]

    def get_most_urgent_unshared(self) -> Optional[LifeEvent]:
        """Return the unshared event with the highest share_urgency."""
        unshared = self.get_unshared_events()
        if not unshared:
            return None
        return max(unshared, key=lambda e: e.share_urgency)

    def mark_shared(self, share_id: Union[str, int], now: Optional[datetime] = None) -> bool:
        """Mark the event whose stable ``share_id`` (``"event:<n>"``, from
        :meth:`record_event`) matches as shared, at ``now`` -- the world
        clock's instant, which ``LifeService.mark_shared`` passes (ruling
        T17-R5; this class holds no clock of its own); the host's clock only
        for a caller that gives none.

        An ``int`` is the event's row id, as 0.5.0's ``mark_shared(event_id)``
        took it (Task 42: on the stable ids alone that call marked nothing).

        Returns whether a match was found. Does not persist -- callers (see
        ``LifeService.mark_shared``, the host-facing entry point that also
        covers ``ShareableExperience``) own saving.
        """
        by_row = isinstance(share_id, int) and not isinstance(share_id, bool)
        for event in self._events:
            if (event.id == share_id and event.id is not None) if by_row else (
                    isinstance(share_id, str) and event.share_id == share_id):
                event.shared = True
                event.shared_at = now if now is not None else datetime.now()
                return True
        return False

    # ============= Reactive Hooks =============

    def on_activity(self, activity_name: str, emotions: dict,
                    share_worthy: bool = False) -> Optional[LifeEvent]:
        """Auto-record notable activities as life events.

        Called from LifeService after each activity tick. Only records when
        the activity was emotionally significant or share-worthy.

        ``activity_name`` is a bare engine identifier (e.g. "reading"), never
        a finished sentence, so it must never become the noun of one of the
        LIFE_EVENT_TEMPLATES["emotional"] phrases ("Couldn't stop thinking
        about reading") -- that phrasing reads fine with a real topic as
        `{context}` but not with the raw activity name, and the SLOT_TEMPLATE_RE
        classifier the task's acceptance test uses flags exactly that
        combination. The high-intensity-positive branch uses the "discovery"
        templates instead (their `{context}` slot already reads fine with a
        bare activity name: "Found something amazing: reading"); the other
        branch uses :data:`_ACTIVITY_LINGERING_TITLES`, a safe standin for
        "emotional". Both draw one template via ``self._rng.choice`` either
        way, matching this method's rng-consumption before Task 5 (only the
        phrase pools changed) -- LifeService shares one ``random.Random``
        across many engines, so a changed draw *count* here would shift
        every later stochastic decision downstream of it.
        """
        # Only record emotionally significant activities
        max_intensity = max(emotions.values()) if emotions else 0
        if max_intensity < 0.2 and not share_worthy:
            return None

        # Determine event type from emotion profile
        positive = {"joyful", "excited", "proud", "awed", "content", "warm", "satisfied"}
        top_emotion = max(emotions, key=emotions.get) if emotions else ""
        discoveries = self._setting.life_event_templates.get("discovery")
        if top_emotion in positive and max_intensity > 0.3 and discoveries:
            event_type = "discovery"
            title = self._rng.choice(discoveries).format(context=activity_name)
        else:
            event_type = "emotional"
            title = self._rng.choice(_ACTIVITY_LINGERING_TITLES).format(activity=activity_name)

        return self.record_event(
            event_type=event_type,
            title=title,
            description=f"It happened while {activity_name}",
            emotional_impact=emotions,
            share_urgency=min(0.8, max_intensity + (0.2 if share_worthy else 0)),
            source="activity",
        )

    def on_mood_change(self, mood_label: str, intensity: float, now: datetime) -> Optional[LifeEvent]:
        """Record a life event when the mood label changes, throttled.

        Replaces the old ``on_emotion_event`` hook, which a caller drove from
        every energy tick whenever mood intensity crossed a threshold --
        recording near-continuously (about one event per 5-minute tick,
        ~380 over a 3-simulated-day run) and titling each one through
        ``record_event``'s old auto-template, which turned the bare mood
        label into "Felt genuinely proud of content". This method fires only
        when ``mood_label`` differs from the label at her *last* mood life
        event, and at most once every :data:`MOOD_EVENT_MIN_HOURS` simulated
        hours -- ``now`` is that clock's instant (the world clock via the
        caller; this class holds no clock of its own).

        The very first call only seeds the baseline (there is nothing yet to
        call a "change" against) and returns ``None``.
        """
        if self._last_mood_label is None:
            self._last_mood_label = mood_label
            return None
        if mood_label == self._last_mood_label:
            return None
        if self._last_mood_event_at is not None:
            elapsed_hours = (now - self._last_mood_event_at).total_seconds() / 3600.0
            if elapsed_hours < MOOD_EVENT_MIN_HOURS:
                return None

        self._last_mood_label = mood_label
        self._last_mood_event_at = now
        return self.record_event(
            event_type="emotional",
            title=f"Mood shifted to {mood_label}",
            description=f"Settled into feeling {mood_label}",
            emotional_impact={mood_label: intensity},
            share_urgency=min(MOOD_EVENT_SHARE_URGENCY_CAP, intensity * MOOD_EVENT_SHARE_URGENCY_PER_INTENSITY),
            source="mood_change",
        )

    # ============= Engine Interface =============

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        unshared = self.get_unshared_events()
        if not unshared:
            return {}
        return {
            "unshared_count": len(unshared),
            "most_urgent": {
                "title": unshared[0].title if unshared else "",
                "type": unshared[0].event_type if unshared else "",
                "urgency": round(unshared[0].share_urgency, 2) if unshared else 0,
            },
        }

    def get_status(self) -> dict:
        """Status for /api/life/status endpoint and debugging."""
        unshared = self.get_unshared_events()
        return {
            "total_events": len(self._events),
            "unshared_count": len(unshared),
            "recent_events": [
                {"title": e.title, "type": e.event_type, "shared": e.shared}
                for e in self._events[-5:]
            ],
        }

    def to_dict(self) -> dict:
        """Serialize full state for DB persistence."""
        return {
            "events": [e.to_dict() for e in self._events],
        }

    @classmethod
    def from_dict(cls, data: dict, rng=None) -> "LifeEventSystem":
        """Deserialize from DB."""
        system = cls(rng=rng)
        for event_data in data.get("events", []):
            system._events.append(LifeEvent.from_dict(event_data))
        return system
