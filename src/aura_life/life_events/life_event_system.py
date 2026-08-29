"""
Life Event System

Tracks significant life moments (achievements, discoveries, surprises) that
create an urge to share.  Events are recorded by LifeService from existing
tick hooks — no separate tick method needed.
"""

import logging
import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import LifeEvent

logger = logging.getLogger(__name__)


# ============= Event Title Templates =============

LIFE_EVENT_TEMPLATES: Dict[str, List[str]] = {
    "achievement": [
        "Finally finished {context}",
        "Nailed it — {context} is done",
        "Can't believe she actually pulled off {context}",
    ],
    "discovery": [
        "Found something amazing: {context}",
        "Stumbled onto {context} and can't stop thinking about it",
    ],
    "social": [
        "Had the best conversation with {context}",
        "Reconnected with {context} after ages",
    ],
    "emotional": [
        "Couldn't stop thinking about {context}",
        "Got a little emotional about {context}",
        "Felt genuinely proud of {context}",
    ],
    "surprise": [
        "Something unexpected happened: {context}",
        "Didn't see this coming — {context}",
    ],
}

MAX_EVENTS = 20


class LifeEventSystem:
    """
    Lightweight engine that stores significant life events.

    Events are created reactively by LifeService (goal completion, skill
    milestones, chaos serendipity, etc.), not on a tick schedule.
    """

    def __init__(self, rng=None):
        self._events: List[LifeEvent] = []
        self._rng = rng if rng is not None else random

    # ============= Public API =============

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

        Returns the created LifeEvent so the caller can inspect it
        (e.g. to decide whether to create a follow-up trigger).
        """
        # Optionally templatize the title
        templates = LIFE_EVENT_TEMPLATES.get(event_type, [])
        if templates and "{context}" in templates[0]:
            title = self._rng.choice(templates).format(context=title)

        event = LifeEvent(
            event_type=event_type,
            title=title,
            description=description or title,
            emotional_impact=emotional_impact or {},
            share_urgency=share_urgency,
            created_at=datetime.now(),
            source=source,
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

    def mark_shared(self, event_id: int) -> None:
        """Mark an event as shared."""
        for event in self._events:
            if event.id == event_id:
                event.shared = True
                event.shared_at = datetime.now()
                break

    # ============= Reactive Hooks =============

    def on_activity(self, activity_name: str, emotions: dict,
                    share_worthy: bool = False) -> Optional[LifeEvent]:
        """Auto-record notable activities as life events.

        Called from LifeService after each activity tick. Only records when
        the activity was emotionally significant or share-worthy.
        """
        # Only record emotionally significant activities
        max_intensity = max(emotions.values()) if emotions else 0
        if max_intensity < 0.2 and not share_worthy:
            return None

        # Determine event type from emotion profile
        positive = {"joyful", "excited", "proud", "awed", "content", "warm", "satisfied"}
        top_emotion = max(emotions, key=emotions.get) if emotions else ""
        if top_emotion in positive:
            event_type = "discovery" if max_intensity > 0.3 else "emotional"
        else:
            event_type = "emotional"

        return self.record_event(
            event_type=event_type,
            title=activity_name,
            description=f"While {activity_name}",
            emotional_impact=emotions,
            share_urgency=min(0.8, max_intensity + (0.2 if share_worthy else 0)),
            source="activity",
        )

    def on_emotion_event(self, emotion: str, intensity: float) -> Optional[LifeEvent]:
        """Auto-record high-intensity emotional moments.

        Called from LifeService on affect tick. Only records intense emotions
        to avoid flooding the event log.
        """
        if intensity < 0.4:
            return None

        return self.record_event(
            event_type="emotional",
            title=emotion,
            description=f"A strong wave of {emotion}",
            emotional_impact={emotion: intensity},
            share_urgency=min(0.7, intensity * 0.8),
            source="emotion",
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
