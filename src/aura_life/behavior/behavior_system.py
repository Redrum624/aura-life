"""
Behavior Engine

Tracks behavioral patterns and creative output:
- Routine detection: auto-detect from repeated activity patterns
- Habits: a dated activity history whose comfort and staleness, per part of her day, reweight her planner's choices
- Creative artifacts: poems, sketches, playlists created during activities
- Ambient senses: derived from location + weather + time
- Possessions: meaningful objects with sentimental value
- Neighborhood: familiar places with emotional associations
"""

import json
import random
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from ..models import (
    RoutinePattern, CreativeArtifact,
    AmbientSenseSnapshot, Possession, NeighborhoodPlace,
)

logger = __import__("logging").getLogger(__name__)

# ---- DESIGN VALUES: habits that drift over days (0.5.0) -------------------------------------------------------------
# None is measured and none is the owner's yet: the owner's eye sets them. One line each says why.
#
# The rule. Per part of her day (habit_band) and activity, her lived ticks of the last four weeks are counted, each
# weighted 0.5 ** (age_days / HABIT_HALF_LIFE_DAYS) (a tick dated after `now`, a clock set back, is not counted);
# `share` is the activity's part of that band's weighted free-time ticks.
#   comfort   = min(1, share / HABIT_PEAK_SHARE)                  -- what she has done often lately pulls her back
#   staleness = clamp(share / HABIT_PEAK_SHARE - 1, 0, 2)          -- past the peak, too much of it pushes her away
#   pull      = confidence * (comfort - staleness), in [-1, 1]: 0 at no share, +1 at the peak, 0 at twice it, -1 from
#               three times it;  confidence = min(1, band ticks / HABIT_FULL_EVIDENCE)
#   factor    = HABIT_MAX_RATIO ** pull, in [1 / R, R] (R = HABIT_MAX_RATIO)
# The planner (and her own picks between slots) multiplies a candidate's SCORE by its factor before its cut to the best
# few, so a habit can bring an activity into the choice or take one out; the bound is on the score: x R up, / R down.

# What she did 3.5 days ago counts half as much as today: a habit builds and fades on the scale of a week, not a day.
HABIT_HALF_LIFE_DAYS = 3.5
# Comfort peaks when an activity fills 15% of a part of her day lately (about 40 minutes of a four-hour morning, daily).
HABIT_PEAK_SHARE = 0.15
# A habit multiplies an activity's score in a choice by at most x1.5 up or /1.5 down: her days shift, never lock.
HABIT_MAX_RATIO = 1.5
# Full strength once a part of her day holds 60 weighted ticks (20 hours of free time in it): habits form over a week.
HABIT_FULL_EVIDENCE = 60.0
# The dated history keeps four weeks: at the half-life an older tick would weigh under 0.4%.
HABIT_HISTORY_DAYS = 28
# The prompt names a habit once its pull is half its full strength either way (comforting, or had a lot of it lately).
HABIT_SHOWN_PULL = 0.5


def habit_band(hour: int) -> str:
    """The part of her day a local hour belongs to, as habits count it (the planner's morning / afternoon split at 12
    and 17; evening ends at 22, when the AI persona's night rhythm begins)."""
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"

# Activity -> creative artifact type
CREATIVE_ACTIVITIES = {
    "writing poetry": "poem",
    "sketching ideas": "sketch",
    "creating a playlist": "playlist",
    "trying a new recipe": "recipe",
    "baking something": "recipe",
}

# Location + weather -> ambient senses
AMBIENT_SOUNDS = {
    "home": ["soft hum of the fridge", "clock ticking"],
    "cafe": ["espresso machine", "quiet chatter", "dishes clinking"],
    "park": ["birds singing", "leaves rustling", "distant laughter"],
    "library": ["pages turning", "hushed whispers"],
    "gym": ["weights clanking", "music playing"],
}
RAIN_SOUNDS = ["rain pattering on windows", "distant thunder"]
NIGHT_SOUNDS = ["crickets", "distant traffic"]

AMBIENT_SMELLS = {
    "home": ["clean laundry", "something cooking"],
    "cafe": ["fresh coffee", "pastries"],
    "park": ["fresh-cut grass", "flowers"],
    "kitchen": ["spices", "something baking"],
}

LIGHT_QUALITY = {
    "morning": "golden morning light",
    "afternoon": "bright daylight",
    "evening": "warm lamplight",
    "night": "soft ambient glow",
    "late_night": "dim blue light",
}


class BehaviorSystem:
    """Tracks routines, habits, creative output, ambient senses, possessions, neighborhood."""

    # Four weeks of her 20-minute activity tick (72 a day): the dated history never holds more, whatever the tick rate.
    MAX_ACTIVITY_LOG = HABIT_HISTORY_DAYS * 72

    def __init__(self):
        self._routines: Dict[str, RoutinePattern] = {}
        self._creative_portfolio: List[CreativeArtifact] = []
        self._ambient: AmbientSenseSnapshot = AmbientSenseSnapshot()
        self._possessions: List[Possession] = []
        self._neighborhood: Dict[str, NeighborhoodPlace] = {}
        self._activity_history: List[str] = []  # last N activities for routine detection
        # The dated history habits are learned from: (activity, world-clock instant, her local hour), oldest first.
        self._activity_log: List[Tuple[str, datetime, int]] = []

    # ============= Tick =============

    def tick(self, location: str, weather: str, time_of_day: str):
        """Per-tick ambient sense update."""
        self._update_ambient(location, weather, time_of_day)

    # ============= Routines =============

    def track_activity(self, activity_name: str, at: Optional[datetime] = None, hour: Optional[int] = None):
        """Track activity for routine detection, and -- given the instant she lived it -- in the dated history.

        ``at`` is the world clock's (naive) instant, ``hour`` her local hour (default ``at.hour``). Without ``at``
        nothing is dated: a catch-up replays hours she did not live, and habits must not learn from them.
        """
        if at is not None:
            newest = max((e[1] for e in self._activity_log), default=at)
            self._activity_log.append((activity_name, at, at.hour if hour is None else int(hour)))
            # Pruned by age: four weeks older than this tick AND than the newest before it, so one tick with the clock
            # far ahead cannot wipe her history (a real absence prunes it from the tick after).
            cutoff = min(at, newest) - timedelta(days=HABIT_HISTORY_DAYS)
            self._activity_log = [e for e in self._activity_log if e[1] >= cutoff][-self.MAX_ACTIVITY_LOG:]
        self._activity_history.append(activity_name)
        self._activity_history = self._activity_history[-50:]  # Keep last 50

        # Count occurrences in recent history
        count = self._activity_history.count(activity_name)
        if count >= 3:
            if activity_name not in self._routines:
                self._routines[activity_name] = RoutinePattern(
                    name=activity_name,
                    activities=[activity_name],
                )
            routine = self._routines[activity_name]
            routine.consistency_streak += 1
            routine.comfort_level = min(1.0, routine.comfort_level + 0.01)
            # Staleness from too much repetition
            if routine.consistency_streak > 10:
                routine.staleness = min(1.0, routine.staleness + 0.005)
        # Decay non-practiced routines
        for name, r in self._routines.items():
            if name != activity_name:
                r.consistency_streak = max(0, r.consistency_streak - 1)
                if r.consistency_streak == 0:
                    r.staleness = max(0.0, r.staleness - 0.01)

    def get_established_routines(self, limit: int = 3) -> List[RoutinePattern]:
        """Get routines with significant comfort level."""
        established = [r for r in self._routines.values() if r.comfort_level > 0.3]
        return sorted(established, key=lambda r: r.comfort_level, reverse=True)[:limit]

    def get_stale_routines(self) -> List[RoutinePattern]:
        """Get routines that have become boring (high staleness)."""
        return [r for r in self._routines.values()
                if r.staleness > 0.4 and r.comfort_level > 0.3]

    def detect_staleness(self) -> List[str]:
        """Detect when activity patterns have become too repetitive.

        Returns list of activity names that feel stale.
        """
        stale = []
        # Check routines with high staleness
        for r in self._routines.values():
            if r.staleness > 0.5 and r.consistency_streak > 15:
                stale.append(r.name)
        # Check if recent history is too monotonous
        if len(self._activity_history) >= 10:
            recent = self._activity_history[-10:]
            unique = set(recent)
            if len(unique) <= 3:
                stale.append("overall_variety")
        return stale

    # ============= Habits (the dated history) =============

    @property
    def activity_log(self) -> List[Tuple[str, datetime, int]]:
        """The dated history, oldest first: (activity, world-clock instant, her local hour)."""
        return list(self._activity_log)

    def habits(self, now: datetime, exclude: Iterable[str] = ()) -> List[dict]:
        """Her habits at ``now`` (world clock), one dict per part of her day and activity she has lived in it:
        ``band``, ``name``, ``count`` (decayed ticks), ``share``, ``comfort``, ``staleness``, ``pull``, ``factor``
        (the rule is in the DESIGN VALUES block above). ``exclude`` names activities no habit forms on (day anchors,
        sleep): they are left out of the shares too. Ticks dated after ``now`` or over four weeks before it count
        for nothing."""
        skip = set(exclude)
        counts: Dict[str, Dict[str, float]] = {}
        for name, at, hour in self._activity_log:
            age_days = (now - at).total_seconds() / 86400.0
            if name in skip or not 0.0 <= age_days <= HABIT_HISTORY_DAYS:
                continue
            band = counts.setdefault(habit_band(hour), {})
            band[name] = band.get(name, 0.0) + 0.5 ** (age_days / HABIT_HALF_LIFE_DAYS)
        out = []
        for band, names in counts.items():
            total = sum(names.values())   # > 0: a band exists only once a tick (weight > 0) is in it
            confidence = min(1.0, total / HABIT_FULL_EVIDENCE)
            for name, count in names.items():
                share = count / total
                comfort = min(1.0, share / HABIT_PEAK_SHARE)
                staleness = min(2.0, max(0.0, share / HABIT_PEAK_SHARE - 1.0))
                pull = confidence * (comfort - staleness)
                out.append({
                    "band": band, "name": name, "count": count, "share": share,
                    "comfort": comfort, "staleness": staleness, "pull": pull,
                    "factor": HABIT_MAX_RATIO ** pull,
                })
        return out

    def habit_factors(self, now: datetime, exclude: Iterable[str] = ()) -> Dict[str, Dict[str, float]]:
        """``{band: {activity: factor}}`` at ``now``, for the planner; an activity or band missing is neutral (1.0)."""
        out: Dict[str, Dict[str, float]] = {}
        for h in self.habits(now, exclude):
            out.setdefault(h["band"], {})[h["name"]] = h["factor"]
        return out

    # ============= Creative Output =============

    def on_creative_activity(self, activity_name: str, mood: str = "", focus: float = 0.5):
        """Maybe produce a creative artifact (30% chance)."""
        artifact_type = CREATIVE_ACTIVITIES.get(activity_name)
        if not artifact_type or random.random() > 0.30:
            return None
        quality = 0.3 + focus * 0.4 + random.uniform(0.0, 0.2)
        artifact = CreativeArtifact(
            artifact_type=artifact_type,
            title=self._generate_title(artifact_type),
            quality_feeling=min(1.0, quality),
            associated_emotions=[mood] if mood else [],
            created_at=datetime.now(),
        )
        self._creative_portfolio.append(artifact)
        # Cap at 20
        if len(self._creative_portfolio) > 20:
            self._creative_portfolio = sorted(
                self._creative_portfolio,
                key=lambda a: a.quality_feeling, reverse=True,
            )[:20]
        return artifact

    def _generate_title(self, artifact_type: str) -> str:
        """Generate a simple title for a creative artifact."""
        titles = {
            "poem": ["untitled", "fragments", "something about the light",
                     "for now", "passing thought"],
            "sketch": ["gesture study", "the view from here", "shapes and shadows",
                       "quick idea", "doodle"],
            "playlist": ["this mood", "late night", "morning energy",
                        "rainy day mix", "new favorites"],
            "recipe": ["experiment #1", "comfort food attempt", "that thing I tried",
                      "improvised", "keeper"],
        }
        return random.choice(titles.get(artifact_type, ["untitled"]))

    def get_recent_artifacts(self, limit: int = 3) -> List[CreativeArtifact]:
        """Get most recent creative artifacts."""
        return self._creative_portfolio[-limit:]

    # ============= Ambient Senses =============

    def _update_ambient(self, location: str, weather: str, time_of_day: str):
        """Update ambient sensory snapshot."""
        sounds = list(AMBIENT_SOUNDS.get(location, []))
        if "rain" in weather or "storm" in weather:
            sounds.extend(RAIN_SOUNDS[:1])
        if time_of_day in ("night", "late_night"):
            sounds.extend(NIGHT_SOUNDS[:1])

        smells = list(AMBIENT_SMELLS.get(location, []))
        light = LIGHT_QUALITY.get(time_of_day, "natural light")

        self._ambient = AmbientSenseSnapshot(
            sounds=sounds[:3],
            smells=smells[:2],
            light_quality=light,
            temperature_comfort="comfortable" if weather not in ("stormy", "snowy") else "chilly",
        )

    def get_ambient(self) -> AmbientSenseSnapshot:
        return self._ambient

    # ============= Possessions =============

    def add_possession(self, name: str, description: str = "",
                       utility: str = "occasional"):
        """Add a possession."""
        for p in self._possessions:
            if p.name == name:
                return
        self._possessions.append(Possession(
            name=name, description=description,
            utility=utility, acquired_at=datetime.now(),
        ))
        if len(self._possessions) > 15:
            self._possessions = sorted(
                self._possessions,
                key=lambda p: p.sentimental_value, reverse=True,
            )[:15]

    def grow_sentimental_value(self, name: str, amount: float = 0.05):
        """Grow sentimental value of a possession from associated memories."""
        for p in self._possessions:
            if p.name == name:
                p.sentimental_value = min(1.0, p.sentimental_value + amount)
                return

    # ============= Neighborhood =============

    def seed_neighborhood(self, places: List[dict]):
        """Seed neighborhood places from persona definition."""
        for pd in places:
            name = pd.get("name", "")
            if name and name not in self._neighborhood:
                self._neighborhood[name] = NeighborhoodPlace(
                    name=name,
                    place_type=pd.get("type", ""),
                    familiarity=pd.get("familiarity", 0.3),
                    emotional_association=pd.get("emotion", ""),
                )

    def visit_place(self, name: str):
        """Record a visit to a neighborhood place."""
        if name in self._neighborhood:
            p = self._neighborhood[name]
            p.last_visit = datetime.now()
            p.familiarity = min(1.0, p.familiarity + 0.02)

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        return {
            "routines": [
                {"name": r.name, "comfort": round(r.comfort_level, 2)}
                for r in self.get_established_routines(2)
            ],
            "recent_creations": [
                {"type": a.artifact_type, "title": a.title}
                for a in self.get_recent_artifacts(2)
            ],
            "ambient": {
                "sounds": self._ambient.sounds[:2],
                "light": self._ambient.light_quality,
            },
        }

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "routines_count": len(self._routines),
            "creative_portfolio_count": len(self._creative_portfolio),
            "possessions_count": len(self._possessions),
            "neighborhood_places": len(self._neighborhood),
            "ambient": {
                "sounds": self._ambient.sounds,
                "smells": self._ambient.smells,
                "light": self._ambient.light_quality,
            },
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "routines": json.dumps([
                {
                    "name": r.name, "activities": r.activities,
                    "consistency_streak": r.consistency_streak,
                    "comfort_level": r.comfort_level, "staleness": r.staleness,
                }
                for r in self._routines.values()
            ]),
            "creative_portfolio": json.dumps([
                {
                    "type": a.artifact_type, "title": a.title,
                    "quality": a.quality_feeling,
                    "emotions": a.associated_emotions,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "shared_with": a.shared_with,
                }
                for a in self._creative_portfolio
            ]),
            "possessions": json.dumps([
                {
                    "name": p.name, "description": p.description,
                    "condition": p.condition, "sentimental_value": p.sentimental_value,
                    "utility": p.utility,
                    "acquired_at": p.acquired_at.isoformat() if p.acquired_at else None,
                }
                for p in self._possessions
            ]),
            "neighborhood": json.dumps([
                {
                    "name": p.name, "type": p.place_type,
                    "status": p.status, "familiarity": p.familiarity,
                    "emotion": p.emotional_association,
                    "last_visit": p.last_visit.isoformat() if p.last_visit else None,
                }
                for p in self._neighborhood.values()
            ]),
            "activity_history": json.dumps(self._activity_history[-50:]),
            "activity_log": json.dumps([[name, at.isoformat(), hour] for name, at, hour in self._activity_log]),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BehaviorSystem":
        """Deserialize from DB."""
        system = cls()
        if not data:
            return system
        # Routines
        raw = data.get("routines", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        for r in items:
            system._routines[r["name"]] = RoutinePattern(
                name=r.get("name", ""),
                activities=r.get("activities", []),
                consistency_streak=r.get("consistency_streak", 0),
                comfort_level=r.get("comfort_level", 0.0),
                staleness=r.get("staleness", 0.0),
            )
        # Creative portfolio
        raw = data.get("creative_portfolio", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        system._creative_portfolio = [
            CreativeArtifact(
                artifact_type=a.get("type", ""),
                title=a.get("title", ""),
                quality_feeling=a.get("quality", 0.5),
                associated_emotions=a.get("emotions", []),
                created_at=datetime.fromisoformat(a["created_at"]) if a.get("created_at") else None,
                shared_with=a.get("shared_with", []),
            ) for a in items
        ]
        # Possessions
        raw = data.get("possessions", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        system._possessions = [
            Possession(
                name=p.get("name", ""),
                description=p.get("description", ""),
                condition=p.get("condition", "good"),
                sentimental_value=p.get("sentimental_value", 0.0),
                utility=p.get("utility", "occasional"),
                acquired_at=datetime.fromisoformat(p["acquired_at"]) if p.get("acquired_at") else None,
            ) for p in items
        ]
        # Neighborhood
        raw = data.get("neighborhood", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        for p in items:
            system._neighborhood[p["name"]] = NeighborhoodPlace(
                name=p.get("name", ""),
                place_type=p.get("type", ""),
                status=p.get("status", "open"),
                familiarity=p.get("familiarity", 0.3),
                emotional_association=p.get("emotion", ""),
                last_visit=datetime.fromisoformat(p["last_visit"]) if p.get("last_visit") else None,
            )
        # Activity history
        raw = data.get("activity_history", "[]")
        try:
            system._activity_history = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            system._activity_history = []
        # Dated history (0.5.0; a 0.4.0 row has none): [name, iso instant, local hour] entries, a bad one skipped.
        raw = data.get("activity_log", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        for e in items if isinstance(items, list) else []:
            try:
                name, at, hour = e
                if isinstance(name, str):
                    system._activity_log.append((name, datetime.fromisoformat(at), int(hour)))
            except (TypeError, ValueError):
                continue
        return system
