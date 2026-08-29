"""
Memory & Time Engine

Tracks subjective time perception, seasonal consciousness, nostalgia,
life narrative, temporal rhythms, and future anticipation.
"""

import json
import random
from datetime import datetime
from typing import List, Optional

from ..models import (
    TimePerceptionState,
    SeasonalConsciousnessState,
    NostalgiaEvent,
    LifeChapter,
    TemporalRhythm,
    Anticipation,
)

logger = __import__("logging").getLogger(__name__)

# Season -> feeling associations
SEASON_FEELINGS = {
    "spring": ["spring restlessness", "hopeful energy", "renewal feeling"],
    "summer": ["summer languor", "warm contentment", "expansive mood"],
    "autumn": ["autumn melancholy", "cozy nostalgia", "reflective calm"],
    "winter": ["winter introspection", "quiet stillness", "hibernation mode"],
}

# Activity -> nostalgia trigger chance
NOSTALGIA_ACTIVITIES = {
    "listening to music": ("song", 0.15),
    "cooking a meal": ("smell", 0.08),
    "baking something": ("smell", 0.10),
    "reading": ("passage", 0.05),
    "stargazing": ("season", 0.12),
    "walking in the park": ("season", 0.08),
    "having coffee with a friend": ("social", 0.06),
    "catching up with family": ("social", 0.10),
}

# Nostalgia memory fragments (templated)
NOSTALGIA_MEMORIES = [
    "that time we stayed up way too late",
    "the first time she tried making pasta from scratch",
    "a warm afternoon that felt like it would last forever",
    "the sound of rain through an open window, years ago",
    "a song that used to play on repeat during a different time",
    "the smell of her mom's kitchen on a Sunday",
    "a laugh she hasn't thought about in a while",
    "the feeling of a new city for the first time",
    "an old friend's voice she can barely remember",
    "a book she read in one sitting on a rainy day",
]

# Day-of-week patterns
WEEKDAY_MOODS = {
    0: "Monday heaviness",
    4: "Friday lightness",
    6: "Sunday evening ambivalence",
}


class MemoryTimeSystem:
    """Tracks time perception, nostalgia, seasonal feeling, life narrative."""

    def __init__(self, rng=None):
        self._time_perception = TimePerceptionState()
        self._rng = rng if rng is not None else random
        self._seasonal = SeasonalConsciousnessState()
        self._nostalgia_log: List[NostalgiaEvent] = []
        self._life_chapters: List[LifeChapter] = []
        self._rhythms: List[TemporalRhythm] = []
        self._anticipations: List[Anticipation] = []
        self._tick_count: int = 0

    # ============= Tick =============

    def tick(self, current_activity: str, mood: str, season: str,
             time_of_day: str) -> Optional[NostalgiaEvent]:
        """Per-tick update. Returns nostalgia event if triggered."""
        self._tick_count += 1

        # Time perception update
        self._update_time_perception(current_activity, mood)

        # Seasonal consciousness
        self._update_seasonal(season)

        # Nostalgia check (~every other tick to reduce frequency)
        nostalgia = None
        if self._tick_count % 2 == 0:
            nostalgia = self._check_nostalgia(current_activity, season)

        # Detect weekly rhythm (every 20 ticks)
        if self._tick_count % 20 == 0:
            self._detect_weekly_rhythm()

        return nostalgia

    # ============= Time Perception =============

    def _update_time_perception(self, activity: str, mood: str):
        """Update subjective time speed based on activity and mood."""
        speed = 0.5  # baseline

        # Flow activities make time fly
        flow_activities = {"reading", "writing poetry", "sketching ideas",
                          "creating a playlist", "exploring a new idea",
                          "learning something new"}
        if activity in flow_activities:
            speed += 0.15

        # Social activities speed time
        social_activities = {"texting a friend", "having coffee with a friend",
                            "catching up with family"}
        if activity in social_activities:
            speed += 0.10

        # Boring or waiting slows time
        boring_activities = {"waiting", "nothing to do", "restless"}
        if activity in boring_activities:
            speed -= 0.20

        # Mood effects
        if mood in ("bored", "restless", "anxious"):
            speed -= 0.10
        elif mood in ("joyful", "excited", "content"):
            speed += 0.10

        # Smooth update (weighted average)
        self._time_perception.subjective_speed = (
            self._time_perception.subjective_speed * 0.7 + speed * 0.3
        )
        self._time_perception.subjective_speed = max(0.0, min(1.0, self._time_perception.subjective_speed))
        self._time_perception.last_assessment = datetime.now()

    # ============= Seasonal Consciousness =============

    def _update_seasonal(self, season: str):
        """Deepen seasonal awareness over time."""
        if not season:
            return

        season_lower = season.lower()

        # Track season encounters
        if season_lower not in self._seasonal.season_memory_count:
            self._seasonal.season_memory_count[season_lower] = 0
        self._seasonal.season_memory_count[season_lower] += 1

        # Update feeling based on current season
        feelings = SEASON_FEELINGS.get(season_lower, [])
        if feelings:
            count = self._seasonal.season_memory_count[season_lower]
            # First time through a season: raw experience
            if count < 10:
                self._seasonal.current_season_feeling = feelings[0]
            else:
                # Deeper, more nuanced feeling after repeated experience
                idx = min(len(feelings) - 1, count // 30)
                self._seasonal.current_season_feeling = feelings[idx]

        # Years experienced (rough: if all 4 seasons have > 30 ticks)
        if all(self._seasonal.season_memory_count.get(s, 0) > 30
               for s in ("spring", "summer", "autumn", "winter")):
            min_count = min(self._seasonal.season_memory_count.get(s, 0)
                          for s in ("spring", "summer", "autumn", "winter"))
            self._seasonal.years_experienced = min_count // 30

    # ============= Nostalgia =============

    def _check_nostalgia(self, activity: str, season: str) -> Optional[NostalgiaEvent]:
        """Check if current activity/season triggers nostalgia."""
        trigger_info = NOSTALGIA_ACTIVITIES.get(activity)
        if not trigger_info:
            # Small chance from season transition
            if season and self._rng.random() < 0.02:
                trigger_info = ("season", 0.10)
            else:
                return None

        trigger_type, chance = trigger_info
        if self._rng.random() > chance:
            return None

        memory = self._rng.choice(NOSTALGIA_MEMORIES)
        bittersweet = self._rng.uniform(0.3, 0.8)

        event = NostalgiaEvent(
            trigger=trigger_type,
            memory_reference=memory,
            intensity=self._rng.uniform(0.2, 0.6),
            bittersweet=bittersweet,
            timestamp=datetime.now(),
        )
        self._nostalgia_log.append(event)
        # Keep last 20
        if len(self._nostalgia_log) > 20:
            self._nostalgia_log = self._nostalgia_log[-20:]

        return event

    def get_recent_nostalgia(self, limit: int = 3) -> List[NostalgiaEvent]:
        """Get recent nostalgia events."""
        return self._nostalgia_log[-limit:]

    # ============= Life Narrative =============

    def add_life_chapter(self, title: str, summary: str,
                         turning_points: Optional[List[str]] = None,
                         dominant_emotions: Optional[List[str]] = None):
        """Add a life chapter (typically from LLM synthesis)."""
        chapter = LifeChapter(
            title=title,
            period_start=datetime.now(),
            summary=summary,
            turning_points=turning_points or [],
            dominant_emotions=dominant_emotions or [],
        )
        # Close previous chapter
        if self._life_chapters:
            self._life_chapters[-1].period_end = datetime.now()
        self._life_chapters.append(chapter)
        # Keep last 10
        if len(self._life_chapters) > 10:
            self._life_chapters = self._life_chapters[-10:]

    def get_current_chapter(self) -> Optional[LifeChapter]:
        """Get the current life chapter."""
        return self._life_chapters[-1] if self._life_chapters else None

    # ============= Temporal Rhythms =============

    def _detect_weekly_rhythm(self):
        """Detect weekly patterns from day-of-week moods and seasonal transitions."""
        now = datetime.now()
        weekday = now.weekday()

        # Day-of-week patterns
        mood_pattern = WEEKDAY_MOODS.get(weekday)
        if mood_pattern:
            for r in self._rhythms:
                if r.pattern == mood_pattern:
                    r.confidence = min(1.0, r.confidence + 0.02)
                    return
            if len(self._rhythms) < 10:
                self._rhythms.append(TemporalRhythm(
                    scale="weekly",
                    pattern=mood_pattern,
                    confidence=0.1,
                    first_noticed=now,
                ))

        # Monthly patterns (detect from seasonal data after enough ticks)
        month = now.month
        monthly_patterns = {
            1: "January fresh start energy",
            3: "March restlessness",
            6: "June expansiveness",
            9: "September back-to-routine",
            11: "November blues",
            12: "December reflection",
        }
        monthly_pattern = monthly_patterns.get(month)
        if monthly_pattern and self._tick_count > 100:
            for r in self._rhythms:
                if r.pattern == monthly_pattern:
                    r.confidence = min(1.0, r.confidence + 0.01)
                    return
            if len(self._rhythms) < 10:
                self._rhythms.append(TemporalRhythm(
                    scale="monthly",
                    pattern=monthly_pattern,
                    confidence=0.05,
                    first_noticed=now,
                ))

        # Decay stale rhythms
        for r in self._rhythms:
            r.confidence = max(0.0, r.confidence - 0.001)

    def get_active_rhythms(self, min_confidence: float = 0.2) -> List[TemporalRhythm]:
        """Get rhythms with sufficient confidence."""
        return [r for r in self._rhythms if r.confidence >= min_confidence]

    # ============= Anticipation =============

    def add_anticipation(self, event: str, feeling: str = "curious",
                         intensity: float = 0.3, date: Optional[datetime] = None):
        """Add an anticipated future event."""
        self._anticipations.append(Anticipation(
            event=event,
            feeling=feeling,
            intensity=intensity,
            date=date,
        ))
        # Keep last 5
        if len(self._anticipations) > 5:
            self._anticipations = self._anticipations[-5:]

    def get_anticipations(self) -> List[Anticipation]:
        """Get current anticipations, filtering expired ones."""
        now = datetime.now()
        active = [a for a in self._anticipations
                  if not a.date or a.date > now]
        self._anticipations = active
        return active

    # ============= Activity / Message Hooks =============

    def on_activity(self, activity_name: str):
        """Engaging activities make time feel faster; trigger nostalgia checks."""
        # Flow activities speed up time more
        flow_activities = {"reading", "writing poetry", "sketching ideas",
                          "creating a playlist", "exploring a new idea",
                          "learning something new"}
        boost = 0.04 if activity_name in flow_activities else 0.02
        self._time_perception.subjective_speed = min(
            1.0, self._time_perception.subjective_speed + boost
        )
        # Check for nostalgia trigger from activity
        trigger_info = NOSTALGIA_ACTIVITIES.get(activity_name)
        if trigger_info:
            trigger_type, chance = trigger_info
            import random as _rng
            if _rng.random() < chance * 0.5:  # Reduced chance vs tick
                memory = _rng.choice(NOSTALGIA_MEMORIES)
                event = NostalgiaEvent(
                    trigger=trigger_type,
                    memory_reference=memory,
                    intensity=_rng.uniform(0.15, 0.4),
                    bittersweet=_rng.uniform(0.3, 0.7),
                    timestamp=datetime.now(),
                )
                self._nostalgia_log.append(event)
                if len(self._nostalgia_log) > 20:
                    self._nostalgia_log = self._nostalgia_log[-20:]

    def on_user_message(self, text: str = ""):
        """Social interaction speeds up time and deepens temporal awareness."""
        self._time_perception.subjective_speed = min(
            1.0, self._time_perception.subjective_speed + 0.01
        )
        # Weekday awareness from conversation timing
        now = datetime.now()
        weekday = now.weekday()
        mood_pattern = WEEKDAY_MOODS.get(weekday)
        if mood_pattern:
            for r in self._rhythms:
                if r.pattern == mood_pattern:
                    r.confidence = min(1.0, r.confidence + 0.01)
                    break

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        result = {}
        # Time perception
        speed = self._time_perception.subjective_speed
        if speed < 0.3:
            result["time_feeling"] = "time is dragging"
        elif speed > 0.7:
            result["time_feeling"] = "time is flying"

        # Season
        if self._seasonal.current_season_feeling:
            result["seasonal_feeling"] = self._seasonal.current_season_feeling

        # Recent nostalgia
        recent = self.get_recent_nostalgia(1)
        if recent:
            n = recent[0]
            result["recent_nostalgia"] = {
                "trigger": n.trigger,
                "memory": n.memory_reference,
            }

        # Current chapter
        chapter = self.get_current_chapter()
        if chapter:
            result["life_chapter"] = chapter.title

        # Anticipations
        anticipations = self.get_anticipations()
        if anticipations:
            result["looking_forward_to"] = [
                {"event": a.event, "feeling": a.feeling}
                for a in anticipations[:2]
            ]

        return result

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "time_perception": round(self._time_perception.subjective_speed, 2),
            "seasonal_feeling": self._seasonal.current_season_feeling,
            "years_experienced": self._seasonal.years_experienced,
            "nostalgia_log_count": len(self._nostalgia_log),
            "life_chapters_count": len(self._life_chapters),
            "current_chapter": self._life_chapters[-1].title if self._life_chapters else None,
            "rhythms": [
                {"pattern": r.pattern, "confidence": round(r.confidence, 2)}
                for r in self._rhythms if r.confidence > 0.1
            ],
            "anticipations": [a.event for a in self._anticipations],
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "time_speed": self._time_perception.subjective_speed,
            "time_last_assessment": (
                self._time_perception.last_assessment.isoformat()
                if self._time_perception.last_assessment else None
            ),
            "seasonal_feeling": self._seasonal.current_season_feeling,
            "season_memory_count": json.dumps(self._seasonal.season_memory_count),
            "years_experienced": self._seasonal.years_experienced,
            "nostalgia_log": json.dumps([
                {
                    "trigger": n.trigger,
                    "memory_reference": n.memory_reference,
                    "intensity": n.intensity,
                    "bittersweet": n.bittersweet,
                    "timestamp": n.timestamp.isoformat() if n.timestamp else None,
                }
                for n in self._nostalgia_log
            ]),
            "life_chapters": json.dumps([
                {
                    "title": c.title,
                    "period_start": c.period_start.isoformat() if c.period_start else None,
                    "period_end": c.period_end.isoformat() if c.period_end else None,
                    "summary": c.summary,
                    "turning_points": c.turning_points,
                    "dominant_emotions": c.dominant_emotions,
                }
                for c in self._life_chapters
            ]),
            "rhythms": json.dumps([
                {
                    "scale": r.scale,
                    "pattern": r.pattern,
                    "confidence": r.confidence,
                    "first_noticed": r.first_noticed.isoformat() if r.first_noticed else None,
                }
                for r in self._rhythms
            ]),
            "anticipations": json.dumps([
                {
                    "event": a.event,
                    "feeling": a.feeling,
                    "intensity": a.intensity,
                    "date": a.date.isoformat() if a.date else None,
                }
                for a in self._anticipations
            ]),
            "tick_count": self._tick_count,
        }

    @classmethod
    def from_dict(cls, data: dict, rng=None) -> "MemoryTimeSystem":
        """Deserialize from DB."""
        system = cls(rng=rng)
        if not data:
            return system

        # Time perception
        system._time_perception.subjective_speed = data.get("time_speed", 0.5)
        ts = data.get("time_last_assessment")
        if ts:
            try:
                system._time_perception.last_assessment = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        # Seasonal
        system._seasonal.current_season_feeling = data.get("seasonal_feeling", "")
        raw = data.get("season_memory_count", "{}")
        try:
            system._seasonal.season_memory_count = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            system._seasonal.season_memory_count = {}
        system._seasonal.years_experienced = data.get("years_experienced", 0)

        # Nostalgia log
        raw = data.get("nostalgia_log", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._nostalgia_log = [
            NostalgiaEvent(
                trigger=n.get("trigger", ""),
                memory_reference=n.get("memory_reference", ""),
                intensity=n.get("intensity", 0.3),
                bittersweet=n.get("bittersweet", 0.5),
                timestamp=datetime.fromisoformat(n["timestamp"]) if n.get("timestamp") else None,
            )
            for n in items
        ]

        # Life chapters
        raw = data.get("life_chapters", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._life_chapters = [
            LifeChapter(
                title=c.get("title", ""),
                period_start=datetime.fromisoformat(c["period_start"]) if c.get("period_start") else None,
                period_end=datetime.fromisoformat(c["period_end"]) if c.get("period_end") else None,
                summary=c.get("summary", ""),
                turning_points=c.get("turning_points", []),
                dominant_emotions=c.get("dominant_emotions", []),
            )
            for c in items
        ]

        # Rhythms
        raw = data.get("rhythms", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._rhythms = [
            TemporalRhythm(
                scale=r.get("scale", ""),
                pattern=r.get("pattern", ""),
                confidence=r.get("confidence", 0.0),
                first_noticed=datetime.fromisoformat(r["first_noticed"]) if r.get("first_noticed") else None,
            )
            for r in items
        ]

        # Anticipations
        raw = data.get("anticipations", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            items = []
        system._anticipations = [
            Anticipation(
                event=a.get("event", ""),
                feeling=a.get("feeling", "neutral"),
                intensity=a.get("intensity", 0.3),
                date=datetime.fromisoformat(a["date"]) if a.get("date") else None,
            )
            for a in items
        ]

        system._tick_count = data.get("tick_count", 0)
        return system
