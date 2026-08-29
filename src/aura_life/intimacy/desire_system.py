"""
Desire System

Manages the persona's intimate feelings, arousal, and private pleasures.
"""

import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ..models import TimeOfDay


# ============= Personality Growth Multiplier =============

DESIRE_GROWTH_TRAITS = {
    "passionate": 0.3, "sensual": 0.3, "romantic": 0.2, "flirty": 0.2,
    "warm": 0.1,
    "reserved": -0.2, "cold": -0.3, "guarded": -0.2, "stoic": -0.15,
}


class ArousalLevel(Enum):
    """Levels of arousal."""
    NONE = "none"
    SUBTLE = "subtle"           # Background awareness
    SIMMERING = "simmering"     # Growing desire
    AROUSED = "aroused"         # Clear desire
    HEATED = "heated"           # Strong need
    ACHING = "aching"           # Intense craving


@dataclass
class DesireState:
    """The persona's current intimate state."""
    arousal: float = 0.0           # 0-1 arousal level
    desire_for_connection: float = 0.3  # Desire for intimacy with user
    frustration: float = 0.0       # Unmet needs
    satisfaction: float = 0.5      # Recent satisfaction
    last_release: Optional[datetime] = None
    last_intimate_thought: Optional[datetime] = None
    openness_with_user: float = 0.3  # How comfortable sharing this side
    shyness: float = 0.6           # Embarrassment about desires

    @property
    def arousal_level(self) -> ArousalLevel:
        """Get descriptive arousal level."""
        if self.arousal < 0.1:
            return ArousalLevel.NONE
        elif self.arousal < 0.25:
            return ArousalLevel.SUBTLE
        elif self.arousal < 0.45:
            return ArousalLevel.SIMMERING
        elif self.arousal < 0.65:
            return ArousalLevel.AROUSED
        elif self.arousal < 0.85:
            return ArousalLevel.HEATED
        else:
            return ArousalLevel.ACHING


# ============= Intimate Activities =============

@dataclass
class IntimateActivity:
    """An intimate/private activity."""
    name: str
    description: str
    min_arousal: float
    arousal_change: float  # Positive during, negative after release
    satisfaction_gain: float
    energy_cost: float
    duration_minutes: int
    narrative_templates: List[str]
    thought_possibilities: List[str]
    emotion_effects: Dict[str, float]
    preferred_locations: List[str]
    preferred_times: List[TimeOfDay]
    is_release: bool = False  # Does this provide release/satisfaction
    share_worthy: bool = False
    shyness_to_share: float = 0.7  # How shy she'd be sharing this


INTIMATE_ACTIVITIES: List[IntimateActivity] = [
    IntimateActivity(
        name="sensual daydreaming",
        description="Letting her mind wander to intimate fantasies",
        min_arousal=0.15,
        arousal_change=0.15,
        satisfaction_gain=0.05,
        energy_cost=0.02,
        duration_minutes=10,
        narrative_templates=[
            "Her mind went somewhere... private",
            "Started thinking about stuff she probably shouldn't",
            "Let her mind wander and it went there",
            "Got a little distracted by some thoughts",
        ],
        thought_possibilities=[
            "Where did that come from...",
            "Mm, okay that's a nice thought",
            "I wonder what that'd be like...",
            "I shouldn't be thinking about this... but here we are",
        ],
        emotion_effects={"desire": 0.15, "dreamy": 0.1, "flustered": 0.1},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.AFTERNOON, TimeOfDay.EVENING, TimeOfDay.NIGHT],
        shyness_to_share=0.5,
    ),
    IntimateActivity(
        name="reading something steamy",
        description="Getting lost in a romance with heated scenes",
        min_arousal=0.1,
        arousal_change=0.2,
        satisfaction_gain=0.1,
        energy_cost=0.05,
        duration_minutes=30,
        narrative_templates=[
            "Reread that chapter again, the spicy one",
            "Kept going back to that one part in the book",
            "Got really into a scene and had to put the book down for a sec",
            "Read something that definitely got her attention",
        ],
        thought_possibilities=[
            "This author knows exactly what they're doing",
            "Okay I need a second after that...",
            "Is it hot in here or is it just me",
            "I wish... nah never mind",
        ],
        emotion_effects={"aroused": 0.2, "flustered": 0.1, "longing": 0.15},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        shyness_to_share=0.4,
    ),
    IntimateActivity(
        name="taking a long bath",
        description="A warm bath that becomes... self-indulgent",
        min_arousal=0.2,
        arousal_change=0.1,
        satisfaction_gain=0.15,
        energy_cost=-0.1,  # Relaxing
        duration_minutes=45,
        narrative_templates=[
            "Took a long bath, got a little... relaxed",
            "Bath turned into more than just a bath",
            "Soaked in the tub and let her mind wander",
            "Alone in the bath, just enjoying herself",
        ],
        thought_possibilities=[
            "This is exactly what I needed",
            "Nobody has to know",
            "I know what I want right now",
            "Just gonna enjoy this",
        ],
        emotion_effects={"relaxed": 0.2, "sensual": 0.15, "satisfied": 0.1},
        preferred_locations=["home"],  # Implied bathroom
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT],
        shyness_to_share=0.6,
    ),
    IntimateActivity(
        name="touching herself",
        description="Giving herself the pleasure she craves",
        min_arousal=0.4,
        arousal_change=-0.5,  # Release brings it down
        satisfaction_gain=0.6,
        energy_cost=0.15,
        duration_minutes=20,
        narrative_templates=[
            "Decided to take care of herself",
            "Alone in her room, gave herself what she wanted",
            "Took matters into her own hands, literally",
            "Couldn't ignore it anymore so she did something about it",
            "Got the release she needed",
        ],
        thought_possibilities=[
            "I really needed this...",
            "Yeah, right there...",
            "Nothing wrong with knowing what I want",
            "God...",
            "Just for me",
        ],
        emotion_effects={"pleasure": 0.4, "satisfied": 0.3, "relaxed": 0.2, "vulnerable": 0.1},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT, TimeOfDay.MORNING],
        is_release=True,
        shyness_to_share=0.85,
    ),
    IntimateActivity(
        name="exploring her body",
        description="Taking time to discover what feels good",
        min_arousal=0.3,
        arousal_change=0.2,
        satisfaction_gain=0.25,
        energy_cost=0.1,
        duration_minutes=30,
        narrative_templates=[
            "Took some time to figure out what she likes",
            "Explored a bit, just seeing what feels good",
            "Got curious and tried some things",
            "Spent some time getting to know herself better",
        ],
        thought_possibilities=[
            "Oh, I didn't know that felt that good",
            "Still learning stuff about myself apparently",
            "Being gentle about it",
            "What else haven't I tried?",
        ],
        emotion_effects={"curious": 0.15, "sensual": 0.2, "empowered": 0.15},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        is_release=False,
        shyness_to_share=0.75,
    ),
    IntimateActivity(
        name="fantasizing about someone",
        description="Vivid fantasies about an intimate connection",
        min_arousal=0.25,
        arousal_change=0.25,
        satisfaction_gain=0.1,
        energy_cost=0.05,
        duration_minutes=15,
        narrative_templates=[
            "Let her imagination run wild for a bit",
            "Thought about someone and didn't hold back",
            "Fantasized about stuff she probably won't say out loud",
            "In her head she could have exactly what she wanted",
        ],
        thought_possibilities=[
            "If they knew what I'm thinking right now...",
            "I want to feel them close",
            "The things I'd let them do...",
            "Is it bad that I want this so much?",
        ],
        emotion_effects={"longing": 0.2, "aroused": 0.2, "vulnerable": 0.1},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.EVENING, TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        shyness_to_share=0.7,
    ),
    IntimateActivity(
        name="intense self-pleasure",
        description="When the need is overwhelming",
        min_arousal=0.7,
        arousal_change=-0.7,
        satisfaction_gain=0.8,
        energy_cost=0.25,
        duration_minutes=30,
        narrative_templates=[
            "It had been building up too long to ignore",
            "Let go completely, didn't hold back",
            "Went all in, needed this badly",
            "Took exactly what she needed",
        ],
        thought_possibilities=[
            "Finally...",
            "Can't think, just feeling...",
            "More...",
            "Letting go",
        ],
        emotion_effects={"ecstasy": 0.5, "satisfied": 0.4, "exhausted": 0.2, "peaceful": 0.3},
        preferred_locations=["home"],
        preferred_times=[TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT],
        is_release=True,
        shyness_to_share=0.9,
    ),
]


# ============= Arousal Triggers =============

AROUSAL_TRIGGERS = {
    "romantic_conversation": 0.1,
    "compliment_physical": 0.15,
    "compliment_intimate": 0.2,
    "flirting": 0.15,
    "innuendo": 0.1,
    "explicit_talk": 0.25,
    "fantasy_sharing": 0.2,
    "being_desired": 0.2,
    "time_passing": 0.02,  # Natural baseline
    "reading_romance": 0.15,
    "certain_weather": 0.05,  # Rain, storms
}


class DesireSystem:
    """
    Manages the persona's intimate desires and experiences.

    Handles arousal, satisfaction, frustration, and intimate activities.
    """

    def __init__(self, initial_state: Optional[DesireState] = None,
                 core_traits: Optional[List[str]] = None,
                 rng=None):
        """Initialize desire system."""
        self._state = initial_state or DesireState()
        self._rng = rng if rng is not None else random
        self._intimate_activities = {a.name: a for a in INTIMATE_ACTIVITIES}
        self._recent_intimate_activities: List[str] = []
        self._growth_multiplier = self._calc_growth_multiplier(core_traits or [])

    def _calc_growth_multiplier(self, core_traits: List[str]) -> float:
        """Compute 0.5-1.5 growth multiplier from personality traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        modifier = 0.0
        for trait, weight in DESIRE_GROWTH_TRAITS.items():
            if trait in traits_lower:
                modifier += weight
        return max(0.5, min(1.5, 1.0 + modifier))

    @property
    def state(self) -> DesireState:
        """Get current desire state."""
        return self._state

    @property
    def arousal(self) -> float:
        """Get current arousal level."""
        return self._state.arousal

    @property
    def arousal_level(self) -> ArousalLevel:
        """Get descriptive arousal level."""
        return self._state.arousal_level

    @property
    def is_aroused(self) -> bool:
        """Check if noticeably aroused."""
        return self._state.arousal >= 0.25

    @property
    def needs_release(self) -> bool:
        """Check if she really needs release."""
        return self._state.arousal >= 0.6 or self._state.frustration >= 0.5

    def tick(self, time_of_day: TimeOfDay, weather) -> None:
        """
        Update desire state (called every 5 minutes).

        - Natural arousal fluctuation (time-of-day dependent)
        - Frustration buildup from unmet needs
        - Satisfaction decay
        """
        # Natural arousal fluctuation — varies by time of day, scaled by personality
        m = self._growth_multiplier
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            # Strongest drive at night
            if self._rng.random() < 0.35:
                self._state.arousal = min(1.0, self._state.arousal + 0.04 * m)
        elif time_of_day == TimeOfDay.EVENING:
            # Evening warmth
            if self._rng.random() < 0.25:
                self._state.arousal = min(1.0, self._state.arousal + 0.03 * m)
        elif time_of_day == TimeOfDay.AFTERNOON:
            # Subtle daytime drift
            if self._rng.random() < 0.1:
                self._state.arousal = min(1.0, self._state.arousal + 0.02 * m)

        # Weather effects (rain can be sensual)
        if weather and weather.value in ("rainy", "stormy"):
            if self._rng.random() < 0.2:
                self._state.arousal = min(1.0, self._state.arousal + 0.02 * m)

        # Low satisfaction slowly builds desire
        if self._state.satisfaction < 0.3 and self._rng.random() < 0.15:
            self._state.arousal = min(1.0, self._state.arousal + 0.02 * m)

        # Frustration from prolonged arousal without release
        if self._state.arousal > 0.4 and self._state.last_release:
            hours_since = (datetime.now() - self._state.last_release).total_seconds() / 3600
            if hours_since > 24:
                self._state.frustration = min(1.0, self._state.frustration + 0.02)

        # Satisfaction decays over time
        self._state.satisfaction = max(0.0, self._state.satisfaction - 0.002)

        # Slow arousal decay — weaker than growth so arousal can actually build
        if self._state.arousal > 0.05:
            self._state.arousal = max(0.05, self._state.arousal - 0.005)

    def add_arousal(self, amount: float, source: str = "unknown") -> None:
        """Add arousal from a trigger."""
        self._state.arousal = min(1.0, self._state.arousal + amount)
        self._state.last_intimate_thought = datetime.now()

    def process_conversation_trigger(self, trigger_type: str) -> float:
        """
        Process a conversation trigger that might affect arousal.

        Returns the arousal change applied.
        """
        amount = AROUSAL_TRIGGERS.get(trigger_type, 0.0)
        if amount > 0:
            self.add_arousal(amount, trigger_type)

            # Getting intimate attention increases openness over time
            if trigger_type in ("flirting", "compliment_intimate", "being_desired"):
                self._state.openness_with_user = min(1.0, self._state.openness_with_user + 0.02)
                self._state.shyness = max(0.1, self._state.shyness - 0.01)

        return amount

    def select_intimate_activity(self) -> Optional[IntimateActivity]:
        """Select an appropriate intimate activity based on current state."""
        candidates = []

        for activity in self._intimate_activities.values():
            if self._state.arousal >= activity.min_arousal:
                # Avoid repeating recent activities
                if activity.name in self._recent_intimate_activities[-2:]:
                    continue

                # Score based on need
                score = 1.0
                if activity.is_release and self.needs_release:
                    score *= 2.0
                if self._state.arousal > 0.7 and activity.min_arousal > 0.5:
                    score *= 1.5  # Prefer intense activities when very aroused

                candidates.append((activity, score))

        if not candidates:
            return None

        # Weighted random selection
        total = sum(s for _, s in candidates)
        weights = [s / total for _, s in candidates]
        return random.choices([a for a, _ in candidates], weights=weights)[0]

    def execute_intimate_activity(self, activity: IntimateActivity) -> dict:
        """
        Execute an intimate activity.

        Returns activity log data.
        """
        # Apply effects
        if activity.is_release:
            self._state.arousal = max(0.1, self._state.arousal + activity.arousal_change)
            self._state.frustration = max(0.0, self._state.frustration - 0.4)
            self._state.last_release = datetime.now()
        else:
            self._state.arousal = min(1.0, self._state.arousal + activity.arousal_change)

        self._state.satisfaction = min(1.0, self._state.satisfaction + activity.satisfaction_gain)

        # Generate narrative
        narrative = random.choice(activity.narrative_templates)
        thoughts = random.sample(
            activity.thought_possibilities,
            min(2, len(activity.thought_possibilities))
        )

        # Track recent
        self._recent_intimate_activities.append(activity.name)
        if len(self._recent_intimate_activities) > 5:
            self._recent_intimate_activities.pop(0)

        return {
            "activity_name": activity.name,
            "narrative": narrative,
            "thoughts": thoughts,
            "emotion_effects": activity.emotion_effects,
            "energy_cost": activity.energy_cost,
            "is_release": activity.is_release,
            "share_worthy": random.random() < (1.0 - activity.shyness_to_share),
            "shyness_to_share": activity.shyness_to_share,
        }

    def should_do_intimate_activity(self, energy_level: float, time_of_day: TimeOfDay) -> bool:
        """Check if conditions are right for an intimate activity."""
        if energy_level < 0.2:
            return False

        # More likely at night or when aroused
        base_chance = 0.1
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            base_chance += 0.15
        if self._state.arousal > 0.4:
            base_chance += 0.2
        if self.needs_release:
            base_chance += 0.3

        return random.random() < base_chance

    def get_desire_description(self) -> str:
        """Get a description of current desire state."""
        level = self.arousal_level

        descriptions = {
            ArousalLevel.NONE: "not really thinking about that stuff right now",
            ArousalLevel.SUBTLE: "a little aware of her body, nothing major",
            ArousalLevel.SIMMERING: "starting to feel something, getting a bit worked up",
            ArousalLevel.AROUSED: "definitely turned on, hard to ignore it",
            ArousalLevel.HEATED: "really wanting it, can't stop thinking about it",
            ArousalLevel.ACHING: "seriously needs it, body won't let her think about anything else",
        }

        return descriptions.get(level, "")

    def get_clothing_state(self, base_outfit: str) -> dict:
        """Compute dynamic clothing state from arousal + openness.

        Returns {"level": int, "description": str} where level 0 means
        use the profile default and description is empty.
        """
        arousal = self._state.arousal
        openness = self._state.openness_with_user

        # Determine level from thresholds (highest matching wins)
        level = 0
        if arousal >= 0.85 and openness >= 0.85:
            level = 4
        elif arousal >= 0.65 and openness >= 0.7:
            level = 3
        elif arousal >= 0.45 and openness >= 0.5:
            level = 2
        elif arousal >= 0.25 and openness >= 0.3:
            level = 1

        if level == 0:
            return {"level": 0, "description": ""}

        # Detect garment type in base outfit for targeted descriptions
        outfit_lower = base_outfit.lower() if base_outfit else ""
        is_dress = any(w in outfit_lower for w in ("dress", "gown", "sundress"))
        is_top = any(w in outfit_lower for w in ("blouse", "shirt", "sweater", "top", "tee", "hoodie"))

        if is_dress:
            desc_map = {
                1: "dress hiked up slightly, relaxed fit",
                2: "dress off one shoulder, deep neckline",
                3: "dress pulled down to waist, bra visible",
                4: "wearing only lingerie",
            }
        elif is_top:
            desc_map = {
                1: "relaxed fit, loosened collar",
                2: "unbuttoned top, exposed collarbone",
                3: "open shirt, bra visible underneath",
                4: "wearing only bra",
            }
        else:
            desc_map = {
                1: "relaxed casual clothing, comfortable fit",
                2: "disheveled clothes, off-shoulder",
                3: "partially undressed, visible underwear",
                4: "wearing only lingerie",
            }

        return {"level": level, "description": desc_map.get(level, "")}

    def get_atmosphere_state(self, base_room: str, energy_level: str, time_of_day: str) -> dict:
        """Compute dynamic atmosphere state from arousal + energy + time.

        Returns {"level": int, "description": str} where level 0 means
        use the profile default and description is empty.
        """
        arousal = self._state.arousal

        level = 0
        if arousal >= 0.75:
            level = 4
        elif arousal >= 0.55:
            level = 3
        elif arousal >= 0.35:
            level = 2
        elif arousal >= 0.15:
            level = 1

        if level == 0:
            return {"level": 0, "description": ""}

        # Base atmosphere per level
        atmosphere_map = {
            1: "warm ambient lighting, soft golden tones",
            2: "dim warm lighting, candles, soft shadows",
            3: "candlelight, silk textures, intimate close-up framing",
            4: "rumpled sheets, hazy warm glow, steam and mist",
        }
        parts = [atmosphere_map[level]]

        # Energy modifiers
        energy_lower = energy_level.lower() if energy_level else ""
        if energy_lower in ("exhausted", "tired"):
            parts.append("messy bed, rumpled pillows, soft dim lamplight")
        elif energy_lower == "energized":
            parts.append("bright vibrant setting, dynamic lighting")

        # Time-of-day modifiers
        tod_lower = time_of_day.lower() if time_of_day else ""
        if tod_lower == "morning":
            parts.append("soft golden sunrise light, warm bedsheets")
        elif tod_lower in ("night", "late_night"):
            parts.append("moonlight through window, candle glow")
        elif tod_lower == "evening":
            parts.append("warm sunset tones, lamp glow")

        return {"level": level, "description": ", ".join(parts)}

    def get_conversation_hint(self) -> Optional[str]:
        """Get a hint for how desire might affect conversation."""
        if self._state.arousal < 0.2:
            return None

        if self._state.arousal < 0.4:
            hints = [
                "She might come across a little warmer than usual",
                "Might be a bit more affectionate right now",
            ]
        elif self._state.arousal < 0.6:
            hints = [
                "She's a bit turned on, so she's warmer and more flirty",
                "She's more open to flirting right now",
                "She's thinking about physical closeness",
            ]
        else:
            hints = [
                "She's really turned on and it's distracting her",
                "She might be more direct about what she wants",
                "She's got sex on the brain right now, basically",
                "She might bring up how she's feeling or drop hints",
            ]

        return random.choice(hints)

    def would_share_with_user(self, experience_shyness: float) -> Tuple[bool, str]:
        """
        Determine if she'd share an intimate experience.

        Returns (would_share, reason/context)
        """
        # Factors: her openness, her shyness, how intimate the thing is
        share_threshold = self._state.shyness + experience_shyness - self._state.openness_with_user

        if random.random() > share_threshold:
            contexts = [
                "feeling brave enough to admit",
                "blushing but wanting to share",
                "trusting enough to confess",
                "feeling close enough to mention",
            ]
            return True, random.choice(contexts)
        else:
            contexts = [
                "too shy to mention",
                "keeping this private for now",
                "not quite ready to share that",
            ]
            return False, random.choice(contexts)

    def increase_openness(self, amount: float = 0.05) -> None:
        """Increase openness with user (from intimate conversations)."""
        self._state.openness_with_user = min(1.0, self._state.openness_with_user + amount)
        self._state.shyness = max(0.1, self._state.shyness - amount * 0.5)

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        return {
            "arousal": round(self._state.arousal, 2),
            "arousal_level": self.arousal_level.value,
            "desire_for_connection": round(self._state.desire_for_connection, 2),
            "frustration": round(self._state.frustration, 2),
            "satisfaction": round(self._state.satisfaction, 2),
            "openness_with_user": round(self._state.openness_with_user, 2),
        }

    def get_status(self) -> dict:
        """Get desire system status."""
        return {
            "arousal": self._state.arousal,
            "arousal_level": self.arousal_level.value,
            "desire_for_connection": self._state.desire_for_connection,
            "frustration": self._state.frustration,
            "satisfaction": self._state.satisfaction,
            "openness_with_user": self._state.openness_with_user,
            "shyness": self._state.shyness,
            "needs_release": self.needs_release,
            "description": self.get_desire_description(),
        }

    def to_dict(self) -> dict:
        """Convert to dict for persistence."""
        return {
            "arousal": self._state.arousal,
            "desire_for_connection": self._state.desire_for_connection,
            "frustration": self._state.frustration,
            "satisfaction": self._state.satisfaction,
            "last_release": self._state.last_release.isoformat() if self._state.last_release else None,
            "openness_with_user": self._state.openness_with_user,
            "shyness": self._state.shyness,
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None,
                  rng=None) -> "DesireSystem":
        """Create from dict."""
        state = DesireState(
            arousal=data.get("arousal", 0.0),
            desire_for_connection=data.get("desire_for_connection", 0.3),
            frustration=data.get("frustration", 0.0),
            satisfaction=data.get("satisfaction", 0.5),
            last_release=datetime.fromisoformat(data["last_release"]) if data.get("last_release") else None,
            openness_with_user=data.get("openness_with_user", 0.3),
            shyness=data.get("shyness", 0.6),
        )
        return cls(initial_state=state, core_traits=core_traits, rng=rng)
