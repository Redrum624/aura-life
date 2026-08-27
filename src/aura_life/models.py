"""
Life System Data Models

All dataclasses for the autonomous life simulation.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# ===== Location/Place Models =====


@dataclass
class PlaceLocationState:
    """Volatile per-persona location and weather state (life.db: life_location_state)."""
    # Current position (= home when not travelling)
    current_city: str = ""
    current_lat: Optional[float] = None
    current_lon: Optional[float] = None
    current_timezone: str = ""
    # Trip overlay
    on_trip: bool = False
    trip_destination: str = ""
    trip_returns_at: str = ""
    trip_reason: str = ""
    # Weather (Open-Meteo WMO code / simulated fallback)
    weather_code: Optional[int] = None
    weather_label: str = ""
    weather_temp_c: Optional[float] = None
    weather_is_day: bool = True
    weather_fetched_at: str = ""
    weather_source: str = "simulated"

    def to_dict(self) -> dict:
        return {
            "current_city": self.current_city,
            "current_lat": self.current_lat,
            "current_lon": self.current_lon,
            "current_timezone": self.current_timezone,
            "on_trip": 1 if self.on_trip else 0,
            "trip_destination": self.trip_destination,
            "trip_returns_at": self.trip_returns_at,
            "trip_reason": self.trip_reason,
            "weather_code": self.weather_code,
            "weather_label": self.weather_label,
            "weather_temp_c": self.weather_temp_c,
            "weather_is_day": 1 if self.weather_is_day else 0,
            "weather_fetched_at": self.weather_fetched_at,
            "weather_source": self.weather_source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlaceLocationState":
        return cls(
            current_city=data.get("current_city") or "",
            current_lat=data.get("current_lat"),
            current_lon=data.get("current_lon"),
            current_timezone=data.get("current_timezone") or "",
            on_trip=bool(data.get("on_trip", 0)),
            trip_destination=data.get("trip_destination") or "",
            trip_returns_at=data.get("trip_returns_at") or "",
            trip_reason=data.get("trip_reason") or "",
            weather_code=data.get("weather_code"),
            weather_label=data.get("weather_label") or "",
            weather_temp_c=data.get("weather_temp_c"),
            weather_is_day=bool(data.get("weather_is_day", 1)),
            weather_fetched_at=data.get("weather_fetched_at") or "",
            weather_source=data.get("weather_source") or "simulated",
        )


# ============= Location Models =============


@dataclass
class LocationProfile:
    """A location the persona can visit, with tracking metadata."""
    key: str = ""              # "marina", "yoga_studio"
    name: str = ""             # "Marina", "Yoga Studio"
    place_type: str = "other"  # home/cafe/park/workplace/gym/library/bar/restaurant/beach/campus/street/transit/other
    description: str = ""      # For image gen / LLM context
    source: str = "default"    # default/profile/occupation/interest/llm/user
    familiarity: float = 0.5   # 0-1, grows with visits
    visit_count: int = 0
    last_visit: Optional[str] = None  # ISO datetime


LOCATION_TYPE_EFFECTS: Dict[str, Dict[str, float]] = {
    "home":       {"energy_drain": -0.01, "stress_delta": -0.02, "social_drain": -0.01, "comfort": 0.9},
    "workplace":  {"energy_drain": 0.04,  "stress_delta": 0.02,  "social_drain": 0.02,  "comfort": 0.4},
    "cafe":       {"energy_drain": 0.01,  "stress_delta": -0.01, "social_drain": 0.01,  "comfort": 0.7},
    "park":       {"energy_drain": 0.01,  "stress_delta": -0.03, "social_drain": 0.0,   "comfort": 0.6},
    "gym":        {"energy_drain": 0.06,  "stress_delta": -0.02, "social_drain": 0.01,  "comfort": 0.3},
    "library":    {"energy_drain": 0.01,  "stress_delta": -0.02, "social_drain": -0.01, "comfort": 0.7},
    "bar":        {"energy_drain": 0.02,  "stress_delta": -0.01, "social_drain": 0.03,  "comfort": 0.5},
    "restaurant": {"energy_drain": 0.01,  "stress_delta": -0.01, "social_drain": 0.02,  "comfort": 0.6},
    "beach":      {"energy_drain": 0.02,  "stress_delta": -0.04, "social_drain": 0.0,   "comfort": 0.6},
    "campus":     {"energy_drain": 0.03,  "stress_delta": 0.01,  "social_drain": 0.02,  "comfort": 0.5},
    "street":     {"energy_drain": 0.02,  "stress_delta": 0.0,   "social_drain": 0.01,  "comfort": 0.4},
    "transit":    {"energy_drain": 0.03,  "stress_delta": 0.01,  "social_drain": 0.01,  "comfort": 0.2},
    "other":      {"energy_drain": 0.02,  "stress_delta": 0.0,   "social_drain": 0.01,  "comfort": 0.5},
}

COMMUTE_ENERGY_COST = 0.03  # Extra energy cost when changing locations


# ============= World Models =============


class Location(Enum):
    """Legacy location enum — kept for backward compatibility with CherishedObject etc.

    The life system now uses plain string keys (e.g. "home", "cafe") so that
    persona-specific locations from text profiles work seamlessly.
    """
    # Physical home spaces
    BEDROOM = "bedroom"
    LIVING_ROOM = "living_room"
    KITCHEN = "kitchen"
    GARDEN = "garden"
    STUDY_NOOK = "study_nook"
    BALCONY = "balcony"
    # Imagined/memory spaces
    BEACH = "beach"  # Childhood memories
    CAFE = "cafe"  # Cozy imagined cafe
    INFINITE_LIBRARY = "infinite_library"  # Dream space


# Mapping from legacy Location enum values to generic string keys
LOCATION_ENUM_TO_KEY: Dict[str, str] = {
    "bedroom": "home",
    "living_room": "home",
    "kitchen": "home",
    "garden": "home",
    "study_nook": "home",
    "balcony": "home",
    "beach": "beach",
    "cafe": "cafe",
    "infinite_library": "home",
}


class Weather(Enum):
    """Weather types affecting mood and activities."""
    SUNNY = "sunny"
    CLOUDY = "cloudy"
    RAINY = "rainy"
    STORMY = "stormy"
    FOGGY = "foggy"
    SNOWY = "snowy"
    CLEAR_NIGHT = "clear_night"
    STARRY = "starry"


class TimeOfDay(Enum):
    """Time periods with associated energy levels."""
    DAWN = "dawn"          # 5-7
    MORNING = "morning"    # 7-12
    AFTERNOON = "afternoon"  # 12-17
    EVENING = "evening"    # 17-21
    NIGHT = "night"        # 21-24
    LATE_NIGHT = "late_night"  # 0-5


class Season(Enum):
    """Seasons affecting available activities and mood."""
    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"


@dataclass
class CherishedObject:
    """An object with emotional significance."""
    name: str
    description: str
    emotional_value: float  # 0-1
    associated_memory: str
    location: Location


@dataclass
class WorldState:
    """Current state of the persona's virtual world."""
    current_location: Location = Location.LIVING_ROOM
    weather: Weather = Weather.SUNNY
    virtual_time: datetime = field(default_factory=datetime.now)
    time_of_day: TimeOfDay = TimeOfDay.MORNING
    season: Season = Season.SPRING
    ambiance_description: str = ""


# ============= Energy Models =============


class EnergyLevel(Enum):
    """Descriptive energy levels."""
    EXHAUSTED = "exhausted"      # < 0.15
    TIRED = "tired"              # 0.15-0.3
    RESTING = "resting"          # 0.3-0.5
    COMFORTABLE = "comfortable"  # 0.5-0.7
    ALERT = "alert"              # 0.7-0.85
    ENERGIZED = "energized"      # > 0.85


@dataclass
class EnergyState:
    """The persona's current energy and fatigue state."""
    level: float = 0.7  # 0-1
    fatigue: float = 0.0  # Accumulated fatigue (0-1)
    caffeine_boost: float = 0.0  # Temporary boost
    inspiration_boost: float = 0.0  # From engaging activities
    social_boost: float = 0.0  # From user interaction
    hours_awake: float = 0.0
    last_sleep_time: Optional[datetime] = None
    last_update: datetime = field(default_factory=datetime.now)

    @property
    def effective_level(self) -> float:
        """Get effective energy including boosts."""
        return min(1.0, self.level + self.caffeine_boost + self.inspiration_boost + self.social_boost)

    @property
    def energy_level_enum(self) -> EnergyLevel:
        """Get descriptive energy level."""
        eff = self.effective_level
        if eff < 0.15:
            return EnergyLevel.EXHAUSTED
        elif eff < 0.3:
            return EnergyLevel.TIRED
        elif eff < 0.5:
            return EnergyLevel.RESTING
        elif eff < 0.7:
            return EnergyLevel.COMFORTABLE
        elif eff < 0.85:
            return EnergyLevel.ALERT
        else:
            return EnergyLevel.ENERGIZED


# ============= Activity Models =============


class ActivityCategory(Enum):
    """Categories of activities."""
    MENTAL = "mental"          # Reading, learning, puzzles
    CREATIVE = "creative"      # Writing, art, music creation
    REFLECTIVE = "reflective"  # Journaling, meditation
    SOCIAL = "social"          # Thinking about user, preparing to share
    REST = "rest"              # Sleeping, napping, relaxing
    EXPLORATION = "exploration"  # Exploring imagined spaces


@dataclass
class Activity:
    """Definition of an activity the persona can do."""
    name: str
    category: ActivityCategory
    energy_cost: float  # Negative = restores energy
    min_energy: float  # Minimum energy needed
    duration_minutes: int
    preferred_times: List[TimeOfDay]
    preferred_weather: List[Weather]
    suitable_locations: List[str]
    narrative_templates: List[str]
    thought_possibilities: List[str]
    emotion_effects: Dict[str, float]  # emotion_name -> intensity_delta
    can_be_interrupted: bool = True
    share_worthy: bool = False
    preferred_seasons: List[Season] = field(default_factory=list)


@dataclass
class ActivityLog:
    """Record of a completed activity."""
    id: Optional[int] = None
    activity_name: str = ""
    category: ActivityCategory = ActivityCategory.MENTAL
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    location: str = "home"
    weather: Weather = Weather.SUNNY
    narrative: str = ""  # "She lost herself in her book..."
    thoughts_generated: List[str] = field(default_factory=list)
    emotions_triggered: Dict[str, float] = field(default_factory=dict)
    energy_before: float = 0.0
    energy_after: float = 0.0
    share_worthy: bool = False
    shared_with_user: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "activity_name": self.activity_name,
            "category": self.category.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "location": self.location,
            "weather": self.weather.value,
            "narrative": self.narrative,
            "thoughts_generated": ",".join(self.thoughts_generated),
            "emotions_triggered": json.dumps(self.emotions_triggered),
            "energy_before": self.energy_before,
            "energy_after": self.energy_after,
            "share_worthy": self.share_worthy,
            "shared_with_user": self.shared_with_user,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityLog":
        """Create from dictionary."""
        emotions = {}
        if data.get("emotions_triggered"):
            try:
                emotions = json.loads(data["emotions_triggered"])
            except (json.JSONDecodeError, TypeError):
                emotions = {}

        return cls(
            id=data.get("id"),
            activity_name=data.get("activity_name", ""),
            category=ActivityCategory(data.get("category", "mental")),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else datetime.now(),
            ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
            location=data.get("location", "home"),
            weather=Weather(data.get("weather", "sunny")),
            narrative=data.get("narrative", ""),
            thoughts_generated=data.get("thoughts_generated", "").split(",") if data.get("thoughts_generated") else [],
            emotions_triggered=emotions,
            energy_before=data.get("energy_before", 0.0),
            energy_after=data.get("energy_after", 0.0),
            share_worthy=data.get("share_worthy", False),
            shared_with_user=data.get("shared_with_user", False),
        )


# ============= Goal Models =============


class GoalTimeframe(Enum):
    """Timeframe for goals."""
    DAILY = "daily"          # Small daily intentions
    WEEKLY = "weekly"        # Achievable within a week
    LONG_TERM = "long_term"  # Projects and ongoing goals
    DREAM = "dream"          # Life aspirations


class GoalSource(Enum):
    """Source of goal generation."""
    PERSONALITY = "personality"    # From OCEAN traits
    EXPERIENCE = "experience"      # From activities
    CONVERSATION = "conversation"  # From user topics
    ASPIRATION = "aspiration"      # Core dreams


@dataclass
class Goal:
    """A goal the persona is working toward."""
    id: Optional[int] = None
    title: str = ""
    description: str = ""
    timeframe: GoalTimeframe = GoalTimeframe.DAILY
    source: GoalSource = GoalSource.PERSONALITY
    progress: float = 0.0  # 0-1
    motivation_level: float = 1.0  # 0-1, decays when stagnant
    milestones: List[str] = field(default_factory=list)
    completed_milestones: List[str] = field(default_factory=list)
    involves_user: bool = False
    motivation: str = ""  # Why this goal matters (text)
    related_activities: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_progress_at: Optional[datetime] = None  # When progress last happened
    target_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    abandoned_at: Optional[datetime] = None
    abandon_reason: str = ""
    is_active: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "timeframe": self.timeframe.value,
            "source": self.source.value,
            "progress": self.progress,
            "motivation_level": self.motivation_level,
            "milestones": ",".join(self.milestones),
            "completed_milestones": ",".join(self.completed_milestones),
            "involves_user": self.involves_user,
            "motivation": self.motivation,
            "related_activities": ",".join(self.related_activities),
            "created_at": self.created_at.isoformat(),
            "last_progress_at": self.last_progress_at.isoformat() if self.last_progress_at else None,
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "abandoned_at": self.abandoned_at.isoformat() if self.abandoned_at else None,
            "abandon_reason": self.abandon_reason,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Goal":
        """Create from dictionary."""
        return cls(
            id=data.get("id"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            timeframe=GoalTimeframe(data.get("timeframe", "daily")),
            source=GoalSource(data.get("source", "personality")),
            progress=data.get("progress", 0.0),
            motivation_level=data.get("motivation_level", 1.0),
            milestones=data.get("milestones", "").split(",") if data.get("milestones") else [],
            completed_milestones=data.get("completed_milestones", "").split(",") if data.get("completed_milestones") else [],
            involves_user=data.get("involves_user", False),
            motivation=data.get("motivation", ""),
            related_activities=data.get("related_activities", "").split(",") if data.get("related_activities") else [],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            last_progress_at=datetime.fromisoformat(data["last_progress_at"]) if data.get("last_progress_at") else None,
            target_date=datetime.fromisoformat(data["target_date"]) if data.get("target_date") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            abandoned_at=datetime.fromisoformat(data["abandoned_at"]) if data.get("abandoned_at") else None,
            abandon_reason=data.get("abandon_reason", ""),
            is_active=data.get("is_active", True),
        )


# ============= Short-Term Desire Models =============


class DesireSource(Enum):
    """How a desire was generated."""
    PERSONALITY = "personality"      # From traits
    ACTIVITY = "activity"            # Inspired by something she did
    GOAL = "goal"                    # Supports a goal
    CONVERSATION = "conversation"    # User mentioned something
    SPONTANEOUS = "spontaneous"      # Random whim


@dataclass
class ShortTermDesire:
    """Something she wants to do in the next few days."""
    id: Optional[int] = None
    title: str = ""
    description: str = ""
    source: DesireSource = DesireSource.PERSONALITY
    related_activities: List[str] = field(default_factory=list)
    related_goal_title: Optional[str] = None
    urgency: float = 0.5  # 0-1, higher = more eager
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # Auto-expire after a few days
    fulfilled: bool = False
    fulfilled_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "source": self.source.value,
            "related_activities": ",".join(self.related_activities),
            "related_goal_title": self.related_goal_title,
            "urgency": self.urgency,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "fulfilled": self.fulfilled,
            "fulfilled_at": self.fulfilled_at.isoformat() if self.fulfilled_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShortTermDesire":
        return cls(
            id=data.get("id"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            source=DesireSource(data.get("source", "personality")),
            related_activities=data.get("related_activities", "").split(",") if data.get("related_activities") else [],
            related_goal_title=data.get("related_goal_title"),
            urgency=data.get("urgency", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            fulfilled=data.get("fulfilled", False),
            fulfilled_at=datetime.fromisoformat(data["fulfilled_at"]) if data.get("fulfilled_at") else None,
        )


# ============= Daily Plan Models =============


@dataclass
class PlannedSlot:
    """A single time slot in the daily plan."""
    hour: int  # 0-23
    activity_name: str
    reason: str = ""  # Why this was chosen (goal, desire, routine, etc.)
    location: Optional[str] = None
    completed: bool = False
    actual_activity: Optional[str] = None  # What actually happened (if different)

    def to_dict(self) -> dict:
        return {
            "hour": self.hour,
            "activity_name": self.activity_name,
            "reason": self.reason,
            "location": self.location,
            "completed": self.completed,
            "actual_activity": self.actual_activity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlannedSlot":
        return cls(
            hour=data.get("hour", 0),
            activity_name=data.get("activity_name", ""),
            reason=data.get("reason", ""),
            location=data.get("location"),
            completed=data.get("completed", False),
            actual_activity=data.get("actual_activity"),
        )


@dataclass
class DailyPlan:
    """A full day schedule, generated once per day."""
    date: str = ""  # ISO date string (YYYY-MM-DD)
    slots: List[PlannedSlot] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    weather_at_creation: Optional[str] = None
    revision_notes: List[str] = field(default_factory=list)  # Silent plan changes

    def get_slot_for_hour(self, hour: int) -> Optional[PlannedSlot]:
        """Get the planned slot for a given hour."""
        for slot in self.slots:
            if slot.hour == hour:
                return slot
        return None

    def get_current_slot(self) -> Optional[PlannedSlot]:
        """Get the slot for the current hour."""
        now = datetime.now()
        # Find the most recent slot at or before current time
        current = None
        for slot in sorted(self.slots, key=lambda s: s.hour):
            if slot.hour <= now.hour:
                current = slot
        return current

    def get_next_slot(self) -> Optional[PlannedSlot]:
        """Get the next upcoming slot."""
        now = datetime.now()
        for slot in sorted(self.slots, key=lambda s: s.hour):
            if slot.hour > now.hour and not slot.completed:
                return slot
        return None

    def get_remaining_slots(self) -> List[PlannedSlot]:
        """Get all remaining uncompleted slots."""
        now = datetime.now()
        return [s for s in self.slots if s.hour >= now.hour and not s.completed]

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "slots": json.dumps([s.to_dict() for s in self.slots]),
            "created_at": self.created_at.isoformat(),
            "weather_at_creation": self.weather_at_creation,
            "revision_notes": json.dumps(self.revision_notes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DailyPlan":
        slots_raw = data.get("slots", "[]")
        if isinstance(slots_raw, str):
            try:
                slots_data = json.loads(slots_raw)
            except (json.JSONDecodeError, TypeError):
                slots_data = []
        else:
            slots_data = slots_raw

        notes_raw = data.get("revision_notes", "[]")
        if isinstance(notes_raw, str):
            try:
                notes = json.loads(notes_raw)
            except (json.JSONDecodeError, TypeError):
                notes = []
        else:
            notes = notes_raw

        return cls(
            date=data.get("date", ""),
            slots=[PlannedSlot.from_dict(s) for s in slots_data],
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            weather_at_creation=data.get("weather_at_creation"),
            revision_notes=notes,
        )


# ============= Transit Models =============


class TransitPhase(Enum):
    """Phase of persona movement between locations."""
    PREPARING = "preparing"     # Still at origin, getting ready
    IN_TRANSIT = "in_transit"   # On the way
    ARRIVED = "arrived"         # Just got there


@dataclass
class TransitState:
    """Overlay tracking persona movement between locations. Sub-hour precision."""
    phase: TransitPhase
    origin: str
    destination: str
    reason: str = ""
    preparing_started_at: Optional[datetime] = None
    departure_at: Optional[datetime] = None       # When they left origin
    expected_arrival_at: Optional[datetime] = None # When they should arrive
    arrived_at: Optional[datetime] = None

    def minutes_until_arrival(self) -> Optional[float]:
        if not self.expected_arrival_at:
            return None
        return max(0, (self.expected_arrival_at - datetime.now()).total_seconds() / 60)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "origin": self.origin,
            "destination": self.destination,
            "reason": self.reason,
            "preparing_started_at": self.preparing_started_at.isoformat() if self.preparing_started_at else None,
            "departure_at": self.departure_at.isoformat() if self.departure_at else None,
            "expected_arrival_at": self.expected_arrival_at.isoformat() if self.expected_arrival_at else None,
            "arrived_at": self.arrived_at.isoformat() if self.arrived_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TransitState":
        return cls(
            phase=TransitPhase(data["phase"]),
            origin=data.get("origin", ""),
            destination=data.get("destination", ""),
            reason=data.get("reason", ""),
            preparing_started_at=datetime.fromisoformat(data["preparing_started_at"]) if data.get("preparing_started_at") else None,
            departure_at=datetime.fromisoformat(data["departure_at"]) if data.get("departure_at") else None,
            expected_arrival_at=datetime.fromisoformat(data["expected_arrival_at"]) if data.get("expected_arrival_at") else None,
            arrived_at=datetime.fromisoformat(data["arrived_at"]) if data.get("arrived_at") else None,
        )


# ============= Shareable Experience Models =============


@dataclass
class ShareableExperience:
    """Something the persona wants to share with the user."""
    id: Optional[int] = None
    activity_log_id: Optional[int] = None
    content: str = ""  # What to share
    thought: str = ""  # Related thought
    context: str = ""  # When/where it happened
    priority: float = 0.5  # 0-1, higher = more eager to share
    created_at: datetime = field(default_factory=datetime.now)
    shared: bool = False
    shared_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "activity_log_id": self.activity_log_id,
            "content": self.content,
            "thought": self.thought,
            "context": self.context,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "shared": self.shared,
            "shared_at": self.shared_at.isoformat() if self.shared_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShareableExperience":
        """Create from dictionary."""
        return cls(
            id=data.get("id"),
            activity_log_id=data.get("activity_log_id"),
            content=data.get("content", ""),
            thought=data.get("thought", ""),
            context=data.get("context", ""),
            priority=data.get("priority", 0.5),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            shared=data.get("shared", False),
            shared_at=datetime.fromisoformat(data["shared_at"]) if data.get("shared_at") else None,
        )


# ============= Life Event Models =============


@dataclass
class LifeEvent:
    """A significant life moment that creates an urge to share."""
    id: Optional[int] = None
    event_type: str = ""           # "achievement", "discovery", "social", "emotional", "surprise"
    title: str = ""                # Short: "Finished my big project"
    description: str = ""          # Narrative: "She finally submitted the last chapter..."
    emotional_impact: Dict[str, float] = field(default_factory=dict)  # emotion->intensity
    share_urgency: float = 0.7    # 0-1, how strongly she wants to tell someone (>0.6 can trigger proactive)
    created_at: datetime = field(default_factory=datetime.now)
    shared: bool = False
    shared_at: Optional[datetime] = None
    source: str = ""              # What generated it: "goal_completion", "activity", "chaos", etc.

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "title": self.title,
            "description": self.description,
            "emotional_impact": self.emotional_impact,
            "share_urgency": self.share_urgency,
            "created_at": self.created_at.isoformat(),
            "shared": self.shared,
            "shared_at": self.shared_at.isoformat() if self.shared_at else None,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LifeEvent":
        """Create from dictionary."""
        emotional_impact = data.get("emotional_impact", {})
        if isinstance(emotional_impact, str):
            import json
            try:
                emotional_impact = json.loads(emotional_impact)
            except (json.JSONDecodeError, TypeError):
                emotional_impact = {}
        return cls(
            id=data.get("id"),
            event_type=data.get("event_type", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            emotional_impact=emotional_impact,
            share_urgency=data.get("share_urgency", 0.7),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            shared=data.get("shared", False),
            shared_at=datetime.fromisoformat(data["shared_at"]) if data.get("shared_at") else None,
            source=data.get("source", ""),
        )


# ============= Basic Needs & Room Models =============


@dataclass
class BasicNeedsState:
    """Physical needs that tick over time (Sustenance engine)."""
    hunger: float = 0.0              # 0=full, 1=starving
    last_meal_time: Optional[datetime] = None
    showered_today: bool = False
    morning_routine_done: bool = False
    meals_today: int = 0
    nutrition: float = 0.6           # 0=poorly nourished .. 1=well nourished


@dataclass
class RoomState:
    """Ambient state of the persona's living space (Habitation engine)."""
    candle_lit: bool = False
    music_playing: bool = False
    window_open: bool = False
    tidiness: float = 0.7            # 0=messy, 1=spotless
    home_type: str = "apartment"     # apartment, house, studio, shared flat
    comfort: float = 0.7             # 0=bleak .. 1=cozy (derived from tidiness+ambiance)


@dataclass
class FinancialState:
    """Persona finances — a light ledger that progresses over time.

    The qualitative feeling fields are kept for back-compat; the quantitative
    ledger drives the FinanceSystem dynamics (monthly income on payday, recurring
    expenses, and discretionary spending shaped by spending_habit). Set
    ``enabled = False`` to freeze the dynamics ("allow spending habits or not").
    """
    # Qualitative (existing)
    feeling: str = "comfortable"     # tight, comfortable, flush, saving
    saving_for: Optional[str] = None
    recent_splurge: Optional[str] = None
    # Quantitative ledger
    balance: float = 1200.0          # spendable money on hand
    savings: float = 400.0           # set-aside savings
    monthly_income: float = 2600.0   # net monthly income (fed by the job engine later)
    monthly_expenses: float = 1850.0  # recurring outgoings (rent, bills, food)
    spending_habit: float = 0.5      # 0=frugal .. 1=spender (per persona)
    enabled: bool = True             # whether spending-habit dynamics run
    currency: str = "$"
    last_payday: Optional[datetime] = None
    last_expense_run: Optional[datetime] = None
    recent_purchases: List[str] = field(default_factory=list)


# ============= Career / Job Models =============


@dataclass
class CareerState:
    """Persona's work life — drives income (→ finances) and work stress (→ affect)."""
    occupation: str = ""
    employer: str = ""
    employed: bool = True
    work_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    shift_start_hour: int = 9
    shift_end_hour: int = 17
    monthly_salary: float = 2600.0   # net monthly pay → FinanceSystem income
    workload: float = 0.5            # 0=light .. 1=swamped
    satisfaction: float = 0.6        # 0=miserable .. 1=loves it
    days_worked: int = 0
    last_workday: Optional[datetime] = None
    recent_work_event: Optional[str] = None


# ============= Inebriation Models =============


@dataclass
class InebriationState:
    """Current substance effect state."""
    level: float = 0.0               # 0=sober, 0.3=tipsy, 0.6=drunk, 0.9=very drunk
    substance: str = ""              # "wine", "beer", "cocktail", ""
    started_at: Optional[datetime] = None
    hangover_severity: float = 0.0   # 0-1, next morning after heavy drinking
    last_drink_at: Optional[datetime] = None


# ============= Media & Skill Models =============


@dataclass
class MediaState:
    """What the persona is currently reading/watching/listening to."""
    current_book: Optional[str] = None
    book_progress: float = 0.0
    books_finished: List[str] = field(default_factory=list)
    current_show: Optional[str] = None
    show_progress: float = 0.0
    current_music_obsession: Optional[str] = None


@dataclass
class SkillProgress:
    """Progress on a skill gained through activities."""
    skill_name: str = ""
    level: float = 0.0              # 0-1, very slow progression
    milestones_reached: List[str] = field(default_factory=list)
    last_practiced: Optional[datetime] = None


@dataclass
class ErrandsState:
    """Backlog of everyday errands/chores (Errands engine)."""
    pending: List[str] = field(default_factory=list)    # outstanding errands
    overdue: List[str] = field(default_factory=list)    # past-due errands (nag)
    completed_count: int = 0
    last_added: Optional[datetime] = None


# ============= Social Models =============


@dataclass
class NPC:
    """A person in the persona's social circle."""
    name: str = ""
    relationship: str = ""           # "best friend", "coworker", "sister", etc.
    personality_brief: str = ""
    shared_interests: List[str] = field(default_factory=list)
    contact_frequency: str = "regular"  # daily, regular, occasional


@dataclass
class SocialEvent:
    """Something that happened with an NPC."""
    npc_name: str = ""
    event_type: str = ""             # text_received, hangout, mentioned, call, invitation
    description: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    share_worthy: bool = False


# ============= Tendency Models =============


@dataclass
class BehavioralTendency:
    """A universal human flaw that fluctuates around a per-persona baseline."""
    name: str = ""
    baseline: float = 0.1       # From profile, default low
    current: float = 0.1        # Fluctuates around baseline
    last_surfaced: Optional[datetime] = None


# ============= Identity Models =============


@dataclass
class IdentityFacet:
    """An emergent aspect of self-identity, reinforced by activities."""
    name: str = ""                  # e.g. "creative", "bookworm", "fitness-oriented"
    strength: float = 0.0           # 0-1, how strongly she identifies with this
    evidence: List[str] = field(default_factory=list)  # recent activities that reinforced it
    last_reinforced: Optional[datetime] = None


@dataclass
class PersonPerception:
    """How the persona perceives another person (user or NPC)."""
    person_name: str = ""
    is_user: bool = False           # True for the user, False for NPCs
    perceived_gender: str = ""      # "male", "female", etc. (user demographics)
    perceived_age: int = 0          # 0 = unknown
    trust_level: float = 0.5        # 0-1
    emotional_valence: float = 0.5  # 0=negative, 0.5=neutral, 1=warm
    perceived_traits: List[str] = field(default_factory=list)  # "funny", "caring", "unreliable"
    shared_memories: List[str] = field(default_factory=list)   # brief memory snippets
    last_interaction: Optional[datetime] = None
    interaction_count: int = 0


# ============= Affect Models =============


@dataclass
class MoodState:
    """Background emotional coloring persisting hours-days."""
    current_mood: str = "neutral"          # "blue", "restless", "content", "raw", "neutral"
    intensity: float = 0.0                 # 0-1
    since: Optional[datetime] = None       # When this mood started
    weather_influence: float = 0.0         # How much weather is affecting mood
    seasonal_influence: float = 0.0        # How much season is affecting mood


@dataclass
class StressState:
    """Cumulative pressure from unmet needs and obligations."""
    level: float = 0.0                     # 0-1
    sources: List[str] = field(default_factory=list)  # Active stressors
    coping_capacity: float = 0.7           # 0-1, baseline resilience
    last_relief: Optional[datetime] = None


@dataclass
class LonelinessState:
    """Gap between desired and actual social contact."""
    level: float = 0.0                     # 0-1
    desired_contact_baseline: float = 0.5  # Personality-dependent (introvert=0.3, extrovert=0.7)
    last_meaningful_interaction: Optional[datetime] = None
    lifetime_peak: float = 0.0             # Deepest ever felt


@dataclass
class RegulationState:
    """Emotional regulation capacity (battery model)."""
    capacity: float = 0.7                  # 0-1 current capacity
    baseline: float = 0.7                  # Slowly-moving long-term baseline
    last_depletion_event: Optional[str] = None


@dataclass
class EmpathyState:
    """Emotional contagion tracking."""
    contagion_susceptibility: float = 0.5  # 0-1 (high agreeableness = higher)
    current_absorbed_emotion: Optional[str] = None
    absorbed_intensity: float = 0.0
    empathic_fatigue: float = 0.0          # 0-1, builds from absorbing others' heavy emotions


# ============= Body Models =============


@dataclass
class PhysicalHealthState:
    """General physical wellness."""
    wellness: float = 0.8              # 0-1 general wellness
    active_conditions: List[dict] = field(default_factory=list)
    # Each condition: {"name": "headache", "severity": 0.4, "started_at": ..., "duration_hours": 6}
    body_image: float = 0.6            # satisfaction with own appearance; low = body issues / dissatisfaction
    body_image_baseline: float = 0.6   # per-persona resting set-point body_image drifts toward
    illness: str = ""                  # current acute illness label, "" = healthy (e.g. "a cold", "a stomach bug", "cramps", "a migraine")
    illness_severity: float = 0.0      # 0..1; decays as she recovers
    injury: str = ""                   # current injury label, "" = none (e.g. "a sprained ankle", "a broken wrist")
    injury_severity: float = 0.0       # 0..1; heals slower than illness


@dataclass
class HormonalCycleState:
    """Hormonal cycle tracking (optional per persona)."""
    enabled: bool = False              # Only for personas where appropriate
    cycle_day: int = 1                 # 1-28
    phase: str = "follicular"          # follicular, ovulation, luteal, premenstrual


@dataclass
class PhysicalComfortState:
    """Physical comfort level."""
    level: float = 0.7                 # 0-1
    posture_stiffness: float = 0.0     # Increases with sitting
    temperature_comfort: float = 0.7   # Based on weather + clothing
    pain_level: float = 0.0            # From conditions or exercise


@dataclass
class AppearanceState:
    """Current appearance and outfit."""
    outfit: str = ""                   # Today's outfit description
    hair_state: str = "styled"         # styled, messy, needs_washing
    put_togetherness: float = 0.7      # 0-1, degrades through day


@dataclass
class SleepQualityState:
    """Sleep quality tracking."""
    last_quality: float = 0.7          # 0-1 quality of last sleep
    insomnia_risk: float = 0.0         # Based on stress, caffeine, rumination
    dream_vividness: float = 0.5       # Affects Dream Processing
    consecutive_poor_nights: int = 0


@dataclass
class FitnessState:
    """Fitness trajectory across categories."""
    cardio: float = 0.3                # 0-1
    strength: float = 0.2              # 0-1
    flexibility: float = 0.3           # 0-1
    peak_cardio: float = 0.3           # Historical peak
    peak_strength: float = 0.2
    last_cardio_session: Optional[datetime] = None
    last_strength_session: Optional[datetime] = None
    last_flexibility_session: Optional[datetime] = None


# ============= Cognitive Models =============


@dataclass
class FocusState:
    """Attention and focus quality."""
    quality: float = 0.7              # 0-1 (scattered → flow)
    flow_streak_minutes: int = 0      # Continuous high-focus time
    last_task_switch: Optional[datetime] = None


@dataclass
class RuminationLoop:
    """An active rumination loop."""
    topic: str = ""                    # "Why did I say that to Tyler?"
    intensity: float = 0.0            # 0-1
    started_at: Optional[datetime] = None
    replay_count: int = 0
    trigger: str = ""                  # "conflict", "embarrassment", "failure"


@dataclass
class InnerMonologueEntry:
    """A passing thought in the inner monologue."""
    thought: str = ""
    source: str = ""                   # "activity", "rumination", "curiosity", "environment"
    timestamp: Optional[datetime] = None


@dataclass
class DreamFragment:
    """A dream fragment from sleep."""
    description: str = ""              # "was in a house that kept changing rooms"
    vividness: float = 0.5            # 0-1
    emotional_tone: str = ""           # "anxious", "warm", "surreal"
    source_material: str = ""          # What triggered this dream content
    residue_emotion: str = ""          # Emotion that lingers after waking
    residue_intensity: float = 0.0


@dataclass
class Opinion:
    """A formed opinion on a subject."""
    subject: str = ""                  # "rainy days", "that book", "Tyler's advice"
    stance: str = ""                   # "positive", "negative", "mixed"
    confidence: float = 0.3           # 0-1
    basis: str = ""                    # "experience", "taste", "reasoning"
    formed_at: Optional[datetime] = None
    last_reinforced: Optional[datetime] = None


# ============= Drive Expansion Models =============


@dataclass
class CuriosityQuestion:
    """Something the persona is curious about."""
    topic: str = ""
    intensity: float = 0.5
    sparked_by: str = ""               # "activity", "conversation", "book", "random"
    created_at: Optional[datetime] = None
    explored: bool = False


@dataclass
class AvoidanceItem:
    """Something being avoided."""
    description: str = ""              # "should call the dentist"
    discomfort: float = 0.3            # 0-1
    reason: str = ""                   # "anxiety", "laziness", "fear"
    created_at: Optional[datetime] = None
    deadline: Optional[datetime] = None
    guilt_accumulated: float = 0.0     # Grows over time


@dataclass
class ComfortZoneBoundary:
    """A boundary of the comfort zone."""
    category: str = ""                 # "social", "physical", "creative", "intellectual"
    activity: str = ""                 # Specific activity
    familiarity: float = 0.5          # 0-1 (0=terrifying, 1=routine)
    growth_edge: bool = False          # Just outside current zone
    last_attempted: Optional[datetime] = None
    attempt_count: int = 0
    success_count: int = 0


# ============= Identity Expansion Models =============


@dataclass
class ValueBelief:
    """A core value or belief."""
    name: str = ""                     # "honesty", "independence", "creativity"
    salience: float = 0.5             # 0-1
    tested_by_adversity: bool = False  # Bedrock if tested
    formed_at: Optional[datetime] = None
    aligned_tags: List[str] = field(default_factory=list)  # Activity category tags this value maps to


@dataclass
class SelfEsteemState:
    """Self-esteem tracking."""
    level: float = 0.5                 # 0-1 current
    baseline: float = 0.5             # Slowly-moving long-term baseline
    last_boost_source: str = ""
    last_drain_source: str = ""


@dataclass
class IdealSelfTrait:
    """An aspect of the ideal self."""
    trait: str = ""                     # "confident", "disciplined", "creative"
    importance: float = 0.5            # How much she wants this
    current_alignment: float = 0.3     # How close she is


@dataclass
class TasteProfile:
    """Aesthetic taste in a domain."""
    domain: str = ""                   # "music", "literature", "food", "fashion"
    preferences: List[str] = field(default_factory=list)
    dislikes: List[str] = field(default_factory=list)
    coherence: float = 0.3            # How defined (0=vague, 1=crystallized)
    adventurousness: float = 0.5      # Openness to new things in this domain


@dataclass
class InsideJoke:
    """An inside joke with someone."""
    reference: str = ""                # "the pigeon incident"
    origin: str = ""                   # Brief origin story
    participants: List[str] = field(default_factory=list)
    callback_count: int = 0
    created_at: Optional[datetime] = None
    last_referenced: Optional[datetime] = None


@dataclass
class HumorProfileState:
    """Humor style and triggers."""
    style: str = ""                    # "dry", "silly", "witty", "absurdist"
    triggers: List[str] = field(default_factory=list)
    inside_jokes: List[InsideJoke] = field(default_factory=list)
    laughter_threshold: float = 0.5    # Modulated by mood


# ============= Social Expansion Models =============


@dataclass
class RelationshipArc:
    """Tracks the trajectory of a relationship over time."""
    npc_name: str = ""
    closeness: float = 0.5            # 0-1
    trend: str = "stable"              # "deepening", "stable", "cooling", "strained", "repairing"
    last_meaningful_interaction: Optional[datetime] = None
    unresolved_tension: Optional[str] = None
    shared_history_depth: int = 0      # Number of shared events


@dataclass
class SocialObligation:
    """A social debt or commitment."""
    description: str = ""              # "Tyler asked for help moving"
    person: str = ""
    urgency: float = 0.3              # 0-1
    deadline: Optional[datetime] = None
    created_at: Optional[datetime] = None
    overdue: bool = False


@dataclass
class SocialConflict:
    """An interpersonal conflict."""
    parties: List[str] = field(default_factory=list)
    cause: str = ""
    severity: float = 0.3             # 0-1
    status: str = "unresolved"         # "unresolved", "cooling", "resolved"
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


@dataclass
class FriendGroup:
    """A social circle or group."""
    name: str = ""                     # "the girls", "the band"
    members: List[str] = field(default_factory=list)
    energy: str = "positive"           # "positive", "tense", "quiet"
    her_role: str = ""                 # "the planner", "the funny one"
    last_group_event: Optional[datetime] = None


@dataclass
class SocialBatteryState:
    """Social energy battery model."""
    charge: float = 0.7               # 0-1 current
    capacity: float = 0.7             # Max (introvert=0.5, extrovert=0.9)
    recharge_rate: float = 0.05       # Per rest tick
    drain_rate: float = 0.03          # Per social tick


# ============= World Expansion Models =============


@dataclass
class Possession:
    """A meaningful possession."""
    name: str = ""
    description: str = ""
    condition: str = "good"            # "new", "good", "worn", "broken"
    sentimental_value: float = 0.0     # 0-1
    utility: str = ""                  # "daily", "occasional", "decorative"
    acquired_at: Optional[datetime] = None


@dataclass
class AmbientSenseSnapshot:
    """Current sensory environment."""
    sounds: List[str] = field(default_factory=list)
    smells: List[str] = field(default_factory=list)
    temperature_comfort: str = "comfortable"
    light_quality: str = "natural"


@dataclass
class NeighborhoodPlace:
    """A place in the neighborhood."""
    name: str = ""                     # "Blue Note Cafe"
    place_type: str = ""               # "cafe", "park", "bookshop", "gym"
    status: str = "open"               # "open", "closed", "renovating", "new"
    familiarity: float = 0.3          # 0-1
    emotional_association: str = ""    # "comfort", "excitement", "nostalgia"
    last_visit: Optional[datetime] = None


@dataclass
class RoutinePattern:
    """A detected behavioral routine."""
    name: str = ""                     # "morning routine"
    activities: List[str] = field(default_factory=list)
    consistency_streak: int = 0        # Days in a row
    comfort_level: float = 0.3        # Grows with consistency
    staleness: float = 0.0            # Grows with too much repetition


@dataclass
class CreativeArtifact:
    """Something the persona created."""
    artifact_type: str = ""            # "poem", "sketch", "playlist", "recipe"
    title: str = ""
    quality_feeling: float = 0.5      # Subjective 0-1
    associated_emotions: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    shared_with: List[str] = field(default_factory=list)


# ============= Memory & Time Models =============


@dataclass
class TimePerceptionState:
    """Subjective time perception."""
    subjective_speed: float = 0.5      # 0=dragging, 0.5=normal, 1=flying
    last_assessment: Optional[datetime] = None


@dataclass
class SeasonalConsciousnessState:
    """Awareness of seasonal patterns."""
    current_season_feeling: str = ""   # "autumn melancholy", "spring restlessness"
    season_memory_count: Dict[str, int] = field(default_factory=dict)
    years_experienced: int = 0


@dataclass
class NostalgiaEvent:
    """A nostalgia trigger event."""
    trigger: str = ""                  # "song", "smell", "season", "anniversary"
    memory_reference: str = ""         # What it brought back
    intensity: float = 0.3
    bittersweet: float = 0.5          # 0=bitter, 1=sweet
    timestamp: Optional[datetime] = None


@dataclass
class LifeChapter:
    """A chapter in the life narrative."""
    title: str = ""                    # "the month I got into cooking"
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    summary: str = ""
    turning_points: List[str] = field(default_factory=list)
    dominant_emotions: List[str] = field(default_factory=list)


@dataclass
class TemporalRhythm:
    """A detected temporal pattern."""
    scale: str = ""                    # "weekly", "monthly", "annual"
    pattern: str = ""                  # "Monday heaviness", "November blues"
    confidence: float = 0.0           # 0-1
    first_noticed: Optional[datetime] = None


@dataclass
class Anticipation:
    """Anticipation of a future event."""
    event: str = ""
    feeling: str = "neutral"           # "excited", "dreading", "curious"
    intensity: float = 0.3
    date: Optional[datetime] = None


@dataclass
class CalendarEntry:
    """A user calendar event extracted from conversation."""
    id: Optional[int] = None
    event_name: str = ""
    event_date: Optional[datetime] = None
    date_str: str = ""
    recurring: bool = False
    feeling: str = "neutral"
    importance: float = 0.5
    source_memory_content: str = ""
    triggered: bool = False
    promoted_to_anniversary: bool = False
    created_at: Optional[datetime] = None


# ============= Expression & Perception Models =============

@dataclass
class ConnectionState:
    """Tracks user availability/connection awareness."""
    is_online: bool = False
    last_message_at: Optional[datetime] = None
    avg_response_time_seconds: float = 0.0
    time_since_last_message_hours: float = 0.0
    likely_at_work: bool = False
    late_night_chat: bool = False

@dataclass
class CommunicationStyleState:
    """Tracks evolving communication style with user."""
    formality: float = 0.7             # 1=formal, 0=intimate shorthand
    avg_message_length: str = "measured"  # "terse", "measured", "comfortable", "variable"
    emoji_frequency: float = 0.2       # 0-1
    humor_density: float = 0.2         # 0-1
    vulnerability_openness: float = 0.2  # 0-1
    relationship_stage: str = "early"  # "early", "comfortable", "deep"


# ============= Continuity Models =============

@dataclass
class Anniversary:
    """An anniversary or recurring meaningful date."""
    name: str = ""
    date: str = ""                     # MM-DD or YYYY-MM-DD
    emotional_weight: float = 0.3
    yearly: bool = True
    first_occurrence: Optional[datetime] = None

@dataclass
class GrowthSnapshot:
    """Periodic snapshot of growth for comparison."""
    date: Optional[datetime] = None
    skill_levels: Dict[str, float] = field(default_factory=dict)
    identity_facets: Dict[str, float] = field(default_factory=dict)
    relationship_trust: float = 0.0
    notable_changes: List[str] = field(default_factory=list)

@dataclass
class RelationshipMilestone:
    """A milestone in the user-persona relationship."""
    name: str = ""
    description: str = ""
    emotional_weight: float = 0.5
    date: Optional[datetime] = None
    detected_retrospectively: bool = True


# ============= Shadow Models =============


@dataclass
class ShadowState:
    """The persona's darker inner psychology and moral tension."""
    # Felt insecurity / preoccupation
    unease: float = 0.2              # diffuse dread / preoccupation / feeling unsafe
    felt_safety: float = 0.7         # sense of security in the relationship/world (high = secure)
    doubt: float = 0.2              # self-doubt, second-guessing
    # Temptation & transgression
    temptation: float = 0.1         # current pull toward crossing a line
    inhibition: float = 0.6         # restraint: high = proper/controlled, low = uninhibited/impulsive
    attention_seeking: float = 0.2  # drive for attention/validation
    transgression_pressure: float = 0.0  # built-up urge to act out / rebel
    recent_transgressions: List[str] = field(default_factory=list)
    intrusive_theme: str = ""       # the intrusive thought currently pressing
    intrusive_winning: bool = False  # is she losing the fight against it right now
    # Concealment
    concealment_load: float = 0.0   # weight of what she's hiding
    masking: float = 0.2            # how much of a front she's putting on now
    secrets: List[str] = field(default_factory=list)
    last_lie: str = ""
    # Conscience
    guilt: float = 0.0
    shame: float = 0.1              # "I am bad/unworthy" (about the SELF; guilt is about an ACT)
    remorse: float = 0.0
    urge_to_confess: float = 0.0
    # Coping
    coping_style: str = "healthy"   # healthy | avoidant | self_soothing | destructive
    maladaptive_coping_active: bool = False
    # Power / relational stance
    power_stance: float = 0.0       # -1 submissive .. 0 equal .. +1 dominant (toward user)
    autonomy: float = 0.5           # "being her own person" (high) vs pushover/people-pleaser (low)
    superiority: float = 0.1        # felt superiority / contempt
    # Trait seeds (set at init from profile; slow/no decay)
    rebelliousness: float = 0.3     # disposition to defy / be stubborn
    deceptiveness: float = 0.15     # disposition to hide/lie
    dominance_disposition: float = 0.0  # baseline lean of power_stance
    conscientiousness: float = 0.6  # how strongly conscience reacts (guilt sensitivity)
    vice_proneness: float = 0.2     # pull toward bad coping / substances / indulgence
    last_update: Optional[datetime] = None
