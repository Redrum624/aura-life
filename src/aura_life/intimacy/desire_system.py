"""
Desire System

Manages the persona's intimate feelings, arousal, and private pleasures.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from ..models import TimeOfDay
from ..personas.parameters import PersonaParameters
from ..personas.pronoun_render import render_line
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
# Legacy names: IntimateActivity moved, unchanged, to aura_life.models, and the
# intimate catalogue into the contemporary setting pack
# (aura_life.settings.contemporary), in Task 9's fix round (ruling T9-R2) --
# the system reads its persona's setting now; re-exported so an import from
# here keeps working.
from ..models import IntimateActivity  # noqa: F401
from ..settings.contemporary import INTIMATE_ACTIVITIES  # noqa: F401


logger = logging.getLogger(__name__)


# ============= Personality Growth Multiplier =============
# Read from her trait text by aura_life.personas.parameters
# (DESIRE_GROWTH_TRAITS, PersonaParameters.desire_multiplier).


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
                 rng=None, gender: Optional[str] = None,
                 params: Optional[PersonaParameters] = None,
                 setting: Optional[SettingSpec] = None,
                 intimacy_rate: Optional[float] = None):
        """Initialize desire system.

        `gender` is the persona's own (from `appearance_details["gender"]`,
        via LifeService's `_persona_gender`) -- the default every rendering
        method here falls back to when *its own* `gender` argument is
        omitted, so a caller that reaches this engine directly (the aura
        host calls `.desire.get_status()`) still gets the persona's real
        pronouns without having to know or pass anything. `None` (no
        definition) renders as they/them, same as ever.

        `params`: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`), whose
        `desire_multiplier` scales arousal growth; without them `core_traits`
        is read for them.

        `setting`: her setting pack (:class:`~aura_life.settings.SettingSpec`),
        whose intimate catalogue (``SettingSpec.intimate_catalogue``) she
        draws from: its own, the default setting's when it leaves the field
        out (so leaving it out never changes how often she does one, spec
        R6), none when it gives an empty list. `None` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s.

        `intimacy_rate`: her `PersonalityDefinition.intimacy_rate` (a
        profile's optional `Intimacy Rate:`, 0..1; spec R6). Set, it scales
        the chance :meth:`should_do_intimate_activity` gives on each activity
        tick -- 1.0 is today's chance, 0.5 half of it, 0 never. `None` -- the
        default, unset -- is today's chance exactly. A value that is not a
        number in 0..1 is dropped, with a warning, as the profile parser
        drops one (never clamped): she keeps today's chance.
        """
        if params is None:
            params = PersonaParameters.from_core_traits(core_traits)
        if intimacy_rate is not None and (isinstance(intimacy_rate, bool)
                                          or not isinstance(intimacy_rate, (int, float))
                                          or not 0.0 <= intimacy_rate <= 1.0):
            logger.warning("DesireSystem: intimacy_rate %r is not a number in 0..1; unset instead", intimacy_rate)
            intimacy_rate = None
        self._intimacy_rate = intimacy_rate
        self._state = initial_state or DesireState()
        self._rng = rng if rng is not None else random
        self._gender = gender
        setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        self._intimate_activities = {a.name: a for a in setting.intimate_catalogue()}
        self._recent_intimate_activities: List[str] = []
        self._growth_multiplier = params.desire_multiplier

    def _effective_gender(self, gender: Optional[str]) -> Optional[str]:
        """`gender` if the caller passed one, else this instance's own
        (possibly also `None`, which `render_line`/`resolve_gender` reads as
        they/them)."""
        return gender if gender is not None else self._gender

    @property
    def state(self) -> DesireState:
        """Get current desire state."""
        return self._state

    @property
    def intimacy_rate(self) -> Optional[float]:
        """Her intimacy rate (see ``__init__``); ``None`` when unset."""
        return self._intimacy_rate

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

    def tick(self, time_of_day: TimeOfDay, weather, *, now: Optional[datetime] = None) -> None:
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
            # Hours to now (the world instant LifeService passes, humanness
            # Task 19; the host's clock when omitted).
            hours_since = ((now if now is not None else datetime.now())
                           - self._state.last_release).total_seconds() / 3600
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
        return self._rng.choices([a for a, _ in candidates], weights=weights)[0]

    def execute_intimate_activity(self, activity: IntimateActivity, *,
                                  now: Optional[datetime] = None) -> dict:
        """
        Execute an intimate activity (a release stamped ``now``: the world
        instant ``LifeService`` passes, humanness Task 19, which :meth:`tick`
        compares; the host's clock when omitted).

        Returns activity log data.
        """
        # Apply effects
        if activity.is_release:
            self._state.arousal = max(0.1, self._state.arousal + activity.arousal_change)
            self._state.frustration = max(0.0, self._state.frustration - 0.4)
            self._state.last_release = now if now is not None else datetime.now()
        else:
            self._state.arousal = min(1.0, self._state.arousal + activity.arousal_change)

        self._state.satisfaction = min(1.0, self._state.satisfaction + activity.satisfaction_gain)

        # Generate narrative
        narrative = self._rng.choice(activity.narrative_templates)
        thoughts = self._rng.sample(
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
            "share_worthy": self._rng.random() < (1.0 - activity.shyness_to_share),
            "shyness_to_share": activity.shyness_to_share,
        }

    def should_do_intimate_activity(self, energy_level: float, time_of_day: TimeOfDay) -> bool:
        """Check if conditions are right for an intimate activity (her
        intimacy rate, when set, scales the chance; see ``__init__``)."""
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
        if self._intimacy_rate is not None:
            base_chance *= self._intimacy_rate

        return self._rng.random() < base_chance

    def get_desire_description(self, gender: Optional[str] = None) -> str:
        """Get a description of current desire state, in the persona's own
        pronouns (`gender`, else this instance's own -- see `__init__`)."""
        level = self.arousal_level

        descriptions = {
            ArousalLevel.NONE: "not really thinking about that stuff right now",
            ArousalLevel.SUBTLE: "a little aware of {poss} body, nothing major",
            ArousalLevel.SIMMERING: "starting to feel something, getting a bit worked up",
            ArousalLevel.AROUSED: "definitely turned on, hard to ignore it",
            ArousalLevel.HEATED: "really wanting it, can't stop thinking about it",
            ArousalLevel.ACHING: "seriously needs it, body won't let {obj} think about anything else",
        }

        template = descriptions.get(level, "")
        if not template:
            return ""
        return render_line(template, gender=self._effective_gender(gender))

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

    def get_conversation_hint(self, gender: Optional[str] = None) -> Optional[str]:
        """Get a hint for how desire might affect conversation, in the
        persona's own pronouns (`gender`, else this instance's own -- see
        `__init__`)."""
        if self._state.arousal < 0.2:
            return None

        if self._state.arousal < 0.4:
            hints = [
                "{Subj} might come across a little warmer than usual",
                "Might be a bit more affectionate right now",
            ]
        elif self._state.arousal < 0.6:
            hints = [
                "{Subj} {be} a bit turned on, so {subj} {be} warmer and more flirty",
                "{Subj} {be} more open to flirting right now",
                "{Subj} {be} thinking about physical closeness",
            ]
        else:
            hints = [
                "{Subj} {be} really turned on and it's distracting {obj}",
                "{Subj} might be more direct about what {subj} want{s}",
                "{Subj} {have} got sex on the brain right now, basically",
                "{Subj} might bring up how {subj} {be} feeling or drop hints",
            ]

        return render_line(self._rng.choice(hints), gender=self._effective_gender(gender))

    def would_share_with_user(self, experience_shyness: float) -> Tuple[bool, str]:
        """
        Determine if she'd share an intimate experience.

        Returns (would_share, reason/context)
        """
        # Factors: her openness, her shyness, how intimate the thing is
        share_threshold = self._state.shyness + experience_shyness - self._state.openness_with_user

        if self._rng.random() > share_threshold:
            contexts = [
                "feeling brave enough to admit",
                "blushing but wanting to share",
                "trusting enough to confess",
                "feeling close enough to mention",
            ]
            return True, self._rng.choice(contexts)
        else:
            contexts = [
                "too shy to mention",
                "keeping this private for now",
                "not quite ready to share that",
            ]
            return False, self._rng.choice(contexts)

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

    def get_status(self, gender: Optional[str] = None) -> dict:
        """Get desire system status. `description` renders in the persona's
        own pronouns (`gender`, else this instance's own -- see `__init__`) --
        this engine is public (`LifeService.desire`) and a host may read
        `description` straight into a prompt, so it must never carry a raw
        `{poss}`/`{obj}` token regardless of who calls it or with what."""
        return {
            "arousal": self._state.arousal,
            "arousal_level": self.arousal_level.value,
            "desire_for_connection": self._state.desire_for_connection,
            "frustration": self._state.frustration,
            "satisfaction": self._state.satisfaction,
            "openness_with_user": self._state.openness_with_user,
            "shyness": self._state.shyness,
            "needs_release": self.needs_release,
            "description": self.get_desire_description(gender),
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
                  rng=None, gender: Optional[str] = None,
                  params: Optional[PersonaParameters] = None,
                  setting: Optional[SettingSpec] = None,
                  intimacy_rate: Optional[float] = None) -> "DesireSystem":
        """Create from dict (the other arguments as in the constructor)."""
        state = DesireState(
            arousal=data.get("arousal", 0.0),
            desire_for_connection=data.get("desire_for_connection", 0.3),
            frustration=data.get("frustration", 0.0),
            satisfaction=data.get("satisfaction", 0.5),
            last_release=datetime.fromisoformat(data["last_release"]) if data.get("last_release") else None,
            openness_with_user=data.get("openness_with_user", 0.3),
            shyness=data.get("shyness", 0.6),
        )
        return cls(initial_state=state, core_traits=core_traits, rng=rng, gender=gender, params=params,
                   setting=setting, intimacy_rate=intimacy_rate)
