"""
Body Engine

Tracks physical state across six modules:
- Physical Health: general wellness, minor ailments
- Hormonal Cycle: optional 28-day cycle affecting mood/energy
- Physical Comfort: posture, temperature, pain
- Appearance: outfit, hair, put-togetherness
- Sleep Quality: insomnia risk, dream vividness, consecutive poor nights
- Fitness: cardio, strength, flexibility trajectories
"""

import json
import logging
import random
from datetime import datetime

from ..models import (
    InebriationState,
    PhysicalHealthState,
    HormonalCycleState,
    PhysicalComfortState,
    AppearanceState,
    SleepQualityState,
    FitnessState,
)

logger = logging.getLogger(__name__)

# Activity → fitness category mapping
CARDIO_ACTIVITIES = {"going for a run", "gym workout", "dancing"}
STRENGTH_ACTIVITIES = {"gym workout"}
FLEXIBILITY_ACTIVITIES = {"yoga", "stretching"}
COMFORT_RELIEF_ACTIVITIES = {"yoga", "stretching", "taking a long bath", "going for a walk"}
SITTING_ACTIVITIES = {"reading", "writing poetry", "journaling", "sketching ideas", "learning something new"}

# Substance activities → (substance type, intoxication increment)
SUBSTANCE_ACTIVITIES = {
    "going out for drinks": ("alcohol", 0.3),
    "having cocktails": ("alcohol", 0.35),
    "drinking wine": ("wine", 0.25),
    "wine tasting": ("wine", 0.2),
    "happy hour": ("alcohol", 0.3),
    "having a beer": ("beer", 0.15),
}
INEBRIATION_DECAY_RATE = 0.02
HANGOVER_THRESHOLD = 0.4
HANGOVER_DECAY_RATE = 0.01

# Acute health recovery (illness heals faster than injury)
ILLNESS_RECOVERY_RATE = 0.02       # illness_severity decay per tick
INJURY_RECOVERY_RATE = 0.006       # injury_severity decay per tick (slower heal)
UNWELL_THRESHOLD = 0.05            # severity below this counts as recovered/healthy

# Body-image dynamics
BODY_IMAGE_DRIFT_RATE = 0.004      # pull toward baseline per tick
BODY_IMAGE_AILMENT_NUDGE = 0.01    # downward nudge per tick while ill/injured (scaled by severity)
BODY_IMAGE_MOOD_NUDGE = 0.006      # downward nudge per tick for low mood
BODY_IMAGE_SHAME_NUDGE = 0.01      # downward nudge per tick for high shame
BODY_IMAGE_FITNESS_NUDGE = 0.004   # upward nudge per tick for good fitness/comfort
LOW_MOOD_THRESHOLD = 0.35          # mood below this drags body_image down
HIGH_SHAME_THRESHOLD = 0.5         # shame above this drags body_image down

# Seeding: phrases in struggles/traits that lower the body_image baseline
BODY_IMAGE_STRUGGLE_MARKERS = (
    "body issues",
    "body image",
    "insecure about her looks",
    "insecure about my looks",
    "eating disorder",
    "hates her body",
    "hate my body",
)
BODY_IMAGE_SEED_LOW = 0.35         # baseline when struggles indicate body-image problems

# Minor ailments pool
MINOR_AILMENTS = [
    {"name": "headache", "severity": 0.3, "duration_hours": 4},
    {"name": "sore throat", "severity": 0.2, "duration_hours": 12},
    {"name": "cramps", "severity": 0.3, "duration_hours": 3},
    {"name": "back ache", "severity": 0.25, "duration_hours": 8},
    {"name": "eye strain", "severity": 0.15, "duration_hours": 2},
]

# Weather → temperature comfort
WEATHER_TEMP_MAP = {
    "sunny": 0.8,
    "cloudy": 0.7,
    "rainy": 0.5,
    "stormy": 0.4,
    "foggy": 0.6,
    "snowy": 0.3,
    "clear_night": 0.6,
    "starry": 0.6,
}

# Hormonal phase → day ranges
HORMONAL_PHASES = [
    (1, 13, "follicular"),
    (14, 16, "ovulation"),
    (17, 24, "luteal"),
    (25, 28, "premenstrual"),
]


class BodySystem:
    """Manages all physical body state modules."""

    def __init__(self, hormonal_enabled: bool = False, substance_tendencies: dict = None,
                 struggles: list = None, core_traits: list = None):
        self._health = PhysicalHealthState()
        self._hormonal = HormonalCycleState(enabled=hormonal_enabled)
        self._comfort = PhysicalComfortState()
        self._appearance = AppearanceState()
        self._sleep = SleepQualityState()
        self._fitness = FitnessState()
        self._inebriation = InebriationState()
        self._substance_tendencies = substance_tendencies or {}
        self._seed_body_image(struggles, core_traits)

    def _seed_body_image(self, struggles: list = None, core_traits: list = None):
        """Seed body_image baseline LOWER when struggles/traits signal body-image problems."""
        haystack = " ".join(
            str(x).lower() for x in (list(struggles or []) + list(core_traits or []))
        )
        if any(marker in haystack for marker in BODY_IMAGE_STRUGGLE_MARKERS):
            self._health.body_image = BODY_IMAGE_SEED_LOW
        # Baseline is the seeded resting set-point body_image drifts toward.
        self._health.body_image_baseline = self._health.body_image

    # ============= Tick =============

    def tick(self, activity_name: str, weather: str, hours_awake: float, stress_level: float, **kwargs):
        """Per-tick update of all body modules.

        Optional kwargs (read defensively so existing callers don't break):
          mood: float = 0.5    — current mood, low mood drags body_image down
          shame: float = 0.0   — current shame, high shame drags body_image down
        """
        mood = kwargs.get("mood", 0.5)
        shame = kwargs.get("shame", 0.0)
        self._update_comfort(activity_name, weather)
        self._update_appearance(hours_awake)
        self._resolve_conditions()
        self._recover_acute_health()
        self._update_body_image(mood, shame)
        self._update_insomnia_risk(stress_level)
        # Fitness decays very slowly each tick
        self._decay_fitness()
        self._tick_inebriation()

    def on_new_day(self):
        """Daily reset and rolls."""
        self.roll_daily_health()
        if self._hormonal.enabled:
            self.advance_hormonal_cycle()
        # Reset appearance for new day
        self._appearance.put_togetherness = 0.7
        self._appearance.hair_state = "styled"

    # ============= Activity Handlers =============

    def on_activity(self, activity_name: str):
        """Update body state from activity."""
        # Fitness improvement
        if activity_name in CARDIO_ACTIVITIES:
            self._fitness.cardio = min(1.0, self._fitness.cardio + 0.002)
            self._fitness.last_cardio_session = datetime.now()
            if self._fitness.cardio > self._fitness.peak_cardio:
                self._fitness.peak_cardio = self._fitness.cardio
        if activity_name in STRENGTH_ACTIVITIES:
            self._fitness.strength = min(1.0, self._fitness.strength + 0.002)
            self._fitness.last_strength_session = datetime.now()
            if self._fitness.strength > self._fitness.peak_strength:
                self._fitness.peak_strength = self._fitness.strength
        if activity_name in FLEXIBILITY_ACTIVITIES:
            self._fitness.flexibility = min(1.0, self._fitness.flexibility + 0.002)
            self._fitness.last_flexibility_session = datetime.now()

        # Comfort from relief activities
        if activity_name in COMFORT_RELIEF_ACTIVITIES:
            self._comfort.posture_stiffness = max(0.0, self._comfort.posture_stiffness - 0.15)
            self._comfort.level = min(1.0, self._comfort.level + 0.1)

        # Sitting increases stiffness
        if activity_name in SITTING_ACTIVITIES:
            self._comfort.posture_stiffness = min(1.0, self._comfort.posture_stiffness + 0.03)

        # Post-workout soreness
        if activity_name in CARDIO_ACTIVITIES | STRENGTH_ACTIVITIES:
            self._comfort.pain_level = min(1.0, self._comfort.pain_level + 0.1)

    def on_sleep(self, stress_level: float, caffeine_boost: float):
        """Calculate sleep quality when sleeping."""
        # Base quality
        quality = 0.7
        # Stress reduces quality
        quality -= stress_level * 0.3
        # Caffeine reduces quality
        quality -= caffeine_boost * 0.5
        # Insomnia risk reduces quality
        quality -= self._sleep.insomnia_risk * 0.2
        quality = max(0.1, min(1.0, quality))

        self._sleep.last_quality = quality
        self._sleep.dream_vividness = 0.3 + random.uniform(0.0, 0.4)

        if quality < 0.4:
            self._sleep.consecutive_poor_nights += 1
        else:
            self._sleep.consecutive_poor_nights = 0

        # Reset comfort on sleep
        self._comfort.posture_stiffness = 0.0
        self._comfort.pain_level = max(0.0, self._comfort.pain_level - 0.3)

    # ============= Health =============

    def roll_daily_health(self):
        """Small chance of minor ailment each day (3%)."""
        if random.random() < 0.03 and not self._health.active_conditions:
            ailment = random.choice(MINOR_AILMENTS).copy()
            ailment["started_at"] = datetime.now().isoformat()
            self._health.active_conditions.append(ailment)
            self._health.wellness = max(0.3, self._health.wellness - ailment["severity"])
            logger.info(f"Body: minor ailment — {ailment['name']}")

    def _resolve_conditions(self):
        """Remove expired conditions."""
        now = datetime.now()
        remaining = []
        for cond in self._health.active_conditions:
            started = datetime.fromisoformat(cond["started_at"])
            if (now - started).total_seconds() / 3600 < cond.get("duration_hours", 6):
                remaining.append(cond)
            else:
                self._health.wellness = min(1.0, self._health.wellness + cond["severity"] * 0.5)
        self._health.active_conditions = remaining

    # ============= Acute Health (illness / injury) =============

    def fall_ill(self, kind: str, severity: float = 0.4):
        """Come down with an acute illness (e.g. 'a cold', 'a stomach bug', 'cramps')."""
        self._health.illness = kind
        self._health.illness_severity = max(0.0, min(1.0, severity))
        logger.info(f"Body: fell ill — {kind} (severity {self._health.illness_severity:.2f})")

    def get_injured(self, kind: str, severity: float = 0.5):
        """Sustain an injury (e.g. 'a sprained ankle', 'a broken wrist'). Heals slower than illness."""
        self._health.injury = kind
        self._health.injury_severity = max(0.0, min(1.0, severity))
        logger.info(f"Body: injured — {kind} (severity {self._health.injury_severity:.2f})")

    def _recover_acute_health(self):
        """Decay illness/injury severity each tick; clear the label once recovered.

        While unwell, drag physical wellness and comfort down proportionally to severity
        so downstream energy/mood react via existing wiring.
        """
        if self._health.illness_severity > 0:
            self._health.illness_severity = max(0.0, self._health.illness_severity - ILLNESS_RECOVERY_RATE)
            if self._health.illness_severity <= UNWELL_THRESHOLD:
                self._health.illness_severity = 0.0
                self._health.illness = ""
        if self._health.injury_severity > 0:
            self._health.injury_severity = max(0.0, self._health.injury_severity - INJURY_RECOVERY_RATE)
            if self._health.injury_severity <= UNWELL_THRESHOLD:
                self._health.injury_severity = 0.0
                self._health.injury = ""

        # Depress wellness/comfort while unwell (proportional to worst severity).
        burden = max(self._health.illness_severity, self._health.injury_severity)
        if burden > 0:
            self._health.wellness = max(0.0, min(1.0, self._health.wellness - burden * 0.05))
            self._comfort.level = max(0.0, min(1.0, self._comfort.level - burden * 0.05))

    def is_unwell(self) -> bool:
        """True if currently ill or injured above a small threshold."""
        return (self._health.illness_severity > UNWELL_THRESHOLD
                or self._health.injury_severity > UNWELL_THRESHOLD)

    def health_label(self) -> str:
        """Short human phrase describing acute health state."""
        ill = self._health.illness_severity > UNWELL_THRESHOLD
        hurt = self._health.injury_severity > UNWELL_THRESHOLD
        if ill and hurt:
            # Lead with whichever is worse.
            if self._health.illness_severity >= self._health.injury_severity:
                return f"down with {self._health.illness}, also nursing {self._health.injury}"
            return f"nursing {self._health.injury}, also down with {self._health.illness}"
        if ill:
            return f"down with {self._health.illness}" if self._health.illness else "under the weather"
        if hurt:
            return f"nursing {self._health.injury}" if self._health.injury else "under the weather"
        return "healthy"

    # ============= Body Image =============

    def _update_body_image(self, mood: float = 0.5, shame: float = 0.0):
        """Drift body_image toward its per-persona baseline, nudged by state.

        Down: active illness/injury, low mood, high shame.
        Up: good fitness and comfort.
        """
        bi = self._health.body_image
        # Drift toward baseline.
        bi += (self._health.body_image_baseline - bi) * BODY_IMAGE_DRIFT_RATE
        # Downward: acute health burden.
        burden = max(self._health.illness_severity, self._health.injury_severity)
        if burden > 0:
            bi -= BODY_IMAGE_AILMENT_NUDGE * burden
        # Downward: low mood.
        if mood < LOW_MOOD_THRESHOLD:
            bi -= BODY_IMAGE_MOOD_NUDGE
        # Downward: high shame.
        if shame > HIGH_SHAME_THRESHOLD:
            bi -= BODY_IMAGE_SHAME_NUDGE
        # Upward: good fitness + comfort.
        avg_fitness = (self._fitness.cardio + self._fitness.strength + self._fitness.flexibility) / 3.0
        if avg_fitness > 0.6 and self._comfort.level > 0.6:
            bi += BODY_IMAGE_FITNESS_NUDGE
        self._health.body_image = max(0.0, min(1.0, bi))

    # ============= Hormonal =============

    def advance_hormonal_cycle(self):
        """Advance cycle by one day."""
        if not self._hormonal.enabled:
            return
        self._hormonal.cycle_day = (self._hormonal.cycle_day % 28) + 1
        for start, end, phase in HORMONAL_PHASES:
            if start <= self._hormonal.cycle_day <= end:
                self._hormonal.phase = phase
                break

    def get_hormonal_modifiers(self) -> dict:
        """Get mood/energy modifiers from hormonal phase."""
        if not self._hormonal.enabled:
            return {}
        modifiers = {
            "follicular": {"energy_mod": 0.0, "sensitivity_mod": 0.0},
            "ovulation": {"energy_mod": 0.05, "sensitivity_mod": -0.05},
            "luteal": {"energy_mod": -0.03, "sensitivity_mod": 0.05},
            "premenstrual": {"energy_mod": -0.05, "sensitivity_mod": 0.1},
        }
        return modifiers.get(self._hormonal.phase, {})

    # ============= Comfort =============

    def _update_comfort(self, activity_name: str, weather: str):
        """Update comfort from environment."""
        self._comfort.temperature_comfort = WEATHER_TEMP_MAP.get(weather, 0.7)
        # Overall comfort is average of components
        self._comfort.level = max(0.0, min(1.0,
            0.4 * (1.0 - self._comfort.posture_stiffness) +
            0.3 * self._comfort.temperature_comfort +
            0.3 * (1.0 - self._comfort.pain_level)
        ))

    # ============= Appearance =============

    def _update_appearance(self, hours_awake: float):
        """Appearance degrades through the day."""
        if hours_awake > 4:
            self._appearance.put_togetherness = max(0.2, self._appearance.put_togetherness - 0.005)
        if hours_awake > 14:
            self._appearance.hair_state = "messy"

    # ============= Sleep =============

    def _update_insomnia_risk(self, stress_level: float):
        """Update insomnia risk from stress."""
        if stress_level > 0.6:
            self._sleep.insomnia_risk = min(1.0, self._sleep.insomnia_risk + 0.005)
        elif stress_level > 0.4:
            self._sleep.insomnia_risk = min(1.0, self._sleep.insomnia_risk + 0.002)
        else:
            self._sleep.insomnia_risk = max(0.0, self._sleep.insomnia_risk - 0.005)

    # ============= Fitness =============

    def _decay_fitness(self):
        """Very slow fitness decay per tick."""
        now = datetime.now()
        # Cardio decays if no session in 3+ days
        if self._fitness.last_cardio_session:
            days_since = (now - self._fitness.last_cardio_session).days
            if days_since > 3:
                self._fitness.cardio = max(0.1, self._fitness.cardio - 0.0005)
        # Strength decays if no session in 4+ days
        if self._fitness.last_strength_session:
            days_since = (now - self._fitness.last_strength_session).days
            if days_since > 4:
                self._fitness.strength = max(0.1, self._fitness.strength - 0.0003)
        # Flexibility decays if no session in 2+ days
        if self._fitness.last_flexibility_session:
            days_since = (now - self._fitness.last_flexibility_session).days
            if days_since > 2:
                self._fitness.flexibility = max(0.1, self._fitness.flexibility - 0.0005)

    # ============= Inebriation =============

    def on_substance_activity(self, activity_name: str):
        """Check if activity involves substances and apply inebriation."""
        entry = SUBSTANCE_ACTIVITIES.get(activity_name)
        if not entry:
            return
        substance, increment = entry
        # Apply tendency multiplier
        tendency = self._substance_tendencies.get(substance, "")
        if not tendency:
            tendency = self._substance_tendencies.get("alcohol", "")
        if tendency == "avoidant":
            return  # Won't drink
        elif tendency == "heavy":
            increment *= 1.3
        elif tendency == "occasional":
            increment *= 0.7
        self._inebriation.level = min(1.0, self._inebriation.level + increment)
        self._inebriation.substance = substance
        if not self._inebriation.started_at:
            self._inebriation.started_at = datetime.now()
        self._inebriation.last_drink_at = datetime.now()

    def _tick_inebriation(self):
        """Decay inebriation level each tick."""
        if self._inebriation.level > 0:
            self._inebriation.level = max(0.0, self._inebriation.level - INEBRIATION_DECAY_RATE)
            if self._inebriation.level < 0.01:
                self._inebriation.level = 0.0
                self._inebriation.substance = ""
                self._inebriation.started_at = None
        # Hangover decays during daytime
        if self._inebriation.hangover_severity > 0:
            self._inebriation.hangover_severity = max(0.0, self._inebriation.hangover_severity - HANGOVER_DECAY_RATE)

    def on_sleep_inebriation(self):
        """Calculate hangover when going to sleep inebriated."""
        if self._inebriation.level >= HANGOVER_THRESHOLD:
            self._inebriation.hangover_severity = min(1.0, self._inebriation.level * 0.7)
        self._inebriation.level = 0.0
        self._inebriation.substance = ""
        self._inebriation.started_at = None

    def get_inebriation_effects(self) -> dict:
        """Get current inebriation effects on other systems."""
        level = self._inebriation.level
        hangover = self._inebriation.hangover_severity
        return {
            "is_inebriated": level > 0.1,
            "is_hungover": hangover > 0.1,
            "level": round(level, 2),
            "hangover": round(hangover, 2),
            "substance": self._inebriation.substance,
            "focus_penalty": level * 0.3,
            "mood_shift": level * 0.2 if level < 0.6 else -level * 0.1,
            "energy_penalty": hangover * 0.3,
            "inhibition_reduction": level * 0.4,
        }

    # ============= Export / Serialize =============

    @staticmethod
    def _severity_word(severity: float) -> str:
        """Coarse severity bucket for digest output."""
        if severity >= 0.6:
            return "bad"
        if severity >= 0.3:
            return "moderate"
        return "mild"

    def export_state(self) -> dict:
        """Structured export for pipeline digest."""
        state = {
            "wellness": round(self._health.wellness, 2),
            "active_conditions": [c["name"] for c in self._health.active_conditions],
            "comfort": round(self._comfort.level, 2),
            "posture_stiffness": round(self._comfort.posture_stiffness, 2),
            "appearance": {
                "outfit": self._appearance.outfit,
                "hair": self._appearance.hair_state,
                "put_togetherness": round(self._appearance.put_togetherness, 2),
            },
            "sleep_quality": round(self._sleep.last_quality, 2),
            "consecutive_poor_nights": self._sleep.consecutive_poor_nights,
            "fitness": {
                "cardio": round(self._fitness.cardio, 2),
                "strength": round(self._fitness.strength, 2),
                "flexibility": round(self._fitness.flexibility, 2),
            },
            "inebriation": {
                "level": round(self._inebriation.level, 2),
                "substance": self._inebriation.substance,
                "hangover": round(self._inebriation.hangover_severity, 2),
            } if self._inebriation.level > 0.05 or self._inebriation.hangover_severity > 0.05 else {},
        }
        # Body image — only when notable.
        if self._health.body_image < 0.45:
            state["body_image"] = {"value": round(self._health.body_image, 2), "feeling": "dissatisfied"}
        elif self._health.body_image > 0.75:
            state["body_image"] = {"value": round(self._health.body_image, 2), "feeling": "confident"}
        # Acute health — only when unwell.
        if self.is_unwell():
            state["health_label"] = self.health_label()
            if self._health.illness_severity > UNWELL_THRESHOLD:
                state["illness"] = {
                    "what": self._health.illness,
                    "severity": self._severity_word(self._health.illness_severity),
                }
            if self._health.injury_severity > UNWELL_THRESHOLD:
                state["injury"] = {
                    "what": self._health.injury,
                    "severity": self._severity_word(self._health.injury_severity),
                }
        return state

    def get_status(self) -> dict:
        """Status for API/debugging."""
        return {
            "wellness": round(self._health.wellness, 2),
            "conditions": [c["name"] for c in self._health.active_conditions],
            "body_image": round(self._health.body_image, 2),
            "illness": self._health.illness,
            "illness_severity": round(self._health.illness_severity, 2),
            "injury": self._health.injury,
            "injury_severity": round(self._health.injury_severity, 2),
            "hormonal_phase": self._hormonal.phase if self._hormonal.enabled else None,
            "comfort": round(self._comfort.level, 2),
            "stiffness": round(self._comfort.posture_stiffness, 2),
            "outfit": self._appearance.outfit,
            "hair": self._appearance.hair_state,
            "put_togetherness": round(self._appearance.put_togetherness, 2),
            "sleep_quality": round(self._sleep.last_quality, 2),
            "insomnia_risk": round(self._sleep.insomnia_risk, 2),
            "fitness_cardio": round(self._fitness.cardio, 2),
            "fitness_strength": round(self._fitness.strength, 2),
            "fitness_flexibility": round(self._fitness.flexibility, 2),
            "inebriation_level": round(self._inebriation.level, 2),
            "inebriation_substance": self._inebriation.substance,
            "inebriation_hangover": round(self._inebriation.hangover_severity, 2),
        }

    def to_dict(self) -> dict:
        """Serialize for DB storage."""
        return {
            "wellness": self._health.wellness,
            "active_conditions": json.dumps(self._health.active_conditions),
            "body_image": self._health.body_image,
            "body_image_baseline": self._health.body_image_baseline,
            "illness": self._health.illness,
            "illness_severity": self._health.illness_severity,
            "injury": self._health.injury,
            "injury_severity": self._health.injury_severity,
            "hormonal_enabled": self._hormonal.enabled,
            "hormonal_cycle_day": self._hormonal.cycle_day,
            "comfort_level": self._comfort.level,
            "posture_stiffness": self._comfort.posture_stiffness,
            "outfit": self._appearance.outfit,
            "hair_state": self._appearance.hair_state,
            "put_togetherness": self._appearance.put_togetherness,
            "sleep_last_quality": self._sleep.last_quality,
            "sleep_insomnia_risk": self._sleep.insomnia_risk,
            "sleep_consecutive_poor": self._sleep.consecutive_poor_nights,
            "fitness_cardio": self._fitness.cardio,
            "fitness_strength": self._fitness.strength,
            "fitness_flexibility": self._fitness.flexibility,
            "fitness_peak_cardio": self._fitness.peak_cardio,
            "fitness_peak_strength": self._fitness.peak_strength,
            "fitness_last_cardio": self._fitness.last_cardio_session.isoformat() if self._fitness.last_cardio_session else None,
            "fitness_last_strength": self._fitness.last_strength_session.isoformat() if self._fitness.last_strength_session else None,
            "fitness_last_flexibility": self._fitness.last_flexibility_session.isoformat() if self._fitness.last_flexibility_session else None,
            "inebriation_level": self._inebriation.level,
            "inebriation_substance": self._inebriation.substance,
            "inebriation_started_at": self._inebriation.started_at.isoformat() if self._inebriation.started_at else None,
            "inebriation_hangover": self._inebriation.hangover_severity,
            "inebriation_last_drink": self._inebriation.last_drink_at.isoformat() if self._inebriation.last_drink_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BodySystem":
        """Deserialize from DB."""
        system = cls(hormonal_enabled=bool(data.get("hormonal_enabled", False)))
        if not data:
            return system
        system._health.wellness = data.get("wellness", 0.8)
        conditions = data.get("active_conditions", "[]")
        system._health.active_conditions = json.loads(conditions) if isinstance(conditions, str) else conditions
        system._health.body_image = data.get("body_image", 0.6)
        # Old rows lack a stored baseline — fall back to the restored body_image.
        system._health.body_image_baseline = data.get("body_image_baseline", system._health.body_image)
        system._health.illness = data.get("illness", "")
        system._health.illness_severity = data.get("illness_severity", 0.0)
        system._health.injury = data.get("injury", "")
        system._health.injury_severity = data.get("injury_severity", 0.0)
        system._hormonal.cycle_day = data.get("hormonal_cycle_day", 1)
        # Derive phase from day
        for start, end, phase in HORMONAL_PHASES:
            if start <= system._hormonal.cycle_day <= end:
                system._hormonal.phase = phase
                break
        system._comfort.level = data.get("comfort_level", 0.7)
        system._comfort.posture_stiffness = data.get("posture_stiffness", 0.0)
        system._appearance.outfit = data.get("outfit", "")
        system._appearance.hair_state = data.get("hair_state", "styled")
        system._appearance.put_togetherness = data.get("put_togetherness", 0.7)
        system._sleep.last_quality = data.get("sleep_last_quality", 0.7)
        system._sleep.insomnia_risk = data.get("sleep_insomnia_risk", 0.0)
        system._sleep.consecutive_poor_nights = data.get("sleep_consecutive_poor", 0)
        system._fitness.cardio = data.get("fitness_cardio", 0.3)
        system._fitness.strength = data.get("fitness_strength", 0.2)
        system._fitness.flexibility = data.get("fitness_flexibility", 0.3)
        system._fitness.peak_cardio = data.get("fitness_peak_cardio", 0.3)
        system._fitness.peak_strength = data.get("fitness_peak_strength", 0.2)
        system._fitness.last_cardio_session = datetime.fromisoformat(data["fitness_last_cardio"]) if data.get("fitness_last_cardio") else None
        system._fitness.last_strength_session = datetime.fromisoformat(data["fitness_last_strength"]) if data.get("fitness_last_strength") else None
        system._fitness.last_flexibility_session = datetime.fromisoformat(data["fitness_last_flexibility"]) if data.get("fitness_last_flexibility") else None
        # Inebriation
        system._inebriation = InebriationState(
            level=data.get("inebriation_level", 0.0),
            substance=data.get("inebriation_substance", ""),
            started_at=datetime.fromisoformat(data["inebriation_started_at"]) if data.get("inebriation_started_at") else None,
            hangover_severity=data.get("inebriation_hangover", 0.0),
            last_drink_at=datetime.fromisoformat(data["inebriation_last_drink"]) if data.get("inebriation_last_drink") else None,
        )
        system._substance_tendencies = data.get("_substance_tendencies", {})
        return system

    # ============= Properties =============

    @property
    def health(self) -> PhysicalHealthState:
        return self._health

    @property
    def comfort(self) -> PhysicalComfortState:
        return self._comfort

    @property
    def appearance(self) -> AppearanceState:
        return self._appearance

    @property
    def sleep_quality(self) -> SleepQualityState:
        return self._sleep

    @property
    def fitness(self) -> FitnessState:
        return self._fitness

    @property
    def hormonal(self) -> HormonalCycleState:
        return self._hormonal

    @property
    def inebriation(self) -> InebriationState:
        return self._inebriation
