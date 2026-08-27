"""
Persona Schedule System

A host-populated container for a persona's recurring and one-time events, and
the timing logic that decides when the persona might proactively mention one
before it happens.

This library ships NO schedule content. `PersonaSchedule` starts empty for
every persona id -- that is the documented default, not a failure -- and the
host application supplies the events it wants, either at construction or via
`add_event`:

    from datetime import time
    from aura_life.schedule import (
        EventType, PersonaSchedule, ScheduledEvent, get_persona_schedule,
    )

    schedule = get_persona_schedule("my-persona")
    schedule.add_event(ScheduledEvent(
        event_type=EventType.CREATIVE,
        title="Studio time",
        description="Working on something new",
        scheduled_time=time(14, 0),
        days_of_week=[5, 6],          # Sat, Sun -- empty list means daily
        share_before_minutes=20,
        share_probability=0.5,
    ))

    for upcoming in schedule.get_events_to_share():
        ...  # host decides how to surface it
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import List, Optional, Dict
import random


class EventType(Enum):
    """Types of scheduled events.

    A broad, host-agnostic vocabulary — the host picks whichever type best
    describes each event it registers.
    """
    PERFORMANCE = "performance"      # Gigs, shows, recitals, public appearances
    REHEARSAL = "rehearsal"          # Practice and preparation sessions
    CREATIVE = "creative"            # Art, writing, music, photography
    WELLNESS = "wellness"            # Exercise, meditation, therapy, self-care
    SOCIAL = "social"                # Meeting friends, dates, group activities
    WORK = "work"                    # Classes, shifts, deadlines
    PERSONAL = "personal"            # Personal time, routines, reflection
    ADVENTURE = "adventure"          # Trips, exploring, outings


@dataclass
class ScheduledEvent:
    """A scheduled event that a persona might want to share about."""

    event_type: EventType
    title: str
    description: str
    scheduled_time: time  # Time of day (for recurring)
    days_of_week: List[int] = field(default_factory=list)  # 0=Monday, 6=Sunday (empty = daily)
    excitement_level: float = 0.7  # How excited they are (affects proactive messaging)
    share_before_minutes: int = 30  # How many minutes before to potentially share
    share_probability: float = 0.6  # Chance they'll reach out about it

    # Pre-event message templates (persona will rephrase naturally)
    pre_event_prompts: List[str] = field(default_factory=list)

    def get_next_occurrence(self, from_time: datetime = None) -> Optional[datetime]:
        """Get the next occurrence of this event."""
        now = from_time or datetime.now()

        # If no specific days, it happens daily
        if not self.days_of_week:
            event_today = now.replace(
                hour=self.scheduled_time.hour,
                minute=self.scheduled_time.minute,
                second=0, microsecond=0
            )
            if event_today > now:
                return event_today
            return event_today + timedelta(days=1)

        # Find the next matching day
        for days_ahead in range(8):  # Check up to a week ahead
            check_date = now + timedelta(days=days_ahead)
            if check_date.weekday() in self.days_of_week:
                event_time = check_date.replace(
                    hour=self.scheduled_time.hour,
                    minute=self.scheduled_time.minute,
                    second=0, microsecond=0
                )
                if event_time > now:
                    return event_time

        return None

    def should_share_now(self, current_time: datetime = None) -> bool:
        """Check if this event should trigger a proactive share right now."""
        now = current_time or datetime.now()
        next_occurrence = self.get_next_occurrence(now)

        if not next_occurrence:
            return False

        minutes_until = (next_occurrence - now).total_seconds() / 60

        # Within the share window?
        if 0 < minutes_until <= self.share_before_minutes:
            # Random chance based on probability
            return random.random() < self.share_probability

        return False

    def get_pre_event_context(self) -> str:
        """Get a random pre-event prompt for message generation."""
        if self.pre_event_prompts:
            return random.choice(self.pre_event_prompts)
        return f"About to: {self.title}"


@dataclass
class UpcomingEvent:
    """An upcoming event with timing info for the API."""
    event: ScheduledEvent
    next_occurrence: datetime
    minutes_until: float
    should_notify: bool


class PersonaSchedule:
    """A host-populated collection of a persona's scheduled events.

    The library supplies the timing and share-window logic; the host supplies
    the events. A schedule constructed without events is empty, and an empty
    schedule is a legitimate, fully supported state: `get_upcoming_events` and
    `get_events_to_share` simply return nothing until the host adds events.

    Args:
        persona_id: Identifier of the persona this schedule belongs to. It is
            stored for the host's convenience and never used to select
            content — no id is special.
        events: Optional initial events. The list is copied, so the caller may
            keep mutating its own list without affecting this schedule.
    """

    def __init__(self, persona_id: str, events: Optional[List[ScheduledEvent]] = None):
        self.persona_id = persona_id
        self.events: List[ScheduledEvent] = list(events) if events else []

    def add_event(self, event: ScheduledEvent) -> None:
        """Register one more event on this schedule."""
        self.events.append(event)

    def get_upcoming_events(self, within_minutes: int = 60) -> List[UpcomingEvent]:
        """Get events happening within the specified time window.

        Returns an empty list when the host has not registered any events.
        """
        now = datetime.now()
        upcoming = []

        for event in self.events:
            next_occ = event.get_next_occurrence(now)
            if next_occ:
                minutes_until = (next_occ - now).total_seconds() / 60
                if minutes_until <= within_minutes:
                    upcoming.append(UpcomingEvent(
                        event=event,
                        next_occurrence=next_occ,
                        minutes_until=minutes_until,
                        should_notify=event.should_share_now(now)
                    ))

        return sorted(upcoming, key=lambda x: x.minutes_until)

    def get_events_to_share(self) -> List[UpcomingEvent]:
        """Get events that should trigger proactive messages right now."""
        upcoming = self.get_upcoming_events(within_minutes=60)
        return [e for e in upcoming if e.should_notify]


# Global schedule instances per persona
_schedules: Dict[str, PersonaSchedule] = {}


def get_persona_schedule(persona_id: str) -> PersonaSchedule:
    """Get or create the process-wide schedule for a persona.

    A schedule created here starts empty — the library ships no content for
    any id. Fill it with `add_event`, or build a `PersonaSchedule` directly
    with its `events` argument if you do not want the shared cache. Release
    it with `clear_persona_schedule`.
    """
    if persona_id not in _schedules:
        _schedules[persona_id] = PersonaSchedule(persona_id)
    return _schedules[persona_id]


def clear_persona_schedule(persona_id: Optional[str] = None) -> bool:
    """Evict cached schedules — the teardown path for `get_persona_schedule`.

    `_schedules` is a process-global cache with no TTL or size limit, so a host
    that serves many persona ids keeps every schedule it ever built resident.
    Call this from the host's persona-teardown path.

    With `persona_id`, drops that one entry and returns whether it was cached.
    With no argument, clears the whole cache and returns True if it held
    anything.
    """
    if persona_id is None:
        had_entries = bool(_schedules)
        _schedules.clear()
        return had_entries
    return _schedules.pop(persona_id, None) is not None
