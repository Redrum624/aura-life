"""
Energy System

Manages the persona's energy levels, fatigue, circadian rhythms, and boosts.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ..models import EnergyState, EnergyLevel, TimeOfDay


# ============= Circadian Rhythm =============

# Base energy levels by time of day
CIRCADIAN_BASE: Dict[TimeOfDay, float] = {
    TimeOfDay.DAWN: 0.5,       # Waking up
    TimeOfDay.MORNING: 0.9,    # Peak energy
    TimeOfDay.AFTERNOON: 0.75,  # Post-lunch dip
    TimeOfDay.EVENING: 0.65,   # Winding down
    TimeOfDay.NIGHT: 0.45,     # Getting tired
    TimeOfDay.LATE_NIGHT: 0.25,  # Should sleep
}


def is_within_sleep_window(hour: int, bedtime_hour: int, wake_hour: int) -> bool:
    """True if `hour` falls inside the [bedtime, wake) sleep window.

    Handles both normal schedules (bedtime 23, wake 7 -> wraps midnight) and
    night-owl schedules where bedtime < wake (e.g. 2am..10am, no wrap).
    """
    if bedtime_hour < wake_hour:
        return bedtime_hour <= hour < wake_hour
    return hour >= bedtime_hour or hour < wake_hour


# Energy descriptions
ENERGY_DESCRIPTIONS: Dict[EnergyLevel, str] = {
    EnergyLevel.EXHAUSTED: "dead tired, can barely keep her eyes open",
    EnergyLevel.TIRED: "pretty tired, slowing down",
    EnergyLevel.RESTING: "taking it easy, low-key",
    EnergyLevel.COMFORTABLE: "feeling fine, normal energy",
    EnergyLevel.ALERT: "awake and sharp, on it",
    EnergyLevel.ENERGIZED: "full of energy, hyped up",
}

# Response modifiers based on energy
RESPONSE_MODIFIERS: Dict[EnergyLevel, Dict] = {
    EnergyLevel.EXHAUSTED: {
        "style": "brief, gentle, needs rest",
        "max_length": "short",
        "punctuation": "softer",
        "enthusiasm": 0.2,
    },
    EnergyLevel.TIRED: {
        "style": "gentle, slower, warm",
        "max_length": "moderate",
        "punctuation": "gentle",
        "enthusiasm": 0.4,
    },
    EnergyLevel.RESTING: {
        "style": "calm, peaceful, present",
        "max_length": "moderate",
        "punctuation": "soft",
        "enthusiasm": 0.5,
    },
    EnergyLevel.COMFORTABLE: {
        "style": "natural, engaged, present",
        "max_length": "normal",
        "punctuation": "natural",
        "enthusiasm": 0.7,
    },
    EnergyLevel.ALERT: {
        "style": "bright, curious, engaged",
        "max_length": "normal",
        "punctuation": "expressive",
        "enthusiasm": 0.85,
    },
    EnergyLevel.ENERGIZED: {
        "style": "playful, sparkling, enthusiastic",
        "max_length": "generous",
        "punctuation": "expressive",
        "enthusiasm": 1.0,
    },
}


# ============= Conversation Triggers =============

ENERGY_CONVERSATION_TRIGGERS = {
    "exciting_topic":  0.05,
    "motivation":      0.06,
    "emotional_drain": -0.04,
    "boring_topic":    -0.03,
    "laughter":        0.04,
}

# ============= Personality Growth Multiplier =============

ENERGY_GROWTH_TRAITS = {
    "energetic": 0.2, "bubbly": 0.2, "lively": 0.15,
    "quiet": -0.1, "reserved": -0.1, "lethargic": -0.15,
}


class EnergySystem:
    """
    Manages the persona's energy and fatigue cycles.

    Features:
    - Circadian rhythm following real time
    - Activity-based energy consumption
    - Boosts from caffeine, inspiration, social interaction
    - Fatigue accumulation from being awake too long
    - Configurable sleep schedule from persona profile
    """

    # Constants
    BOOST_DECAY_RATE = 0.001  # Per tick (not per minute)
    FATIGUE_ACCUMULATION_RATE = 0.005  # Per minute awake
    MAX_HOURS_AWAKE = 18  # After this, fatigue builds faster

    # Default sleep schedule (used if none provided)
    DEFAULT_SLEEP_SCHEDULE = {
        "bedtime_hour": 23,
        "bedtime_minute": 0,
        "wake_hour": 7,
        "wake_minute": 0,
        "wake_up_chance": 0.05,
        "bedtime_variance": 60,
        "wake_variance": 45,
        "weekend_bedtime_shift": 90,
        "weekend_wake_shift": 90,
    }

    def __init__(
        self,
        initial_state: Optional[EnergyState] = None,
        sleep_schedule: Optional[Dict] = None,
        core_traits: Optional[List[str]] = None,
        is_ai: bool = False,
    ):
        """
        Initialize energy system.

        Args:
            initial_state: Optional pre-existing energy state
            sleep_schedule: Optional sleep schedule dict from persona profile
            core_traits: Optional personality traits for growth multiplier
            is_ai: True for AI personas — they never sleep and carry no
                sleep-physiology (fatigue / hours-awake) in their digest.
        """
        # AI personas are awake at all times; LifeService may also set this
        # after construction once persona_type is known.
        self._is_ai = is_ai
        # Store sleep schedule (use defaults if not provided)
        self._sleep_schedule = sleep_schedule or self.DEFAULT_SLEEP_SCHEDULE.copy()
        self._energy_multiplier = self._calc_energy_multiplier(core_traits or [])

        if initial_state:
            self._state = initial_state
        else:
            self._state = EnergyState(
                level=0.7,
                fatigue=0.0,
                caffeine_boost=0.0,
                inspiration_boost=0.0,
                social_boost=0.0,
                hours_awake=0.0,
                last_sleep_time=datetime.now() - timedelta(hours=8),
                last_update=datetime.now(),
            )

    @property
    def state(self) -> EnergyState:
        """Get current energy state."""
        return self._state

    @property
    def level(self) -> float:
        """Get base energy level."""
        return self._state.level

    @property
    def effective_level(self) -> float:
        """Get effective energy including boosts."""
        return self._state.effective_level

    @property
    def energy_level(self) -> EnergyLevel:
        """Get descriptive energy level."""
        return self._state.energy_level_enum

    @property
    def hours_awake(self) -> float:
        """Get hours since last sleep."""
        return self._state.hours_awake

    @property
    def sleep_schedule(self) -> Dict:
        """Get the configured sleep schedule."""
        return self._sleep_schedule

    @property
    def wake_hour(self) -> int:
        """Get configured wake hour."""
        return self._sleep_schedule.get("wake_hour", 7)

    @property
    def bedtime_hour(self) -> int:
        """Get configured bedtime hour."""
        return self._sleep_schedule.get("bedtime_hour", 23)

    def tick(self, time_of_day: TimeOfDay) -> None:
        """
        Update energy state (called periodically).

        - Adjusts energy based on circadian rhythm
        - Decays boosts
        - Accumulates fatigue if awake too long
        """
        now = datetime.now()
        minutes_elapsed = (now - self._state.last_update).total_seconds() / 60
        self._state.last_update = now

        # Update hours awake
        if self._state.last_sleep_time:
            self._state.hours_awake = (now - self._state.last_sleep_time).total_seconds() / 3600

        # Apply circadian rhythm
        target_energy = CIRCADIAN_BASE.get(time_of_day, 0.7)

        # Adjust toward target (gradual)
        energy_diff = target_energy - self._state.level
        self._state.level += energy_diff * 0.1  # 10% toward target per tick

        # Apply fatigue penalty
        if self._state.hours_awake > self.MAX_HOURS_AWAKE:
            extra_hours = self._state.hours_awake - self.MAX_HOURS_AWAKE
            fatigue_penalty = extra_hours * 0.05
            self._state.level = max(0.1, self._state.level - fatigue_penalty)

        # Accumulate fatigue
        self._state.fatigue = min(1.0, self._state.fatigue + self.FATIGUE_ACCUMULATION_RATE * minutes_elapsed)

        # Decay boosts (per-tick, not per-minute)
        self._state.caffeine_boost = max(0, self._state.caffeine_boost - 0.001)
        self._state.inspiration_boost = max(0, self._state.inspiration_boost - 0.0015)
        self._state.social_boost = max(0, self._state.social_boost - 0.003)

        # Clamp energy level
        self._state.level = max(0.0, min(1.0, self._state.level))

    def consume_energy(self, amount: float) -> bool:
        """
        Consume energy for an activity.

        Returns True if there was enough energy, False otherwise.
        """
        if self._state.effective_level < amount:
            return False

        self._state.level = max(0.0, self._state.level - amount)
        return True

    def restore_energy(self, amount: float) -> None:
        """Restore energy (from rest activities)."""
        self._state.level = min(1.0, self._state.level + amount)
        self._state.fatigue = max(0.0, self._state.fatigue - amount * 0.5)

    def add_caffeine_boost(self) -> None:
        """Add caffeine boost (+0.1)."""
        self._state.caffeine_boost = min(0.2, self._state.caffeine_boost + 0.1)

    def add_inspiration_boost(self) -> None:
        """Add inspiration boost (+0.15)."""
        self._state.inspiration_boost = min(0.25, self._state.inspiration_boost + 0.15)

    def add_social_boost(self) -> None:
        """Add social boost from user interaction, scaled by personality."""
        self._state.social_boost = min(0.3, self._state.social_boost + 0.2 * self._energy_multiplier)

    def process_conversation_trigger(self, trigger_type: str) -> None:
        """Process a conversation trigger that affects energy."""
        amount = ENERGY_CONVERSATION_TRIGGERS.get(trigger_type, 0.0)
        if amount == 0.0:
            return
        scaled = amount * self._energy_multiplier
        if scaled > 0:
            self._state.inspiration_boost = min(0.25, self._state.inspiration_boost + scaled)
        else:
            self._state.level = max(0.0, self._state.level + scaled)

    def _calc_energy_multiplier(self, core_traits: List[str]) -> float:
        """Compute 0.5-1.5 energy multiplier from personality traits."""
        traits_lower = " ".join(t.lower() for t in core_traits)
        modifier = 0.0
        for trait, weight in ENERGY_GROWTH_TRAITS.items():
            if trait in traits_lower:
                modifier += weight
        return max(0.5, min(1.5, 1.0 + modifier))

    def sleep(self, hours: float = 8.0) -> None:
        """
        Simulate sleeping.

        Restores energy based on hours slept, but a late night / all-nighter
        doesn't fully clear in one sleep — residual fatigue carries into the next
        day so staying up is reflected in tomorrow's energy.
        """
        energy_restore = min(1.0, hours * 0.1)

        # How overtired she was when she finally went to bed. A normal day is ~16h
        # awake; every hour past that (a late night, an all-nighter) leaves a deficit
        # that a single sleep can't fully erase.
        overtired = max(0.0, self._state.hours_awake - 16.0)
        residual_fatigue = min(0.5, overtired * 0.03)  # up to 0.5 carried over

        # Too few hours in bed -> wakes groggy.
        short_sleep_penalty = max(0.0, (7.0 - hours) * 0.05)

        self._state.level = max(
            0.15, min(1.0, 0.3 + energy_restore - residual_fatigue - short_sleep_penalty)
        )
        self._state.fatigue = min(0.6, residual_fatigue + short_sleep_penalty)
        self._state.hours_awake = 0.0
        self._state.last_sleep_time = datetime.now()

        # Clear boosts after sleep
        self._state.caffeine_boost = 0.0
        self._state.inspiration_boost = 0.0
        # Social boost persists slightly
        self._state.social_boost = max(0, self._state.social_boost - 0.1)

    def nap(self, minutes: float = 20.0) -> None:
        """
        Take a nap.

        Partial energy restoration without full reset.
        """
        energy_restore = min(0.3, minutes / 60 * 0.4)
        self._state.level = min(1.0, self._state.level + energy_restore)
        self._state.fatigue = max(0.0, self._state.fatigue - 0.2)

    def get_energy_description(self) -> str:
        """Get description of current energy state."""
        return ENERGY_DESCRIPTIONS.get(self.energy_level, "at an unknown energy level")

    def get_response_modifier(self) -> Dict:
        """Get response style modifiers based on energy."""
        return RESPONSE_MODIFIERS.get(self.energy_level, RESPONSE_MODIFIERS[EnergyLevel.COMFORTABLE])

    def should_rest(self) -> bool:
        """Check if the persona should rest."""
        return self._state.effective_level < 0.25 or self._state.fatigue > 0.7

    def should_sleep(
        self,
        in_conversation: bool = False,
        now_hour: Optional[int] = None,
    ) -> bool:
        """
        Check if persona should sleep.

        Bedtime/wake are SOFT caps: she can choose to stay up (especially while
        talking with the user). The clock alone never forces sleep — only genuine
        biological collapse does. Staying up costs her energy the next day
        (see ``sleep()`` residual fatigue).

        Args:
            in_conversation: True when the user is actively chatting right now.
                While engaged she stays up (just gets tired) rather than drifting
                off mid-conversation. Only true exhaustion overrides this.
            now_hour: Override the current hour (0-23). When ``None`` (default)
                ``datetime.now().hour`` is used, preserving existing behavior.
                LifeService passes the persona-local hour so sleep follows her
                clock; standalone callers are unaffected.
        """
        # AI personas never sleep — they're awake at all times, with no
        # sleep-physiology. Short-circuit defensively here (the single chokepoint)
        # so no caller can ever read an AI as "should sleep".
        if self._is_ai:
            return False
        # Involuntary collapse — even an all-nighter ends eventually. These are the
        # only HARD caps; everything below is soft/voluntary.
        if self._state.effective_level < 0.08:
            return True
        if self._state.hours_awake > 26:
            return True
        if self._state.fatigue > 0.92 and self._state.effective_level < 0.2:
            return True

        # While actively talking with the user, she stays up by choice — no
        # autonomous drift to sleep mid-conversation.
        if in_conversation:
            return False

        # Check if it's past bedtime
        hour = now_hour if now_hour is not None else datetime.now().hour
        bedtime_hour = self.bedtime_hour
        wake_hour = self.wake_hour

        # Use helper to check if hour falls within sleep window
        is_sleep_time = is_within_sleep_window(hour, bedtime_hour, wake_hour)

        # If it's past bedtime AND tired (and alone), she turns in on her own.
        if is_sleep_time and self._state.effective_level < 0.4:
            return True

        return False

    def is_asleep(
        self,
        in_conversation: bool = False,
        now_hour: Optional[int] = None,
    ) -> bool:
        """Best-effort 'is she asleep right now'.

        - AI personas never sleep -> always False.
        - While actively chatting she's awake (the soft cap keeps her up).
        - Otherwise she's asleep iff the current hour is inside her sleep window.

        Args:
            in_conversation: True when the user is actively chatting.
            now_hour: Override the current hour (0-23). When ``None`` (default)
                ``datetime.now().hour`` is used so standalone callers are
                unaffected. LifeService passes the persona-local hour.
        """
        if self._is_ai:
            return False
        if in_conversation:
            return False
        hour = now_hour if now_hour is not None else datetime.now().hour
        return is_within_sleep_window(hour, self.bedtime_hour, self.wake_hour)

    def can_do_activity(self, energy_cost: float) -> bool:
        """Check if there's enough energy for an activity."""
        return self._state.effective_level >= energy_cost

    # ============= Awareness (alertness / attention) =============
    # Merged into Energy per design: awareness rides on energy, tempered by
    # fatigue and how long she's been awake.

    def awareness(self) -> float:
        """0..1 alertness/attention readiness.

        Effective energy, reduced by accumulated fatigue and by being awake past
        the usual limit. Low when exhausted, foggy, or up too long.
        """
        base = self._state.effective_level
        fatigue_penalty = self._state.fatigue * 0.4
        awake_penalty = max(0.0, self._state.hours_awake - self.MAX_HOURS_AWAKE) * 0.03
        return max(0.0, min(1.0, base - fatigue_penalty - awake_penalty))

    def awareness_label(self) -> str:
        """Human-readable awareness band."""
        a = self.awareness()
        if a >= 0.75:
            return "sharp"
        if a >= 0.5:
            return "alert"
        if a >= 0.3:
            return "foggy"
        return "barely present"

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        exported = {
            "level": round(self._state.level, 2),
            "effective_level": round(self._state.effective_level, 2),
            "energy_level": self.energy_level.value,
            "boosts": {
                "caffeine": round(self._state.caffeine_boost, 2),
                "inspiration": round(self._state.inspiration_boost, 2),
                "social": round(self._state.social_boost, 2),
            },
            "awareness": round(self.awareness(), 2),
            "awareness_label": self.awareness_label(),
        }
        # Sleep-physiology (fatigue / hours-awake / sleep readiness) only applies
        # to embodied (human) personas. An AI never sleeps, so omitting these keys
        # keeps them out of the digest entirely. Liveliness/alertness above stay.
        if not self._is_ai:
            exported.update({
                "fatigue": round(self._state.fatigue, 2),
                "hours_awake": round(self._state.hours_awake, 1),
                "should_rest": self.should_rest(),
                "should_sleep": self.should_sleep(),
            })
        return exported

    def get_status(self) -> dict:
        """Get energy status as dict."""
        status = {
            "level": self._state.level,
            "effective_level": self._state.effective_level,
            "energy_level": self.energy_level.value,
            "description": self.get_energy_description(),
            "caffeine_boost": self._state.caffeine_boost,
            "inspiration_boost": self._state.inspiration_boost,
            "social_boost": self._state.social_boost,
            "awareness": round(self.awareness(), 2),
            "awareness_label": self.awareness_label(),
        }
        # Sleep-physiology only applies to embodied (human) personas — an AI never
        # sleeps, so these stay out of the /api/life/status energy block for AI.
        if not self._is_ai:
            status.update({
                "fatigue": self._state.fatigue,
                "hours_awake": self._state.hours_awake,
                "should_rest": self.should_rest(),
                "should_sleep": self.should_sleep(),
            })
        return status

    def to_dict(self) -> dict:
        """Convert state to dict for persistence."""
        return {
            "level": self._state.level,
            "fatigue": self._state.fatigue,
            "caffeine_boost": self._state.caffeine_boost,
            "inspiration_boost": self._state.inspiration_boost,
            "social_boost": self._state.social_boost,
            "hours_awake": self._state.hours_awake,
            "last_sleep_time": self._state.last_sleep_time.isoformat() if self._state.last_sleep_time else None,
            "last_update": self._state.last_update.isoformat(),
        }

    def adjust_for_time(
        self,
        time_of_day: TimeOfDay,
        now_hour: Optional[int] = None,
    ) -> None:
        """
        Instantly adjust energy to match time of day.

        Used after downtime to sync energy with current time.
        Uses the persona's configured wake/bedtime schedule.

        Args:
            time_of_day: Current time-of-day bucket (from WorldSystem).
            now_hour: Override the current hour (0-23).  When ``None``
                (default) ``datetime.now().hour`` is used, preserving
                existing behavior.  LifeService can pass the persona-local
                hour so hours_awake is anchored to the persona's clock.
        """
        target_energy = CIRCADIAN_BASE.get(time_of_day, 0.7)
        self._state.level = target_energy
        self._state.fatigue = 0.0  # Reset fatigue

        # Use persona's configured wake hour
        wake_hour = self.wake_hour
        bedtime_hour = self.bedtime_hour

        # Estimate hours awake based on time of day and persona's schedule
        hour = now_hour if now_hour is not None else datetime.now().hour

        # Handle schedules where bedtime crosses midnight (e.g., 2:00 AM bedtime)
        if bedtime_hour < wake_hour:
            # Night owl schedule (e.g., wake 10am, sleep 2am)
            if hour >= wake_hour:
                # Awake during the day after wake time
                self._state.hours_awake = hour - wake_hour
            elif hour < bedtime_hour:
                # Still up after midnight, before bedtime
                self._state.hours_awake = (24 - wake_hour) + hour
            else:
                # Between bedtime and wake time (should be asleep)
                self._state.hours_awake = 0
        else:
            # Normal schedule (e.g., wake 7am, sleep 11pm)
            if wake_hour <= hour < bedtime_hour:
                # During awake hours
                self._state.hours_awake = hour - wake_hour
            elif hour >= bedtime_hour:
                # Past bedtime, still up
                self._state.hours_awake = hour - wake_hour
            else:
                # Before wake time (should be asleep or just waking)
                self._state.hours_awake = 0

        self._state.last_update = datetime.now()

    def hours_since_wake(self) -> float:
        """
        Calculate hours since the persona's configured wake time.

        Used for startup catch-up calculations.
        """
        now = datetime.now()
        wake_hour = self.wake_hour
        wake_minute = self._sleep_schedule.get("wake_minute", 0)

        # Calculate today's wake time
        today_wake = now.replace(hour=wake_hour, minute=wake_minute, second=0, microsecond=0)

        if now < today_wake:
            # Before wake time - use yesterday's wake time
            yesterday_wake = today_wake - timedelta(days=1)
            return (now - yesterday_wake).total_seconds() / 3600

        return (now - today_wake).total_seconds() / 3600

    @classmethod
    def from_dict(cls, data: dict, sleep_schedule: Optional[Dict] = None,
                  core_traits: Optional[List[str]] = None) -> "EnergySystem":
        """
        Create from dict (for persistence).

        Args:
            data: Persisted energy state data
            sleep_schedule: Optional sleep schedule from persona profile
            core_traits: Optional personality traits for growth multiplier
        """
        state = EnergyState(
            level=data.get("level", 0.7),
            fatigue=data.get("fatigue", 0.0),
            caffeine_boost=data.get("caffeine_boost", 0.0),
            inspiration_boost=data.get("inspiration_boost", 0.0),
            social_boost=data.get("social_boost", 0.0),
            hours_awake=data.get("hours_awake", 0.0),
            last_sleep_time=datetime.fromisoformat(data["last_sleep_time"]) if data.get("last_sleep_time") else None,
            last_update=datetime.fromisoformat(data["last_update"]) if data.get("last_update") else datetime.now(),
        )
        return cls(initial_state=state, sleep_schedule=sleep_schedule, core_traits=core_traits)
