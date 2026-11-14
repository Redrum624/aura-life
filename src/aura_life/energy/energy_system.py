"""
Energy System

Manages the persona's energy levels, sleep, fatigue, circadian rhythms, and
boosts. Sleep is a state with a duration: see :meth:`EnergySystem.update_sleep`.
"""

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from ..models import EnergyState, EnergyLevel, TimeOfDay
from ..personas.parameters import PersonaParameters


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


@dataclass(frozen=True)
class SleepNight:
    """One night's sleep window, in the persona's local wall time (naive).

    ``night`` is the date of the evening the night belongs to -- a 03:00
    bedtime on a Saturday is Friday's night. ``bedtime`` and ``wake`` are that
    night's times with the schedule's variance and weekend shift applied, and
    ``early_wake`` says ``wake_up_chance`` drew an early morning for it.
    """

    night: date
    bedtime: datetime
    wake: datetime
    early_wake: bool = False


# Energy descriptions
ENERGY_DESCRIPTIONS: Dict[EnergyLevel, str] = {
    EnergyLevel.EXHAUSTED: "dead tired, can barely keep your eyes open",
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
# Read from her trait text by aura_life.personas.parameters
# (ENERGY_GROWTH_TRAITS, PersonaParameters.energy_multiplier).


class EnergySystem:
    """
    Manages the persona's energy and fatigue cycles.

    Features:
    - Circadian rhythm following real time
    - Activity-based energy consumption
    - Boosts from caffeine, inspiration, social interaction
    - Sleep as a state with a duration, from sleep pressure and the persona's
      own nightly window (:meth:`update_sleep`)
    - Fatigue that is that sleep pressure, measured in hours awake
    - Configurable sleep schedule from persona profile
    """

    # Constants
    BOOST_DECAY_RATE = 0.001  # Per tick (not per minute)
    MAX_HOURS_AWAKE = 18  # After this, fatigue builds faster

    # ============= Sleep model: every constant, and where it comes from =============
    # A two-process model. Process S, the homeostatic sleep pressure, rises
    # while she is awake and falls while she sleeps; ``state.fatigue`` *is* that
    # pressure, 0..1. Process C, the circadian gate, is her own nightly window:
    # bedtime and wake time from her sleep schedule, moved on weekend nights by
    # its shifts (her *effective* window) and each night by its variances,
    # drawn once per night from the rng the caller passes (``update_sleep``).
    # She falls asleep inside that window once the pressure allows, and sleeps
    # until the window's wake time.
    #
    # An AI persona runs on the same scale but never sleeps: it rests through
    # its effective window instead -- awake and reachable, while its pressure
    # falls and its energy comes back at the sleep rates below -- and its day
    # restarts when the window ends.
    #
    # Pressure rises 1/MAX_HOURS_AWAKE per hour awake: it reaches its ceiling
    # after the 18 hours this class already treats as awake too long (the
    # MAX_HOURS_AWAKE energy penalty in ``tick``); a usual 16-hour day builds
    # 16/18. It falls at ``sleep_pressure_fall_per_hour``, per persona, so her
    # usual night clears what her usual day built.
    SLEEP_PRESSURE_RISE_PER_HOUR = 1.0 / MAX_HOURS_AWAKE
    # The pressure she needs, inside her window, to fall asleep: about nine
    # hours awake. A chosen value, not a derived one: far below the 16/18 a
    # usual day builds, so it only holds her awake after a late morning or a
    # long nap.
    SLEEP_PRESSURE_TO_FALL_ASLEEP = 0.5
    # Energy regained per hour asleep: the ``hours * 0.1`` that ``sleep()``
    # applies at once for a whole night, spread across the hours she sleeps.
    SLEEP_ENERGY_RECOVERY_PER_HOUR = 0.1
    # A nap needs her at least this tired: the top of the EnergyLevel.TIRED
    # band (``EnergyState.energy_level_enum``).
    NAP_ENERGY_BELOW = 0.3
    # Weekend shifts apply to Friday and Saturday nights, the nights before the
    # Saturday and Sunday mornings -- the days aura's Android ``SleepSchedule``
    # (``getTodayBedtime`` / ``getTodayWakeTime``) shifts in full.
    WEEKEND_NIGHTS = (4, 5)  # date.weekday(): Friday, Saturday
    # Each night's bedtime and wake time move by a triangular draw on
    # [-variance, +variance] minutes, peaked at 0 -- chosen: bounded by the
    # profile's "+/- N minutes" as that ``SleepSchedule``'s uniform draw is,
    # but with most nights near the usual time, where a uniform draw lands a
    # late bedtime or an early wake as often as an on-time one.
    # ``wake_up_chance`` is the chance per night of an early morning, up to one
    # more ``wake_variance`` before the drawn wake time -- chosen: the profile
    # gives only the chance, and its one measure of how far her wake time
    # moves is ``wake_variance``.

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
        now: Optional[Callable[[], datetime]] = None,
        params: Optional[PersonaParameters] = None,
    ):
        """
        Initialize energy system.

        Args:
            initial_state: Optional pre-existing energy state
            sleep_schedule: Optional sleep schedule dict from persona profile
            core_traits: Optional personality traits for growth multiplier,
                read when no ``params`` are given
            params: Her traits' engine parameters
                (:class:`~aura_life.personas.parameters.PersonaParameters`);
                ``energy_multiplier`` scales the social boost and the
                conversation triggers
            is_ai: True for AI personas — they never sleep (they rest through
                their night instead) and carry no sleep-physiology (fatigue /
                hours-awake) in their digest.
            now: The clock this system measures elapsed time against — a
                zero-argument callable returning a naive :class:`datetime`.
                Defaults to ``datetime.now``, so every existing caller keeps
                exactly the behaviour it had. ``LifeService`` passes its
                world's :meth:`~aura_life.world.WorldEnvironment.now`, so a
                consumer running the world on a simulated clock gets a
                simulated circadian rhythm instead of one keyed to how long
                the host process has been alive. See :attr:`clock`.
        """
        # AI personas are awake at all times; LifeService may also set this
        # after construction once persona_type is known.
        self._is_ai = is_ai
        # Store sleep schedule (use defaults if not provided)
        self._sleep_schedule = sleep_schedule or self.DEFAULT_SLEEP_SCHEDULE.copy()
        if params is None:
            params = PersonaParameters.from_core_traits(core_traits)
        self._energy_multiplier = params.energy_multiplier
        # Every wall-clock read below goes through this. Installed before the
        # initial state is built, because building it reads the clock twice.
        self._now: Callable[[], datetime] = now or datetime.now

        if initial_state:
            self._state = initial_state
        else:
            # A fresh system has been up eight hours, as it always was, and its
            # fatigue is the sleep pressure those hours built. A persona that
            # starts now on her own schedule gets start_on_schedule() instead.
            seeded_hours_awake = 8.0
            self._state = EnergyState(
                level=0.7,
                fatigue=seeded_hours_awake * self.SLEEP_PRESSURE_RISE_PER_HOUR,
                caffeine_boost=0.0,
                inspiration_boost=0.0,
                social_boost=0.0,
                hours_awake=0.0,
                last_sleep_time=self._now() - timedelta(hours=seeded_hours_awake),
                last_update=self._now(),
            )

        # The sleep state. Times here are the persona's local wall time,
        # naive -- the ``local_now`` given to ``update_sleep``. ``_resting`` is
        # an AI persona's night: never asleep, recovering as if it were.
        self._asleep: bool = False
        self._resting: bool = False
        self._wake_at: Optional[datetime] = None  # when this sleep ends
        self._sleep_night: Optional[date] = None  # the night this sleep belongs to
        self._night: Optional[SleepNight] = None  # the latest night drawn
        self._night_done: bool = False  # she woke from ``_night`` already
        self._napped: bool = False  # she has napped since she last woke

    @property
    def clock(self) -> Callable[[], datetime]:
        """The callable this system reads the time from.

        ``EnergySystem().clock == datetime.now`` for a default-constructed
        system. Compare with ``==``, not ``is``: ``datetime.now`` is a bound
        builtin and each attribute access on the class produces a fresh object,
        so ``datetime.now is datetime.now`` is already ``False``.

        Exposed so a consumer can tell *which* clock is installed rather than
        infer it from behaviour — the same reason
        :func:`aura_life.hooks.provider_for` exists for the hook registry.
        """
        return self._now

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

    @property
    def sleep_pressure(self) -> float:
        """A human persona's homeostatic sleep pressure, 0..1 -- the same
        number as ``state.fatigue``. Rises by the hour awake, falls by the hour
        asleep. (An AI's fatigue keeps its old per-minute meaning.)"""
        return self._state.fatigue

    @property
    def night(self) -> Optional[SleepNight]:
        """The latest night :meth:`update_sleep` drew, or ``None`` before the first."""
        return self._night

    @property
    def usual_awake_hours(self) -> float:
        """Hours from her wake time to her bedtime on her schedule: her usual day."""
        return self._usual_spans()[0]

    @property
    def sleep_pressure_fall_per_hour(self) -> float:
        """How fast sleep clears the pressure: her usual night clears exactly
        what her usual day builds at ``SLEEP_PRESSURE_RISE_PER_HOUR``."""
        awake, asleep = self._usual_spans()
        return self.SLEEP_PRESSURE_RISE_PER_HOUR * awake / asleep

    def tick(self, time_of_day: TimeOfDay) -> None:
        """
        Update energy state (called periodically).

        Awake: energy follows the circadian rhythm and sleep pressure (fatigue)
        builds by the hour. Asleep (an AI: resting through its night): no
        circadian pull -- the pressure falls and energy comes back, both by the
        hour. Boosts decay either way.
        """
        now = self._now()
        seconds_elapsed = (now - self._state.last_update).total_seconds()
        self._state.last_update = now
        hours = max(0.0, seconds_elapsed / 3600)

        if self._asleep or self._resting:
            self._state.hours_awake = 0.0
            self._state.fatigue = max(0.0, self._state.fatigue - hours * self.sleep_pressure_fall_per_hour)
            self._state.level += hours * self.SLEEP_ENERGY_RECOVERY_PER_HOUR
        else:
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

            self._state.fatigue = min(1.0, self._state.fatigue + hours * self.SLEEP_PRESSURE_RISE_PER_HOUR)

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
        """Restore energy (from rest activities).

        A rest activity does not clear sleep pressure -- only sleep does (see
        :meth:`nap`), or an AI's night of rest -- so an evening of it cannot
        keep her up past her bedtime.
        """
        self._state.level = min(1.0, self._state.level + amount)

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

    def sleep(self, hours: float = 8.0) -> None:
        """
        Account for a whole sleep of ``hours`` that ends now.

        Restores energy based on hours slept, but a late night / all-nighter
        doesn't fully clear in one sleep — residual fatigue carries into the next
        day so staying up is reflected in tomorrow's energy. She is awake
        afterwards, her day starting now.

        The autonomous life no longer calls this: sleep there is a state that
        lasts the night (:meth:`update_sleep`). It stays for a host that wants
        to book a night in one call.
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
        self._state.last_sleep_time = self._now()

        self._clear_boosts_after_sleep()
        self._asleep = False
        self._resting = False
        self._wake_at = None
        self._sleep_night = None
        self._napped = False

    def _clear_boosts_after_sleep(self) -> None:
        # Clear boosts after sleep
        self._state.caffeine_boost = 0.0
        self._state.inspiration_boost = 0.0
        # Social boost persists slightly
        self._state.social_boost = max(0, self._state.social_boost - 0.1)

    def nap(self, minutes: float = 20.0) -> None:
        """
        Take a nap.

        Partial energy restoration without full reset. A nap is sleep: the
        sleep pressure falls for its length at the rate a night's does, and it
        counts as her one nap until she next wakes (:meth:`can_nap`).
        """
        energy_restore = min(0.3, minutes / 60 * 0.4)
        self._state.level = min(1.0, self._state.level + energy_restore)
        self._state.fatigue = max(0.0, self._state.fatigue - minutes / 60 * self.sleep_pressure_fall_per_hour)
        self._napped = True

    def can_nap(self, time_of_day: Optional[TimeOfDay] = None) -> bool:
        """Whether a nap is open to her now: awake, tired (effective energy
        under ``NAP_ENERGY_BELOW``), not yet napped since she last woke, and not
        in the night part of her day (``time_of_day`` NIGHT or LATE_NIGHT),
        where she waits for bed instead. An AI never naps."""
        if self._is_ai or self._asleep or self._napped:
            return False
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            return False
        return self._state.effective_level < self.NAP_ENERGY_BELOW

    def get_energy_description(self) -> str:
        """Get description of current energy state."""
        return ENERGY_DESCRIPTIONS.get(self.energy_level, "at an unknown energy level")

    def get_response_modifier(self) -> Dict:
        """Get response style modifiers based on energy."""
        return RESPONSE_MODIFIERS.get(self.energy_level, RESPONSE_MODIFIERS[EnergyLevel.COMFORTABLE])

    def should_rest(self) -> bool:
        """Check if the persona should rest.

        Her energy is nearly gone, or she has been up longer than her usual day
        (``usual_awake_hours``) -- rest in hours awake, not a fatigue number that
        used to cross its line about two hours after she woke. The same rule
        for an AI, whose day restarts after each night of rest.
        """
        if self._state.effective_level < 0.25:
            return True
        return self._state.hours_awake >= self.usual_awake_hours

    def should_sleep(
        self,
        in_conversation: bool = False,
        now_hour: Optional[int] = None,
    ) -> bool:
        """
        Check if persona should sleep: she is asleep, or everything
        :meth:`update_sleep` needs to put her to sleep holds now.

        Bedtime/wake are SOFT caps: she can choose to stay up (especially while
        talking with the user). The clock alone never forces sleep — inside her
        window she still needs the sleep pressure, and only genuine biological
        collapse overrides a conversation. Staying up costs her the next day:
        the pressure she did not sleep off carries over.

        Args:
            in_conversation: True when the user is actively chatting right now.
                While engaged she stays up (just gets tired) rather than drifting
                off mid-conversation. Only true exhaustion overrides this.
            now_hour: Override the current hour (0-23) of the instant checked,
                which is otherwise this system's clock. LifeService's own sleep
                decisions go through :meth:`update_sleep` with the persona-local
                time instead.

        A query: it draws nothing. Before the night in question has been drawn
        it reads that night without variance.
        """
        # AI personas never sleep — they're awake at all times, with no
        # sleep-physiology. Short-circuit defensively here (the single chokepoint)
        # so no caller can ever read an AI as "should sleep".
        if self._is_ai:
            return False
        # Involuntary collapse — even an all-nighter ends eventually. These are the
        # only HARD caps (see _collapsing); everything below is soft/voluntary.
        if self._collapsing():
            return True

        # While actively talking with the user, she stays up by choice — no
        # autonomous drift to sleep mid-conversation.
        if in_conversation:
            return False
        if self._asleep:
            return True

        t = self._local(None)
        if now_hour is not None:
            t = t.replace(hour=now_hour)
        key = self._night_key(t)
        if self._night is not None and self._night.night == key:
            night, done = self._night, self._night_done
        else:
            bedtime, wake = self._effective_night(key)
            night, done = SleepNight(key, bedtime, wake), False
        return not done and self._may_fall_asleep(t, night)

    def is_asleep(
        self,
        in_conversation: bool = False,
        now_hour: Optional[int] = None,
    ) -> bool:
        """Is she asleep right now -- her sleep state, not the clock.

        - AI personas never sleep -> always False (a resting AI is awake).
        - While actively chatting she's awake (the soft cap keeps her up).
        - Otherwise True from the moment :meth:`update_sleep` puts her to sleep
          until it wakes her (or :meth:`start_on_schedule` /
          :meth:`adjust_for_time` start her asleep).

        Args:
            in_conversation: True when the user is actively chatting.
            now_hour: Unused; kept for callers that pass it. The answer used to
                be "is this hour inside her window", which had her asleep through
                ticks she spent awake.
        """
        if self._is_ai:
            return False
        if in_conversation:
            return False
        return self._asleep

    # ============= Sleep as a state =============

    def update_sleep(
        self,
        local_now: Optional[datetime] = None,
        *,
        in_conversation: bool = False,
        rng=None,
    ) -> Optional[str]:
        """Advance her sleep state to ``local_now``; return what changed.

        Returns ``"fell_asleep"``, ``"woke"`` or ``None``.

        - Asleep: she wakes at this sleep's wake time -- the night's drawn wake
          time, earlier on a night ``wake_up_chance`` picked. A message does not
          wake her; that is the host's call (``LifeService.force_wake``).
        - Awake: she falls asleep once she is inside tonight's window and her
          sleep pressure is at least ``SLEEP_PRESSURE_TO_FALL_ASLEEP`` -- unless
          she is in a conversation, or has already woken from tonight's sleep.
          Collapse (see :meth:`should_sleep`) puts her to sleep anywhere.

        Args:
            local_now: The persona's local wall time (``LifeService`` passes
                its ``_local_world_now()``); an aware value is read as its wall
                time. Defaults to this system's clock.
            in_conversation: True while the user is chatting with her.
            rng: The source each night is drawn from, once per night: three
                draws, four when an early morning is drawn. ``None`` uses module
                ``random``.

        AI personas never sleep: always ``None``, and nothing is drawn. An AI
        rests through its effective window instead (awake, recovering as if
        asleep) and its day restarts when the window ends.
        """
        t = self._local(local_now)
        if self._is_ai:
            self._update_rest(t)
            return None
        rng = rng if rng is not None else random

        if self._asleep:
            if self._wake_at is None:
                # Started asleep (start_on_schedule / adjust_for_time): she
                # wakes at the drawn wake time of the night she is sleeping.
                key = self._sleep_night if self._sleep_night is not None else self._night_key(t)
                self._wake_at = self._night_for(key, rng).wake
            if t < self._wake_at:
                return None
            self._wake()
            return "woke"

        night = self._night_for(self._night_key(t), rng)
        if self._collapsing():
            self._fall_asleep(t, night)
            return "fell_asleep"
        if in_conversation or self._night_done:
            return None
        if self._may_fall_asleep(t, night):
            self._fall_asleep(t, night)
            return "fell_asleep"
        return None

    def _update_rest(self, t: datetime) -> None:
        """An AI persona's night: resting while ``t`` is inside its effective
        window, its day starting over when the window ends."""
        inside = self._effective_night_at(t) is not None
        if inside and not self._resting:
            self._resting = True
            self._state.hours_awake = 0.0
        elif not inside and self._resting:
            self._resting = False
            self._state.hours_awake = 0.0
            self._state.last_sleep_time = self._now()

    def start_on_schedule(self, local_now: Optional[datetime] = None) -> None:
        """Start a brand-new persona on her own schedule at ``local_now``.

        Inside that night's effective window -- her bedtime and wake time, with
        the weekend shift on a Friday or Saturday night, no variance -- she is
        asleep (an AI: resting), with the pressure a sleeper has that far into
        the night and the energy she has got back since bedtime; outside it she
        is awake since that day's effective wake time, with the pressure those
        hours built. For a persona with no saved state: a loaded one keeps the
        state it saved.

        Args:
            local_now: The persona's local wall time, as for :meth:`update_sleep`.
                Defaults to this system's clock.
        """
        t = self._local(local_now)
        world_now = self._now()
        self._state.last_update = world_now
        self._asleep = self._resting = False
        self._wake_at = None
        self._sleep_night = None
        self._night = None
        self._night_done = False
        self._napped = False

        inside = self._effective_night_at(t)
        self._state.fatigue, hours = self.pressure_on_schedule(t)
        if inside is not None:
            key, bedtime, _ = inside
            slept = (t - bedtime).total_seconds() / 3600
            # Back from the level the circadian rhythm had her at by bedtime.
            self._state.level = min(
                1.0, CIRCADIAN_BASE[TimeOfDay.LATE_NIGHT] + slept * self.SLEEP_ENERGY_RECOVERY_PER_HOUR
            )
            self._state.hours_awake = 0.0
            if self._is_ai:
                self._resting = True
            else:
                self._asleep = True
                self._sleep_night = key  # the night's wake time is drawn on the next update_sleep
            return

        self._state.hours_awake = hours
        self._state.last_sleep_time = world_now - timedelta(hours=hours)

    def pressure_on_schedule(self, local_now: Optional[datetime] = None) -> Tuple[float, float]:
        """(sleep pressure, hours awake) her schedule gives at ``local_now``
        (her local wall time; this system's clock when omitted): inside that
        night's effective window, the pressure a sleeper has that far into the
        night and no hour awake; outside it, the pressure the hours since that
        day's effective wake time built, and those hours. What
        :meth:`start_on_schedule` starts a new persona with, and what the
        downtime catch-up hands her affect for the hours of a gap, where her
        own state is the evening the host went down (Task 41). A query that
        changes nothing."""
        t = self._local(local_now)
        inside = self._effective_night_at(t)
        if inside is not None:
            slept = (t - inside[1]).total_seconds() / 3600
            day_pressure = min(1.0, self.usual_awake_hours * self.SLEEP_PRESSURE_RISE_PER_HOUR)
            return max(0.0, day_pressure - slept * self.sleep_pressure_fall_per_hour), 0.0
        hours = (t - self._last_effective_wake(t)).total_seconds() / 3600
        return min(1.0, hours * self.SLEEP_PRESSURE_RISE_PER_HOUR), hours

    def in_sleep_window(self, local_now: Optional[datetime] = None) -> bool:
        """Is ``local_now`` (her local wall time, as for :meth:`update_sleep`;
        this system's clock when omitted) inside her sleep window: that
        night's effective window -- her schedule's bedtime to wake time, with
        the weekend shift -- or the night her sleep drew, variance and all?
        Asleep or not: a query that draws nothing."""
        t = self._local(local_now)
        if self._effective_night_at(t) is not None:
            return True
        night = self._night
        return night is not None and night.bedtime <= t < night.wake

    def _effective_night_at(self, t: datetime) -> Optional[Tuple[date, datetime, datetime]]:
        """(night, bedtime, wake) of the effective window ``t`` falls inside, or None."""
        for back in (0, 1, 2):
            key = t.date() - timedelta(days=back)
            bedtime, wake = self._effective_night(key)
            if bedtime <= t < wake:
                return key, bedtime, wake
        return None

    def last_wake(self, local_now: Optional[datetime] = None) -> datetime:
        """The latest effective wake time at or before ``local_now`` (her local
        wall time; this system's clock when omitted): when her current day
        began, so a night owl up past midnight is still in the day before.
        A query that draws nothing."""
        return self._last_effective_wake(self._local(local_now))

    def _last_effective_wake(self, t: datetime) -> datetime:
        """The latest effective wake time at or before ``t``. Night ``key``
        wakes on ``key + 1``, a weekend shift can carry that past midnight
        (a 23:00 wake + 90 minutes is 00:30), so just past midnight the two
        nights before may not have woken her yet: the third night back's wake,
        at most a day plus the shift before ``t``, always has."""
        wakes = [self._effective_night(t.date() - timedelta(days=back))[1] for back in (0, 1, 2, 3)]
        return max(wake for wake in wakes if wake <= t)

    def _may_fall_asleep(self, t: datetime, night: SleepNight) -> bool:
        return (
            night.bedtime <= t < night.wake
            and self._state.fatigue >= self.SLEEP_PRESSURE_TO_FALL_ASLEEP
        )

    def _collapsing(self) -> bool:
        """Sleep she cannot hold off: up more than 26 hours, or her sleep
        pressure at the top with her energy all but gone. An energy crash with
        little pressure behind it (the old ``effective_level < 0.08`` cap) is
        exhaustion, not sleepiness: she rests (:meth:`should_rest`) instead of
        sleeping for hours in the middle of her day."""
        return (
            self._state.hours_awake > 26
            or (self._state.fatigue > 0.92 and self._state.effective_level < 0.2)
        )

    def _fall_asleep(self, t: datetime, night: SleepNight) -> None:
        self._asleep = True
        self._state.hours_awake = 0.0
        if night.bedtime <= t < night.wake:
            self._wake_at = night.wake
            self._sleep_night = night.night
            return
        # A collapse outside her window: she sleeps off the pressure she has --
        # and on to tonight's wake time if that would wake her inside tonight's
        # window, which makes it tonight's sleep.
        wake_at = t + timedelta(hours=self._state.fatigue / self.sleep_pressure_fall_per_hour)
        if night.bedtime <= wake_at < night.wake:
            wake_at = night.wake
        self._wake_at = wake_at
        self._sleep_night = night.night if t < night.wake and wake_at > night.bedtime else None

    def _wake(self) -> None:
        self._asleep = False
        self._wake_at = None
        if self._night is not None and self._sleep_night == self._night.night:
            self._night_done = True
        self._sleep_night = None
        self._napped = False
        self._state.hours_awake = 0.0
        self._state.last_sleep_time = self._now()
        self._clear_boosts_after_sleep()

    def _night_for(self, key: date, rng) -> SleepNight:
        """The night ``key``, drawing it the first time it is asked for."""
        if self._night is None or self._night.night != key:
            self._night = self._draw_night(key, rng)
            self._night_done = False
        return self._night

    def _draw_night(self, key: date, rng) -> SleepNight:
        bedtime, wake = self._effective_night(key)
        bedtime_variance = abs(float(self._schedule_value("bedtime_variance")))
        wake_variance = abs(float(self._schedule_value("wake_variance")))
        bedtime += timedelta(minutes=rng.triangular(-bedtime_variance, bedtime_variance, 0.0))
        wake += timedelta(minutes=rng.triangular(-wake_variance, wake_variance, 0.0))
        early = rng.random() < float(self._schedule_value("wake_up_chance"))
        if early:
            wake -= timedelta(minutes=rng.uniform(0.0, wake_variance))
        if wake <= bedtime:
            # Only variances as long as the night itself get here.
            wake = bedtime + timedelta(hours=self._usual_spans()[1])
        return SleepNight(key, bedtime, wake, early)

    def _effective_night(self, key: date) -> Tuple[datetime, datetime]:
        """Night ``key``'s effective window: her schedule's bedtime and wake
        time, with the weekend shifts on a weekend night, and no variance."""
        midnight = datetime.combine(key + timedelta(days=1), datetime.min.time())
        wake = midnight + timedelta(minutes=self._minute_of_day("wake"))
        bedtime = wake - timedelta(hours=self._usual_spans()[1])
        if key.weekday() in self.WEEKEND_NIGHTS:
            bedtime += timedelta(minutes=float(self._schedule_value("weekend_bedtime_shift")))
            wake += timedelta(minutes=float(self._schedule_value("weekend_wake_shift")))
        return bedtime, wake

    def _night_key(self, t: datetime) -> date:
        """The night ``t`` belongs to: the evening's date. It turns over once the
        latest wake time the schedule allows (weekend shift plus variance) has
        passed, so a late morning still belongs to the night before."""
        latest_wake = (
            self._minute_of_day("wake")
            + max(0.0, float(self._schedule_value("weekend_wake_shift")))
            + abs(float(self._schedule_value("wake_variance")))
        )
        return (t - timedelta(minutes=latest_wake)).date()

    def _usual_spans(self) -> Tuple[float, float]:
        """Hours (awake, asleep) of her usual day. A schedule whose bedtime is
        its wake time names no window; the default schedule's stands in."""
        asleep = (self._minute_of_day("wake") - self._minute_of_day("bedtime")) % (24 * 60)
        if asleep == 0:
            default = self.DEFAULT_SLEEP_SCHEDULE
            asleep = (
                (default["wake_hour"] - default["bedtime_hour"]) * 60
                + default["wake_minute"] - default["bedtime_minute"]
            ) % (24 * 60)
        return (24 * 60 - asleep) / 60, asleep / 60

    def _minute_of_day(self, which: str) -> int:
        return (
            int(self._schedule_value(f"{which}_hour")) * 60
            + int(self._schedule_value(f"{which}_minute"))
        ) % (24 * 60)

    def _schedule_value(self, key: str):
        """A schedule field, or the default schedule's when the profile gave none."""
        value = self._sleep_schedule.get(key)
        return self.DEFAULT_SLEEP_SCHEDULE[key] if value is None else value

    def _local(self, local_now: Optional[datetime]) -> datetime:
        t = local_now if local_now is not None else self._now()
        return t.replace(tzinfo=None) if t.tzinfo is not None else t

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
        """Convert state to dict for persistence.

        ``sleep_state`` carries the sleep state -- asleep (or, for an AI,
        resting) or not, until when, and the night drawn for her -- so a restart
        mid-night neither wakes her nor draws that night again.
        """
        return {
            "level": self._state.level,
            "fatigue": self._state.fatigue,
            "caffeine_boost": self._state.caffeine_boost,
            "inspiration_boost": self._state.inspiration_boost,
            "social_boost": self._state.social_boost,
            "hours_awake": self._state.hours_awake,
            "last_sleep_time": self._state.last_sleep_time.isoformat() if self._state.last_sleep_time else None,
            "last_update": self._state.last_update.isoformat(),
            "sleep_state": self._sleep_state_to_dict(),
        }

    def _sleep_state_to_dict(self) -> dict:
        night = self._night
        return {
            "asleep": self._asleep,
            "resting": self._resting,
            "wake_at": self._wake_at.isoformat() if self._wake_at else None,
            "sleep_night": self._sleep_night.isoformat() if self._sleep_night else None,
            "night": None if night is None else {
                "night": night.night.isoformat(),
                "bedtime": night.bedtime.isoformat(),
                "wake": night.wake.isoformat(),
                "early_wake": night.early_wake,
            },
            "night_done": self._night_done,
            "napped": self._napped,
        }

    def _restore_sleep_state(self, data) -> None:
        """Inverse of :meth:`_sleep_state_to_dict`. ``data`` may be the dict, its
        JSON text (the database column), or empty for a row written before the
        sleep state was persisted -- then she is simply awake."""
        if isinstance(data, str):
            data = json.loads(data) if data else None
        if not data:
            return
        self._asleep = bool(data.get("asleep", False))
        self._resting = bool(data.get("resting", False))
        self._wake_at = datetime.fromisoformat(data["wake_at"]) if data.get("wake_at") else None
        self._sleep_night = date.fromisoformat(data["sleep_night"]) if data.get("sleep_night") else None
        night = data.get("night")
        if night:
            self._night = SleepNight(
                night=date.fromisoformat(night["night"]),
                bedtime=datetime.fromisoformat(night["bedtime"]),
                wake=datetime.fromisoformat(night["wake"]),
                early_wake=bool(night.get("early_wake", False)),
            )
        self._night_done = bool(data.get("night_done", False))
        self._napped = bool(data.get("napped", False))

    def adjust_for_time(
        self,
        time_of_day: TimeOfDay,
        now_hour: Optional[int] = None,
    ) -> None:
        """
        Instantly adjust energy to match time of day.

        Used after downtime to sync energy with current time.
        Uses the persona's configured wake/bedtime schedule: inside her window
        she is set asleep (an AI: resting) since her usual bedtime, until her
        night's wake time; outside it, awake since her usual wake time, with
        the sleep pressure those hours built.

        Args:
            time_of_day: Current time-of-day bucket (from WorldSystem).
            now_hour: Override the current hour (0-23).  When ``None``
                (default) the system clock's hour is used, preserving
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
        hour = now_hour if now_hour is not None else self._now().hour

        if is_within_sleep_window(hour, bedtime_hour, wake_hour):
            t = self._local(None).replace(hour=hour)
            key = self._night_key(t)
            bedtime, _ = self._effective_night(key)
            slept = max(0.0, (t - bedtime).total_seconds() / 3600)
            day_pressure = min(1.0, self.usual_awake_hours * self.SLEEP_PRESSURE_RISE_PER_HOUR)
            self._state.fatigue = max(0.0, day_pressure - slept * self.sleep_pressure_fall_per_hour)
            self._state.hours_awake = 0.0
            self._wake_at = None  # the night's wake time is drawn on the next update_sleep
            if self._is_ai:
                self._resting = True
            else:
                self._asleep = True
                self._sleep_night = key
            self._state.last_update = self._now()
            return

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

        # Awake since her usual wake time: the pressure those hours built, and
        # a wake instant the next tick keeps counting from.
        self._state.fatigue = min(1.0, self._state.hours_awake * self.SLEEP_PRESSURE_RISE_PER_HOUR)
        self._state.last_sleep_time = self._now() - timedelta(hours=self._state.hours_awake)
        self._asleep = self._resting = False
        self._wake_at = None
        self._sleep_night = None

        self._state.last_update = self._now()

    def hours_since_wake(self) -> float:
        """
        Calculate hours since the persona's configured wake time.

        Used for startup catch-up calculations.
        """
        now = self._now()
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
                  core_traits: Optional[List[str]] = None,
                  now: Optional[Callable[[], datetime]] = None,
                  params: Optional[PersonaParameters] = None) -> "EnergySystem":
        """
        Create from dict (for persistence).

        Args:
            data: Persisted energy state data
            sleep_schedule: Optional sleep schedule from persona profile
            core_traits: Optional personality traits for growth multiplier
            params: Her traits' engine parameters, as in :meth:`__init__`
            now: Clock for the restored system, as in :meth:`__init__`. Also
                supplies the ``last_update`` fallback when the persisted row
                carries none, so a restore on a simulated clock does not stamp
                the host's wall time into the state it just rehydrated.
        """
        _now = now or datetime.now
        state = EnergyState(
            level=data.get("level", 0.7),
            fatigue=data.get("fatigue", 0.0),
            caffeine_boost=data.get("caffeine_boost", 0.0),
            inspiration_boost=data.get("inspiration_boost", 0.0),
            social_boost=data.get("social_boost", 0.0),
            hours_awake=data.get("hours_awake", 0.0),
            last_sleep_time=datetime.fromisoformat(data["last_sleep_time"]) if data.get("last_sleep_time") else None,
            last_update=datetime.fromisoformat(data["last_update"]) if data.get("last_update") else _now(),
        )
        restored = cls(initial_state=state, sleep_schedule=sleep_schedule, core_traits=core_traits, now=now,
                       params=params)
        restored._restore_sleep_state(data.get("sleep_state"))
        return restored
