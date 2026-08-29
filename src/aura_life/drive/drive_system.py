"""
Drive Engine

Tracks motivational drives beyond goals:
- Curiosity: questions sparked by activities/conversation
- Avoidance: things being put off, with accumulating guilt
- Comfort Zone: familiarity boundaries that expand with attempts
"""

import json
import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import CuriosityQuestion, AvoidanceItem, ComfortZoneBoundary

logger = __import__("logging").getLogger(__name__)

# Activity -> curiosity sparks
CURIOSITY_SPARKS: Dict[str, List[str]] = {
    "reading": [
        "What else has this author written?",
        "Is that historical detail actually true?",
        "What would it be like to live in that world?",
    ],
    "learning something new": [
        "How deep does this rabbit hole go?",
        "Who first figured this out?",
        "What are the practical applications?",
    ],
    "listening to music": [
        "What genre is this actually?",
        "Who influenced this artist?",
        "Why does this chord progression feel so satisfying?",
    ],
    "stargazing": [
        "What constellation is that?",
        "How far away is the nearest star?",
        "What would it feel like to float in space?",
    ],
    "exploring a new idea": [
        "What if I combined this with something else?",
        "Has anyone else thought about this?",
        "Where does this idea lead?",
    ],
    "writing poetry": [
        "What makes a metaphor work?",
        "How did my favorite poets find their voice?",
        "Could I write in a completely different style?",
    ],
    "cooking a meal": [
        "What's the science behind this reaction?",
        "What do they eat in that country?",
        "Could I make this from scratch?",
    ],
    "journaling": [
        "Why do I keep coming back to this theme?",
        "What would I tell my younger self?",
        "What patterns am I not seeing?",
    ],
}

# Avoidance templates (generated probabilistically)
AVOIDANCE_SEEDS = [
    {"description": "organizing that messy drawer", "reason": "laziness", "discomfort": 0.2},
    {"description": "replying to that message", "reason": "anxiety", "discomfort": 0.3},
    {"description": "scheduling that appointment", "reason": "anxiety", "discomfort": 0.4},
    {"description": "having that difficult conversation", "reason": "fear", "discomfort": 0.5},
    {"description": "finishing that project", "reason": "perfectionism", "discomfort": 0.3},
    {"description": "cleaning out old things", "reason": "nostalgia", "discomfort": 0.2},
]

# Comfort zone categories
COMFORT_ZONE_MAP: Dict[str, str] = {
    "going for a run": "physical",
    "gym workout": "physical",
    "yoga": "physical",
    "texting a friend": "social",
    "having coffee with a friend": "social",
    "catching up with family": "social",
    "writing poetry": "creative",
    "sketching ideas": "creative",
    "creating a playlist": "creative",
    "learning something new": "intellectual",
    "exploring a new idea": "intellectual",
    "meditating": "mindful",
    "trying a new recipe": "creative",
}

# ============= Conversation Triggers =============

DRIVE_CONVERSATION_TRIGGERS = {
    "interesting_topic":     0.10,
    "new_idea":              0.08,
    "avoidance_nudge":       0.05,   # guilt relief
    "comfort_zone_push":     0.03,
    "accomplishment_shared": 0.03,   # guilt relief
}

# ============= Personality Growth Multiplier =============

DRIVE_GROWTH_TRAITS = {
    "curious": 0.3, "adventurous": 0.2, "ambitious": 0.15, "driven": 0.15,
    "lazy": -0.2, "cautious": -0.1, "anxious": -0.1,
}

GUILT_GROWTH_RATE = 0.003  # Per tick for avoidance items
MAX_CURIOSITY = 5
MAX_AVOIDANCE = 4


class DriveSystem:
    """Tracks curiosity, avoidance, and comfort zone boundaries."""

    def __init__(self, core_traits: Optional[List[str]] = None,
                 comfort_zone_seeds: Optional[List[str]] = None,
                 rng=None):
        self._curiosities: List[CuriosityQuestion] = []
        self._rng = rng if rng is not None else random
        self._avoidances: List[AvoidanceItem] = []
        self._comfort_zones: Dict[str, ComfortZoneBoundary] = {}
        self._drive_multiplier = self._calc_drive_multiplier(core_traits or [])
        # Seed comfort zones from persona profile
        if comfort_zone_seeds:
            self._seed_comfort_zones(comfort_zone_seeds)

    # ============= Tick =============

    def tick(self):
        """Per-tick update: grow guilt, decay old curiosity."""
        # Avoidance guilt grows — less driven personas feel more guilt
        guilt_rate = GUILT_GROWTH_RATE * (2.0 - self._drive_multiplier)
        for item in self._avoidances:
            item.guilt_accumulated = min(1.0, item.guilt_accumulated + guilt_rate)
            # Overdue check
            if item.deadline and datetime.now() > item.deadline:
                item.guilt_accumulated = min(1.0, item.guilt_accumulated + 0.01)

        # Old curiosity loses intensity slowly — curious personas hold interest longer
        decay = 0.001 / self._drive_multiplier
        for q in self._curiosities:
            if q.explored:
                continue
            q.intensity = max(0.0, q.intensity - decay)

        # Remove faded curiosity
        self._curiosities = [q for q in self._curiosities if q.intensity > 0.05 or q.explored]

    # ============= Curiosity =============

    def on_activity(self, activity_name: str):
        """Spark curiosity from an activity, chance scaled by personality."""
        if random.random() > 0.15 * self._drive_multiplier:
            return
        sparks = CURIOSITY_SPARKS.get(activity_name)
        if not sparks:
            return
        topic = random.choice(sparks)
        # Don't duplicate
        for q in self._curiosities:
            if q.topic == topic:
                q.intensity = min(1.0, q.intensity + 0.1)
                return
        self._curiosities.append(CuriosityQuestion(
            topic=topic,
            intensity=random.uniform(0.3, 0.7),
            sparked_by=activity_name,
            created_at=datetime.now(),
        ))
        # Cap
        if len(self._curiosities) > MAX_CURIOSITY:
            self._curiosities.sort(key=lambda q: q.intensity, reverse=True)
            self._curiosities = self._curiosities[:MAX_CURIOSITY]

    def on_conversation_topic(self, topic: str):
        """Spark curiosity from conversation."""
        for q in self._curiosities:
            if topic.lower() in q.topic.lower():
                q.intensity = min(1.0, q.intensity + 0.15)
                return
        self._curiosities.append(CuriosityQuestion(
            topic=f"What more can I learn about {topic}?",
            intensity=0.5,
            sparked_by="conversation",
            created_at=datetime.now(),
        ))
        if len(self._curiosities) > MAX_CURIOSITY:
            self._curiosities.sort(key=lambda q: q.intensity, reverse=True)
            self._curiosities = self._curiosities[:MAX_CURIOSITY]

    def explore_curiosity(self, topic: str):
        """Mark a curiosity as explored."""
        for q in self._curiosities:
            if topic.lower() in q.topic.lower() and not q.explored:
                q.explored = True
                return

    def get_active_curiosities(self, limit: int = 3) -> List[CuriosityQuestion]:
        """Get most intense unexplored curiosities."""
        active = [q for q in self._curiosities if not q.explored]
        return sorted(active, key=lambda q: q.intensity, reverse=True)[:limit]

    # ============= Avoidance =============

    def add_avoidance(self, description: str, reason: str = "anxiety",
                      discomfort: float = 0.3, deadline: Optional[datetime] = None):
        """Add something being avoided."""
        for a in self._avoidances:
            if a.description == description:
                return  # Already tracking
        self._avoidances.append(AvoidanceItem(
            description=description,
            discomfort=discomfort,
            reason=reason,
            created_at=datetime.now(),
            deadline=deadline,
        ))
        if len(self._avoidances) > MAX_AVOIDANCE:
            self._avoidances.sort(key=lambda a: a.guilt_accumulated, reverse=True)
            self._avoidances = self._avoidances[:MAX_AVOIDANCE]

    def resolve_avoidance(self, description: str):
        """Resolve an avoidance item."""
        self._avoidances = [a for a in self._avoidances if a.description != description]

    def roll_avoidance(self):
        """Small chance (3%) per tick to generate an avoidance item."""
        if self._rng.random() > 0.03 or len(self._avoidances) >= MAX_AVOIDANCE:
            return
        seed = self._rng.choice(AVOIDANCE_SEEDS)
        for a in self._avoidances:
            if a.description == seed["description"]:
                return
        self.add_avoidance(
            description=seed["description"],
            reason=seed["reason"],
            discomfort=seed["discomfort"],
        )

    def get_guilt_stressors(self) -> List[str]:
        """Get avoidance items with high guilt (for feeding into Affect stress)."""
        return [a.description for a in self._avoidances if a.guilt_accumulated > 0.4]

    # ============= Comfort Zone =============

    def track_activity_comfort(self, activity_name: str):
        """Track comfort zone expansion from activity."""
        category = COMFORT_ZONE_MAP.get(activity_name)
        if not category:
            return
        key = f"{category}:{activity_name}"
        if key not in self._comfort_zones:
            self._comfort_zones[key] = ComfortZoneBoundary(
                category=category,
                activity=activity_name,
                familiarity=0.3,
            )
        zone = self._comfort_zones[key]
        zone.attempt_count += 1
        zone.success_count += 1
        zone.last_attempted = datetime.now()
        # Familiarity grows with attempts
        zone.familiarity = min(1.0, zone.familiarity + 0.02)
        # No longer growth edge once familiar
        zone.growth_edge = zone.familiarity < 0.6

    def get_growth_edges(self, limit: int = 2) -> List[ComfortZoneBoundary]:
        """Get activities at the growth edge of comfort zone."""
        edges = [z for z in self._comfort_zones.values() if z.growth_edge]
        return sorted(edges, key=lambda z: z.familiarity)[:limit]

    def _seed_comfort_zones(self, seeds: List[str]):
        """Pre-populate comfort zones from persona profile seeds."""
        for activity in seeds:
            category = COMFORT_ZONE_MAP.get(activity, "other")
            key = f"{category}:{activity}"
            if key not in self._comfort_zones:
                self._comfort_zones[key] = ComfortZoneBoundary(
                    category=category,
                    activity=activity,
                    familiarity=0.7,  # Seeds start familiar (within comfort zone)
                    growth_edge=False,
                    attempt_count=5,  # Implied prior experience
                    success_count=4,
                )

    # ============= Conversation Triggers =============

    def process_conversation_trigger(self, trigger_type: str) -> None:
        """Process a conversation trigger that affects curiosity or avoidance guilt."""
        amount = DRIVE_CONVERSATION_TRIGGERS.get(trigger_type, 0.0)
        if amount == 0.0:
            return
        scaled = amount * self._drive_multiplier

        if trigger_type in ("avoidance_nudge", "accomplishment_shared"):
            # Relieve guilt on avoidance items
            for item in self._avoidances:
                item.guilt_accumulated = max(0.0, item.guilt_accumulated - scaled)
        else:
            # Boost curiosity intensity for active curiosities, or spark a generic one
            if self._curiosities:
                strongest = max(self._curiosities, key=lambda q: q.intensity)
                strongest.intensity = min(1.0, strongest.intensity + scaled)
            else:
                self._curiosities.append(CuriosityQuestion(
                    topic="Something sparked by conversation",
                    intensity=scaled,
                    sparked_by="conversation",
                    created_at=datetime.now(),
                ))

    # ============= Personality Calculation =============

    def _calc_drive_multiplier(self, core_traits: List[str]) -> float:
        """Compute 0.5-1.5 drive multiplier from personality traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        modifier = 0.0
        for trait, weight in DRIVE_GROWTH_TRAITS.items():
            if trait in traits_lower:
                modifier += weight
        return max(0.5, min(1.5, 1.0 + modifier))

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        return {
            "curiosities": [
                {"topic": q.topic, "intensity": round(q.intensity, 2)}
                for q in self.get_active_curiosities(2)
            ],
            "avoidances": [
                {"description": a.description, "guilt": round(a.guilt_accumulated, 2)}
                for a in self._avoidances[:2]
            ],
            "growth_edges": [
                {"activity": z.activity, "familiarity": round(z.familiarity, 2)}
                for z in self.get_growth_edges(2)
            ],
        }

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "curiosities": [
                {"topic": q.topic, "intensity": round(q.intensity, 2), "explored": q.explored}
                for q in self._curiosities
            ],
            "avoidances": [
                {"description": a.description, "guilt": round(a.guilt_accumulated, 2), "reason": a.reason}
                for a in self._avoidances
            ],
            "comfort_zones": {
                k: {"familiarity": round(z.familiarity, 2), "attempts": z.attempt_count, "growth_edge": z.growth_edge}
                for k, z in self._comfort_zones.items()
            },
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "curiosities": json.dumps([
                {
                    "topic": q.topic, "intensity": q.intensity,
                    "sparked_by": q.sparked_by,
                    "created_at": q.created_at.isoformat() if q.created_at else None,
                    "explored": q.explored,
                }
                for q in self._curiosities
            ]),
            "avoidances": json.dumps([
                {
                    "description": a.description, "discomfort": a.discomfort,
                    "reason": a.reason,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "deadline": a.deadline.isoformat() if a.deadline else None,
                    "guilt_accumulated": a.guilt_accumulated,
                }
                for a in self._avoidances
            ]),
            "comfort_zones": json.dumps([
                {
                    "category": z.category, "activity": z.activity,
                    "familiarity": z.familiarity, "growth_edge": z.growth_edge,
                    "last_attempted": z.last_attempted.isoformat() if z.last_attempted else None,
                    "attempt_count": z.attempt_count, "success_count": z.success_count,
                }
                for z in self._comfort_zones.values()
            ]),
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None,
                  rng=None) -> "DriveSystem":
        """Deserialize from DB."""
        system = cls(core_traits=core_traits, rng=rng)
        if not data:
            return system
        # Curiosities
        raw = data.get("curiosities", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        system._curiosities = [
            CuriosityQuestion(
                topic=q.get("topic", ""),
                intensity=q.get("intensity", 0.5),
                sparked_by=q.get("sparked_by", ""),
                created_at=datetime.fromisoformat(q["created_at"]) if q.get("created_at") else None,
                explored=q.get("explored", False),
            ) for q in items
        ]
        # Avoidances
        raw = data.get("avoidances", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        system._avoidances = [
            AvoidanceItem(
                description=a.get("description", ""),
                discomfort=a.get("discomfort", 0.3),
                reason=a.get("reason", ""),
                created_at=datetime.fromisoformat(a["created_at"]) if a.get("created_at") else None,
                deadline=datetime.fromisoformat(a["deadline"]) if a.get("deadline") else None,
                guilt_accumulated=a.get("guilt_accumulated", 0.0),
            ) for a in items
        ]
        # Comfort zones
        raw = data.get("comfort_zones", "[]")
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            items = []
        for z in items:
            key = f"{z.get('category', '')}:{z.get('activity', '')}"
            system._comfort_zones[key] = ComfortZoneBoundary(
                category=z.get("category", ""),
                activity=z.get("activity", ""),
                familiarity=z.get("familiarity", 0.5),
                growth_edge=z.get("growth_edge", False),
                last_attempted=datetime.fromisoformat(z["last_attempted"]) if z.get("last_attempted") else None,
                attempt_count=z.get("attempt_count", 0),
                success_count=z.get("success_count", 0),
            )
        return system
