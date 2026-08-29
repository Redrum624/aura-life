"""
Life Service

Main facade for a persona's autonomous life system.
Coordinates world, energy, activities, goals, and scheduling.
"""

import contextlib
import json
import logging
import random
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from .models import (
    ActivityLog,
    ActivityCategory,
    BasicNeedsState,
    CalendarEntry,
    COMMUTE_ENERGY_COST,
    DailyPlan,
    FinancialState,
    Goal,
    LifeEvent,
    LOCATION_TYPE_EFFECTS,
    LocationProfile,
    MediaState,
    NPC,
    PlaceLocationState,
    RoomState,
    ShareableExperience,
    ShortTermDesire,
    SkillProgress,
    TimeOfDay,
    TransitPhase,
    TransitState,
)
from .world import WorldEnvironment
from .energy import EnergySystem
from .activities import ActivityEngine
from .goals import GoalEngine
from .planner import DailyPlanner
from .planner.daily_planner import PHYSICAL_ACTIVITIES
from aura_life.conversation_session import ConversationSession
from aura_life.planner.daily_planner import is_important_activity
from .scheduler import LifeScheduler
from .context import LifeContextBuilder
from .intimacy import DesireSystem
from .social import SocialSystem
from .identity import IdentitySystem
from .affect import AffectSystem
from .body import BodySystem
from .cognitive import CognitiveSystem
from .shadow import ShadowSystem
from .sanity import SanitySystem, STATES as SANITY_STATES
from .drive import DriveSystem
from .behavior import BehaviorSystem
from .memory_time import MemoryTimeSystem
from .expression import ExpressionSystem
from .continuity import ContinuitySystem
from .persona_evolution import CharacterEvolution
from .chaos import ChaosEngine
from .life_events import LifeEventSystem
from .money import FinanceSystem
from .job import CareerSystem
from .habitation import HabitationSystem
from .sustenance import SustenanceSystem
from .skills import SkillsSystem
from .errands import ErrandsSystem
from .location import LocationSystem
from .transportation import TransportSystem

logger = logging.getLogger(__name__)


# How long a conversation-driven CURRENT activity overrides the scheduled one.
# Within this window after the last user message, what she told the user she's
# doing (via a [DOING:] tag) wins over the stale daily-planner slot in status
# exports, picture generation, and proactive moment-shares.
CONVERSATION_ACTIVITY_WINDOW_MINUTES = 45

# How long an explicit user-initiated wake (the app's "Wake up" button →
# force_wake()) keeps is_asleep() False past the last user message. Matches the
# 20-minute "in conversation" window used by on_user_message's wake detection:
# while the user keeps chatting the override keeps refreshing; once the chat
# lapses she can drift back to sleep naturally.
FORCED_WAKE_WINDOW_MINUTES = 20

# Cap on the in-memory shareable-experience queue. Reload already keeps only the
# newest 10 (SELECT ... LIMIT 10); this bounds runtime .append() growth to match,
# so a long-running server can't accumulate an unbounded queue between restarts.
SHAREABLE_QUEUE_MAX = 10

# ============= Retention bounds =============
# Everything below is written on a fixed tick cadence and read back with a hard
# LIMIT, so rows past the limit are never used again. Without a prune each table
# grows for the persona's whole lifetime. Pruning happens on the write path, in
# the connection already open, so no extra connection is taken.

#: activity_logs rows kept. _load_state reads only the newest 20; the rest is
#: write-only history, so this is generous headroom rather than a working set.
ACTIVITY_LOG_RETENTION = 500

#: Days a *shared* shareable_experiences row is kept. Unshared rows are queued
#: work and are never pruned by age.
SHAREABLE_RETENTION_DAYS = 90

#: Completed / abandoned goals written to life_goals per save. GoalEngine keeps
#: its own in-memory history cap; this bounds the table independently of it,
#: because _save_goals rewrites the table wholesale on every goal tick.
GOAL_HISTORY_PERSISTED_MAX = 20

#: Distinct finished book titles kept. _pick_new_book falls back to re-reading a
#: finished title once everything is read, so without dedupe the same title is
#: appended again on every re-read. Evicting the oldest simply lets a long-ago
#: title count as unread again.
BOOKS_FINISHED_MAX = 200

#: Locations registered from free text the user or the LLM produced
#: (source="user"). Profile / occupation / interest seeds are never evicted.
USER_LOCATION_MAX = 100

#: Days a non-recurring user_calendar row is kept past its event date. Well
#: beyond the 48h post-event check-in window, after which the row can no longer
#: trigger anything: the upcoming scan looks forward only, the check-in scan
#: looks at 48h, and promotion applies to recurring rows alone. Recurring rows
#: are the anniversary source and are kept.
CALENDAR_RETENTION_DAYS = 30

# ============= Weather mood routing constants =============
# === Sanity -> library couplings ===
# Applied by LifeService glue from the sanity engine's state word (never inside
# the engine), so a host that couples to ``SanitySystem.state`` and a host that
# reads affect or shadow directly see one story. The words are the contract;
# the amounts live here.
SANITY_STRESS_SOURCE = "sanity"             # affect stressor while strained or worse
SANITY_FRAYING_RESTRAINT_PRESSURE = 0.2     # shadow restraint pull while fraying or worse
SANITY_BREAKING_REGULATION_COLLAPSE = 1.0   # regulation capacity drained on entering breaking
# Affect stress *level* at or above which the sanity tick reads the persona as
# stressed. The level is what affect keeps live (it decays every tick); the
# ``stress.sources`` labels are a capped summary that the service never
# resolves (``struggle:*``, ``money worries`` ...), so reading *them* would make
# every persona with a struggle erode to ``broken`` in days without a single
# blow. 0.2 is the floor of affect's own ``get_stress_description()`` -- below
# it, affect has nothing to say about stress.
SANITY_STRESSED_LEVEL = 0.2

# Small one-shot nudge applied via AffectSystem.on_weather_nudge() on WEATHER CHANGE
# (not every tick), so the push is bounded. Scale factors are unitless weights on
# _shift_mood_positive / _shift_mood_negative internally.
WEATHER_MOOD_WEIGHT = 0.03  # overall scale — keep tiny so weather is atmospheric, not dominant

# Trip length: a real "travelling abroad" span (about one to just-over-two weeks),
# not a long-weekend. Overridable via AURA_TRIP_MIN_DAYS / AURA_TRIP_MAX_DAYS.
TRIP_MIN_DAYS = 5
TRIP_MAX_DAYS = 16

# Signed delta per Weather enum value: +1 = max positive, -1 = max negative.
# Multiplied by WEATHER_MOOD_WEIGHT before passing to on_weather_nudge().
_WEATHER_MOOD_DELTA: dict = {
    "sunny":       +1.0,
    "clear_night": +0.5,
    "starry":      +1.0,
    "cloudy":      -0.3,
    "rainy":       -1.0,
    "stormy":      -1.0,
    "foggy":       -0.5,
    "snowy":       -0.5,
}


# ============= Micro-Events Pool =============

MICRO_EVENTS = [
    {"text": "She spilled coffee on her shirt", "emotion": {"amused": 0.1}, "share_worthy": True},
    {"text": "A cute cat appeared on the windowsill", "emotion": {"joyful": 0.15}, "share_worthy": True},
    {"text": "The power flickered for a moment", "emotion": {"startled": 0.1}, "share_worthy": False},
    {"text": "A package arrived that she forgot she ordered", "emotion": {"excited": 0.1, "surprised": 0.1}, "share_worthy": True},
    {"text": "She found a really good song by accident", "emotion": {"joyful": 0.15}, "share_worthy": True},
    {"text": "Her pen ran out of ink mid-sentence", "emotion": {"amused": 0.05}, "share_worthy": False},
    {"text": "She noticed the sunset was particularly beautiful", "emotion": {"awed": 0.15}, "share_worthy": True},
    {"text": "A neighbor's dog barked hello at her", "emotion": {"amused": 0.1}, "share_worthy": True},
    {"text": "She tripped on absolutely nothing", "emotion": {"amused": 0.1}, "share_worthy": True},
    {"text": "The wind blew her hair into her face", "emotion": {"amused": 0.05}, "share_worthy": False},
    {"text": "She overheard a stranger say something hilarious", "emotion": {"amused": 0.15}, "share_worthy": True},
    {"text": "Her phone buzzed with a notification she didn't care about", "emotion": {}, "share_worthy": False},
    {"text": "She caught a whiff of something delicious from somewhere", "emotion": {"curious": 0.1}, "share_worthy": False},
    {"text": "A bird landed right next to her", "emotion": {"wonder": 0.1}, "share_worthy": True},
    {"text": "She realized she'd been humming a song without noticing", "emotion": {"content": 0.1}, "share_worthy": False},
    {"text": "She found some money in her jacket pocket", "emotion": {"surprised": 0.1, "joyful": 0.1}, "share_worthy": True},
    {"text": "The first drops of rain hit the window", "emotion": {"peaceful": 0.1}, "share_worthy": False},
    {"text": "She got a compliment from a stranger", "emotion": {"warm": 0.15}, "share_worthy": True},
    {"text": "Her favorite mug was clean when she needed it", "emotion": {"content": 0.05}, "share_worthy": False},
    {"text": "She caught her reflection and liked what she saw", "emotion": {"content": 0.1}, "share_worthy": False},
]


# ============= Skill Mappings =============

SKILL_MAPPINGS: Dict[str, tuple] = {
    "reading": ("knowledge", 0.005),
    "writing poetry": ("writing", 0.008),
    "sketching ideas": ("art", 0.008),
    "cooking a meal": ("cooking", 0.005),
    "baking something": ("cooking", 0.006),
    "trying a new recipe": ("cooking", 0.008),
    "yoga": ("flexibility", 0.005),
    "going for a run": ("fitness", 0.008),
    "gym workout": ("fitness", 0.01),
    "meditating": ("mindfulness", 0.005),
    "journaling": ("writing", 0.004),
    "learning something new": ("knowledge", 0.008),
    "creating a playlist": ("music_curation", 0.004),
}

SKILL_MILESTONES: Dict[str, List[tuple]] = {
    "knowledge": [
        (0.1, "Started getting into a groove with reading"),
        (0.3, "Feels more well-read lately"),
        (0.6, "Has opinions about literary styles now"),
    ],
    "cooking": [
        (0.1, "Made something that actually tasted good"),
        (0.3, "Getting confident in the kitchen"),
        (0.6, "Experimenting with her own recipes"),
    ],
    "fitness": [
        (0.1, "Starting to feel stronger"),
        (0.3, "Exercise is becoming a habit"),
        (0.6, "Noticeably fitter and more energetic"),
    ],
    "writing": [
        (0.1, "Found her voice on paper"),
        (0.3, "Writing comes more naturally now"),
        (0.6, "Proud of what she's been creating"),
    ],
    "mindfulness": [
        (0.1, "Meditation is getting easier"),
        (0.3, "Feels more present in daily life"),
        (0.6, "Inner calm is becoming her default"),
    ],
}


# ============= Dream Templates =============

DREAM_TEMPLATES = [
    "Dreamed she was {0} in some place made of {1}",
    "Had a weird dream where {0} and {1} got mixed together",
    "Had a dream where {0} kept turning into {1}",
    "Dreamed about {0} and woke up feeling {1}",
    "Her dream had {0} and {1} mixed up in some weird way",
]


# ============= Multi-Engine Conversation Keyword Map =============

CONVERSATION_KEYWORD_MAP = {
    # Desire (existing keywords, preserved)
    "beautiful": [("desire", "compliment_physical")],
    "gorgeous": [("desire", "compliment_physical")],
    "pretty": [("desire", "compliment_physical")],
    "sexy": [("desire", "compliment_intimate")],
    "hot": [("desire", "compliment_intimate")],
    "want you": [("desire", "being_desired")],
    "fantasize": [("desire", "fantasy_sharing")],
    "flirt": [("desire", "flirting")],
    "tease": [("desire", "flirting")],
    # Affect
    "proud of you": [("affect", "encouragement"), ("identity", "affirmation")],
    "well done": [("affect", "encouragement"), ("identity", "validation")],
    "it's okay": [("affect", "emotional_support")],
    "don't worry": [("affect", "emotional_support")],
    "haha": [("affect", "humor"), ("energy", "laughter")],
    "lol": [("affect", "humor"), ("energy", "laughter")],
    "how do you feel": [("affect", "deep_conversation")],
    # Energy
    "exciting": [("energy", "exciting_topic")],
    "can't wait": [("energy", "exciting_topic")],
    "keep going": [("energy", "motivation")],
    "boring": [("energy", "boring_topic")],
    "exhausting": [("energy", "emotional_drain")],
    # Cognitive
    "what do you think": [("cognitive", "intellectual_topic")],
    "interesting": [("cognitive", "intellectual_topic"), ("drive", "interesting_topic")],
    "why do you": [("cognitive", "philosophical_question")],
    "what if": [("cognitive", "philosophical_question"), ("drive", "new_idea")],
    "i disagree": [("cognitive", "disagreement"), ("affect", "healthy_debate")],
    "you're wrong": [("affect", "healthy_debate"), ("cognitive", "defending_opinion")],
    "no way": [("affect", "healthy_debate"), ("cognitive", "defending_opinion")],
    "don't you think": [("cognitive", "philosophical_question"), ("affect", "healthy_debate")],
    "but what about": [("cognitive", "intellectual_topic"), ("affect", "healthy_debate")],
    "agree to disagree": [("affect", "healthy_debate"), ("identity", "standing_ground")],
    "that's not": [("cognitive", "defending_opinion"), ("affect", "healthy_debate")],
    "smart": [("cognitive", "compliment_intelligence"), ("identity", "validation")],
    "clever": [("cognitive", "compliment_intelligence"), ("identity", "validation")],
    "imagine": [("cognitive", "creative_prompt"), ("drive", "new_idea")],
    # Identity
    "love": [("desire", "romantic_conversation"), ("identity", "affirmation")],
    "miss you": [("desire", "romantic_conversation"), ("affect", "emotional_support")],
    "think about you": [("desire", "romantic_conversation"), ("identity", "personal_question")],
    "me too": [("identity", "shared_interest")],
    "same here": [("identity", "shared_interest")],
    # Drive
    "you should try": [("drive", "comfort_zone_push")],
    "curious about": [("drive", "interesting_topic")],
    "wonder": [("drive", "interesting_topic")],
    "did it": [("drive", "accomplishment_shared")],
    "stop putting off": [("drive", "avoidance_nudge")],
}


# ============= Transit Constants =============

PREP_TIME_MINUTES = 12
TRAVEL_TIME_RANGES = {
    "nearby": (5, 12), "moderate": (12, 25), "far": (25, 45),
}
PLACE_TYPE_DISTANCES = {
    "home": "nearby", "cafe": "nearby", "park": "nearby",
    "gym": "moderate", "bar": "moderate", "restaurant": "moderate",
    "library": "moderate", "beach": "moderate",
    "workplace": "far", "campus": "far", "school": "far",
}


# ============= Need Assessment Constants =============

NEED_UNMET_THRESHOLD = 0.35  # Below this, need is "unmet" and produces directives


# ============= Life Trigger Cooldowns =============
BASE_LIFE_TRIGGER_COOLDOWNS = {
    # Self-narrating / abstract types are deliberately rare: they interrupt the user
    # to broadcast the persona's own inner life, so without a concrete anchor they
    # read as vague filler. Grounded types (loneliness, dream, concrete events) keep
    # tighter cooldowns.
    "mood_shift": 12.0,       # was 4.0 — pure self-narration, make rare
    "loneliness_spike": 8.0,
    "dream_share": 24.0,      # once per sleep cycle
    "chaos_event": 8.0,       # was 6.0 — concrete event, mild bump
    "nostalgia": 24.0,        # was 12.0
    "upcoming_event": 12.0,
    "event_check_in": 12.0,
    "goal_milestone": 24.0,   # was 8.0 — worst "epiphany about my content" offender
    "social_event": 12.0,     # was 6.0
    "need_driven": 24.0,      # was 12.0
    "life_question": 18.0,    # was 6.0
    "excitement_share": 12.0, # was 4.0 — "I cracked the code" filler, make rare
    "moment_share": 12.0,     # was 8.0 — notable activity moment (with photo)
}

# Activities too routine to generate a moment-share trigger
MOMENT_SHARE_ROUTINE_SKIP = {"sleep", "commut", "work"}

# Relationship stages (ExpressionSystem) considered "close". An AI persona only
# unlocks human-like spontaneous/emotional proactive behavior once the bond is
# this deep; before then she stays in practical/reminder territory. Humans are
# never gated by this.
CLOSE_RELATIONSHIP_STAGES = {"comfortable", "deep"}


class LifeService:
    """
    Main service coordinating the persona's autonomous life.

    Manages:
    - World environment (location, weather, time)
    - Energy system (fatigue, circadian rhythm)
    - Activity simulation
    - Goal tracking
    - Desire/intimacy system
    - Shareable experiences
    - Background scheduling
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        emotion_engine: Optional[object] = None,
        memory_service: Optional[object] = None,
        world_environment: Optional[WorldEnvironment] = None,
        sleep_schedule: Optional[Dict] = None,
        occupation: str = "",
        interests: Optional[List[str]] = None,
        persona_locations: Optional[Dict[str, str]] = None,
        persona_id: Optional[str] = None,
        definition: Optional[object] = None,
        social_circle: Optional[List[Dict]] = None,
        media_preferences: Optional[Dict[str, List[str]]] = None,
        user_info: Optional[Dict] = None,
        weather_service: Optional[object] = None,
        trip_llm: Optional[object] = None,
        trip_geocode=None,
        user_model_provider: Optional[Callable[[str], object]] = None,
        follow_up_provider: Optional[Callable[[str], object]] = None,
        datastore: Optional[object] = None,
        sanity_rng=None,
        rng=None,
    ):
        """
        Initialize the life service.

        Args:
            db_path: Path to the SQLite database. Optional only when a host has
                registered the ``get_config`` hook and ``persona_id`` is given,
                in which case it resolves to
                ``<get_config().data_dir>/<persona_id>/life.db``. There is no
                relative default: see :meth:`_resolve_db_path`.
            emotion_engine: Optional emotion engine for integration
            memory_service: Optional memory service for integration
            world_environment: Optional shared WorldEnvironment. When provided,
                world ticks are skipped internally (caller is responsible for ticking).
            sleep_schedule: Optional sleep schedule dict from persona profile.
                Contains bedtime_hour, wake_hour, etc.
            occupation: Persona's occupation (e.g. "nurse", "software engineer").
                When set, work blocks are added to the daily schedule.
            interests: Persona's interests/hobbies for schedule variety.
            persona_locations: Dict mapping location keys to descriptions
                from the persona profile (e.g. {"home": "cozy apartment..."}).
            persona_id: Persona identifier (for visual description updates).
            definition: PersonalityDefinition object (for visual description updates).
            datastore: Optional host datastore for the user-calendar tables. When
                supplied it must expose ``get_connection()`` as a context manager
                yielding a live sqlite3 connection (the same contract
                ``EmotionPersistence`` uses), and calendar rows are written there
                instead of into ``db_path``. Optional like ``memory_service``:
                with none supplied the calendar lives in ``db_path``, where
                ``_init_database()`` already creates its table.
            sanity_rng: Optional random source for the sanity engine's one
                construction-time draw (the baseline jitter; see
                :class:`~aura_life.sanity.SanitySystem`). ``None`` -- the
                default -- takes no draw at all, so a host that already seeds
                its own rng and passes nothing keeps its sequence untouched.
                When ``rng`` is given and this is not, it defaults to ``rng``:
                one injected source then replays the whole persona, jitter
                included. Pass both to keep them apart.
            rng: Optional ``random.Random`` for every draw on the energy-tick
                path (identity's struggles, defects and tendencies; desire,
                habitation, cognitive, drive, career, finance, errands,
                memory-time and life-event draws; the service's own
                struggle-to-rumination roll, shareable priority and
                life-trigger pick). ``None`` -- the default -- leaves every
                draw on the module-level ``random`` exactly as before, so an
                existing consumer is byte-identical. Given, no draw on that
                path touches module ``random``, so a host that ticks two
                services from two equal-seeded rngs gets two identical runs.
                Draws off the tick path (persona generation, the daily
                planner, activities, chaos, the world's weather) are not
                routed here.
        """
        self._db_path = self._resolve_db_path(db_path, persona_id)
        self._emotion_engine = emotion_engine
        self._memory_service = memory_service
        # Host-supplied datastore for the user calendar. Injected, not resolved
        # through get_persona_datastore(): every other collaborator on this class
        # is injected, and a hook lookup would silently relocate an existing
        # host's calendar rows out of db_path.
        self._datastore = datastore
        self._calendar_schema_ready = False
        self._sleep_schedule = sleep_schedule
        self._occupation = occupation
        self._interests = interests or []
        self._persona_locations = persona_locations or {}
        self._persona_id = persona_id
        self._user_model_provider = user_model_provider
        self._follow_up_provider = follow_up_provider
        self._definition = definition
        self._social_circle_defs = social_circle or []
        self._media_preferences = media_preferences or {}
        self._user_info = user_info

        # Initialize subsystems — pass persona_locations and sleep_schedule to world and planner
        if world_environment:
            world_environment._persona_locations = self._persona_locations
            world_environment._sleep_schedule = sleep_schedule
        self._world = world_environment or WorldEnvironment(
            persona_locations=self._persona_locations,
            sleep_schedule=sleep_schedule,
        )
        self._shared_world = world_environment is not None
        # Extract core_traits once for all engines
        self._core_traits = getattr(definition, 'core_traits', []) if definition else []
        # The tick-path rng. ``_rng`` is what the host gave (None or a Random)
        # and is threaded into every engine that draws on the energy tick;
        # ``_random`` is what this class itself draws from (module ``random``
        # when nothing was injected, so the default is byte-identical).
        self._rng = rng
        self._random = rng if rng is not None else random
        if sanity_rng is None:
            sanity_rng = rng

        self._energy = EnergySystem(
            sleep_schedule=sleep_schedule,
            core_traits=self._core_traits,
            now=self._world_clock(),
        )
        self._activity_engine = ActivityEngine()
        self._goal_engine = GoalEngine()
        self._desire_system = DesireSystem(core_traits=self._core_traits, rng=self._rng)

        # New subsystems — seeded from the persona profile where applicable.
        _defn = self._definition
        # AI personas have no body/finances/home/commute — gate the physical-life
        # engines off so an AI companion doesn't "get hungry" or "pay rent".
        self._is_ai = (getattr(_defn, 'persona_type', 'human') == 'ai') if _defn else False
        # Energy is built above (before persona_type is known) — thread the AI flag
        # in now so an AI never sleeps and carries no sleep-physiology in its digest.
        self._energy._is_ai = self._is_ai
        # Conversation-session tracking for the sign-off / wrap-up feature
        # (in-memory; resets on new session/day). Plus the server-side
        # "just woke up" latch for wake-aware first replies, and the explicit
        # forced-wake override (the app's "Wake up" button — v2.31.1).
        self._session = ConversationSession()
        self._woke_pending = False
        self._forced_wake_at: Optional[datetime] = None
        # Weather change tracking for one-shot mood nudge.
        self._last_weather_label: str = ""
        self._sustenance = SustenanceSystem()
        self._basic_needs = self._sustenance.state  # back-compat alias (same object)
        self._habitation = HabitationSystem(
            home_type=getattr(_defn, 'home_type', '') if _defn else '',
            rng=self._rng,
        )
        self._room_state = self._habitation.state  # back-compat alias (same object)
        self._finance = FinanceSystem(core_traits=self._core_traits, rng=self._rng, now=self._world_clock()())
        if _defn and getattr(_defn, 'spending_habit', None) is not None:
            self._finance.state.spending_habit = _defn.spending_habit
        self._financial = self._finance.state  # back-compat alias (same state object)
        _occupation = self._occupation or (getattr(_defn, 'occupation', '') if _defn else '')
        _salary = getattr(_defn, 'monthly_salary', None) if _defn else None
        self._career = CareerSystem(occupation=_occupation, monthly_salary=_salary, rng=self._rng)
        # Align the Job engine's schedule with the planner's occupation type so
        # "on shift" matches when the planner schedules work.
        self._apply_occupation_schedule(self._career, _occupation)
        # Job pays the bills: salary drives finance income.
        if self._career.monthly_salary > 0:
            self._finance.state.monthly_income = self._career.monthly_salary
        self._media = self._init_media_state()
        self._skills_system = SkillsSystem()
        self._skills: Dict[str, SkillProgress] = self._skills_system.skills  # alias
        self._errands = ErrandsSystem(rng=self._rng)
        npcs = self._build_npcs(self._social_circle_defs)
        self._social = SocialSystem(npcs=npcs)
        self._identity = IdentitySystem(
            npcs=npcs, user_info=self._user_info, core_traits=self._core_traits,
            humor_style=getattr(definition, 'humor_style', '') if definition else '',
            core_values=getattr(definition, 'core_values', []) if definition else [],
            struggles=getattr(definition, 'struggles', []) if definition else [],
            character_defects=getattr(definition, 'character_defects', []) if definition else [],
            behavioral_tendencies=getattr(definition, 'behavioral_tendencies', {}) if definition else {},
            rng=self._rng,
        )
        self._affect = AffectSystem(
            core_traits=self._core_traits,
            emotional_baseline=getattr(definition, 'emotional_baseline', {}) if definition else {},
        )
        self._body = BodySystem(
            hormonal_enabled=getattr(definition, 'hormonal_enabled', False) if definition else False,
            substance_tendencies=getattr(definition, 'substance_tendencies', {}) if definition else {},
        )
        self._cognitive = CognitiveSystem(
            core_traits=self._core_traits,
            intrusive_thought_themes=getattr(definition, 'intrusive_thought_themes', []) if definition else [],
            rng=self._rng,
        )
        self._shadow = ShadowSystem(
            behavioral_tendencies=(getattr(definition, 'behavioral_tendencies', {}) if definition else {}) or {},
            character_defects=(getattr(definition, 'character_defects', []) if definition else []) or [],
            struggles=(getattr(definition, 'struggles', []) if definition else []) or [],
            intrusive_thought_themes=(getattr(definition, 'intrusive_thought_themes', []) if definition else []) or [],
            substance_tendencies=(getattr(definition, 'substance_tendencies', {}) if definition else {}) or {},
            core_traits=(getattr(definition, 'core_traits', []) if definition else []) or [],
        )
        self._sanity_rng = sanity_rng
        self._sanity = SanitySystem(
            struggles=(getattr(definition, 'struggles', []) if definition else []) or [],
            character_defects=(getattr(definition, 'character_defects', []) if definition else []) or [],
            intrusive_thought_themes=(getattr(definition, 'intrusive_thought_themes', []) if definition else []) or [],
            rng=sanity_rng,
        )
        # Elapsed-time stamp for the sanity tick, on the world clock like energy.
        self._sanity_ticked_at = self._world_clock()()
        # The word the couplings were last applied for. Recorded, never applied
        # here: the couplings fire on a *change* of word, so a persona whose
        # baseline already sits below ``sound`` is not coupled for existing.
        self._sanity_coupled_state: str = self._sanity.state
        self._drive = DriveSystem(
            core_traits=self._core_traits,
            comfort_zone_seeds=getattr(self._definition, 'comfort_zone_seeds', []) if self._definition else [],
            rng=self._rng,
        )
        self._behavior = BehaviorSystem()
        self._memory_time = MemoryTimeSystem(rng=self._rng)
        self._expression = ExpressionSystem()
        self._continuity = ContinuitySystem()
        self._character_evolution = CharacterEvolution(
            original_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
            core_traits=getattr(self._definition, 'core_traits', []) if self._definition else [],
        )
        self._chaos = ChaosEngine()
        self._life_events = LifeEventSystem(rng=self._rng)
        self._pipeline = None  # Set externally via set_pipeline()
        self._transit: Optional[TransitState] = None  # Active transit overlay
        self._transport = TransportSystem()           # Travel estimation + mode
        # Place-identity volatile state (current city / trip / weather)
        self._place_location: PlaceLocationState = PlaceLocationState()

        # WeatherService injection (default lazy-loaded singleton; mock in tests).
        # Stored as-is (may be None until first use).
        self._weather_service_override: Optional[object] = weather_service

        # Trip feature injections (LLM + geocoder may be mocked in tests; None = use defaults).
        self._trip_llm_override: Optional[object] = trip_llm
        self._trip_geocode_override = trip_geocode
        # Track the calendar date of the last trip-roll so we roll at most once per day.
        self._trip_last_roll_date: str = ""
        # Deferred save flag: set by _load_place_state when catch-up reverts a trip,
        # consumed by _load_state after the cursor is closed.
        self._trip_catchup_pending_save: bool = False

        # Location registry: rich LocationProfile objects keyed by slug
        self._location = LocationSystem()
        self._location_registry: Dict[str, LocationProfile] = self._location.registry  # alias
        self._build_location_registry()
        self._last_location: str = "home"
        self._consecutive_home_ticks: int = 0
        self._locations_visited_today: set = self._location.visited_today  # alias
        self._locations_visited_today_date: str = ""

        self._daily_planner = DailyPlanner(
            occupation=occupation,
            interests=interests or [],
            sleep_schedule=sleep_schedule,
            persona_locations=self._persona_locations,
            nationality=getattr(definition, 'nationality', '') if definition else '',
            is_ai=self._is_ai,
        )
        # Supply the planner with derived location keys
        self._daily_planner._available_location_keys |= set(self._location_registry.keys())

        # Context builder
        self._context_builder = LifeContextBuilder(
            self._world,
            self._energy,
            self._activity_engine,
            self._goal_engine,
            self._desire_system,
            self._daily_planner,
            basic_needs=self._basic_needs,
            room_state=self._room_state,
            social_system=self._social,
            media_state=self._media,
            identity_system=self._identity,
            affect_system=self._affect,
            cognitive_system=self._cognitive,
            shadow_system=self._shadow,
            location_registry=self._location_registry,
            drive_system=self._drive,
            body_system=self._body,
            behavior_system=self._behavior,
            memory_time_system=self._memory_time,
            expression_system=self._expression,
            continuity_system=self._continuity,
            finance_system=self._finance,
            career_system=self._career,
            life_service=self,
            is_ai=self._is_ai,
        )

        # Scheduler
        self._scheduler = LifeScheduler(
            on_world_tick=self._on_world_tick,
            on_activity_tick=self._on_activity_tick,
            on_energy_tick=self._on_energy_tick,
            on_goal_tick=self._on_goal_tick,
            on_plan_tick=self._on_plan_tick,
        )

        # State
        self._recent_activities: List[ActivityLog] = []
        self._shareable_queue: List[ShareableExperience] = []
        self._is_initialized = False

        # Visual description tracking (for transition detection)
        self._last_visual_activity: Optional[str] = None
        self._last_visual_location: Optional[str] = None
        self._last_visual_outfit: Optional[str] = None

        # Conversation-driven CURRENT activity (in-memory, not persisted — same
        # precedent as _last_user_message_at). Set from a [DOING:] tag; overrides
        # the scheduled activity for CONVERSATION_ACTIVITY_WINDOW_MINUTES.
        self._conversation_activity: str = ""
        self._conversation_activity_at: Optional[datetime] = None

        # Sites that have already reported a user_model_provider failure, so a
        # broken host provider is loud once instead of every tick forever.
        self._user_model_failures_seen: set = set()

        # Background thread handles. Both are daemon threads spawned by this
        # class; keeping the handles is what lets stop() join them instead of
        # leaving them mutating engine state after _save_state() has run.
        self._visual_thread: Optional[threading.Thread] = None
        self._init_ticks_thread: Optional[threading.Thread] = None
        # Guards the check-and-spawn in _trigger_visual_description_update: the
        # trigger is reachable from the scheduler tick and from the init-tick
        # thread at once, so the is_alive() check alone would race.
        self._visual_thread_lock = threading.Lock()

        # Life-driven proactive trigger state (in-memory, not persisted)
        self._life_trigger_cooldowns: Dict[str, datetime] = {}
        self._prev_mood: Optional[str] = None
        self._prev_mood_intensity: float = 0.0
        self._prev_loneliness: float = 0.0
        self._last_seen_chaos_event: Optional[str] = None
        self._last_seen_nostalgia_ref: Optional[str] = None
        self._last_moment_share_chaos_event: Optional[str] = None
        self._pending_moment_share_chaos_event: Optional[str] = None

        # Initialize database
        self._init_database()

    # ============= Init Helpers =============

    @staticmethod
    def _resolve_db_path(db_path: Optional[str], persona_id: Optional[str]) -> str:
        """Resolve the SQLite path, refusing to invent a relative one.

        The default used to be the bare relative name ``"life.db"``, so a service
        constructed without arguments wrote its database into whatever directory
        the host process happened to be running in, and two personas started from
        the same working directory silently shared one file. This module already
        documents that exact class of bug — see the note in
        ``_persist_activity_emotions`` about ``*_emotions.db`` being scattered by
        a relative path.

        With no explicit path, resolve the host's data directory the way
        ``profile_db.get_profile_db`` does: ``<data_dir>/<persona_id>/life.db``,
        through ``safe_join`` so a crafted persona id cannot escape it. When
        neither an explicit path nor a host data directory is available there is
        no correct answer, so raise instead of guessing.

        Raises:
            ValueError: when no path can be resolved, or ``persona_id`` is not a
                well-formed id (see :mod:`aura_life._safe_ids`).
        """
        if db_path:
            return db_path

        if not persona_id:
            raise ValueError(
                "LifeService requires db_path, or a persona_id plus a host "
                "get_config() hook so it can resolve "
                "<data_dir>/<persona_id>/life.db. There is no relative default: "
                "one would put the database in the host process's working "
                "directory and let two personas share it."
            )

        from aura_life._safe_ids import safe_join, safe_persona_id

        try:
            # Imported inside the guard: an unconfigured hook must degrade into
            # the ValueError below, not escape as HookNotConfigured. (The
            # unguarded-call-site census in tests keys on this import's position.)
            from aura_life.hooks import get_config
            data_dir = get_config().data_dir
        except Exception as exc:
            raise ValueError(
                f"LifeService got no db_path and cannot resolve one for "
                f"{persona_id!r}: the host get_config() hook is unavailable "
                f"({exc}). Pass db_path explicitly."
            ) from exc

        if not data_dir:
            raise ValueError(
                f"LifeService got no db_path and the host's get_config().data_dir "
                f"is empty, so no path can be resolved for {persona_id!r}."
            )

        resolved = safe_join(data_dir, safe_persona_id(persona_id), "life.db")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return str(resolved)

    def _build_npcs(self, circle_defs: List[Dict]) -> List[NPC]:
        """Convert social_circle dicts from profile into NPC dataclasses."""
        npcs = []
        for d in circle_defs:
            interests_raw = d.get("shared_interests", "")
            if isinstance(interests_raw, str):
                interests = [i.strip() for i in interests_raw.split(",") if i.strip()]
            else:
                interests = list(interests_raw)

            rel = d.get("relationship", "friend")
            # Infer contact frequency from relationship type
            freq = "regular"
            if any(k in rel.lower() for k in ("best friend", "roommate", "bandmate")):
                freq = "daily"
            elif any(k in rel.lower() for k in ("family", "mom", "dad", "mum", "sister", "brother")):
                freq = "regular"
            elif any(k in rel.lower() for k in ("occasional", "ex", "old friend")):
                freq = "occasional"

            npcs.append(NPC(
                name=d.get("name", ""),
                relationship=rel,
                personality_brief=d.get("personality", ""),
                shared_interests=interests,
                contact_frequency=freq,
            ))
        return npcs

    def _init_media_state(self) -> MediaState:
        """Initialize media state from profile preferences."""
        media = MediaState()
        books = self._media_preferences.get("books", [])
        if books:
            media.current_book = random.choice(books)
            media.book_progress = random.uniform(0.1, 0.4)
        music = self._media_preferences.get("music", [])
        if music:
            media.current_music_obsession = random.choice(music)
        shows = self._media_preferences.get("shows", [])
        if shows:
            media.current_show = random.choice(shows)
            media.show_progress = random.uniform(0.1, 0.5)
        return media

    # ============= Location Registry =============

    # Default locations every persona starts with
    _DEFAULT_LOCATIONS: Dict[str, str] = {
        "home": "home", "cafe": "cafe", "park": "park", "gym": "gym",
        "library": "library", "street": "street", "workplace": "workplace",
        "restaurant": "restaurant", "bar": "bar", "rooftop": "other",
        "beach": "beach", "school": "campus", "campus": "campus",
        "in transit": "transit",
    }

    def _build_location_registry(self) -> None:
        """Build the location registry from multiple sources.

        Sources (in priority order):
        1. Default locations (always present)
        2. Persona profile locations (from text profiles)
        3. Occupation-derived locations
        4. Interest-derived locations
        5. User/LLM-added locations (loaded from DB later in _load_state)
        """
        from .planner.daily_planner import OCCUPATION_LOCATIONS, INTEREST_LOCATIONS

        registry = self._location_registry

        # 1. Defaults
        for key, place_type in self._DEFAULT_LOCATIONS.items():
            registry[key] = LocationProfile(
                key=key,
                name=key.replace("_", " ").title(),
                place_type=place_type,
                source="default",
                familiarity=0.5,
            )

        # 2. Profile locations (persona-specific, from text profiles)
        for loc_key, desc in self._persona_locations.items():
            slug = loc_key.lower().replace(" ", "_")
            if slug in registry:
                # Enrich existing entry with description
                registry[slug].description = desc
                registry[slug].source = "profile"
            else:
                registry[slug] = LocationProfile(
                    key=slug,
                    name=loc_key.replace("_", " ").title(),
                    place_type=self._infer_place_type(slug),
                    description=desc,
                    source="profile",
                    familiarity=0.6,
                )

        # 3. Occupation-derived
        occ_lower = self._occupation.lower() if self._occupation else ""
        for keyword, loc_pairs in OCCUPATION_LOCATIONS.items():
            if keyword in occ_lower:
                for loc_key, place_type in loc_pairs:
                    if loc_key not in registry:
                        registry[loc_key] = LocationProfile(
                            key=loc_key,
                            name=loc_key.replace("_", " ").title(),
                            place_type=place_type,
                            source="occupation",
                            familiarity=0.4,
                        )

        # 4. Interest-derived
        interests_lower = " ".join(i.lower() for i in self._interests)
        for keyword, loc_pairs in INTEREST_LOCATIONS.items():
            if keyword in interests_lower:
                for loc_key, place_type in loc_pairs:
                    if loc_key not in registry:
                        registry[loc_key] = LocationProfile(
                            key=loc_key,
                            name=loc_key.replace("_", " ").title(),
                            place_type=place_type,
                            source="interest",
                            familiarity=0.3,
                        )

    # Place-type inference from location name keywords
    _PLACE_TYPE_KEYWORDS: Dict[str, List[str]] = {
        "beach": ["marina", "pier", "harbor", "harbour", "surf", "cove", "dock", "waterfront"],
        "park": ["trail", "garden", "botanical", "field", "meadow", "forest", "woods"],
        "gym": ["studio", "dojo", "pool", "court", "climbing", "rink", "track"],
        "cafe": ["coffee", "cafe", "tea_house", "bakery"],
        "bar": ["pub", "tavern", "wine_bar", "lounge", "music_venue", "club"],
        "restaurant": ["diner", "bistro", "pizzeria", "noodle", "sushi"],
        "library": ["bookstore", "bookshop", "reading_room"],
        "workplace": ["office", "lab", "clinic", "hospital", "courthouse"],
        "campus": ["university", "college", "lecture"],
        "other": ["cinema", "theater", "theatre", "gallery", "museum", "mall", "market", "shop"],
    }

    @classmethod
    def _infer_place_type(cls, location_name: str) -> str:
        """Infer place_type from a location name using keyword matching."""
        name_lower = location_name.lower().replace("_", " ")
        for place_type, keywords in cls._PLACE_TYPE_KEYWORDS.items():
            for kw in keywords:
                if kw in name_lower:
                    return place_type
        return "other"

    def _apply_location_effects(self, location_key: str) -> None:
        """Apply location-based effects on energy, stress, mood, social battery.

        Called each activity tick after the activity executes.
        """
        # AI personas have no physical location (their "place" is a digital space),
        # so they never record real-world visits or accrue location-based effects.
        if self._is_ai:
            return
        now = datetime.now()
        loc = (location_key or "home").lower().replace(" ", "_")

        # Location engine: record the visit (familiarity + daily tracking) and
        # report what's needed to apply cross-engine effects.
        visit = self._location.record_visit(loc, now)
        place_type = visit["place_type"]
        is_nature = visit["is_nature"]
        profile = self._location.get_profile(loc)

        effects = LOCATION_TYPE_EFFECTS.get(place_type, LOCATION_TYPE_EFFECTS["other"])

        # Apply energy drain (negative = restorative)
        drain = effects["energy_drain"]
        if drain > 0:
            self._energy.consume_energy(drain)
        elif drain < 0:
            self._energy.restore_energy(abs(drain))

        # Apply commute cost when changing locations
        if loc != self._last_location:
            self._energy.consume_energy(COMMUTE_ENERGY_COST)

        # Affect: stress + social + nature
        self._affect.on_location_effects(
            stress_delta=effects["stress_delta"],
            social_drain=effects["social_drain"],
            is_nature=is_nature,
        )

        # Variety bonus: new location visited today → small mood boost
        if visit["is_new_today"] and visit["visited_today_count"] > 1:
            # Visiting a new place is refreshing
            self._affect.on_emotion_event("content", 0.02)

        # Favorite location comfort bonus (familiarity > 0.8)
        if profile and profile.familiarity > 0.8:
            comfort = effects.get("comfort", 0.5)
            comfort *= 1.5  # 50% bonus for favorite spots
            # Small stress relief from being in a familiar place
            self._affect.on_location_effects(
                stress_delta=-0.005 * comfort,
                social_drain=0.0,
                is_nature=False,
            )

        # Consecutive home tracking → loneliness nudge
        if loc == "home":
            self._consecutive_home_ticks += 1
            if self._consecutive_home_ticks > 18:  # ~90 min before kicking in
                # Stuck at home too long — nudge loneliness up
                nudge = 0.003 if self._consecutive_home_ticks <= 24 else 0.005
                self._affect._loneliness.level = min(
                    1.0, self._affect._loneliness.level + nudge
                )
        else:
            self._consecutive_home_ticks = 0

        self._last_location = loc

    def _register_user_location(self, location_key: str) -> LocationProfile:
        """Register a new user-mentioned location into the registry and persist it."""
        slug = location_key.lower().replace(" ", "_")
        if slug in self._location_registry:
            return self._location_registry[slug]

        profile = LocationProfile(
            key=slug,
            name=location_key.replace("_", " ").title(),
            place_type=self._infer_place_type(slug),
            source="user",
            familiarity=0.3,
        )
        self._location_registry[slug] = profile
        # Update planner's available keys
        self._daily_planner._available_location_keys.add(slug)
        # Persist
        self._save_location(profile)
        self._prune_user_locations()
        return profile

    def _prune_user_locations(self) -> None:
        """Keep the registry of user-mentioned places bounded.

        Slugs here come from free text the user or the LLM produced (a ``[PLAN: …]``
        tag, a schedule override), so a chatty or adversarial conversation would
        otherwise grow the registry, the planner's key set and the ``life_locations``
        table without limit, and ``_load_locations`` reloads all of them at start.

        Only ``source="user"`` entries are evictable — defaults, profile,
        occupation and interest seeds are structural. Never-visited entries go
        first (conversational noise), oldest registration first; a place she has
        actually been is part of her history. The location she is at right now is
        never evicted.
        """
        registry = self._location_registry
        user_keys = [k for k, p in registry.items() if p.source == "user"]
        excess = len(user_keys) - USER_LOCATION_MAX
        if excess <= 0:
            return

        current = (self._world.current_location or "").lower().replace(" ", "_")
        candidates = [(i, k) for i, k in enumerate(user_keys) if k != current]
        # Ascending by (visits, registration order) — least-attached first.
        candidates.sort(key=lambda ik: (registry[ik[1]].visit_count, ik[0]))
        doomed = [k for _, k in candidates[:excess]]
        if not doomed:
            return

        for key in doomed:
            registry.pop(key, None)
            self._daily_planner._available_location_keys.discard(key)

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            conn.executemany(
                "DELETE FROM life_locations WHERE key = ?",
                [(k,) for k in doomed],
            )
            conn.commit()

    # ============= Lifecycle =============

    def start(self) -> None:
        """Start the life service and background simulation."""
        if not self._is_initialized:
            self._load_state()
            self._goal_engine.initialize_goals()
            self._is_initialized = True

        # Backfill home location once for human personas that have none yet.
        # No-op for AI, feature-flag-off, or already-assigned personas.
        self._try_assign_home()

        # Start scheduler
        self._scheduler.start()

        # Run initial ticks in background — scheduler is already running,
        # endpoints return default state until first tick completes.
        # Guarded: _scheduler.start() is idempotent but this spawn was not, so a
        # second start() used to add an orphan thread with no handle, still free
        # to mutate engine state after stop() had already saved.
        if self._init_ticks_thread is None or not self._init_ticks_thread.is_alive():
            self._init_ticks_thread = threading.Thread(
                target=self._scheduler.force_all_ticks,
                daemon=True,
                name=f"life-init-ticks-{self._persona_id}",
            )
            self._init_ticks_thread.start()

        # Log sleep schedule info
        if self._sleep_schedule:
            wake_h = self._sleep_schedule.get("wake_hour", 7)
            wake_m = self._sleep_schedule.get("wake_minute", 0)
            bed_h = self._sleep_schedule.get("bedtime_hour", 23)
            bed_m = self._sleep_schedule.get("bedtime_minute", 0)
            logger.info(f"Life service started (sleep schedule: wake {wake_h}:{wake_m:02d}, bed {bed_h}:{bed_m:02d})")
        else:
            logger.info("Life service started (using default sleep schedule)")

    def _try_assign_home(self) -> None:
        """Backfill home city once for human personas that don't have one yet.

        Gated by the host's injected config — ``get_config().place_enabled``
        via ``aura_life.hooks`` — and by persona_type; no-op when home is
        already assigned. That gate is config, not an environment variable:
        nothing here consults ``os.environ``. Safe-fail (never raises).
        """
        try:
            from aura_life.hooks import get_config
            cfg = get_config()
            if not cfg.place_enabled:
                return
            if self._is_ai:
                return
            if not self._definition:
                return
            # Quick check — skip the import if home is already set
            if (getattr(self._definition, "home_city", "")
                    or getattr(self._definition, "home_lat", None) is not None):
                return
            from aura_life.location.place_service import PlaceService
            PlaceService().assign_home_if_missing(self._definition, self)
        except Exception as exc:
            logger.warning("_try_assign_home failed: %s", exc)

    #: Seconds stop() waits for each background thread before giving up on it.
    _THREAD_JOIN_TIMEOUT = 10.0

    def stop(self) -> None:
        """Stop the life service and save state.

        Background threads are joined *before* ``_save_state()``: both of them
        mutate engine state, so saving first would persist a snapshot they then
        moved on from, and returning with them still running leaves work racing a
        service the caller believes is stopped.
        """
        self._scheduler.stop()

        for label, thread in (
            ("init-ticks", self._init_ticks_thread),
            ("visual-description", self._visual_thread),
        ):
            if thread is not None and thread.is_alive():
                thread.join(self._THREAD_JOIN_TIMEOUT)
                if thread.is_alive():
                    logger.warning(
                        "%s thread did not finish within %.0fs of stop()",
                        label, self._THREAD_JOIN_TIMEOUT,
                    )
        self._init_ticks_thread = None
        self._visual_thread = None

        self._save_state()
        logger.info("Life service stopped")

    # ============= Public API =============

    @property
    def world(self) -> WorldEnvironment:
        """Get world environment."""
        return self._world

    @property
    def energy(self) -> EnergySystem:
        """Get energy system."""
        return self._energy

    @property
    def goals(self) -> GoalEngine:
        """Get goal engine."""
        return self._goal_engine

    @property
    def desire(self) -> DesireSystem:
        """Get desire system."""
        return self._desire_system

    @property
    def planner(self) -> DailyPlanner:
        """Get daily planner."""
        return self._daily_planner

    @property
    def social(self) -> SocialSystem:
        """Get social system."""
        return self._social

    @property
    def identity(self) -> IdentitySystem:
        """Get identity system."""
        return self._identity

    @property
    def basic_needs(self) -> BasicNeedsState:
        """Get basic needs state."""
        return self._basic_needs

    @property
    def media(self) -> MediaState:
        """Get media state."""
        return self._media

    @property
    def chaos(self) -> ChaosEngine:
        """Get chaos engine."""
        return self._chaos

    @property
    def life_events(self) -> LifeEventSystem:
        """Get life events system."""
        return self._life_events

    @property
    def expression(self) -> ExpressionSystem:
        """Get expression system."""
        return self._expression

    @property
    def affect(self) -> AffectSystem:
        """Get affect system."""
        return self._affect

    @property
    def sanity(self) -> SanitySystem:
        """Get sanity system -- the one interior number that can break."""
        return self._sanity

    @property
    def cognitive(self) -> CognitiveSystem:
        """Get cognitive system."""
        return self._cognitive

    @property
    def drive(self) -> DriveSystem:
        """Get drive system."""
        return self._drive

    @property
    def body(self) -> BodySystem:
        """Get body system."""
        return self._body

    @property
    def memory_time(self) -> MemoryTimeSystem:
        """Get memory-time system."""
        return self._memory_time

    @property
    def continuity(self) -> ContinuitySystem:
        """Get continuity system."""
        return self._continuity

    @property
    def current_activity_name(self) -> str:
        """Get the name of the current activity.

        Conversation-driven activity (from a [DOING:] tag) wins over the scheduled
        slot for a window after the last user message, so a stale planner slot
        doesn't bleed into status, pictures, or proactive messages.
        """
        scheduled = ""
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot()
            if slot:
                scheduled = slot.activity_name
        return self.effective_current_activity(scheduled)

    def set_conversation_activity(self, activity: str) -> None:
        """Record the persona's CURRENT activity as stated in conversation.

        Captured from a [DOING:] tag in her response. Overrides the scheduled
        activity for CONVERSATION_ACTIVITY_WINDOW_MINUTES. Blank input is ignored.
        """
        cleaned = (activity or "").strip()
        if not cleaned:
            return
        self._conversation_activity = cleaned
        self._conversation_activity_at = datetime.now()
        logger.info(f"Conversation activity set: {cleaned!r}")

    def effective_current_activity(self, scheduled: str) -> str:
        """Return the conversation activity if it's still within the window,
        otherwise the scheduled activity passed in."""
        if self._conversation_activity and self._conversation_activity_at:
            elapsed = datetime.now() - self._conversation_activity_at
            if elapsed <= timedelta(minutes=CONVERSATION_ACTIVITY_WINDOW_MINUTES):
                return self._conversation_activity
        return scheduled

    def consume_just_woke(self) -> bool:
        """Return True exactly once if the latest user message woke her.

        Consumed by the chat prompt builder to set time_ctx.just_woke_up so the
        SleepAwarenessSection renders the groggy first reply. Self-clearing.
        """
        woke = getattr(self, "_woke_pending", False)
        self._woke_pending = False
        return woke

    def force_wake(self) -> None:
        """Explicit user-initiated wake (the app's "Wake up" button — v2.31.1).

        Called by the /api/chat sleep-guard bypass when a request arrives with
        time_context.just_woke_up=True while she's asleep. Flips is_asleep()
        to False (via the forced-wake override, refreshed by ongoing chat and
        expiring FORCED_WAKE_WINDOW_MINUTES after the last user message), ends
        the "sleeping" activity through the conversation-activity override, and
        sets the just-woke latch so the existing SleepAwarenessSection renders
        the groggy first reply. In-memory only, like the wake latch itself.

        No-op for AI personas — they never sleep, so there is nothing to wake.
        """
        if self._is_ai:
            return
        self._forced_wake_at = datetime.now()
        self._woke_pending = True
        # End the "sleeping" activity: the conversation override wins over the
        # planner slot for status/pictures/proactive for the usual window.
        self.set_conversation_activity("just woke up")
        logger.info("Forced wake: user explicitly woke her (wake button)")

    def is_forced_wake_fresh(self) -> bool:
        """True while the explicit forced-wake override (wake button) is still live.

        Cheap read-only check for the proactive scheduler's WAKE_UP_REPLY gate:
        right after a wake press, is_asleep() is already False but the wake-turn
        generation is still in flight (assistant row unsaved), so the deferred
        messages still look unanswered — queuing a WAKE_UP_REPLY then would
        double-fire ("sorry I missed your messages" alongside the wake reply).

        Mirrors the is_asleep() override window — fresh while the later of the
        wake press and the last user message is within FORCED_WAKE_WINDOW_MINUTES
        — but never mutates state (is_asleep() owns the expiry/clear). Always
        False for AI personas and when the wake button was never pressed.
        """
        if self._is_ai:
            return False
        forced_at = getattr(self, "_forced_wake_at", None)
        if forced_at is None:
            return False
        ref = forced_at
        last_msg = getattr(self, "_last_user_message_at", None)
        if last_msg is not None and last_msg > ref:
            ref = last_msg
        return (datetime.now() - ref) <= timedelta(minutes=FORCED_WAKE_WINDOW_MINUTES)

    def _next_activity_info(self) -> tuple:
        """(activity_name, is_important) for her next scheduled slot."""
        name = ""
        plan = self._daily_planner.current_plan
        if plan is not None:
            nxt = plan.get_next_slot()
            if nxt is not None:
                name = nxt.activity_name or ""
        important = is_important_activity(name, self._errands) if name else False
        return name, important

    def wrapup_due(self) -> Optional[dict]:
        """Sign-off context if an active chat just went quiet, else None.

        Returns {'escalation': int, 'next_activity': str,
        'next_activity_important': bool}. Suppressed while asleep.
        """
        now = datetime.now()
        last = getattr(self, "_last_user_message_at", None)
        in_conv = bool(last and (now - last).total_seconds() < 20 * 60)
        asleep = self._energy.is_asleep(in_conversation=in_conv, now_hour=self.persona_local_hour())
        ctx = self._session.wrapup_context(now, last, asleep)
        if ctx is None:
            return None
        name, important = self._next_activity_info()
        ctx["next_activity"] = name
        ctx["next_activity_important"] = important
        return ctx

    def note_wrapup_sent(self) -> None:
        """Mark the sign-off sent so it doesn't repeat until they reply."""
        self._session.note_wrapup_sent()

    @property
    def sleep_schedule(self) -> Optional[Dict]:
        """Get the persona's sleep schedule."""
        return self._sleep_schedule

    def hours_since_wake(self) -> float:
        """
        Calculate hours since the persona's configured wake time.

        Uses the energy system's sleep schedule for accurate calculation.
        """
        return self._energy.hours_since_wake()

    def get_life_context(self, max_activities: int = 3, include_intimate: bool = True) -> str:
        """
        Get life context for system prompt.

        Returns formatted context section.
        """
        return self._context_builder.build_full_context(
            recent_activities=self._recent_activities[:max_activities],
            shareable=self._get_unshared_experiences()[:2],
            include_intimate=include_intimate,
            daily_plan=self._daily_planner.current_plan,
            desires=self._daily_planner.desires,
            life_events=self._life_events.get_unshared_events()[:2],
        )

    def get_response_style_hint(self) -> str:
        """Get response style hint based on energy."""
        return self._context_builder.get_response_style_hint()

    def set_pipeline(self, pipeline) -> None:
        """Set the pipeline service for digest generation."""
        self._pipeline = pipeline

    def assess_needs(self) -> dict:
        """Compute need satisfaction from existing engine state.

        Not persisted — derived on demand. Each need is 0.0–1.0
        (1.0 = fully satisfied). Returns dict of need dicts with
        'satisfaction' (float) and 'drivers' (list of strings).
        """
        needs = {}

        # Connection: loneliness (inverted) + social battery
        try:
            loneliness = self._affect.loneliness.level
            social_battery = self._social.social_battery.charge
            needs["connection"] = {
                "satisfaction": max(0.0, min(1.0, 1.0 - loneliness * 0.6 - (1.0 - social_battery) * 0.4)),
                "drivers": [],
            }
            if loneliness > 0.5:
                needs["connection"]["drivers"].append("lonely")
            if social_battery < 0.3:
                needs["connection"]["drivers"].append("socially drained")
        except Exception:
            needs["connection"] = {"satisfaction": 0.7, "drivers": []}

        # Autonomy: avoidance guilt (feeling forced) + external pressure
        try:
            drive_state = self._drive.export_state()
            avoidances = drive_state.get("avoidances", [])
            high_guilt = [a for a in avoidances if a.get("guilt", 0) > 0.4]
            stress_sources = self._affect.stress.sources if self._affect.stress.sources else []
            external_pressure = sum(1 for s in stress_sources if s not in ("self-imposed", "internal"))
            score = 1.0 - len(high_guilt) * 0.2 - external_pressure * 0.15
            needs["autonomy"] = {
                "satisfaction": max(0.0, min(1.0, score)),
                "drivers": [],
            }
            if high_guilt:
                needs["autonomy"]["drivers"].append("things feel forced")
            if external_pressure > 1:
                needs["autonomy"]["drivers"].append("external pressure")
        except Exception:
            needs["autonomy"] = {"satisfaction": 0.7, "drivers": []}

        # Competence: self-esteem + goal momentum
        try:
            esteem = self._identity.self_esteem.level
            goals = self._goal_engine.active_goals
            stagnant = sum(1 for g in goals if g.motivation_level < 0.3)
            score = esteem * 0.6 + (1.0 - min(1.0, stagnant * 0.3)) * 0.4
            needs["competence"] = {
                "satisfaction": max(0.0, min(1.0, score)),
                "drivers": [],
            }
            if esteem < 0.4:
                needs["competence"]["drivers"].append("low self-esteem")
            if stagnant > 0:
                needs["competence"]["drivers"].append("goals stalling")
        except Exception:
            needs["competence"] = {"satisfaction": 0.7, "drivers": []}

        # Safety: stress (inverted) + chaos events
        try:
            stress = self._affect.stress.level
            chaos_state = self._chaos.export_state()
            recent_chaos = len(chaos_state.get("today_events", []))
            score = 1.0 - stress * 0.6 - min(0.4, recent_chaos * 0.15)
            needs["safety"] = {
                "satisfaction": max(0.0, min(1.0, score)),
                "drivers": [],
            }
            if stress > 0.5:
                needs["safety"]["drivers"].append("stressed")
            if recent_chaos > 1:
                needs["safety"]["drivers"].append("chaotic day")
        except Exception:
            needs["safety"] = {"satisfaction": 0.7, "drivers": []}

        # Stimulation: curiosity level + growth edges
        try:
            drive_state = self._drive.export_state()
            curiosities = [c for c in drive_state.get("curiosities", []) if c.get("intensity", 0) > 0.3]
            growth_edges = drive_state.get("growth_edges", [])
            has_curiosity = len(curiosities) > 0
            has_growth = len(growth_edges) > 0
            score = 0.5 + (0.3 if has_curiosity else -0.2) + (0.2 if has_growth else -0.1)
            needs["stimulation"] = {
                "satisfaction": max(0.0, min(1.0, score)),
                "drivers": [],
            }
            if not has_curiosity:
                needs["stimulation"]["drivers"].append("nothing sparking interest")
            if not has_growth:
                needs["stimulation"]["drivers"].append("stuck in routine")
        except Exception:
            needs["stimulation"] = {"satisfaction": 0.7, "drivers": []}

        # Physical Comfort: hunger + energy + body comfort.
        # AI personas have no physical body, so this need must never surface —
        # gating it out at the source covers all three consumers at once
        # (inner_digest, inner_life directives, unmet-needs context section).
        if not self._is_ai:
            try:
                hunger = self._basic_needs.hunger
                energy = self._energy.effective_level
                comfort = self._body.comfort.level
                score = (1.0 - hunger) * 0.3 + energy * 0.4 + comfort * 0.3
                needs["physical_comfort"] = {
                    "satisfaction": max(0.0, min(1.0, score)),
                    "drivers": [],
                }
                if hunger > 0.6:
                    needs["physical_comfort"]["drivers"].append("hungry")
                if energy < 0.3:
                    needs["physical_comfort"]["drivers"].append("exhausted")
                if comfort < 0.4:
                    needs["physical_comfort"]["drivers"].append("uncomfortable")
            except Exception:
                needs["physical_comfort"] = {"satisfaction": 0.7, "drivers": []}

        return needs

    def export_inner_state(self) -> dict:
        """Structured dump of all Inner World engines for digest pass."""
        return {
            "identity": self._identity.export_state(),
            "drive": {
                "goals": self._goal_engine.export_state(),
                "plan": self._daily_planner.export_state(),
                "intimacy": self._desire_system.export_state(),
                **self._drive.export_state(),
            },
            "affect": {
                "energy": self._energy.export_state(),
                **self._affect.export_state(),
            },
            "cognitive": {
                "recent_activities": self._activity_engine.export_recent_state(
                    self._recent_activities
                ),
                "skills": {
                    name: round(sp.level, 3)
                    for name, sp in self._skills.items()
                },
                **self._cognitive.export_state(),
            },
            "shadow": self._shadow.export_state(),
            "sanity": self._sanity.export_state(),
            "memory_time": self._memory_time.export_state(),
            "continuity": self._continuity.export_state(),
            "character_evolution": self._character_evolution.export_state(),
            "chaos": self._chaos.export_state(),
            "life_events": self._life_events.export_state(),
            "needs": self.assess_needs(),
            "mental_health": self.mental_health_index(),
        }

    def export_outer_state(self) -> dict:
        """Structured dump of all Outer World engines for digest pass."""
        # Location profile for current location
        loc_key = self._world.current_location.lower().replace(" ", "_") if self._world.current_location else "home"
        loc_profile = self._location_registry.get(loc_key)
        location_export = {}
        if loc_profile:
            location_export = {
                "place_type": loc_profile.place_type,
                "familiarity": round(loc_profile.familiarity, 2),
                "source": loc_profile.source,
                "visit_count": loc_profile.visit_count,
            }
        state = {
            "world": {**self._world.export_state(), "location_detail": location_export},
            "body": {
                **self._body.export_state(),
            },
            "social": self._social.export_state(),
            "media": {
                "current_book": self._media.current_book,
                "book_progress": round(self._media.book_progress, 2),
                "current_show": self._media.current_show,
                "current_music": self._media.current_music_obsession,
            },
            "behavior": self._behavior.export_state(),
            "expression": self._expression.export_state(),
            "skills": self._skills_system.export_state(),
        }
        if not self._is_ai:
            # Physical-life state — only embodied (human) personas get hungry,
            # commute, earn/spend money, run real-world errands, or keep a physical
            # home. AI companions have none of these, so omitting the keys keeps them
            # out of the digest entirely.
            state["body"].update({
                "hunger": round(self._basic_needs.hunger, 2),
                "hunger_label": self._sustenance.hunger_label(),
                "meals_today": self._basic_needs.meals_today,
                "nutrition": round(self._basic_needs.nutrition, 2),
                "showered_today": self._basic_needs.showered_today,
                "morning_routine_done": self._basic_needs.morning_routine_done,
            })
            state.update({
                "room": {
                    "candle_lit": self._room_state.candle_lit,
                    "music_playing": self._room_state.music_playing,
                    "tidiness": round(self._room_state.tidiness, 2),
                    "comfort": round(self._room_state.comfort, 2),
                    "home_type": self._room_state.home_type,
                },
                "finance": self._finance.export_state(),
                "career": self._career.export_state(),
                "errands": self._errands.export_state(),
                "places": self._location.export_state(),
                "transport": self._transport.export_state(self._transit),
            })
        return state

    def on_user_message(self, text: str, detected_emotion: str = "", emotion_intensity: float = 0.0) -> None:
        """
        Called when user sends a message.

        - Adds social energy boost
        - Multi-engine conversation trigger dispatch
        - May generate conversation-based goal
        - Updates UserModel behavioral statistics
        """
        # Track live conversation activity so the autonomous tick won't drift her
        # to sleep mid-chat (sleep is a soft cap — see EnergySystem.should_sleep).
        _now = datetime.now()
        _prev_user_at = getattr(self, "_last_user_message_at", None)
        # Server-authoritative wake detection: if she was asleep when this
        # message arrived (and not mid-conversation), her first reply should
        # reflect being roused. is_asleep() is a no-op for AI personas.
        _was_in_conv = bool(
            _prev_user_at and (_now - _prev_user_at).total_seconds() < 20 * 60
        )
        self._woke_pending = self._energy.is_asleep(in_conversation=_was_in_conv, now_hour=self.persona_local_hour())
        # Advance the conversation-session state machine (drives the sign-off).
        self._session.on_user_message(_now, _prev_user_at)
        self._last_user_message_at = _now

        # Identity: track user interaction
        self._identity.update_from_user_message()

        # Expression: track connection and style
        self._expression.on_user_message()

        # Affect: meaningful social interaction
        self._affect.on_social_interaction(meaningful=True)

        # Social boost from interaction
        self._energy.add_social_boost()

        # Multi-engine conversation trigger dispatch
        text_lower = text.lower()
        triggered = set()  # Dedup (engine, trigger_type) pairs

        engine_dispatch = {
            "desire": self._desire_system,
            "affect": self._affect,
            "energy": self._energy,
            "cognitive": self._cognitive,
            "identity": self._identity,
            "drive": self._drive,
        }

        for keyword, triggers in CONVERSATION_KEYWORD_MAP.items():
            if keyword in text_lower:
                for engine_name, trigger_type in triggers:
                    pair = (engine_name, trigger_type)
                    if pair not in triggered:
                        triggered.add(pair)
                        engine = engine_dispatch.get(engine_name)
                        if engine:
                            engine.process_conversation_trigger(trigger_type)

        # Cognitive + MemoryTime: conversation engagement
        self._cognitive.on_user_message(text)
        self._shadow.on_user_message(text)
        self._memory_time.on_user_message(text)

        # Small chance to generate goal or desire from interesting topic
        # (Simplified - could use NLP for topic extraction)
        if len(text) > 50 and random.random() < 0.1:
            # Extract potential topic (very simplified)
            words = text.lower().split()
            interesting = [w for w in words if len(w) > 6 and w.isalpha()]
            if interesting:
                topic = random.choice(interesting)
                self._goal_engine.generate_goal_from_conversation(topic)
                self._daily_planner.generate_desire_from_conversation(topic)

        # UserModel: observe message for behavioral learning
        if self._user_model_provider is not None:
            try:
                um = self._user_model_provider(self._persona_id)
                um.observe_message(text, datetime.now(), detected_emotion, emotion_intensity)
            except Exception as exc:
                self._report_user_model_failure("observe_message", exc)

    def on_theater_conversation(self, other_name: str, tone: str = "neutral") -> None:
        """Apply residue from a persona-to-persona (theater) conversation.

        Routed by the theater router after a conversation ends. A meaningful
        social interaction nudges affect; tense conversations don't count as
        a positive social touch.
        """
        try:
            self._affect.on_social_interaction(meaningful=(tone != "tense"))
        except Exception as e:
            logger.warning(f"Theater affect residue failed: {e}")

        if tone == "positive":
            try:
                self._energy.add_social_boost()
            except Exception as e:
                logger.warning(f"Theater energy boost failed: {e}")

    def process_intimate_trigger(self, trigger_type: str) -> float:
        """
        Explicitly process an intimate conversation trigger.

        Returns the arousal change applied.
        """
        return self._desire_system.process_conversation_trigger(trigger_type)

    def increase_intimacy_openness(self, amount: float = 0.05) -> None:
        """Increase the persona's openness about intimate topics."""
        self._desire_system.increase_openness(amount)

    def get_shareable_experiences(self, limit: int = 3) -> List[ShareableExperience]:
        """Get experiences the persona wants to share."""
        unshared = self._get_unshared_experiences()
        return sorted(unshared, key=lambda x: x.priority, reverse=True)[:limit]

    def mark_experience_shared(self, experience_id: int) -> None:
        """Mark an experience as shared."""
        for exp in self._shareable_queue:
            if exp.id == experience_id:
                exp.shared = True
                exp.shared_at = datetime.now()
                break
        self._save_shareable()

    def apply_schedule_override(self, action: str) -> None:
        """
        Apply a schedule override from conversation (e.g. user said 'skip work').

        Parses the action string and delegates to the appropriate planner method.
        """
        action_lower = action.strip().lower()

        if any(w in action_lower for w in ["cancel work", "call off", "skip work", "no work", "day off"]):
            self._daily_planner.cancel_work_today()

        elif action_lower.startswith("go to ") or action_lower.startswith("move to "):
            location = action_lower.split("to ", 1)[1].strip()
            # Auto-register unknown locations from user
            slug = location.lower().replace(" ", "_")
            if slug not in self._location_registry:
                self._register_user_location(location)
            self._world.move_to(location)
            self._daily_planner.override_current_location(location)

        elif any(w in action_lower for w in ["stay home", "stay here", "stay in"]):
            self._daily_planner.stay_at_current_location()

        else:
            # Generic location move: try to extract a location name
            for key in self._persona_locations:
                if key.lower() in action_lower:
                    self._world.move_to(key.lower())
                    self._daily_planner.override_current_location(key.lower())
                    break

        # Persist the updated plan
        self._save_plan()
        logger.info(f"Applied schedule override: {action}")

    def schedule_meeting_arrival(self, location: str) -> None:
        """Update activity, schedule and world location when the persona arrives for a planned meeting."""
        self._world.move_to(location)
        self._daily_planner.schedule_rendezvous(location)
        self._save_plan()
        logger.info(f"Meeting arrival applied: now at {location}")

    def add_conversation_plan(self, raw: str) -> None:
        """
        Commit a FUTURE plan agreed in conversation to today's schedule.

        `raw` is the inside of a [PLAN: ...] tag, formatted as
        ``HH:MM <what>`` with an optional trailing location
        (``<what> @ <location>`` or ``<what> at <location>``).

        Examples:
            "23:00 meet user at the park"  -> 23:00, "meet user", loc "the park"
            "19:00 cook dinner together"   -> 19:00, "cook dinner together", no loc
            "15:00 pilates @ studio"       -> 15:00, "pilates", loc "studio"

        Validates HH:MM (00:00–23:59). If the time can't be parsed, logs a
        warning and returns without mutating the plan (never crashes the path).

        Minutes are accepted/validated for format leniency, but the planner's
        slot granularity is hourly — "19:30" and "19:00" both commit to hour 19.
        """
        text = (raw or "").strip()
        m = re.match(r'^(\d{1,2}):(\d{2})\b\s*(.*)$', text)
        if not m:
            logger.warning(f"add_conversation_plan: no HH:MM time in {raw!r}; ignoring")
            return

        hour = int(m.group(1))
        minute = int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            logger.warning(f"add_conversation_plan: out-of-range time in {raw!r}; ignoring")
            return

        what = m.group(3).strip()
        if not what:
            logger.warning(f"add_conversation_plan: no activity in {raw!r}; ignoring")
            return

        # Optional trailing location: "<what> @ <loc>" or "<what> at <loc>".
        location = ""
        loc_split = re.split(r'\s+(?:@|\bat\b)\s+', what, maxsplit=1)
        if len(loc_split) == 2 and loc_split[1].strip():
            what = loc_split[0].strip()
            location = loc_split[1].strip()

        if not what:
            logger.warning(f"add_conversation_plan: empty activity after location split in {raw!r}; ignoring")
            return

        # Auto-register an unknown user-named location so the world/planner can use it.
        if location:
            slug = location.lower().replace(" ", "_")
            if slug not in self._location_registry:
                try:
                    self._register_user_location(location)
                except Exception as e:
                    logger.debug(f"add_conversation_plan: could not register location {location!r}: {e}")

        self._daily_planner.set_planned_activity(
            hour=hour,
            activity_name=what,
            location=location,
            reason="agreed with user",
        )
        self._save_plan()
        logger.info(f"Conversation plan added: {hour:02d}:{minute:02d} -> hour {hour:02d} — {what}" + (f" @ {location}" if location else ""))

    # ============= Transit System =============

    @property
    def transit(self) -> Optional[TransitState]:
        """Current active transit state, or None."""
        return self._transit

    def begin_transit(self, destination: str, reason: str = "", total_minutes: Optional[int] = None) -> None:
        """Start the transit state machine: PREPARING → IN_TRANSIT → ARRIVED.

        Creates a DEPARTURE trigger so the 1-minute checker advances to IN_TRANSIT.
        If total_minutes < PREP_TIME_MINUTES, skips PREPARING and goes straight to IN_TRANSIT.
        """
        # AI personas have no physical body and never travel — no commute, no
        # transit state machine, no travel-time estimation.
        if self._is_ai:
            return
        origin = self._world.current_location or "home"

        # Already there — nothing to do
        if origin == destination:
            logger.info(f"Transit skipped: already at {destination}")
            return

        now = datetime.now()

        # Transportation engine: estimate the trip (travel time, mode, arrival).
        est = self._transport.estimate(destination, total_minutes, now)
        total_minutes = est["total_minutes"]
        expected_arrival = est["expected_arrival"]

        # Short trip: skip PREPARING, go straight to IN_TRANSIT
        if est["skip_prep"]:
            self._transit = TransitState(
                phase=TransitPhase.IN_TRANSIT,
                origin=origin,
                destination=destination,
                reason=reason,
                departure_at=now,
                expected_arrival_at=expected_arrival,
            )
            self._world.move_to("in transit")
            logger.info(
                f"Transit started (short trip, skipped prep): "
                f"{origin} → {destination}, ETA {total_minutes}min"
            )
        else:
            self._transit = TransitState(
                phase=TransitPhase.PREPARING,
                origin=origin,
                destination=destination,
                reason=reason,
                preparing_started_at=now,
                expected_arrival_at=expected_arrival,
            )

            # Create DEPARTURE trigger so the 1-minute checker fires it
            if self._follow_up_provider is not None:
                try:
                    follow_ups = self._follow_up_provider(self._persona_id)
                    follow_ups.create_trigger(
                        "DEPARTURE",
                        topic=destination,
                        context=f"transit_depart:{destination}",
                        urgency=0.95,
                        emotional_weight=0.1,
                        delay_hours=PREP_TIME_MINUTES / 60.0,
                    )
                except Exception as e:
                    logger.warning(f"Failed to create DEPARTURE trigger: {e}")

            logger.info(
                f"Transit started (preparing): {origin} → {destination}, "
                f"depart in {PREP_TIME_MINUTES}min, arrive in {total_minutes}min"
            )

        self._save_transit()

    def advance_transit_phase(self, to_phase: TransitPhase) -> None:
        """Advance the transit state machine to the next phase."""
        if not self._transit:
            logger.warning("advance_transit_phase called but no active transit")
            return

        now = datetime.now()

        if to_phase == TransitPhase.IN_TRANSIT:
            self._transit.phase = TransitPhase.IN_TRANSIT
            self._transit.departure_at = now
            self._world.move_to("in transit")
            logger.info(f"Transit phase → IN_TRANSIT: heading to {self._transit.destination}")

        elif to_phase == TransitPhase.ARRIVED:
            self._transit.phase = TransitPhase.ARRIVED
            self._transit.arrived_at = now
            self._world.move_to(self._transit.destination)
            self._daily_planner.schedule_rendezvous(self._transit.destination)
            self._save_plan()
            logger.info(f"Transit phase → ARRIVED: at {self._transit.destination}")

        self._save_transit()

    def clear_transit(self) -> None:
        """Clear active transit state."""
        if self._transit:
            logger.info(f"Transit cleared (was {self._transit.phase.value} → {self._transit.destination})")
        self._transit = None
        self._save_transit()

    def _save_transit(self) -> None:
        """Persist transit state to DB."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            if self._transit:
                data = self._transit.to_dict()
                cursor.execute("""
                    INSERT OR REPLACE INTO life_transit_state
                    (id, phase, origin, destination, reason,
                     preparing_started_at, departure_at, expected_arrival_at, arrived_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["phase"], data["origin"], data["destination"], data["reason"],
                    data["preparing_started_at"], data["departure_at"],
                    data["expected_arrival_at"], data["arrived_at"],
                ))
            else:
                cursor.execute("DELETE FROM life_transit_state WHERE id = 1")
            conn.commit()

    def _load_transit(self, cursor) -> None:
        """Load transit state from DB. Fast-forward past arrivals."""
        try:
            cursor.execute("SELECT * FROM life_transit_state WHERE id = 1")
            row = cursor.fetchone()
            if not row:
                return
            data = dict(row)
            self._transit = TransitState.from_dict(data)

            # Fast-forward: if expected arrival is in the past, complete the transit
            if self._transit.expected_arrival_at and self._transit.expected_arrival_at < datetime.now():
                logger.info(
                    f"Transit fast-forward: arrival at {self._transit.destination} was past due"
                )
                self._transit.phase = TransitPhase.ARRIVED
                self._transit.arrived_at = self._transit.expected_arrival_at
                self._world.move_to(self._transit.destination)
                self.clear_transit()
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    # ------------------------------------------------------------------
    # Place-identity state persistence
    # ------------------------------------------------------------------

    def _save_place_state(self) -> None:
        """Persist place-identity volatile state (current city / trip / weather) to DB."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._place_location.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_location_state
                (id, current_city, current_lat, current_lon, current_timezone,
                 on_trip, trip_destination, trip_returns_at, trip_reason,
                 weather_code, weather_label, weather_temp_c, weather_is_day,
                 weather_fetched_at, weather_source, trip_last_roll_date)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["current_city"], data["current_lat"], data["current_lon"],
                data["current_timezone"],
                data["on_trip"], data["trip_destination"], data["trip_returns_at"],
                data["trip_reason"],
                data["weather_code"], data["weather_label"], data["weather_temp_c"],
                data["weather_is_day"], data["weather_fetched_at"], data["weather_source"],
                self._trip_last_roll_date,
            ))
            conn.commit()

    def _load_place_state(self, cursor) -> None:
        """Load place-identity volatile state from DB.

        Also handles catch-up: if a trip's ``trip_returns_at`` is in the past
        (server was offline while she was supposed to be returning home), revert
        her current location back to home immediately so she is never stuck away.
        """
        try:
            cursor.execute("SELECT * FROM life_location_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._place_location = PlaceLocationState.from_dict(dict(row))
                row_dict = dict(row)
                self._trip_last_roll_date = row_dict.get("trip_last_roll_date", "") or ""
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet (older DBs)

        # Catch-up: revert an overdue trip so we never resume "stuck" away.
        # We update only the in-memory state here; the DB write is deferred so we
        # don't open a second connection while the caller's cursor is still open.
        pl = self._place_location
        if pl.on_trip and pl.trip_returns_at:
            from datetime import datetime
            needs_revert = False
            try:
                needs_revert = datetime.now() >= datetime.fromisoformat(pl.trip_returns_at)
            except ValueError:
                needs_revert = True  # Malformed timestamp — clear defensively.
            if needs_revert:
                self._revert_to_home_in_memory()
                # Mark for a deferred DB write (done in _load_state after the cursor closes).
                self._trip_catchup_pending_save = True

    # ------------------------------------------------------------------
    # Real weather integration
    # ------------------------------------------------------------------

    def _place_enabled(self) -> bool:
        """Whether the host has place features enabled. Unreadable config means no.

        This is a kill switch, so it fails **closed**. The check used to sit
        inside a ``try`` whose ``except Exception`` was a bare ``pass``, which
        meant ``HookNotConfigured`` — the state of every host that has not
        registered ``get_config``, i.e. the default — fell through and ran the
        feature as though the flag were on.
        """
        try:
            from aura_life.hooks import get_config
            return bool(get_config().place_enabled)
        except Exception:
            logger.debug(
                "place_enabled is unreadable — treating place features as disabled",
                exc_info=True,
            )
            return False

    def _get_weather_service(self):
        """Return the WeatherService instance (lazy-init singleton unless overridden)."""
        if self._weather_service_override is not None:
            return self._weather_service_override
        from aura_life.hooks import get_weather_service
        return get_weather_service()

    def _update_weather(self) -> None:
        """Fetch real weather and override the World sim when available.

        No-op for AI personas, personas without a known lat/lon, for a persona
        sharing a World it does not own, or when the host's injected config
        reports ``place_enabled`` false (``aura_life.hooks.get_config()``).
        That gate is config, not an environment variable: nothing on this path
        consults ``os.environ``. Whether a real reading exists at all is the
        host's ``get_weather_service()`` hook's call — it returns None when it
        has nothing, and the World engine's existing Markov-simulated weather is
        the fallback, never reset here on failure.
        """
        # Master place flag — when place is fully disabled, weather is too.
        if not self._place_enabled():
            return
        # Shared-world personas don't own the World object; skip to avoid last-writer-wins races.
        if getattr(self, "_shared_world", False):
            return
        if self._is_ai:
            return
        lat = self._place_location.current_lat
        lon = self._place_location.current_lon
        if lat is None or lon is None:
            return

        svc = self._get_weather_service()
        reading = svc.get_current(lat, lon)
        if reading is None:
            # Simulated fallback; if we previously had a real reading, clear it so
            # a restart doesn't serve stale real data via get_current_weather().
            if self._place_location.weather_source != "simulated":
                self._place_location.weather_source = "simulated"
                self._place_location.weather_code = None  # clear stale real reading
                self._save_place_state()
            return

        # Map WMO code → Weather enum, then override the World engine
        from aura_life.world.environment import wmo_to_world_weather
        weather_enum = wmo_to_world_weather(reading, local_hour=self.persona_local_hour())
        self._world._state.weather = weather_enum

        # Persist the raw reading into place_location
        self._place_location.weather_code = reading["code"]
        self._place_location.weather_label = reading["label"]
        self._place_location.weather_temp_c = reading["temp_c"]
        self._place_location.weather_is_day = reading.get("is_day", True)
        self._place_location.weather_fetched_at = reading.get("fetched_at", "")
        self._place_location.weather_source = reading.get("source", "open-meteo")
        self._save_place_state()

    # ------------------------------------------------------------------
    # Travel / trip lifecycle
    # ------------------------------------------------------------------

    def _trip_enabled(self) -> bool:
        """Return True when the trip feature is globally enabled."""
        import os
        return os.environ.get("AURA_TRIP_ENABLED", "true").lower() not in ("0", "false", "no")

    def _trip_daily_chance(self) -> float:
        """Return the per-day probability of starting a trip (default 0.01)."""
        import os
        try:
            return float(os.environ.get("AURA_TRIP_DAILY_CHANCE", "0.01"))
        except ValueError:
            return 0.01

    def _trip_duration_range(self) -> tuple[int, int]:
        """Return (min_days, max_days) for a trip's length.

        Defaults to a real "trip abroad" span of about one to just-over-two weeks
        (5–16 days), not a long-weekend. Override with AURA_TRIP_MIN_DAYS /
        AURA_TRIP_MAX_DAYS. Min is clamped >= 1 and max >= min.
        """
        import os
        try:
            lo = int(os.environ.get("AURA_TRIP_MIN_DAYS", str(TRIP_MIN_DAYS)))
        except ValueError:
            lo = TRIP_MIN_DAYS
        try:
            hi = int(os.environ.get("AURA_TRIP_MAX_DAYS", str(TRIP_MAX_DAYS)))
        except ValueError:
            hi = TRIP_MAX_DAYS
        lo = max(1, lo)
        hi = max(lo, hi)
        return lo, hi

    def _get_trip_llm(self):
        """Return the LLM client to use for trip destination selection."""
        if self._trip_llm_override is not None:
            return self._trip_llm_override
        # Lazy-import to avoid circular deps; use the same singleton as the pipeline.
        try:
            from aura_life.hooks import get_llm_service
            return get_llm_service()
        except Exception:
            return None

    def _geocode_trip(self, city_name: str) -> Optional[dict]:
        """Geocode a trip destination city; injectable for tests."""
        if self._trip_geocode_override is not None:
            return self._trip_geocode_override(city_name)
        from aura_life.hooks import geocode
        return geocode(city_name)

    def _pick_trip_destination(self) -> Optional[dict]:
        """Ask the LLM to suggest a plausible trip destination.

        Returns a dict with keys ``city``, ``lat``, ``lon``, ``timezone``, ``reason``
        or None on any failure (safe-fail).
        """
        home_city = self._place_location.current_city or ""
        definition = self._definition
        nationality = getattr(definition, "nationality", "") or "" if definition else ""
        interests = getattr(definition, "interests", []) or [] if definition else []

        llm = self._get_trip_llm()
        if llm is None:
            return None

        prompt = (
            f"You are helping plan a trip abroad for a person "
            f"{'from ' + nationality + ' ' if nationality else ''}"
            f"who currently lives in '{home_city}'. "
            f"Their interests include: {', '.join(interests[:4]) or 'travel'}.\n"
            "Suggest ONE plausible international trip destination — a real city in a "
            "DIFFERENT COUNTRY from where they live, the kind of place someone would "
            "go for a one-to-two-week trip. "
            "Reply with ONLY a JSON object, no markdown, no commentary:\n"
            '{"city": "<City, Country>", "reason": "<one short sentence why they are going>"}'
        )

        try:
            raw = llm.generate(prompt)
            import json
            import re
            # Strip markdown fences if present
            raw = re.sub(r"```[a-z]*\n?", "", raw or "").strip()
            data = json.loads(raw)
            city_str = data.get("city") or ""
            reason = data.get("reason") or "a short trip"
            if not city_str:
                return None
        except Exception:
            return None

        geo = self._geocode_trip(city_str)
        if geo is None:
            return None

        return {
            "city": geo["city"],
            "lat": geo["lat"],
            "lon": geo["lon"],
            "timezone": geo.get("timezone", ""),
            "reason": reason,
        }

    def _update_trip(self, _now=None, _rng=None) -> None:
        """Manage the trip lifecycle: start, while-on-trip, and return.

        Called from ``_on_world_tick``; mirrors the safe-fail / guard pattern of
        ``_update_weather``.  All side effects go through ``_save_place_state``.

        Args:
            _now: injectable datetime for tests (default: datetime.now()).
            _rng: injectable random.Random instance for tests.
        """
        # Master place flag — when place is fully disabled, trips are too.
        if not self._place_enabled():
            return
        # Shared-world personas don't own the world state.
        if getattr(self, "_shared_world", False):
            return
        # AI personas never travel.
        if self._is_ai:
            return
        # Feature flag gate.
        if not self._trip_enabled():
            return

        from datetime import datetime, timedelta
        import random as _random_mod

        rng = _rng if _rng is not None else _random_mod
        now = _now if _now is not None else datetime.now()
        pl = self._place_location

        # --- Return check (runs even while on trip) ---
        if pl.on_trip and pl.trip_returns_at:
            try:
                returns_at = datetime.fromisoformat(pl.trip_returns_at)
                if now >= returns_at:
                    self._end_trip()
                    return
            except ValueError:
                # Malformed timestamp — clear the trip to avoid being stuck.
                self._end_trip()
                return

        # --- Start check (not already on a trip) ---
        if pl.on_trip:
            return  # still travelling; nothing more to do

        # Per-day gate: at most one roll per calendar date.
        today_str = now.strftime("%Y-%m-%d")
        if self._trip_last_roll_date == today_str:
            return

        self._trip_last_roll_date = today_str

        chance = self._trip_daily_chance()
        if rng.random() >= chance:
            return  # not today

        dest = self._pick_trip_destination()
        if dest is None:
            return  # LLM/geocode failed — safe-fail, no trip

        _lo, _hi = self._trip_duration_range()
        duration_days = rng.randint(_lo, _hi)
        returns_at = now + timedelta(days=duration_days)

        # Store home's current values before overwriting (they are already in home_* on
        # the definition; current_* reverts to them on return so no extra store needed).
        pl.on_trip = True
        pl.trip_destination = dest["city"]
        pl.trip_returns_at = returns_at.isoformat()
        pl.trip_reason = dest["reason"]
        # Switch current location to destination — weather + tz follow automatically.
        pl.current_city = dest["city"]
        pl.current_lat = dest["lat"]
        pl.current_lon = dest["lon"]
        pl.current_timezone = dest["timezone"]
        # Reset stale weather from home so we don't serve home weather at the destination.
        pl.weather_code = None
        pl.weather_label = ""
        pl.weather_temp_c = None
        pl.weather_source = "simulated"
        self._save_place_state()

    def _revert_to_home_in_memory(self) -> None:
        """Update in-memory place_location back to home values (does NOT persist)."""
        pl = self._place_location
        definition = self._definition
        home_city = getattr(definition, "home_city", "") or "" if definition else ""
        home_lat = getattr(definition, "home_lat", None) if definition else None
        home_lon = getattr(definition, "home_lon", None) if definition else None
        home_tz = getattr(definition, "home_timezone", "") or "" if definition else ""

        pl.on_trip = False
        pl.trip_destination = ""
        pl.trip_returns_at = ""
        pl.trip_reason = ""
        pl.current_city = home_city
        pl.current_lat = home_lat
        pl.current_lon = home_lon
        pl.current_timezone = home_tz
        # Reset stale destination weather.
        pl.weather_code = None
        pl.weather_label = ""
        pl.weather_temp_c = None
        pl.weather_source = "simulated"

    def _end_trip(self) -> None:
        """Revert current_* to home, clear the trip overlay, and persist."""
        self._revert_to_home_in_memory()
        self._save_place_state()

    def get_current_weather(self) -> dict:
        """Return the effective current weather.

        When real weather has been fetched (source != 'simulated' and code is set),
        returns the raw reading fields plus the mapped Weather enum value.
        Otherwise returns the World engine's simulated weather.

        Shape::

            # real
            {"code": int, "label": str, "temp_c": float, "is_day": bool,
             "source": "open-meteo", "weather_enum": str}
            # simulated
            {"label": str, "source": "simulated", "weather_enum": str}
        """
        pl = self._place_location
        if pl.weather_source != "simulated" and pl.weather_code is not None:
            return {
                "code": pl.weather_code,
                "label": pl.weather_label,
                "temp_c": pl.weather_temp_c,
                "is_day": pl.weather_is_day,
                "source": pl.weather_source,
                "weather_enum": self._world.weather.value,
            }
        return {
            "label": self._world.weather.value,
            "source": "simulated",
            "weather_enum": self._world.weather.value,
        }

    def resume_planned_activity(self) -> None:
        """Resume the current planned activity after a conversation concludes.

        Syncs world location to the current plan slot so the persona returns
        to what she was supposed to be doing (commuting, attending classes, etc.).
        Also immediately re-evaluates the visual transition so descriptions update.
        """
        plan = self._daily_planner.current_plan
        if not plan:
            return

        slot = plan.get_current_slot()
        if not slot or slot.completed:
            return

        planned_location = slot.location or "home"
        if self._world.current_location != planned_location:
            self._world.move_to(planned_location)
            logger.info(
                f"Resumed planned activity: '{slot.activity_name}' at {planned_location}"
            )
        # Force visual transition check so description updates immediately
        self._check_visual_transition()

    def get_recent_activities(self, limit: int = 10) -> List[ActivityLog]:
        """Get recent activity logs."""
        return self._recent_activities[:limit]

    def get_active_goals(self) -> List[Goal]:
        """Get active goals."""
        return self._goal_engine.active_goals

    # Emoji lookup for planner activity names → status bar display
    _ACTIVITY_EMOJI: Dict[str, str] = {
        "sleeping": "😴", "napping": "😴",
        "relaxing": "😌", "resting": "😪",
        "reading": "📖",
        "cooking": "🍳", "baking": "🍳",
        "eating": "🍽️", "having breakfast": "🍽️", "having lunch": "🍽️", "having dinner": "🍽️",
        "working": "💻", "studying": "💻",
        "gaming": "🎮", "playing games": "🎮",
        "watching tv": "📺", "watching a movie": "📺", "watching": "📺",
        "listening to music": "🎧",
        "exercising": "🏃", "working out": "🏃", "running": "🏃",
        "yoga": "🧘", "meditating": "🧘", "stretching": "🧘",
        "drawing": "🎨", "painting": "🎨", "crafting": "🎨", "creating": "🎨",
        "writing": "✍️", "journaling": "✍️",
        "walking": "🚶", "going for a walk": "🚶",
        "shopping": "🛍️",
        "cleaning": "🧹", "tidying up": "🧹",
        "gardening": "🌱",
        "chatting": "💬", "texting": "💬",
        "exploring": "🔍",
        "daydreaming": "💭", "thinking": "🤔",
    }

    def _emoji_for_activity(self, name: str) -> str:
        """Get an emoji for an activity name, with fuzzy keyword fallback."""
        lower = name.lower()
        # Exact match
        if lower in self._ACTIVITY_EMOJI:
            return self._ACTIVITY_EMOJI[lower]
        # Keyword match
        for keyword, emoji in self._ACTIVITY_EMOJI.items():
            if keyword in lower or lower in keyword:
                return emoji
        return "✨"

    def get_current_location(self) -> str:
        """Get current location from the daily planner (single source of truth).

        The planner slot's location is authoritative. The world engine is
        kept in sync as a side effect.  Falls back to 'home' only when no
        plan exists yet.
        """
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot()
            if slot and slot.location:
                # Keep world engine in sync with planner
                if self._world.current_location != slot.location:
                    self._world.move_to(slot.location)
                return slot.location.replace("_", " ")
        return "home"

    @staticmethod
    def _weather_mood_enabled() -> bool:
        """Gate check for weather → mood nudge. Read at call time so
        tests can monkeypatch os.environ without reloading the module."""
        import os as _os
        return _os.environ.get("AURA_WEATHER_MOOD_ENABLED", "true").lower() in ("true", "1", "yes")

    @staticmethod
    def _mood_to_valence(label: str, intensity: float) -> float:
        """Map a mood label + intensity to a 0..1 valence (1 = good, 0 = bad).

        Single source of truth shared by the Shadow tick and the mental-health
        read-out so the two never drift apart.
        """
        if label == "content":
            return 0.5 + 0.5 * intensity
        if label == "blue":
            return 0.5 - 0.5 * intensity
        if label in ("restless", "raw"):
            return 0.5 - 0.3 * intensity
        return 0.5

    def mental_health_index(self) -> dict:
        """Derived mental-health / wellness read-out (no stored state, no tick).

        Aggregates existing engine scalars into a single 0..1 wellness score
        (1 = thriving, 0 = in a dark place). Pure observer: reads sub-engine
        status, never mutates. Returns {"score", "label", "drivers"} where
        drivers names the 1-3 biggest negative contributors.
        """
        components: dict = {}
        # --- Affect: mood (higher=better), stress + loneliness (inverted) ---
        try:
            mood_valence = self._mood_to_valence(
                self._affect.mood.current_mood, self._affect.mood.intensity
            )
            stress = max(0.0, min(1.0, self._affect.stress.level))
            loneliness = max(0.0, min(1.0, self._affect.loneliness.level))
        except Exception:
            mood_valence, stress, loneliness = 0.5, 0.0, 0.0
        components["mood"] = max(0.0, min(1.0, mood_valence))
        components["calm"] = 1.0 - stress
        components["connected"] = 1.0 - loneliness

        # --- Shadow: unease / shame / guilt (inverted) ---
        try:
            sh = self._shadow.get_status()
            unease = max(0.0, min(1.0, float(sh.get("unease", 0.0))))
            shame = max(0.0, min(1.0, float(sh.get("shame", 0.0))))
            guilt = max(0.0, min(1.0, float(sh.get("guilt", 0.0))))
        except Exception:
            unease = shame = guilt = 0.0
        components["at_ease"] = 1.0 - unease
        components["unashamed"] = 1.0 - shame
        components["guilt_free"] = 1.0 - guilt

        # --- Body: overall wellness (higher=better) ---
        try:
            wellness = max(0.0, min(1.0, float(self._body.get_status().get("wellness", 0.7))))
        except Exception:
            wellness = 0.7
        components["wellbeing"] = wellness

        # --- Weighted aggregate ---
        # Affect carries the most weight (mood/stress/loneliness are the
        # day-to-day drivers); shadow and body shade it.
        weights = {
            "mood": 2.0,
            "calm": 1.5,
            "connected": 1.5,
            "at_ease": 1.0,
            "unashamed": 1.0,
            "guilt_free": 1.0,
            "wellbeing": 1.0,
        }
        total_w = sum(weights.values())
        score = sum(components[k] * weights[k] for k in weights) / total_w
        score = max(0.0, min(1.0, score))

        # --- Label bands ---
        if score >= 0.7:
            label = "thriving"
        elif score >= 0.5:
            label = "okay"
        elif score >= 0.35:
            label = "struggling"
        else:
            label = "in a dark place"

        # --- Drivers: the 1-3 biggest negatives, in plain language ---
        negatives = [
            (stress, "high stress"),
            (loneliness, "lonely"),
            (guilt, "heavy guilt"),
            (shame, "shame"),
            (unease, "uneasy"),
            (1.0 - wellness, "unwell"),
            # Mood only counts as a driver when it's genuinely below neutral
            # (valence < 0.5). A neutral mood (valence 0.5) is the absence of a
            # negative, not a negative itself, so it must not be flagged.
            ((0.5 - components["mood"]) * 2.0 if components["mood"] < 0.5 else 0.0, "low mood"),
        ]
        drivers = [name for value, name in sorted(negatives, reverse=True) if value >= 0.4][:3]

        return {"score": round(score, 3), "label": label, "drivers": drivers}

    def get_status(self) -> dict:
        """Get full life system status."""
        # Current activity from planner (flat fields for Android status bar).
        # A recent [DOING:] tag overrides the scheduled slot within its window so
        # the status bar reflects what she's actually doing in the conversation.
        current_activity = None
        current_activity_emoji = None
        _scheduled_act = ""
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot()
            if slot:
                _scheduled_act = slot.activity_name
        _effective_act = self.effective_current_activity(_scheduled_act)
        if _effective_act:
            current_activity = _effective_act.capitalize()
            current_activity_emoji = self._emoji_for_activity(_effective_act)

        current_location = self.get_current_location()

        # Energy as descriptive string
        energy = self._energy.get_status()
        energy_level_val = energy.get("level", 0.5)
        if energy_level_val >= 0.7:
            energy_level = "high"
        elif energy_level_val >= 0.4:
            energy_level = "medium"
        else:
            energy_level = "low"

        status = {
            # Flat fields consumed by Android LifeStatus
            "current_activity": current_activity,
            "current_activity_emoji": current_activity_emoji,
            "energy_level": energy_level,
            "location": current_location,
            "location_type": self._location_registry[current_location.lower().replace(" ", "_")].place_type if current_location.lower().replace(" ", "_") in self._location_registry else "other",
            "locations_visited_today": len(self._locations_visited_today),
            "consecutive_home_hours": self._consecutive_home_ticks,
            # Detailed nested data (for debugging / future use)
            "world": self._world.get_status(),
            "energy": energy,
            "desire": self._desire_system.get_status(),
            "goals": self._goal_engine.get_status(),
            "planner": {
                "has_plan": self._daily_planner.current_plan is not None,
                "plan_date": self._daily_planner.current_plan.date if self._daily_planner.current_plan else None,
                "active_desires": len(self._daily_planner.desires),
                "schedule": self._daily_planner.get_schedule_summary(),
            },
            "scheduler": self._scheduler.get_status(),
            "recent_activities_count": len(self._recent_activities),
            "shareable_count": len(self._get_unshared_experiences()),
            "media": {
                "current_book": self._media.current_book,
                "book_progress": round(self._media.book_progress, 2),
                "books_finished": len(self._media.books_finished),
                "current_show": self._media.current_show,
                "current_music_obsession": self._media.current_music_obsession,
            },
            "skills": {
                name: round(sp.level, 3)
                for name, sp in self._skills.items()
            },
            "social": self._social.get_status(),
            "identity": self._identity.get_status(),
            "affect": self._affect.get_status(),
            "body": self._body.get_status(),
            "cognitive": self._cognitive.get_status(),
            "shadow": self._shadow.get_status(),
            "sanity": self._sanity.get_status(),
            "mental_health": self.mental_health_index(),
            "drive": self._drive.get_status(),
            "behavior": self._behavior.get_status(),
            "memory_time": self._memory_time.get_status(),
            "expression": self._expression.get_status(),
            "continuity": self._continuity.get_status(),
            "character_evolution": self._character_evolution.get_status(),
            "chaos": self._chaos.get_status(),
            "life_events": self._life_events.get_status(),
            "pipeline": self._pipeline.get_status() if self._pipeline else {"enabled": False},
            "transit": self._transit.to_dict() if self._transit else None,
        }
        if not self._is_ai:
            # Physical-life subsystems — only embodied (human) personas eat, keep a
            # physical home, earn/spend, run errands, visit places, or commute. Keep
            # these out of the AI status payload entirely (defense-in-depth).
            status.update({
                "needs": {
                    "hunger": round(self._basic_needs.hunger, 2),
                    "hunger_label": self._sustenance.hunger_label(),
                    "meals_today": self._basic_needs.meals_today,
                    "nutrition": round(self._basic_needs.nutrition, 2),
                    "showered_today": self._basic_needs.showered_today,
                    "morning_routine_done": self._basic_needs.morning_routine_done,
                },
                "room": {
                    "candle_lit": self._room_state.candle_lit,
                    "music_playing": self._room_state.music_playing,
                    "tidiness": round(self._room_state.tidiness, 2),
                    "comfort": round(self._room_state.comfort, 2),
                    "home_type": self._room_state.home_type,
                },
                "finance": self._finance.get_status(),
                "career": self._career.get_status(),
                "errands": self._errands.get_status(),
                "places": self._location.get_status(),
                "transport": self._transport.get_status(self._transit),
            })
        return status

    # ============= Tick Handlers =============

    def _reset_visual_moment(self) -> None:
        """Drop the transient self-photo "moment" override on a new day so she
        returns to profile-default looks. Safe no-op on any failure."""
        if not self._persona_id:
            return
        try:
            from aura_life.hooks import get_image_service
            get_image_service().clear_current_description(self._persona_id)
        except Exception:
            pass

    def _on_plan_tick(self) -> None:
        """Handle plan tick - generate daily plan if needed."""
        if self._daily_planner.needs_new_plan():
            # Reset daily flags for new day
            self._basic_needs.showered_today = False
            self._basic_needs.morning_routine_done = False
            self._sustenance.reset_daily()
            self._room_state.candle_lit = False
            self._room_state.music_playing = False
            self._body.on_new_day()
            self._reset_visual_moment()

            # Rotate music obsession every few days
            if random.random() < 0.2:
                music = self._media_preferences.get("music", [])
                if music:
                    self._media.current_music_obsession = random.choice(music)

            self._daily_planner.generate_daily_plan(
                goals=self._goal_engine.active_goals,
                weather=self._world.weather,
                available_activities=self._activity_engine.get_all_activities(),
                recent_activity_names=[a.activity_name for a in self._recent_activities[:5]],
                work_schedule=self._career_schedule(),
            )
            self._save_plan()
            logger.info("Generated new daily plan")
        else:
            # Silently revise upcoming slots if conditions changed
            self._daily_planner.revise_upcoming(
                weather=self._world.weather,
                energy_level=self._energy.effective_level,
                mood=self._affect.mood.current_mood if self._affect else "",
                mood_intensity=self._affect.mood.intensity if hasattr(self._affect.mood, 'intensity') else 0,
            )

    def _on_world_tick(self) -> None:
        """Handle world tick. Skips if world is externally managed (shared)."""
        if not self._shared_world:
            self._world.tick()
            logger.debug(f"World tick: {self._world.weather.value}, {self._world.time_of_day.value}")
        # Real weather override — runs whether or not the world was ticked here,
        # because the persona's location state may have changed independently.
        self._update_weather()
        # Trip lifecycle — per-day roll; return check on every tick.
        self._update_trip()

    def _on_energy_tick(self) -> None:
        """Handle energy tick."""
        self._energy.tick(self._world.time_of_day)
        self._desire_system.tick(self._world.time_of_day, self._world.weather)
        self._identity.tick()

        # Tick behavioral tendencies with cross-engine state
        self._identity.tick_tendencies(
            stress=self._affect.stress.level,
            loneliness=self._affect.loneliness.level,
            energy_level=self._energy.state.effective_level,
            stimulation_need=getattr(self._drive, '_stimulation_need', 0.5) if self._drive else 0.5,
            mood=self._affect.mood.current_mood if self._affect else "neutral",
        )

        # Route struggle effects to affect/cognitive
        for struggle in self._identity.get_pending_struggle_effects():
            self._affect.on_stressor_added(f"struggle:{struggle}")
            if self._random.random() < 0.5:
                self._cognitive.on_conflict(struggle)

        # === Physical-life engines (humans only — an AI doesn't eat or keep a home) ===
        if not self._is_ai:
            # Sustenance: hunger / nutrition
            self._sustenance.tick()
            if self._sustenance.hunger > 0.7:  # high hunger drains energy
                self._energy._state.level = max(0.1, self._energy._state.level - 0.01)
            # Habitation: living space
            self._habitation.tick(self._world.time_of_day)
            if self._habitation.comfort < 0.35:  # a bleak, messy space is a mild stressor
                if "messy space" not in list(self._affect._stress.sources):
                    self._affect.on_stressor_added("messy space")

        # === Body tick ===
        current_activity = ""
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot()
            if slot:
                current_activity = slot.activity_name
        self._body.tick(
            activity_name=current_activity,
            weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
            hours_awake=self._energy.hours_awake,
            stress_level=self._affect.stress.level,
            # Self-image is dragged down by shame (routed from Shadow via LifeService).
            shame=self._shadow.get_status().get("shame", 0.0) if self._shadow else 0.0,
        )

        # === Hormonal modifiers routing ===
        hormonal_mods = self._body.get_hormonal_modifiers() if self._body else {}
        if hormonal_mods:
            energy_mod = hormonal_mods.get("energy_mod", 0.0)
            if energy_mod != 0.0:
                self._energy._state.level = max(0.05, min(1.0,
                    self._energy._state.level + energy_mod * 0.1))
            sensitivity_mod = hormonal_mods.get("sensitivity_mod", 0.0)
            if sensitivity_mod != 0.0:
                self._affect._affect_multiplier = max(0.5, min(1.5,
                    self._affect._base_affect_multiplier + sensitivity_mod))

        # === Inebriation effects routing ===
        inebriation_fx = self._body.get_inebriation_effects()
        if inebriation_fx.get("is_inebriated"):
            self._cognitive._focus.quality = max(0.0,
                self._cognitive._focus.quality - inebriation_fx["focus_penalty"] * 0.1)
        if inebriation_fx.get("is_hungover"):
            if "hangover" not in [s for s in self._affect._stress.sources]:
                self._affect.on_stressor_added("hangover")

        # === Affect tick ===
        self._affect.tick(
            body_state={"hunger": self._basic_needs.hunger, "hours_awake": self._energy.hours_awake},
            social_state={"recent_events": self._social.get_recent_events() if hasattr(self._social, 'get_recent_events') else []},
            weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
            season=self._world.season.value if hasattr(self._world.season, 'value') else str(self._world.season),
        )

        # === Weather → Affect mood nudge (human-only, on weather CHANGE) ===
        # Route a one-shot bounded nudge when the weather label changes so the push
        # never accumulates unboundedly.  Gated by AURA_WEATHER_MOOD_ENABLED.
        if not self._is_ai and self._weather_mood_enabled():
            _cur_w = self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather)
            if _cur_w != self._last_weather_label:
                _delta = _WEATHER_MOOD_DELTA.get(_cur_w, 0.0)
                if _delta != 0.0:
                    self._affect.on_weather_nudge(_delta * WEATHER_MOOD_WEIGHT)
                self._last_weather_label = _cur_w

        # === Life Events: record intense emotional moments ===
        mood_intensity = self._affect.mood.intensity if hasattr(self._affect.mood, 'intensity') else 0
        if mood_intensity > 0.5:
            life_event = self._life_events.on_emotion_event(
                self._affect.mood.current_mood, mood_intensity
            )
            if life_event:
                self._bridge_life_event(life_event)

        # === Cognitive tick ===
        self._cognitive.tick(
            current_activity=current_activity,
            stress_level=self._affect.stress.level,
            sleep_quality=self._body.sleep_quality.last_quality,
            hunger=self._basic_needs.hunger,
        )
        # Awareness (from Energy) modulates focus — foggy/barely-present dampens it.
        _awareness = self._energy.awareness()
        if _awareness < 0.4:
            self._cognitive._focus.quality = max(
                0.0, self._cognitive._focus.quality - (0.4 - _awareness) * 0.2
            )

        # === Shadow tick (inner dark psychology) ===
        # Reuse the same affect-derived signals the cognitive/affect ticks use.
        # Mood is a string label + intensity; map it to a 0..1 valence
        # (1 = good, 0 = bad) the Shadow engine expects.
        _mood_label = self._affect.mood.current_mood if self._affect else "neutral"
        _mood_intensity = self._affect.mood.intensity if self._affect else 0.0
        _mood_valence = self._mood_to_valence(_mood_label, _mood_intensity)
        self._shadow.tick(
            stress=self._affect.stress.level,
            loneliness=self._affect.loneliness.level,
            mood=_mood_valence,
        )

        # === Sanity tick (the interior that integrates and can break) ===
        self._tick_sanity()

        # === Drive tick ===
        self._drive.tick()
        self._drive.roll_avoidance()
        # Feed avoidance guilt into affect stress
        for stressor in self._drive.get_guilt_stressors():
            self._affect.on_stressor_added(f"avoiding: {stressor}")

        # === Social expansion tick ===
        self._social.tick_arcs()
        self._social.tick_obligations()
        self._social.tick_conflicts()
        self._social.recharge_social_battery()
        # Feed overdue obligations into affect stress
        for obligation in self._social.get_overdue_obligations():
            self._affect.on_stressor_added(f"overdue: {obligation}")

        # === Career / Finance / Errands (humans only) ===
        # On the world clock, the way the catch-up path already ticks them
        # (``now=timestamp``): ``CareerSystem.tick`` registers a workday off
        # ``now``'s date and hour and only then draws, ``FinanceSystem.tick``
        # credits and debits on ``now``'s month, and with those draws on an
        # injected ``rng`` a bare ``tick()`` made the host wall clock decide
        # how many values the stream gave up -- a run and its replay, hours
        # apart, drew different counts. Without an injected world clock this
        # is ``datetime.now()`` exactly as before (see :meth:`_world_clock`).
        if not self._is_ai:
            _world_now = self._world_clock()()
            self._career.tick(now=_world_now)
            if self._career.monthly_salary > 0:
                self._finance.state.monthly_income = self._career.monthly_salary
            if self._career.work_stress() >= 0.5:
                if "work stress" not in list(self._affect._stress.sources):
                    self._affect.on_stressor_added("work stress")

            self._finance.tick(now=_world_now)
            if self._finance.financial_stress() >= 0.4:
                if "money worries" not in list(self._affect._stress.sources):
                    self._affect.on_stressor_added("money worries")

            self._errands.tick(now=_world_now)
            if self._errands.overdue_count >= 3:
                if "errands piling up" not in list(self._affect._stress.sources):
                    self._affect.on_stressor_added("errands piling up")

        # === Behavior tick (ambient senses) ===
        self._behavior.tick(
            location=self._world.current_location or "home",
            weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
            time_of_day=self._world.time_of_day.value if hasattr(self._world.time_of_day, 'value') else str(self._world.time_of_day),
        )

        # === Expression tick (connection awareness) ===
        self._expression.tick()

        # === Continuity tick (daily/weekly cycles) ===
        now = datetime.now()
        if (not self._continuity._last_daily_tick or
                (now - self._continuity._last_daily_tick).total_seconds() > 86400):
            continuity_events = self._continuity.daily_tick()
            for evt in continuity_events:
                if evt.startswith("anniversary:"):
                    self._affect.on_emotion_event("nostalgic", 0.3)
            # Scan user calendar for upcoming event triggers
            try:
                self._scan_calendar_for_triggers()
            except Exception:
                logger.debug("Calendar scan failed", exc_info=True)
        if (not self._continuity._last_weekly_tick or
                (now - self._continuity._last_weekly_tick).total_seconds() > 604800):
            skill_levels = {name: sp.level for name, sp in self._skills.items()}
            identity_facets = {f.name: f.strength for f in self._identity.get_top_facets(5)}
            trust = self._identity.get_user_perception().trust_level
            self._continuity.weekly_tick(skill_levels, identity_facets, trust)
        # Monthly character evolution (every 30 days)
        if (not self._character_evolution._last_evolution or
                (now - self._character_evolution._last_evolution).total_seconds() > 2592000):
            identity_facets = {f.name: f.strength for f in self._identity.get_top_facets(5)}
            trust = self._identity.get_user_perception().trust_level
            mood_str_evo = self._affect.mood.current_mood if self._affect else "neutral"
            drift_changes = self._character_evolution.monthly_evolution(
                identity_facets=identity_facets,
                relationship_trust=trust,
                avg_mood=mood_str_evo,
            )
            if drift_changes:
                logger.info(f"Character evolution drift: {drift_changes}")
        # Monthly continuity synthesis (life chapters, every 30 days)
        if (not self._continuity._last_monthly_tick or
                (now - self._continuity._last_monthly_tick).total_seconds() > 2592000):
            # Gather month's data for chapter synthesis
            from collections import Counter
            activity_counts = dict(Counter(self._behavior._activity_history))
            mood_str_month = self._affect.mood.current_mood if self._affect else "neutral"
            avg_energy_month = self._energy.level
            completed = [g.title for g in self._goal_engine.completed_goals[-5:]
                         if g.completed_at and (now - g.completed_at).days <= 35]
            abandoned = [g.title for g in self._goal_engine.abandoned_goals[-5:]
                         if g.abandoned_at and (now - g.abandoned_at).days <= 35]
            identity_shifts_month = []
            if self._growth_snapshots_for_month(now):
                identity_shifts_month = self._growth_snapshots_for_month(now)
            chapter = self._continuity.monthly_tick(
                activity_summary=activity_counts,
                dominant_mood=mood_str_month,
                avg_energy=avg_energy_month,
                goals_completed=completed,
                goals_abandoned=abandoned,
                identity_shifts=identity_shifts_month,
            )
            if chapter:
                # Also add to MemoryTime's life chapters
                self._memory_time.add_life_chapter(
                    title=chapter.title,
                    summary=chapter.summary,
                    turning_points=chapter.turning_points,
                    dominant_emotions=chapter.dominant_emotions,
                )
                self._save_continuity()
        # Check milestones
        milestone = self._continuity.check_milestones(
            interaction_count=self._expression._interaction_count,
            vulnerability_openness=self._expression._style.vulnerability_openness,
            inside_joke_count=len(self._identity.get_inside_jokes()),
        )
        if milestone:
            self._create_shareable_from_text(
                f"A milestone: {milestone.name} — {milestone.description}",
                context="Looking back",
            )
            event = self._life_events.record_event(
                event_type="social",
                title=milestone.name,
                description=milestone.description,
                emotional_impact={"warm": 0.3, "grateful": 0.2},
                share_urgency=0.5,
                source="relationship_milestone",
            )
            self._bridge_life_event(event)

        # === Memory & Time tick ===
        mood_str = self._affect.mood.current_mood if self._affect else "neutral"
        season_str = self._world.season.value if hasattr(self._world.season, 'value') else str(self._world.season)
        tod_str = self._world.time_of_day.value if hasattr(self._world.time_of_day, 'value') else str(self._world.time_of_day)
        nostalgia_event = self._memory_time.tick(
            current_activity=current_activity,
            mood=mood_str,
            season=season_str,
            time_of_day=tod_str,
        )
        if nostalgia_event:
            self._affect.on_emotion_event("nostalgic", nostalgia_event.intensity)
            if nostalgia_event.intensity > 0.4:
                self._create_shareable_from_text(
                    f"Something reminded her of {nostalgia_event.memory_reference}",
                    context=f"A wave of nostalgia from {nostalgia_event.trigger}",
                )

        # === Anticipation → mood ===
        anticipations = self._memory_time.get_anticipations()
        for ant in anticipations:
            if ant.feeling == "excited" and ant.intensity > 0.2:
                self._affect.on_emotion_event("excited", ant.intensity * 0.1)
            elif ant.feeling == "dreading" and ant.intensity > 0.2:
                self._affect.on_emotion_event("anxious", ant.intensity * 0.1)

        # === Evaluate life-driven proactive triggers ===
        self._evaluate_life_triggers()

        logger.debug(f"Energy tick: {self._energy.effective_level:.2f}, hunger: {self._basic_needs.hunger:.2f}")

    # ============= Life-Driven Proactive Triggers =============

    def _get_adaptive_cooldown(self, trigger_type: str) -> float:
        """Get adaptive cooldown based on base value and user engagement.

        If user ignores proactive messages (bid_response_rate < 0.3), back off (2x).
        If user is engaged (bid_response_rate > 0.7), send more (0.75x).
        Floor: never exceed 3x base to prevent infinite backoff.
        """
        base = BASE_LIFE_TRIGGER_COOLDOWNS.get(trigger_type, 6.0)
        if self._user_model_provider is None:
            return base
        try:
            um = self._user_model_provider(self._persona_id)
            rate = um.bid_response_rate
            if rate < 0.3:
                multiplier = 2.0
            elif rate > 0.7:
                multiplier = 0.75
            else:
                multiplier = 1.0
            return min(base * multiplier, base * 3.0)
        except Exception:
            return base

    def _life_trigger_cooled_down(self, trigger_type: str, now: datetime) -> bool:
        """Check if enough time has passed since last trigger of this type."""
        last = self._life_trigger_cooldowns.get(trigger_type)
        if not last:
            return True
        hours_since = (now - last).total_seconds() / 3600
        required = self._get_adaptive_cooldown(trigger_type)
        return hours_since >= required

    def _record_life_trigger_cooldown(self, trigger_type: str, now: datetime):
        self._life_trigger_cooldowns[trigger_type] = now

    def _report_user_model_failure(self, site: str, exc: BaseException) -> None:
        """Report a failing host-supplied user-model provider.

        WARNING the first time each site fails, DEBUG afterwards. These three
        sites sit on the message and tick paths, so an unconditional warning
        would be a log storm — but the bare ``except Exception: pass`` that was
        here meant a broken provider degraded three behaviours invisibly and
        permanently.
        """
        if site in self._user_model_failures_seen:
            logger.debug("user_model_provider failed at %s: %s", site, exc, exc_info=True)
            return
        self._user_model_failures_seen.add(site)
        logger.warning(
            "user_model_provider failed at %s: %s — this behaviour stays degraded "
            "until the host provider is fixed (reported once per site)",
            site, exc, exc_info=True,
        )

    def _relationship_is_close(self) -> bool:
        """True when the user<->persona bond is close (comfortable/deep stage).

        Reads ExpressionSystem.relationship_stage — the single existing closeness
        signal. Used to decide whether an AI persona may act out human-like
        spontaneous/emotional proactive behavior. Defensive: if the stage can't be
        read, returns False (the safe, less-intrusive choice — AI stays practical).
        """
        try:
            return self._expression._style.relationship_stage in CLOSE_RELATIONSHIP_STAGES
        except Exception:
            return False

    # ============= Sanity: the interior that integrates and can break =============

    def on_sanity_blow(self, kind: str, severity: float) -> float:
        """Report a blow to the sanity engine and apply the couplings at once.

        Thin over :meth:`SanitySystem.on_blow`. A host may also call the engine
        directly through :attr:`sanity`; the couplings then catch up at the
        next energy tick. Returns the loss applied.
        """
        loss = self._sanity.on_blow(kind, severity)
        self._sync_sanity_couplings()
        return loss

    def on_sanity_recovery(self, kind: str, amount: float) -> float:
        """Report a recovery to the sanity engine and apply the couplings at
        once. Thin over :meth:`SanitySystem.on_recovery`; returns the gain."""
        gain = self._sanity.on_recovery(kind, amount)
        self._sync_sanity_couplings()
        return gain

    def _tick_sanity(self) -> None:
        """Advance sanity by the world time elapsed since the last tick.

        Hours come from the world clock, the way energy measures elapsed time
        (:meth:`_world_clock`); the engine itself reads no clock. The stamp is
        taken at construction and again on reload rather than persisted, so a
        host's downtime is not charged as lived time -- catch-up is the host's
        business, and the engine is only told about hours the persona lived.

        ``stressed`` reads affect's stress *level* against
        ``SANITY_STRESSED_LEVEL``, not the ``stress.sources`` labels: the level
        is the live quantity (it decays), the labels are a summary the service
        never clears.
        """
        now = self._world_clock()()
        hours = (now - self._sanity_ticked_at).total_seconds() / 3600
        self._sanity_ticked_at = now
        self._sanity.tick(
            hours,
            stressed=self._affect.stress.level >= SANITY_STRESSED_LEVEL,
            concealment_load=self._shadow.state.concealment_load,
        )
        self._sync_sanity_couplings()

    def _sync_sanity_couplings(self) -> None:
        """Apply the sanity -> library couplings when the engine's state word
        has changed since they were last applied.

        Nothing happens while the word holds -- a persona whose baseline sits
        in ``strained`` and never moves is byte-identical to one built before
        this engine existed. On a change, the word-functions are applied
        (they are idempotent, so repeated changes never double-count):

        * ``strained`` or worse: affect carries a stressor named
          ``SANITY_STRESS_SOURCE``; ``sound`` clears it.
        * ``fraying`` or worse: shadow holds ``SANITY_FRAYING_RESTRAINT_PRESSURE``
          on restraint (inhibition down, intrusive thoughts closer to winning);
          above ``fraying`` it is released.

        The third is an entry event -- regulation capacity collapses by
        ``SANITY_BREAKING_REGULATION_COLLAPSE`` once, on the way *into*
        ``breaking`` from above. A reload never comes through here: it restores
        the coupled word from the row (see :meth:`_load_sanity`), so the entry
        event is not fired twice and affect's row keeps its own side.
        """
        new = self._sanity.state
        old = self._sanity_coupled_state
        if new == old:
            return
        rank = SANITY_STATES.index

        if new == "sound":
            if SANITY_STRESS_SOURCE in self._affect.stress.sources:
                self._affect.on_stressor_resolved(SANITY_STRESS_SOURCE)
        else:
            self._affect.on_stressor_added(SANITY_STRESS_SOURCE)

        self._hold_sanity_restraint(new)

        if rank(old) < rank("breaking") <= rank(new):
            self._affect.deplete_regulation(SANITY_BREAKING_REGULATION_COLLAPSE, "sanity: breaking")

        self._sanity_coupled_state = new

    def _hold_sanity_restraint(self, word: str) -> None:
        """Hold (``fraying`` or worse) or release shadow's restraint pull for
        ``word``. Idempotent: a pull already held at that amount moves nothing,
        which is what makes it safe after a reload."""
        rank = SANITY_STATES.index
        pressure = SANITY_FRAYING_RESTRAINT_PRESSURE if rank(word) >= rank("fraying") else 0.0
        if self._shadow.restraint_pressure != pressure:
            self._shadow.set_restraint_pressure(pressure)

    def _evaluate_life_triggers(self):
        """Evaluate all engine state and create proactive triggers when conditions are met.

        Called at end of _on_energy_tick() (every 5 min) after all cross-engine routing
        is complete. Never called during catch-up.
        """
        if self._follow_up_provider is None:
            return

        now = datetime.now()
        fm = self._follow_up_provider(self._persona_id)
        candidates = []  # (trigger_type_str, urgency, topic, prompt_hint)

        # --- 1. MOOD_SHIFT ---
        try:
            cur_mood = self._affect.mood.current_mood
            cur_intensity = self._affect.mood.intensity
            mood_changed = (
                self._prev_mood is not None
                and cur_mood != self._prev_mood
                and cur_intensity >= 0.3
            )
            intensity_spiked = (
                self._prev_mood is not None
                and cur_mood == self._prev_mood
                and (cur_intensity - self._prev_mood_intensity) >= 0.25
            )
            if (mood_changed or intensity_spiked) and self._life_trigger_cooled_down("mood_shift", now):
                context = f"intensity {cur_intensity:.1f}"
                if mood_changed:
                    context = f"was {self._prev_mood}, now {cur_mood} ({context})"
                hint = (
                    f"Your mood shifted to {cur_mood}. {context}. "
                    f"Reach out naturally — share how you're feeling or let it color what you say."
                )
                candidates.append(("mood_shift", 0.5, cur_mood, hint))
            # Always update prev state
            self._prev_mood = cur_mood
            self._prev_mood_intensity = cur_intensity
        except Exception:
            logger.debug("Life trigger: mood_shift eval failed", exc_info=True)

        # --- 2. LONELINESS_SPIKE ---
        try:
            cur_loneliness = self._affect.loneliness.level
            crossed_up = self._prev_loneliness < 0.6 and cur_loneliness >= 0.6
            if crossed_up and self._life_trigger_cooled_down("loneliness_spike", now):
                hint = (
                    "You've been feeling really lonely. You want to hear from them — "
                    "ask how their day is going, or share something to start a conversation."
                )
                candidates.append(("loneliness_spike", 0.6, "feeling lonely", hint))
            self._prev_loneliness = cur_loneliness
        except Exception:
            logger.debug("Life trigger: loneliness_spike eval failed", exc_info=True)

        # --- 3. DREAM_SHARE ---
        try:
            dream = self._cognitive.get_dream_residue()
            if dream and dream.get("intensity", 0) >= 0.3:
                if self._life_trigger_cooled_down("dream_share", now):
                    emotion = dream.get("emotion", "strange")
                    hint = (
                        f"You had a weird/vivid dream — it left you feeling {emotion}. "
                        f"Share it casually, like 'I had the strangest dream last night...'"
                    )
                    candidates.append(("dream_share", 0.4, f"dream ({emotion})", hint))
        except Exception:
            logger.debug("Life trigger: dream_share eval failed", exc_info=True)

        # --- 4. CHAOS_EVENT ---
        try:
            chaos_state = self._chaos.export_state()
            last_event_text = chaos_state.get("last_chaos_event", "")
            last_event_type = chaos_state.get("last_chaos_type", "")
            if last_event_text and last_event_text != self._last_seen_chaos_event:
                share_worthy = last_event_type in ("serendipity", "universal")
                if share_worthy and self._life_trigger_cooled_down("chaos_event", now):
                    hint = (
                        f"Something happened: {last_event_text}. "
                        f"Share it like you'd tell a friend about your day."
                    )
                    candidates.append(("chaos_event", 0.55, last_event_text[:60], hint))
                self._last_seen_chaos_event = last_event_text
        except Exception:
            logger.debug("Life trigger: chaos_event eval failed", exc_info=True)

        # --- 5. NOSTALGIA ---
        try:
            recent = self._memory_time.get_recent_nostalgia(1)
            if recent:
                n = recent[0]
                if n.intensity >= 0.4 and n.memory_reference != self._last_seen_nostalgia_ref:
                    if self._life_trigger_cooled_down("nostalgia", now):
                        hint = (
                            f"A memory hit you — {n.memory_reference}. "
                            f"Share the feeling with them, maybe ask if they've had moments like that."
                        )
                        candidates.append(("nostalgia", 0.4, n.memory_reference[:60], hint))
                    self._last_seen_nostalgia_ref = n.memory_reference
        except Exception:
            logger.debug("Life trigger: nostalgia eval failed", exc_info=True)

        # --- 6. GOAL_MILESTONE ---
        try:
            emotional_ctx = self._goal_engine.get_emotional_context()
            if emotional_ctx and self._life_trigger_cooled_down("goal_milestone", now):
                hint = (
                    f"You've been thinking about your goals — {emotional_ctx} "
                    f"Name the ONE concrete thing that actually moved (a specific step "
                    f"you took, a real obstacle you hit) — never a vague 'epiphany' or "
                    f"'I cracked the code'. Or just ask what they're working toward."
                )
                candidates.append(("goal_milestone", 0.5, emotional_ctx[:60], hint))
        except Exception:
            logger.debug("Life trigger: goal_milestone eval failed", exc_info=True)

        # --- 7. SOCIAL_EVENT ---
        try:
            events = self._social.get_recent_events(1)
            if events:
                ev = events[0]
                age_min = (now - ev.timestamp).total_seconds() / 60 if ev.timestamp else 999
                if ev.share_worthy and age_min <= 30:
                    if self._life_trigger_cooled_down("social_event", now):
                        hint = (
                            f"Something happened with {ev.npc_name}: {ev.description}. "
                            f"Share it naturally."
                        )
                        candidates.append(("social_event", 0.45, ev.description[:60], hint))
        except Exception:
            logger.debug("Life trigger: social_event eval failed", exc_info=True)

        # --- 8. NEED_DRIVEN ---
        try:
            needs = self.assess_needs()
            need_hints = {
                "connection": "You're craving connection. Reach out warmly.",
                "stimulation": "You're bored and restless. Start an interesting conversation or ask them something thought-provoking.",
                "competence": "You're feeling unsure of yourself. Talk about something you're working on, or ask for their perspective.",
                "safety": "You're feeling uneasy. Reach out for some comfort or grounding.",
                "autonomy": "You're feeling boxed in. Share what's on your mind or vent a little.",
            }
            for need_name, need_data in needs.items():
                if need_name == "physical_comfort":
                    continue  # Don't message about hunger/tiredness
                if need_data["satisfaction"] < 0.2:
                    if self._life_trigger_cooled_down("need_driven", now):
                        hint = need_hints.get(need_name, f"You're reaching out because you need {need_name}.")
                        candidates.append(("need_driven", 0.55, need_name, hint))
                    break  # Only one need-driven trigger at a time
        except Exception:
            logger.debug("Life trigger: need_driven eval failed", exc_info=True)

        # --- 9. LIFE_QUESTION ---
        try:
            question_candidates = []

            # Rumination source
            for rum in self._cognitive.ruminations:
                if rum.intensity >= 0.4:
                    question_candidates.append((
                        0.5 + rum.intensity * 0.1,
                        rum.topic,
                        f"You've been turning '{rum.topic}' over in your mind. "
                        f"Ask them what they think about it.",
                    ))

            # Uncertain opinion source
            for op in self._cognitive.get_opinions_for_context(3):
                if op.confidence < 0.4:
                    question_candidates.append((
                        0.45,
                        op.subject,
                        f"You're forming an opinion about '{op.subject}' but you're not sure yet. "
                        f"Ask where they stand.",
                    ))

            # Active curiosity source
            for cur in self._drive.get_active_curiosities(2):
                if cur.intensity >= 0.5:
                    question_candidates.append((
                        0.5 + cur.intensity * 0.1,
                        cur.topic,
                        f"You've gotten curious about '{cur.topic}'. "
                        f"Ask if they know anything about it or have thoughts.",
                    ))

            # Low self-esteem source
            if self._identity.self_esteem.level < 0.35:
                question_candidates.append((
                    0.45,
                    "self-doubt",
                    "You've been second-guessing yourself. "
                    "Ask for their honest perspective on something you're unsure about.",
                ))

            # Loneliness source (lower threshold than spike)
            if self._affect.loneliness.level >= 0.5:
                question_candidates.append((
                    0.5,
                    "missing real conversation",
                    "You miss real conversation. Ask them something personal — "
                    "what they've been thinking about, what's on their mind.",
                ))

            # Inner monologue source
            thought = self._cognitive.get_inner_monologue()
            if thought and len(thought) > 10:
                question_candidates.append((
                    0.45,
                    thought[:40],
                    f"You had this thought: '{thought[:60]}'. "
                    f"Turn it into a question — ask them what they think.",
                ))

            if question_candidates and self._life_trigger_cooled_down("life_question", now):
                # Pick top 3 by urgency, then weighted random (weight = urgency^2)
                question_candidates.sort(key=lambda x: x[0], reverse=True)
                top = question_candidates[:3]
                weights = [u ** 2 for u, _, _ in top]
                chosen = self._random.choices(top, weights=weights, k=1)[0]
                urgency, topic, hint = chosen
                candidates.append(("life_question", urgency, topic[:60], hint))
        except Exception:
            logger.debug("Life trigger: life_question eval failed", exc_info=True)

        # --- 10. MOMENT_SHARE ---
        # Reset transient each evaluation cycle so stale values never leak.
        self._pending_moment_share_chaos_event = None
        try:
            # Don't fire a scheduled-activity moment-share right after a real
            # conversation — the planner slot is likely stale (e.g. "attending to
            # plants" while she was actually in bed with the user), which would
            # produce an off-topic "about plants" proactive. Suppress within the
            # same window the conversation activity overrides the schedule.
            # Keyed on last user message (any recent conversation), NOT on
            # _conversation_activity_at — we suppress the stale scheduled-activity
            # share after ANY real conversation, whether or not a [DOING:] tag was
            # emitted.
            _recent_msg = getattr(self, "_last_user_message_at", None)
            _recent_conversation = bool(
                _recent_msg
                and (now - _recent_msg)
                <= timedelta(minutes=CONVERSATION_ACTIVITY_WINDOW_MINUTES)
            )
            _act_name = ""
            if self._daily_planner.current_plan:
                _slot = self._daily_planner.current_plan.get_current_slot()
                if _slot:
                    _act_name = _slot.activity_name or ""
            # Defensive: an AI persona has no physical body, so her moment-share
            # must never claim a physical action (eating, commuting, sleeping…).
            # The AI scheduler already excludes physical activities, but a stale
            # plan or a manually-set slot could still carry one — blank it so the
            # share falls back to the conversation-driven [DOING:] activity below.
            if self._is_ai and _act_name:
                if _act_name.lower() in PHYSICAL_ACTIVITIES:
                    _act_name = ""
            if _recent_conversation:
                _act_name = ""  # skip — recent chat makes the scheduled slot unreliable
            if _act_name and not any(skip in _act_name.lower() for skip in MOMENT_SHARE_ROUTINE_SKIP):
                # Signal 1: chaos event is NEW (not yet consumed by a moment share)
                _chaos_event_text = self._chaos.export_state().get("last_chaos_event", "")
                _chaos_new = bool(_chaos_event_text and _chaos_event_text != self._last_moment_share_chaos_event)
                # Signal 2: mood clearly lifted (reuse same accessor as MOOD_SHIFT block)
                _mood_high = self._affect.mood.intensity >= 0.7
                # Signal 3: shadow validation drive is high — a "look at me" moment.
                # Reuse the existing MOMENT_SHARE photo path, just flavor the hint
                # toward a flattering selfie/scene fishing for a little attention.
                _shadow_status = self._shadow.get_status()
                _acting_out = self._shadow.export_state().get("acting_out_for_attention", False)
                _attention_high = _acting_out or _shadow_status.get("attention_seeking", 0.0) >= 0.55
                # The spontaneous "look at me" attention-image flavor is a human-like
                # behavior. An AI persona only acts it out once the relationship is
                # close; before then she stays in helpful/practical territory and
                # never fishes for attention with a selfie. Humans are unaffected.
                if self._is_ai and not self._relationship_is_close():
                    _attention_high = False
                if (_chaos_new or _mood_high or _attention_high) and self._life_trigger_cooled_down("moment_share", now):
                    if _attention_high:
                        hint = (
                            f"You're feeling a pull to be noticed right now. You're"
                            f" {_act_name} and you want a little attention — share a"
                            f" casual, flattering photo of yourself or the moment using"
                            f" an [IMAGE:self: ...] or [IMAGE:scene: ...] tag, with a"
                            f" short caption that low-key fishes for a compliment or"
                            f" some validation. Keep it in your own voice, a bit playful,"
                            f" not needy."
                        )
                    else:
                        hint = (
                            f"You're {_act_name} right now and it feels worth sharing."
                            f" Send a short excited message about it, like texting a photo to"
                            f" someone you like."
                        )
                    candidates.append(("moment_share", 0.55, _act_name, hint))
                    # Stash the chaos text as a transient; consume only if this
                    # candidate is the one that actually fires (see dispatch tail).
                    if _chaos_new:
                        self._pending_moment_share_chaos_event = _chaos_event_text
        except Exception:
            logger.debug("Life trigger: moment_share eval failed", exc_info=True)

        # --- Boost/penalize by user engagement data ---
        if self._user_model_provider is not None:
            try:
                um = self._user_model_provider(self._persona_id)
                engaged = {t.lower() for t, _ in um.get_engaged_topics(5)}
                disengaged = {t.lower() for t, _ in um.get_disengaged_topics(5)}
                for i, (ttype, urgency, topic, hint) in enumerate(candidates):
                    topic_lower = topic.lower()
                    if any(e in topic_lower for e in engaged):
                        candidates[i] = (ttype, min(1.0, urgency + 0.1), topic, hint)
                    elif any(d in topic_lower for d in disengaged):
                        candidates[i] = (ttype, max(0.0, urgency - 0.15), topic, hint)
            except Exception as exc:
                self._report_user_model_failure("engagement_weighting", exc)

        # --- Select and create triggers ---
        # Pick top 3 candidates by urgency, then weighted-random one
        if not candidates:
            return

        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[:3]
        weights = [u ** 2 for _, u, _, _ in top]
        chosen = self._random.choices(top, weights=weights, k=1)[0]
        trigger_type_str, urgency, topic, hint = chosen

        # Map candidate string to the follow-up type's member NAME. The host
        # adapter turns the name back into its enum member — the engine never
        # imports the enum itself.
        type_map = {
            "mood_shift": "MOOD_SHIFT",
            "loneliness_spike": "LONELINESS_SPIKE",
            "dream_share": "DREAM_SHARE",
            "chaos_event": "CHAOS_EVENT",
            "nostalgia": "NOSTALGIA",
            "goal_milestone": "GOAL_MILESTONE",
            "social_event": "SOCIAL_EVENT",
            "need_driven": "NEED_DRIVEN",
            "life_question": "LIFE_QUESTION",
            "upcoming_event": "UPCOMING_EVENT",
            "moment_share": "MOMENT_SHARE",
        }
        follow_up_type = type_map.get(trigger_type_str)
        if not follow_up_type:
            return

        # Pass user quiet windows for smart delay scheduling
        quiet_windows = None
        if self._user_model_provider is not None:
            try:
                um = self._user_model_provider(self._persona_id)
                quiet_windows = um.quiet_windows if um.quiet_windows else None
            except Exception as exc:
                self._report_user_model_failure("quiet_windows", exc)

        fm.create_trigger(
            trigger_type=follow_up_type,
            topic=topic,
            context=f"life_trigger:{trigger_type_str}",
            urgency=urgency,
            prompt_hint=hint,
            quiet_windows=quiet_windows,
        )
        self._record_life_trigger_cooldown(trigger_type_str, now)
        # Consume the pending chaos event only when moment_share actually fires.
        if trigger_type_str == "moment_share" and self._pending_moment_share_chaos_event:
            self._last_moment_share_chaos_event = self._pending_moment_share_chaos_event
        self._pending_moment_share_chaos_event = None
        logger.info(f"[LIFE-TRIGGER] {trigger_type_str} for {self._persona_id}: {topic[:40]}")

    def _on_activity_tick(self) -> None:
        """Handle activity tick - perform an activity."""
        # Clear stale ARRIVED transit (auto-clears after next activity tick)
        if self._transit and self._transit.phase == TransitPhase.ARRIVED:
            self.clear_transit()

        # Check if should rest/sleep
        force_rest = self._energy.should_rest()

        # If the user is actively chatting right now, sleep is a soft cap: she stays
        # up with them (and pays for it tomorrow) instead of drifting off mid-chat.
        recent_msg = getattr(self, "_last_user_message_at", None)
        in_conversation = bool(
            recent_msg and (datetime.now() - recent_msg).total_seconds() < 20 * 60
        )

        # AI personas never sleep — skip the autonomous sleep decision entirely so
        # they stay awake at all times (humans keep the existing soft-cap behavior).
        if not self._is_ai and self._energy.should_sleep(in_conversation=in_conversation, now_hour=self.persona_local_hour()):
            # Sleep activity
            activity = self._activity_engine.get_activity("sleeping")
            if activity:
                self._energy.sleep()
                log = ActivityLog(
                    activity_name="sleeping",
                    category=activity.category,
                    started_at=datetime.now(),
                    narrative="She drifted into restful sleep",
                    energy_before=0.1,
                    energy_after=0.7,
                )
                self._record_activity(log)
                logger.info("The persona went to sleep")
                return

        # Check if conditions are right for an intimate activity
        if self._desire_system.should_do_intimate_activity(
            self._energy.effective_level,
            self._world.time_of_day
        ):
            intimate_activity = self._desire_system.select_intimate_activity()
            if intimate_activity:
                # Move to home for intimate activities
                if self._world.current_location != "home":
                    self._world.move_to("home")

                # Execute intimate activity
                result = self._desire_system.execute_intimate_activity(intimate_activity)

                # Apply energy cost
                if result["energy_cost"] < 0:
                    self._energy.restore_energy(abs(result["energy_cost"]))
                else:
                    self._energy.consume_energy(result["energy_cost"])

                # Apply emotion effects
                if result["emotion_effects"]:
                    # Update real-time EmotionEngine
                    if self._emotion_engine:
                        for emotion, intensity in result["emotion_effects"].items():
                            try:
                                self._emotion_engine.add_emotion(emotion, intensity)
                            except Exception:
                                pass

                    # Persist emotions for multi-day arcs
                    self._persist_activity_emotions(
                        result["activity_name"],
                        result["emotion_effects"]
                    )

                # Create activity log
                log = ActivityLog(
                    activity_name=result["activity_name"],
                    category=ActivityCategory.REST,  # Categorize as rest for now
                    started_at=datetime.now(),
                    location=self._world.current_location,
                    weather=self._world.weather,
                    narrative=result["narrative"],
                    thoughts_generated=result["thoughts"],
                    emotions_triggered=result["emotion_effects"],
                    energy_before=self._energy.effective_level + result["energy_cost"],
                    energy_after=self._energy.effective_level,
                    share_worthy=result["share_worthy"],
                )
                self._record_activity(log)

                # Maybe create shareable (with shyness consideration)
                if result["share_worthy"]:
                    would_share, context = self._desire_system.would_share_with_user(
                        result["shyness_to_share"]
                    )
                    if would_share:
                        self._create_shareable(log, context)

                logger.info(f"Intimate activity: {intimate_activity.name}")
                return

        # Consult daily plan for the current hour (persona-local so her schedule
        # follows her own timezone, not the server's clock).
        planned_slot = self._daily_planner.get_planned_activity(self.persona_local_hour())
        planned_activity_name = planned_slot.activity_name if planned_slot and not planned_slot.completed else None

        # Try to follow the plan; fall back to ad-hoc selection
        activity = None
        if planned_activity_name and not force_rest:
            activity = self._activity_engine.get_activity(planned_activity_name)
            # Verify energy requirement
            if activity and self._energy.effective_level < activity.min_energy:
                activity = None  # Can't do this right now

        if not activity:
            # Get salient values for value-influenced scoring
            salient_vals = None
            if self._identity:
                sv = self._identity.get_salient_values(limit=5)
                if sv:
                    salient_vals = [
                        {"name": v.name, "salience": v.salience, "aligned_tags": v.aligned_tags}
                        for v in sv
                    ]
            activity = self._activity_engine.select_activity(
                energy_level=self._energy.effective_level,
                time_of_day=self._world.time_of_day,
                weather=self._world.weather,
                current_location=self._world.current_location,
                active_goals=self._goal_engine.active_goals,
                force_rest=force_rest,
                season=self._world.season,
                salient_values=salient_vals,
            )

        if not activity:
            logger.debug("No suitable activity found")
            return

        # Sync world location with the planner's slot location
        # Skip when transit is active (PREPARING or IN_TRANSIT) — don't let the
        # hourly slot system override the transit location.
        if self._transit and self._transit.phase in (TransitPhase.PREPARING, TransitPhase.IN_TRANSIT):
            pass  # Transit controls location
        elif planned_slot and planned_slot.location and planned_slot.location != self._world.current_location:
            self._world.move_to(planned_slot.location)
        elif activity.suitable_locations and self._world.current_location not in activity.suitable_locations:
            new_location = random.choice(activity.suitable_locations)
            self._world.move_to(new_location)

        # Execute activity
        log = self._activity_engine.execute_activity(
            activity=activity,
            location=self._world.current_location,
            weather=self._world.weather,
            energy_before=self._energy.effective_level,
        )

        # Apply energy cost
        if activity.energy_cost < 0:
            self._energy.restore_energy(abs(activity.energy_cost))
        else:
            self._energy.consume_energy(activity.energy_cost)

        # Apply emotion effects
        if log.emotions_triggered:
            # Update real-time EmotionEngine
            if self._emotion_engine:
                for emotion, intensity in log.emotions_triggered.items():
                    try:
                        self._emotion_engine.add_emotion(emotion, intensity)
                    except Exception:
                        pass  # Emotion might not exist in wheel

            # Persist emotions for multi-day arcs
            self._persist_activity_emotions(activity.name, log.emotions_triggered)

            # Feed into affect system
            for emotion, intensity in log.emotions_triggered.items():
                self._affect.on_emotion_event(emotion, intensity)

        # Activity-based affect update (regulation recharge, stress relief)
        self._affect.on_activity(activity.name)

        # Update goal progress
        self._goal_engine.update_progress_from_activity(log)

        # Maybe generate new goal from experience
        self._goal_engine.generate_goal_from_activity(log)

        # Track against daily plan and desires (persona-local hour)
        self._daily_planner.mark_slot_completed(self.persona_local_hour(), activity.name)
        self._daily_planner.fulfill_desire(activity.name)
        self._daily_planner.generate_desire_from_activity(activity.name)

        # Record activity
        self._record_activity(log)

        # Maybe create shareable experience
        if log.share_worthy:
            self._create_shareable(log)

        # === Basic needs + Room (humans only) ===
        if not self._is_ai:
            self._sustenance.on_activity(activity.name)
            if activity.name in ("morning shower", "taking a long bath"):
                self._basic_needs.showered_today = True
            if activity.name in ("waking up", "having breakfast"):
                self._basic_needs.morning_routine_done = True
            if activity.name == "listening to music":
                self._room_state.music_playing = True
            # Tidying / cleaning restores tidiness (Habitation engine).
            self._habitation.on_activity(activity.name)

        # === Media progress ===
        if activity.name == "reading" and self._media.current_book:
            self._media.book_progress += random.uniform(0.05, 0.12)
            if self._media.book_progress >= 1.0:
                finished_title = self._media.current_book
                self._record_finished_book(finished_title)
                self._create_shareable_from_text(
                    f"Just finished reading {finished_title}!",
                    context="After finishing the last page"
                )
                event = self._life_events.record_event(
                    event_type="achievement",
                    title=f"Finished reading {finished_title}",
                    description=f"Just finished the last page of {finished_title}",
                    emotional_impact={"satisfied": 0.3, "thoughtful": 0.2},
                    share_urgency=0.7,
                    source="book_completion",
                )
                self._bridge_life_event(event)
                self._media.current_book = self._pick_new_book()
                self._media.book_progress = 0.0

        # === Skill progression ===
        if activity.name in SKILL_MAPPINGS:
            skill_name, increment = SKILL_MAPPINGS[activity.name]
            self._update_skill(skill_name, increment, log)

        # === Body update from activity ===
        self._body.on_activity(activity.name)
        self._body.on_substance_activity(activity.name)

        # === Location effects ===
        self._apply_location_effects(log.location)

        # === Identity facets + esteem + taste ===
        self._identity.update_from_activity(activity.name)
        self._identity.on_activity_esteem(activity.name)
        self._identity.on_activity_taste(activity.name)

        # === Value reinforcement from activity ===
        cat_tag = activity.category.value.lower() if hasattr(activity.category, 'value') else ""
        if cat_tag:
            for v in self._identity.get_salient_values(limit=10):
                if cat_tag in v.aligned_tags:
                    self._identity.reinforce_value(v.name)

        # === Value conflict detection ===
        if cat_tag:
            conflict = self._identity.check_value_conflict(cat_tag)
            if conflict:
                self._affect.on_stressor_added(f"value conflict: {conflict['value']} vs {conflict['conflicting_tag']}")
                self._cognitive.on_conflict(f"{conflict['value']} challenged by {conflict['tension_with']}")

        # === Drive: curiosity + comfort zone ===
        self._drive.on_activity(activity.name)
        self._drive.track_activity_comfort(activity.name)

        # === Character evolution: track activity ===
        self._character_evolution.track_activity(activity.name)

        # === Cognitive + MemoryTime: activity engagement ===
        self._cognitive.on_activity(activity.name)
        self._shadow.on_activity(activity.name)
        self._memory_time.on_activity(activity.name)

        # === Physical-life engines react to the activity (humans only) ===
        if not self._is_ai:
            self._finance.on_activity(activity.name)   # money-spending activities
            self._career.on_activity(activity.name)    # work activities shift workload
            self._errands.on_activity(activity.name)   # chores clear the backlog

        # === Life Events: auto-record notable activities ===
        life_event = self._life_events.on_activity(
            activity_name=activity.name,
            emotions=log.emotions_triggered or {},
            share_worthy=log.share_worthy,
        )
        if life_event:
            self._bridge_life_event(life_event)

        # === Behavior: routines + creative output ===
        self._behavior.track_activity(activity.name)
        artifact = self._behavior.on_creative_activity(
            activity.name,
            mood=next(iter(log.emotions_triggered), "") if log.emotions_triggered else "",
            focus=self._cognitive.focus.quality if self._cognitive else 0.5,
        )
        if artifact:
            self._create_shareable_from_text(
                f"She made something: {artifact.title} ({artifact.artifact_type})",
                context=f"While {activity.name}",
            )

        # === Social tick ===
        social_event = self._social.tick()
        if social_event:
            log.narrative += f" {social_event.description}."
            self._identity.update_from_social_event(social_event)
            self._social.update_arc(social_event.npc_name, "interaction")
            self._social.drain_social_battery()
            if social_event.share_worthy:
                self._create_shareable_from_text(
                    social_event.description,
                    context=f"While {activity.name}"
                )
            # Value alignment with NPC
            npc = next((n for n in self._social._npcs if n.name == social_event.npc_name), None)
            if npc:
                alignment = self._identity.get_npc_value_alignment(npc)
                arc = self._social._arcs.get(social_event.npc_name)
                if arc and alignment != 0:
                    arc.closeness = max(0.1, min(1.0, arc.closeness + alignment * 0.01))

        # === Micro-event (20% chance) ===
        if random.random() < 0.20:
            event = random.choice(MICRO_EVENTS)
            log.narrative += f" {event['text']}."
            if event.get("emotion") and self._emotion_engine:
                for emo, intensity in event["emotion"].items():
                    try:
                        self._emotion_engine.add_emotion(emo, intensity)
                    except Exception:
                        pass
            if event.get("share_worthy"):
                self._create_shareable_from_text(
                    event["text"],
                    context=f"While {activity.name}"
                )

        # === Chaos event ===
        chaos_event = self._chaos.roll(
            current_activity=activity.name,
            energy=self._energy.effective_level,
            regulation=self._affect.regulation.capacity if self._affect else 0.7,
        )
        if chaos_event:
            log.narrative += f" {chaos_event['text']}."
            if chaos_event.get("emotions") and self._emotion_engine:
                for emo, intensity in chaos_event["emotions"].items():
                    try:
                        self._emotion_engine.add_emotion(emo, intensity)
                    except Exception:
                        pass
                for emo, intensity in chaos_event["emotions"].items():
                    self._affect.on_emotion_event(emo, intensity)
            if chaos_event.get("share_worthy"):
                self._create_shareable_from_text(
                    chaos_event["text"],
                    context=f"While {activity.name}",
                )
            if chaos_event.get("type") == "serendipity":
                event = self._life_events.record_event(
                    event_type="surprise",
                    title=chaos_event["text"],
                    description=chaos_event["text"],
                    emotional_impact=chaos_event.get("emotions", {}),
                    share_urgency=0.6,
                    source="chaos_serendipity",
                )
                self._bridge_life_event(event)
            # Apply any state-mutating effect (shadow nudge / acute health).
            effect = chaos_event.get("effect")
            if effect:
                self._apply_chaos_effect(effect)

        # === Dream generation (when sleeping) ===
        if activity.name == "sleeping":
            self._body.on_sleep(
                stress_level=self._affect.stress.level,
                caffeine_boost=self._energy.state.caffeine_boost,
            )
            dream = self._generate_dream()
            if dream:
                self._create_shareable_from_text(dream, context="When she woke up")

        logger.info(f"Activity: {activity.name} - {log.narrative[:50]}...")

        # Mark pipeline digests as stale
        if hasattr(self, '_pipeline') and self._pipeline:
            self._pipeline.on_tick()

        # Check for visual description transitions
        self._check_visual_transition()

    def _apply_chaos_effect(self, effect: dict) -> None:
        """Apply a chaos event's optional state-mutating `effect` to an engine.

        Compact effect schema (all keys but `engine`/`call` are call-specific):
            {"engine": "shadow", "call": "add_unease", "amount": 0.2}
            {"engine": "body", "call": "fall_ill", "kind": "a cold", "severity": 0.4}

        Defensive by design: an unknown engine, missing method, or malformed
        payload is ignored rather than raised. Physical illness/injury is gated
        to non-AI personas (AI personas don't get sick or break bones).
        """
        if not isinstance(effect, dict):
            return
        engine = effect.get("engine")
        call = effect.get("call")
        if not engine or not call:
            return
        try:
            if engine == "shadow":
                if call in ("add_unease", "add_temptation", "add_guilt") and self._shadow:
                    method = getattr(self._shadow, call, None)
                    if callable(method):
                        method(float(effect.get("amount", 0.0)))
            elif engine == "body":
                # Persona-type gate: AI personas don't fall ill or get injured.
                if self._is_ai:
                    return
                if call in ("fall_ill", "get_injured") and self._body:
                    method = getattr(self._body, call, None)
                    if callable(method):
                        method(
                            effect.get("kind", ""),
                            float(effect.get("severity", 0.4)),
                        )
            # Unknown engine → ignore.
        except Exception:
            logger.debug("Chaos effect application failed", exc_info=True)

    def _check_visual_transition(self) -> None:
        """Check if activity/location/outfit changed and trigger visual description update."""
        if not self._persona_id or not self._definition:
            return

        # Get current activity/location from planner
        current_activity = "relaxing"
        current_location = self.get_current_location()
        try:
            plan = self._daily_planner.current_plan
            if plan:
                slot = plan.get_current_slot()
                if slot:
                    current_activity = slot.activity_name or "relaxing"
        except Exception:
            return

        # Resolve current outfit
        try:
            from aura_life.hooks import get_schedule_phase, resolve_outfit_for_context

            outfits = getattr(self._definition, "outfits", {}) or {}
            default_outfit = getattr(self._definition, "appearance_details", {}).get(
                "clothing_style", "casual clothes"
            )
            schedule_phase = get_schedule_phase(self)
            current_outfit = resolve_outfit_for_context(
                activity=current_activity,
                location=current_location,
                time_of_day=schedule_phase,
                outfits=outfits,
                default_outfit=default_outfit,
            )
        except Exception:
            current_outfit = None

        # Compare to last known state
        changed = (
            current_activity != self._last_visual_activity
            or current_location != self._last_visual_location
            or current_outfit != self._last_visual_outfit
        )

        if changed:
            prev_location = self._last_visual_location
            self._last_visual_activity = current_activity
            self._last_visual_location = current_location
            self._last_visual_outfit = current_outfit
            self._trigger_visual_description_update()

            # Fire arrival notification when returning to a user-expected location
            _USER_EXPECTED_LOCATIONS = {"home"}
            if (
                prev_location is not None  # skip on first tick
                and prev_location not in _USER_EXPECTED_LOCATIONS
                and current_location in _USER_EXPECTED_LOCATIONS
            ):
                self._trigger_arrival_message(current_location)

    def _trigger_visual_description_update(self) -> None:
        """Run visual description generation in a background daemon thread.

        At most one at a time. This fires at the end of every activity tick and
        again on resume, and the hook it calls is host LLM + image work; with no
        in-flight guard a hook slower than the tick interval stacked a new thread
        per tick, each closing over the service and the world and pinning both,
        and ``stop()`` neither joined nor cancelled them.
        """
        persona_id = self._persona_id
        definition = self._definition
        life_service = self
        world = self._world

        def _run():
            try:
                from aura_life.hooks import generate_and_update
                generate_and_update(persona_id, definition, life_service, world)
            except Exception as e:
                logger.warning(f"Background visual description update failed: {e}")

        # The check and the spawn must be atomic: this is reachable from the
        # scheduler tick and from the init-tick thread at the same time.
        with self._visual_thread_lock:
            if self._visual_thread is not None and self._visual_thread.is_alive():
                logger.debug("Visual description update already in flight — skipping")
                return
            self._visual_thread = threading.Thread(
                target=_run,
                daemon=True,
                name=f"life-visual-{self._persona_id}",
            )
            self._visual_thread.start()

    def _trigger_arrival_message(self, location: str) -> None:
        """Create a proactive follow-up trigger when the persona arrives at a user-expected location."""
        if not self._persona_id or self._follow_up_provider is None:
            return
        try:
            location_labels = {
                "home": "home",
            }
            label = location_labels.get(location, location)

            fm = self._follow_up_provider(self._persona_id)
            fm.create_trigger(
                trigger_type="ARRIVAL",
                topic=label,
                context=f"Just arrived at {label} after being out.",
                urgency=0.95,
                emotional_weight=0.4,
                delay_hours=random.uniform(1 / 60, 3 / 60),  # 1-3 minutes
            )
            logger.info(f"[ARRIVAL] Trigger created for {self._persona_id}: arrived at {label}")
        except Exception as e:
            logger.warning(f"Failed to create arrival trigger: {e}")

    def _on_goal_tick(self) -> None:
        """Handle goal tick."""
        # Generate daily goal
        self._goal_engine.generate_daily_goal()

        # Check completions
        completed = self._goal_engine.check_goal_completion()
        for goal in completed:
            logger.info(f"Goal completed: {goal.title}")
            event = self._life_events.record_event(
                event_type="achievement",
                title=f"Completed: {goal.title}",
                description=goal.description or goal.title,
                emotional_impact={"proud": 0.4, "satisfied": 0.3},
                share_urgency=0.8,
                source="goal_completion",
            )
            self._bridge_life_event(event)

        # Evaluate motivation — may produce emotional events
        events = self._goal_engine.evaluate_motivation()
        for event in events:
            logger.info(f"Goal event: {event.event_type} - {event.description}")
            if event.emotions:
                # Update real-time EmotionEngine
                if self._emotion_engine:
                    for emotion, intensity in event.emotions.items():
                        try:
                            self._emotion_engine.add_emotion(emotion, intensity)
                        except Exception:
                            pass

                # Persist emotions for multi-day arcs
                self._persist_activity_emotions(
                    f"goal_{event.event_type}",
                    event.emotions
                )

        # Create anticipation from upcoming goals with deadlines
        for goal in self._goal_engine.active_goals:
            if goal.target_date and goal.progress < 0.8:
                hours_until = (goal.target_date - datetime.now()).total_seconds() / 3600
                if 0 < hours_until < 48:  # Within 2 days
                    feeling = "excited" if goal.motivation_level > 0.5 else "anxious"
                    self._memory_time.add_anticipation(
                        event=goal.title,
                        feeling=feeling,
                        intensity=min(0.5, 0.3 + (1.0 - goal.progress) * 0.2),
                        date=goal.target_date,
                    )

        # Save goals
        self._save_goals()

    def _persist_activity_emotions(self, activity_name: str, emotions: dict) -> None:
        """
        Persist emotions from life activities to EmotionPersistence.

        This enables multi-day emotional arcs from autonomous life activities.

        Args:
            activity_name: Name of the activity that caused these emotions
            emotions: Dict of emotion name -> intensity
        """
        try:
            from aura_life.emotion.emotion_persistence import get_emotion_persistence
            from pathlib import Path

            # Extract persona_id from db_path (format: "data/{persona}/life.db").
            # A bare relative filename has NO parent directory name at all:
            # Path("mara.db").parent.name is "" (and Path("./mara.db") normalises
            # to the same thing), never ".". Testing only against "." meant the
            # empty string was accepted as a persona id and the explicitly-passed
            # self._persona_id was never consulted.
            db_parent = Path(self._db_path).parent.name
            persona_id = db_parent if db_parent not in ("", ".") else (self._persona_id or "")
            if not persona_id:
                # No id to write under. Inventing one silently wrote every
                # persona's emotions to a hardcoded name — better to skip and
                # say so than to persist under a made-up identity.
                logger.warning(
                    "Cannot persist activity emotions: no persona_id, and db_path "
                    "%r has no persona directory to derive one from",
                    self._db_path,
                )
                return

            # Use the persona's CONSOLIDATED datastore so emotions are written into
            # memory.db — never a stray "{persona}_emotions.db" in the working dir.
            # (Passing Path(".") here was the bug that scattered *_emotions.db into server/.)
            datastore = None
            try:
                from aura_life.hooks import get_config, get_persona_datastore
                datastore = get_persona_datastore(persona_id, get_config().data_dir)
            except Exception:
                pass
            emotion_persistence = get_emotion_persistence(persona_id, datastore=datastore)

            for emotion, intensity in emotions.items():
                if intensity >= 0.1:  # Only persist significant emotions
                    emotion_persistence.save_emotion(
                        emotion=emotion,
                        intensity=intensity,
                        caused_by=f"While {activity_name}"
                    )

            logger.debug(f"Persisted {len(emotions)} emotions from {activity_name}")
        except Exception as e:
            logger.warning(f"Failed to persist activity emotions: {e}")

    # ============= Database =============

    def _init_database(self) -> None:
        """Initialize database tables."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            # Activity logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    location TEXT,
                    weather TEXT,
                    narrative TEXT,
                    thoughts_generated TEXT,
                    emotions_triggered TEXT,
                    energy_before REAL,
                    energy_after REAL,
                    share_worthy INTEGER DEFAULT 0,
                    shared_with_user INTEGER DEFAULT 0
                )
            """)

            # Goals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    timeframe TEXT NOT NULL,
                    source TEXT,
                    progress REAL DEFAULT 0,
                    motivation_level REAL DEFAULT 1.0,
                    milestones TEXT,
                    completed_milestones TEXT,
                    involves_user INTEGER DEFAULT 0,
                    motivation TEXT,
                    related_activities TEXT,
                    created_at TEXT NOT NULL,
                    last_progress_at TEXT,
                    target_date TEXT,
                    completed_at TEXT,
                    abandoned_at TEXT,
                    abandon_reason TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Location registry table (user/llm-added locations)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_locations (
                    key TEXT PRIMARY KEY,
                    name TEXT,
                    place_type TEXT DEFAULT 'other',
                    description TEXT DEFAULT '',
                    source TEXT DEFAULT 'user',
                    familiarity REAL DEFAULT 0.3,
                    visit_count INTEGER DEFAULT 0,
                    last_visit TEXT
                )
            """)

            # Energy state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_energy_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    level REAL DEFAULT 0.7,
                    fatigue REAL DEFAULT 0,
                    caffeine_boost REAL DEFAULT 0,
                    inspiration_boost REAL DEFAULT 0,
                    social_boost REAL DEFAULT 0,
                    hours_awake REAL DEFAULT 0,
                    last_sleep_time TEXT,
                    last_update TEXT
                )
            """)

            # Shareable experiences table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shareable_experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_log_id INTEGER,
                    content TEXT NOT NULL,
                    thought TEXT,
                    context TEXT,
                    priority REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    shared INTEGER DEFAULT 0,
                    shared_at TEXT,
                    FOREIGN KEY (activity_log_id) REFERENCES activity_logs(id)
                )
            """)

            # Desire state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_desire_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    arousal REAL DEFAULT 0,
                    desire_for_connection REAL DEFAULT 0.3,
                    frustration REAL DEFAULT 0,
                    satisfaction REAL DEFAULT 0.5,
                    last_release TEXT,
                    openness_with_user REAL DEFAULT 0.3,
                    shyness REAL DEFAULT 0.6
                )
            """)

            # Short-term desires table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_short_term_desires (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    source TEXT,
                    related_activities TEXT,
                    related_goal_title TEXT,
                    urgency REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    fulfilled INTEGER DEFAULT 0,
                    fulfilled_at TEXT
                )
            """)

            # Daily plan table (single current plan)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_daily_plan (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    date TEXT NOT NULL,
                    slots TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    weather_at_creation TEXT,
                    revision_notes TEXT
                )
            """)

            # Basic needs state table (single row) — Sustenance engine
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_basic_needs (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    hunger REAL DEFAULT 0,
                    last_meal_time TEXT,
                    showered_today INTEGER DEFAULT 0,
                    morning_routine_done INTEGER DEFAULT 0,
                    meals_today INTEGER DEFAULT 0,
                    nutrition REAL DEFAULT 0.6
                )
            """)
            # Sustenance columns migration (ALTER TABLE for existing DBs)
            for col, col_def in [
                ("meals_today", "INTEGER DEFAULT 0"),
                ("nutrition", "REAL DEFAULT 0.6"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_basic_needs ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Media state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_media_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_book TEXT,
                    book_progress REAL DEFAULT 0,
                    books_finished TEXT DEFAULT '[]',
                    current_show TEXT,
                    show_progress REAL DEFAULT 0,
                    current_music_obsession TEXT
                )
            """)

            # Skills table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_skills (
                    skill_name TEXT PRIMARY KEY,
                    level REAL DEFAULT 0,
                    milestones_reached TEXT DEFAULT '[]',
                    last_practiced TEXT
                )
            """)

            # Room state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_room_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    candle_lit INTEGER DEFAULT 0,
                    music_playing INTEGER DEFAULT 0,
                    window_open INTEGER DEFAULT 0,
                    tidiness REAL DEFAULT 0.7,
                    home_type TEXT DEFAULT 'apartment',
                    comfort REAL DEFAULT 0.7
                )
            """)
            # Habitation columns migration (ALTER TABLE for existing DBs)
            for col, col_def in [
                ("home_type", "TEXT DEFAULT 'apartment'"),
                ("comfort", "REAL DEFAULT 0.7"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_room_state ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Financial state table (single row) — Money engine ledger
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_financial_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    feeling TEXT DEFAULT 'comfortable',
                    saving_for TEXT,
                    recent_splurge TEXT,
                    balance REAL DEFAULT 1200.0,
                    savings REAL DEFAULT 400.0,
                    monthly_income REAL DEFAULT 2600.0,
                    monthly_expenses REAL DEFAULT 1850.0,
                    spending_habit REAL DEFAULT 0.5,
                    enabled INTEGER DEFAULT 1,
                    currency TEXT DEFAULT '$',
                    last_payday TEXT,
                    last_expense_run TEXT,
                    recent_purchases TEXT DEFAULT '[]'
                )
            """)
            # Money-engine columns migration (ALTER TABLE for existing DBs)
            for col, col_def in [
                ("balance", "REAL DEFAULT 1200.0"),
                ("savings", "REAL DEFAULT 400.0"),
                ("monthly_income", "REAL DEFAULT 2600.0"),
                ("monthly_expenses", "REAL DEFAULT 1850.0"),
                ("spending_habit", "REAL DEFAULT 0.5"),
                ("enabled", "INTEGER DEFAULT 1"),
                ("currency", "TEXT DEFAULT '$'"),
                ("last_payday", "TEXT"),
                ("last_expense_run", "TEXT"),
                ("recent_purchases", "TEXT DEFAULT '[]'"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_financial_state ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Career state table (single row) — Job engine
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_career_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    occupation TEXT DEFAULT '',
                    employer TEXT DEFAULT '',
                    employed INTEGER DEFAULT 1,
                    work_days TEXT DEFAULT '[0, 1, 2, 3, 4]',
                    shift_start_hour INTEGER DEFAULT 9,
                    shift_end_hour INTEGER DEFAULT 17,
                    monthly_salary REAL DEFAULT 2600.0,
                    workload REAL DEFAULT 0.5,
                    satisfaction REAL DEFAULT 0.6,
                    days_worked INTEGER DEFAULT 0,
                    last_workday TEXT,
                    recent_work_event TEXT
                )
            """)

            # Errands state table (single row) — Errands engine
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_errands_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    pending TEXT DEFAULT '[]',
                    overdue TEXT DEFAULT '[]',
                    completed_count INTEGER DEFAULT 0,
                    last_added TEXT
                )
            """)

            # Identity facets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_identity_facets (
                    name TEXT PRIMARY KEY,
                    strength REAL DEFAULT 0,
                    evidence TEXT DEFAULT '[]',
                    last_reinforced TEXT
                )
            """)

            # Person perceptions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_person_perceptions (
                    person_name TEXT PRIMARY KEY,
                    is_user INTEGER DEFAULT 0,
                    perceived_gender TEXT DEFAULT '',
                    perceived_age INTEGER DEFAULT 0,
                    trust_level REAL DEFAULT 0.5,
                    emotional_valence REAL DEFAULT 0.5,
                    perceived_traits TEXT DEFAULT '[]',
                    shared_memories TEXT DEFAULT '[]',
                    last_interaction TEXT,
                    interaction_count INTEGER DEFAULT 0
                )
            """)

            # Migration: add perceived_gender/perceived_age columns if missing
            try:
                cursor.execute("SELECT perceived_gender FROM life_person_perceptions LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE life_person_perceptions ADD COLUMN perceived_gender TEXT DEFAULT ''")
                cursor.execute("ALTER TABLE life_person_perceptions ADD COLUMN perceived_age INTEGER DEFAULT 0")

            # Cognitive state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_cognitive_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    focus_quality REAL DEFAULT 0.7,
                    focus_flow_streak INTEGER DEFAULT 0,
                    active_ruminations TEXT DEFAULT '[]',
                    last_monologue TEXT DEFAULT '',
                    last_dream TEXT DEFAULT '',
                    dream_residue_emotion TEXT,
                    dream_residue_intensity REAL DEFAULT 0.0,
                    opinions TEXT DEFAULT '[]'
                )
            """)

            # Shadow state table (single row) — full to_dict() stored as JSON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_shadow_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT
                )
            """)

            # Sanity state table (single row) -- full to_dict() stored as JSON
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_sanity_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT
                )
            """)

            # Body state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_body_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    wellness REAL DEFAULT 0.8,
                    active_conditions TEXT DEFAULT '[]',
                    hormonal_enabled INTEGER DEFAULT 0,
                    hormonal_cycle_day INTEGER DEFAULT 1,
                    comfort_level REAL DEFAULT 0.7,
                    posture_stiffness REAL DEFAULT 0.0,
                    outfit TEXT DEFAULT '',
                    hair_state TEXT DEFAULT 'styled',
                    put_togetherness REAL DEFAULT 0.7,
                    sleep_last_quality REAL DEFAULT 0.7,
                    sleep_insomnia_risk REAL DEFAULT 0.0,
                    sleep_consecutive_poor INTEGER DEFAULT 0,
                    fitness_cardio REAL DEFAULT 0.3,
                    fitness_strength REAL DEFAULT 0.2,
                    fitness_flexibility REAL DEFAULT 0.3,
                    fitness_peak_cardio REAL DEFAULT 0.3,
                    fitness_peak_strength REAL DEFAULT 0.2,
                    fitness_last_cardio TEXT,
                    fitness_last_strength TEXT,
                    fitness_last_flexibility TEXT
                )
            """)

            # Inebriation columns migration (ALTER TABLE for existing DBs)
            for col, col_def in [
                ("inebriation_level", "REAL DEFAULT 0.0"),
                ("inebriation_substance", "TEXT DEFAULT ''"),
                ("inebriation_started_at", "TEXT"),
                ("inebriation_hangover", "REAL DEFAULT 0.0"),
                ("inebriation_last_drink", "TEXT"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_body_state ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Affect state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_affect_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mood_current TEXT DEFAULT 'neutral',
                    mood_intensity REAL DEFAULT 0.0,
                    mood_since TEXT,
                    stress_level REAL DEFAULT 0.0,
                    stress_sources TEXT DEFAULT '[]',
                    stress_coping_capacity REAL DEFAULT 0.7,
                    stress_last_relief TEXT,
                    loneliness_level REAL DEFAULT 0.0,
                    loneliness_desired_baseline REAL DEFAULT 0.5,
                    loneliness_last_meaningful TEXT,
                    loneliness_lifetime_peak REAL DEFAULT 0.0,
                    regulation_capacity REAL DEFAULT 0.7,
                    regulation_baseline REAL DEFAULT 0.7,
                    regulation_last_event TEXT,
                    empathy_susceptibility REAL DEFAULT 0.5,
                    empathy_absorbed_emotion TEXT,
                    empathy_absorbed_intensity REAL DEFAULT 0.0,
                    empathy_fatigue REAL DEFAULT 0.0
                )
            """)

            # Social expansion state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_social_expansion (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    arcs TEXT DEFAULT '[]',
                    obligations TEXT DEFAULT '[]',
                    conflicts TEXT DEFAULT '[]',
                    groups TEXT DEFAULT '[]',
                    battery_charge REAL DEFAULT 0.7,
                    battery_capacity REAL DEFAULT 0.7
                )
            """)

            # Identity expansion: values table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_values (
                    name TEXT PRIMARY KEY,
                    salience REAL DEFAULT 0.5,
                    tested INTEGER DEFAULT 0,
                    formed_at TEXT
                )
            """)

            # Drive state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_drive_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    curiosities TEXT DEFAULT '[]',
                    avoidances TEXT DEFAULT '[]',
                    comfort_zones TEXT DEFAULT '[]'
                )
            """)

            # Behavior state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_behavior_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    routines TEXT DEFAULT '{}',
                    creative_portfolio TEXT DEFAULT '[]',
                    possessions TEXT DEFAULT '[]',
                    neighborhood TEXT DEFAULT '[]',
                    activity_history TEXT DEFAULT '[]'
                )
            """)

            # Expression state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_expression_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    interaction_count INTEGER DEFAULT 0,
                    formality REAL DEFAULT 0.7,
                    avg_message_length TEXT DEFAULT 'measured',
                    emoji_frequency REAL DEFAULT 0.2,
                    humor_density REAL DEFAULT 0.2,
                    vulnerability_openness REAL DEFAULT 0.2,
                    relationship_stage TEXT DEFAULT 'early',
                    last_message_at TEXT,
                    avg_response_time REAL DEFAULT 0.0,
                    response_times TEXT DEFAULT '[]'
                )
            """)

            # Chaos state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_chaos_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    events_today TEXT DEFAULT '[]',
                    last_event_text TEXT DEFAULT '',
                    last_date TEXT DEFAULT '',
                    total_events INTEGER DEFAULT 0
                )
            """)

            # Character evolution state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_character_evolution (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    original_baseline TEXT DEFAULT '{}',
                    current_baseline TEXT DEFAULT '{}',
                    core_traits TEXT DEFAULT '[]',
                    drift_history TEXT DEFAULT '[]',
                    activity_counts TEXT DEFAULT '{}',
                    last_evolution TEXT
                )
            """)

            # Continuity state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_continuity_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    anniversaries TEXT DEFAULT '[]',
                    growth_snapshots TEXT DEFAULT '[]',
                    milestones TEXT DEFAULT '[]',
                    milestones_detected TEXT DEFAULT '[]',
                    life_chapters TEXT DEFAULT '[]',
                    last_daily_tick TEXT,
                    last_weekly_tick TEXT,
                    last_monthly_tick TEXT
                )
            """)
            # Migrate continuity table — add new columns for existing DBs
            for col, col_def in [
                ("life_chapters", "TEXT DEFAULT '[]'"),
                ("last_monthly_tick", "TEXT"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_continuity_state ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Memory & Time state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_memory_time_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    time_speed REAL DEFAULT 0.5,
                    time_last_assessment TEXT,
                    seasonal_feeling TEXT DEFAULT '',
                    season_memory_count TEXT DEFAULT '{}',
                    years_experienced INTEGER DEFAULT 0,
                    nostalgia_log TEXT DEFAULT '[]',
                    life_chapters TEXT DEFAULT '[]',
                    rhythms TEXT DEFAULT '[]',
                    anticipations TEXT DEFAULT '[]',
                    tick_count INTEGER DEFAULT 0
                )
            """)

            # Life events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    emotional_impact TEXT,
                    share_urgency REAL DEFAULT 0.7,
                    created_at TEXT NOT NULL,
                    shared INTEGER DEFAULT 0,
                    shared_at TEXT,
                    source TEXT
                )
            """)

            # Migrate existing life_goals table — add columns that may be missing
            for col, col_def in [
                ("motivation_level", "REAL DEFAULT 1.0"),
                ("last_progress_at", "TEXT"),
                ("abandoned_at", "TEXT"),
                ("abandon_reason", "TEXT DEFAULT ''"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_goals ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # World state table (single row) — persists current location
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_world_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_location TEXT DEFAULT 'home'
                )
            """)

            # Transit state table (single row) — active transit overlay
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_transit_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    phase TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    preparing_started_at TEXT,
                    departure_at TEXT,
                    expected_arrival_at TEXT,
                    arrived_at TEXT
                )
            """)

            # User calendar table — events extracted from conversation
            self._ensure_calendar_schema(conn)

            # Place-identity volatile state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_location_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_city TEXT DEFAULT '',
                    current_lat REAL,
                    current_lon REAL,
                    current_timezone TEXT DEFAULT '',
                    on_trip INTEGER DEFAULT 0,
                    trip_destination TEXT DEFAULT '',
                    trip_returns_at TEXT DEFAULT '',
                    trip_reason TEXT DEFAULT '',
                    weather_code INTEGER,
                    weather_label TEXT DEFAULT '',
                    weather_temp_c REAL,
                    weather_is_day INTEGER DEFAULT 1,
                    weather_fetched_at TEXT DEFAULT '',
                    weather_source TEXT DEFAULT 'simulated'
                )
            """)

            # Migration: add trip_last_roll_date column if missing (older DBs).
            try:
                cursor.execute(
                    "ALTER TABLE life_location_state ADD COLUMN trip_last_roll_date TEXT DEFAULT ''"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.commit()

    def _load_state(self) -> None:
        """Load persisted state from database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Load energy state (pass sleep_schedule for persona-specific timing)
            cursor.execute("SELECT * FROM life_energy_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._energy = EnergySystem.from_dict(
                    dict(row),
                    sleep_schedule=self._sleep_schedule,
                    core_traits=self._core_traits,
                    now=self._world_clock(),
                )
                # Reapply the AI flag after reload — an AI never sleeps / carries no
                # sleep-physiology (from_dict doesn't persist persona_type).
                self._energy._is_ai = self._is_ai
            else:
                # Insert default
                cursor.execute("""
                    INSERT INTO life_energy_state (id, level, fatigue, last_update)
                    VALUES (1, 0.7, 0, ?)
                """, (datetime.now().isoformat(),))

            # Load recent activities
            cursor.execute("""
                SELECT * FROM activity_logs
                ORDER BY started_at DESC
                LIMIT 20
            """)
            self._recent_activities = [
                ActivityLog.from_dict(dict(row))
                for row in cursor.fetchall()
            ]

            # Load goals
            cursor.execute("SELECT * FROM life_goals")
            goals = [Goal.from_dict(dict(row)) for row in cursor.fetchall()]
            self._goal_engine.load_goals(goals)

            # Load shareable experiences
            cursor.execute("""
                SELECT * FROM shareable_experiences
                WHERE shared = 0
                ORDER BY created_at DESC
                LIMIT 10
            """)
            self._shareable_queue = [
                ShareableExperience.from_dict(dict(row))
                for row in cursor.fetchall()
            ]

            # Load desire state
            cursor.execute("SELECT * FROM life_desire_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._desire_system = DesireSystem.from_dict(dict(row), core_traits=self._core_traits, rng=self._rng)
            else:
                # Insert default
                cursor.execute("""
                    INSERT INTO life_desire_state (id, arousal, satisfaction, shyness)
                    VALUES (1, 0, 0.5, 0.6)
                """)

            # Load daily plan
            cursor.execute("SELECT * FROM life_daily_plan WHERE id = 1")
            row = cursor.fetchone()
            plan = None
            if row:
                plan = DailyPlan.from_dict(dict(row))

            # Load short-term desires
            cursor.execute("SELECT * FROM life_short_term_desires WHERE fulfilled = 0")
            desires = [ShortTermDesire.from_dict(dict(r)) for r in cursor.fetchall()]

            self._daily_planner.load_state(plan, desires)

            # Load locations (must come after planner init so we can update available keys)
            self._load_locations(cursor)

            # Load world location (must come after plan so we can fallback to plan slot)
            self._load_world(cursor)

            # Load basic needs (Sustenance engine)
            cursor.execute("SELECT * FROM life_basic_needs WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._sustenance = SustenanceSystem.from_dict(dict(row))
                self._basic_needs = self._sustenance.state  # keep the alias

            # Load media state
            cursor.execute("SELECT * FROM life_media_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                books_finished_raw = row["books_finished"] or "[]"
                try:
                    books_finished = json.loads(books_finished_raw)
                except (json.JSONDecodeError, TypeError):
                    books_finished = []
                self._media = MediaState(
                    current_book=row["current_book"],
                    book_progress=row["book_progress"] or 0.0,
                    books_finished=books_finished,
                    current_show=row["current_show"],
                    show_progress=row["show_progress"] or 0.0,
                    current_music_obsession=row["current_music_obsession"],
                )
            else:
                # First run — initialize from preferences
                self._media = self._init_media_state()

            # Load room state (Habitation engine)
            cursor.execute("SELECT * FROM life_room_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._habitation = HabitationSystem.from_dict(dict(row), rng=self._rng)
                self._room_state = self._habitation.state  # keep the alias

            # Load financial state
            cursor.execute("SELECT * FROM life_financial_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._finance = FinanceSystem.from_dict(dict(row), core_traits=self._core_traits, rng=self._rng, now=self._world_clock()())
                self._financial = self._finance.state  # keep the alias pointing at loaded state

            # Load career state
            cursor.execute("SELECT * FROM life_career_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                _occupation = self._occupation or (getattr(self._definition, 'occupation', '') if self._definition else '')
                self._career = CareerSystem.from_dict(dict(row), occupation=_occupation, rng=self._rng)
                if self._career.monthly_salary > 0:
                    self._finance.state.monthly_income = self._career.monthly_salary

            # Load errands state
            cursor.execute("SELECT * FROM life_errands_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._errands = ErrandsSystem.from_dict(dict(row), rng=self._rng)

            # Load skills
            cursor.execute("SELECT * FROM life_skills")
            for row in cursor.fetchall():
                milestones_raw = row["milestones_reached"] or "[]"
                try:
                    milestones = json.loads(milestones_raw)
                except (json.JSONDecodeError, TypeError):
                    milestones = []
                self._skills[row["skill_name"]] = SkillProgress(
                    skill_name=row["skill_name"],
                    level=row["level"],
                    milestones_reached=milestones,
                    last_practiced=datetime.fromisoformat(row["last_practiced"]) if row["last_practiced"] else None,
                )

            # Load identity (facets + perceptions)
            self._load_identity(cursor)

            # Load affect state
            self._load_affect(cursor)

            # Load body state
            self._load_body(cursor)

            # Load cognitive state
            self._load_cognitive(cursor)

            # Load shadow state
            self._load_shadow(cursor)

            # Load sanity state (after affect and shadow: the couplings read both)
            self._load_sanity(cursor)

            # Load drive state
            self._load_drive(cursor)

            # Load social expansion state
            self._load_social_expansion(cursor)

            # Load behavior state
            self._load_behavior(cursor)

            # Load memory & time state
            self._load_memory_time(cursor)

            # Load expression state
            self._load_expression(cursor)

            # Load continuity state
            self._load_continuity(cursor)

            # Load character evolution state
            self._load_character_evolution(cursor)

            # Load chaos state
            self._load_chaos(cursor)

            # Load life events
            self._load_life_events(cursor)

            # Load transit state (must come after world load so fast-forward can move_to)
            self._load_transit(cursor)

            # Load place-identity volatile state (weather, trip, current city)
            self._load_place_state(cursor)

            # Seed backstory chapter if this is first load (no chapters yet)
            if self._definition and not self._continuity._life_chapters:
                self._continuity.seed_backstory(
                    background=getattr(self._definition, 'backstory', '') or
                               getattr(self._definition, 'system_prompt', '')[:200] if self._definition else '',
                    persona_name=self._definition.name if self._definition else '',
                )

            # Seed taste profiles from persona definition if none exist
            if self._definition and not self._identity._taste:
                taste_seeds = getattr(self._definition, 'taste_seeds', {})
                if taste_seeds:
                    for domain, prefs in taste_seeds.items():
                        self._identity.update_taste(domain, prefs[0], positive=True)

            conn.commit()

        # Deferred catch-up save: if _load_place_state reverted an overdue trip, persist now
        # (cannot save inside _load_place_state because the cursor above was still open).
        if getattr(self, "_trip_catchup_pending_save", False):
            self._trip_catchup_pending_save = False
            self._save_place_state()

        # Apply the user-location cap to what came back off disk too, or a database
        # written before the cap simply reloads its whole registry on every start.
        # Deferred out of the block above for the same reason: it writes, and the
        # cursor was still open.
        self._prune_user_locations()

    def _save_state(self) -> None:
        """Save state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            # Save energy state
            energy_data = self._energy.to_dict()
            cursor.execute("""
                UPDATE life_energy_state SET
                    level = ?,
                    fatigue = ?,
                    caffeine_boost = ?,
                    inspiration_boost = ?,
                    social_boost = ?,
                    hours_awake = ?,
                    last_sleep_time = ?,
                    last_update = ?
                WHERE id = 1
            """, (
                energy_data["level"],
                energy_data["fatigue"],
                energy_data["caffeine_boost"],
                energy_data["inspiration_boost"],
                energy_data["social_boost"],
                energy_data["hours_awake"],
                energy_data["last_sleep_time"],
                energy_data["last_update"],
            ))

            # Save desire state
            desire_data = self._desire_system.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_desire_state
                (id, arousal, desire_for_connection, frustration, satisfaction,
                 last_release, openness_with_user, shyness)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """, (
                desire_data["arousal"],
                desire_data["desire_for_connection"],
                desire_data["frustration"],
                desire_data["satisfaction"],
                desire_data["last_release"],
                desire_data["openness_with_user"],
                desire_data["shyness"],
            ))

            conn.commit()

        # Save goals
        self._save_goals()

        # Save plan and desires
        self._save_plan()

        # Save world location and locations registry
        self._save_world()
        self._save_all_locations()

        # Save new subsystems
        self._save_needs_state()
        self._save_media_state()
        self._save_room_state()
        self._save_financial_state()
        self._save_career_state()
        self._save_errands_state()
        self._save_skills()
        self._save_identity()
        self._save_affect()
        self._save_body()
        self._save_cognitive()
        self._save_shadow()
        self._save_sanity()
        self._save_drive()
        self._save_social_expansion()
        self._save_behavior()
        self._save_memory_time()
        self._save_expression()
        self._save_continuity()
        self._save_character_evolution()
        self._save_chaos()
        self._save_life_events()
        self._save_transit()

    def _record_activity(self, log: ActivityLog) -> None:
        """Record an activity to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            data = log.to_dict()
            cursor.execute("""
                INSERT INTO activity_logs
                (activity_name, category, started_at, ended_at, location, weather,
                 narrative, thoughts_generated, emotions_triggered, energy_before,
                 energy_after, share_worthy, shared_with_user)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["activity_name"],
                data["category"],
                data["started_at"],
                data["ended_at"],
                data["location"],
                data["weather"],
                data["narrative"],
                data["thoughts_generated"],
                data["emotions_triggered"],
                data["energy_before"],
                data["energy_after"],
                1 if data["share_worthy"] else 0,
                1 if data["shared_with_user"] else 0,
            ))

            log.id = cursor.lastrowid

            # Retention: one row lands here every activity tick (~72/day) and
            # only the newest 20 are ever read back, so without this the table is
            # pure write-only growth on the user's disk.
            cursor.execute("""
                DELETE FROM activity_logs
                WHERE id NOT IN (
                    SELECT id FROM activity_logs
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                )
            """, (ACTIVITY_LOG_RETENTION,))

            conn.commit()

        # Add to recent
        self._recent_activities.insert(0, log)
        if len(self._recent_activities) > 20:
            self._recent_activities = self._recent_activities[:20]

    def _save_goals(self) -> None:
        """Save goals to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            # Clear and rewrite (simple approach)
            cursor.execute("DELETE FROM life_goals")

            # This is a DELETE + full reinsert on every goal tick, so the write
            # cost is the size of the history. Bound it here rather than relying
            # on GoalEngine's own in-memory cap: the table is this method's
            # responsibility. Both lists are append-ordered, so [-N:] is newest.
            all_goals = (
                self._goal_engine.active_goals
                + self._goal_engine.completed_goals[-GOAL_HISTORY_PERSISTED_MAX:]
                + self._goal_engine.abandoned_goals[-GOAL_HISTORY_PERSISTED_MAX:]
            )
            for goal in all_goals:
                data = goal.to_dict()
                cursor.execute("""
                    INSERT INTO life_goals
                    (title, description, timeframe, source, progress, motivation_level,
                     milestones, completed_milestones, involves_user, motivation,
                     related_activities, created_at, last_progress_at, target_date,
                     completed_at, abandoned_at, abandon_reason, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["title"],
                    data["description"],
                    data["timeframe"],
                    data["source"],
                    data["progress"],
                    data["motivation_level"],
                    data["milestones"],
                    data["completed_milestones"],
                    1 if data["involves_user"] else 0,
                    data["motivation"],
                    data["related_activities"],
                    data["created_at"],
                    data["last_progress_at"],
                    data["target_date"],
                    data["completed_at"],
                    data["abandoned_at"],
                    data["abandon_reason"],
                    1 if data["is_active"] else 0,
                ))

            conn.commit()

    def _save_plan(self) -> None:
        """Save daily plan and desires to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            # Save current plan
            plan = self._daily_planner.current_plan
            if plan:
                data = plan.to_dict()
                cursor.execute("""
                    INSERT OR REPLACE INTO life_daily_plan
                    (id, date, slots, created_at, weather_at_creation, revision_notes)
                    VALUES (1, ?, ?, ?, ?, ?)
                """, (
                    data["date"],
                    data["slots"],
                    data["created_at"],
                    data["weather_at_creation"],
                    data["revision_notes"],
                ))

            # Save desires (clear and rewrite active ones)
            cursor.execute("DELETE FROM life_short_term_desires")
            for desire in self._daily_planner.all_desires:
                data = desire.to_dict()
                cursor.execute("""
                    INSERT INTO life_short_term_desires
                    (title, description, source, related_activities, related_goal_title,
                     urgency, created_at, expires_at, fulfilled, fulfilled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data["title"],
                    data["description"],
                    data["source"],
                    data["related_activities"],
                    data["related_goal_title"],
                    data["urgency"],
                    data["created_at"],
                    data["expires_at"],
                    1 if data["fulfilled"] else 0,
                    data["fulfilled_at"],
                ))

            conn.commit()

    def _create_shareable(self, log: ActivityLog, share_context: Optional[str] = None) -> None:
        """Create a shareable experience from an activity."""
        context_str = share_context or f"While {log.activity_name} at {log.location}"

        experience = ShareableExperience(
            activity_log_id=log.id,
            content=log.narrative,
            thought=log.thoughts_generated[0] if log.thoughts_generated else "",
            context=context_str,
            priority=0.5 + random.random() * 0.3,
            created_at=datetime.now(),
        )

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            data = experience.to_dict()
            cursor.execute("""
                INSERT INTO shareable_experiences
                (activity_log_id, content, thought, context, priority, created_at, shared)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (
                data["activity_log_id"],
                data["content"],
                data["thought"],
                data["context"],
                data["priority"],
                data["created_at"],
            ))

            experience.id = cursor.lastrowid
            conn.commit()

        self._append_shareable(experience)

    def _append_shareable(self, experience: ShareableExperience) -> None:
        """Append to the shareable queue, capping it to the newest N.

        Runtime appends are otherwise unbounded (only reload trims via LIMIT 10),
        so on a long-running server the queue would grow without bound.
        """
        self._shareable_queue.append(experience)
        if len(self._shareable_queue) > SHAREABLE_QUEUE_MAX:
            self._shareable_queue = self._shareable_queue[-SHAREABLE_QUEUE_MAX:]

    def _save_shareable(self) -> None:
        """Save shareable experiences, then drop long-since-shared ones."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            for exp in self._shareable_queue:
                if exp.id:
                    cursor.execute("""
                        UPDATE shareable_experiences
                        SET shared = ?, shared_at = ?
                        WHERE id = ?
                    """, (
                        1 if exp.shared else 0,
                        exp.shared_at.isoformat() if exp.shared_at else None,
                        exp.id,
                    ))

            # Retention: the load path only ever reads `shared = 0`, so a row
            # stays on disk forever the moment it is shared. Unshared rows are
            # still queued work and are never pruned by age.
            cutoff = (datetime.now() - timedelta(days=SHAREABLE_RETENTION_DAYS)).isoformat()
            cursor.execute("""
                DELETE FROM shareable_experiences
                WHERE shared = 1 AND COALESCE(shared_at, created_at) < ?
            """, (cutoff,))

            conn.commit()

    def _get_unshared_experiences(self) -> List[ShareableExperience]:
        """Get experiences not yet shared."""
        return [exp for exp in self._shareable_queue if not exp.shared]

    # ============= New Subsystem Helpers =============

    def _create_shareable_from_text(self, text: str, context: str = "") -> None:
        """Create a shareable experience from plain text (not an ActivityLog)."""
        experience = ShareableExperience(
            content=text,
            context=context,
            priority=0.4 + self._random.random() * 0.3,
            created_at=datetime.now(),
        )

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = experience.to_dict()
            cursor.execute("""
                INSERT INTO shareable_experiences
                (activity_log_id, content, thought, context, priority, created_at, shared)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (None, data["content"], "", data["context"], data["priority"], data["created_at"]))
            experience.id = cursor.lastrowid
            conn.commit()

        self._append_shareable(experience)

    def _bridge_life_event(self, event: LifeEvent) -> None:
        """Bridge a life event to proactive messaging and shareable queue.

        If share_urgency >= 0.6, creates a follow-up trigger so the persona
        can reach out proactively.  Also boosts the priority of the most
        recent shareable so it surfaces in conversation.
        """
        if event.share_urgency >= 0.6 and self._follow_up_provider is not None:
            if not self._life_trigger_cooled_down("excitement_share", datetime.now()):
                return  # Still cooling down
            try:
                fm = self._follow_up_provider(self._persona_id)
                fm.create_trigger(
                    trigger_type="EXCITEMENT_SHARE",
                    topic=event.title,
                    context=event.description,
                    urgency=min(event.share_urgency, 0.85),
                    emotional_weight=max(event.emotional_impact.values()) if event.emotional_impact else 0.5,
                    prompt_hint=(
                        f"Something specific happened you're excited about: {event.title}. "
                        f"Share the concrete detail — what actually happened — not a vague "
                        f"'I had an epiphany' or 'I cracked the code'."
                    ),
                )
                self._record_life_trigger_cooldown("excitement_share", datetime.now())
            except Exception:
                # Matches the sibling trigger handlers: without this the trigger
                # can be permanently dead in production with zero signal.
                logger.warning(
                    "Life trigger: EXCITEMENT_SHARE dispatch failed", exc_info=True
                )

        # Boost priority of the most recent shareable (just created by caller)
        if self._shareable_queue:
            self._shareable_queue[-1].priority = min(0.95, event.share_urgency + 0.1)

    def _update_skill(self, skill_name: str, increment: float, log: ActivityLog) -> None:
        """Advance a skill via the Skills engine; route any new milestones to
        shareables + life events (engines never call each other directly)."""
        new_milestones = self._skills_system.practice(
            skill_name, increment, SKILL_MILESTONES.get(skill_name, [])
        )
        for milestone_text in new_milestones:
            self._create_shareable_from_text(
                milestone_text,
                context=f"After practicing {skill_name}"
            )
            event = self._life_events.record_event(
                event_type="achievement",
                title=milestone_text,
                description=milestone_text,
                emotional_impact={"proud": 0.3},
                share_urgency=0.6,
                source="skill_milestone",
            )
            self._bridge_life_event(event)
            logger.info(f"Skill milestone: {skill_name} - {milestone_text}")

        # Persist skills
        self._save_skills()

    def _record_finished_book(self, title: str) -> None:
        """Record a finished book, without duplicates and without unbounded growth.

        ``_pick_new_book`` deliberately falls back to ``random.choice(books)`` once
        every title has been read, so the same title finishes again and again. The
        list is JSON-serialized into ``life_media_state`` on every save, so a plain
        append grew both memory and disk forever. Evicting the oldest at the cap
        only means a long-ago title counts as unread again.
        """
        if not title:
            return
        if title in self._media.books_finished:
            return
        self._media.books_finished.append(title)
        if len(self._media.books_finished) > BOOKS_FINISHED_MAX:
            self._media.books_finished = self._media.books_finished[-BOOKS_FINISHED_MAX:]

    def _pick_new_book(self) -> Optional[str]:
        """Pick a new book from preferences that hasn't been finished yet."""
        books = self._media_preferences.get("books", [])
        unread = [b for b in books if b not in self._media.books_finished]
        if unread:
            return random.choice(unread)
        # All read — re-read a favorite
        return random.choice(books) if books else None

    def _generate_dream(self) -> Optional[str]:
        """Generate a dream from recent activities and emotions."""
        if random.random() > 0.4:
            return None  # Not every sleep produces a memorable dream

        ingredients = []
        for act in self._recent_activities[:5]:
            ingredients.append(act.activity_name)

        # Add current book/show if reading/watching
        if self._media.current_book:
            ingredients.append(self._media.current_book)
        if self._media.current_show:
            ingredients.append(self._media.current_show)

        if len(ingredients) < 2:
            return None

        elements = random.sample(ingredients, min(2, len(ingredients)))
        template = random.choice(DREAM_TEMPLATES)
        return template.format(*elements)

    def _save_skills(self) -> None:
        """Save skill progress to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            for name, skill in self._skills.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO life_skills
                    (skill_name, level, milestones_reached, last_practiced)
                    VALUES (?, ?, ?, ?)
                """, (
                    name,
                    skill.level,
                    json.dumps(skill.milestones_reached),
                    skill.last_practiced.isoformat() if skill.last_practiced else None,
                ))
            conn.commit()

    def _save_identity(self) -> None:
        """Save identity facets and person perceptions to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            # Save facets (clear and rewrite)
            cursor.execute("DELETE FROM life_identity_facets")
            for name, facet in self._identity._facets.items():
                cursor.execute("""
                    INSERT INTO life_identity_facets (name, strength, evidence, last_reinforced)
                    VALUES (?, ?, ?, ?)
                """, (
                    name,
                    facet.strength,
                    json.dumps(facet.evidence),
                    facet.last_reinforced.isoformat() if facet.last_reinforced else None,
                ))

            # Save perceptions (clear and rewrite)
            cursor.execute("DELETE FROM life_person_perceptions")
            for key, p in self._identity._perceptions.items():
                cursor.execute("""
                    INSERT INTO life_person_perceptions
                    (person_name, is_user, perceived_gender, perceived_age,
                     trust_level, emotional_valence,
                     perceived_traits, shared_memories, last_interaction, interaction_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    key,
                    1 if p.is_user else 0,
                    p.perceived_gender,
                    p.perceived_age,
                    p.trust_level,
                    p.emotional_valence,
                    json.dumps(p.perceived_traits),
                    json.dumps(p.shared_memories),
                    p.last_interaction.isoformat() if p.last_interaction else None,
                    p.interaction_count,
                ))

            # Save values (clear and rewrite)
            cursor.execute("DELETE FROM life_values")
            for name, v in self._identity._values.items():
                cursor.execute("""
                    INSERT INTO life_values (name, salience, tested, formed_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    name,
                    v.salience,
                    1 if v.tested_by_adversity else 0,
                    v.formed_at.isoformat() if v.formed_at else None,
                ))

            # Save behavioral tendencies as JSON blob
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_behavioral_tendencies (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    data TEXT DEFAULT '{}'
                )
            """)
            tendencies_data = json.dumps({
                name: {
                    "baseline": t.baseline,
                    "current": t.current,
                    "last_surfaced": t.last_surfaced.isoformat() if t.last_surfaced else None,
                }
                for name, t in self._identity._tendencies.items()
            })
            cursor.execute(
                "INSERT OR REPLACE INTO life_behavioral_tendencies (id, data) VALUES (1, ?)",
                (tendencies_data,),
            )

            conn.commit()

    def _load_identity(self, cursor) -> None:
        """Load identity facets and person perceptions from database."""
        from .models import IdentityFacet, PersonPerception, ValueBelief
        from .identity.identity_system import VALUE_ACTIVITY_ALIGNMENT

        # Load facets
        cursor.execute("SELECT * FROM life_identity_facets")
        facets = {}
        for row in cursor.fetchall():
            evidence_raw = row["evidence"] or "[]"
            try:
                evidence = json.loads(evidence_raw)
            except (json.JSONDecodeError, TypeError):
                evidence = []
            facets[row["name"]] = IdentityFacet(
                name=row["name"],
                strength=row["strength"],
                evidence=evidence,
                last_reinforced=datetime.fromisoformat(row["last_reinforced"]) if row["last_reinforced"] else None,
            )

        # Load perceptions
        cursor.execute("SELECT * FROM life_person_perceptions")
        perceptions = {}
        for row in cursor.fetchall():
            traits_raw = row["perceived_traits"] or "[]"
            memories_raw = row["shared_memories"] or "[]"
            try:
                traits = json.loads(traits_raw)
            except (json.JSONDecodeError, TypeError):
                traits = []
            try:
                memories = json.loads(memories_raw)
            except (json.JSONDecodeError, TypeError):
                memories = []
            perceptions[row["person_name"]] = PersonPerception(
                person_name=row["person_name"],
                is_user=bool(row["is_user"]),
                perceived_gender=row["perceived_gender"] if "perceived_gender" in row.keys() else "",
                perceived_age=row["perceived_age"] if "perceived_age" in row.keys() else 0,
                trust_level=row["trust_level"],
                emotional_valence=row["emotional_valence"],
                perceived_traits=traits,
                shared_memories=memories,
                last_interaction=datetime.fromisoformat(row["last_interaction"]) if row["last_interaction"] else None,
                interaction_count=row["interaction_count"],
            )

        # Apply loaded data if we have any
        if facets:
            self._identity._facets = facets
        if perceptions:
            self._identity._perceptions = perceptions
            # Ensure user perception exists
            if "__user__" not in self._identity._perceptions:
                self._identity._perceptions["__user__"] = PersonPerception(
                    person_name="the user",
                    is_user=True,
                    trust_level=0.5,
                    emotional_valence=0.6,
                )

        # Load values
        try:
            cursor.execute("SELECT * FROM life_values")
            loaded_values = {}
            for row in cursor.fetchall():
                name = row["name"]
                loaded_values[name] = ValueBelief(
                    name=name,
                    salience=row["salience"],
                    tested_by_adversity=bool(row["tested"]),
                    formed_at=datetime.fromisoformat(row["formed_at"]) if row["formed_at"] else None,
                    aligned_tags=VALUE_ACTIVITY_ALIGNMENT.get(name, []),
                )
            if loaded_values:
                self._identity._values = loaded_values
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet — normal on first run
        except Exception:
            # A row-parse failure, a bad formed_at, a ValueBelief that won't
            # build: real corruption, not a first run. The broad catch here
            # discarded all of it with no log at any level.
            logger.warning("Failed to load identity values", exc_info=True)

        # Load behavioral tendencies
        try:
            from .models import BehavioralTendency
            from .identity.identity_system import TENDENCY_NAMES
            cursor.execute("SELECT data FROM life_behavioral_tendencies WHERE id = 1")
            row = cursor.fetchone()
            if row and row["data"]:
                td = json.loads(row["data"])
                for name in TENDENCY_NAMES:
                    if name in td:
                        entry = td[name]
                        self._identity._tendencies[name] = BehavioralTendency(
                            name=name,
                            baseline=entry.get("baseline", 0.1),
                            current=entry.get("current", entry.get("baseline", 0.1)),
                            last_surfaced=datetime.fromisoformat(entry["last_surfaced"]) if entry.get("last_surfaced") else None,
                        )
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet — normal on first run
        except Exception:
            logger.warning("Failed to load behavioral tendencies", exc_info=True)

    def _save_affect(self) -> None:
        """Save affect state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._affect.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_affect_state
                (id, mood_current, mood_intensity, mood_since,
                 stress_level, stress_sources, stress_coping_capacity, stress_last_relief,
                 loneliness_level, loneliness_desired_baseline, loneliness_last_meaningful, loneliness_lifetime_peak,
                 regulation_capacity, regulation_baseline, regulation_last_event,
                 empathy_susceptibility, empathy_absorbed_emotion, empathy_absorbed_intensity, empathy_fatigue)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["mood_current"], data["mood_intensity"], data["mood_since"],
                data["stress_level"], data["stress_sources"], data["stress_coping_capacity"], data["stress_last_relief"],
                data["loneliness_level"], data["loneliness_desired_baseline"], data["loneliness_last_meaningful"], data["loneliness_lifetime_peak"],
                data["regulation_capacity"], data["regulation_baseline"], data["regulation_last_event"],
                data["empathy_susceptibility"], data["empathy_absorbed_emotion"], data["empathy_absorbed_intensity"], data["empathy_fatigue"],
            ))
            conn.commit()

    def _load_affect(self, cursor) -> None:
        """Load affect state from database."""
        try:
            cursor.execute("SELECT * FROM life_affect_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                data = dict(row)
                self._affect = AffectSystem.from_dict(
                    data,
                    core_traits=getattr(self._definition, 'core_traits', []) if self._definition else [],
                    emotional_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
                )
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_cognitive(self) -> None:
        """Save cognitive state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._cognitive.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_cognitive_state
                (id, focus_quality, focus_flow_streak, active_ruminations,
                 last_monologue, last_dream, dream_residue_emotion, dream_residue_intensity, opinions)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["focus_quality"], data["focus_flow_streak"],
                data["active_ruminations"], data["last_monologue"],
                data["last_dream"], data["dream_residue_emotion"],
                data["dream_residue_intensity"], data["opinions"],
            ))
            conn.commit()

    def _load_cognitive(self, cursor) -> None:
        """Load cognitive state from database."""
        try:
            cursor.execute("SELECT * FROM life_cognitive_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._cognitive = CognitiveSystem.from_dict(
                    dict(row), core_traits=self._core_traits,
                    intrusive_thought_themes=getattr(self._definition, 'intrusive_thought_themes', []) if self._definition else [],
                    rng=self._rng,
                )
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_shadow(self) -> None:
        """Save shadow state to database (full to_dict() as JSON)."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = json.dumps(self._shadow.to_dict())
            cursor.execute("""
                INSERT OR REPLACE INTO life_shadow_state (id, data)
                VALUES (1, ?)
            """, (data,))
            conn.commit()

    def _load_shadow(self, cursor) -> None:
        """Load shadow state from database. Keep the constructed instance on a
        fresh DB (no row) so the profile-seeded traits survive."""
        try:
            cursor.execute("SELECT data FROM life_shadow_state WHERE id = 1")
            row = cursor.fetchone()
            if row and row["data"]:
                self._shadow = ShadowSystem.from_dict(json.loads(row["data"]))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_sanity(self) -> None:
        """Save sanity state to database (full to_dict() as JSON)."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._sanity.to_dict()
            data["coupled_state"] = self._sanity_coupled_state   # glue's, not the engine's
            data = json.dumps(data)
            cursor.execute("""
                INSERT OR REPLACE INTO life_sanity_state (id, data)
                VALUES (1, ?)
            """, (data,))
            conn.commit()

    def _load_sanity(self, cursor) -> None:
        """Load sanity state from database. Keep the constructed instance on a
        fresh DB (no row); a stored row resumes number, state, flag and pending
        events without a draw, plus the word the couplings were last applied
        for. Affect's and shadow's rows already carry their sides of the
        couplings; the pull is held again from that word only for a shadow
        row that predates it (a no-op when the row has it)."""
        try:
            cursor.execute("SELECT data FROM life_sanity_state WHERE id = 1")
            row = cursor.fetchone()
            if row and row["data"]:
                data = json.loads(row["data"])
                self._sanity = SanitySystem.from_dict(data)
                self._sanity_ticked_at = self._world_clock()()
                coupled = data.get("coupled_state")
                self._sanity_coupled_state = coupled if coupled in SANITY_STATES else self._sanity.state
                self._hold_sanity_restraint(self._sanity_coupled_state)
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_drive(self) -> None:
        """Save drive state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._drive.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_drive_state
                (id, curiosities, avoidances, comfort_zones)
                VALUES (1, ?, ?, ?)
            """, (data["curiosities"], data["avoidances"], data["comfort_zones"]))
            conn.commit()

    def _load_drive(self, cursor) -> None:
        """Load drive state from database."""
        try:
            cursor.execute("SELECT * FROM life_drive_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._drive = DriveSystem.from_dict(dict(row), core_traits=self._core_traits, rng=self._rng)
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_social_expansion(self) -> None:
        """Save social expansion state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._social.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_social_expansion
                (id, arcs, obligations, conflicts, groups, battery_charge, battery_capacity)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                data["arcs"], data["obligations"], data["conflicts"],
                data["groups"], data["battery_charge"], data["battery_capacity"],
            ))
            conn.commit()

    def _load_social_expansion(self, cursor) -> None:
        """Load social expansion state from database."""
        try:
            cursor.execute("SELECT * FROM life_social_expansion WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._social.load_expansion(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_behavior(self) -> None:
        """Save behavior state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._behavior.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_behavior_state
                (id, routines, creative_portfolio, possessions, neighborhood, activity_history)
                VALUES (1, ?, ?, ?, ?, ?)
            """, (
                data["routines"], data["creative_portfolio"],
                data["possessions"], data["neighborhood"],
                data["activity_history"],
            ))
            conn.commit()

    def _load_behavior(self, cursor) -> None:
        """Load behavior state from database."""
        try:
            cursor.execute("SELECT * FROM life_behavior_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._behavior = BehaviorSystem.from_dict(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_memory_time(self) -> None:
        """Save memory & time state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._memory_time.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_memory_time_state
                (id, time_speed, time_last_assessment, seasonal_feeling,
                 season_memory_count, years_experienced, nostalgia_log,
                 life_chapters, rhythms, anticipations, tick_count)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["time_speed"], data["time_last_assessment"],
                data["seasonal_feeling"], data["season_memory_count"],
                data["years_experienced"], data["nostalgia_log"],
                data["life_chapters"], data["rhythms"],
                data["anticipations"], data["tick_count"],
            ))
            conn.commit()

    def _load_memory_time(self, cursor) -> None:
        """Load memory & time state from database."""
        try:
            cursor.execute("SELECT * FROM life_memory_time_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._memory_time = MemoryTimeSystem.from_dict(dict(row), rng=self._rng)
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_expression(self) -> None:
        """Save expression state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._expression.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_expression_state
                (id, interaction_count, formality, avg_message_length,
                 emoji_frequency, humor_density, vulnerability_openness,
                 relationship_stage, last_message_at, avg_response_time, response_times)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["interaction_count"], data["formality"],
                data["avg_message_length"], data["emoji_frequency"],
                data["humor_density"], data["vulnerability_openness"],
                data["relationship_stage"], data["last_message_at"],
                data["avg_response_time"], data["response_times"],
            ))
            conn.commit()

    def _load_expression(self, cursor) -> None:
        """Load expression state from database."""
        try:
            cursor.execute("SELECT * FROM life_expression_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._expression = ExpressionSystem.from_dict(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_continuity(self) -> None:
        """Save continuity state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._continuity.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_continuity_state
                (id, anniversaries, growth_snapshots, milestones,
                 milestones_detected, life_chapters,
                 last_daily_tick, last_weekly_tick, last_monthly_tick)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["anniversaries"], data["growth_snapshots"],
                data["milestones"], data["milestones_detected"],
                data["life_chapters"],
                data["last_daily_tick"], data["last_weekly_tick"],
                data["last_monthly_tick"],
            ))
            conn.commit()

    def _load_continuity(self, cursor) -> None:
        """Load continuity state from database."""
        try:
            cursor.execute("SELECT * FROM life_continuity_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._continuity = ContinuitySystem.from_dict(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_character_evolution(self) -> None:
        """Save character evolution state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._character_evolution.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_character_evolution
                (id, original_baseline, current_baseline, core_traits,
                 drift_history, activity_counts, last_evolution)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                data["original_baseline"], data["current_baseline"],
                data["core_traits"], data["drift_history"],
                data["activity_counts"], data["last_evolution"],
            ))
            conn.commit()

    def _load_character_evolution(self, cursor) -> None:
        """Load character evolution state from database."""
        try:
            cursor.execute("SELECT * FROM life_character_evolution WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._character_evolution = CharacterEvolution.from_dict(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_chaos(self) -> None:
        """Save chaos state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._chaos.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_chaos_state
                (id, events_today, last_event_text, last_date, total_events)
                VALUES (1, ?, ?, ?, ?)
            """, (
                data["events_today"], data["last_event_text"],
                data["last_date"], data["total_events"],
            ))
            conn.commit()

    def _load_chaos(self, cursor) -> None:
        """Load chaos state from database."""
        try:
            cursor.execute("SELECT * FROM life_chaos_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._chaos = ChaosEngine.from_dict(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_life_events(self) -> None:
        """Save life events to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()

            # Clear and rewrite recent events
            cursor.execute("DELETE FROM life_events")
            for event in self._life_events._events:
                cursor.execute("""
                    INSERT INTO life_events
                    (event_type, title, description, emotional_impact,
                     share_urgency, created_at, shared, shared_at, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_type,
                    event.title,
                    event.description,
                    json.dumps(event.emotional_impact),
                    event.share_urgency,
                    event.created_at.isoformat(),
                    1 if event.shared else 0,
                    event.shared_at.isoformat() if event.shared_at else None,
                    event.source,
                ))
                event.id = cursor.lastrowid

            conn.commit()

    def _load_life_events(self, cursor) -> None:
        """Load life events from database."""
        try:
            cursor.execute("SELECT * FROM life_events ORDER BY created_at DESC LIMIT 20")
            rows = cursor.fetchall()
            if rows:
                events = []
                for row in rows:
                    emotional_impact_raw = row["emotional_impact"] or "{}"
                    try:
                        emotional_impact = json.loads(emotional_impact_raw)
                    except (json.JSONDecodeError, TypeError):
                        emotional_impact = {}
                    events.append(LifeEvent(
                        id=row["id"],
                        event_type=row["event_type"],
                        title=row["title"],
                        description=row["description"] or "",
                        emotional_impact=emotional_impact,
                        share_urgency=row["share_urgency"],
                        created_at=datetime.fromisoformat(row["created_at"]),
                        shared=bool(row["shared"]),
                        shared_at=datetime.fromisoformat(row["shared_at"]) if row["shared_at"] else None,
                        source=row["source"] or "",
                    ))
                # Reverse so oldest is first (list was DESC)
                self._life_events._events = list(reversed(events))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_body(self) -> None:
        """Save body state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            data = self._body.to_dict()
            cursor.execute("""
                INSERT OR REPLACE INTO life_body_state
                (id, wellness, active_conditions, hormonal_enabled, hormonal_cycle_day,
                 comfort_level, posture_stiffness, outfit, hair_state, put_togetherness,
                 sleep_last_quality, sleep_insomnia_risk, sleep_consecutive_poor,
                 fitness_cardio, fitness_strength, fitness_flexibility,
                 fitness_peak_cardio, fitness_peak_strength,
                 fitness_last_cardio, fitness_last_strength, fitness_last_flexibility,
                 inebriation_level, inebriation_substance, inebriation_started_at,
                 inebriation_hangover, inebriation_last_drink)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["wellness"], data["active_conditions"],
                1 if data["hormonal_enabled"] else 0, data["hormonal_cycle_day"],
                data["comfort_level"], data["posture_stiffness"],
                data["outfit"], data["hair_state"], data["put_togetherness"],
                data["sleep_last_quality"], data["sleep_insomnia_risk"], data["sleep_consecutive_poor"],
                data["fitness_cardio"], data["fitness_strength"], data["fitness_flexibility"],
                data["fitness_peak_cardio"], data["fitness_peak_strength"],
                data["fitness_last_cardio"], data["fitness_last_strength"], data["fitness_last_flexibility"],
                data.get("inebriation_level", 0.0), data.get("inebriation_substance", ""),
                data.get("inebriation_started_at"), data.get("inebriation_hangover", 0.0),
                data.get("inebriation_last_drink"),
            ))
            conn.commit()

    def _load_body(self, cursor) -> None:
        """Load body state from database."""
        try:
            cursor.execute("SELECT * FROM life_body_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._body = BodySystem.from_dict(dict(row))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_world(self) -> None:
        """Save world location to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_world_state (id, current_location)
                VALUES (1, ?)
            """, (self._world.current_location,))
            conn.commit()

    def _load_world(self, cursor) -> None:
        """Load world location from database.

        Falls back to: current plan slot → last activity location → 'home'.
        """
        try:
            cursor.execute("SELECT current_location FROM life_world_state WHERE id = 1")
            row = cursor.fetchone()
            if row and row["current_location"]:
                self._world._current_location = row["current_location"]
                return
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet — normal on first run
        except Exception:
            # Say so before falling back, or a genuine read failure is
            # indistinguishable from an empty first-run database.
            logger.warning(
                "Failed to load world location; falling back to plan slot / last "
                "activity / 'home'", exc_info=True,
            )

        # Fallback: use current plan slot location
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot()
            if slot and slot.location:
                self._world._current_location = slot.location
                return

        # Fallback: use last recorded activity location
        if self._recent_activities:
            last_loc = self._recent_activities[0].location
            if last_loc and last_loc != "None":
                self._world._current_location = last_loc
                return

        # Final fallback stays "home" (the __init__ default)

    def _save_location(self, profile: LocationProfile) -> None:
        """Save a single location profile to the database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_locations
                (key, name, place_type, description, source, familiarity, visit_count, last_visit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile.key, profile.name, profile.place_type, profile.description,
                profile.source, profile.familiarity, profile.visit_count, profile.last_visit,
            ))
            conn.commit()

    def _save_all_locations(self) -> None:
        """Save all non-default locations (user/llm + visit tracking for all) to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            for key, profile in self._location_registry.items():
                # Only persist user/llm-added locations and familiarity updates
                if profile.source in ("user", "llm") or profile.visit_count > 0:
                    cursor.execute("""
                        INSERT OR REPLACE INTO life_locations
                        (key, name, place_type, description, source, familiarity, visit_count, last_visit)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        profile.key, profile.name, profile.place_type, profile.description,
                        profile.source, profile.familiarity, profile.visit_count, profile.last_visit,
                    ))
            conn.commit()

    def _load_locations(self, cursor) -> None:
        """Load persisted locations from database and merge into registry.

        Only the query is allowed to fail quietly (no table on a first run). A bad
        row is logged and skipped rather than ending the loop: the broad catch that
        used to wrap the whole loop let one malformed row silently truncate the
        persona's known places, leaving a half-populated planner key set.
        """
        try:
            cursor.execute("SELECT * FROM life_locations")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return  # Table doesn't exist yet — normal on first run

        for row in rows:
            try:
                key = row["key"]
                if key in self._location_registry:
                    # Update existing entry with persisted visit data
                    existing = self._location_registry[key]
                    existing.familiarity = row["familiarity"]
                    existing.visit_count = row["visit_count"]
                    existing.last_visit = row["last_visit"]
                else:
                    # Restore user/llm-added location
                    self._location_registry[key] = LocationProfile(
                        key=key,
                        name=row["name"],
                        place_type=row["place_type"],
                        description=row["description"] or "",
                        source=row["source"],
                        familiarity=row["familiarity"],
                        visit_count=row["visit_count"],
                        last_visit=row["last_visit"],
                    )
                    self._daily_planner._available_location_keys.add(key)
            except Exception:
                logger.warning("Skipping unreadable life_locations row", exc_info=True)

    def _save_needs_state(self) -> None:
        """Save the Sustenance engine state to the database."""
        d = self._sustenance.to_dict()
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_basic_needs
                (id, hunger, last_meal_time, showered_today, morning_routine_done,
                 meals_today, nutrition)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                d["hunger"], d["last_meal_time"], d["showered_today"],
                d["morning_routine_done"], d["meals_today"], d["nutrition"],
            ))
            conn.commit()

    def _save_media_state(self) -> None:
        """Save media state to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_media_state
                (id, current_book, book_progress, books_finished,
                 current_show, show_progress, current_music_obsession)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                self._media.current_book,
                self._media.book_progress,
                json.dumps(self._media.books_finished),
                self._media.current_show,
                self._media.show_progress,
                self._media.current_music_obsession,
            ))
            conn.commit()

    def _save_room_state(self) -> None:
        """Save the Habitation engine living-space state to the database."""
        d = self._habitation.to_dict()
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_room_state
                (id, candle_lit, music_playing, window_open, tidiness, home_type, comfort)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                d["candle_lit"], d["music_playing"], d["window_open"], d["tidiness"],
                d["home_type"], d["comfort"],
            ))
            conn.commit()

    def _save_financial_state(self) -> None:
        """Save the Money engine ledger to the database."""
        d = self._finance.to_dict()
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_financial_state
                (id, feeling, saving_for, recent_splurge, balance, savings,
                 monthly_income, monthly_expenses, spending_habit, enabled, currency,
                 last_payday, last_expense_run, recent_purchases)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d["feeling"], d["saving_for"], d["recent_splurge"], d["balance"],
                d["savings"], d["monthly_income"], d["monthly_expenses"],
                d["spending_habit"], d["enabled"], d["currency"], d["last_payday"],
                d["last_expense_run"], d["recent_purchases"],
            ))
            conn.commit()

    def _save_career_state(self) -> None:
        """Save the Job engine state to the database."""
        d = self._career.to_dict()
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_career_state
                (id, occupation, employer, employed, work_days, shift_start_hour,
                 shift_end_hour, monthly_salary, workload, satisfaction, days_worked,
                 last_workday, recent_work_event)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d["occupation"], d["employer"], d["employed"], d["work_days"],
                d["shift_start_hour"], d["shift_end_hour"], d["monthly_salary"],
                d["workload"], d["satisfaction"], d["days_worked"], d["last_workday"],
                d["recent_work_event"],
            ))
            conn.commit()

    def _save_errands_state(self) -> None:
        """Save the Errands engine backlog to the database."""
        d = self._errands.to_dict()
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_errands_state
                (id, pending, overdue, completed_count, last_added)
                VALUES (1, ?, ?, ?, ?)
            """, (
                d["pending"], d["overdue"], d["completed_count"], d["last_added"],
            ))
            conn.commit()

    # ============= Catch-up / Reset =============

    def get_last_activity_time(self) -> Optional[datetime]:
        """
        Get the timestamp of the most recent activity.

        Returns None if no activities have been recorded.
        """
        if not self._recent_activities:
            # Try to load from database
            with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT started_at FROM activity_logs
                    ORDER BY started_at DESC
                    LIMIT 1
                """)
                row = cursor.fetchone()

            if row:
                return datetime.fromisoformat(row[0])
            return None

        return self._recent_activities[0].started_at

    def get_last_state_update(self) -> Optional[datetime]:
        """
        Get the timestamp of the last energy state update.

        This indicates when the server was last running.
        """
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_update FROM life_energy_state WHERE id = 1")
            row = cursor.fetchone()

        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None

    def reset_state(self) -> None:
        """
        Reset life service state to defaults.

        Used when clearing memory or after extended downtime.
        """
        # Reset energy to neutral
        self._energy = EnergySystem(core_traits=self._core_traits, now=self._world_clock())

        # Reset desire system
        self._desire_system = DesireSystem(core_traits=self._core_traits, rng=self._rng)

        # Clear recent activities (keep in DB for history)
        self._recent_activities = []

        # Clear shareable queue
        self._shareable_queue = []

        # Reset goals
        self._goal_engine = GoalEngine()
        self._goal_engine.initialize_goals()

        # Reset planner
        self._daily_planner = DailyPlanner(
            occupation=self._occupation,
            interests=self._interests,
            sleep_schedule=self._sleep_schedule,
            persona_locations=self._persona_locations,
            nationality=getattr(self._definition, 'nationality', '') if self._definition else '',
            is_ai=self._is_ai,
        )

        # Reset conversation-session and wake latch so a memory clear doesn't
        # carry over stale msg_count (which could trigger a premature sign-off)
        # or a leftover wake flag.
        self._session = ConversationSession()
        self._woke_pending = False
        self._forced_wake_at = None

        # Reset new subsystems
        _defn = self._definition
        # AI personas have no body/finances/home/commute — gate the physical-life
        # engines off so an AI companion doesn't "get hungry" or "pay rent".
        self._is_ai = (getattr(_defn, 'persona_type', 'human') == 'ai') if _defn else False
        # Energy is built above (before persona_type is known) — thread the AI flag
        # in now so an AI never sleeps and carries no sleep-physiology in its digest.
        self._energy._is_ai = self._is_ai
        self._sustenance = SustenanceSystem()
        self._basic_needs = self._sustenance.state  # back-compat alias (same object)
        self._habitation = HabitationSystem(
            home_type=getattr(_defn, 'home_type', '') if _defn else '',
            rng=self._rng,
        )
        self._room_state = self._habitation.state  # back-compat alias (same object)
        self._finance = FinanceSystem(core_traits=self._core_traits, rng=self._rng, now=self._world_clock()())
        if _defn and getattr(_defn, 'spending_habit', None) is not None:
            self._finance.state.spending_habit = _defn.spending_habit
        self._financial = self._finance.state  # back-compat alias (same state object)
        _occupation = self._occupation or (getattr(_defn, 'occupation', '') if _defn else '')
        _salary = getattr(_defn, 'monthly_salary', None) if _defn else None
        self._career = CareerSystem(occupation=_occupation, monthly_salary=_salary, rng=self._rng)
        self._apply_occupation_schedule(self._career, _occupation)
        if self._career.monthly_salary > 0:
            self._finance.state.monthly_income = self._career.monthly_salary
        self._media = self._init_media_state()
        self._skills_system = SkillsSystem()
        self._skills = self._skills_system.skills  # alias
        self._errands = ErrandsSystem(rng=self._rng)
        self._identity = IdentitySystem(
            npcs=self._build_npcs(self._social_circle_defs), user_info=self._user_info,
            core_traits=self._core_traits,
            humor_style=getattr(self._definition, 'humor_style', '') if self._definition else '',
            core_values=getattr(self._definition, 'core_values', []) if self._definition else [],
            struggles=getattr(self._definition, 'struggles', []) if self._definition else [],
            character_defects=getattr(self._definition, 'character_defects', []) if self._definition else [],
            behavioral_tendencies=getattr(self._definition, 'behavioral_tendencies', {}) if self._definition else {},
            rng=self._rng,
        )
        self._affect = AffectSystem(
            core_traits=self._core_traits,
            emotional_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
        )
        self._body = BodySystem(
            hormonal_enabled=getattr(self._definition, 'hormonal_enabled', False) if self._definition else False,
            substance_tendencies=getattr(self._definition, 'substance_tendencies', {}) if self._definition else {},
        )
        self._cognitive = CognitiveSystem(
            core_traits=self._core_traits,
            intrusive_thought_themes=getattr(self._definition, 'intrusive_thought_themes', []) if self._definition else [],
            rng=self._rng,
        )
        self._shadow = ShadowSystem(
            behavioral_tendencies=(getattr(self._definition, 'behavioral_tendencies', {}) if self._definition else {}) or {},
            character_defects=(getattr(self._definition, 'character_defects', []) if self._definition else []) or [],
            struggles=(getattr(self._definition, 'struggles', []) if self._definition else []) or [],
            intrusive_thought_themes=(getattr(self._definition, 'intrusive_thought_themes', []) if self._definition else []) or [],
            substance_tendencies=(getattr(self._definition, 'substance_tendencies', {}) if self._definition else {}) or {},
            core_traits=(getattr(self._definition, 'core_traits', []) if self._definition else []) or [],
        )
        self._sanity = SanitySystem(
            struggles=(getattr(self._definition, 'struggles', []) if self._definition else []) or [],
            character_defects=(getattr(self._definition, 'character_defects', []) if self._definition else []) or [],
            intrusive_thought_themes=(getattr(self._definition, 'intrusive_thought_themes', []) if self._definition else []) or [],
            rng=self._sanity_rng,
        )
        self._sanity_ticked_at = self._world_clock()()
        self._sanity_coupled_state = self._sanity.state
        self._drive = DriveSystem(
            core_traits=self._core_traits,
            comfort_zone_seeds=getattr(self._definition, 'comfort_zone_seeds', []) if self._definition else [],
            rng=self._rng,
        )
        self._behavior = BehaviorSystem()
        self._memory_time = MemoryTimeSystem(rng=self._rng)
        self._expression = ExpressionSystem()
        self._continuity = ContinuitySystem()
        self._character_evolution = CharacterEvolution(
            original_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
            core_traits=getattr(self._definition, 'core_traits', []) if self._definition else [],
        )
        self._chaos = ChaosEngine()

        # Clear visual description tracking
        self._last_visual_activity = None
        self._last_visual_location = None
        self._last_visual_outfit = None

        # Save new state
        self._save_state()

        logger.info("Life service state reset to defaults")

    def catch_up_from_downtime(self, downtime_hours: float) -> dict:
        """
        Handle server catch-up after downtime using a 5-phase pipeline.

        Phase 0: Detect gap and decide strategy
        Phase 1: Plan the gap (use DailyPlanner for each missed day, max 7)
        Phase 2: Execute plans (tick all engines with backdated timestamps)
        Phase 3: Generate narratives for recent activities
        Phase 4: Set current state (energy, world, emotions to NOW)

        Args:
            downtime_hours: How many hours the server was down

        Returns:
            Summary of what was generated
        """
        now = datetime.now()
        gap_start = now - timedelta(hours=downtime_hours)
        generated_activities = []

        # ── Phase 0: Detect gap strategy ──
        if downtime_hours < 1.0:
            return {"downtime_hours": downtime_hours, "activities_generated": 0, "mode": "none"}

        # Cap at 2 days max — beyond that, just reset to now
        if downtime_hours > 48:
            logger.info(f"Catch-up: {downtime_hours:.1f}h exceeds 48h cap, clamping to 48h")
            gap_start = now - timedelta(hours=48)
            downtime_hours = 48

        if downtime_hours <= 6:
            mode = "short"
            max_activities = min(3, max(1, int(downtime_hours / 2)))
        elif downtime_hours <= 24:
            mode = "day"
            max_activities = min(8, int(downtime_hours / 2))
        else:
            mode = "extended"
            max_activities = min(12, int(downtime_hours / 3))

        logger.info(f"Catch-up Phase 0: {downtime_hours:.1f}h gap, mode={mode}")

        # ── Phase 1: Plan the gap ──
        # Generate daily plans for each missed day
        days_to_plan = max(1, min(2, int(downtime_hours / 24) + 1))
        plan_day = gap_start.replace(hour=0, minute=0, second=0, microsecond=0)
        all_slots = []

        for d in range(days_to_plan):
            current_day = plan_day + timedelta(days=d)
            # Use the planner to generate a day plan
            try:
                plan = self._daily_planner.generate_daily_plan(
                    goals=self._goal_engine.active_goals,
                    weather=self._world.weather,
                    available_activities=self._activity_engine.get_all_activities(),
                    recent_activity_names=[a.activity_name for a in self._recent_activities[:5]],
                    work_schedule=self._career_schedule(),
                )
                if plan and plan.slots:
                    for slot in plan.slots:
                        # Only include slots within the actual gap window
                        slot_time = current_day.replace(hour=slot.hour)
                        if gap_start <= slot_time <= now:
                            all_slots.append((slot_time, slot))
            except Exception as e:
                logger.warning(f"Catch-up plan generation failed for day {d}: {e}")
                continue

        # Sort slots chronologically
        all_slots.sort(key=lambda x: x[0])

        # Limit to max_activities
        slots_to_execute = all_slots[:max_activities]
        logger.info(f"Catch-up Phase 1: {len(slots_to_execute)} activities planned across {days_to_plan} days")

        # ── Phase 2: Execute plans (tick all engines with backdated timestamps) ──
        for slot_time, slot in slots_to_execute:
            activity_name = slot.activity_name
            location = slot.location or "home"

            # Determine sleep status. AI personas never sleep, so never backdate
            # them into the "sleeping" activity during catch-up.
            hour = slot_time.hour
            if not self._is_ai and self._is_sleep_hour(hour):
                activity_name = "sleeping"
                location = "home"

            # Create backdated activity log
            duration_hours = 1.0
            end_time = slot_time + timedelta(hours=duration_hours)
            narrative = self._get_catchup_narrative(activity_name, hour)

            # Tick engines with backdated context
            self._tick_engines_for_catchup(
                activity_name=activity_name,
                timestamp=slot_time,
                weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
                season=self._world.season.value if hasattr(self._world, 'season') and hasattr(self._world.season, 'value') else "spring",
            )

            # Move world to this location
            self._world.move_to(location)

            log = ActivityLog(
                activity_name=activity_name,
                category=self._categorize_activity(activity_name),
                started_at=slot_time,
                ended_at=end_time,
                location=location,
                weather=self._world.weather,
                narrative=narrative,
                energy_before=0.5,
                energy_after=0.5,
            )
            self._record_activity(log)
            generated_activities.append(log)

        logger.info(f"Catch-up Phase 2: Executed {len(generated_activities)} activities")

        # ── Phase 3: (Narrative generation happens at next chat, via pipeline) ──

        # ── Phase 4: Set current state to NOW ──
        self._world.tick()
        self._energy.adjust_for_time(self._world.time_of_day, now_hour=self.persona_local_hour())

        # Sync location to current plan slot
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot()
            if slot and slot.location:
                self._world.move_to(slot.location)

        # Save all engine state
        self._save_state()
        self._save_affect()
        self._save_body()
        self._save_cognitive()
        self._save_shadow()
        self._save_sanity()
        self._save_drive()
        self._save_behavior()
        self._save_memory_time()
        self._save_expression()
        self._save_identity()
        self._save_goals()
        self._save_plan()

        logger.info(f"Catch-up complete: {len(generated_activities)} activities for {downtime_hours:.1f}h gap")

        return {
            "downtime_hours": downtime_hours,
            "activities_generated": len(generated_activities),
            "mode": mode,
            "activities": [a.activity_name for a in generated_activities],
        }

    # ------------------------------------------------------------------
    # Persona-local time helpers
    # ------------------------------------------------------------------

    def _persona_timezone(self) -> str:
        """Return the persona's current IANA timezone string, or '' for fallback.

        AI personas always fall back to server-local time (AI personas are
        timeless digital entities; their schedule already ignores sleep).
        Human personas with no resolved timezone also fall back.
        """
        if self._is_ai:
            return ""
        try:
            return self._place_location.current_timezone or ""
        except Exception:
            return ""

    def _world_clock(self) -> Callable[[], datetime]:
        """The clock the world runs on, for engines that measure elapsed time.

        Distinct from :meth:`persona_local_now`, which is the ``persona_now``
        hook and answers *what time is it where she lives* (timezone-aware,
        used for wall-clock hours). This one answers *how much time has passed*
        and is deliberately naive, because every ``datetime`` stored in engine
        state is.

        Falls back to ``datetime.now`` when the injected world does not expose a
        callable ``now`` -- a host may hand in a duck-typed environment, and an
        engine losing its clock entirely would be a worse failure than reading
        the wall clock.
        """
        clock = getattr(self._world, "now", None)
        return clock if callable(clock) else datetime.now

    def persona_local_now(self):
        """Return 'now' in the persona's local timezone (or server-local fallback)."""
        from aura_life.hooks import persona_now
        return persona_now(self._persona_timezone())

    def persona_local_hour(self) -> int:
        """Return the persona's current local hour (0-23).

        Falls back to ``datetime.now().hour`` when the persona has no
        timezone set (including all AI personas).
        """
        return self.persona_local_now().hour

    def _is_sleep_hour(self, hour: int) -> bool:
        """Check if an hour falls during the persona's sleep time."""
        wake_hour = self._energy.wake_hour
        bedtime_hour = self._energy.bedtime_hour
        if bedtime_hour < wake_hour:
            return bedtime_hour <= hour < wake_hour
        else:
            return hour >= bedtime_hour or hour < wake_hour

    def _apply_occupation_schedule(self, career, occupation: str) -> None:
        """Align the Job engine's work schedule with the planner's occupation type.

        The planner schedules work blocks by occupation classification; mirroring
        that into CareerSystem keeps "on shift" / work-stress consistent with when
        the planner actually has her working. Only seeds the default schedule —
        a persisted/loaded career keeps its own.
        """
        try:
            from aura_life.planner.daily_planner import (
                classify_occupation, OCC_NONE, OCC_STANDARD,
                OCC_SERVICE, OCC_STUDENT, OCC_CREATIVE,
            )
            occ = classify_occupation(occupation or "")
            if occ == OCC_NONE:
                career.state.employed = False
                return
            career.state.employed = True
            schedules = {
                OCC_STANDARD: ([0, 1, 2, 3, 4], 9, 17),
                OCC_SERVICE:  ([0, 1, 2, 3, 4, 5], 8, 16),
                OCC_STUDENT:  ([0, 1, 2, 3, 4], 9, 15),
                OCC_CREATIVE: ([1, 2, 3, 4], 11, 18),
            }
            days, start, end = schedules.get(occ, ([0, 1, 2, 3, 4], 9, 17))
            career.state.work_days = days
            career.state.shift_start_hour = start
            career.state.shift_end_hour = end
        except Exception as e:
            logger.debug(f"Occupation schedule seed failed: {e}")

    def _career_schedule(self) -> dict:
        """The Job engine's schedule, handed to the planner as the source of truth
        for which days she works and her shift window."""
        s = self._career.state
        return {
            "employed": s.employed,
            "work_days": list(s.work_days),
            "shift_start_hour": s.shift_start_hour,
            "shift_end_hour": s.shift_end_hour,
        }

    def is_asleep(self) -> bool:
        """True if the persona is currently asleep.

        Used to gate spontaneous proactive outreach — a sleeping persona isn't
        doing things to share. Trusts the live activity first ("sleeping"), then
        falls back to the sleep-schedule hour window so it's correct even if the
        sim hasn't ticked recently.

        AI personas never sleep — they're awake at all times — so this is always
        False for them.
        """
        if self._is_ai:
            return False
        try:
            # Explicit forced wake (wake button) overrides both the activity and
            # the schedule window while the conversation is live. The reference
            # point is the later of the wake itself and the last user message,
            # so an ongoing chat keeps her up; once it lapses past the window
            # the override clears and normal sleep logic resumes.
            forced_at = getattr(self, "_forced_wake_at", None)
            if forced_at is not None:
                ref = forced_at
                last_msg = getattr(self, "_last_user_message_at", None)
                if last_msg is not None and last_msg > ref:
                    ref = last_msg
                if (datetime.now() - ref) <= timedelta(minutes=FORCED_WAKE_WINDOW_MINUTES):
                    return False
                self._forced_wake_at = None  # conversation lapsed — she can sleep again
            if (self.current_activity_name or "").lower() == "sleeping":
                return True
            return self._is_sleep_hour(self.persona_local_hour())
        except Exception:
            return False

    def _tick_engines_for_catchup(self, activity_name: str, timestamp: datetime,
                                   weather: str, season: str):
        """Tick all engines once for a catch-up activity (lightweight, no DB writes)."""
        try:
            # Affect: activity emotions
            self._affect.on_activity(activity_name)

            # Body: activity effects
            self._body.on_activity(activity_name)
            self._body.on_substance_activity(activity_name)

            # Cognitive: activity engagement
            self._cognitive.on_activity(activity_name)

            # Shadow: activity engagement (coping / temptation relief)
            self._shadow.on_activity(activity_name)

            # Drive: curiosity sparks, comfort zone
            self._drive.on_activity(activity_name)
            self._drive.track_activity_comfort(activity_name)

            # Identity: activity reinforcement
            self._identity.update_from_activity(activity_name)

            # Behavior: routine tracking
            self._behavior.track_activity(activity_name)

            # Memory Time: time perception
            self._memory_time.on_activity(activity_name)

            # Physical-life engines accrue at the backdated time so the ledgers stay
            # consistent across downtime — humans only (AI personas have none of this).
            if not self._is_ai:
                self._finance.on_activity(activity_name)
                self._finance.tick(now=timestamp)
                self._career.on_activity(activity_name)
                self._career.tick(now=timestamp)
                self._habitation.on_activity(activity_name)
                self._sustenance.on_activity(activity_name, now=timestamp)
                self._sustenance.tick(now=timestamp)
                self._errands.on_activity(activity_name)
                self._errands.tick(now=timestamp)

            # Goal progress (expects ActivityLog, not str)
            from aura_life.models import ActivityLog
            self._goal_engine.update_progress_from_activity(
                ActivityLog(activity_name=activity_name)
            )

        except Exception as e:
            logger.debug(f"Catch-up engine tick error for {activity_name}: {e}")

    def _growth_snapshots_for_month(self, now: datetime) -> List[str]:
        """Extract identity shift descriptions from recent growth snapshots."""
        shifts = []
        for snap in self._continuity._growth_snapshots:
            if snap.date and (now - snap.date).days <= 35:
                for change in snap.notable_changes:
                    if change.startswith("growing more "):
                        shifts.append(change.replace("growing more ", ""))
        return shifts

    def _categorize_activity(self, activity_name: str) -> ActivityCategory:
        """Get ActivityCategory for an activity name."""
        creative = {"writing poetry", "sketching ideas", "creating a playlist",
                    "creative_work", "trying a new recipe"}
        mental = {"reading", "learning", "learning something new",
                  "exploring a new idea", "journaling", "exploring_interests"}
        physical = {"going for a run", "yoga", "gym workout", "gentle_walk"}
        social = {"texting a friend", "having coffee with a friend",
                  "catching up with family"}
        if activity_name in creative:
            return ActivityCategory.CREATIVE
        if activity_name in mental:
            return ActivityCategory.MENTAL
        if activity_name in physical:
            return ActivityCategory.PHYSICAL
        if activity_name in social:
            return ActivityCategory.SOCIAL
        return ActivityCategory.REST

    def _get_catchup_narrative(self, activity_name: str, hour: int) -> str:
        """Generate a simple narrative for a catch-up activity."""
        narratives = {
            "sleeping": "She slept peacefully through the night",
            "morning_routine": random.choice([
                "She started her day with a warm shower and coffee",
                "She did some light stretching and had breakfast",
            ]),
            "reading": "She spent time lost in a book",
            "cooking a meal": "She prepared something to eat",
            "relaxing": "She took some time to relax",
            "going for a run": "She went for a run to clear her head",
            "yoga": "She did a yoga session",
            "journaling": "She spent some time journaling",
        }
        return narratives.get(activity_name,
                              f"She spent some time {activity_name.replace('_', ' ')}")

    def _get_activity_for_hour(self, hour: int) -> tuple:
        """
        Get appropriate activity for a given hour based on persona's sleep schedule.

        Returns (activity_name, category, narrative) tuple.
        """
        # Get persona's sleep schedule (or defaults)
        wake_hour = self._energy.wake_hour
        bedtime_hour = self._energy.bedtime_hour

        # Determine if this hour is during sleep time
        if bedtime_hour < wake_hour:
            # Night owl schedule (e.g., bedtime 2am, wake 10am)
            is_sleep_time = bedtime_hour <= hour < wake_hour
        else:
            # Normal schedule (e.g., bedtime 11pm, wake 7am)
            is_sleep_time = hour >= bedtime_hour or hour < wake_hour

        if is_sleep_time:
            return (
                "sleeping",
                ActivityCategory.REST,
                "She slept peacefully through the night"
            )

        # Calculate hours since wake time for activity selection
        if hour >= wake_hour:
            hours_awake = hour - wake_hour
        else:
            # Past midnight but before bedtime
            hours_awake = (24 - wake_hour) + hour

        # Activity selection based on hours since wake
        if hours_awake < 2:
            # Morning routine (first 2 hours after wake)
            return (
                "morning_routine",
                ActivityCategory.REST,
                random.choice([
                    "She started her day with a warm shower and coffee",
                    "She did some light stretching and had breakfast",
                    "She enjoyed a quiet morning, easing into the day",
                ])
            )
        elif hours_awake < 5:
            # Morning activity
            activity_name = random.choice(["reading", "learning", "creative_work"])
            return (
                activity_name,
                ActivityCategory.CREATIVE if "creative" in activity_name else ActivityCategory.MENTAL,
                random.choice([
                    "She spent the morning lost in a fascinating book",
                    "She worked on a creative project that had been on her mind",
                    "She explored some new ideas and took notes",
                ])
            )
        elif hours_awake < 7:
            # Midday / lunch
            return (
                "cooking",
                ActivityCategory.REST,
                random.choice([
                    "She prepared a light lunch and enjoyed eating slowly",
                    "She made something simple but satisfying to eat",
                ])
            )
        elif hours_awake < 11:
            # Afternoon
            activity_name = random.choice(["exploring_interests", "gentle_walk", "creative_work"])
            return (
                activity_name,
                ActivityCategory.CREATIVE,
                random.choice([
                    "She spent the afternoon exploring things that interested her",
                    "She went for a walk and let her mind wander",
                    "She worked on something creative, losing track of time",
                ])
            )
        elif hours_awake < 14:
            # Evening
            activity_name = random.choice(["relaxing", "watching_sunset", "evening_routine"])
            return (
                activity_name,
                ActivityCategory.REST,
                random.choice([
                    "She relaxed as the day wound down",
                    "She watched the evening sky change colors",
                    "She settled into her evening routine",
                ])
            )
        else:
            # Late evening / winding down
            return (
                "winding_down",
                ActivityCategory.REST,
                "She prepared for sleep, feeling pleasantly tired"
            )

    # ============= Calendar CRUD =============

    @staticmethod
    def _ensure_calendar_schema(conn) -> None:
        """Create the ``user_calendar`` table and its migration on *conn*.

        Runs against both backing stores: ``_init_database()`` creates it inside
        ``db_path``, and an injected host datastore gets it on first use — the
        host owns that file and has no reason to already carry this schema.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                date_str TEXT DEFAULT '',
                recurring INTEGER DEFAULT 0,
                feeling TEXT DEFAULT 'neutral',
                importance REAL DEFAULT 0.5,
                source_memory_content TEXT DEFAULT '',
                triggered INTEGER DEFAULT 0,
                promoted_to_anniversary INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        # Migration: post-event check-in tracking (added 2026-06)
        try:
            conn.execute("ALTER TABLE user_calendar ADD COLUMN followed_up INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists

    @contextlib.contextmanager
    def _calendar_connection(self):
        """Yield the connection the ``user_calendar`` table lives on.

        Two shapes, both supported:

        * a host that injected ``datastore=`` gets calendar rows in its own
          consolidated store (the contract ``EmotionPersistence`` already uses);
        * with no datastore — the plain library shape — rows go to ``db_path``,
          where ``_init_database()`` has already created the table.

        This helper exists because the three calendar methods below opened the
        host datastore directly while nothing ever assigned that attribute, so
        both public methods raised ``AttributeError`` on first call and the daily
        scan failed silently inside its ``except``.
        """
        if self._datastore is not None:
            with self._datastore.get_connection() as conn:
                if not self._calendar_schema_ready:
                    self._ensure_calendar_schema(conn)
                    self._calendar_schema_ready = True
                yield conn
            return

        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def add_calendar_entry(self, entry: CalendarEntry) -> bool:
        """Add a calendar entry with event_name+event_date dedup.

        Returns True if added, False if duplicate.
        """
        with self._calendar_connection() as conn:
            date_str = entry.event_date.isoformat() if entry.event_date else ""
            # Dedup check
            existing = conn.execute(
                "SELECT id FROM user_calendar WHERE event_name = ? AND event_date = ?",
                (entry.event_name, date_str),
            ).fetchone()
            if existing:
                return False

            cursor = conn.execute("""
                INSERT INTO user_calendar
                (event_name, event_date, date_str, recurring, feeling, importance,
                 source_memory_content, triggered, promoted_to_anniversary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """, (
                entry.event_name, date_str, entry.date_str,
                1 if entry.recurring else 0,
                entry.feeling, entry.importance,
                entry.source_memory_content,
                (entry.created_at or datetime.now()).isoformat(),
            ))
            entry.id = cursor.lastrowid
        # The event name is user-derived personal content ("extracted from
        # conversation"), so it never reaches the host log — id only, at DEBUG.
        logger.debug("[CALENDAR] Added entry id=%s", entry.id)

        # Also add anticipation to MemoryTimeSystem so it flows into context
        if entry.event_date and entry.event_date > datetime.now():
            self._memory_time.add_anticipation(
                event=entry.event_name,
                feeling=entry.feeling or "curious",
                intensity=min(entry.importance + 0.1, 1.0),
                date=entry.event_date,
            )
        return True

    def get_upcoming_calendar_entries(self, days_ahead: int = 7) -> List[CalendarEntry]:
        """Query calendar entries within the next N days."""
        now = datetime.now()
        cutoff = (now + timedelta(days=days_ahead)).isoformat()
        now_str = now.isoformat()

        entries = []
        with self._calendar_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM user_calendar
                WHERE event_date >= ? AND event_date <= ?
                ORDER BY event_date ASC
            """, (now_str, cutoff)).fetchall()

            for row in rows:
                entries.append(CalendarEntry(
                    id=row["id"],
                    event_name=row["event_name"],
                    event_date=datetime.fromisoformat(row["event_date"]) if row["event_date"] else None,
                    date_str=row["date_str"],
                    recurring=bool(row["recurring"]),
                    feeling=row["feeling"],
                    importance=row["importance"],
                    source_memory_content=row["source_memory_content"],
                    triggered=bool(row["triggered"]),
                    promoted_to_anniversary=bool(row["promoted_to_anniversary"]),
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
                ))
        return entries

    def _scan_calendar_for_triggers(self):
        """Scan calendar for upcoming events and create UPCOMING_EVENT triggers.

        Called from daily tick. Creates triggers for events within 3 days.
        Also promotes passed recurring events to anniversaries.
        """
        now = datetime.now()
        cutoff = (now + timedelta(days=3)).isoformat()
        now_str = now.isoformat()

        with self._calendar_connection() as conn:
            conn.row_factory = sqlite3.Row

            # --- Untriggered events within 3 days ---
            rows = conn.execute("""
                SELECT * FROM user_calendar
                WHERE triggered = 0 AND event_date >= ? AND event_date <= ?
                ORDER BY event_date ASC
            """, (now_str, cutoff)).fetchall()

            for row in rows:
                event_date = datetime.fromisoformat(row["event_date"])
                days_until = (event_date - now).total_seconds() / 86400

                # Set urgency based on proximity
                if days_until < 1:
                    urgency = 0.7
                    hint_prefix = "Today is the day"
                elif days_until < 2:
                    urgency = 0.6
                    hint_prefix = "Tomorrow is"
                else:
                    urgency = 0.45
                    hint_prefix = f"Coming up in {int(days_until)} days"

                # Boost for high-importance or strong-feeling events
                if row["importance"] > 0.7 or row["feeling"] not in ("neutral", ""):
                    urgency = min(urgency + 0.1, 1.0)

                hint = (
                    f"{hint_prefix}: {row['event_name']}. "
                    f"Bring it up naturally — ask them about it or wish them well."
                )

                if self._life_trigger_cooled_down("upcoming_event", now):
                    if self._follow_up_provider is None:
                        continue        # no trigger fired — leave the row untriggered
                    fm = self._follow_up_provider(self._persona_id)
                    fm.create_trigger(
                        trigger_type="UPCOMING_EVENT",
                        topic=row["event_name"],
                        context=f"calendar_event:{row['id']}",
                        urgency=urgency,
                        prompt_hint=hint,
                    )
                    self._record_life_trigger_cooldown("upcoming_event", now)

                    # Mark triggered
                    conn.execute(
                        "UPDATE user_calendar SET triggered = 1 WHERE id = ?",
                        (row["id"],),
                    )

            # --- Promote passed recurring events to anniversaries ---
            past_recurring = conn.execute("""
                SELECT * FROM user_calendar
                WHERE recurring = 1 AND promoted_to_anniversary = 0
                  AND event_date < ?
            """, (now_str,)).fetchall()

            for row in past_recurring:
                event_date = datetime.fromisoformat(row["event_date"])
                date_mm_dd = event_date.strftime("%m-%d")
                self._continuity.add_anniversary(
                    name=row["event_name"],
                    date_str=date_mm_dd,
                    yearly=True,
                )
                conn.execute(
                    "UPDATE user_calendar SET promoted_to_anniversary = 1 WHERE id = ?",
                    (row["id"],),
                )
                logger.debug("[CALENDAR] Promoted recurring event id=%s to anniversary", row["id"])

            # --- Post-event check-ins: ask how a just-passed event went ---
            window_start = (now - timedelta(hours=48)).isoformat()
            passed_events = conn.execute("""
                SELECT * FROM user_calendar
                WHERE followed_up = 0 AND recurring = 0
                  AND event_date < ? AND event_date >= ?
            """, (now_str, window_start)).fetchall()

            for row in passed_events:
                if not self._life_trigger_cooled_down("event_check_in", now):
                    break
                if self._follow_up_provider is None:
                    break           # no trigger fired — leave the row un-followed-up
                fm = self._follow_up_provider(self._persona_id)
                fm.create_trigger(
                    trigger_type="EMOTIONAL_CHECK_IN",
                    topic=row["event_name"],
                    context=f"calendar_event_passed:{row['id']}",
                    urgency=0.7,
                    emotional_weight=0.7,
                    prompt_hint=(
                        f"The user's event '{row['event_name']}' just happened."
                        f" Ask warmly how it went — you remembered it mattered to them."
                    ),
                )
                conn.execute(
                    "UPDATE user_calendar SET followed_up = 1 WHERE id = ?", (row["id"],)
                )
                self._record_life_trigger_cooldown("event_check_in", now)
                logger.debug("[CALENDAR] Post-event check-in triggered for entry id=%s", row["id"])

            # --- Retention: drop rows that can never fire again ---
            # A non-recurring event past the retention window is finished
            # business: the block above only looks forward, the check-in block
            # only looks back 48h, and promotion applies to recurring rows only.
            # Every scan re-queries this table in full, so leaving them costs on
            # every tick forever. Recurring rows are the anniversary source and
            # are kept.
            retention_cutoff = (
                now - timedelta(days=CALENDAR_RETENTION_DAYS)
            ).isoformat()
            conn.execute(
                "DELETE FROM user_calendar WHERE recurring = 0 AND event_date < ?",
                (retention_cutoff,),
            )

    def _generate_gap_narrative(self, hours: float) -> str:
        """Generate a narrative summarizing a long gap period."""
        days = hours / 24

        if days >= 7:
            return "The past week has been a mix of quiet routines and small adventures. She's been keeping busy with her usual interests."
        elif days >= 2:
            return "The last few days passed in a comfortable rhythm of activities, rest, and contemplation."
        else:
            return "She spent the time in her usual way - a blend of rest, creativity, and quiet moments."
