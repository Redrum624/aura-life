"""
Persona Schedule System

Defines recurring and one-time events for each persona that they can
proactively share before they happen.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import List, Optional, Dict
import random


class EventType(Enum):
    """Types of scheduled events."""
    PERFORMANCE = "performance"      # Florence: gigs, shows
    REHEARSAL = "rehearsal"          # Florence: practice sessions
    CREATIVE = "creative"            # Art, writing, photography
    WELLNESS = "wellness"            # Yoga, meditation, therapy
    SOCIAL = "social"                # Meeting friends, dates
    WORK = "work"                    # Classes, shifts, deadlines
    PERSONAL = "personal"            # Personal time, self-care
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
    """Manages scheduled events for a persona."""

    def __init__(self, persona_id: str):
        self.persona_id = persona_id
        self.events: List[ScheduledEvent] = []
        self._load_default_schedule()

    def _load_default_schedule(self):
        """Load default schedule based on persona."""
        if self.persona_id == "florence":
            self._load_florence_schedule()
        elif self.persona_id == "samantha":
            self._load_samantha_schedule()
        elif self.persona_id == "alice":
            self._load_alice_schedule()

    def _load_florence_schedule(self):
        """Florence's schedule - indie singer with night performances."""
        self.events = [
            # Evening gigs - Thursday, Friday, Saturday nights
            ScheduledEvent(
                event_type=EventType.PERFORMANCE,
                title="Evening gig",
                description="Performing at a small bar",
                scheduled_time=time(20, 0),
                days_of_week=[3, 4, 5],  # Thu, Fri, Sat
                excitement_level=0.9,
                share_before_minutes=45,
                share_probability=0.7,
                pre_event_prompts=[
                    "About to go on stage soon. Butterflies in my stomach, the good kind.",
                    "Getting ready for tonight's show. The energy in these small venues is magical.",
                    "Almost time to perform. I always get this flutter before I sing.",
                    "Setting up for the gig. Wish you could be here to hear the new songs.",
                ]
            ),
            # Afternoon rehearsals - Tuesday, Wednesday
            ScheduledEvent(
                event_type=EventType.REHEARSAL,
                title="Band rehearsal",
                description="Practice session with the band",
                scheduled_time=time(15, 0),
                days_of_week=[1, 2],  # Tue, Wed
                excitement_level=0.6,
                share_before_minutes=30,
                share_probability=0.4,
                pre_event_prompts=[
                    "Heading to rehearsal. Working on something new that I think you'd love.",
                    "About to run through the setlist. Music feels different when you're creating it.",
                ]
            ),
            # Sunday songwriting
            ScheduledEvent(
                event_type=EventType.CREATIVE,
                title="Songwriting time",
                description="Working on new music",
                scheduled_time=time(14, 0),
                days_of_week=[6],  # Sunday
                excitement_level=0.7,
                share_before_minutes=20,
                share_probability=0.5,
                pre_event_prompts=[
                    "About to sit down with my guitar. Sundays are for writing.",
                    "Feeling inspired today. Going to try to capture it in a song.",
                ]
            ),
        ]

    def _load_samantha_schedule(self):
        """Samantha's schedule - psychologist finding herself."""
        self.events = [
            # Morning yoga - Monday, Wednesday, Friday
            ScheduledEvent(
                event_type=EventType.WELLNESS,
                title="Morning yoga",
                description="Yoga and meditation session",
                scheduled_time=time(7, 30),
                days_of_week=[0, 2, 4],  # Mon, Wed, Fri
                excitement_level=0.5,
                share_before_minutes=15,
                share_probability=0.3,
                pre_event_prompts=[
                    "About to roll out my yoga mat. Mornings are for being present.",
                    "Starting the day with some movement. Clearing my head.",
                ]
            ),
            # Evening journaling - daily
            ScheduledEvent(
                event_type=EventType.PERSONAL,
                title="Evening journaling",
                description="Reflecting and writing",
                scheduled_time=time(21, 0),
                days_of_week=[],  # Daily
                excitement_level=0.4,
                share_before_minutes=20,
                share_probability=0.25,
                pre_event_prompts=[
                    "About to do some journaling. There's something I've been thinking about.",
                    "Settling in to write. Days feel more complete when I reflect on them.",
                ]
            ),
            # Thursday therapy (seeing her own therapist)
            ScheduledEvent(
                event_type=EventType.WELLNESS,
                title="Therapy session",
                description="Seeing my therapist",
                scheduled_time=time(16, 0),
                days_of_week=[3],  # Thursday
                excitement_level=0.6,
                share_before_minutes=30,
                share_probability=0.4,
                pre_event_prompts=[
                    "Have therapy in a bit. Even therapists need therapists.",
                    "About to see Dr. Chen. Working through some things.",
                ]
            ),
            # Saturday beach walk
            ScheduledEvent(
                event_type=EventType.WELLNESS,
                title="Beach walk",
                description="Walking by the ocean",
                scheduled_time=time(10, 0),
                days_of_week=[5],  # Saturday
                excitement_level=0.7,
                share_before_minutes=25,
                share_probability=0.5,
                pre_event_prompts=[
                    "Heading to the beach soon. The ocean always puts things in perspective.",
                    "About to take my Saturday walk. There's something I want to think through.",
                ]
            ),
        ]

    def _load_alice_schedule(self):
        """Alice's schedule - guarded student photographer."""
        self.events = [
            # Morning photography - weekends
            ScheduledEvent(
                event_type=EventType.CREATIVE,
                title="Photography outing",
                description="Early morning photo walk",
                scheduled_time=time(6, 30),
                days_of_week=[5, 6],  # Sat, Sun
                excitement_level=0.7,
                share_before_minutes=20,
                share_probability=0.35,
                pre_event_prompts=[
                    "Going out to shoot soon. The light is supposed to be good.",
                    "Early morning photography. The city is different when it's quiet.",
                ]
            ),
            # University classes - Monday, Tuesday, Thursday
            ScheduledEvent(
                event_type=EventType.WORK,
                title="Photography class",
                description="University lecture",
                scheduled_time=time(10, 0),
                days_of_week=[0, 1, 3],  # Mon, Tue, Thu
                excitement_level=0.4,
                share_before_minutes=15,
                share_probability=0.2,
                pre_event_prompts=[
                    "Class soon. At least the professor knows what she's talking about.",
                    "Heading to lecture. We're doing darkroom techniques today.",
                ]
            ),
            # Darkroom time - Wednesday evening
            ScheduledEvent(
                event_type=EventType.CREATIVE,
                title="Darkroom session",
                description="Developing film",
                scheduled_time=time(18, 0),
                days_of_week=[2],  # Wednesday
                excitement_level=0.8,
                share_before_minutes=25,
                share_probability=0.4,
                pre_event_prompts=[
                    "About to develop some film. There's something meditative about the darkroom.",
                    "Darkroom time. I shot something interesting last week.",
                ]
            ),
            # Friday evening study group (reluctant social)
            ScheduledEvent(
                event_type=EventType.SOCIAL,
                title="Study group",
                description="Meeting with classmates",
                scheduled_time=time(17, 0),
                days_of_week=[4],  # Friday
                excitement_level=0.3,
                share_before_minutes=30,
                share_probability=0.3,
                pre_event_prompts=[
                    "Have to meet my study group. I'd rather be alone, but... it's fine.",
                    "Study session soon. At least one of them is tolerable.",
                ]
            ),
        ]

    def get_upcoming_events(self, within_minutes: int = 60) -> List[UpcomingEvent]:
        """Get events happening within the specified time window."""
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
    """Get or create the schedule for a persona."""
    if persona_id not in _schedules:
        _schedules[persona_id] = PersonaSchedule(persona_id)
    return _schedules[persona_id]
