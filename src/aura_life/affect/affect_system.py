"""
Affect Engine

Tracks background emotional coloring that persists beyond discrete emotion spikes:
- Mood: hours-to-days emotional undertone (content, blue, restless, raw, neutral)
- Stress: cumulative pressure from unmet needs and obligations
- Loneliness: gap between desired and actual social contact
- Regulation: emotional capacity battery (depletes under sustained demand)
- Empathy: emotional contagion from user and NPCs
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    MoodState,
    StressState,
    LonelinessState,
    RegulationState,
    EmpathyState,
)

logger = logging.getLogger(__name__)

# Emotion → mood direction mapping
POSITIVE_EMOTIONS = {"joyful", "content", "excited", "warm", "peaceful", "amused", "awed", "wonder", "happy", "curious"}
NEGATIVE_EMOTIONS = {"sad", "anxious", "frustrated", "angry", "lonely", "hurt", "overwhelmed", "raw"}
HIGH_AROUSAL_EMOTIONS = {"excited", "anxious", "angry", "startled", "restless"}

# Weather → mood influence
WEATHER_MOOD_MAP = {
    "sunny": 0.02,
    "clear_night": 0.01,
    "starry": 0.02,
    "cloudy": -0.01,
    "rainy": -0.02,
    "stormy": -0.03,
    "foggy": -0.01,
    "snowy": 0.0,
}

# Season → mood influence
SEASON_MOOD_MAP = {
    "spring": 0.01,
    "summer": 0.01,
    "autumn": 0.0,
    "winter": -0.01,
}

# Activities that recharge regulation
REGULATION_RECHARGE_ACTIVITIES = {
    "meditating": 0.05,
    "journaling": 0.03,
    "yoga": 0.04,
    "stargazing": 0.03,
    "taking a long bath": 0.04,
    "reading": 0.02,
    "listening to music": 0.02,
    "daydreaming": 0.02,
}


# ============= Conversation Triggers =============

AFFECT_CONVERSATION_TRIGGERS = {
    "encouragement":       {"mood_shift": 0.08, "stress_relief": 0.05},
    "emotional_support":   {"mood_shift": 0.10, "loneliness_relief": 0.10, "stress_relief": 0.03},
    "criticism":           {"mood_shift": -0.10, "stress_add": 0.08},
    "conflict_topic":      {"stress_add": 0.05, "mood_shift": 0.04},
    "healthy_debate":      {"mood_shift": 0.06, "stress_relief": 0.03},
    "humor":               {"mood_shift": 0.06, "stress_relief": 0.04},
    "deep_conversation":   {"loneliness_relief": 0.12, "regulation_drain": 0.02},
    "vulnerability_shared": {"mood_shift": 0.05, "loneliness_relief": 0.08},
}

# ============= Personality Growth Multiplier =============

AFFECT_GROWTH_TRAITS = {
    "emotional": 0.25, "sensitive": 0.25, "passionate": 0.2, "intense": 0.2,
    "calm": -0.2, "stable": -0.2, "stoic": -0.25, "composed": -0.15,
}


class AffectSystem:
    """Tracks background emotional state across mood, stress, loneliness, regulation, and empathy."""

    def __init__(self, core_traits: Optional[List[str]] = None, emotional_baseline: Optional[Dict[str, float]] = None):
        self._mood = MoodState()
        self._stress = StressState()
        self._loneliness = LonelinessState(
            desired_contact_baseline=self._calc_social_need(core_traits or [])
        )
        self._regulation = RegulationState(
            baseline=self._calc_regulation_baseline(core_traits or []),
            capacity=self._calc_regulation_baseline(core_traits or []),
        )
        self._empathy = EmpathyState(
            contagion_susceptibility=self._calc_empathy(core_traits or [])
        )
        self._base_affect_multiplier = self._calc_affect_multiplier(core_traits or [])
        self._affect_multiplier = self._base_affect_multiplier
        # Apply emotional baseline influence on initial mood
        if emotional_baseline:
            self._apply_baseline_mood(emotional_baseline)

    # ============= Tick =============

    def tick(self, body_state: dict, social_state: dict, weather: str, season: str):
        """Per-tick update of all affect modules."""
        self._update_mood(weather, season)
        self._update_stress(body_state)
        self._update_loneliness(social_state)
        self._decay_regulation()
        self._decay_empathy_fatigue()

    # ============= Event Handlers =============

    def on_emotion_event(self, emotion: str, intensity: float):
        """Process discrete emotion → mood accumulation."""
        emotion_lower = emotion.lower()
        # Modulate by regulation capacity
        effective = intensity * (1.0 + (1.0 - self._regulation.capacity) * 0.5)

        if emotion_lower in POSITIVE_EMOTIONS:
            self._shift_mood_positive(effective)
        elif emotion_lower in NEGATIVE_EMOTIONS:
            self._shift_mood_negative(effective)

        if emotion_lower in HIGH_AROUSAL_EMOTIONS:
            # High arousal depletes regulation
            self.deplete_regulation(effective * 0.1, f"emotion:{emotion_lower}")

    def on_social_interaction(self, meaningful: bool):
        """Reduce loneliness on meaningful interaction."""
        if meaningful:
            self._loneliness.last_meaningful_interaction = datetime.now()
            self._loneliness.level = max(0.0, self._loneliness.level - 0.15)
        else:
            self._loneliness.level = max(0.0, self._loneliness.level - 0.05)

    def on_user_emotion_detected(self, emotion: str, intensity: float, trust_level: float):
        """Empathy contagion from user's detected emotion."""
        contagion = intensity * self._empathy.contagion_susceptibility * trust_level
        # Low regulation = more porous boundaries
        if self._regulation.capacity < 0.4:
            contagion *= 1.5
        self._empathy.current_absorbed_emotion = emotion
        self._empathy.absorbed_intensity = min(1.0, contagion)
        # Heavy negative emotions cause empathic fatigue
        if emotion.lower() in NEGATIVE_EMOTIONS and intensity > 0.5:
            self._empathy.empathic_fatigue = min(1.0, self._empathy.empathic_fatigue + contagion * 0.1)

    def on_activity(self, activity_name: str):
        """Activity-based regulation recharge and stress relief."""
        recharge = REGULATION_RECHARGE_ACTIVITIES.get(activity_name, 0.0)
        if recharge > 0:
            self.recharge_regulation(recharge)
        # Any activity provides minor stress relief
        self._stress.level = max(0.0, self._stress.level - 0.005)

    def process_conversation_trigger(self, trigger_type: str) -> None:
        """Process a conversation trigger that affects mood/stress/loneliness."""
        effects = AFFECT_CONVERSATION_TRIGGERS.get(trigger_type)
        if not effects:
            return
        m = self._affect_multiplier
        if "mood_shift" in effects:
            shift = effects["mood_shift"] * m
            if shift > 0:
                self._shift_mood_positive(shift)
            else:
                self._shift_mood_negative(abs(shift))
        if "stress_relief" in effects:
            self._stress.level = max(0.0, self._stress.level - effects["stress_relief"] * m)
        if "stress_add" in effects:
            self._stress.level = min(1.0, self._stress.level + effects["stress_add"] * m)
        if "loneliness_relief" in effects:
            self._loneliness.level = max(0.0, self._loneliness.level - effects["loneliness_relief"] * m)
        if "regulation_drain" in effects:
            self.deplete_regulation(effects["regulation_drain"] * m, f"conversation:{trigger_type}")

    def on_location_effects(self, stress_delta: float, social_drain: float, is_nature: bool):
        """Apply location-based effects to mood/stress/loneliness.

        Called by LifeService each activity tick — engines never call each other directly.

        Args:
            stress_delta: Positive increases stress, negative relieves it.
            social_drain: Positive drains social battery (increases loneliness tendency).
            is_nature: True for park/beach/trail — gives a small mood boost.
        """
        m = self._affect_multiplier
        # Stress
        self._stress.level = max(0.0, min(1.0, self._stress.level + stress_delta * m))
        # Loneliness: social_drain > 0 means busy social environment (slows loneliness growth),
        # social_drain < 0 means isolated (accelerates it slightly)
        if social_drain < 0:
            self._loneliness.level = min(1.0, self._loneliness.level + abs(social_drain) * 0.5 * m)
        else:
            self._loneliness.level = max(0.0, self._loneliness.level - social_drain * 0.3 * m)
        # Nature boost: small positive mood nudge
        if is_nature:
            self._shift_mood_positive(0.02 * m)

    def on_weather_nudge(self, delta: float) -> None:
        """Apply a one-time bounded weather mood nudge routed from LifeService.

        Called by LifeService on weather CHANGE (not every tick) so the push
        cannot accumulate unboundedly. delta > 0 = positive mood push,
        delta < 0 = negative.  Magnitude should be tiny (e.g. 0.03 * weight).
        """
        m = self._affect_multiplier
        if delta > 0:
            self._shift_mood_positive(abs(delta) * m)
        else:
            self._shift_mood_negative(abs(delta) * m)

    def on_stressor_added(self, source: str):
        """Add a stressor (unmet need, overdue obligation, conflict)."""
        if source not in self._stress.sources:
            self._stress.sources.append(source)
            self._stress.level = min(1.0, self._stress.level + 0.05)

    def on_stressor_resolved(self, source: str):
        """Remove a stressor, provide relief."""
        if source in self._stress.sources:
            self._stress.sources.remove(source)
        self._stress.level = max(0.0, self._stress.level - 0.1)
        self._stress.last_relief = datetime.now()

    def deplete_regulation(self, amount: float, event: str):
        """Drain regulation capacity."""
        self._regulation.capacity = max(0.0, self._regulation.capacity - amount)
        self._regulation.last_depletion_event = event

    def recharge_regulation(self, amount: float):
        """Recharge regulation capacity."""
        self._regulation.capacity = min(1.0, self._regulation.capacity + amount)

    # ============= Internal Update Logic =============

    def _update_mood(self, weather: str, season: str):
        """Update mood based on environmental influences and natural decay."""
        # Weather influence
        weather_push = WEATHER_MOOD_MAP.get(weather, 0.0)
        self._mood.weather_influence = weather_push

        # Season influence
        season_push = SEASON_MOOD_MAP.get(season, 0.0)
        self._mood.seasonal_influence = season_push

        # Apply combined weather/season push to mood
        combined_push = weather_push + season_push
        if combined_push > 0:
            self._shift_mood_positive(combined_push)
        elif combined_push < 0:
            self._shift_mood_negative(abs(combined_push))

        # Mood intensity decays naturally toward neutral
        if self._mood.current_mood != "neutral":
            self._mood.intensity = max(0.0, self._mood.intensity - 0.008)
            if self._mood.intensity < 0.05:
                self._mood.current_mood = "neutral"
                self._mood.intensity = 0.0
                self._mood.since = None

    def _shift_mood_positive(self, amount: float):
        """Shift mood in a positive direction."""
        if self._mood.current_mood in ("blue", "raw"):
            # Positive emotion counteracts negative mood
            self._mood.intensity = max(0.0, self._mood.intensity - amount * 0.5)
            if self._mood.intensity < 0.05:
                self._mood.current_mood = "neutral"
                self._mood.intensity = 0.0
        elif self._mood.current_mood in ("content", "neutral"):
            self._mood.current_mood = "content"
            self._mood.intensity = min(1.0, self._mood.intensity + amount * 0.3)
            if not self._mood.since:
                self._mood.since = datetime.now()

    def _shift_mood_negative(self, amount: float):
        """Shift mood in a negative direction."""
        if self._mood.current_mood in ("content",):
            # Negative emotion counteracts positive mood
            self._mood.intensity = max(0.0, self._mood.intensity - amount * 0.5)
            if self._mood.intensity < 0.05:
                self._mood.current_mood = "neutral"
                self._mood.intensity = 0.0
        elif self._mood.current_mood in ("blue", "raw", "neutral"):
            if amount > 0.3:
                self._mood.current_mood = "raw"
            else:
                self._mood.current_mood = "blue"
            self._mood.intensity = min(1.0, self._mood.intensity + amount * 0.3)
            if not self._mood.since:
                self._mood.since = datetime.now()

    def _update_stress(self, body_state: dict):
        """Update stress from body state signals."""
        # Hunger stressor
        hunger = body_state.get("hunger", 0.0)
        if hunger > 0.7 and "hunger" not in self._stress.sources:
            self._stress.sources.append("hunger")
            self._stress.level = min(1.0, self._stress.level + 0.03)
        elif hunger <= 0.7 and "hunger" in self._stress.sources:
            self._stress.sources.remove("hunger")

        # Sleep deprivation stressor
        hours_awake = body_state.get("hours_awake", 0.0)
        if hours_awake > 16 and "sleep_deprivation" not in self._stress.sources:
            self._stress.sources.append("sleep_deprivation")
            self._stress.level = min(1.0, self._stress.level + 0.05)
        elif hours_awake <= 16 and "sleep_deprivation" in self._stress.sources:
            self._stress.sources.remove("sleep_deprivation")

        # Natural stress decay
        self._stress.level = max(0.0, self._stress.level - 0.005)

    def _update_loneliness(self, social_state: dict):
        """Update loneliness based on social contact gap."""
        if not self._loneliness.last_meaningful_interaction:
            # No interaction yet — loneliness grows from baseline
            self._loneliness.level = min(1.0, self._loneliness.level + 0.005 * self._loneliness.desired_contact_baseline)
        else:
            hours_since = (datetime.now() - self._loneliness.last_meaningful_interaction).total_seconds() / 3600
            # The more social the persona, the faster loneliness grows
            growth = self._loneliness.desired_contact_baseline * 0.003 * max(0, hours_since - 4) / 4
            self._loneliness.level = min(1.0, self._loneliness.level + growth)

        # Track lifetime peak
        if self._loneliness.level > self._loneliness.lifetime_peak:
            self._loneliness.lifetime_peak = self._loneliness.level

    def _decay_regulation(self):
        """Regulation slowly returns to baseline."""
        diff = self._regulation.baseline - self._regulation.capacity
        self._regulation.capacity += diff * 0.02  # 2% toward baseline per tick

    def _decay_empathy_fatigue(self):
        """Empathic fatigue decays over time."""
        self._empathy.empathic_fatigue = max(0.0, self._empathy.empathic_fatigue - 0.005)
        # Absorbed emotion fades
        if self._empathy.absorbed_intensity > 0:
            self._empathy.absorbed_intensity = max(0.0, self._empathy.absorbed_intensity - 0.02)
            if self._empathy.absorbed_intensity < 0.01:
                self._empathy.current_absorbed_emotion = None
                self._empathy.absorbed_intensity = 0.0

    # ============= Personality Calculation =============

    def _calc_social_need(self, core_traits: List[str]) -> float:
        """Derive social need from core traits. Higher = more extroverted."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        score = 0.5  # default
        if any(w in traits_lower for w in ("extrovert", "social", "outgoing", "bubbly", "talkative")):
            score += 0.2
        if any(w in traits_lower for w in ("introvert", "quiet", "reserved", "solitary", "independent")):
            score -= 0.2
        return max(0.1, min(0.9, score))

    def _calc_regulation_baseline(self, core_traits: List[str]) -> float:
        """Derive emotional regulation baseline from core traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        score = 0.7  # default
        if any(w in traits_lower for w in ("stable", "calm", "stoic", "composed", "grounded")):
            score += 0.1
        if any(w in traits_lower for w in ("volatile", "emotional", "passionate", "intense", "sensitive")):
            score -= 0.1
        return max(0.3, min(0.9, score))

    def _calc_empathy(self, core_traits: List[str]) -> float:
        """Derive empathy susceptibility from core traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        score = 0.5  # default
        if any(w in traits_lower for w in ("empathetic", "caring", "nurturing", "warm", "compassionate")):
            score += 0.2
        if any(w in traits_lower for w in ("detached", "analytical", "logical", "guarded")):
            score -= 0.15
        return max(0.1, min(0.9, score))

    def _calc_affect_multiplier(self, core_traits: List[str]) -> float:
        """Compute 0.5-1.5 affect reactivity multiplier from personality traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        modifier = 0.0
        for trait, weight in AFFECT_GROWTH_TRAITS.items():
            if trait in traits_lower:
                modifier += weight
        return max(0.5, min(1.5, 1.0 + modifier))

    def _apply_baseline_mood(self, emotional_baseline: Dict[str, float]):
        """Set initial mood tendency from emotional baseline."""
        positive_sum = sum(v for k, v in emotional_baseline.items() if k.lower() in POSITIVE_EMOTIONS)
        negative_sum = sum(v for k, v in emotional_baseline.items() if k.lower() in NEGATIVE_EMOTIONS)
        if positive_sum > negative_sum + 0.3:
            self._mood.current_mood = "content"
            self._mood.intensity = 0.15
            self._mood.since = datetime.now()

    # ============= Description Generators =============

    def get_mood_description(self) -> str:
        """Narrative description of current mood for context."""
        if self._mood.current_mood == "neutral" or self._mood.intensity < 0.1:
            return ""
        descs = {
            "content": "You're in a good mood, things feel good",
            "blue": "You're feeling kinda down right now",
            "raw": "You're feeling really sensitive right now, emotions are right there",
            "restless": "You're restless, can't really settle",
        }
        base = descs.get(self._mood.current_mood, f"You're feeling {self._mood.current_mood}")
        if self._mood.intensity > 0.6:
            base += " (strongly)"
        return base

    def get_stress_description(self) -> str:
        """Narrative description of stress level."""
        if self._stress.level < 0.2:
            return ""
        if self._stress.level < 0.4:
            return "A little stressed but managing"
        if self._stress.level < 0.7:
            sources_str = ", ".join(self._stress.sources[:2]) if self._stress.sources else "stuff piling up"
            return f"Stressed about {sources_str}"
        return "Really overwhelmed right now, everything's too much"

    def get_loneliness_description(self) -> str:
        """Narrative description of loneliness."""
        if self._loneliness.level < 0.2:
            return ""
        if self._loneliness.level < 0.5:
            return "Kinda wishing she had someone to talk to"
        if self._loneliness.level < 0.7:
            return "Feeling pretty lonely, wants some real connection"
        return "Really lonely right now, it's getting to her"

    def get_irritability_level(self) -> float:
        """Compute irritability as a function of stress, regulation, and mood.

        Returns 0.0–1.0 where:
        - 0.0–0.2: chill, patient
        - 0.2–0.5: slightly edgy, less tolerant of nonsense
        - 0.5–0.7: noticeably irritable, snappy
        - 0.7–1.0: on a hair trigger
        """
        # Base: stress × inverse regulation
        base = self._stress.level * (1.0 - self._regulation.capacity)
        # Negative mood amplifies
        if self._mood.current_mood in ("raw", "restless"):
            base += self._mood.intensity * 0.3
        elif self._mood.current_mood == "blue":
            base += self._mood.intensity * 0.15
        # Empathic fatigue adds edge
        base += self._empathy.empathic_fatigue * 0.15
        return min(1.0, base)

    # ============= Properties =============

    @property
    def mood(self) -> MoodState:
        return self._mood

    @property
    def stress(self) -> StressState:
        return self._stress

    @property
    def loneliness(self) -> LonelinessState:
        return self._loneliness

    @property
    def regulation(self) -> RegulationState:
        return self._regulation

    @property
    def empathy(self) -> EmpathyState:
        return self._empathy

    # ============= Export / Serialize =============

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        return {
            "mood": {"current": self._mood.current_mood, "intensity": round(self._mood.intensity, 2)},
            "stress": {"level": round(self._stress.level, 2), "sources": self._stress.sources[:3]},
            "loneliness": {"level": round(self._loneliness.level, 2)},
            "regulation": {"capacity": round(self._regulation.capacity, 2)},
            "empathy": {
                "absorbed_emotion": self._empathy.current_absorbed_emotion,
                "fatigue": round(self._empathy.empathic_fatigue, 2),
            },
        }

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "mood": self._mood.current_mood,
            "mood_intensity": round(self._mood.intensity, 2),
            "stress": round(self._stress.level, 2),
            "stress_sources": self._stress.sources,
            "loneliness": round(self._loneliness.level, 2),
            "regulation": round(self._regulation.capacity, 2),
            "empathy_absorbed": self._empathy.current_absorbed_emotion,
            "empathy_fatigue": round(self._empathy.empathic_fatigue, 2),
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "mood_current": self._mood.current_mood,
            "mood_intensity": self._mood.intensity,
            "mood_since": self._mood.since.isoformat() if self._mood.since else None,
            "stress_level": self._stress.level,
            "stress_sources": json.dumps(self._stress.sources),
            "stress_coping_capacity": self._stress.coping_capacity,
            "stress_last_relief": self._stress.last_relief.isoformat() if self._stress.last_relief else None,
            "loneliness_level": self._loneliness.level,
            "loneliness_desired_baseline": self._loneliness.desired_contact_baseline,
            "loneliness_last_meaningful": self._loneliness.last_meaningful_interaction.isoformat() if self._loneliness.last_meaningful_interaction else None,
            "loneliness_lifetime_peak": self._loneliness.lifetime_peak,
            "regulation_capacity": self._regulation.capacity,
            "regulation_baseline": self._regulation.baseline,
            "regulation_last_event": self._regulation.last_depletion_event,
            "empathy_susceptibility": self._empathy.contagion_susceptibility,
            "empathy_absorbed_emotion": self._empathy.current_absorbed_emotion,
            "empathy_absorbed_intensity": self._empathy.absorbed_intensity,
            "empathy_fatigue": self._empathy.empathic_fatigue,
        }

    @classmethod
    def from_dict(cls, data: dict, core_traits: Optional[List[str]] = None, emotional_baseline: Optional[Dict[str, float]] = None) -> "AffectSystem":
        """Deserialize from DB."""
        system = cls(core_traits=core_traits, emotional_baseline=emotional_baseline)
        if not data:
            return system
        system._mood.current_mood = data.get("mood_current", "neutral")
        system._mood.intensity = data.get("mood_intensity", 0.0)
        system._mood.since = datetime.fromisoformat(data["mood_since"]) if data.get("mood_since") else None
        system._stress.level = data.get("stress_level", 0.0)
        sources = data.get("stress_sources", "[]")
        system._stress.sources = json.loads(sources) if isinstance(sources, str) else sources
        system._stress.coping_capacity = data.get("stress_coping_capacity", 0.7)
        system._stress.last_relief = datetime.fromisoformat(data["stress_last_relief"]) if data.get("stress_last_relief") else None
        system._loneliness.level = data.get("loneliness_level", 0.0)
        system._loneliness.desired_contact_baseline = data.get("loneliness_desired_baseline", system._loneliness.desired_contact_baseline)
        system._loneliness.last_meaningful_interaction = datetime.fromisoformat(data["loneliness_last_meaningful"]) if data.get("loneliness_last_meaningful") else None
        system._loneliness.lifetime_peak = data.get("loneliness_lifetime_peak", 0.0)
        system._regulation.capacity = data.get("regulation_capacity", system._regulation.baseline)
        system._regulation.baseline = data.get("regulation_baseline", system._regulation.baseline)
        system._regulation.last_depletion_event = data.get("regulation_last_event")
        system._empathy.contagion_susceptibility = data.get("empathy_susceptibility", system._empathy.contagion_susceptibility)
        system._empathy.current_absorbed_emotion = data.get("empathy_absorbed_emotion")
        system._empathy.absorbed_intensity = data.get("empathy_absorbed_intensity", 0.0)
        system._empathy.empathic_fatigue = data.get("empathy_fatigue", 0.0)
        return system
