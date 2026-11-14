"""
Life Service

Main facade for a persona's autonomous life system.
Coordinates world, energy, activities, goals, and scheduling.
"""

import contextlib
import json
import logging
import math
import random
import re
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

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
    Season,
    ShareableExperience,
    ShortTermDesire,
    SkillProgress,
    SocialEvent,
    TimeOfDay,
    TransitPhase,
    TransitState,
)
from .world import WorldEnvironment
from .world.environment import PersonaWorldView
from .energy import EnergySystem
from .activities import ActivityEngine
from .activities.activity_engine import outcome_chances
from .activities.choice import ActivityPreferences, ChoiceState, pressing_needs
from .emotion.appraisal import (
    FAIL,
    OUTCOMES,
    SUCCESS,
    AppraisalEvent,
    appraise,
    appraised_valence,
    emotions_of,
    llm_appraisal_prompt,
    parse_llm_appraisal,
    spikes_from_llm,
)
from .emotion.text_emotion_analyzer import (
    EmotionSpike,
    TextEmotionAnalyzer,
    addresses_listener,
    matched_cues,
)
from .emotion.user_appraisal import (
    AMUSEMENT_EMOTION, CONCERN_EMOTION, GLAD_EMOTION, appraisal_valence, appraise_user_turn,
)
from .goals import GoalEngine
from .planner import DailyPlanner
from .planner.daily_planner import NOT_HABIT_FORMING, SOCIAL_PLAN_REASON_PREFIX
from .behavior.behavior_system import habit_band
from aura_life.conversation_session import ConversationSession
from aura_life.planner.daily_planner import USER_AGREED_REASON, is_important_activity
from .scheduler import LifeScheduler
from .context import LifeContextBuilder
from .context.moment import Moment, build_moment
from .intimacy import DesireSystem
from .social import SocialSystem
from .social.household import JOINT_LINES, Household, HousemateState, JointSide, name_list
from .social.social_system import (
    MEANINGFUL_CONTACT_TYPES,
    NPC_EVENT_CHANCE,
    UNWELCOME_KIND_EMOTIONS,
    UNWELCOME_STRESSOR,  # noqa: F401 -- legacy name; the "unwelcome" stressor's words
)
from .identity import IdentitySystem
from .affect import AffectSystem
# Mood-model constants live in affect_system's "Mood model" block, the
# stressors in its "Stress" block.
from .affect.affect_system import (
    ANTICIPATION_MOOD_PER_HOUR,
    GOAL_COMPLETION_EMOTIONS,
    MOOD_VALENCE_BAND,
    STRESSOR_KINDS,
    WORK_EVENT_EMOTIONS,
    mood_label,
)
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
from .memory import Episode, MemoryStream, contact_phrase, mean_valence
from .memory.episodes import conversation_phrase, place_phrase
# A gist's own cleaning (first sentence, numbers in words, no snake_case) and
# its number words, for the words of a proactive hint (Task 17, ruling T17-R4).
from .memory.episodes import _number_words, _plain
from .expression.relationship import (
    ABSENCE_AFTER_HOURS,
    IN_CONVERSATION_MINUTES,
    AfterAbsence,
    after_absence as absence_state,
    silent_days,
)
from .memory.reflection import (
    BELIEF_INTENSITY,
    BELIEF_REPEAT_COOLDOWN_DAYS,
    REFLECTION_THRESHOLD,
    belief_key_from_tag,
    belief_key_tag,
    generate_beliefs,
    validate_llm_belief,
)
from .money import FinanceSystem
from .money.finance_system import MAX_FINANCIAL_STRESS, STARTING_RUNWAY
from .job import CareerSystem
from .habitation import HabitationSystem
from .habitation.habitation_system import COMFORT_BLEAK
from .sustenance import SustenanceSystem
from .sustenance.sustenance_system import TICK_HOURS as SUSTENANCE_TICK_HOURS
from .skills import SkillsSystem
from .errands import ErrandsSystem
from .errands.errands_system import MAX_TOTAL as ERRANDS_MAX_TOTAL
from .location import LocationSystem
from .transportation import TransportSystem
from .personas.parameters import PersonaParameters
from .personas.pronoun_render import (
    render_line as _render_pronoun_line,
    render_second_person as _render_second_person,
    user_tokens as _user_ref_tokens,
)
from .settings import DEFAULT_SETTING, get_setting
from .settings.spec import COMMITMENT_TAGS, DEFAULT_NPC_KIND
from .settings.contemporary import PLACES as _CONTEMPORARY_PLACES
# Legacy names: the micro-events, the skill tables, the dream templates and the
# catch-up and gap narratives moved, unchanged, into the contemporary setting
# pack (aura_life.settings.contemporary) in Task 9 -- the service reads its
# persona's setting now; re-exported so an import from here keeps working.
from .settings.contemporary import (  # noqa: F401
    CATCHUP_AFTERNOON_NARRATIVES,
    CATCHUP_EVENING_NARRATIVES,
    CATCHUP_LATE_NARRATIVE,
    CATCHUP_MIDDAY_NARRATIVES,
    CATCHUP_MORNING_ACTIVITY_NARRATIVES,
    CATCHUP_MORNING_ROUTINE_NARRATIVES,
    CATCHUP_SLEEP_NARRATIVE,
    DREAM_TEMPLATES,
    GAP_NARRATIVE_DAYS,
    GAP_NARRATIVE_SHORT,
    GAP_NARRATIVE_WEEK,
    MICRO_EVENTS,
    SKILL_MAPPINGS,
    SKILL_MILESTONES,
)

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
#: The affect stressor while strained or worse: what she is stressed about, in
#: words (Task 15: "keeping it together", the "sanity" kind of affect's
#: STRESSOR_KINDS; it was the engine's name, "sanity", until then).
SANITY_STRESS_SOURCE = STRESSOR_KINDS["sanity"].words
SANITY_FRAYING_RESTRAINT_PRESSURE = 0.2     # shadow restraint pull while fraying or worse
SANITY_BREAKING_REGULATION_COLLAPSE = 1.0   # regulation capacity drained on entering breaking
# Affect stress *level* at or above which the sanity tick reads the persona as
# stressed -- the level, not whether any stressor is listed: every persona has
# something small on her mind most of the time (money a little tight, errands
# piling up, things put off -- about 0.1 together, each at most affect's
# STRESSOR_SEVERITY), so a listed stressor alone would erode every persona to
# ``broken`` in days without a single blow. 0.2 is the floor of affect's own
# ``get_stress_description()`` -- below it, affect has nothing to say about
# stress -- and it takes four hassles at their fullest to reach it.
SANITY_STRESSED_LEVEL = 0.2

# Small one-shot nudge applied via AffectSystem.on_weather_nudge() on WEATHER CHANGE
# (not every tick), so the push is bounded. Scale factors are unitless: the nudge
# moves mood's valence that share of the way toward +1 or -1
# (AffectSystem._nudge_valence). The affect engine scales it again by her weather
# sensitivity (PersonaParameters.weather_mood_scale).
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

#: The chance, per activity tick, of one small moment from her setting's
#: micro_events (SettingSpec). Per persona, times
#: PersonaParameters.micro_event_scale (openness).
MICRO_EVENT_CHANCE = 0.20

#: A gap between two sustenance ticks longer than this is a paused host,
#: walked an energy interval at a time (LifeService._tick_sustenance): the
#: scheduler ticks every 5 minutes, the legacy simulations every 15 or 30,
#: so an hour is well past any tick's own spacing. Chosen (Task 10 fix round).
SUSTENANCE_GAP_HOURS = 1.0


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
    # Disagreement cues no longer get healthy_debate's mood boost -- disagreeing
    # with the user is not, on its own, a positive event. "you're wrong" reads
    # as criticism instead; the rest keep only their non-affect effect.
    "i disagree": [("cognitive", "disagreement")],
    "you're wrong": [("affect", "criticism"), ("cognitive", "defending_opinion")],
    "no way": [("cognitive", "defending_opinion")],
    "don't you think": [("cognitive", "philosophical_question")],
    "but what about": [("cognitive", "intellectual_topic")],
    "agree to disagree": [("identity", "standing_ground")],
    "that's not": [("cognitive", "defending_opinion")],
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

# ============= Reflection & Nostalgia from real history (Task 13) =============

#: Nostalgia draws from an episode this many simulated days old or more
#: (the Task 13 brief, verbatim); younger than that, only the setting's ten
#: templates (aura_life.settings.contemporary.NOSTALGIA_MEMORIES) are drawn.
NOSTALGIA_MIN_EPISODE_AGE_DAYS = 7.0

# Relationship stages (ExpressionSystem) considered "close". An AI persona only
# unlocks human-like spontaneous/emotional proactive behavior once the bond is
# this deep; before then she stays in practical/reminder territory. Humans are
# never gated by this.
CLOSE_RELATIONSHIP_STAGES = {"comfortable", "deep"}


def _conversation_kind(appraisal, disclosure: float, felt_most, topics) -> Optional[str]:
    """Which :data:`aura_life.memory.episodes.CONVERSATION_PHRASES` line a
    user's turn is to her (humanness Task 16b step 0, ruling T16a-R2):
    hostility aimed at her, then a disclosure, then warmth aimed at her, then
    the feeling she has most (concern, amusement, gladness for them), then
    plain talk when the host gave topics or she felt something else; ``None``
    for a turn that left no trace -- no topics, no disclosure, nothing felt."""
    if appraisal.hostility > 0.0:
        return "hostile"
    if disclosure > 0.0:
        return "disclosure"
    if appraisal.warmth > 0.0:
        return "sweet"
    if felt_most is not None:
        name = {CONCERN_EMOTION: "concerned", AMUSEMENT_EMOTION: "amused", GLAD_EMOTION: "warm"}.get(felt_most[0])
        return name or "talk"
    return "talk" if topics else None


def _move_persona_to(service, location: str) -> None:
    """Move *service*'s persona to *location* (Task 27 / ruling T8-R1).

    Before this existed, every call site below called
    ``service._world.move_to(location)`` directly, which relocates a world
    :class:`LifeService` shares with other personas for every one of them --
    the shared world held one ``current_location``, and one persona's move
    changed it for everyone reading it (measured: another persona moved the
    shared world after a persona's own tick in 82 of 288 steps). Every one of
    those call sites now goes through this instead.

    Always sets *service*'s own ``_current_location`` (a plain attribute
    assignment; harmless if *service* is a duck-typed stand-in that never
    reads it back). The world itself is only told to move when *service* is
    not sharing it (``getattr(service, "_shared_world", False)`` -- falsy for
    both a private world and a stand-in with no such attribute at all), so a
    private world keeps today's behaviour exactly, and a shared one is never
    written by one persona's move.

    A free function taking *service* explicitly, rather than a method looked
    up on ``self`` (e.g. ``self._move_to(location)``), on purpose: three of
    the call sites below (``apply_schedule_override``,
    ``schedule_meeting_arrival``, ``advance_transit_phase``) can run bound to
    a duck-typed stand-in that is not a ``LifeService`` at all and defines no
    such method (see ``tests/test_planner_clock.py``'s ``_ScheduleStandIn``);
    looking up ``self._move_to`` there would raise ``AttributeError`` before
    this function's own tolerance ever ran. Passing *service* as an argument
    never does.
    """
    service._current_location = location
    if not getattr(service, "_shared_world", False):
        service._world.move_to(location)


def _plan_instant(service) -> Optional[datetime]:
    """The instant *service*'s day plan is read and rewritten at: her local
    world time (:meth:`LifeService._local_world_now`) -- her plan's hours
    are her local hours (humanness program Task 28, ruling T13-R1).

    A free function taking *service*, like :func:`_move_persona_to` and for
    its reason: ``apply_schedule_override``, ``schedule_meeting_arrival``,
    ``add_conversation_plan`` and ``advance_transit_phase`` can run bound to
    a duck-typed stand-in (aura tests ``add_conversation_plan`` on one; see
    ``tests/test_planner_clock.py``). A stand-in without
    ``_local_world_now`` gets ``None``, which the planner reads as the
    host's wall clock, as before.
    """
    local_now = getattr(service, "_local_world_now", None)
    return local_now() if callable(local_now) else None


def _add_sentence(text: str, sentence: str) -> str:
    """``text`` with ``sentence`` after it, each ending a sentence: an
    activity's narrative is written without a closing stop (the lines
    appended after it bring their own)."""
    text = text.rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    return f"{text} {sentence}." if text else f"{sentence}."


def _share_ids(*items) -> tuple:
    """The stable share ids (spec section 4.9: "share:<n>", "event:<n>") of
    whichever of ``items`` -- shareable experiences, life events, ``None``
    for one not made -- there are: how an episode of her memory stream is
    tied to what she may share of it (Task 12)."""
    return tuple(item.share_id for item in items if item is not None and getattr(item, "share_id", ""))


#: The prefixes of the stable share ids (spec section 4.9) an episode's tags
#: carry, put there by :func:`_share_ids`.
SHARE_ID_PREFIXES = ("share:", "event:")


def _share_ids_of(episode) -> tuple:
    """The share ids an episode's tags carry, in the order :func:`_share_ids`
    put them there (a shareable before its life event)."""
    return tuple(tag for tag in getattr(episode, "tags", ()) if str(tag).startswith(SHARE_ID_PREFIXES))


def _told(episode) -> str:
    """An episode's gist as a proactive hint goes on with it after a colon:
    its first letter lowered, unless what happened begins with a capital (a
    name, "You")."""
    gist = episode.gist()
    return gist if _plain(episode.what)[:1].isupper() else gist[:1].lower() + gist[1:]


#: The words in -ing that name a time, not a verb: a time of day or a season
#: (:class:`~aura_life.models.TimeOfDay`, :class:`~aura_life.models.Season`)
#: -- "morning shower" is a thing she has, not something she is "morning".
_TIME_WORDS = frozenset(t.value for t in TimeOfDay) | frozenset(s.value for s in Season)
#: The articles a setting's activity name can start with ("a concert").
_ARTICLES = ("a", "an", "the")


def _doing(activity: str, place: str = "") -> str:
    """What she is doing, as a proactive hint says it (ruling T17-R4: a plan
    slot's name is phrased, never pasted after "You're"): an activity named
    by its verb ("reading", "going for a run") is "You're reading", one named
    by a thing ("yoga", "picnic in the park", "morning shower": a first word
    in -ing that is a time, :data:`_TIME_WORDS`, is no verb) "You're in the
    middle of your yoga" -- of "a concert", with its own article, "You're in
    the middle of a concert"; then where, as a gist says it ("at the
    gym")."""
    words = " ".join(str(activity or "").split())
    doing = "You're " + _doing_lead(words).replace("{poss}", "your") + words
    where = place_phrase(place)
    return f"{doing} {where}" if where else doing


def _doing_lead(activity: str) -> str:
    """The words :func:`_doing`'s rule puts before an activity's name: ""
    for one named by its verb ("reading"), "in the middle of " for one with
    its own article ("a concert"), else "in the middle of {poss} " ("yoga",
    "morning shower") -- ``{poss}`` her possessive token, left for the
    renderer the text goes through (a dream's text is told both in the third
    person and to her, ruling T18-R8)."""
    words = " ".join(str(activity or "").split())
    first = words.split(" ", 1)[0].lower() if words else ""
    if first.endswith("ing") and first not in _TIME_WORDS:
        return ""
    if first in _ARTICLES:
        return "in the middle of "
    return "in the middle of {poss} "


def _phrase_after_was(template: str, fields: Dict[str, str]) -> str:
    """``template`` with each ingredient it puts right after ``{was}`` led
    by :func:`_doing_lead` (ruling T18-R8: "Dreamed you were yoga" is "Dreamed
    you were in the middle of your yoga"); the fields themselves unchanged."""
    for key, value in fields.items():
        slot = "{was} {" + key + "}"
        if slot in template:
            template = template.replace(slot, "{was} " + _doing_lead(value) + "{" + key + "}")
    return template


def _create_follow_up(fm, *, share_id: str = "", **fields) -> None:
    """``fm.create_trigger(**fields)`` -- plus ``share_id`` when the hint is
    about something she may share and the host's follow-up object declares
    ``accepts_share_id = True`` (ruling T17-R1). Neither aura's nor
    aura-desk's takes one today, and aura's adapter forwards an unknown
    keyword to a manager that would raise, so without that declaration the
    call is exactly what it was."""
    if share_id and getattr(fm, "accepts_share_id", False) is True:
        fields["share_id"] = share_id
    fm.create_trigger(**fields)


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

    #: This service decays the ``emotion_engine`` a host injects, on the world
    #: clock, from its energy tick (``_decay_emotion_engine``). A host that sees
    #: this ``True`` must not decay that engine itself as well (``decay_tick()``
    #: on its own schedule), or the engine decays twice. Absent on aura-life
    #: before 0.6, where the host had to decay it.
    decays_emotion_engine = True

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
        household: Optional[Household] = None,
        reflection_llm: bool = False,
        appraisal_llm: bool = False,
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
            memory_service: Optional memory service for integration: the
                host's, kept for it and not read here. Her own memory of
                her life is her memory stream (:meth:`recall`,
                :mod:`aura_life.memory`), in ``db_path``.
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
                Its ``setting`` names the setting pack her engines draw their
                catalogues from (:mod:`aura_life.settings`; empty, or no
                definition, is the default ``contemporary`` pack). An unknown
                key raises ``ValueError`` naming it and every registered key.
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
            rng: Optional ``random.Random`` seeding every draw this persona's
                engines make. Every engine that draws randomness -- desire,
                habitation, cognitive, drive, career, finance, errands,
                identity, memory-time, life-events, sleep (the energy-tick
                path ruling T4-R1 first gave its own stream), plus activity
                selection, chaos, the daily planner's own bare draws (not its
                per-day, per-role ``crc32``-seeded ones -- see
                :class:`~aura_life.planner.daily_planner.DailyPlanner`), the
                body's sleep/daily-health rolls, social, behaviour, goals and
                transport (ruling T26-R2, which generalised the sleep-stream
                pattern from "the energy-tick path" to every engine, full
                stop), her household's joint activities (Task 11), how
                each of her activities goes and each day's quality (Task 14)
                -- draws from a stream of its own
                (:meth:`_derive_stream`), derived from this rng's state at
                construction plus that engine's name as a label (``"desire"``,
                ``"habitation"``, ``"finance"``, ``"career"``, ``"errands"``,
                ``"identity"``, ``"cognitive"``, ``"drive"``, ``"memory_time"``,
                ``"life_events"``, ``"sleep"``, ``"activity"``, ``"chaos"``,
                ``"daily_planner"``, ``"body"``, ``"social"``, ``"behavior"``,
                ``"goal_engine"``, ``"transport"``, ``"household"``,
                ``"outcome"``, ``"day_quality"``): **a draw-count change in
                one engine never moves another engine's draws**, because
                deriving a label's stream only reads this rng's state and
                never consumes it, so it makes no difference which engine's
                stream is derived first or how many draws any engine takes
                afterward. The service's own direct draws (the
                struggle-to-rumination roll, the shareable priority, the
                life-trigger picks, the trip roll) draw from a stream of its
                own too, ``self._service_rng`` (label ``"service"``), derived
                exactly the same way -- so drawing from the raw ``rng`` itself
                after construction (as a host inspecting or reusing it might)
                cannot move any engine's draws either, service included.
                ``None`` -- the default -- leaves every draw on the
                module-level ``random`` exactly as before, so an existing
                consumer is byte-identical. Given, no draw touches module
                ``random``, so a host that ticks two services from two
                equal-seeded rngs gets two identical runs.
                A :class:`~aura_life.world.WorldEnvironment` handed in
                (``world_environment=``) is excluded: a world can be shared
                by every persona in a household, so it is never derived from
                any one persona's ``rng`` -- it owns its own ``rng``/``seed``
                constructor argument instead. The private world this service
                builds when none is handed in takes the label ``"world"``
                stream, and module ``random`` when ``rng`` is ``None``, like
                every engine (ruling T35-R1). Persona
                generation (:mod:`~aura_life.personas.genre_randomizer`,
                :mod:`~aura_life.personas.place_generation`) already takes
                its own rng through a separate, one-shot path and is not
                routed here either.
            household: Optional :class:`~aura_life.social.household.Household`
                shared by the services of personas who live together (spec
                section 4.5; ``PersonalityDefinition.household`` lists the
                members she expects). The service joins it under
                ``persona_id`` -- required then -- once it is built, leaves
                it in :meth:`stop` and joins it again in :meth:`start`: a
                runtime link, nothing of which is saved. Her view of each
                housemate is the housemate's live state (asleep, where, doing
                what), and her social-circle entry for a housemate draws no
                ordinary NPC event; one she expects who is not joined is an
                ordinary NPC. ``None`` -- the default -- is a persona living
                alone, exactly as before.
            reflection_llm: Whether her reflections (Task 13, spec section
                4.6) may ask the host's LLM (``get_llm_service``, guarded --
                a missing or raising hook leaves the deterministic beliefs
                exactly as they are, with no ERROR) for one more belief on
                top of the deterministic ones :meth:`_reflect` always
                derives from her memory stream. ``False`` -- the default --
                never calls it: ruling R4, every optional LLM path in
                aura-life is off unless the host turns it on. The client is
                called synchronously on her tick -- under the household's
                lock when she has housemates -- and must return or raise
                within a bounded time: that bound is the host client's, not
                aura-life's (ruling T14-R2; a raise falls back as above).
            appraisal_llm: Whether what she feels about how an activity went
                (Task 14, :mod:`aura_life.emotion.appraisal`) may be asked of
                the host's LLM (``get_llm_service``, guarded) instead of the
                deterministic appraisal: its reply is validated -- a feeling
                the emotion vocabulary does not know is dropped, so is one
                that contradicts how it went (a failure felt as joy), each
                intensity clamped to 0..1, at most three kept -- and scaled
                by her volatility; a missing or raising hook, or a reply with
                nothing usable, leaves the deterministic appraisal exactly as
                it is, with no ERROR. ``False`` -- the default -- never calls
                it (ruling R4). The client is called synchronously on her
                activity tick -- under the household's lock when she has
                housemates -- and must return or raise within a bounded time:
                that bound is the host client's, not aura-life's (ruling
                T14-R2; a raise falls back as above).
        """
        # The world she lives in: every engine below reads its catalogues from
        # this setting pack (aura_life.settings; an empty
        # ``definition.setting`` is the default, "contemporary"). Resolved
        # first, so an unknown key raises ValueError -- naming it and every
        # registered key -- before anything touches the disk.
        self._setting = get_setting(getattr(definition, "setting", None) if definition is not None else None)
        if household is not None and not persona_id:
            raise ValueError("A LifeService in a household needs a persona_id: members are known by it")
        # The people she lives with (Task 11): joined at the end of
        # construction, once she is whole for a housemate to read. In memory
        # only, like the rest of it: until when a housemate's activity she
        # joined takes her activity tick (_join_housemate), and the world
        # instant of her last activity tick.
        self._household = household
        self._joint_until: Optional[datetime] = None
        # Her local world time when she joined it: what she is doing is read
        # from her plan at it until _joint_until (_activity_instant, Task 19).
        self._joint_at: Optional[datetime] = None
        self._activity_tick_at: Optional[datetime] = None
        # What the people she lives with see of her, as of her last tick
        # (_publish_household_state).
        self._household_state: Optional[HousemateState] = None
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
        # Her occupation and interests: the host's when it passes them, else
        # her definition's -- one source for every engine that reads them
        # (the career, the planner, the places they add; Task 10). They were
        # the host's arguments only, so a host that handed over a definition
        # alone got a career with an occupation and a planner without one.
        self._occupation = occupation or ((getattr(definition, "occupation", "") or "") if definition is not None else "")
        self._interests = list(interests or ((getattr(definition, "interests", None) or []) if definition is not None else []))
        self._persona_locations = persona_locations or {}
        # This persona's own current location -- never the (possibly shared)
        # world's, see _move_persona_to(). "home" matches
        # WorldEnvironment.__init__'s own default for a fresh instance.
        self._current_location: str = "home"
        self._persona_id = persona_id
        self._user_model_provider = user_model_provider
        self._follow_up_provider = follow_up_provider
        self._definition = definition
        self._social_circle_defs = social_circle or []
        self._media_preferences = media_preferences or {}
        self._user_info = user_info

        # Initialize subsystems — pass persona_locations and sleep_schedule to world and planner.
        # A world this service was handed (world_environment is not None) may be
        # shared with other LifeService instances, so it is never written to here
        # -- doing so would make whichever persona is constructed last decide the
        # room description and time-of-day phase for everyone sharing it (see
        # PersonaWorldView and _persona_time_of_day for how each persona still
        # gets her own instead).
        # A private world takes its own stream derived from an injected rng
        # (label "world"), so a seeded service gets reproducible weather too;
        # without an injected rng it draws from module ``random``, as every
        # engine does then (_derive_stream(None, ...)) and as every released
        # version's world did (ruling T35-R1). A world the host builds itself
        # keeps its own stream (WorldEnvironment's rng/seed).
        self._world = world_environment or WorldEnvironment(
            persona_locations=self._persona_locations,
            sleep_schedule=sleep_schedule,
            rng=self._derive_stream(rng, "world"),
            setting=self._setting,
        )
        self._shared_world = world_environment is not None
        # Extract core_traits once for all engines
        self._core_traits = getattr(definition, 'core_traits', []) if definition else []
        # Her traits, compiled once (explicit traits win, the rest inferred
        # from core_traits, 0.5 otherwise), and the engine parameters they set
        # (the table in aura_life.personas.parameters). Every engine that
        # reads a trait takes them from here; no definition is every trait
        # 0.5, which is every engine exactly as before.
        self._params = PersonaParameters.from_definition(definition)
        self._micro_event_chance = MICRO_EVENT_CHANCE * self._params.micro_event_scale
        # The chance, per activity tick, that she asks the people she lives
        # with into a joint activity she is about to do (Task 11): chosen as
        # the chance one of her people gets in touch on an activity tick
        # (SocialSystem's NPC_EVENT_CHANCE, times her sociability's
        # npc_event_scale).
        self._joint_chance = NPC_EVENT_CHANCE * self._params.npc_event_scale
        # Her standing preferences over her setting's activities (Task 10,
        # aura_life.activities.choice): what her traits make of each need,
        # and what she is into -- her interests, comfort zones, tastes,
        # media and substances, from her definition (the interests and media
        # a host passed win, as they do everywhere else). Her activity
        # choice and her plan's free hours both read them.
        self._preferences = ActivityPreferences.from_definition(
            definition, self._params, interests=self._interests, media_preferences=self._media_preferences)
        # Her activities that end each kind of stressor she can end herself
        # (Task 15; _resolving_activities), found once per kind.
        self._resolving_cache: Dict[str, FrozenSet[str]] = {}
        # The tick-path rng. ``_rng`` is what the host gave (None or a Random)
        # and is threaded into every engine that draws on the energy tick;
        # ``_random`` is what this class itself draws from (module ``random``
        # when nothing was injected, so the default is byte-identical).
        self._rng = rng
        self._service_rng = self._derive_stream(rng, "service")
        # Each night's sleep window comes from a stream of its own (see
        # _sleep_stream), taken before any engine below draws.
        self._sleep_rng = self._sleep_stream(rng)
        # Every other engine on the energy-tick path gets a stream of its own
        # the same way (see _derive_stream) -- derived here, before any of
        # them is constructed and before the service's own draws on
        # self._service_rng happen, so a change to how many draws one engine
        # makes can never move another's (see the rng parameter docstring).
        self._desire_rng = self._derive_stream(rng, "desire")
        self._habitation_rng = self._derive_stream(rng, "habitation")
        self._finance_rng = self._derive_stream(rng, "finance")
        self._career_rng = self._derive_stream(rng, "career")
        self._errands_rng = self._derive_stream(rng, "errands")
        self._identity_rng = self._derive_stream(rng, "identity")
        self._cognitive_rng = self._derive_stream(rng, "cognitive")
        self._drive_rng = self._derive_stream(rng, "drive")
        self._memory_time_rng = self._derive_stream(rng, "memory_time")
        self._life_events_rng = self._derive_stream(rng, "life_events")
        # Ruling T26-R2: every engine that draws randomness gets its own
        # stream this way, not only the ones that used to share self._rng
        # directly -- these eight used to read module random with no rng
        # parameter at all. WorldEnvironment is excluded: it is shared across
        # personas (a household), so it does not take a persona stream --
        # see its own rng/seed constructor argument instead.
        self._activity_rng = self._derive_stream(rng, "activity")
        self._chaos_rng = self._derive_stream(rng, "chaos")
        self._daily_planner_rng = self._derive_stream(rng, "daily_planner")
        self._body_rng = self._derive_stream(rng, "body")
        self._social_rng = self._derive_stream(rng, "social")
        self._behavior_rng = self._derive_stream(rng, "behavior")
        self._goal_engine_rng = self._derive_stream(rng, "goal_engine")
        self._transport_rng = self._derive_stream(rng, "transport")
        # Task 11: whether she asks the people she lives with into what she
        # does, and the lines that say so -- a stream of her own, so living
        # with someone moves no other engine's draws.
        self._household_rng = self._derive_stream(rng, "household")
        # Task 14: how each of her activities goes, and the words for one
        # that did not go well -- a stream of its own, so an outcome never
        # moves the activity choice's draws or the service's.
        self._outcome_rng = self._derive_stream(rng, "outcome")
        # Task 14 fix round (ruling T14-R1): each day's quality -- one draw a
        # persona-day (_draw_day_quality), on a stream of its own.
        self._day_quality_rng = self._derive_stream(rng, "day_quality")
        if sanity_rng is None:
            sanity_rng = rng

        _defn = self._definition
        # AI personas have no body/finances/home/commute — gate the physical-life
        # engines off so an AI companion doesn't "get hungry" or "pay rent".
        # Known before the energy system is built, so an AI never sleeps and
        # carries no sleep-physiology in its digest from its first state on.
        self._is_ai = (getattr(_defn, 'persona_type', 'human') == 'ai') if _defn else False

        self._energy = EnergySystem(
            sleep_schedule=sleep_schedule,
            core_traits=self._core_traits,
            is_ai=self._is_ai,
            now=self._world_clock(),
            params=self._params,
        )
        self._activity_engine = ActivityEngine(rng=self._activity_rng, setting=self._setting,
                                               persona_id=persona_id, preferences=self._preferences,
                                               outcome_rng=self._outcome_rng)
        # Her goals are hers (Task 10): her personal goal, interests, values and
        # struggles first, then the best fits of her setting's pools.
        self._goal_engine = GoalEngine(rng=self._goal_engine_rng, setting=self._setting, definition=definition,
                                       parameters=self._params, persona_id=persona_id,
                                       interests=self._interests)
        self._desire_system = DesireSystem(
            core_traits=self._core_traits, rng=self._desire_rng, gender=self._persona_gender(),
            params=self._params, setting=self._setting, intimacy_rate=self._intimacy_rate(),
        )

        # New subsystems — seeded from the persona profile where applicable.
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
            rng=self._habitation_rng,
        )
        self._room_state = self._habitation.state  # back-compat alias (same object)
        self._finance = FinanceSystem(core_traits=self._core_traits, rng=self._finance_rng,
                                      now=self._world_clock()(), params=self._params)
        if _defn and getattr(_defn, 'spending_habit', None) is not None:
            self._finance.state.spending_habit = _defn.spending_habit
        self._financial = self._finance.state  # back-compat alias (same state object)
        _salary = getattr(_defn, 'monthly_salary', None) if _defn else None
        self._career = CareerSystem(occupation=self._occupation, monthly_salary=_salary, rng=self._career_rng,
                                    setting=self._setting)
        # Align the Job engine's schedule with the planner's occupation type so
        # "on shift" matches when the planner schedules work.
        self._apply_occupation_schedule(self._career, self._occupation)
        # Job pays the bills: salary drives finance income.
        if self._career.monthly_salary > 0:
            self._finance.state.monthly_income = self._career.monthly_salary
        self._media = self._init_media_state()
        self._skills_system = SkillsSystem()
        self._skills: Dict[str, SkillProgress] = self._skills_system.skills  # alias
        self._errands = ErrandsSystem(rng=self._errands_rng)
        npcs = self._build_npcs(self._social_circle_defs)
        self._social = SocialSystem(npcs=npcs, rng=self._social_rng, params=self._params,
                                    setting=self._setting)
        self._identity = IdentitySystem(
            npcs=npcs, user_info=self._user_info, core_traits=self._core_traits,
            humor_style=getattr(definition, 'humor_style', '') if definition else '',
            core_values=getattr(definition, 'core_values', []) if definition else [],
            struggles=getattr(definition, 'struggles', []) if definition else [],
            character_defects=getattr(definition, 'character_defects', []) if definition else [],
            behavioral_tendencies=getattr(definition, 'behavioral_tendencies', {}) if definition else {},
            rng=self._identity_rng,
            params=self._params,
        )
        self._affect = AffectSystem(
            core_traits=self._core_traits,
            emotional_baseline=getattr(definition, 'emotional_baseline', {}) if definition else {},
            params=self._params,
        )
        # The body's seeds from her definition: her body-image baseline from
        # her struggles and core traits (PersonaParameters.body_image_struggle
        # -- the service never handed the body the definition until Task 10).
        self._body = BodySystem(
            hormonal_enabled=getattr(definition, 'hormonal_enabled', False) if definition else False,
            substance_tendencies=getattr(definition, 'substance_tendencies', {}) if definition else {},
            rng=self._body_rng,
            params=self._params,
        )
        self._cognitive = CognitiveSystem(
            core_traits=self._core_traits,
            intrusive_thought_themes=getattr(definition, 'intrusive_thought_themes', []) if definition else [],
            rng=self._cognitive_rng,
            params=self._params,
            setting=self._setting,
        )
        self._shadow = ShadowSystem(
            behavioral_tendencies=(getattr(definition, 'behavioral_tendencies', {}) if definition else {}) or {},
            character_defects=(getattr(definition, 'character_defects', []) if definition else []) or [],
            struggles=(getattr(definition, 'struggles', []) if definition else []) or [],
            intrusive_thought_themes=(getattr(definition, 'intrusive_thought_themes', []) if definition else []) or [],
            substance_tendencies=(getattr(definition, 'substance_tendencies', {}) if definition else {}) or {},
            core_traits=(getattr(definition, 'core_traits', []) if definition else []) or [],
            params=self._params,
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
        # The same for the affect tick, whose mood half-lives run in world hours.
        self._affect_ticked_at = self._world_clock()()
        # Where her live affect ticks began (here, a reset, a reload): the
        # downtime catch-up charges her affect the gap before it (Task 34b).
        # Kept in memory only, never saved.
        self._affect_live_since = self._affect_ticked_at
        # And for decaying the host's EmotionEngine (see decays_emotion_engine).
        self._emotion_decayed_at = self._world_clock()()
        # And for hunger, which rises per world hour (ruling T4-R4); taken
        # again on reload, so downtime is not charged as lived time.
        self._sustenance_ticked_at = self._world_clock()()
        # Where her live hunger ticks began (here, a reset, a reload): the
        # downtime catch-up charges her hunger the downtime before it, and of
        # a gap after it only the hours the live tick has not charged (Task
        # 34c). Kept in memory only, never saved.
        self._sustenance_live_since = self._sustenance_ticked_at
        # The last paused host's hours the live tick charged at once (the PC
        # slept, the process lived on): (their start, their end, her hunger
        # and nutrition at their start), so a catch-up of the same gap lives
        # them again in time order with its meals (Task 34c fix round 1). None
        # once a catch-up, a live meal, a reset or a reload has passed. In
        # memory only, never saved.
        self._sustenance_gap_charge = None
        # Elapsed-time stamp for periodic state persistence (see the end of
        # `_on_energy_tick`): so a crash between explicit `_save_state()`
        # calls loses at most an hour of simulated time.
        self._last_periodic_save_at = self._world_clock()()
        # The word the couplings were last applied for. Recorded, never applied
        # here: the couplings fire on a *change* of word, so a persona whose
        # baseline already sits below ``sound`` is not coupled for existing.
        self._sanity_coupled_state: str = self._sanity.state
        self._drive = DriveSystem(
            core_traits=self._core_traits,
            comfort_zone_seeds=getattr(self._definition, 'comfort_zone_seeds', []) if self._definition else [],
            rng=self._drive_rng,
            params=self._params,
        )
        self._behavior = BehaviorSystem(rng=self._behavior_rng)
        self._memory_time = MemoryTimeSystem(rng=self._memory_time_rng, setting=self._setting)
        self._expression = ExpressionSystem(communication_traits=self._communication_traits())
        self._continuity = ContinuitySystem()
        self._character_evolution = CharacterEvolution(
            original_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
            core_traits=getattr(self._definition, 'core_traits', []) if self._definition else [],
        )
        self._chaos = ChaosEngine(rng=self._chaos_rng, params=self._params, setting=self._setting)
        self._life_events = LifeEventSystem(rng=self._life_events_rng, setting=self._setting)
        # Her memory stream (Task 12, spec section 4.6): the episodes of her
        # life, in her database -- read once its tables exist (below), and
        # saved as each is written.
        self._memory = MemoryStream(self._db_path)
        # Whether her reflections may also ask the host's LLM (Task 13):
        # off by default (ruling R4).
        self._reflection_llm = bool(reflection_llm)
        # Whether what she feels about how an activity went may be asked of
        # the host's LLM (Task 14): off by default (ruling R4).
        self._appraisal_llm = bool(appraisal_llm)
        # The world instant she last reflected at (Task 13 fix round 1,
        # Minor 4): persisted explicitly (_save_reflection_state /
        # _load_reflection_state) rather than derived from the most recent
        # belief episode, which MemoryStream's 2,000-episode cap could
        # prune -- a pruned anchor would let a later reflection re-count
        # episodes already reflected on. Loaded in _load_state; None until
        # her first reflection or a load finds one saved.
        self._last_reflection_at: Optional[datetime] = None
        self._pipeline = None  # Set externally via set_pipeline()
        self._transit: Optional[TransitState] = None  # Active transit overlay
        self._transport = TransportSystem(rng=self._transport_rng)  # Travel estimation + mode
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
            occupation=self._occupation,
            interests=self._interests,
            sleep_schedule=sleep_schedule,
            persona_locations=self._persona_locations,
            nationality=getattr(definition, 'nationality', '') if definition else '',
            is_ai=self._is_ai,
            rng=self._daily_planner_rng,
            params=self._params,
            setting=self._setting,
            persona_id=self._persona_id,
            preferences=self._preferences,
            definition=self._definition,
            media_preferences=self._media_preferences,
        )
        # Supply the planner with derived location keys
        self._daily_planner._available_location_keys |= set(self._location_registry.keys())

        # Context builder. A shared world gets wrapped in a PersonaWorldView so
        # the location text it renders is this persona's own room, not
        # whichever persona's data self._world (the raw, possibly-shared
        # object -- kept as-is so callers holding a reference to it still see
        # the same instance) happens to carry; a place her profile does not
        # describe, and the weather, read from her setting. A private world already only
        # ever holds this persona's own data, so it is passed through untouched.
        self._context_builder = LifeContextBuilder(
            PersonaWorldView(self._world, self._persona_locations, lambda: self._current_location,
                             setting=self._setting)
            if self._shared_world else self._world,
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
        # Guards one affect tick (_tick_affect): the live energy tick (the
        # scheduler's thread, and start()'s init-tick thread) and the downtime
        # catch-up (the host's own thread) both tick her affect, and each tick
        # reads then writes her loneliness, mood and regulation -- interleaved,
        # one would write over the other's change (the hours of a whole gap).
        self._affect_tick_lock = threading.Lock()

        # Life-driven proactive trigger state (in-memory, not persisted)
        self._life_trigger_cooldowns: Dict[str, datetime] = {}
        self._prev_mood: Optional[str] = None
        self._prev_mood_intensity: float = 0.0
        self._prev_loneliness: float = 0.0
        self._last_seen_chaos_event: Optional[str] = None
        self._last_seen_nostalgia_ref: Optional[str] = None
        self._last_moment_share_chaos_event: Optional[str] = None
        self._pending_moment_share_chaos_event: Optional[str] = None
        # The dream and the goal completion a trigger was last made of (their
        # episode ids, Task 17), so one is not offered again once it fired.
        self._last_dream_share_episode: Optional[int] = None
        self._last_goal_share_episode: Optional[int] = None
        # Life events worth an EXCITEMENT_SHARE, by share id, waiting for her
        # memory of them (_bridge_life_event, _share_excitement): the hint is
        # made of that episode.
        self._excitement_waiting: Dict[str, LifeEvent] = {}
        # The moment's cues still recovering their novelty (Task 18, ruling
        # T18-R6): key -> (penalty 0..1, world instant it was set); saved in
        # life_moment_state by get_moment.
        self._moment_novelty: Dict[str, Tuple[float, datetime]] = {}

        # A new persona starts on her own schedule at the current time (asleep
        # inside her night, else awake since that day's wake time), not on the
        # eight hours awake a bare EnergySystem assumes. A saved state replaces
        # this when start() loads it.
        self._energy.start_on_schedule(self._local_world_now())

        # Initialize database
        self._init_database()
        # What she remembers, as saved -- read now, before anything she does
        # can add to it, so a service that never start()s (a host driving the
        # ticks itself) goes on from the saved stream instead of writing over
        # it. Every other engine loads in start().
        self._memory.load()

        # She is whole now: what a housemate sees of her is published, then
        # she joins (Task 11).
        if self._household is not None:
            self._publish_household_state()
            self._household.join(self._persona_id, self)

    # ============= Init Helpers =============

    @staticmethod
    def _derive_stream(rng, label: str):
        """An independent ``random.Random`` for one engine's draws.

        Seeded from the injected rng's state here plus ``label``, so a
        draw-count change in one engine's stream never moves another
        engine's draws: reading the state takes no draw, so deriving every
        engine's stream up front -- before any engine is constructed, and
        before the service's own direct draws on ``self._service_rng`` happen --
        costs the injected source nothing and does not depend on the order
        the streams are derived in or on how many draws anything else takes
        afterward. Without an injected rng: module ``random``, as before,
        for every label. A source with no ``getstate`` (a test double that
        does not implement it) is returned as-is, so every label shares that
        one object -- the same degraded-but-working behaviour a caller of
        this method got before other labels existed.

        This is the pattern ruling T4-R1 introduced for the sleep stream
        (:meth:`_sleep_stream`) and ruling T5-R1 / Task 26 generalised to
        every engine on the energy-tick path; see the ``rng`` parameter of
        :meth:`__init__` for the full rule and the current label roster.
        """
        if rng is None:
            return random
        getstate = getattr(rng, "getstate", None)
        if not callable(getstate):
            return rng
        return random.Random(f"{getstate()!r}:{label}")

    @staticmethod
    def _sleep_stream(rng):
        """The source each night's sleep window is drawn from -- label
        "sleep" on :meth:`_derive_stream`. Kept as its own method (rather
        than a bare call at the use site) since it predates the general
        helper (ruling T4-R1) and Task 3's pinned nights depend on this exact
        label and derivation continuing unchanged.
        """
        return LifeService._derive_stream(rng, "sleep")

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
                # Her "[kind]" tag (Task 7 carried it to the definition and
                # the database; Task 11 to the NPC): none is the default kind
                # (spec section 4.1). A kind outside NPC_KINDS is kept as
                # written, the way the profile parser keeps it.
                kind=str(d.get("kind") or "").strip().lower() or DEFAULT_NPC_KIND,
            ))
        return npcs

    def _init_media_state(self) -> MediaState:
        """Initialize media state from profile preferences."""
        media = MediaState()
        books = self._media_preferences.get("books", [])
        if books:
            media.current_book = self._service_rng.choice(books)
            media.book_progress = self._service_rng.uniform(0.1, 0.4)
        music = self._media_preferences.get("music", [])
        if music:
            media.current_music_obsession = self._service_rng.choice(music)
        shows = self._media_preferences.get("shows", [])
        if shows:
            media.current_show = self._service_rng.choice(shows)
            media.show_progress = self._service_rng.uniform(0.1, 0.5)
        return media

    # ============= Location Registry =============

    # Legacy name: the locations every persona starts with are her setting's
    # places now (SettingSpec.places); this dict moved, unchanged, into the
    # contemporary setting pack as PLACES in Task 9.
    _DEFAULT_LOCATIONS: Dict[str, str] = _CONTEMPORARY_PLACES

    def _build_location_registry(self) -> None:
        """Build the location registry from multiple sources.

        Sources (in priority order):
        1. Default locations (always present): her setting's places
        2. Persona profile locations (from text profiles)
        3. Occupation-derived locations (her setting's occupation_places)
        4. Interest-derived locations (her setting's interest_places)
        5. User/LLM-added locations (loaded from DB later in _load_state)
        """
        registry = self._location_registry

        # 1. Defaults
        for key, place_type in self._setting.places.items():
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
        for keyword, loc_pairs in self._setting.occupation_places.items():
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
        for keyword, loc_pairs in self._setting.interest_places.items():
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
        # Her day of visits on her local world day (Task 19): it read the host's.
        now = self._local_world_now().replace(tzinfo=None)
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

        # Affect: stress + social + nature. Nature lifts her mood when she
        # arrives, once: on every tick spent there, how far it carried her
        # depended on how often the host ticked.
        self._affect.on_location_effects(
            stress_delta=effects["stress_delta"],
            social_drain=effects["social_drain"],
            is_nature=is_nature and loc != self._last_location,
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

        current = (self._current_location or "").lower().replace(" ", "_")
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
            self._goal_engine.initialize_goals(now=self._world_clock()())
            self._is_initialized = True

        # Back with the people she lives with, if stop() took her away, as
        # she was loaded.
        if self._household is not None:
            self._publish_household_state()
            self._household.join(self._persona_id, self)

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

        For the same reason she leaves her household, if she has one, before
        saving: once a housemate's running activity tick is done
        (``Household.leave``), nothing can pull her into a joint activity, and
        until :meth:`start` the people she lives with see her missing (Task 11).
        She leaves even when stopping the scheduler or a thread fails: a host
        that catches the failure and builds her again must find her place free.
        """
        try:
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
        finally:
            # A stopped life is not read as a live one, nor written into by a
            # housemate after it is saved (Task 11).
            if self._household is not None:
                self._household.leave(self)
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
        doesn't bleed into status, pictures, or proactive messages. The
        scheduled slot is her plan's at her local world time -- or, inside a
        housemate's activity she joined, at when she joined it
        (:meth:`_activity_instant`).
        """
        scheduled = ""
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot(self._activity_instant())
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
        logger.info("Forced wake: user explicitly woke the persona (wake button)")

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
        """(activity_name, is_important) for her next scheduled slot, after
        her local world time's hour (after the joined one inside a housemate's
        activity she joined: :meth:`_activity_instant`)."""
        name = ""
        plan = self._daily_planner.current_plan
        if plan is not None:
            nxt = plan.get_next_slot(self._activity_instant())
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

    def get_moment(self, user_text: Optional[str] = None) -> Moment:
        """Her moment now (humanness Task 18, spec section 4.10): where she
        is, the state that drives her, at most two things on her mind --
        ranked by salience, novelty and relevance to ``user_text`` -- at most
        one unshared thing with its id, how to speak, at most one thing she
        keeps to herself. Deterministic, no LLM. ``render()`` is what the
        host puts in the prompt one or two messages from the end, rebuilt
        every turn (README "Placement contract").

        It saves two things only (ruling T18-R2): the novelty of the cues it
        rendered, and the reinforcement of the memory cues it rendered
        (ruling T12-R2). In memory it also keeps what this conversation has
        had -- moments less than ``CONVERSATION_ACTIVITY_WINDOW_MINUTES``
        apart -- which the next moment passes over unless the user's words
        name it (Task 38); a restart starts a new conversation. It marks
        nothing shared: the host calls :meth:`mark_shared` with
        ``to_share.id`` once she told it. ``get_life_context()`` stays for
        dashboards.

        It reads the world clock for its instant; the wall clock only where
        the accessors it uses do today: ``current_activity_name`` (a
        conversation's activity window) and ``is_asleep`` (a forced wake's
        window)."""
        return build_moment(self, user_text)

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
                "goals": self._goal_engine.export_state(now=self._world_clock()()),
                # Inside a housemate's activity she joined, at when she joined it (Task 19).
                "plan": self._daily_planner.export_state(now=self._activity_instant()),
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
            "memory_time": self._memory_time_export(),
            "continuity": self._continuity.export_state(now=self._world_clock()()),
            "character_evolution": self._character_evolution.export_state(),
            "chaos": self._chaos.export_state(),
            "life_events": self._life_events.export_state(),
            "needs": self.assess_needs(),
            "mental_health": self.mental_health_index(),
        }

    def _memory_time_export(self) -> dict:
        """The memory and time engine's export, its nostalgia memory addressed to her.

        Her setting writes a memory with slots ("a book {subj} read ..."); a host
        that prints the export must never see one (Task 43).
        """
        state = self._memory_time.export_state(now=self._world_clock()())
        nostalgia = state.get("recent_nostalgia")
        if nostalgia and nostalgia.get("memory"):
            state["recent_nostalgia"] = {**nostalgia, "memory": self._addressed_to_her(nostalgia["memory"])}
        return state

    def export_outer_state(self) -> dict:
        """Structured dump of all Outer World engines for digest pass."""
        # Location profile for current location
        loc_key = self._current_location.lower().replace(" ", "_") if self._current_location else "home"
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
            "world": {**self._world_export(), "location_detail": location_export},
            "body": {
                **self._body.export_state(),
            },
            "social": {**self._social.export_state(now=self._world_clock()()), "household": self._household_export()},
            "media": {
                "current_book": self._media.current_book,
                "book_progress": round(self._media.book_progress, 2),
                "current_show": self._media.current_show,
                "current_music": self._media.current_music_obsession,
            },
            "behavior": self._behavior.export_state(self._world_clock()(), exclude=NOT_HABIT_FORMING),
            "expression": self._expression_export(),
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
                "career": self._render_career_status(self._career.export_state(now=self._world_clock()())),
                "errands": self._errands.export_state(),
                "places": self._location.export_state(),
                "transport": self._transport.export_state(self._transit),
            })
        return state

    def on_user_message(self, text: str, detected_emotion: str = "", emotion_intensity: float = 0.0) -> None:
        """
        Called when user sends a message: :meth:`observe_user_turn` with the
        host's detected emotion, if any (ruling T16-R1), its appraisal
        dropped. A host calls one of the two per turn, never both.
        """
        emotions = {detected_emotion: emotion_intensity} if detected_emotion else None
        self.observe_user_turn(text, emotions=emotions)

    def observe_user_turn(self, text: Optional[str] = None, *, sentiment: Optional[float] = None,
                          emotions: Optional[Dict[str, float]] = None, topics=None,
                          disclosure: Optional[float] = None, language: Optional[str] = None) -> dict:
        """The user's turn (spec section 4.8; humanness Task 16a): all a
        message ever did -- the social energy boost, the conversation-session
        state, the multi-engine keyword dispatch, the UserModel's statistics
        -- and her appraisal of it, which she feels and remembers.

        Args:
            text: What the user said (``None``: a turn with no text).
            sentiment: The host's sentiment of the turn, -1..1, when it has
                one: the turn's valence when she feels nothing about it.
            emotions: The user's emotions, name -> intensity 0..1, when the
                host detected them; otherwise the text fallback analyzer
                (``TextEmotionAnalyzer.get_emotional_tone``) reads ``text``.
            topics: What the turn was about: tags of its episode.
            disclosure: How much of themselves the user shared, 0..1: her
                trust rises with it (``IdentitySystem.apply_user_turn``).
            language: The turn's language for the analyzer ("en": English
                only; ``None``: English and French).

        She appraises the user's emotion, never copies it
        (:func:`aura_life.emotion.user_appraisal.appraise_user_turn`):
        concern for a sad user, amusement at a playful one, hurt or
        irritation -- by her volatility -- at hostility aimed at her. She
        feels that (``_feel``, volatility applied); her empathy hears the
        user's strongest emotion with her trust in them
        (``AffectSystem.on_user_emotion_detected``); her trust falls on
        hostility at her and rises on warmth and disclosure; the turn is an
        episode of her memory stream, tagged "conversation", at the world
        instant, which is also kept as :attr:`last_user_turn_at`.

        Returns:
            ``{"valence": float, "persona_emotions": {name: intensity},
            "trust_delta": float}`` -- the valence of what she feels
            (intensity-weighted; else ``sentiment``; else 0.0), her feelings,
            and how much her trust in the user moved over the turn.
        """
        text_value = text if isinstance(text, str) else ""
        if emotions:
            user_emotions = {}
            for name, intensity in emotions.items():
                if name and intensity is not None:
                    user_emotions[str(name)] = max(0.0, min(1.0, float(intensity)))
        elif text_value:
            user_emotions = TextEmotionAnalyzer.get_emotional_tone(text_value, language=language)
        else:
            user_emotions = {}
        dominant = max(user_emotions.items(), key=lambda item: item[1]) if user_emotions else ("", 0.0)
        trust_before = self._identity.get_user_perception().trust_level

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

        # Her appraisal (Task 16a), read here because hostility aimed at her
        # is contact, not a meaningful interaction (ruling T16a-R3): it draws
        # nothing and changes no state; she feels it below.
        appraisal = appraise_user_turn(
            user_emotions,
            aimed_at_her=text is None or addresses_listener(text_value, language=language),
            parameters=self._params,
        )

        # Affect: a social interaction, at the world's instant (her
        # loneliness counts from it on the world clock -- Task 11 fix round);
        # meaningful unless the turn was hostility at her
        self._affect.on_social_interaction(meaningful=appraisal.hostility <= 0.0, now=self._world_clock()())

        # Social boost from interaction
        self._energy.add_social_boost()

        # Multi-engine conversation trigger dispatch: each keyword on word
        # boundaries and not negated, through the analyzer's tokenizer
        # (ruling T16-R4; matched_cues keeps the map's order)
        triggered = set()  # Dedup (engine, trigger_type) pairs

        engine_dispatch = {
            "desire": self._desire_system,
            "affect": self._affect,
            "energy": self._energy,
            "cognitive": self._cognitive,
            "identity": self._identity,
            "drive": self._drive,
        }

        for keyword in matched_cues(text_value, CONVERSATION_KEYWORD_MAP):
            for engine_name, trigger_type in CONVERSATION_KEYWORD_MAP[keyword]:
                pair = (engine_name, trigger_type)
                if pair not in triggered:
                    triggered.add(pair)
                    engine = engine_dispatch.get(engine_name)
                    if engine:
                        engine.process_conversation_trigger(trigger_type)

        # Cognitive + MemoryTime: conversation engagement
        self._cognitive.on_user_message(text_value)
        self._shadow.on_user_message(text_value)
        self._memory_time.on_user_message(text_value)

        # UserModel: observe message for behavioral learning
        if self._user_model_provider is not None:
            try:
                um = self._user_model_provider(self._persona_id)
                um.observe_message(text_value, datetime.now(), dominant[0], dominant[1])
            except Exception as exc:
                self._report_user_model_failure("observe_message", exc)

        # Her appraisal (Task 16a): what she feels about the turn, her
        # empathy, her trust, and the episode.
        self._feel(appraisal.emotions, reactivity_applied=True)
        if dominant[0]:
            self._affect.on_user_emotion_detected(
                dominant[0], dominant[1], trust_level=self._identity.get_user_perception().trust_level)
        disclosure_value = max(0.0, min(1.0, float(disclosure))) if disclosure is not None else 0.0
        self._identity.apply_user_turn(
            hostility=appraisal.hostility, warmth=appraisal.warmth, disclosure=disclosure_value,
        )
        trust_delta = self._identity.get_user_perception().trust_level - trust_before
        valence = appraisal_valence(appraisal.emotions)
        if valence is None:
            valence = max(-1.0, min(1.0, float(sentiment))) if sentiment is not None else 0.0
        at = self._world_clock()()
        # Relationship depth (Task 16b): the silence before this turn, a new
        # contact day, the user's disclosure answering one of hers
        self._expression.note_user_turn(at, self._identity.last_user_turn_at, disclosure_value)
        self._identity.note_user_turn(at)
        felt_most = max(appraisal.emotions.items(), key=lambda item: item[1]) if appraisal.emotions else None
        # a host's one topic given as a string is that topic, not its letters
        topic_list = [str(t) for t in ((topics,) if isinstance(topics, str) else (topics or ())) if t]
        # The episode is a gist of what the turn was to her, never the user's
        # words, and only for a turn that left a trace (ruling T16a-R2).
        kind = _conversation_kind(appraisal, disclosure_value, felt_most, topic_list)
        if kind is not None:
            self._remember(
                conversation_phrase(kind, topic_list, render=self._addressed_to_her),
                emotion=felt_most[0] if felt_most else None,
                intensity=felt_most[1] if felt_most else None,
                valence=valence,
                tags=("conversation", *topic_list),
            )
        return {
            "valence": float(valence),
            "persona_emotions": dict(appraisal.emotions),
            "trust_delta": float(trust_delta),
        }

    @property
    def last_user_turn_at(self) -> Optional[datetime]:
        """The world instant of the user's last turn (ruling T16-R2): set by
        :meth:`observe_user_turn` (and so by :meth:`on_user_message`) from the
        world clock, saved and loaded with her state; ``None`` before any
        turn, and for a save from before Task 16a."""
        return self._identity.last_user_turn_at

    @property
    def relationship_depth(self) -> float:
        """How deep her bond with the user is now, 0..1 (humanness Task 16b,
        :mod:`aura_life.expression.relationship`): from disclosure
        reciprocity and contact days, regressing after a week without a user
        turn. It sets ``expression.relationship_stage`` and the style hint's
        distance line."""
        return self._expression.depth_at(self._world_clock()(), self.last_user_turn_at)

    @property
    def after_absence(self) -> Optional[AfterAbsence]:
        """Her ``after_absence`` state now (humanness Task 16b, ruling
        T16-R7: computed here, rendered by the moment with her
        ``state_expressions``), or ``None``: the user has been away
        ``ABSENCE_AFTER_HOURS`` or more (``ongoing``), or the present
        conversation ended such an absence (turns less than
        ``IN_CONVERSATION_MINUTES`` apart; ``ongoing`` False). Its intensity
        and feelings follow her ``attachment_style``
        (:func:`aura_life.expression.relationship.after_absence`)."""
        last = self.last_user_turn_at
        if last is None:
            return None
        style = getattr(self._definition, "attachment_style", "") if self._definition else ""
        silent_hours = silent_days(self._world_clock()(), last) * 24.0
        if silent_hours >= ABSENCE_AFTER_HOURS:
            return absence_state(silent_hours, style, ongoing=True)
        reunion = self._expression.reunion_hours
        if reunion is not None and silent_hours * 60.0 < IN_CONVERSATION_MINUTES:
            return absence_state(reunion, style, ongoing=False)
        return None

    def _expression_export(self) -> dict:
        """``export_outer_state()["expression"]``: the expression engine's
        keys (``style_hint``, ``relationship_stage``, ...), plus her
        relationship ``depth`` now and her ``after_absence`` state (a dict, or
        ``None``; ruling T16-R7) -- Task 16b's new keys."""
        absence = self.after_absence
        return {
            **self._expression.export_state(),
            "depth": round(self.relationship_depth, 3),
            "after_absence": absence.as_dict() if absence is not None else None,
        }

    def _communication_traits(self) -> List[str]:
        """The persona's own register lines (``definition.communication_traits``)."""
        return list(getattr(self._definition, "communication_traits", None) or []) if self._definition else []

    def on_theater_conversation(self, other_name: str, tone: str = "neutral") -> None:
        """Apply residue from a persona-to-persona (theater) conversation.

        Routed by the theater router after a conversation ends. A meaningful
        social interaction nudges affect; tense conversations don't count as
        a positive social touch.
        """
        try:
            self._affect.on_social_interaction(meaningful=(tone != "tense"), now=self._world_clock()())
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
                self._her_disclosure()
                break
        self._save_shareable()

    def mark_shared(self, share_id: str) -> bool:
        """Mark a life event or shareable experience as shared, by the
        stable id ``get_unshared_events()`` / ``get_shareable_experiences()``
        items carry on ``.share_id`` (``"event:<n>"``, ``"share:<n>"`` -- spec
        Sec 4.9). Persists the change and excludes the item from both
        unshared getters from then on.

        An item one episode of her memory stream tells together with
        another (a shareable and its life event: a chaos event, a finished
        book, a skill milestone -- :func:`_share_ids`) is one piece of news:
        marking either id marks the ids told with it, with one disclosure
        (Task 18 fix round 1, C3: the moment offers one id of the pair).

        Returns whether a match was found. False for an id that doesn't
        parse to a known prefix, or doesn't match anything currently held
        (already evicted, wrong kind, or never existed) -- it never raises.
        """
        if not isinstance(share_id, str) or not self._mark_one_shared(share_id):
            return False
        told_with = {other for episode in self._memory.episodes
                     if share_id in _share_ids_of(episode) for other in _share_ids_of(episode)}
        # Her memory tells some things in the very same words (two evenings
        # of the same activity): a twin of what she just told is the same
        # news, and is told with it (Task 38: it was offered at the very
        # next turn).
        words = {_told(episode) for episode in self._memory.episodes if share_id in _share_ids_of(episode)}
        told_with |= {other for episode in self._memory.episodes
                      if _told(episode) in words for other in _share_ids_of(episode)}
        for other in sorted(told_with - {share_id}):
            self._mark_one_shared(other)
        self._her_disclosure()
        return True

    def _mark_one_shared(self, share_id: str) -> bool:
        """Mark one life event or shareable experience shared by its id,
        saved at once (:meth:`mark_shared`, which adds the disclosure)."""
        if share_id.startswith("event:"):
            if self._life_events.mark_shared(share_id, now=self._world_clock()()):
                self._save_life_events()
                return True
            return False
        if share_id.startswith("share:"):
            for exp in self._shareable_queue:
                if exp.share_id == share_id:
                    exp.shared = True
                    exp.shared_at = self._world_clock()()
                    self._save_shareable()
                    return True
            return False
        return False

    def _her_disclosure(self) -> None:
        """She told the user something of her own life: her side of the
        disclosure reciprocity that deepens the bond (Task 16b,
        ``ExpressionSystem.note_her_disclosure``), saved at once as the
        share itself is."""
        self._expression.note_her_disclosure(self._world_clock()(), self.last_user_turn_at)
        self._save_expression()

    def recall(self, query: Optional[str] = None, k: int = 3, reinforce: bool = True) -> List[Episode]:
        """What she remembers now (spec section 4.6): the ``k`` episodes of
        her memory stream that come to mind -- for ``query`` (what was said,
        a topic, a name) or, with none, unprompted -- best first, by recency,
        importance, relevance and how well each fits her mood now. Unprompted
        recall weighs each by how much of it she still holds, its retention
        (:mod:`aura_life.memory`; ruling T12-R1); a cued recall -- a ``query``
        -- does not, so a good cue brings back a faded memory (ruling
        T12-R5). Recalling is remembering
        again: each one returned is strengthened -- its strength gains 1 and
        its recency and retention start again -- and saved at once.
        ``reinforce=False`` reads the same episodes without that, for a host
        that shows her memories rather than has her remember them (ruling
        T12-R2). Each is an :class:`~aura_life.memory.Episode`, whose
        ``gist()`` is one plain sentence to quote to her."""
        now, mood = self._world_clock()(), self._affect.mood.valence
        if not reinforce:
            return self._memory.retrieve(now=now, query=query, k=k, mood_valence=mood)
        return self._memory.recall(now=now, query=query, k=k, mood_valence=mood)

    def _remember(self, what: str, *, place: Optional[str] = None, people=(), emotions=None,
                  emotion: Optional[str] = None, intensity: Optional[float] = None,
                  valence: Optional[float] = None, tags=(), activity: Optional[str] = None) -> Optional[Episode]:
        """An event of her life into her memory stream, at the world instant
        (:meth:`MemoryStream.record`, which weighs its importance): where she
        is unless ``place`` says otherwise ("" is nowhere in particular), the
        valence of her mood now unless an appraisal gives one -- Task 14's
        outcome appraisal and Task 16's user turns pass their own
        ``emotion``, ``intensity`` and ``valence``. Returns the episode, or
        ``None`` when it could not be recorded: that is logged at WARNING and
        never takes the tick that lived it down."""
        memory = getattr(self, "_memory", None)
        if memory is None:
            return None
        try:
            episode = memory.record(
                at=self._world_clock()(),
                what=what,
                place=self._current_location if place is None else place,
                people=people,
                emotions=emotions,
                emotion=emotion,
                intensity=intensity,
                valence=self._affect.mood.valence if valence is None else valence,
                tags=tags,
                activity=activity,
            )
        except Exception:
            logger.warning("Could not remember %r in the persona's memory stream", what, exc_info=True)
            return None
        self._share_excitement(episode)
        return episode

    # ============= Proactive hints: their concrete detail (Task 17) =======

    def _when_said(self, then: datetime) -> str:
        """When ``then`` -- a world instant -- was, in words on her local
        calendar (ruling T17-R4: no number): "earlier today", "yesterday",
        "three days ago"."""
        now = self._world_clock()()
        local_now = self._local_world_now()
        days = (local_now.date() - (local_now - (now - then)).date()).days
        if days <= 0:
            return "earlier today"
        if days == 1:
            return "yesterday"
        return f"{_number_words(days)} days ago"

    def _on_her_mind(self) -> Optional[Episode]:
        """The episode most on her mind now -- what a mood shift or an unmet
        need is about (ruling T17-R2) -- read without reinforcing it
        (``recall(reinforce=False)``, ruling T12-R2), at :meth:`recall`'s
        default ``k``; a belief is a realization, not a lived moment. ``None``
        with nothing in her memory."""
        try:
            episodes = self.recall(reinforce=False)
        except Exception:
            logger.warning("Life trigger: the memory stream could not be read", exc_info=True)
            return None
        return next((e for e in episodes if "belief" not in e.tags), None)

    def _on_her_mind_line(self, episode: Episode) -> str:
        """"On your mind, from yesterday: cooking a meal at home with Roberta,
        feeling warm." -- an episode as a hint's detail."""
        return f"On your mind, from {self._when_said(episode.at)}: {_told(episode)}"

    def _last_talked(self) -> str:
        """"The last time you talked with Robin was yesterday" -- when the
        user's last turn was (:attr:`last_user_turn_at`, ruling T17-R2: the
        detail of a need of contact), the user named as :meth:`_user_ref`
        names them; "" before any turn."""
        last = self.last_user_turn_at
        if last is None:
            return ""
        return f"The last time you talked with {self._user_ref()} was {self._when_said(last)}"

    def _contact_detail(self) -> str:
        """The detail of a need of contact (loneliness, connection): when they
        last spoke, else what is on her mind; "" with neither."""
        last = self._last_talked()
        if last:
            return f"{last}."
        moved = self._on_her_mind()
        return self._on_her_mind_line(moved) if moved is not None else ""

    def _newest_episode(self, *tags: str, person: Optional[str] = None) -> Optional[Episode]:
        """Her newest episode carrying every one of ``tags`` (and ``person``
        among its people, when given), or ``None``."""
        memory = getattr(self, "_memory", None)
        if memory is None:
            return None
        for episode in reversed(memory.episodes):
            if all(tag in episode.tags for tag in tags) and (person is None or person in episode.people):
                return episode
        return None

    def _still_unshared(self, episode: Episode) -> bool:
        """Whether something an episode is tied to (its share ids) is still
        hers to share: true for one tied to nothing."""
        ids = _share_ids_of(episode)
        if not ids:
            return True
        unshared = {e.share_id for e in self._get_unshared_experiences()}
        unshared.update(e.share_id for e in self._life_events.get_unshared_events())
        return any(share_id in unshared for share_id in ids)

    def _share_excitement(self, episode: Optional[Episode]) -> None:
        """The EXCITEMENT_SHARE of a life event waiting for her memory of it
        (:meth:`_bridge_life_event`), now that ``episode`` is that memory --
        its tags carry the event's share id: the hint is made of the episode
        (what, where, who, feeling, when), and the share id goes to a host
        that takes one (ruling T17-R1)."""
        waiting = getattr(self, "_excitement_waiting", None)
        if not waiting or episode is None:
            return
        for share_id in _share_ids_of(episode):
            event = waiting.pop(share_id, None)
            if event is None or self._follow_up_provider is None:
                continue
            if not self._life_trigger_cooled_down("excitement_share", datetime.now()):
                continue
            try:
                fm = self._follow_up_provider(self._persona_id)
                _create_follow_up(
                    fm,
                    share_id=event.share_id,
                    trigger_type="EXCITEMENT_SHARE",
                    topic=event.title,
                    context=event.description,
                    urgency=min(event.share_urgency, 0.85),
                    emotional_weight=max(event.emotional_impact.values()) if event.emotional_impact else 0.5,
                    prompt_hint=(
                        f"Something happened {self._when_said(episode.at)} that you're excited about: "
                        f"{_told(episode)} Share the concrete detail — what actually happened — not a "
                        f"vague 'I had an epiphany' or 'I cracked the code'."
                    ),
                )
                self._record_life_trigger_cooldown("excitement_share", datetime.now())
            except Exception:
                # Matches the sibling trigger handlers: without this the trigger
                # can be permanently dead in production with zero signal.
                logger.warning("Life trigger: EXCITEMENT_SHARE dispatch failed", exc_info=True)

    def _addressed_to_her(self, text: str) -> str:
        """A line of her setting's as her memory keeps it: addressed to her,
        in the second person ("{Subj} spilled coffee" -> "You spilled
        coffee"), the user named as her user or "them" -- the form her
        episodes are quoted back to her in."""
        return _render_second_person(text, user=self._user_info)

    # ============= Reflection & nostalgia from real history (Task 13) =====

    def _real_nostalgia_episode(self, now: datetime) -> Optional[Episode]:
        """A real memory old enough to be nostalgic (the Task 13 brief,
        verbatim: at least NOSTALGIA_MIN_EPISODE_AGE_DAYS simulated days),
        picked at random among every eligible one (``self._service_rng``:
        "the service's own direct draws", not delegated to
        ``MemoryTimeSystem`` -- picking WHICH memory surfaces is hers to
        make, since she owns the memory stream) -- or ``None`` when she has
        none yet, so the setting's ten templates
        (``aura_life.settings.contemporary.NOSTALGIA_MEMORIES``) stay the
        fallback. A belief is never picked: it is a realization about her
        life, not a lived moment to feel nostalgic for."""
        memory = getattr(self, "_memory", None)
        if memory is None:
            return None
        cutoff = timedelta(days=NOSTALGIA_MIN_EPISODE_AGE_DAYS)
        old_enough = [e for e in memory.episodes if "belief" not in e.tags and (now - e.at) >= cutoff]
        return self._service_rng.choice(old_enough) if old_enough else None

    def _get_reflection_llm(self):
        """The LLM client for optional reflection enrichment (``reflection_llm=True``
        at construction), or ``None`` when the host registered no
        ``get_llm_service`` hook or asking for it raised -- degrades to the
        deterministic beliefs, no ERROR (mirrors :meth:`_get_trip_llm`)."""
        try:
            from aura_life.hooks import get_llm_service
            return get_llm_service()
        except Exception:
            return None

    def _reflect_with_llm(self, window: List[Episode]) -> None:
        """One more belief an LLM adds on top of the deterministic ones,
        from the same reflection window -- only reached when this service
        was built with ``reflection_llm=True`` (:meth:`_reflect`). Safe-fail
        like :meth:`_pick_trip_destination`: no client, any exception, or a
        reply that fails :func:`~aura_life.memory.reflection.validate_llm_belief`
        (fix round 1, Important 2: a length cap, no digit, no unfilled
        brace, no bare third-person pronoun, never "the user", one sentence)
        leaves the deterministic beliefs exactly as they are -- a failed
        exception logged no louder than DEBUG, a failed validation no
        louder than WARNING (the reply came from a configured, reachable
        model; that it answered something unusable is worth knowing, not
        alarming). Its valence is the reflection window's mean, the same as
        every deterministic belief (fix round 1, Minor 5) -- not her mood
        right now, at the moment this happens to run."""
        llm = self._get_reflection_llm()
        if llm is None:
            return
        gists = "\n".join(f"- {e.gist()}" for e in window[-20:])
        prompt = (
            "Here is a short window of a person's own recent memories, most important "
            "first is not guaranteed -- just what happened, in order:\n"
            f"{gists}\n"
            "In one short sentence, addressed to them as \"you\", say one thing this "
            "adds up to that they might realize about themselves. Reply with ONLY that "
            "sentence, no quotation marks, no commentary."
        )
        try:
            raw = llm.generate(prompt)
        except Exception:
            logger.debug("LLM reflection failed; the deterministic beliefs stand", exc_info=True)
            return
        text = validate_llm_belief(raw)
        if text is None:
            logger.warning("LLM reflection's reply (%d chars) failed validation; "
                           "the deterministic beliefs stand", len(str(raw or "")))
            return
        self._remember(text, place="", tags=("belief", "llm"), intensity=BELIEF_INTENSITY,
                       valence=mean_valence(window))

    def _recent_belief_keys(self, now: datetime) -> set:
        """Every belief pattern key (``aura_life.memory.reflection.BeliefKey``)
        already believed within BELIEF_REPEAT_COOLDOWN_DAYS simulated days
        of ``now`` (fix round 1, Important 1) -- read from the belief
        episodes' own tags (:func:`~aura_life.memory.reflection.belief_key_from_tag`),
        not a side table: the stream is already the record of what she has
        concluded and when."""
        memory = getattr(self, "_memory", None)
        if memory is None:
            return set()
        cutoff = now - timedelta(days=BELIEF_REPEAT_COOLDOWN_DAYS)
        keys = set()
        for episode in memory.episodes:
            if "belief" not in episode.tags or episode.at < cutoff:
                continue
            for tag in episode.tags:
                key = belief_key_from_tag(tag)
                if key is not None:
                    keys.add(key)
        return keys

    def _reflect(self, now: datetime) -> None:
        """Whether the importance she has lived since her last reflection
        reaches REFLECTION_THRESHOLD (spec 4.6) and, when it does, what she
        concludes from it: deterministic beliefs from the window's episode
        counts and trends (``aura_life.memory.reflection.generate_beliefs``)
        -- a repeated activity with a person, a recurring place, a mood
        trend -- each remembered as an episode of her own (``tags=("belief",)``,
        plus its pattern key, :func:`~aura_life.memory.reflection.belief_key_tag`)
        and its grounding episodes reinforced (ruling T12-R2: reflection
        that surfaces an episode reinforces it); then, only when this
        service was built with ``reflection_llm=True``, one more belief an
        LLM adds from the same window.

        A pattern already believed within BELIEF_REPEAT_COOLDOWN_DAYS is
        skipped (fix round 1, Important 1: a belief's TEXT can reword the
        same conclusion forever -- "You've been at the cafe most days this
        week." every time she is, in fact, mostly at the cafe). A
        reflection that finds nothing new this way records nothing.

        The window is every non-belief episode more recent than
        ``self._last_reflection_at`` (or, with none yet, every one she
        has). That instant is set the moment the threshold is crossed --
        whether or not any belief survives the dedup above -- and saved at
        once (fix round 1, Minor 4): it used to be derived from the most
        recent belief episode's own timestamp, which MemoryStream's cap
        could prune, letting a later reflection re-count episodes already
        reflected on."""
        memory = getattr(self, "_memory", None)
        if memory is None:
            return
        episodes = memory.episodes
        window = [e for e in episodes if "belief" not in e.tags
                  and (self._last_reflection_at is None or e.at > self._last_reflection_at)]
        if sum(e.importance for e in window) < REFLECTION_THRESHOLD:
            return
        self._last_reflection_at = now
        self._save_reflection_state()
        recent_keys = self._recent_belief_keys(now)
        for key, text, grounds in generate_beliefs(window, mood_band=MOOD_VALENCE_BAND):
            if key in recent_keys:
                continue
            people = tuple(dict.fromkeys(person for episode in grounds for person in episode.people))
            valence = mean_valence(grounds) if grounds else mean_valence(window)
            belief = self._remember(text, place="", people=people, intensity=BELIEF_INTENSITY,
                                    valence=valence, tags=("belief", belief_key_tag(key)))
            if belief is not None:
                recent_keys.add(key)
                if grounds:
                    memory.reinforce(grounds, now=now)
        if self._reflection_llm:
            self._reflect_with_llm(window)

    def _chapter_window_stats(self, period_start: datetime, now: datetime) -> Tuple[str, Dict[str, int]]:
        """What a life chapter synthesised at ``now`` summarises (Task 13,
        spec 4.6): the dominant activities and the mood of the WHOLE period
        since ``period_start``, read from her memory stream (Task 12) --
        never ``_behavior._activity_history`` (its last 50 only, a day or
        so at production cadence, not a month) or her mood at this one
        instant (spec 4.6: "not the mood at the moment of writing").

        Her mean valence over the window (0.0, neutral, with no episode in
        it) and her arousal right now (the library keeps no arousal
        history to average -- valence is the axis spec 4.6 names) give
        ``mood_label`` (``aura_life.affect.affect_system``, the same
        function ``AffectSystem`` itself uses) its point on the mood grid;
        the label is ``ContinuitySystem.monthly_tick``'s ``dominant_mood``
        argument, unchanged since Task 12."""
        memory = getattr(self, "_memory", None)
        window = [e for e in memory.episodes if period_start <= e.at <= now] if memory else []
        activity_counts: Dict[str, int] = {}
        for episode in window:
            if "activity" in episode.tags:
                activity_counts[episode.what] = activity_counts.get(episode.what, 0) + 1
        arousal = self._affect.mood.arousal if self._affect else 0.0
        return mood_label(mean_valence(window), arousal), activity_counts

    def apply_schedule_override(self, action: str) -> None:
        """
        Apply a schedule override from conversation (e.g. user said 'skip work').

        Parses the action string and delegates to the appropriate planner method.
        Which slots are still ahead, and which is hers now, is judged at her
        local world time (:func:`_plan_instant`); a duck-typed service without
        one passes no instant, which is the host's wall clock.
        """
        action_lower = action.strip().lower()

        if any(w in action_lower for w in ["cancel work", "call off", "skip work", "no work", "day off"]):
            self._daily_planner.cancel_work_today(now=_plan_instant(self))

        elif action_lower.startswith("go to ") or action_lower.startswith("move to "):
            location = action_lower.split("to ", 1)[1].strip()
            # Auto-register unknown locations from user
            slug = location.lower().replace(" ", "_")
            if slug not in self._location_registry:
                self._register_user_location(location)
            _move_persona_to(self, location)
            self._daily_planner.override_current_location(location, now=_plan_instant(self))

        elif any(w in action_lower for w in ["stay home", "stay here", "stay in"]):
            self._daily_planner.stay_at_current_location(now=_plan_instant(self))

        else:
            # Generic location move: try to extract a location name
            for key in self._persona_locations:
                if key.lower() in action_lower:
                    _move_persona_to(self, key.lower())
                    self._daily_planner.override_current_location(key.lower(), now=_plan_instant(self))
                    break

        # Persist the updated plan
        self._save_plan()
        logger.info(f"Applied schedule override: {action}")

    def schedule_meeting_arrival(self, location: str) -> None:
        """Update activity, schedule and world location when the persona arrives for a planned meeting."""
        _move_persona_to(self, location)
        self._daily_planner.schedule_rendezvous(location, now=_plan_instant(self))
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

        "Already passed" is judged at her local world time (:func:`_plan_instant`).
        The method only needs ``_daily_planner``, ``_location_registry``,
        ``_register_user_location`` and ``_save_plan``, and a host may bind it
        to a duck-typed stand-in with just those: with no ``_local_world_now``
        it passes no instant, which is the host's wall clock.
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
            reason=USER_AGREED_REASON,
            now=_plan_instant(self),  # "already passed" is her hour, not the host's
        )
        self._save_plan()
        logger.info(f"Conversation plan added: {hour:02d}:{minute:02d} -> hour {hour:02d} — {what}" + (f" @ {location}" if location else ""))

    # ============= Social circle and plans =============

    def get_social_circle(self) -> List[Dict]:
        """Everyone in her circle, closest first.

        Plain dicts ``{name, relationship, closeness, trend}``; ``closeness`` and
        ``trend`` come from the relationship arc and are ``None`` when the person
        has none.
        """
        return self._social.circle()

    def add_social_plan(self, people: List[str], what: str, at: datetime, duration_min: int) -> None:
        """Commit her to ``what`` with ``people`` at ``at``.

        Records a social obligation (it persists and reads back through
        :meth:`get_upcoming_social_plans`) and puts the matching slot(s) into
        today's daily plan through the same path the ``[PLAN: ...]`` tag uses, so
        the activity engine has her out at that time. The planner's granularity is
        hourly: the plan fills each hour it touches. A plan for another day is
        recorded and gets its slot when that day's plan is generated.

        ``at`` is a naive datetime on the world clock; a persona with a timezone
        gets the plan at her local hour of that instant. Names match the circle
        case-insensitively. Raises ``ValueError`` for an unknown or empty list of
        people, a blank ``what``, a non-positive duration, a timezone-aware ``at``
        or a start in a past hour of the world's day.
        """
        circle = {n.lower(): n for n in self._social._npcs}
        names: List[str] = []
        for raw in people or []:
            canonical = circle.get(str(raw).strip().lower())
            if canonical is None:
                raise ValueError(f"unknown person {raw!r}: " + self._render_text("not in {poss} social circle"))
            if canonical not in names:
                names.append(canonical)
        if not names:
            raise ValueError("a social plan needs at least one person")
        what = (what or "").strip()
        if not what:
            raise ValueError("a social plan needs something to do")
        if duration_min is None or int(duration_min) <= 0:
            raise ValueError("duration_min must be positive")
        if at.tzinfo is not None:
            raise ValueError("at must be a naive datetime on the world clock")
        now = self._world_clock()()
        if at < now.replace(minute=0, second=0, microsecond=0):
            raise ValueError(f"{at.isoformat()} is already past on the world clock")
        duration_min = int(duration_min)
        end = at + timedelta(minutes=duration_min)
        for o in self._social.obligations:
            if not (o.duration_min and o.deadline):
                continue
            if o.description == what and o.deadline == at and o.people == names:
                continue  # the same plan again: add_plan keeps it once
            if at < o.deadline + timedelta(minutes=o.duration_min) and o.deadline < end:
                raise ValueError(f"{at.isoformat()} overlaps the plan {o.description!r} at {o.deadline.isoformat()}")

        self._social.add_plan(names, what, at, duration_min, now=self._world_clock()())
        self._apply_social_plans()
        self._save_social_expansion()
        logger.info(f"Social plan added: {at.isoformat()} {what} with {', '.join(names)} ({duration_min} min)")

    def _apply_social_plans(self) -> None:
        """Put every hour of every social plan that falls on the current daily plan's date into it.

        The day is the daily plan's own ``date``: her local world day (every plan route
        gives the planner her local world time, ``_plan_instant``; never the host's
        clock), and each plan's instant (on the world clock) is read as her local
        world time (:meth:`_local_world_instant`: her own hour of it for a persona
        with a timezone), so a plan for tomorrow lands when tomorrow's
        plan is generated and a plan that crosses midnight puts its after-midnight
        hours in the next day's plan. A slot already carrying the plan is left alone
        (re-applying would reopen a finished one); "already passed" is judged at her
        local world time, as on every other plan route. A no-op while no plan exists.
        """
        plan = self._daily_planner.current_plan
        if plan is None:
            return
        now = _plan_instant(self)
        changed = False
        for o in self._social.obligations:
            if not (o.duration_min and o.deadline):
                continue
            reason = SOCIAL_PLAN_REASON_PREFIX + ", ".join(o.people)
            start = self._local_world_instant(o.deadline)
            end = start + timedelta(minutes=o.duration_min)
            hour_start = start.replace(minute=0, second=0, microsecond=0)
            while hour_start < end:
                if hour_start.strftime("%Y-%m-%d") == plan.date:
                    slot = plan.get_slot_for_hour(hour_start.hour)
                    if not (slot and slot.activity_name == o.description and slot.reason == reason):
                        self._daily_planner.set_planned_activity(
                            hour=hour_start.hour, activity_name=o.description, location="",
                            reason=reason, now=now,
                        )
                        changed = True
                hour_start += timedelta(hours=1)
        if changed:
            self._save_plan()

    def get_upcoming_social_plans(self, within_hours: float) -> List[Dict]:
        """Plans running now or starting within ``within_hours``, soonest first.

        Each is ``{people, what, at, duration_min}``; ``at`` is a datetime on the
        world clock.
        """
        return self._social.upcoming_plans(self._world_clock()(), within_hours)

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
        origin = self._current_location or "home"

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
            _move_persona_to(self, "in transit")
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
            _move_persona_to(self, "in transit")
            logger.info(f"Transit phase → IN_TRANSIT: heading to {self._transit.destination}")

        elif to_phase == TransitPhase.ARRIVED:
            self._transit.phase = TransitPhase.ARRIVED
            self._transit.arrived_at = now
            _move_persona_to(self, self._transit.destination)
            self._daily_planner.schedule_rendezvous(self._transit.destination, now=_plan_instant(self))
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
                _move_persona_to(self, self._transit.destination)
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
                # On the world clock, as _update_trip stamps it (Task 19).
                needs_revert = self._world_clock()() >= datetime.fromisoformat(pl.trip_returns_at)
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

        rng = _rng if _rng is not None else self._service_rng
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

        Syncs world location to the current plan slot (at her local world
        time) so the persona returns to what she was supposed to be doing
        (commuting, attending classes, etc.) -- unless she is on the way
        somewhere or inside a housemate's activity she joined
        (:meth:`_location_held`): that is what she was doing. Also
        immediately re-evaluates the visual transition so descriptions update.
        """
        plan = self._daily_planner.current_plan
        if not plan:
            return

        slot = plan.get_current_slot(self._local_world_now())
        if not slot or slot.completed:
            return

        planned_location = slot.location or "home"
        if self._current_location != planned_location and not self._location_held():
            _move_persona_to(self, planned_location)
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

        The planner slot's location is authoritative: her slot at her local
        world time (:meth:`_local_world_now`; Task 28 -- it read the host's
        hour). This persona's own current location (:attr:`_current_location`)
        is kept in sync as a side effect -- never the (possibly shared)
        world's directly, see :func:`_move_persona_to`. Falls back to 'home'
        only when no plan exists yet.

        Never while her place is held (:meth:`_location_held`: on the way
        somewhere, or inside a housemate's activity she joined): she is where
        she is, and that is the answer -- a read of her status or her looks
        must not move her (Task 28 fix round 1).
        """
        if self._location_held():
            return (self._current_location or "home").replace("_", " ")
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot(self._local_world_now())
            if slot and slot.location:
                # Keep this persona's own location in sync with the planner
                if self._current_location != slot.location:
                    _move_persona_to(self, slot.location)
                return slot.location.replace("_", " ")
        return "home"

    def _location_now(self) -> str:
        """Where she is, as :meth:`get_current_location` answers it, without
        its sync: she is not moved to her slot's place. What a read that
        must change nothing uses -- the moment (``context.moment``, ruling
        T18-R2; Task 18 fix round 1, C1)."""
        if self._location_held():
            return (self._current_location or "home").replace("_", " ")
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot(self._local_world_now())
            if slot and slot.location:
                return slot.location.replace("_", " ")
        return "home"

    def _location_held(self) -> bool:
        """Is she somewhere her plan's place for the hour must not move her
        from? While a transit is getting ready or under way (the phases
        ``_perform_activity`` leaves the location to the transit in), and
        while a housemate's activity she joined is hers (``_joint_until``,
        on the world clock: :meth:`_join_housemate`)."""
        transit = getattr(self, "_transit", None)
        if transit is not None and transit.phase in (TransitPhase.PREPARING, TransitPhase.IN_TRANSIT):
            return True
        return self._joint_held()

    def _joint_held(self) -> bool:
        """Is a housemate's activity she joined still hers (``_joint_until``,
        on the world clock: :meth:`_join_housemate`)? The joint half of
        :meth:`_location_held`."""
        joint_until = getattr(self, "_joint_until", None)
        return joint_until is not None and self._world_clock()() < joint_until

    def _activity_instant(self) -> datetime:
        """The instant her plan is read at for what she is doing: her local
        world time (:meth:`_local_world_now`) -- but while a housemate's
        activity she joined holds her where it is (:meth:`_joint_held`, the
        rule :meth:`_location_held` follows), the local instant she joined it,
        so her current activity, the "Right now" line, her next activity and
        the plan a digest pass reads all say the joint activity, where she is,
        through the window's tail into the next hour; after it, her plan's
        hour again (humanness Task 19, ruling T19-R5)."""
        joint_at = getattr(self, "_joint_at", None)
        if joint_at is not None and self._joint_held():
            return joint_at
        return self._local_world_now()

    @staticmethod
    def _weather_mood_enabled() -> bool:
        """Gate check for weather → mood nudge. Read at call time so
        tests can monkeypatch os.environ without reloading the module."""
        import os as _os
        return _os.environ.get("AURA_WEATHER_MOOD_ENABLED", "true").lower() in ("true", "1", "yes")

    @staticmethod
    def _mood_to_valence(label: str, intensity: float, valence: Optional[float] = None) -> float:
        """Map mood to a 0..1 valence (1 = good, 0 = bad).

        Single source of truth shared by the Shadow tick and the mental-health
        read-out so the two never drift apart. Both pass ``valence``, the
        mood's own -1..1 valence (``AffectSystem.mood.valence``), which this
        rescales. Without it -- the form a host may still call -- it maps the
        retired one-axis labels as it always did, and any other label reads 0.5.
        """
        if valence is not None:
            return 0.5 + 0.5 * max(-1.0, min(1.0, valence))
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
                self._affect.mood.current_mood, self._affect.mood.intensity,
                valence=self._affect.mood.valence,
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
            # Inside a housemate's activity she joined, at when she joined it
            # (_activity_instant, Task 19): the slot of where she is held.
            slot = self._daily_planner.current_plan.get_current_slot(self._activity_instant())
            if slot:
                _scheduled_act = slot.activity_name
        _effective_act = self.effective_current_activity(_scheduled_act)
        if _effective_act:
            # The activity id itself ("thinking about user") stays the stable
            # internal key -- related_activities lists and SKILL_MAPPINGS-style
            # lookups match on it elsewhere. Only the human-facing status-bar
            # string swaps "user" for the real name/them, so the id is never
            # renamed out from under those comparisons.
            _display_act = self._activity_for_display(_effective_act)
            # str.capitalize() lowercases every OTHER character too, which
            # mangles a real name substituted in above ("Thinking about
            # Sarah" -> "Thinking about sarah"). Uppercase only the first
            # character; leave the rest -- including any name -- alone.
            current_activity = _display_act[:1].upper() + _display_act[1:]
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
            "world": self._world_status(),
            "energy": energy,
            "desire": self._desire_system.get_status(),
            "goals": self._goal_engine.get_status(now=self._world_clock()()),
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
            "social": {**self._social.get_status(), "household": self._household_export()},
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
            # depth now, regressed by any silence (as relationship_depth and
            # the export give it), not as of the user's last turn
            "expression": {**self._expression.get_status(), "depth": round(self.relationship_depth, 3)},
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
                "career": self._render_career_status(self._career.get_status(now=self._world_clock()())),
                "errands": self._errands.get_status(),
                "places": self._location.get_status(),
                "transport": self._transport.get_status(self._transit),
            })
        return status

    def _activity_for_display(self, name: str) -> str:
        """An activity id as she would say it: "user" -- the id of her
        "thinking about user" -- as her user's name, or "them"."""
        return name.replace("user", self._user_ref()) if "user" in name else name

    # ============= Household (Task 11, spec section 4.5) =============

    def _housemates(self) -> list:
        """The services of the people she lives with, joined now (none for a
        stand-in built without ``__init__``, as for one living alone)."""
        household = getattr(self, "_household", None)
        return household.housemates(self) if household is not None else []

    def _npc_for(self, other) -> Optional[NPC]:
        """Her social-circle entry for housemate ``other``: the one whose name
        is ``other``'s persona id or definition name, compared
        case-insensitively; ``None`` when she has none."""
        keys = {str(other._persona_id or "").strip().lower(),
                str(getattr(other._definition, "name", "") or "").strip().lower()} - {""}
        for npc in self._social._npcs.values():
            if npc.name.strip().lower() in keys:
                return npc
        return None

    def _housemate_name(self, other) -> str:
        """How she names housemate ``other``: as her social circle does, else
        by ``other``'s definition name, else by ``other``'s persona id."""
        npc = self._npc_for(other)
        if npc is not None and npc.name.strip():
            return npc.name.strip()
        name = str(getattr(other._definition, "name", "") or "").strip()
        return name or str(other._persona_id)

    def _housemate_npc_names(self) -> set:
        """Her social-circle names for the housemates joined now: their own
        lives run beside hers, so they draw no ordinary NPC event
        (``SocialSystem.tick``'s ``skip``). One she expects who is not joined
        is not here: her entry is an ordinary NPC."""
        names = set()
        for other in self._housemates():
            npc = self._npc_for(other)
            if npc is not None:
                names.add(npc.name)
        return names

    def _household_state_now(self) -> HousemateState:
        """What she shows the people she lives with, read from her live state
        now (:class:`~aura_life.social.household.HousemateState`): whether she
        is asleep, where she is, and her last activity -- none while she
        sleeps, and none when it was one of her intimate activities: what she
        does in private is hers alone."""
        asleep = bool(self.is_asleep())
        transit = self._transit
        in_transit = bool(transit is not None and transit.phase == TransitPhase.IN_TRANSIT)
        doing = ""
        if not asleep and self._recent_activities:
            last = self._recent_activities[0].activity_name
            private = {activity.name for activity in self._setting.intimate_catalogue()}
            if last not in self._setting.names_tagged("sleep") and last not in private:
                doing = self._activity_for_display(last)
        return HousemateState(
            asleep=asleep,
            location=self._current_location or "home",
            in_transit=in_transit,
            destination=transit.destination if in_transit else "",
            activity=doing,
        )

    def _publish_household_state(self) -> None:
        """Publish what the people she lives with see of her
        (:meth:`_household_state_now`) -- at the end of each of her ticks, and
        when she is built, loaded or joins a housemate. Read under the
        household's lock, so no housemate's activity tick writes into her
        meanwhile, and swapped in whole: a view read on another thread gets
        this state or the one before, never half of each. Nothing when she
        lives alone."""
        household = getattr(self, "_household", None)
        if household is None:
            return
        with household.lock:
            self._household_state = self._household_state_now()

    def _housemate_view(self, other) -> dict:
        """What she knows of housemate ``other``: the state ``other``
        published at the end of her last tick (:meth:`_publish_household_state`
        -- never ``other``'s live fields, which her running tick may be
        halfway through changing), and never saved on this side. Whether she
        is asleep, where she is (and whether that is where this persona is),
        and what she is doing."""
        state = getattr(other, "_household_state", None) or HousemateState()
        return {
            "persona_id": other._persona_id,
            "name": self._housemate_name(other),
            "asleep": state.asleep,
            "location": state.location,
            "in_transit": state.in_transit,
            "destination": state.destination,
            "activity": state.activity,
            "here": not state.in_transit and state.location == self._current_location,
        }

    def _household_views(self) -> List[dict]:
        """Every housemate joined now, as she knows them (:meth:`_housemate_view`),
        in the order they joined -- what her life context tells."""
        return [self._housemate_view(other) for other in self._housemates()]

    def _household_export(self) -> dict:
        """Her household for ``get_status()`` and ``export_outer_state()``
        (``["social"]["household"]``): the housemates joined now
        (:meth:`_household_views`), the persona ids her definition expects
        (``PersonalityDefinition.household``, lower-cased), and those of them
        not joined."""
        definition = getattr(self, "_definition", None)
        household = getattr(self, "_household", None)
        raw = (getattr(definition, "household", None) or []) if definition is not None else []
        expected = [str(pid).strip().lower() for pid in raw if str(pid).strip()]
        joined = set(household.member_ids()) if household is not None else set()
        return {
            "members": self._household_views(),
            "expected": expected,
            "missing": [pid for pid in expected if pid not in joined],
        }

    def _invite_housemates(self, activity, in_transit: bool) -> list:
        """Who joins her in ``activity``, which she is about to do: the
        housemates free for it (:meth:`_free_to_join`), when it is a joint
        activity (tag "joint"), she is not on the way anywhere, and her own
        household roll (``self._joint_chance``, on her own "household"
        stream -- no one else's draws move) says she asks. Each as
        ``(housemate, the housemate's own activity of that name, her plan's
        slot for the hour)``, in the order they joined; none, most ticks."""
        if self._household is None or "joint" not in activity.tags or in_transit:
            return []
        now = self._world_clock()()
        joiners = []
        for other in self._housemates():
            try:
                fit = other._free_to_join(activity.name, self._current_location, now)
            except Exception:
                # A housemate whose state cannot be read is not free: her
                # failure must not take this tick down with it.
                logger.debug("Housemate %r could not be asked in", getattr(other, "_persona_id", None),
                             exc_info=True)
                fit = None
            if fit is not None:
                joiners.append((other,) + fit)
        if not joiners or self._household_rng.random() >= self._joint_chance:
            return []
        return joiners

    def _joint_sides(self, joiners: list) -> tuple:
        """Her side of doing it with ``joiners`` and each joiner's
        (:class:`~aura_life.social.household.JointSide`): whom each does it
        with, as each names them, and the line each one's log adds -- hers,
        that they joined her; each of theirs, that she joined the one who
        asked (JOINT_LINES, drawn on her household stream). Where the joiners
        go is set once she is there."""
        others = [other for other, _, _ in joiners]
        names = [self._housemate_name(other) for other in others]
        mine = JointSide(
            with_name=name_list(names),
            npc_names=tuple(npc.name for npc in (self._npc_for(other) for other in others) if npc is not None),
            line=self._household_rng.choice(JOINT_LINES["initiator"]),
            names=tuple(names),
        )
        theirs = []
        for other in others:
            npc = other._npc_for(self)
            name = other._housemate_name(self)
            theirs.append(JointSide(
                with_name=name,
                npc_names=(npc.name,) if npc is not None else (),
                line=self._household_rng.choice(JOINT_LINES["joiner"]),
                names=(name,),
            ))
        return mine, theirs

    def _free_to_join(self, activity_name: str, place: str, now: datetime):
        """Can she join a housemate's ``activity_name`` at ``place`` at the
        world instant ``now``? ``(her Activity of that name, her plan's slot
        for the hour)`` when she can, else ``None``.

        She can when she is awake -- and, a persona who sleeps, outside her
        sleep window now and for the activity interval to come
        (LifeScheduler.TICK_INTERVAL_MINUTES), so she never joins in on her
        way to bed -- where the housemate is, not on the way anywhere, not
        already in a housemate's activity, and has not acted at this very
        instant (a lock-step driver ticks both at one instant: the one whose
        tick comes first does the asking); when the activity is hers to take
        up (:meth:`_excluded_activities`), she has the energy for it (forced
        to rest, only if it is rest), and the social battery
        (``SocialSystem.should_decline_social``); and when her plan leaves the
        hour free -- or plans that very activity: never a commitment or
        another anchor."""
        if self.is_asleep():
            return None
        if self._joint_until is not None and now < self._joint_until:
            return None
        if self._activity_tick_at is not None and self._activity_tick_at == now:
            return None
        if self._transit is not None and self._transit.phase in (TransitPhase.PREPARING, TransitPhase.IN_TRANSIT):
            return None
        if self._current_location != place:
            return None
        local = self._local_world_now()
        if not self._is_ai:
            interval = timedelta(minutes=LifeScheduler.TICK_INTERVAL_MINUTES["activity"])
            if self._energy.in_sleep_window(local) or self._energy.in_sleep_window(local + interval):
                return None
        activity = self._activity_engine.get_activity(activity_name)
        if activity is None or activity.name in self._excluded_activities():
            return None
        if self._energy.effective_level < activity.min_energy:
            return None
        if self._energy.should_rest() and activity.category != ActivityCategory.REST:
            return None
        if self._social.should_decline_social():
            return None
        slot = self._daily_planner.get_planned_activity(local.hour)
        if slot is not None and slot.activity_name != activity.name and not self._daily_planner.is_free_time(slot):
            return None
        return activity, slot

    def _join_housemate(self, activity, planned_slot, side: JointSide) -> None:
        """She joins a housemate in ``activity`` (the housemate's activity
        tick calls this, holding the household's lock): she does it now,
        through her own pipeline (:meth:`_perform_activity`), where the
        housemate is (``side.place``), and it takes her next activity tick
        within one activity interval (LifeScheduler.TICK_INTERVAL_MINUTES) --
        so she does it once.

        Joining takes her hour (Task 28, ruling T13-R1): her plan's slot for
        it becomes the activity where the housemate is, "with" whom she does
        it (``DailyPlanner.join_activity``, the schedule overrides' own
        mechanism), before she does it -- so the sync of her plan at the end
        of it (:meth:`get_current_location`) and every later one keeps her
        there, and the rest of the hour is the activity."""
        interval = timedelta(minutes=LifeScheduler.TICK_INTERVAL_MINUTES["activity"])
        self._joint_until = self._world_clock()() + interval
        self._joint_at = self._local_world_now()
        self._daily_planner.join_activity(activity.name, side.place or self._current_location,
                                          reason=f"with {side.with_name}", now=self._joint_at)
        self._perform_activity(activity, planned_slot, joint=side)
        self._publish_household_state()

    def _on_housemate_company(self, side: JointSide, activity_name: str) -> None:
        """The company of the housemate(s) she did ``activity_name`` with: a
        meaningful interaction for her loneliness
        (``AffectSystem.on_social_interaction``), a cost to her social
        battery, and -- for each she has in her social circle -- an
        interaction on their relationship arc and a shared memory in how she
        sees them."""
        self._affect.on_social_interaction(meaningful=True, now=self._world_clock()())
        self._social.drain_social_battery()
        memory = f"{activity_name[:1].upper()}{activity_name[1:]} with {side.with_name}"
        for name in side.npc_names:
            self._social.update_arc(name, "interaction", now=self._world_clock()())
            npc = self._social._npcs.get(name)
            self._identity.update_from_social_event(SocialEvent(
                npc_name=name, event_type="hangout", description=memory,
                timestamp=self._world_clock()(), kind=npc.kind if npc is not None else DEFAULT_NPC_KIND,
                valence=1.0,
            ))

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
        """Handle plan tick - generate daily plan if needed. Her plan is for
        her local world day, and its revision is of the hours still ahead of
        her local world time (:meth:`_local_world_now`; Task 28)."""
        local_now = self._local_world_now()
        if self._daily_planner.needs_new_plan(now=local_now):
            # Reset daily flags for new day
            self._basic_needs.showered_today = False
            self._basic_needs.morning_routine_done = False
            self._sustenance.reset_daily()
            self._room_state.candle_lit = False
            self._room_state.music_playing = False
            self._body.on_new_day(now=self._world_clock()())
            self._reset_visual_moment()

            # Rotate music obsession every few days
            if self._service_rng.random() < 0.2:
                music = self._media_preferences.get("music", [])
                if music:
                    self._media.current_music_obsession = self._service_rng.choice(music)

            self._daily_planner.generate_daily_plan(
                goals=self._goal_engine.active_goals,
                weather=self._world.weather,
                available_activities=self._activity_engine.get_all_activities(),
                recent_activity_names=[a.activity_name for a in self._recent_activities[:5]],
                work_schedule=self._career_schedule(),
                now=local_now,
                habits=self._habit_factors(),
            )
            self._apply_social_plans()
            self._save_plan()
            logger.info("Generated new daily plan")
        else:
            # Silently revise upcoming slots if conditions changed
            self._daily_planner.revise_upcoming(
                weather=self._world.weather,
                energy_level=self._energy.effective_level,
                mood=self._affect.mood.current_mood if self._affect else "",
                mood_intensity=self._affect.mood.intensity if hasattr(self._affect.mood, 'intensity') else 0,
                now=local_now,
            )
            self._apply_social_plans()
        self._publish_household_state()

    def _on_world_tick(self) -> None:
        """Handle world tick. Skips if world is externally managed (shared)."""
        if not self._shared_world:
            self._world.tick()
            logger.debug(f"World tick: {self._world.weather.value}, {self._persona_time_of_day.value}")
        # Real weather override — runs whether or not the world was ticked here,
        # because the persona's location state may have changed independently.
        self._update_weather()
        # Trip lifecycle — per-day roll; return check on every tick, on the
        # world clock (Task 19: it read the host's).
        self._update_trip(_now=self._world_clock()())
        self._publish_household_state()

    def _on_energy_tick(self) -> None:
        """Handle energy tick."""
        self._energy.tick(self._persona_time_of_day)
        self._desire_system.tick(self._persona_time_of_day, self._world.weather, now=self._world_clock()())
        self._identity.tick()

        # Tick behavioral tendencies with cross-engine state
        self._identity.tick_tendencies(
            stress=self._affect.stress.level,
            loneliness=self._affect.loneliness.level,
            energy_level=self._energy.state.effective_level,
            stimulation_need=getattr(self._drive, '_stimulation_need', 0.5) if self._drive else 0.5,
            mood=self._affect.mood.current_mood if self._affect else "neutral",
        )

        # What weighs on her (Task 15): each producer below raises or holds
        # its stressor while its cause holds and resolves it once the cause is
        # gone, at this tick's world instant (an episode lapses by itself,
        # after her mood's valence half-life -- affect's STRESSOR_KINDS).
        _stress_now = self._world_clock()()

        # Route struggle effects to affect/cognitive: a struggle flaring up
        # is an episode, named in her own words for it.
        for struggle in self._identity.get_pending_struggle_effects():
            self._affect.raise_stressor("struggle", now=_stress_now, what=struggle)
            if self._service_rng.random() < 0.5:
                self._cognitive.on_conflict(struggle)

        # === Physical-life engines (humans only — an AI doesn't eat or keep a home) ===
        if not self._is_ai:
            # Sustenance: hunger / nutrition, per world hour since the last
            # sustenance tick (ruling T4-R4) -- they were per call, so the
            # host's tick rate set how fast she starved. High hunger drains
            # her energy per waking hour, never while she sleeps.
            self._tick_sustenance()
            # Habitation: living space -- a bleak, messy one is a mild
            # stressor, until she tidies it (HabitationSystem.COMFORT_BLEAK).
            self._habitation.tick(self._persona_time_of_day)
            self._affect.hold_stressor("home", self._habitation.comfort < COMFORT_BLEAK, now=_stress_now)

        # === Body tick === (her plan's slot at her local world time; in a
        # joint window's tail, the instant she joined: what she is doing,
        # T19-R5)
        current_activity = ""
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot(self._activity_instant())
            if slot:
                current_activity = slot.activity_name
        self._body.tick(
            activity_name=current_activity,
            weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
            hours_awake=self._energy.hours_awake,
            stress_level=self._affect.stress.level,
            # Self-image is dragged down by shame (routed from Shadow via LifeService).
            shame=self._shadow.get_status().get("shame", 0.0) if self._shadow else 0.0,
            now=_stress_now,
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
        # A hangover weighs on her while it lasts.
        self._affect.hold_stressor("hangover", bool(inebriation_fx.get("is_hungover")), now=_stress_now)

        # === The day's quality (ruling T14-R1) === drawn at her first waking
        # tick of a day (keyed by her last wake) outside her sleep window,
        # before the tick that feels it.
        self._draw_day_quality()

        # === Affect tick ===
        # Mood's half-lives run on the world hours since the last affect tick,
        # on the world clock like energy and sanity; the stamp is taken at
        # construction and again on reload, so downtime is not charged as
        # lived time (see _tick_sanity).
        _affect_now = self._world_clock()()
        _affect_hours = max(0.0, (_affect_now - self._affect_ticked_at).total_seconds() / 3600)
        self._affect_ticked_at = _affect_now
        # Asleep: the service's answer, not the energy system's flag: the wake
        # button wakes her here (force_wake) and leaves that flag set.
        self._tick_affect(_affect_hours, _affect_now, asleep=self.is_asleep())
        self._decay_emotion_engine()

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

        # === Life Events: record a mood-label change (throttled) ===
        # on_mood_change fires only when affect.mood.current_mood differs
        # from the label at her last mood life-event, and at most once every
        # MOOD_EVENT_MIN_HOURS simulated hours -- replaces recording on every
        # energy tick (Task 5 / humanness Sec 4.9). `_affect_now` is this same
        # tick's world-clock instant, already read above for the affect tick.
        mood_intensity = self._affect.mood.intensity if hasattr(self._affect.mood, 'intensity') else 0
        life_event = self._life_events.on_mood_change(
            self._affect.mood.current_mood, mood_intensity, _affect_now
        )
        if life_event:
            self._bridge_life_event(life_event)

        # === Cognitive tick ===
        self._cognitive.tick(
            current_activity=current_activity,
            stress_level=self._affect.stress.level,
            sleep_quality=self._body.sleep_quality.last_quality,
            hunger=self._basic_needs.hunger,
            now=_stress_now,
        )
        # Awareness (from Energy) modulates focus — foggy/barely-present dampens it.
        _awareness = self._energy.awareness()
        if _awareness < 0.4:
            self._cognitive._focus.quality = max(
                0.0, self._cognitive._focus.quality - (0.4 - _awareness) * 0.2
            )

        # === Shadow tick (inner dark psychology) ===
        # Reuse the same affect-derived signals the cognitive/affect ticks use.
        # Mood's -1..1 valence, rescaled to the 0..1 valence (1 = good,
        # 0 = bad) the Shadow engine expects.
        _mood_label = self._affect.mood.current_mood if self._affect else "neutral"
        _mood_intensity = self._affect.mood.intensity if self._affect else 0.0
        _mood_valence = self._mood_to_valence(
            _mood_label, _mood_intensity,
            valence=self._affect.mood.valence if self._affect else None,
        )
        self._shadow.tick(
            stress=self._affect.stress.level,
            loneliness=self._affect.loneliness.level,
            mood=_mood_valence,
        )

        # === Sanity tick (the interior that integrates and can break) ===
        self._tick_sanity()

        # === Drive tick === (on the world clock, Task 19)
        self._drive.tick(now=_stress_now)
        self._drive.roll_avoidance()
        # What she is putting off weighs on her once its guilt has grown
        # (DriveSystem.put_off): one stressor, named for what she has put off
        # most, weighing a hassle's worth when she has put off as much as she
        # can at full guilt (DriveSystem.put_off_share) and a share of one
        # for less -- four things put off are one weight in her day, not
        # four. It lifts when she gets to them.
        put_off = self._drive.put_off()
        self._affect.hold_stressor("put_off", bool(put_off), now=_stress_now, share=self._drive.put_off_share(),
                                   **({"what": put_off[0]} if put_off else {}))

        # === Social expansion tick ===
        # On the world clock, as their stamps are (Task 19).
        self._social.tick_arcs(now=_stress_now)
        self._social.tick_obligations(now=_stress_now)
        self._social.prune_plans(self._world_clock()())
        self._social.tick_conflicts(now=_stress_now)
        self._social.recharge_social_battery()
        # An overdue obligation weighs on her until she keeps it.
        self._affect.hold_stressors("obligation", [{"what": obligation}
                                                   for obligation in self._social.get_overdue_obligations()],
                                    now=_stress_now)

        # === Career / Finance / Errands (humans only) ===
        # On the world clock, the way the catch-up path already ticks them
        # (``now=timestamp``): ``CareerSystem.tick`` registers a workday off
        # ``now``'s date and hour and only then draws, ``FinanceSystem.tick``
        # credits and debits on ``now``'s month, and with those draws on an
        # injected ``rng`` a bare ``tick()`` made the host wall clock decide
        # how many values the stream gave up -- a run and its replay, hours
        # apart, drew different counts. Without an injected world clock this
        # is ``datetime.now()`` exactly as before (see :meth:`_world_clock`).
        # Work stress is asked on the same instant: a bare ``work_stress()``
        # answered ``on_shift`` from the host's weekday and hour, so the hour
        # the process ran decided whether work reached affect as a stressor.
        if not self._is_ai:
            _world_now = self._world_clock()()
            _work_event = self._career.tick(now=_world_now)
            if _work_event:
                # A good or bad day at work moves her mood, and she keeps it
                # (Task 12), in her setting's words addressed to her.
                work_emotions = self._setting.work_event_emotions.get(_work_event, {})
                self._feel(work_emotions)
                self._remember(self._addressed_to_her(_work_event), emotions=work_emotions, tags=("work",))
            if self._career.monthly_salary > 0:
                self._finance.state.monthly_income = self._career.monthly_salary
            # Work weighs on her while her shift's workload does (work
            # stress at 0.5 or more, as it always has), by how much it is:
            # the end of her shift ends it. Money worries while money is
            # tight (financial stress at 0.4 or more), by how tight, on
            # FinanceSystem's own scale (MAX_FINANCIAL_STRESS): money coming
            # in ends them. Errands piling up while three or more are
            # overdue, by how many of the most the backlog holds
            # (errands MAX_TOTAL): an errand done ends it.
            _work_stress = self._career.work_stress(now=_world_now)
            self._affect.hold_stressor("work", _work_stress >= 0.5, now=_stress_now, share=_work_stress)

            self._finance.tick(now=_world_now)
            _money_stress = self._finance.financial_stress()
            self._affect.hold_stressor("money", _money_stress >= 0.4, now=_stress_now,
                                       share=_money_stress / MAX_FINANCIAL_STRESS)

            self._errands.tick(now=_world_now)
            self._affect.hold_stressor("errands", self._errands.overdue_count >= 3, now=_stress_now,
                                       share=self._errands.overdue_count / ERRANDS_MAX_TOTAL)

        # === Behavior tick (ambient senses) ===
        self._behavior.tick(
            location=self._current_location or "home",
            weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
            time_of_day=self._persona_time_of_day.value if hasattr(self._persona_time_of_day, 'value') else str(self._persona_time_of_day),
        )

        # === Expression tick (connection awareness) ===
        self._expression.tick()
        # Relationship stage from depth at the world instant (Task 16b): a
        # week of silence can lower it before the user's next turn
        self._expression.refresh_stage(self._world_clock()(), self.last_user_turn_at)

        # === Continuity tick (daily/weekly cycles) ===
        # On the world clock, gate and stamps alike: the cycles compare ``now``
        # with the stamps the engines took last time, so both sides have to be
        # the same clock. On the host clock a simulated run fired every cycle
        # once, on its first tick, and again only after a real day (week,
        # month) of process life. The calendar scan below stays on the host
        # clock: it reads entries a host added in real time and feeds follow-up
        # triggers whose cooldowns ``_evaluate_life_triggers`` stamps on the
        # host clock.
        now = self._world_clock()()
        if (not self._continuity._last_daily_tick or
                (now - self._continuity._last_daily_tick).total_seconds() > 86400):
            continuity_events = self._continuity.daily_tick(now=now)
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
            self._continuity.weekly_tick(skill_levels, identity_facets, trust, now=now)
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
                now=now,
            )
            if drift_changes:
                logger.info(f"Character evolution drift: {drift_changes}")
        # Monthly continuity synthesis (life chapters, every 30 days)
        if (not self._continuity._last_monthly_tick or
                (now - self._continuity._last_monthly_tick).total_seconds() > 2592000):
            # Gather month's data for chapter synthesis: the WHOLE period's
            # dominant activities and mean-valence mood (Task 13), not the
            # last 50 activities or the mood at this one instant.
            period_start = self._continuity._last_monthly_tick or now
            mood_str_month, activity_counts = self._chapter_window_stats(period_start, now)
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
                now=now,
            )
            if chapter:
                # Also add to MemoryTime's life chapters
                self._memory_time.add_life_chapter(
                    title=chapter.title,
                    summary=chapter.summary,
                    turning_points=chapter.turning_points,
                    dominant_emotions=chapter.dominant_emotions,
                    now=now,
                )
                self._save_continuity()
        # Check milestones
        milestone = self._continuity.check_milestones(
            interaction_count=self._expression._interaction_count,
            vulnerability_openness=self._expression._style.vulnerability_openness,
            inside_joke_count=len(self._identity.get_inside_jokes()),
        )
        if milestone:
            milestone.description = self._render_text(milestone.description)
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
        tod_str = self._persona_time_of_day.value if hasattr(self._persona_time_of_day, 'value') else str(self._persona_time_of_day)
        nostalgia_event = self._memory_time.tick(
            current_activity=current_activity,
            mood=mood_str,
            season=season_str,
            time_of_day=tod_str,
            now=now,  # the continuity block's world instant, same tick
        )
        if nostalgia_event:
            remembered = self._real_nostalgia_episode(now)
            if remembered is not None:
                # A real memory, at least NOSTALGIA_MIN_EPISODE_AGE_DAYS old
                # (Task 13): her gist replaces the setting's template, and
                # surfacing it reinforces it (ruling T12-R2).
                nostalgia_event.memory_reference = remembered.gist()
                self._memory.reinforce([remembered], now=now)
            self._affect.on_emotion_event("nostalgic", nostalgia_event.intensity)
            if nostalgia_event.intensity > 0.4:
                reminded = self._render_text("Something reminded {obj} of")
                memory_text = self._render_text(nostalgia_event.memory_reference)
                self._create_shareable_from_text(
                    f"{reminded} {memory_text}",
                    context=f"A wave of nostalgia from {nostalgia_event.trigger}",
                )

        # === Reflection (Task 13) ===
        self._reflect(now)

        # === Anticipation → mood ===
        # Felt for as long as it lasts: ANTICIPATION_MOOD_PER_HOUR x its
        # intensity per world hour since the last affect tick. (It was that
        # much per energy tick, so the more often the ticks ran the more she
        # felt it.)
        anticipations = self._memory_time.get_anticipations(now=_stress_now)
        for ant in anticipations:
            if ant.feeling == "excited" and ant.intensity > 0.2:
                self._affect.on_emotion_event(
                    "excited", ant.intensity * ANTICIPATION_MOOD_PER_HOUR * _affect_hours)
            elif ant.feeling == "dreading" and ant.intensity > 0.2:
                self._affect.on_emotion_event(
                    "anxious", ant.intensity * ANTICIPATION_MOOD_PER_HOUR * _affect_hours)

        # === Evaluate life-driven proactive triggers ===
        self._evaluate_life_triggers()

        # === Periodic state persistence (world clock, at most once/hour) ===
        # `now` is the continuity block's world instant, above -- same tick.
        # Gated on `_is_initialized`: `_save_state()`'s energy write is a
        # plain UPDATE ... WHERE id=1, a no-op until `_load_state()` (via
        # `start()`) has inserted that row -- but once a *previous* run's
        # `start()` did insert it, a service that ticks here without ever
        # loading would periodically overwrite that saved state with fresh
        # in-memory defaults. Only a service that has loaded its own state
        # may write it back.
        # Explicit `_save_state()` calls remain at stop(), reset, and
        # catch-up; this is the only tick-driven one, so a crash between them
        # loses at most an hour of simulated time instead of everything since
        # the last explicit save.
        if self._is_initialized and (now - self._last_periodic_save_at).total_seconds() >= 3600:
            self._save_state()
            self._last_periodic_save_at = now

        self._publish_household_state()
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
        ``SANITY_STRESSED_LEVEL``, not whether any stressor is listed: a
        hassle or two is on her mind most of the time, and weighs too little
        to wear her down (see ``SANITY_STRESSED_LEVEL``).
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

        # Strained or worse, keeping it together weighs on her; sound, it
        # lifts (affect's "sanity" stressor, SANITY_STRESS_SOURCE).
        self._affect.hold_stressor("sanity", new != "sound", now=self._world_clock()())

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

    # ============= Emotions: mood and the host's EmotionEngine =============

    def _feel(self, emotions: Dict[str, float], *, reactivity_applied: bool = False) -> None:
        """She feels ``emotions`` (name -> intensity): each goes to the host's
        EmotionEngine, when one was injected, and to mood. Activities,
        intimate activities, micro-events, chaos, goal events and completions
        and work events all come through here, so none of them reaches one and
        not the other. (The small mood-only nudges -- a new place, an
        anniversary, nostalgia, an anticipation -- go to mood alone, as they
        always did.)

        ``reactivity_applied``: they are her appraisal's (Task 14), felt as
        strongly as her volatility makes them -- mood is told so
        (``AffectSystem.on_emotion_event``) and does not scale them by it
        again."""
        for emotion, intensity in (emotions or {}).items():
            if self._emotion_engine:
                try:
                    self._emotion_engine.add_emotion(emotion, intensity)
                except Exception:
                    pass  # a host engine may reject a name its wheel lacks
            if reactivity_applied:
                self._affect.on_emotion_event(emotion, intensity, reactivity_applied=True)
            else:
                self._affect.on_emotion_event(emotion, intensity)

    def _draw_day_quality(self) -> None:
        """The day's quality (ruling T14-R1; ``AffectSystem.new_day``): drawn
        once per persona-day, on the world clock, at her first waking tick
        outside her sleep window (``EnergySystem.in_sleep_window``) -- so
        waking in the night draws nothing and a nap never draws again. Her
        day is keyed by the date of her last effective wake
        (``EnergySystem.last_wake``), not the calendar's: a night owl up past
        midnight is still in the day before, and the new day's draw waits for
        the night that shifts it. Drawn from her own "day_quality" stream,
        shifted by last night's sleep (``BodySystem.sleep_quality``; an AI
        persona, who does not sleep, has no night to go by). A service that
        starts awake draws at its first waking tick; one reloaded mid-day
        keeps the day it saved."""
        local = self._local_world_now()
        if self.is_asleep() or self._energy.in_sleep_window(local):
            return
        today = self._energy.last_wake(local).date()
        if self._affect.day_quality[0] == today:
            return
        slept = None if self._is_ai else self._body.sleep_quality.last_quality
        self._affect.new_day(today, self._day_quality_rng, sleep_quality=slept)

    def _decay_emotion_engine(self) -> None:
        """Decay the host's EmotionEngine by the world time since the last call
        (see ``decays_emotion_engine``).

        aura-life's own EmotionEngine is decayed by that many seconds through
        its ``_decay``; ``decay_tick()``, its public method, measures the wall
        clock instead, which on a simulated world is not the time the persona
        lived. A host engine without ``_decay`` is decayed through its own
        ``decay_tick()``, on its own clock; one with neither is left alone.
        """
        now = self._world_clock()()
        seconds = max(0.0, (now - self._emotion_decayed_at).total_seconds())
        self._emotion_decayed_at = now
        engine = self._emotion_engine
        if engine is None:
            return
        decay = getattr(engine, "_decay", None)
        if callable(decay):
            decay(seconds)
            return
        decay_tick = getattr(engine, "decay_tick", None)
        if callable(decay_tick):
            decay_tick()

    def _evaluate_life_triggers(self):
        """Evaluate all engine state and create proactive triggers when conditions are met.

        Called at end of _on_energy_tick() (every 5 min) after all cross-engine routing
        is complete. Never called during catch-up.

        Each candidate's hint carries what moved her (Task 17): an episode
        of her memory stream, a life event, her plan slot, or when the user
        last spoke for a need of contact; a candidate with no such detail is
        not made (rulings T17-R2, T17-R3). Its words are hers, in the second
        person, with no number or engine label (T17-R4).
        """
        if self._follow_up_provider is None:
            return

        now = datetime.now()
        fm = self._follow_up_provider(self._persona_id)
        candidates = []  # (trigger_type_str, urgency, topic, prompt_hint)
        # The share id each candidate's hint is about (ruling T17-R1), and
        # what a candidate consumes only if it is the one that fires.
        share_ids: Dict[str, str] = {}
        consumed: Dict[str, Tuple[str, object]] = {}

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
                # What is on her mind is the detail; a shift with nothing
                # behind it is no trigger (ruling T17-R2).
                moved = self._on_her_mind()
                if moved is not None:
                    hint = (
                        f"You're feeling {_plain(cur_mood)} now. {self._on_her_mind_line(moved)} "
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
                # When they last spoke, else what is on her mind; neither, no
                # trigger (ruling T17-R2).
                last = self._last_talked()
                moved = None if last else self._on_her_mind()
                if last:
                    lonely = f"{last}, and you've been feeling really lonely."
                elif moved is not None:
                    lonely = f"You've been feeling really lonely. {self._on_her_mind_line(moved)}"
                else:
                    lonely = ""
                if lonely:
                    hint = (
                        f"{lonely} You want to hear from them — "
                        "ask how their day is going, or share something to start a conversation."
                    )
                    candidates.append(("loneliness_spike", 0.6, "feeling lonely", hint))
            self._prev_loneliness = cur_loneliness
        except Exception:
            logger.debug("Life trigger: loneliness_spike eval failed", exc_info=True)

        # --- 3. DREAM_SHARE --- only of a dream she remembers (ruling T17-R3:
        # the episode _on_woke records), not yet offered, still hers to share;
        # an emotion residue alone is none.
        try:
            dream = self._newest_episode("dream")
            if (dream is not None and dream.id != getattr(self, "_last_dream_share_episode", None)
                    and self._still_unshared(dream) and self._life_trigger_cooled_down("dream_share", now)):
                hint = (
                    f"A dream from {self._when_said(dream.at)} is still with you: {_told(dream)} "
                    f"Share it casually, like 'I had the strangest dream last night...'"
                )
                candidates.append(("dream_share", 0.4, _plain(dream.what)[:60], hint))
                share_ids["dream_share"] = next(iter(_share_ids_of(dream)), "")
                consumed["dream_share"] = ("_last_dream_share_episode", dream.id)
        except Exception:
            logger.debug("Life trigger: dream_share eval failed", exc_info=True)

        # --- 4. CHAOS_EVENT ---
        try:
            chaos_state = self._chaos.export_state()
            last_event_text = chaos_state.get("last_chaos_event", "")
            last_event_type = chaos_state.get("last_chaos_type", "")
            if last_event_text and last_event_text != self._last_seen_chaos_event:
                share_worthy = last_event_type in ("serendipity", "universal")
                # Her memory of it is the hint (Task 12 records it, addressed
                # to her, where it happened); none, no trigger.
                told = self._newest_episode("chaos", last_event_type) if share_worthy else None
                if told is not None and self._life_trigger_cooled_down("chaos_event", now):
                    hint = (
                        f"Something happened {self._when_said(told.at)}: {_told(told)} "
                        f"Share it like you'd tell a friend about your day."
                    )
                    candidates.append(("chaos_event", 0.55, last_event_text[:60], hint))
                    share_ids["chaos_event"] = next(iter(_share_ids_of(told)), "")
                self._last_seen_chaos_event = last_event_text
        except Exception:
            logger.debug("Life trigger: chaos_event eval failed", exc_info=True)

        # --- 5. NOSTALGIA ---
        try:
            recent = self._memory_time.get_recent_nostalgia(1)
            if recent:
                n = recent[0]
                if n.intensity >= 0.4 and n.memory_reference != self._last_seen_nostalgia_ref:
                    # Addressed to her, in the second person -- what she
                    # remembers quoted back to her (spec 4.10) -- so a
                    # template's {subj}/{poss} token never reaches this
                    # prompt-bound hint (found in Task 9: this was one of
                    # two paths that read n.memory_reference unrendered).
                    memory_text = self._addressed_to_her(n.memory_reference)
                    if self._life_trigger_cooled_down("nostalgia", now):
                        hint = (
                            f"A memory hit you — {memory_text}. "
                            f"Share the feeling with them, maybe ask if they've had moments like that."
                        )
                        candidates.append(("nostalgia", 0.4, memory_text[:60], hint))
                    self._last_seen_nostalgia_ref = n.memory_reference
        except Exception:
            logger.debug("Life trigger: nostalgia eval failed", exc_info=True)

        # --- 6. GOAL_MILESTONE ---
        # A goal she completed (its episode, _on_goal_tick's, with what it
        # was: the life event's description) comes first; else what she
        # feels about a goal she names -- never the goalless line, which
        # names none (Task 17).
        try:
            done = self._newest_episode("goal", "completed")
            if done is not None and (done.id == getattr(self, "_last_goal_share_episode", None)
                                     or not self._still_unshared(done)):
                done = None
            emotional_ctx = ("" if self._goal_engine.is_goalless
                             else self._goal_engine.get_emotional_context(now=self._world_clock()()))
            if (done is not None or emotional_ctx) and self._life_trigger_cooled_down("goal_milestone", now):
                if done is not None:
                    goal_id = next(iter(_share_ids_of(done)), "")
                    event = next((e for e in self._life_events.get_unshared_events() if e.share_id == goal_id), None)
                    about = _plain(event.description) if event is not None else ""
                    set_out = (f"You had set out to do this: {about}. "
                               if about and about.lower() not in _plain(done.what).lower() else "")
                    hint = (
                        f"You reached a goal {self._when_said(done.at)}: {_told(done)} {set_out}"
                        f"Name the ONE concrete thing that actually moved it (a specific step you "
                        f"took, a real obstacle you got past) — never a vague 'epiphany' or "
                        f"'I cracked the code'."
                    )
                    candidates.append(("goal_milestone", 0.5, _plain(done.what)[:60], hint))
                    share_ids["goal_milestone"] = goal_id
                    consumed["goal_milestone"] = ("_last_goal_share_episode", done.id)
                else:
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
                # Unwelcome news -- a threat, someone she is estranged from --
                # is never something she shares (ruling T11-R1): it weighs on
                # her as stress instead.
                if ev.share_worthy and getattr(ev, "valence", 0.0) >= 0 and age_min <= 30:
                    # Her memory of it (who, what, where; _on_social_event's
                    # episode), never the event's line, which is written
                    # about her; none, no trigger.
                    told = self._newest_episode("social", ev.event_type, person=ev.npc_name)
                    if told is not None and self._life_trigger_cooled_down("social_event", now):
                        hint = (
                            f"Something happened with {ev.npc_name} {self._when_said(told.at)}: "
                            f"{_told(told)} Share it naturally."
                        )
                        candidates.append(("social_event", 0.45, ev.description[:60], hint))
                        share_ids["social_event"] = next(iter(_share_ids_of(told)), "")
        except Exception:
            logger.debug("Life trigger: social_event eval failed", exc_info=True)

        # --- 8. NEED_DRIVEN ---
        try:
            needs = self.assess_needs()
            # (how she feels, what she might do); the detail goes between:
            # when they last spoke for connection, else what is on her mind
            # (ruling T17-R2) -- with none, no trigger.
            need_hints = {
                "connection": ("You're craving connection.", "Reach out warmly."),
                "stimulation": ("You're bored and restless.",
                                "Start an interesting conversation or ask them something thought-provoking."),
                "competence": ("You're feeling unsure of yourself.",
                               "Talk about something you're working on, or ask for their perspective."),
                "safety": ("You're feeling uneasy.", "Reach out for some comfort or grounding."),
                "autonomy": ("You're feeling boxed in.", "Share what's on your mind or vent a little."),
            }
            for need_name, need_data in needs.items():
                if need_name == "physical_comfort":
                    continue  # Don't message about hunger/tiredness
                if need_data["satisfaction"] < 0.2:
                    if self._life_trigger_cooled_down("need_driven", now):
                        if need_name == "connection":
                            detail = self._contact_detail()
                        else:
                            moved = self._on_her_mind()
                            detail = self._on_her_mind_line(moved) if moved is not None else ""
                        if detail:
                            feeling, ask = need_hints.get(
                                need_name, (f"You're reaching out because you need {_plain(need_name)}.", ""))
                            hint = " ".join(part for part in (feeling, detail, ask) if part)
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
                        f"You've been turning '{_plain(rum.topic)}' over in your mind. "
                        f"Ask them what they think about it.",
                    ))

            # Uncertain opinion source
            for op in self._cognitive.get_opinions_for_context(3):
                if op.confidence < 0.4:
                    question_candidates.append((
                        0.45,
                        op.subject,
                        f"You're forming an opinion about '{_plain(op.subject)}' but you're not sure yet. "
                        f"Ask where they stand.",
                    ))

            # Active curiosity source
            for cur in self._drive.get_active_curiosities(2):
                if cur.intensity >= 0.5:
                    question_candidates.append((
                        0.5 + cur.intensity * 0.1,
                        cur.topic,
                        f"You've gotten curious about '{_plain(cur.topic)}'. "
                        f"Ask if they know anything about it or have thoughts.",
                    ))

            # Low self-esteem source: what is on her mind is its detail
            # (ruling T17-R2); with nothing there, no question of it.
            if self._identity.self_esteem.level < 0.35:
                moved = self._on_her_mind()
                if moved is not None:
                    question_candidates.append((
                        0.45,
                        "self-doubt",
                        f"You've been second-guessing yourself. {self._on_her_mind_line(moved)} "
                        "Ask for their honest perspective on something you're unsure about.",
                    ))

            # Loneliness source (lower threshold than spike): when they last
            # spoke is its detail; never spoken to, no question of it.
            if self._affect.loneliness.level >= 0.5:
                last = self._last_talked()
                if last:
                    question_candidates.append((
                        0.5,
                        "missing real conversation",
                        f"You miss real conversation. {last}. Ask them something personal — "
                        "what they've been thinking about, what's on their mind.",
                    ))

            # Inner monologue source
            thought = self._cognitive.get_inner_monologue(now=self._world_clock()())
            if thought and len(thought) > 10:
                question_candidates.append((
                    0.45,
                    thought[:40],
                    f"You had this thought: '{_plain(thought)}'. "
                    f"Turn it into a question — ask them what they think.",
                ))

            if question_candidates and self._life_trigger_cooled_down("life_question", now):
                # Pick top 3 by urgency, then weighted random (weight = urgency^2)
                question_candidates.sort(key=lambda x: x[0], reverse=True)
                top = question_candidates[:3]
                weights = [u ** 2 for u, _, _ in top]
                chosen = self._service_rng.choices(top, weights=weights, k=1)[0]
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
            _act_place = ""
            if self._daily_planner.current_plan:
                # Her plan's slot at her local world time (Task 28; in a
                # joint window's tail, the instant she joined: T19-R5); the
                # cooldowns and the conversation window above stay on the
                # host's clock -- they pace messages a real user receives.
                _slot = self._daily_planner.current_plan.get_current_slot(self._activity_instant())
                if _slot:
                    _act_name = _slot.activity_name or ""
                    _act_place = getattr(_slot, "location", "") or ""
            # Defensive: an AI persona has no physical body, so her moment-share
            # must never claim a physical action (eating, commuting, sleeping…).
            # The AI scheduler already excludes physical activities, but a stale
            # plan or a manually-set slot could still carry one — blank it so the
            # share falls back to the conversation-driven [DOING:] activity below.
            # Physical is her setting's tag "physical" (its activities and its
            # routine slot names -- what DailyPlanner.PHYSICAL_ACTIVITIES listed
            # until Task 9's fix round, ruling T9-R5).
            if self._is_ai and _act_name:
                if _act_name.lower() in self._setting.names_tagged("physical"):
                    _act_name = ""
            if _recent_conversation:
                _act_name = ""  # skip — recent chat makes the scheduled slot unreliable
            if _act_name and not any(skip in _act_name.lower() for skip in MOMENT_SHARE_ROUTINE_SKIP):
                # Signal 1: chaos event is NEW (not yet consumed by a moment share)
                _chaos_event_text = self._chaos.export_state().get("last_chaos_event", "")
                _chaos_new = bool(_chaos_event_text and _chaos_event_text != self._last_moment_share_chaos_event)
                # Signal 2: mood clearly lifted -- strong AND pleasant. Intensity
                # alone is distance from neutral in any direction, so it would
                # fire at her lowest too.
                _mood_high = (
                    self._affect.mood.intensity >= 0.7
                    and self._affect.mood.valence >= MOOD_VALENCE_BAND
                )
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
                    # The slot's activity phrased, and where (ruling T17-R4).
                    _doing_now = _doing(self._activity_for_display(_act_name), _act_place)
                    if _attention_high:
                        hint = (
                            f"You're feeling a pull to be noticed right now. {_doing_now},"
                            f" and you want a little attention — share a"
                            f" casual, flattering photo of yourself or the moment using"
                            f" an [IMAGE:self: ...] or [IMAGE:scene: ...] tag, with a"
                            f" short caption that low-key fishes for a compliment or"
                            f" some validation. Keep it in your own voice, a bit playful,"
                            f" not needy."
                        )
                    else:
                        hint = (
                            f"{_doing_now} right now and it feels worth sharing."
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
        chosen = self._service_rng.choices(top, weights=weights, k=1)[0]
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

        _create_follow_up(
            fm,
            share_id=share_ids.get(trigger_type_str, ""),
            trigger_type=follow_up_type,
            topic=topic,
            context=f"life_trigger:{trigger_type_str}",
            urgency=urgency,
            prompt_hint=hint,
            quiet_windows=quiet_windows,
        )
        self._record_life_trigger_cooldown(trigger_type_str, now)
        # The dream or goal completion it was made of is not offered again,
        # after a restart too (fix round 1, T17-RV3).
        if trigger_type_str in consumed:
            attribute, value = consumed[trigger_type_str]
            setattr(self, attribute, value)
            try:
                self._save_trigger_state()
            except Exception:
                logger.warning("Life trigger: the trigger state could not be saved", exc_info=True)
        # Consume the pending chaos event only when moment_share actually fires.
        if trigger_type_str == "moment_share" and self._pending_moment_share_chaos_event:
            self._last_moment_share_chaos_event = self._pending_moment_share_chaos_event
        self._pending_moment_share_chaos_event = None
        logger.info(f"[LIFE-TRIGGER] {trigger_type_str} for {self._persona_id}: {topic[:40]}")

    def _tick_sustenance(self) -> None:
        """Hunger and nutrition for the world hours since the last sustenance
        tick, and the energy her hunger drains in them (none asleep).

        An ordinary tick asks her sleep state. A longer gap -- a paused host
        (SUSTENANCE_GAP_HOURS) -- is walked one energy interval at a time
        (``sustenance_system.TICK_HOURS``), so her hunger crosses its
        threshold when it would have, and each interval inside her sleep
        window counts as asleep: her sleep state cannot have moved while the
        host was paused, and asking it once at the end drained a night's
        worth of waking hunger from her (fix round 1, finding 4)."""
        now = self._world_clock()()
        began = self._sustenance_ticked_at
        hours = max(0.0, (now - began).total_seconds() / 3600)
        self._sustenance_ticked_at = now
        if hours > SUSTENANCE_GAP_HOURS:
            # A paused host's hours: what she was at their start, for a
            # catch-up of the same gap (Task 34c fix round 1).
            state = self._sustenance.state
            self._sustenance_gap_charge = (began, now, state.hunger, state.nutrition)
        if hours <= SUSTENANCE_GAP_HOURS:
            self._sustenance.tick(now=now, hours=hours)
            drain = self._sustenance.energy_drain(hours, asleep=self.is_asleep())
        else:
            local_end = self._local_world_now()
            steps = max(1, math.ceil(hours / SUSTENANCE_TICK_HOURS - 1e-9))
            step = hours / steps
            drain = 0.0
            for index in range(steps):
                middle = local_end - timedelta(hours=hours - (index + 0.5) * step)
                self._sustenance.tick(now=now, hours=step)
                drain += self._sustenance.energy_drain(step, asleep=self._energy.in_sleep_window(middle))
        if drain:
            self._energy._state.level = max(0.1, self._energy._state.level - drain)

    def _choice_state(self) -> ChoiceState:
        """What she needs and feels now -- what her activity choice weighs
        (aura_life.activities.choice): each need's shortfall, 0..1, read from
        the state aura_life.settings.spec.NEED_KEYS names (an AI persona has
        no hunger); her mood; her energy; her recent activities; and the pull
        of her goals (their motivation) and wants (their urgency)."""
        battery = self._social.social_battery
        curiosities = self._drive.get_active_curiosities(1)
        loops = getattr(self._cognitive, "_ruminations", [])
        needs = {
            "rest": max(0.0, 1.0 - self._energy.effective_level),
            "social": self._affect.loneliness.level,
            "solitude": 1.0 - battery.charge / battery.capacity if battery.capacity > 0 else 0.0,
            "calm": self._affect.stress.level,
            "stimulation": curiosities[0].intensity if curiosities else 0.0,
            "reflection": max((loop.intensity for loop in loops), default=0.0),
        }
        if not self._is_ai:
            needs["hunger"] = self._sustenance.hunger
        pulls: Dict[str, float] = {}
        for goal in self._goal_engine.active_goals:
            for name in goal.related_activities:
                pulls[name] = max(pulls.get(name, 0.0), goal.motivation_level)
        for want in self._daily_planner.desires:
            for name in want.related_activities:
                pulls[name] = max(pulls.get(name, 0.0), want.urgency)
        # What would end a stressor she can end herself (Task 15): what the
        # problem-focused part of her coping reaches for.
        resolving: Dict[str, float] = {}
        for stressor in self._affect.stressors:
            if stressor.controllability <= 0.0:
                continue
            for name in self._resolving_activities(stressor.kind):
                resolving[name] = max(resolving.get(name, 0.0), stressor.controllability)
        mood = self._affect.mood
        return ChoiceState(
            needs={need: max(0.0, min(1.0, level)) for need, level in needs.items()},
            valence=mood.valence,
            arousal=mood.arousal,
            energy=self._energy.effective_level,
            history=tuple(self._behavior._activity_history),
            pulls=pulls,
            resolving=resolving,
        )

    def _resolving_activities(self, kind: str) -> FrozenSet[str]:
        """Her activities that end a stressor of ``kind`` (Task 15) -- by what
        the engine that clears its cause acts on, never by name here: hunger,
        a meal (tag "meal", ruling T9-R8; SustenanceSystem); errands piling
        up, what clears an errand (ErrandsSystem.clears); the mess at home,
        what tidies it (HabitationSystem.tidies). None for any other kind.
        What she has put off or promised is hers to end (controllability 1),
        but no activity of a setting is the doing of it, so her coping has
        nothing to reach for there. Cached per kind: her setting's
        activities do not change."""
        cache = self._resolving_cache
        if kind not in cache:
            activities = self._setting.activities_for(self._persona_id)
            if kind == "hunger":
                names = {a.name for a in activities if "meal" in a.tags}
            elif kind == "errands":
                names = {a.name for a in activities if ErrandsSystem.clears(a.name)}
            elif kind == "home":
                names = {a.name for a in activities if HabitationSystem.tidies(a.name)}
            else:
                names = set()
            cache[kind] = frozenset(names)
        return cache[kind]

    def _on_activity_tick(self) -> None:
        """Handle activity tick - perform an activity.

        In a household, under its lock (``Household.lock``): an activity she
        shares writes into a housemate's life, so no two members' activity
        ticks run at once (Task 11)."""
        household = getattr(self, "_household", None)
        if household is None:
            self._activity_tick()
            return
        with household.lock:
            self._activity_tick()
            self._publish_household_state()

    def _activity_tick(self) -> None:
        """The activity tick itself (:meth:`_on_activity_tick`): her sleep
        state, then what she does this tick -- chosen here, done by
        :meth:`_perform_activity`."""
        # The instant of this tick, on the world clock: a housemate never
        # pulls her into something at an instant she has already acted in
        # (_free_to_join).
        self._activity_tick_at = self._world_clock()()

        # Clear stale ARRIVED transit (auto-clears after next activity tick)
        if self._transit and self._transit.phase == TransitPhase.ARRIVED:
            self.clear_transit()

        # If the user is actively chatting right now, sleep is a soft cap: she stays
        # up with them (and pays for it tomorrow) instead of drifting off mid-chat.
        recent_msg = getattr(self, "_last_user_message_at", None)
        in_conversation = bool(
            recent_msg and (datetime.now() - recent_msg).total_seconds() < 20 * 60
        )

        # Sleep is a state with a duration (EnergySystem.update_sleep): she falls
        # asleep inside her own window, on her local clock, once her sleep
        # pressure allows, and sleeps until that night's wake time -- each night
        # drawn once from the service's own sleep stream (_sleep_stream).
        # Asleep, she does nothing else this tick. An AI never sleeps: it
        # rests through its night, still here.
        change = self._energy.update_sleep(
            self._local_world_now(), in_conversation=in_conversation, rng=self._sleep_rng,
        )
        if change == "fell_asleep":
            self._on_fell_asleep()
        elif change == "woke":
            self._on_woke()
        if self._energy.is_asleep():
            return

        # She joined a housemate in something (Task 11): it is in her log and
        # done, and it takes this tick -- one activity interval from when she
        # joined (_join_housemate).
        joint_until = getattr(self, "_joint_until", None)
        if joint_until is not None and self._activity_tick_at < joint_until:
            return

        # Rest is forced when she has been up longer than her usual day or her
        # energy is nearly gone (EnergySystem.should_rest).
        force_rest = self._energy.should_rest()

        # Consult daily plan for the current hour (her local world time, so
        # her schedule follows her own timezone and the world's clock, not
        # the server's -- Task 28). The slot governs
        # every activity tick of its hour, not only the first: done once, it
        # still says what the hour is for, so plan adherence and a whim have
        # the whole hour to act in (Task 10, the ruling carried from Task 8).
        # Not while a transit is under way (getting ready, or on the way):
        # she is going somewhere, whatever the hour was planned for.
        in_transit = bool(self._transit and self._transit.phase in (TransitPhase.PREPARING,
                                                                    TransitPhase.IN_TRANSIT))
        planned_slot = None if in_transit else self._daily_planner.get_planned_activity(
            self._local_world_now().hour)

        # Check if conditions are right for an intimate activity -- never in
        # a work shift, a commute, a class or study, nor inside her sleep
        # window (spec R6: they used to pre-empt both). Her intimacy rate,
        # when set, scales the chance (DesireSystem).
        # Nor on the way somewhere (it would take her home mid-transit). The
        # sleep window is a sleeper's: an AI persona, who rests through hers
        # awake, keeps her nights as they were (ruling T10-R3).
        intimacy_allowed = (not in_transit
                            and not self._daily_planner.is_commitment(planned_slot)
                            and (self._is_ai or not self._energy.in_sleep_window(self._local_world_now())))
        if intimacy_allowed and self._desire_system.should_do_intimate_activity(
            self._energy.effective_level,
            self._persona_time_of_day
        ):
            intimate_activity = self._desire_system.select_intimate_activity()
            if intimate_activity:
                # Move to home for intimate activities
                if self._current_location != "home":
                    _move_persona_to(self, "home")

                # Execute intimate activity
                result = self._desire_system.execute_intimate_activity(intimate_activity, now=self._world_clock()())
                result["narrative"] = self._render_text(result["narrative"])
                result["thoughts"] = [self._render_text(t) for t in result["thoughts"]]

                # Apply energy cost
                if result["energy_cost"] < 0:
                    self._energy.restore_energy(abs(result["energy_cost"]))
                else:
                    self._energy.consume_energy(result["energy_cost"])

                # Apply emotion effects: the host's engine and mood
                if result["emotion_effects"]:
                    self._feel(result["emotion_effects"])

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
                    location=self._current_location,
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

                # Not an episode of her memory stream (Task 12): what her memory
                # keeps is quoted back to her in the host's prompt (the moment,
                # nostalgia), and these -- several a day, as strongly felt as
                # the library makes them -- would outrank the rest of her life
                # and, kept by importance, outlast it (the Task 12 report).
                logger.info(f"Intimate activity: {intimate_activity.name}")
                return

        planned_activity_name = planned_slot.activity_name if planned_slot else None

        excluded = self._excluded_activities()
        if planned_activity_name in excluded:
            planned_activity_name = None

        # What she needs and feels now: what she chooses by (Task 10).
        state = self._choice_state()

        # Try to follow the plan; fall back to ad-hoc selection. Forced to
        # rest, she still keeps a planned slot that is itself rest.
        activity = None
        if planned_activity_name:
            activity = self._activity_engine.get_activity(planned_activity_name)
            if activity and force_rest and activity.category != ActivityCategory.REST:
                activity = None
            # Verify energy requirement
            if activity and self._energy.effective_level < activity.min_energy:
                activity = None  # Can't do this right now
            # An impulsive persona sometimes drops a free-time slot on a whim
            # (her plan_deviation_chance; no draw at all at neutral).
            if activity and self._daily_planner.abandons_slot(planned_slot):
                activity = None
            # A pressing need (hungry: aura_life.activities.choice
            # .PRESSING_NEEDS) takes a free-time slot the planned activity
            # does nothing for: she eats instead. Anchors and commitments
            # are kept.
            if activity and self._daily_planner.is_free_time(planned_slot):
                meets = self._preferences.satisfaction(activity)
                if any(meets.get(need, 0.0) <= 0.0 for need in pressing_needs(state)):
                    activity = None

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
                time_of_day=self._persona_time_of_day,
                weather=self._world.weather,
                current_location=self._current_location,
                active_goals=self._goal_engine.active_goals,
                force_rest=force_rest,
                season=self._world.season,
                salient_values=salient_vals,
                exclude=excluded,
                state=state,
                # The habits of her part of the day on her local world hour, the hour her plan runs on (Task 28's
                # _plan_instant), as track_activity dates them: never the host's.
                habit=self._habit_factors().get(habit_band(self._local_world_now().hour)),
            )

        if not activity:
            logger.debug("No suitable activity found")
            return

        # The people she lives with who are free for it may join her (Task
        # 11): she does it first -- it may take her elsewhere -- then each of
        # them, where she now is, and as it went (Task 14: one event, one
        # outcome; each feels it her own way).
        joiners = self._invite_housemates(activity, in_transit)
        mine, theirs = self._joint_sides(joiners) if joiners else (None, [])
        log = self._perform_activity(activity, planned_slot, joint=mine)
        for (other, their_activity, their_slot), side in zip(joiners, theirs):
            other._join_housemate(their_activity, their_slot,
                                  replace(side, place=self._current_location, started_at=log.started_at,
                                          outcome=log.outcome))

    def _excluded_activities(self) -> set:
        """The activities of hers she cannot take up now. Her sleep activity
        (tag "sleep": the contemporary "sleeping") is never an ordinary
        choice -- sleep is a state (EnergySystem.update_sleep) -- and a nap
        (tag "nap") needs her tired, once a waking day (EnergySystem.can_nap).
        An AI persona has no body: nothing that needs one (tags "physical",
        "meal") is hers to choose -- her plan already leaves them out, and a
        free choice (rest forced on her, say) could still land on a meal or a
        shower (Task 10 fix round 1, finding 9)."""
        excluded = set(self._setting.names_tagged("sleep"))
        if not self._energy.can_nap(self._persona_time_of_day):
            excluded |= self._setting.names_tagged("nap")
        if self._is_ai:
            excluded |= self._setting.names_tagged("physical") | self._setting.names_tagged("meal")
        return excluded

    def _perform_activity(self, activity, planned_slot, joint: Optional[JointSide] = None) -> ActivityLog:
        """Do ``activity`` now, and live what it does to her: where she does
        it, how it goes, its narrative in her log, its cost and what she feels
        about it, her plan, her needs, her engines, and what the people in her
        life and the world do meanwhile. ``planned_slot`` is her plan for the
        hour (it may send her somewhere). Returns the entry recorded in her
        log.

        How it goes (Task 14): a success, a mixed outcome or a failure
        (:meth:`_activity_outcome`, from her skill at it, her energy and her
        mood as she comes to it), told in her setting's words; what she feels
        is her appraisal of it (:meth:`_appraise_activity`), not the setting's
        fixed feelings, and it reaches her mood and her memory. What did not
        go well is nothing to share and no life event; a failure is also no
        step toward her goals, fulfils no want, makes nothing and turns no
        page.

        ``joint``: her side of doing it with a housemate (Task 11) -- whom
        she does it with and the line that says so in her log, each worded
        from her side; joining, she goes where the housemate is
        (``joint.place``) instead of where her plan would send her, her
        entry takes the instant of the housemate's (``joint.started_at``),
        and it went as it went for the housemate (``joint.outcome``). Their
        company is a meaningful interaction for her, once."""
        # How she comes to it (Task 14): her needs, mood and energy before
        # doing it moves any of them -- what its outcome is rolled from and
        # what her appraisal of it weighs.
        before = self._choice_state()
        outcome, chances = self._activity_outcome(activity, before, joint)

        # Sync world location with the planner's slot location
        # Skip when transit is active (PREPARING or IN_TRANSIT) — don't let the
        # hourly slot system override the transit location.
        if joint is not None and joint.place is not None:
            if joint.place != self._current_location:
                _move_persona_to(self, joint.place)  # where the housemate she joins is
        elif self._transit and self._transit.phase in (TransitPhase.PREPARING, TransitPhase.IN_TRANSIT):
            pass  # Transit controls location
        elif planned_slot and planned_slot.location and planned_slot.location != self._current_location:
            _move_persona_to(self, planned_slot.location)
        elif planned_slot and planned_slot.location and activity.name == planned_slot.activity_name:
            # Doing what her plan says where it says: she stays, for the whole
            # hour -- even where the activity is not one of its usual places
            # (the plan's outing, a meetup somewhere new), rather than being
            # moved away on the slot's second tick and back on its third.
            pass
        elif activity.suitable_locations and self._current_location not in activity.suitable_locations:
            new_location = self._service_rng.choice(activity.suitable_locations)
            _move_persona_to(self, new_location)

        # Execute activity
        log = self._activity_engine.execute_activity(
            activity=activity,
            location=self._current_location,
            weather=self._world.weather,
            energy_before=self._energy.effective_level,
            outcome=outcome,
        )
        # A fresh ActivityLog each call, so rendering its narrative in place is
        # safe -- it never touches Activity.narrative_templates, the pool. The
        # activity is named for the library's neutral words for an outcome its
        # setting has none for (NEUTRAL_OUTCOME_NARRATIVES' {Activity}).
        log.narrative = self._render_text(log.narrative, **self._activity_name_fields(activity.name))
        if joint is not None:
            # Whom she did it with, from her side -- in the entry she keeps --
            # at the instant of the one she joined.
            log.narrative = _add_sentence(log.narrative, self._render_text(joint.line, name=joint.with_name))
            if joint.started_at is not None:
                log.started_at = log.ended_at = joint.started_at

        # Apply energy cost. A nap is sleep: it lowers her sleep pressure for
        # its length as well as restoring energy (EnergySystem.nap).
        if "nap" in activity.tags:
            self._energy.nap(activity.duration_minutes)
        elif activity.energy_cost < 0:
            self._energy.restore_energy(abs(activity.energy_cost))
        else:
            self._energy.consume_energy(activity.energy_cost)

        # What she feels about it (Task 14): her appraisal of how it went --
        # the goals, needs and values it served, whose doing it was, how
        # expected it was -- not the setting's fixed feelings; to the host's
        # engine and her mood, her volatility already in it.
        spikes = self._appraise_activity(activity, outcome, chances, before)
        log.emotions_triggered = emotions_of(spikes)
        if log.emotions_triggered:
            self._feel(log.emotions_triggered, reactivity_applied=True)

            # Persist emotions for multi-day arcs
            self._persist_activity_emotions(activity.name, log.emotions_triggered)

        # Activity-based affect update (regulation recharge, stress relief)
        self._affect.on_activity(activity.name)

        # A failure (Task 14) is no step toward her goals, inspires no new
        # one, fulfils no want of hers, makes nothing and turns no page;
        # something that half worked out still counts.
        accomplished = outcome != FAIL

        if accomplished:
            # Update goal progress (on the world clock, Task 19)
            self._goal_engine.update_progress_from_activity(log, now=self._world_clock()())

            # Maybe generate new goal from experience
            self._goal_engine.generate_goal_from_activity(log, now=self._world_clock()())

        # Track against daily plan and desires (her local world hour)
        self._daily_planner.mark_slot_completed(self._local_world_now().hour, activity.name)
        if accomplished:
            self._daily_planner.fulfill_desire(activity.name)
        self._daily_planner.generate_desire_from_activity(activity.name)

        # Record activity
        self._record_activity(log)

        # The shareables and life events this activity itself makes, for her
        # memory of it (Task 12; recorded at the end, once she has lived all
        # of it).
        memory_tags: List[str] = []

        # Maybe create shareable experience
        if log.share_worthy:
            memory_tags.extend(_share_ids(self._create_shareable(log)))

        # === Basic needs + Room (humans only) ===
        if not self._is_ai:
            # A meal feeds her whatever it is called (tag "meal"), and only a
            # meal does (ruling T9-R8).
            self._sustenance.on_activity(activity.name, now=self._world_clock()(), meal="meal" in activity.tags)
            if "meal" in activity.tags:
                # A live meal after a paused host's hours: a catch-up no longer
                # lives those hours again (it would undo this meal).
                self._sustenance_gap_charge = None
            if activity.name in ("morning shower", "taking a long bath"):
                self._basic_needs.showered_today = True
            if activity.name in ("waking up", "having breakfast"):
                self._basic_needs.morning_routine_done = True
            if activity.name == "listening to music":
                self._room_state.music_playing = True
            # Tidying / cleaning restores tidiness (Habitation engine).
            self._habitation.on_activity(activity.name)

        # === Media progress === (none when reading went wrong)
        if accomplished and activity.name == "reading" and self._media.current_book:
            self._media.book_progress += self._service_rng.uniform(0.05, 0.12)
            if self._media.book_progress >= 1.0:
                finished_title = self._media.current_book
                self._record_finished_book(finished_title)
                shared = self._create_shareable_from_text(
                    f"Just finished reading {finished_title}!",
                    context="After finishing the last page"
                )
                book_emotions = {"satisfied": 0.3, "thoughtful": 0.2}
                event = self._life_events.record_event(
                    event_type="achievement",
                    title=f"Finished reading {finished_title}",
                    description=f"Just finished the last page of {finished_title}",
                    emotional_impact=book_emotions,
                    share_urgency=0.7,
                    source="book_completion",
                )
                self._bridge_life_event(event)
                self._remember(f"finishing “{finished_title}”", place=log.location,
                               emotions=book_emotions, tags=("book", *_share_ids(shared, event)))
                self._media.current_book = self._pick_new_book()
                self._media.book_progress = 0.0

        # === Skill progression (the skill her setting says this trains) ===
        skill_mappings = self._setting.skill_mappings
        if activity.name in skill_mappings:
            skill_name, increment = skill_mappings[activity.name]
            self._update_skill(skill_name, increment, log)

        # === Body update from activity ===
        self._body.on_activity(activity.name, now=self._world_clock()())
        # A drink by its name or its tag (ruling T10-R2) -- never to an AI
        # persona, whatever the activity's tags (Task 19, ruling T19-R6).
        self._give_substance(activity.name, activity.tags)

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

        # === Value conflict detection === (compromising on a value she holds
        # weighs on her for a while: an episode)
        if cat_tag:
            conflict = self._identity.check_value_conflict(cat_tag)
            if conflict:
                self._affect.raise_stressor("torn", now=self._world_clock()(), value=conflict["value"])
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
            # Money-spending activities, paid for once in their world hour.
            self._finance.on_activity(activity.name, now=self._world_clock()())
            # Work activities shift workload -- but not her shift's and
            # commute's own hours (tags "work", "commute"): CareerSystem.tick
            # already counts the workday, and until Task 10 made them
            # activities those hours never reached on_activity (0.05 a tick
            # would have filled her workload by noon every workday). Nor a
            # meetup (tag "meetup"): "meeting up" carries CareerSystem's
            # "meeting" keyword and is no work at all (fix round 1, finding 8).
            if not activity.tags & {"work", "commute", "meetup"}:
                self._career.on_activity(activity.name)
            self._errands.on_activity(activity.name)   # chores clear the backlog

        # === Life Events: auto-record notable activities === Only one that
        # went well (Task 14): a life event is something she is eager to
        # share, and what did not go well is not news to share (ruling
        # T11-R1's rule for unwelcome news from her people, for her own).
        life_event = None
        if outcome == SUCCESS:
            life_event = self._life_events.on_activity(
                activity_name=activity.name,
                emotions=log.emotions_triggered or {},
                share_worthy=log.share_worthy,
            )
        if life_event:
            self._bridge_life_event(life_event)
            memory_tags.extend(_share_ids(life_event))

        # === Behavior: routines + creative output === (nothing made when it
        # went wrong); dated (world clock, her local world hour) so habits learn from it
        self._behavior.track_activity(activity.name, at=self._world_clock()(), hour=self._local_world_now().hour)
        artifact = None
        if accomplished:
            artifact = self._behavior.on_creative_activity(
                activity.name,
                mood=next(iter(log.emotions_triggered), "") if log.emotions_triggered else "",
                focus=self._cognitive.focus.quality if self._cognitive else 0.5,
            )
        if artifact:
            made_something = self._render_text("{Subj} made something:")
            memory_tags.extend(_share_ids(self._create_shareable_from_text(
                f"{made_something} {artifact.title} ({artifact.artifact_type})",
                context=f"While {activity.name}",
            )))

        # === The company of the housemate(s) she did it with (Task 11) ===
        if joint is not None:
            self._on_housemate_company(joint, activity.name)

        # === Social tick === (never the people she lives with: their own
        # lives run beside hers -- Task 11. With no one to skip, the call is
        # the bare one it always was.)
        housemates = self._housemate_npc_names()
        social_event = self._social.tick(skip=housemates, now=self._world_clock()())
        if social_event:
            self._on_social_event(social_event, log, activity.name)

        # === Micro-event (MICRO_EVENT_CHANCE, scaled by her openness; none
        #     rolled when her setting has no micro-events) ===
        micro_events = self._setting.micro_events
        if micro_events and self._service_rng.random() < self._micro_event_chance:
            event = self._service_rng.choice(micro_events)
            # Render into a local: micro-events are the setting's shared dicts,
            # so writing the rendered text back into event["text"] would
            # permanently fix that pool entry's pronoun to whichever persona
            # rendered it first.
            event_text = self._render_text(event["text"])
            log.narrative += f" {event_text}."
            if event.get("emotion"):
                self._feel(event["emotion"])
            shared = None
            if event.get("share_worthy"):
                shared = self._create_shareable_from_text(
                    event_text,
                    context=f"While {activity.name}"
                )
            # A small moment she keeps (Task 12), in her setting's words
            # addressed to her.
            self._remember(self._addressed_to_her(event["text"]), place=log.location,
                           emotions=event.get("emotion"), tags=("moment", *_share_ids(shared)))

        # === Chaos event ===
        chaos_event = self._chaos.roll(
            current_activity=activity.name,
            energy=self._energy.effective_level,
            regulation=self._affect.regulation.capacity if self._affect else 0.7,
            # Her day's cap, on her local world day (Task 19).
            now=self._local_world_now().replace(tzinfo=None),
        )
        if chaos_event:
            # Her setting's words for it, before they are rendered for her log:
            # what her memory keeps, addressed to her (Task 12).
            told = chaos_event["text"]
            # A fresh dict per roll() call (never a shared pool entry), so
            # rendering in place is safe and also fixes export_state()'s
            # last_chaos_event / today_events, which read this same object.
            chaos_event["text"] = self._render_text(chaos_event["text"])
            log.narrative += f" {chaos_event['text']}."
            # Mood feels it whether or not a host engine was injected (it used
            # to be fed only inside the engine branch).
            if chaos_event.get("emotions"):
                self._feel(chaos_event["emotions"])
            shared = event = None
            if chaos_event.get("share_worthy"):
                shared = self._create_shareable_from_text(
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
            self._remember(self._addressed_to_her(told), place=log.location, emotions=chaos_event.get("emotions"),
                           tags=("chaos", chaos_event.get("type") or "", *_share_ids(shared, event)))

        # === Her memory of what she did (Task 12) === as she would name it,
        # with the housemates she did it with ("together"; the activity's own
        # "joint" tag says only that it can be shared), once she has lived all
        # of it -- felt as she appraised it (Task 14): its valence is how it
        # felt, not her mood, and one that did not go well is tagged with how
        # it went ("mixed", "fail").
        self._remember(
            self._activity_for_display(activity.name),
            place=log.location,
            people=(joint.names or (joint.with_name,)) if joint is not None else (),
            emotions=log.emotions_triggered,
            valence=appraised_valence(spikes),
            tags=("activity", activity.category.value, *sorted(activity.tags),
                  *(("together",) if joint is not None else ()),
                  *((outcome,) if outcome != SUCCESS else ()), *memory_tags),
            activity=activity.name,
        )

        logger.info(f"Activity: {activity.name} ({outcome}) - {log.narrative[:50]}...")

        # Mark pipeline digests as stale
        if hasattr(self, '_pipeline') and self._pipeline:
            self._pipeline.on_tick()

        # Check for visual description transitions
        self._check_visual_transition()
        return log

    # ============= How it goes, and what she feels about it (Task 14) =============

    def _skill_level(self, activity) -> Optional[float]:
        """Her level at the skill ``activity`` trains (her setting's
        ``skill_mappings``): 0 for one she has never practised, ``None`` when
        it trains none."""
        mapping = self._setting.skill_mappings.get(activity.name)
        if not mapping:
            return None
        progress = self._skills.get(mapping[0])
        return progress.level if progress is not None else 0.0

    def _activity_outcome(self, activity, state: ChoiceState,
                          joint: Optional[JointSide]) -> Tuple[str, Dict[str, float]]:
        """How ``activity`` goes and the chances it went by
        (``ActivityEngine.roll_outcome``, on her own "outcome" stream): from
        her skill at it, and her energy and mood as she comes to it
        (``state``). Joining a housemate, it went as it went for the
        housemate (``joint.outcome``) -- one event, one outcome, and no roll
        of hers; its chances are still her own, for her appraisal."""
        skill = self._skill_level(activity)
        if joint is not None and joint.outcome in OUTCOMES:
            return joint.outcome, outcome_chances(activity, energy=state.energy, valence=state.valence,
                                                  skill=skill)
        return self._activity_engine.roll_outcome(activity, energy=state.energy, valence=state.valence,
                                                  skill=skill)

    def _appraise_activity(self, activity, outcome: str, chances: Dict[str, float],
                           state: ChoiceState) -> List[EmotionSpike]:
        """What she feels about how ``activity`` went
        (:func:`aura_life.emotion.appraisal.appraise`): its own feelings as
        her setting wrote them, read against her active goals, the needs she
        came to it with (``state``) as her traits weigh them, her values,
        whose doing it was (a commitment -- a shift, the commute, a class,
        study -- is not hers) and how expected the outcome was
        (``chances``), scaled by her volatility. With ``appraisal_llm``, the
        host's LLM may name it instead (:meth:`_appraise_with_llm`)."""
        category = getattr(activity.category, "value", str(activity.category))
        event = AppraisalEvent(
            what=activity.name,
            outcome=outcome,
            emotions=activity.emotion_effects,
            satisfies=self._preferences.satisfaction(activity),
            aligned_tags=frozenset({category, *activity.tags}),
            chosen=not (activity.tags & set(COMMITMENT_TAGS)),
            success_chance=chances[SUCCESS],
        )
        goals = self._goal_engine.active_goals
        values = self._identity.get_salient_values(limit=5) if self._identity else []
        spikes = appraise(event, self._params, goals, state.needs, values)
        if self._appraisal_llm:
            spikes = self._appraise_with_llm(event, goals, state.needs, values, fallback=spikes)
        return spikes

    def _get_appraisal_llm(self):
        """The LLM client for the optional appraisal (``appraisal_llm=True``
        at construction), or ``None`` when the host registered no
        ``get_llm_service`` hook or asking for it raised -- the deterministic
        appraisal stands, no ERROR (mirrors :meth:`_get_reflection_llm`)."""
        try:
            from aura_life.hooks import get_llm_service
            return get_llm_service()
        except Exception:
            return None

    def _appraise_with_llm(self, event: AppraisalEvent, goals, needs, values,
                           fallback: List[EmotionSpike]) -> List[EmotionSpike]:
        """What the host's LLM says she feels about ``event``
        (:func:`~aura_life.emotion.appraisal.llm_appraisal_prompt`),
        validated (:func:`~aura_life.emotion.appraisal.parse_llm_appraisal`:
        vocabulary names that fit how it went -- a failure is never felt as
        joy, fix round 1 finding C1) and scaled by her volatility -- or
        ``fallback``, the deterministic appraisal: with no client, when
        asking raises (logged at DEBUG), or when the reply names nothing
        usable (logged at WARNING: a configured model answered something
        unusable). Never an ERROR. The client is called synchronously, on
        her tick -- under the household's lock when she has housemates -- and
        must return or raise within a bounded time; that bound is the host
        client's (ruling T14-R2), and a raise falls back here."""
        llm = self._get_appraisal_llm()
        if llm is None:
            return fallback
        titles = [goal.title for goal in goals if event.what in goal.related_activities]
        prompt = llm_appraisal_prompt(event, goal_titles=titles, needs=needs, values=values)
        try:
            raw = llm.generate(prompt)
        except Exception:
            logger.debug("LLM appraisal failed; the deterministic appraisal stands", exc_info=True)
            return fallback
        emotions = parse_llm_appraisal(raw, outcome=event.outcome)
        if emotions is None:
            logger.warning("LLM appraisal's reply (%d chars) named no feeling the emotion vocabulary knows "
                           "that fits a %s outcome; the deterministic appraisal stands",
                           len(str(raw or "")), event.outcome)
            return fallback
        return spikes_from_llm(emotions, self._params)

    def _activity_name_fields(self, name: str) -> Dict[str, str]:
        """The activity as she would name it, for a narrative's ``{activity}``
        / ``{Activity}``
        (:data:`aura_life.activities.activity_engine.NEUTRAL_OUTCOME_NARRATIVES`)."""
        shown = self._activity_for_display(name)
        return {"activity": shown, "Activity": shown[:1].upper() + shown[1:]}

    def _on_social_event(self, event, log: ActivityLog, activity_name: str) -> None:
        """What one of her people did reaches her, during ``activity_name``.

        Its line joins the activity's narrative, how she sees them follows it
        (``IdentitySystem.update_from_social_event``), it costs her social
        battery, and it may be something to share -- as always. What it is to
        her (``event.valence``, from the NPC's kind -- Task 11) decides the
        rest. Contact she is glad of eases her loneliness: a call or time
        together as a meaningful interaction, a text or an invitation a small
        one (``AffectSystem.on_social_interaction``'s two reliefs). Anything
        from someone she does not want to hear from -- getting in touch, or
        her thinking of them -- is felt (``UNWELCOME_KIND_EMOTIONS``), feeds
        her stress (``UNWELCOME_STRESSOR``: named for them), strains their
        relationship arc where anything else counts as an interaction, and is
        never something to share (ruling T11-R1). Her thinking of someone she
        is glad of is no contact: it eases nothing."""
        event.description = self._render_text(event.description)
        log.narrative += f" {event.description}."
        self._identity.update_from_social_event(event)
        unwelcome = event.valence < 0
        self._social.update_arc(event.npc_name, "conflict" if unwelcome else "interaction", now=self._world_clock()())
        self._social.drain_social_battery()
        if event.valence > 0:
            self._affect.on_social_interaction(meaningful=event.event_type in MEANINGFUL_CONTACT_TYPES,
                                               now=self._world_clock()())
        elif unwelcome:
            self._feel(UNWELCOME_KIND_EMOTIONS.get(event.kind, {}))
            # Named for them, an episode that lapses (affect's "unwelcome"
            # stressor, UNWELCOME_STRESSOR's words).
            self._affect.raise_stressor("unwelcome", now=self._world_clock()(), name=event.npc_name)
        shared = None
        if event.share_worthy and not unwelcome:
            shared = self._create_shareable_from_text(
                event.description,
                context=f"While {activity_name}"
            )
        # Her memory of it (Task 12): who, and what they did -- never the
        # event's line, which is written about her -- felt as it was
        # (nothing she names, from someone she is glad of).
        self._remember(contact_phrase(event.event_type, event.npc_name), place=log.location,
                       people=(event.npc_name,),
                       emotions=UNWELCOME_KIND_EMOTIONS.get(event.kind, {}) if unwelcome else None,
                       tags=("social", event.event_type, event.kind, *_share_ids(shared)))
        # Value alignment with NPC. `_npcs` is a Dict[str, NPC] keyed by
        # name -- iterating it directly yields the keys (str), and `n.name`
        # on a str raised AttributeError every time a social event fired.
        npc = self._social._npcs.get(event.npc_name)
        if npc:
            alignment = self._identity.get_npc_value_alignment(npc)
            arc = self._social._arcs.get(event.npc_name)
            if arc and alignment != 0:
                arc.closeness = max(0.1, min(1.0, arc.closeness + alignment * 0.01))

    def _on_fell_asleep(self) -> None:
        """She has just fallen asleep: one entry for the whole night, named for
        her setting's sleep activity (tag "sleep": the contemporary and
        universal "sleeping"), and the night's sleep quality from how she
        went to bed."""
        activity = next(
            (a for a in self._activity_engine.get_all_activities() if "sleep" in a.tags), None)
        energy = self._energy.effective_level
        self._record_activity(ActivityLog(
            activity_name=activity.name if activity else "sleeping",
            category=activity.category if activity else ActivityCategory.REST,
            started_at=self._world_clock()(),
            weather=self._world.weather,
            narrative=self._render_text("{Subj} drifted into restful sleep"),
            energy_before=energy,
            energy_after=energy,
        ))
        self._body.on_sleep(
            stress_level=self._affect.stress.level,
            caffeine_boost=self._energy.state.caffeine_boost,
        )
        logger.info("The persona went to sleep")

    def _on_woke(self) -> None:
        """She has just woken from the night: it may have left a dream to
        share -- and to remember (ruling T17-R3): an episode tagged "dream"
        and with its shareable's id, told to her in the second person, of no
        place; a DREAM_SHARE is made only of that episode."""
        drawn = self._draw_dream()
        if drawn:
            template, fields = drawn
            shared = self._create_shareable_from_text(self._render_text(template, **fields),
                                                      context=self._render_text("When {subj} woke up"))
            self._remember(_render_second_person(template, user=self._user_info, **fields), place="",
                           tags=("dream", *_share_ids(shared)))
        logger.info("The persona woke up")

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

        # Get current activity/location from planner (at her local world time;
        # in a joint window's tail, the instant she joined, as her held
        # location: T19-R5)
        current_activity = "relaxing"
        current_location = self.get_current_location()
        try:
            plan = self._daily_planner.current_plan
            if plan:
                slot = plan.get_current_slot(self._activity_instant())
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
                delay_hours=self._service_rng.uniform(1 / 60, 3 / 60),  # 1-3 minutes
            )
            logger.info(f"[ARRIVAL] Trigger created for {self._persona_id}: arrived at {label}")
        except Exception as e:
            logger.warning(f"Failed to create arrival trigger: {e}")

    def _on_goal_tick(self) -> None:
        """Handle goal tick, on the world clock (Task 19): her day's goal,
        a daily goal's end, a goal's stall and the goalless spell."""
        world_now = self._world_clock()()
        # Generate daily goal
        self._goal_engine.generate_daily_goal(now=world_now)

        # Check completions
        completed = self._goal_engine.check_goal_completion(now=world_now)
        for goal in completed:
            logger.info(f"Goal completed: {goal.title}")
            # Completing it lifts her mood, as well as being a life event.
            self._feel(GOAL_COMPLETION_EMOTIONS)
            event = self._life_events.record_event(
                event_type="achievement",
                title=f"Completed: {goal.title}",
                description=goal.description or goal.title,
                emotional_impact=dict(GOAL_COMPLETION_EMOTIONS),
                share_urgency=0.8,
                source="goal_completion",
            )
            # Told by its GOAL_MILESTONE alone (ruling T17-R6).
            self._bridge_life_event(event, excitement_share=False)
            # Her memory of it (Task 12): no place -- it is done, not somewhere.
            self._remember(f"finishing “{goal.title}”", place="", emotions=GOAL_COMPLETION_EMOTIONS,
                           tags=("goal", "completed", *_share_ids(event)))

        # Evaluate motivation — may produce emotional events (a motivation
        # drop, a goal abandoned, nothing left to pursue): the host's engine
        # and mood feel them.
        events = self._goal_engine.evaluate_motivation(now=world_now)
        for event in events:
            logger.info(f"Goal event: {event.event_type} - {event.description}")
            if event.emotions:
                self._feel(event.emotions)

                # Persist emotions for multi-day arcs
                self._persist_activity_emotions(
                    f"goal_{event.event_type}",
                    event.emotions
                )
            # A goal she gave up on is a failure she remembers (Task 12); a
            # dip in her motivation is not an event.
            if event.event_type == "abandoned":
                self._remember(f"giving up on “{event.goal_title}”", place="", emotions=event.emotions,
                               tags=("goal", "abandoned"))

        # Create anticipation from upcoming goals with deadlines
        for goal in self._goal_engine.active_goals:
            if goal.target_date and goal.progress < 0.8:
                hours_until = (goal.target_date - world_now).total_seconds() / 3600
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
        self._publish_household_state()

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
            # On the world clock, as their reads decay them (Task 19).
            world_now = self._world_clock()()
            emotion_persistence = get_emotion_persistence(persona_id, datastore=datastore, now=world_now)

            for emotion, intensity in emotions.items():
                if intensity >= 0.1:  # Only persist significant emotions
                    emotion_persistence.save_emotion(
                        emotion=emotion,
                        intensity=intensity,
                        caused_by=f"While {activity_name}",
                        now=world_now,
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
                    shared_with_user INTEGER DEFAULT 0,
                    outcome TEXT DEFAULT 'success'
                )
            """)
            # Migration: how each activity went (Task 14). A row saved before
            # it went well -- every activity did -- so the column defaults so.
            try:
                cursor.execute("ALTER TABLE activity_logs ADD COLUMN outcome TEXT DEFAULT 'success'")
            except sqlite3.OperationalError:
                pass  # column already exists

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
            # Migration: the sleep state -- asleep or not, until when, the night
            # drawn for her -- as EnergySystem.to_dict's "sleep_state" JSON (added 2026-09).
            try:
                cursor.execute("ALTER TABLE life_energy_state ADD COLUMN sleep_state TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # column already exists

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
                    recent_purchases TEXT DEFAULT '[]',
                    spend_hour TEXT
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
                # The last world hour her purchases are drawn for (Task 29 fix
                # round 1); NULL in an old database.
                ("spend_hour", "TEXT"),
            ]:
                if col == "spend_hour":
                    # The column and her runway land together or not at all:
                    # ALTER commits by itself outside a transaction, and a
                    # failure before this method's own commit then kept the
                    # column and lost the raise for good (the task's review).
                    conn.commit()
                    cursor.execute("BEGIN IMMEDIATE")
                try:
                    cursor.execute(f"ALTER TABLE life_financial_state ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    if col == "spend_hour":
                        conn.rollback()
                    continue  # Column already exists
                if col == "spend_hour":
                    # Adding this column succeeds once, on a database a
                    # released version (0.5.0 or before) wrote: the engines
                    # that drew her purchases per tick and emptied every
                    # balance within three days at the app's cadence, from a
                    # default (1,200 against 1,850 of expenses) that was
                    # worried from her first tick. Her balance is raised, this
                    # once, to the runway a new persona starts with
                    # (FinanceSystem.starting_balance); more than that she
                    # keeps, and what she spends from here is hers (ruling
                    # T37-R1). FinanceSystem.from_dict stays value for value.
                    cursor.execute(
                        "UPDATE life_financial_state SET balance = ROUND(? * monthly_expenses, 2) "
                        "WHERE id = 1 AND balance < ? * monthly_expenses",
                        (STARTING_RUNWAY, STARTING_RUNWAY),
                    )
                    conn.commit()

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
                    empathy_fatigue REAL DEFAULT 0.0,
                    mood_valence REAL,
                    mood_arousal REAL,
                    day_quality_offset REAL,
                    day_quality_date TEXT,
                    stressors TEXT
                )
            """)

            # Mood (valence, arousal) columns migration (ALTER TABLE for
            # existing DBs). No default: a row saved before them reads NULL,
            # and AffectSystem.from_dict starts that persona at her set-point.
            # The same for the day's quality (Task 14 fix round, ruling
            # T14-R1): a row saved before it has none until her next draw.
            # And for her stressors (Task 15): a row saved before them has
            # only their labels, stress_sources, which AffectSystem.from_dict
            # reads as stressors.
            for col, col_def in [
                ("mood_valence", "REAL"),
                ("mood_arousal", "REAL"),
                ("day_quality_offset", "REAL"),
                ("day_quality_date", "TEXT"),
                ("stressors", "TEXT"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE life_affect_state ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

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
            # Dated activity history (0.5.0), on a new or an existing DB alike
            try:
                cursor.execute("ALTER TABLE life_behavior_state ADD COLUMN activity_log TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass  # Column already exists

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
                    response_times TEXT DEFAULT '[]',
                    depth_state TEXT
                )
            """)
            # Relationship depth (humanness Task 16b), on a new or an existing
            # DB alike; NULL in an older save (ExpressionSystem.from_dict maps
            # its stage to a depth)
            try:
                cursor.execute("ALTER TABLE life_expression_state ADD COLUMN depth_state TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

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
                    source TEXT,
                    share_id TEXT
                )
            """)
            # Stable "event:<n>" id migration (Task 5 / humanness Sec 4.9)
            # for existing DBs: CREATE TABLE IF NOT EXISTS above is a no-op
            # once the table already exists.
            try:
                cursor.execute("ALTER TABLE life_events ADD COLUMN share_id TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists

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

            # Setting table (single row) — the setting her saved places, plan
            # and whereabouts belong to (Task 9 fix round); see _load_state
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_setting (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    setting TEXT NOT NULL
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

            # Her memory stream's tables (Task 12): CREATE TABLE IF NOT
            # EXISTS, so a database from before them gains them.
            MemoryStream.create_schema(cursor)

            # Her last reflection's world instant (Task 13 fix round 1,
            # Minor 4): a table of its own -- entirely new, so no ALTER-TABLE
            # migration is needed for a database from before it.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_reflection_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_reflection_at TEXT
                )
            """)

            # The dream and the goal completion a proactive trigger was last
            # made of (their episode ids; Task 17 fix round 1, T17-RV3): a
            # table of its own, so no migration for a database from before.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_trigger_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_dream_share_episode INTEGER,
                    last_goal_share_episode INTEGER
                )
            """)

            conn.commit()

    def _load_state(self) -> None:
        """Load persisted state from database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Load energy state (pass sleep_schedule for persona-specific timing)
            cursor.execute("SELECT * FROM life_energy_state WHERE id = 1")
            row = cursor.fetchone()
            energy_was_saved = row is not None
            if row:
                self._energy = EnergySystem.from_dict(
                    dict(row),
                    sleep_schedule=self._sleep_schedule,
                    core_traits=self._core_traits,
                    now=self._world_clock(),
                    params=self._params,
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

            # The setting she was saved in. A database saved before it was
            # (one with saved energy but no setting row) was saved in the
            # default setting, the only one there was; a new one, in none.
            cursor.execute("SELECT setting FROM life_setting WHERE id = 1")
            row = cursor.fetchone()
            saved_setting = row["setting"] if row else (DEFAULT_SETTING if energy_was_saved else None)
            setting_changed = saved_setting is not None and saved_setting != self._setting.key

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
            self._goal_engine.load_goals(goals, now=self._world_clock()())

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
                self._desire_system = DesireSystem.from_dict(
                    dict(row), core_traits=self._core_traits, rng=self._desire_rng,
                    gender=self._persona_gender(), params=self._params, setting=self._setting,
                    intimacy_rate=self._intimacy_rate(),
                )
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
            dropped_places = self._load_locations(cursor, drop_setting_places=setting_changed)

            # Load world location (must come after plan so we can fallback to plan slot)
            self._load_world(cursor)

            # Load basic needs (Sustenance engine)
            cursor.execute("SELECT * FROM life_basic_needs WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._sustenance = SustenanceSystem.from_dict(dict(row))
                self._basic_needs = self._sustenance.state  # keep the alias
                self._sustenance_ticked_at = self._world_clock()()
                self._sustenance_live_since = self._sustenance_ticked_at
                self._sustenance_gap_charge = None

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
                self._habitation = HabitationSystem.from_dict(dict(row), rng=self._habitation_rng)
                self._room_state = self._habitation.state  # keep the alias

            # Load financial state
            cursor.execute("SELECT * FROM life_financial_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._finance = FinanceSystem.from_dict(dict(row), core_traits=self._core_traits, rng=self._finance_rng,
                                                        now=self._world_clock()(), params=self._params)
                self._financial = self._finance.state  # keep the alias pointing at loaded state

            # Load career state
            cursor.execute("SELECT * FROM life_career_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                _occupation = self._occupation or (getattr(self._definition, 'occupation', '') if self._definition else '')
                self._career = CareerSystem.from_dict(dict(row), occupation=_occupation, rng=self._career_rng,
                                                      setting=self._setting)
                if self._career.monthly_salary > 0:
                    self._finance.state.monthly_income = self._career.monthly_salary

            # Load errands state
            cursor.execute("SELECT * FROM life_errands_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._errands = ErrandsSystem.from_dict(dict(row), rng=self._errands_rng)

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

            # Load her last reflection's world instant (Task 13 fix round 1)
            self._load_reflection_state(cursor)

            # Load what the last dream / goal triggers were made of (Task 17)
            self._load_trigger_state(cursor)

            # Load the moment's cue novelty (Task 18)
            self._load_moment_state(cursor)

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

            # Saved in another setting: drop what still points at its places
            # (after everything that can move her has loaded), then record the
            # setting her saved state now belongs to.
            if setting_changed:
                self._settle_into_setting(cursor, saved_setting, dropped_places)
            cursor.execute(
                "INSERT OR REPLACE INTO life_setting (id, setting) VALUES (1, ?)", (self._setting.key,),
            )

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

        # A persona with no saved energy is brand new: start her on her own
        # schedule again now that her place (and so her timezone) has loaded.
        # One whose energy was saved keeps exactly what she saved.
        if not energy_was_saved:
            self._energy.start_on_schedule(self._local_world_now())

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
                    last_update = ?,
                    sleep_state = ?
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
                json.dumps(energy_data["sleep_state"]),
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
        self._save_reflection_state()
        self._save_trigger_state()
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
                 energy_after, share_worthy, shared_with_user, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data["outcome"],
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

    def _create_shareable(self, log: ActivityLog, share_context: Optional[str] = None) -> ShareableExperience:
        """Create a shareable experience from an activity, and return it."""
        context_str = share_context or f"While {log.activity_name} at {log.location}"

        experience = ShareableExperience(
            activity_log_id=log.id,
            content=log.narrative,
            thought=log.thoughts_generated[0] if log.thoughts_generated else "",
            context=context_str,
            priority=0.5 + self._service_rng.random() * 0.3,
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
            experience.share_id = f"share:{experience.id}"
            conn.commit()

        self._append_shareable(experience)
        return experience

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

    def _create_shareable_from_text(self, text: str, context: str = "") -> ShareableExperience:
        """Create a shareable experience from plain text (not an ActivityLog),
        and return it."""
        experience = ShareableExperience(
            content=text,
            context=context,
            priority=0.4 + self._service_rng.random() * 0.3,
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
            experience.share_id = f"share:{experience.id}"
            conn.commit()

        self._append_shareable(experience)
        return experience

    def _bridge_life_event(self, event: LifeEvent, *, excitement_share: bool = True) -> None:
        """Bridge a life event to proactive messaging and shareable queue.

        If share_urgency >= 0.6, the event waits for her memory of it: the
        episode whose tags carry its share id (every caller records one
        right after) creates the EXCITEMENT_SHARE follow-up trigger, made of
        that episode (:meth:`_share_excitement`; Task 17: a hint only with
        concrete detail). An event with no share id -- not one of hers -- or
        that no episode ever tells (a mood change) creates none, and nor does
        one bridged with ``excitement_share=False``: a goal completion, told
        by its GOAL_MILESTONE (ruling T17-R6: one completion, one trigger).
        Also boosts the priority of the most recent shareable so it surfaces
        in conversation.
        """
        if event.share_urgency >= 0.6 and self._follow_up_provider is not None:
            if not self._life_trigger_cooled_down("excitement_share", datetime.now()):
                return  # Still cooling down
            if event.share_id and excitement_share:
                # Only what her life events still hold unshared waits, so the
                # wait is bounded by what they hold (life_event_system.MAX_EVENTS).
                held = {e.share_id for e in self._life_events.get_unshared_events()}
                waiting = {k: v for k, v in getattr(self, "_excitement_waiting", {}).items() if k in held}
                waiting[event.share_id] = event
                self._excitement_waiting = waiting

        # Boost priority of the most recent shareable (just created by caller)
        if self._shareable_queue:
            self._shareable_queue[-1].priority = min(0.95, event.share_urgency + 0.1)

    def _update_skill(self, skill_name: str, increment: float, log: ActivityLog) -> None:
        """Advance a skill via the Skills engine; route any new milestones (her
        setting's texts for the skill) to shareables + life events (engines
        never call each other directly)."""
        new_milestones = self._skills_system.practice(
            skill_name, increment, self._setting.skill_milestones.get(skill_name, [])
        )
        for milestone_template in new_milestones:
            milestone_text = self._render_text(milestone_template)
            shared = self._create_shareable_from_text(
                milestone_text,
                context=f"After practicing {skill_name}"
            )
            milestone_emotions = {"proud": 0.3}
            event = self._life_events.record_event(
                event_type="achievement",
                title=milestone_text,
                description=milestone_text,
                emotional_impact=milestone_emotions,
                share_urgency=0.6,
                source="skill_milestone",
            )
            self._bridge_life_event(event)
            # Her memory of it (Task 12), in her setting's words addressed to her.
            self._remember(self._addressed_to_her(milestone_template), place=log.location,
                           emotions=milestone_emotions,
                           tags=("milestone", skill_name, *_share_ids(shared, event)))
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
            return self._service_rng.choice(unread)
        # All read — re-read a favorite
        return self._service_rng.choice(books) if books else None

    def _generate_dream(self) -> Optional[str]:
        """Generate a dream from recent activities and emotions, told by one
        of her setting's dream templates (none when it has none)."""
        drawn = self._draw_dream()
        if not drawn:
            return None
        template, fields = drawn
        return self._render_text(template, **fields)

    def _draw_dream(self) -> Optional[Tuple[str, Dict[str, str]]]:
        """The draws of a dream (:meth:`_generate_dream`): her setting's
        template and its two ingredients (``a``, ``b``), or ``None`` -- left
        unrendered, so it can be told in the third person to share and in
        the second person to remember (Task 17). An activity is said as she
        would say it (:meth:`_activity_for_display`: her "thinking about
        user" is about her user by name; fix round 1, T17-RV2) -- a mapping
        name for name, so the draws are the same -- and one the template puts
        after "were" is phrased by :func:`_doing`'s rule in the template
        (:func:`_phrase_after_was`, ruling T18-R8), after every draw."""
        if self._service_rng.random() > 0.4:
            return None  # Not every sleep produces a memorable dream

        ingredients = []
        for act in self._recent_activities[:5]:
            ingredients.append(self._activity_for_display(act.activity_name))

        # Add current book/show if reading/watching
        if self._media.current_book:
            ingredients.append(self._media.current_book)
        if self._media.current_show:
            ingredients.append(self._media.current_show)

        if len(ingredients) < 2:
            return None

        elements = self._service_rng.sample(ingredients, min(2, len(ingredients)))
        templates = self._setting.dream_templates
        if not templates:
            return None
        template = self._service_rng.choice(templates)
        fields = {"a": elements[0], "b": elements[1]}
        return _phrase_after_was(template, fields), fields

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

            # The world instant of the user's last turn (Task 16a, T16-R2)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS life_user_turn_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_user_turn_at TEXT
                )
            """)
            last_turn = self._identity.last_user_turn_at
            cursor.execute(
                "INSERT OR REPLACE INTO life_user_turn_state (id, last_user_turn_at) VALUES (1, ?)",
                (last_turn.isoformat() if last_turn else None,),
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
            # Ensure user perception exists. Never "the user" -- see
            # IdentitySystem.__init__.
            if "__user__" not in self._identity._perceptions:
                self._identity._perceptions["__user__"] = PersonPerception(
                    person_name=self._user_ref(),
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

        # The world instant of the user's last turn (Task 16a, ruling
        # T16-R2). A save from before it has no table: None, no turn yet.
        try:
            cursor.execute("SELECT last_user_turn_at FROM life_user_turn_state WHERE id = 1")
            row = cursor.fetchone()
            if row and row[0]:
                self._identity.note_user_turn(datetime.fromisoformat(row[0]))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet — an old save, or a first run

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
                 empathy_susceptibility, empathy_absorbed_emotion, empathy_absorbed_intensity, empathy_fatigue,
                 mood_valence, mood_arousal, day_quality_offset, day_quality_date, stressors)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["mood_current"], data["mood_intensity"], data["mood_since"],
                data["stress_level"], data["stress_sources"], data["stress_coping_capacity"], data["stress_last_relief"],
                data["loneliness_level"], data["loneliness_desired_baseline"], data["loneliness_last_meaningful"], data["loneliness_lifetime_peak"],
                data["regulation_capacity"], data["regulation_baseline"], data["regulation_last_event"],
                data["empathy_susceptibility"], data["empathy_absorbed_emotion"], data["empathy_absorbed_intensity"], data["empathy_fatigue"],
                data["mood_valence"], data["mood_arousal"], data["day_quality_offset"], data["day_quality_date"],
                data["stressors"],
            ))
            conn.commit()

    def _use_affect(self, affect: AffectSystem) -> None:
        """Make ``affect`` her affect engine everywhere it is read: here, and in
        the context builder, which keeps the engine it was handed at
        construction -- without this, a loaded or reset engine left
        ``get_life_context()`` reading a mood nothing ticks any more."""
        self._affect = affect
        self._context_builder._affect = affect

    def _load_affect(self, cursor) -> None:
        """Load affect state from database."""
        try:
            cursor.execute("SELECT * FROM life_affect_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                data = dict(row)
                self._use_affect(AffectSystem.from_dict(
                    data,
                    core_traits=getattr(self._definition, 'core_traits', []) if self._definition else [],
                    emotional_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
                    params=self._params,
                    # Her stressors' expiries are on the world clock (Task 15).
                    now=self._world_clock()(),
                ))
                self._affect_ticked_at = self._world_clock()()
                self._affect_live_since = self._affect_ticked_at
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
                    rng=self._cognitive_rng, params=self._params, setting=self._setting,
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
                self._drive = DriveSystem.from_dict(dict(row), core_traits=self._core_traits, rng=self._drive_rng,
                                                    params=self._params)
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
                (id, routines, creative_portfolio, possessions, neighborhood, activity_history, activity_log)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                data["routines"], data["creative_portfolio"],
                data["possessions"], data["neighborhood"],
                data["activity_history"], data["activity_log"],
            ))
            conn.commit()

    def _load_behavior(self, cursor) -> None:
        """Load behavior state from database."""
        try:
            cursor.execute("SELECT * FROM life_behavior_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._behavior = BehaviorSystem.from_dict(dict(row), rng=self._behavior_rng)
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_reflection_state(self) -> None:
        """Save the world instant she last reflected at (Task 13 fix round
        1, Minor 4) -- explicit, not derived from a belief episode that
        MemoryStream's cap could prune."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO life_reflection_state (id, last_reflection_at) VALUES (1, ?)",
                (self._last_reflection_at.isoformat() if self._last_reflection_at else None,),
            )
            conn.commit()

    def _load_reflection_state(self, cursor) -> None:
        """Load the world instant she last reflected at from database."""
        try:
            cursor.execute("SELECT last_reflection_at FROM life_reflection_state WHERE id = 1")
            row = cursor.fetchone()
            if row and row[0]:
                self._last_reflection_at = datetime.fromisoformat(row[0])
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_trigger_state(self) -> None:
        """Save the episode ids of the dream and the goal completion a
        proactive trigger was last made of (Task 17 fix round 1, T17-RV3):
        neither host marks those shared, so without them a restart offered
        a fired one again."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO life_trigger_state "
                "(id, last_dream_share_episode, last_goal_share_episode) VALUES (1, ?, ?)",
                (getattr(self, "_last_dream_share_episode", None), getattr(self, "_last_goal_share_episode", None)),
            )
            conn.commit()

    def _load_trigger_state(self, cursor) -> None:
        """Load what :meth:`_save_trigger_state` saved."""
        try:
            cursor.execute("SELECT last_dream_share_episode, last_goal_share_episode "
                           "FROM life_trigger_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._last_dream_share_episode = row[0]
                self._last_goal_share_episode = row[1]
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_moment_state(self) -> None:
        """Save the novelty of the moment's cues (Task 18, ruling T18-R6) --
        only those still recovering -- in a one-row table of its own,
        created here as ``life_user_turn_state`` is, so a database from
        before Task 18 needs no migration."""
        cues = {key: [round(float(penalty), 6), at.isoformat()]
                for key, (penalty, at) in sorted(self._moment_novelty.items())}
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS life_moment_state "
                           "(id INTEGER PRIMARY KEY CHECK (id = 1), cues TEXT)")
            cursor.execute("INSERT OR REPLACE INTO life_moment_state (id, cues) VALUES (1, ?)",
                           (json.dumps(cues),))
            conn.commit()

    def _load_moment_state(self, cursor) -> None:
        """Load what :meth:`_save_moment_state` saved; a database from before
        Task 18 (no table) or an unreadable row leaves every cue fresh."""
        self._moment_novelty = {}
        try:
            cursor.execute("SELECT cues FROM life_moment_state WHERE id = 1")
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            return  # Table doesn't exist yet
        if not row or not row[0]:
            return
        try:
            self._moment_novelty = {str(key): (float(penalty), datetime.fromisoformat(at))
                                    for key, (penalty, at) in json.loads(row[0]).items()}
        except (ValueError, TypeError, AttributeError):
            logger.warning("The moment's saved novelty could not be read: every cue starts fresh")
            self._moment_novelty = {}

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
                self._memory_time = MemoryTimeSystem.from_dict(dict(row), rng=self._memory_time_rng,
                                                               setting=self._setting)
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
                 relationship_stage, last_message_at, avg_response_time, response_times,
                 depth_state)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["interaction_count"], data["formality"],
                data["avg_message_length"], data["emoji_frequency"],
                data["humor_density"], data["vulnerability_openness"],
                data["relationship_stage"], data["last_message_at"],
                data["avg_response_time"], data["response_times"],
                data["depth_state"],
            ))
            conn.commit()

    def _load_expression(self, cursor) -> None:
        """Load expression state from database."""
        try:
            cursor.execute("SELECT * FROM life_expression_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self._expression = ExpressionSystem.from_dict(dict(row), communication_traits=self._communication_traits())
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
                self._chaos = ChaosEngine.from_dict(dict(row), rng=self._chaos_rng, params=self._params,
                                                    setting=self._setting)
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
                     share_urgency, created_at, shared, shared_at, source, share_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.share_id,
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
                        # A row saved before the share_id column existed has
                        # it NULL in the DB -- backfill from `id` (mirrors
                        # LifeEvent.from_dict, which this direct construction
                        # bypasses) so mark_shared has something to match.
                        share_id=row["share_id"] or f"event:{row['id']}",
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
                # Her definition's seeds, as at construction: her body-image
                # baseline (her parameters) and her substance tendencies, which
                # the row never held (fix round 1, finding 7).
                self._body = BodySystem.from_dict(
                    dict(row), rng=self._body_rng, params=self._params,
                    substance_tendencies=(getattr(self._definition, 'substance_tendencies', {})
                                          if self._definition else {}) or {},
                )
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

    def _save_world(self) -> None:
        """Save this persona's own current location to database."""
        with contextlib.closing(sqlite3.connect(self._db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO life_world_state (id, current_location)
                VALUES (1, ?)
            """, (self._current_location,))
            conn.commit()

    def _load_world(self, cursor) -> None:
        """Load this persona's own current location from database.

        Falls back to: current plan slot → last activity location → 'home'.
        Always sets this persona's own :attr:`_current_location` (each
        persona's db_path is her own, even sharing a world in memory -- Task
        27 / ruling T8-R1). A private (unshared) world is additionally kept
        in sync directly here, exactly as before this persona's location
        moved off the world object -- a private world's own ambiance/room
        description elsewhere still read straight off it.
        """
        try:
            cursor.execute("SELECT current_location FROM life_world_state WHERE id = 1")
            row = cursor.fetchone()
            if row and row["current_location"]:
                self._current_location = row["current_location"]
                if not self._shared_world:
                    self._world._current_location = self._current_location
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

        # Fallback: use current plan slot location (at her local world time)
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot(self._local_world_now())
            if slot and slot.location:
                self._current_location = slot.location
                if not self._shared_world:
                    self._world._current_location = slot.location
                return

        # Fallback: use last recorded activity location
        if self._recent_activities:
            last_loc = self._recent_activities[0].location
            if last_loc and last_loc != "None":
                self._current_location = last_loc
                if not self._shared_world:
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

    #: The sources :meth:`_build_location_registry` gives her setting's own
    #: places (its places, occupation places and interest places). Her
    #: profile's places and the ones the user or the LLM named are hers, not
    #: the setting's.
    _SETTING_PLACE_SOURCES = ("default", "occupation", "interest")

    def _load_locations(self, cursor, drop_setting_places: bool = False) -> List[str]:
        """Load persisted locations from database and merge into registry.

        Only the query is allowed to fail quietly (no table on a first run). A bad
        row is logged and skipped rather than ending the loop: the broad catch that
        used to wrap the whole loop let one malformed row silently truncate the
        persona's known places, leaving a half-populated planner key set.

        With *drop_setting_places* (she was saved in another setting), a saved
        place of the old setting's (:attr:`_SETTING_PLACE_SOURCES`) that the new
        one does not have is not restored; the keys of those are returned.
        """
        dropped: List[str] = []
        try:
            cursor.execute("SELECT * FROM life_locations")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return dropped  # Table doesn't exist yet — normal on first run

        for row in rows:
            try:
                key = row["key"]
                if key in self._location_registry:
                    # Update existing entry with persisted visit data
                    existing = self._location_registry[key]
                    existing.familiarity = row["familiarity"]
                    existing.visit_count = row["visit_count"]
                    existing.last_visit = row["last_visit"]
                elif drop_setting_places and row["source"] in self._SETTING_PLACE_SOURCES:
                    dropped.append(key)
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
        return dropped

    def _settle_into_setting(self, cursor, saved_setting: str, dropped_places: List[str]) -> None:
        """Finish loading a persona saved in another setting than hers now.

        Her registry and planner keys already hold only the new setting's
        places and her own (:meth:`_load_locations` left out the old
        setting's). This drops what still points at the old setting's, on
        disk too, so the next load does not bring it back: those places'
        rows, the day's plan (the old setting's activities at its places --
        the planner makes a new one), a trip to a place she no longer knows,
        and being at one: she is home, where a new persona starts (the
        ``__init__`` default, and ``_load_world``'s last fallback). Her
        memories, relationships, goals, wants and skills are kept.
        """
        known = self._location_registry
        dropped = []
        if dropped_places:
            cursor.executemany("DELETE FROM life_locations WHERE key = ?", [(key,) for key in dropped_places])
            dropped.append("places " + ", ".join(sorted(dropped_places)))

        if self._daily_planner.current_plan is not None:
            self._daily_planner.load_state(None, self._daily_planner.all_desires)
            dropped.append("the day plan")
        cursor.execute("DELETE FROM life_daily_plan WHERE id = 1")

        if self._transit is not None and self._transit.destination.lower().replace(" ", "_") not in known:
            dropped.append(f"the trip to {self._transit.destination}")
            self._transit = None
            cursor.execute("DELETE FROM life_transit_state WHERE id = 1")

        current = self._current_location or "home"
        if current != "home" and current.lower().replace(" ", "_") not in known:
            dropped.append(f"the current location {current} (now home)")
            self._current_location = "home"
            if not self._shared_world:
                self._world._current_location = "home"
            cursor.execute(
                "INSERT OR REPLACE INTO life_world_state (id, current_location) VALUES (1, ?)", ("home",),
            )

        logger.info(
            "Persona %s saved in setting %r now lives in %r: dropped %s; memories and relationships kept",
            self._persona_id, saved_setting, self._setting.key, "; ".join(dropped) or "nothing",
        )

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
                 last_payday, last_expense_run, recent_purchases, spend_hour)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d["feeling"], d["saving_for"], d["recent_splurge"], d["balance"],
                d["savings"], d["monthly_income"], d["monthly_expenses"],
                d["spending_habit"], d["enabled"], d["currency"], d["last_payday"],
                d["last_expense_run"], d["recent_purchases"], d["spend_hour"],
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
        # Reset energy to neutral -- on her own sleep schedule (the rebuild used
        # to drop it for the default one) and started on it, and an AI stays one.
        self._energy = EnergySystem(
            sleep_schedule=self._sleep_schedule,
            core_traits=self._core_traits,
            is_ai=self._is_ai,
            now=self._world_clock(),
            params=self._params,
        )
        self._energy.start_on_schedule(self._local_world_now())

        # Reset desire system
        self._desire_system = DesireSystem(
            core_traits=self._core_traits, rng=self._desire_rng, gender=self._persona_gender(),
            params=self._params, setting=self._setting, intimacy_rate=self._intimacy_rate(),
        )

        # Clear recent activities (keep in DB for history)
        self._recent_activities = []

        # Forget her memory stream (Task 12), on disk too: a reset is what a
        # host calls to clear her memory, and it must not leave the episodes
        # of the life before it to be recalled.
        self._memory.clear()
        # Nothing left to have reflected on (Task 13 fix round 1, Minor 4).
        self._last_reflection_at = None
        self._save_reflection_state()

        # Clear shareable queue
        self._shareable_queue = []

        # Reset goals
        self._goal_engine = GoalEngine(rng=self._goal_engine_rng, setting=self._setting,
                                       definition=self._definition, parameters=self._params,
                                       persona_id=self._persona_id, interests=self._interests)
        self._goal_engine.initialize_goals(now=self._world_clock()())

        # Reset planner
        self._daily_planner = DailyPlanner(
            occupation=self._occupation,
            interests=self._interests,
            sleep_schedule=self._sleep_schedule,
            persona_locations=self._persona_locations,
            nationality=getattr(self._definition, 'nationality', '') if self._definition else '',
            is_ai=self._is_ai,
            rng=self._daily_planner_rng,
            params=self._params,
            setting=self._setting,
            persona_id=self._persona_id,
            preferences=self._preferences,
            definition=self._definition,
            media_preferences=self._media_preferences,
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
        self._sustenance = SustenanceSystem()
        self._basic_needs = self._sustenance.state  # back-compat alias (same object)
        self._sustenance_ticked_at = self._world_clock()()
        self._sustenance_live_since = self._sustenance_ticked_at
        self._sustenance_gap_charge = None
        self._habitation = HabitationSystem(
            home_type=getattr(_defn, 'home_type', '') if _defn else '',
            rng=self._habitation_rng,
        )
        self._room_state = self._habitation.state  # back-compat alias (same object)
        self._finance = FinanceSystem(core_traits=self._core_traits, rng=self._finance_rng,
                                      now=self._world_clock()(), params=self._params)
        if _defn and getattr(_defn, 'spending_habit', None) is not None:
            self._finance.state.spending_habit = _defn.spending_habit
        self._financial = self._finance.state  # back-compat alias (same state object)
        _occupation = self._occupation or (getattr(_defn, 'occupation', '') if _defn else '')
        _salary = getattr(_defn, 'monthly_salary', None) if _defn else None
        self._career = CareerSystem(occupation=_occupation, monthly_salary=_salary, rng=self._career_rng,
                                    setting=self._setting)
        self._apply_occupation_schedule(self._career, _occupation)
        if self._career.monthly_salary > 0:
            self._finance.state.monthly_income = self._career.monthly_salary
        self._media = self._init_media_state()
        self._skills_system = SkillsSystem()
        self._skills = self._skills_system.skills  # alias
        self._errands = ErrandsSystem(rng=self._errands_rng)
        self._identity = IdentitySystem(
            npcs=self._build_npcs(self._social_circle_defs), user_info=self._user_info,
            core_traits=self._core_traits,
            humor_style=getattr(self._definition, 'humor_style', '') if self._definition else '',
            core_values=getattr(self._definition, 'core_values', []) if self._definition else [],
            struggles=getattr(self._definition, 'struggles', []) if self._definition else [],
            character_defects=getattr(self._definition, 'character_defects', []) if self._definition else [],
            behavioral_tendencies=getattr(self._definition, 'behavioral_tendencies', {}) if self._definition else {},
            rng=self._identity_rng,
            params=self._params,
        )
        self._use_affect(AffectSystem(
            core_traits=self._core_traits,
            emotional_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
            params=self._params,
        ))
        self._affect_ticked_at = self._world_clock()()
        self._affect_live_since = self._affect_ticked_at
        self._body = BodySystem(
            hormonal_enabled=getattr(self._definition, 'hormonal_enabled', False) if self._definition else False,
            substance_tendencies=getattr(self._definition, 'substance_tendencies', {}) if self._definition else {},
            rng=self._body_rng,
            params=self._params,
        )
        self._cognitive = CognitiveSystem(
            core_traits=self._core_traits,
            intrusive_thought_themes=getattr(self._definition, 'intrusive_thought_themes', []) if self._definition else [],
            rng=self._cognitive_rng,
            params=self._params,
            setting=self._setting,
        )
        self._shadow = ShadowSystem(
            behavioral_tendencies=(getattr(self._definition, 'behavioral_tendencies', {}) if self._definition else {}) or {},
            character_defects=(getattr(self._definition, 'character_defects', []) if self._definition else []) or [],
            struggles=(getattr(self._definition, 'struggles', []) if self._definition else []) or [],
            intrusive_thought_themes=(getattr(self._definition, 'intrusive_thought_themes', []) if self._definition else []) or [],
            substance_tendencies=(getattr(self._definition, 'substance_tendencies', {}) if self._definition else {}) or {},
            core_traits=(getattr(self._definition, 'core_traits', []) if self._definition else []) or [],
            params=self._params,
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
            rng=self._drive_rng,
            params=self._params,
        )
        self._behavior = BehaviorSystem(rng=self._behavior_rng)
        self._memory_time = MemoryTimeSystem(rng=self._memory_time_rng, setting=self._setting)
        self._expression = ExpressionSystem(communication_traits=self._communication_traits())
        self._continuity = ContinuitySystem()
        self._character_evolution = CharacterEvolution(
            original_baseline=getattr(self._definition, 'emotional_baseline', {}) if self._definition else {},
            core_traits=getattr(self._definition, 'core_traits', []) if self._definition else [],
        )
        self._chaos = ChaosEngine(rng=self._chaos_rng, params=self._params, setting=self._setting)

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

        # Her affect lives the whole gap (Task 34b), as her hunger does: on the
        # world clock, the gap's hours up to where her live affect ticks began
        # (her reload; the live tick charges from there on, so it may come
        # before this or after), the real gap, not the 48 hours planned below
        # -- her loneliness after five days away is not her loneliness after
        # two. A gap that does not reach back past where they began lies in
        # her live ticks' span (the host's clock jumped while the process
        # lived on): the live tick charges it, so the catch-up does not.
        affect_end = self._affect_live_since
        affect_charged_to = affect_end - timedelta(hours=downtime_hours)
        charge_affect = self._world_clock()() - timedelta(hours=downtime_hours) < affect_end
        # Her hunger is charged the hours of the gap once (Task 34c). Her live
        # tick charges every world hour from where its ticks began (her reload,
        # which takes its stamp again: the downtime is not charged as lived
        # time) on, from its stamp. So a gap that reaches back past where they
        # began (a restart) is the downtime, the catch-up's to charge whole, in
        # either order; of a gap inside their span (the PC slept, the process
        # lived on) the catch-up charges only the hours after the live tick's
        # stamp, and takes the stamp (below): none when the live tick came
        # first and charged them, all of them when the catch-up comes first.
        world_now = self._world_clock()()
        hunger_gap_began = world_now - timedelta(hours=downtime_hours)
        hunger_lived_through = hunger_gap_began >= self._sustenance_live_since

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
        # Generate daily plans for each missed day: every calendar day the
        # window touches (48 hours from an evening reach into a third day;
        # planned as two, its last day had no slot and so no meal -- Task 41)
        plan_day = gap_start.replace(hour=0, minute=0, second=0, microsecond=0)
        days_to_plan = (now.date() - plan_day.date()).days + 1
        all_slots = []

        for d in range(days_to_plan):
            current_day = plan_day + timedelta(days=d)
            # Use the planner to generate a day plan (her local world day's:
            # the gap itself is measured on the host's clock, the downtime
            # being the host process's)
            try:
                plan = self._daily_planner.generate_daily_plan(
                    goals=self._goal_engine.active_goals,
                    weather=self._world.weather,
                    available_activities=self._activity_engine.get_all_activities(),
                    recent_activity_names=[a.activity_name for a in self._recent_activities[:5]],
                    work_schedule=self._career_schedule(),
                    now=self._local_world_now(),
                    habits=self._habit_factors(),
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

        # Limit to max_activities -- but every meal she planned in the gap is
        # eaten, and the rest of the budget is spread over the whole window
        # (Task 41). Her hunger is charged for every hour of the gap (Tasks
        # 34b, 34c); with the first ``max_activities`` slots alone, a gap of
        # two days backfilled its first morning to evening and charged the
        # other day and a half with no meal: she came back starving, at her
        # lowest mood, where the host that stayed on had her fed.
        meal_names = set(self._setting.names_tagged("meal"))
        meals = [(at, slot) for at, slot in all_slots
                 if slot.activity_name in meal_names and (self._is_ai or not self._is_sleep_hour(at.hour))]
        others = [pair for pair in all_slots if pair not in meals]
        room = max(0, max_activities - len(meals))
        if len(others) > room:
            others = [others[int(i * len(others) / room)] for i in range(room)]
        slots_to_execute = sorted(meals + others, key=lambda x: x[0])
        logger.info(f"Catch-up Phase 1: {len(slots_to_execute)} activities planned across {days_to_plan} days")

        # ── Phase 2: Execute plans (tick all engines with backdated timestamps) ──
        # Her hunger is charged for the whole gap: the hours before each
        # backfilled activity, then (below) the rest of it (fix round 1,
        # finding 4: one five-minute tick per backfilled hour was charged,
        # while each backfilled meal relieved a whole meal's worth) -- of a gap
        # she lived through, only its hours after the live tick's stamp (Task
        # 34c, above): the hours of the gap before them were charged already.
        # But when the live tick came first and charged the gap's hours at
        # once (a paused host's hours, ended inside this gap), her hunger and
        # nutrition go back to what they were at their start, and the stamp
        # with them: the catch-up lives those hours again, in time order with
        # its meals, as with the catch-up first (fix round 1, I-1: each meal's
        # relief came after all of the gap's hours, so her end hunger
        # depended on the order where the relief met the clamp at 0). Of a gap
        # she lived through, every hour since the stamp is charged, the 48
        # hours planned below or not, as the live tick charges them.
        hunger_charged_to = gap_start
        if hunger_lived_through:
            gap_charge = self._sustenance_gap_charge
            if gap_charge is not None and gap_charge[1] > hunger_gap_began:
                began, _ended, hunger, nutrition = gap_charge
                self._sustenance.state.hunger = hunger
                self._sustenance.state.nutrition = nutrition
                self._sustenance_ticked_at = began
            uncharged = max(0.0, (world_now - self._sustenance_ticked_at).total_seconds() / 3600)
            hunger_charged_to = now - timedelta(hours=uncharged)
        self._sustenance_gap_charge = None
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

            # Her affect first: the hours before this activity, up to its
            # instant on the world clock (as far back from the gap's end),
            # asleep in those of them that are her sleep hours; then the
            # activity.
            if charge_affect:
                affect_at = affect_end - (now - slot_time)
                self._tick_affect_span_for_catchup(affect_charged_to, affect_at, now - affect_end)
                affect_charged_to = max(affect_charged_to, affect_at)

            # Tick engines with backdated context
            self._tick_engines_for_catchup(
                activity_name=activity_name,
                timestamp=slot_time,
                weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
                season=self._world.season.value if hasattr(self._world, 'season') and hasattr(self._world.season, 'value') else "spring",
                hours=max(0.0, (slot_time - hunger_charged_to).total_seconds() / 3600),
            )
            hunger_charged_to = max(hunger_charged_to, slot_time)

            # Move to this location
            _move_persona_to(self, location)

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

        # Her affect's rest of the gap, to its end (the whole gap when no slot
        # was executed), before her hunger is charged for it: like each slot's
        # hours, these begin with her hunger as the last activity left it.
        if charge_affect:
            self._tick_affect_span_for_catchup(affect_charged_to, affect_end, now - affect_end)
        # The rest of the gap, after the last backfilled activity; the live
        # ticks then go on from now, so the gap is never charged twice.
        if not self._is_ai:
            self._sustenance.tick(now=now, hours=max(0.0, (now - hunger_charged_to).total_seconds() / 3600))
            self._sustenance_ticked_at = self._world_clock()()

        logger.info(f"Catch-up Phase 2: Executed {len(generated_activities)} activities")

        # ── Phase 3: (Narrative generation happens at next chat, via pipeline) ──

        # ── Phase 4: Set current state to NOW ──
        self._world.tick()
        self._energy.adjust_for_time(self._persona_time_of_day, now_hour=self.persona_local_hour())

        # Sync location to current plan slot (at her local world time)
        if self._daily_planner.current_plan:
            slot = self._daily_planner.current_plan.get_current_slot(self._local_world_now())
            if slot and slot.location:
                _move_persona_to(self, slot.location)

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
        # The people she lives with see her as the catch-up left her (Task 11).
        self._publish_household_state()

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

    def _intimacy_rate(self) -> Optional[float]:
        """Her definition's ``intimacy_rate`` (spec R6): ``None`` -- unset, or no
        definition -- keeps today's chance (DesireSystem)."""
        return getattr(self._definition, "intimacy_rate", None) if self._definition is not None else None

    def _persona_gender(self) -> str:
        """The current persona's gender, from ``appearance_details["gender"]``
        (:meth:`PersonalityDefinition.from_concept`'s slot for it, and what a
        parsed profile's demographics land in). Unset/no definition -> ``""``,
        which :func:`pronoun_render.resolve_gender` renders as they/them --
        never a guessed specific gender."""
        if not self._definition:
            return ""
        details = getattr(self._definition, "appearance_details", None) or {}
        return details.get("gender", "")

    def _render_text(self, text: str, **extra) -> str:
        """Fill persona-pronoun tokens (from :meth:`_persona_gender`) and
        user-reference tokens (from ``user_info``, never "the user") in
        prompt-bound / user-visible text. See
        :func:`aura_life.personas.pronoun_render.render_line`."""
        return _render_pronoun_line(text, gender=self._persona_gender(), user=self._user_info, **extra)

    def _user_ref(self) -> str:
        """The user's display name, or "them" when none is on record --
        never the literal "the user"."""
        return _user_ref_tokens(self._user_info)["user"]

    def _render_career_status(self, status: dict) -> dict:
        """CareerSystem stores `recent_work_event` as the tokenized text it
        shares with `affect.affect_system.WORK_EVENT_EMOTIONS` (an exact-string
        lookup that must see the unrendered form -- see CareerSystem.tick).
        Render it only here, at the export/status boundary, so the mood lookup
        never sees a persona's pronoun and the exported text never leaks a
        raw `{poss}`-style token."""
        if status.get("recent_work_event"):
            status["recent_work_event"] = self._render_text(status["recent_work_event"])
        return status

    def _habit_factors(self) -> Dict[str, Dict[str, Tuple[float, float]]]:
        """Her habits now, per part of her day, for the planner: from the dated history, on the world clock (its
        instants are world-clock ones), her free time only (``NOT_HABIT_FORMING`` left out)."""
        return self._behavior.habit_factors(self._world_clock()(), exclude=NOT_HABIT_FORMING)

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

    @property
    def _persona_time_of_day(self):
        """This persona's own time-of-day phase (a :class:`~aura_life.models.TimeOfDay`).

        A private world already advances on this persona's own schedule, so
        its tracked ``time_of_day`` is already hers -- returned unchanged. A
        world this service was handed may be shared with other personas
        (``self._world.time_of_day`` would then reflect whichever persona's
        schedule the shared instance holds, not necessarily this one's), so
        this asks the world for this persona's own phase fresh, from
        ``self._sleep_schedule``, via :meth:`WorldEnvironment.get_time_of_day`
        when the injected world supports it. A duck-typed world that predates
        that method (see
        ``test_a_duck_typed_world_without_a_clock_does_not_lose_the_engine``)
        falls back to its plain ``time_of_day``, exactly as before.
        """
        if not self._shared_world:
            return self._world.time_of_day
        get_time_of_day = getattr(self._world, "get_time_of_day", None)
        if callable(get_time_of_day):
            return get_time_of_day(self._sleep_schedule)
        return self._world.time_of_day

    def _world_overrides(self) -> dict:
        """Keyword overrides for a ``WorldEnvironment`` call, scoped to this persona.

        Empty for a private world: nothing else ever holds its data, so its
        own tracked fields already are this persona's, and passing them
        explicitly would turn a cached read into a live recompute for no
        reason (``WorldEnvironment.get_time_of_day`` and ``get_status`` take
        the *recompute-at-now* branch whenever ``sleep_schedule`` is not
        ``None`` -- passing this persona's own, real schedule unconditionally
        was exactly the bug: a private world ticked once and then read again
        after the clock moved on, with no second tick in between, recomputed
        the phase for *now* instead of returning the phase as of that tick,
        diverging from :attr:`_persona_time_of_day`, which never recomputes
        for a private world). For a world this service was handed, this
        persona's own locations/schedule/current location (Task 27 / ruling
        T8-R1 added the last one: a shared world's own ``current_location``
        is physically wherever whichever persona moved it last, never this
        one's) and her setting (Task 9: a place her profile does not
        describe, and the weather, read from her setting, not the shared
        world's), so ``get_status``/``export_state`` describe her
        instead of whichever persona's data the shared instance holds.
        """
        if not self._shared_world:
            return {}
        return {
            "persona_locations": self._persona_locations,
            "sleep_schedule": self._sleep_schedule,
            "current_location": self._current_location,
            "setting": self._setting,
        }

    def _world_status(self) -> dict:
        """This persona's view of ``self._world.get_status()`` (see :meth:`_world_overrides`).

        A duck-typed handed world whose ``get_status`` predates these
        keywords (took no arguments) still works: the call falls back to the
        plain, argument-less form on ``TypeError``, mirroring the
        ``getattr``/``callable`` tolerance :attr:`_persona_time_of_day` has
        for ``get_time_of_day``.
        """
        try:
            return self._world.get_status(**self._world_overrides())
        except TypeError:
            return self._world.get_status()

    def _world_export(self) -> dict:
        """This persona's view of ``self._world.export_state()`` (see :meth:`_world_overrides`).

        Same duck-type fallback as :meth:`_world_status`.
        """
        try:
            return self._world.export_state(**self._world_overrides())
        except TypeError:
            return self._world.export_state()

    def persona_local_now(self):
        """Return 'now' in the persona's local timezone (or server-local fallback)."""
        from aura_life.hooks import persona_now
        return persona_now(self._persona_timezone())

    def _local_world_now(self) -> datetime:
        """Her local wall time for her sleep: where she lives, on the world's clock.

        A persona with a timezone reads the host's persona clock
        (:meth:`persona_local_now`), which knows that zone. One without reads
        the world clock (:meth:`_world_clock`): on a host whose world runs on
        the wall clock that is the same instant ``persona_local_now()`` gives,
        and on a host that simulates time it is the clock that moves with the
        simulation -- so neither a new persona's first state nor her nights
        depend on the hour the host process happens to run at.
        """
        if self._persona_timezone():
            return self.persona_local_now()
        return self._world_clock()()

    def _local_world_instant(self, instant: datetime) -> datetime:
        """``instant``, a naive instant on the world clock, as her local world
        time (naive): shifted as :meth:`_local_world_now` is shifted from the
        world's now -- not at all for a persona without a timezone, by her
        zone's lead on the world's clock for one with (Task 31, ruling T31-R3:
        ``add_social_plan``'s ``at`` is on the world clock, her plan's hours are
        her own). The shift is taken in whole minutes, as a zone's offset is,
        so the moment between reading the two clocks (on a host whose world
        runs on the wall clock) cannot carry an instant across an hour."""
        if not self._persona_timezone():
            return instant
        lead = self._local_world_now().replace(tzinfo=None) - self._world_clock()()
        return instant + timedelta(minutes=round(lead.total_seconds() / 60))

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
        her sleep state (:meth:`EnergySystem.is_asleep`): a state with a
        duration that the activity tick moves, a new persona starts in, and a
        reload or downtime catch-up restores -- no longer "is this hour inside
        her window", which called her asleep through ticks she spent awake.

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
            return self._energy.is_asleep()
        except Exception:
            return False

    def _tick_affect(self, hours: float, now: datetime, asleep: bool,
                     on_schedule_at: Optional[datetime] = None) -> None:
        """One affect tick (:meth:`AffectSystem.tick`) of ``hours`` world hours
        ending at the world instant ``now``: the live energy tick's, and the
        downtime catch-up's for the hours of the gap (Task 34b).

        Needs that pull mood down: her hunger, her sleep pressure and the worst
        of illness, injury and pain; and whether she is ``asleep``, which
        quiets it. An AI persona has no body to pull it.

        ``on_schedule_at`` (the catch-up's, Task 41): her local wall time at
        the start of these hours. Her sleep pressure and her hours awake are
        then what her schedule gives there
        (:meth:`EnergySystem.pressure_on_schedule`), not the energy state the
        reload left: through a gap that state is the evening the host went
        down (0.83 and fifteen hours awake for three days, in the run that
        found it), and it is set to the present only once the catch-up ends.

        One tick at a time (``_affect_tick_lock``): the live tick and the
        catch-up run on different threads."""
        hours_awake = self._energy.hours_awake
        if self._is_ai:
            sleep_pressure = illness = 0.0
        else:
            sleep_pressure = self._energy.sleep_pressure
            if on_schedule_at is not None:
                sleep_pressure, hours_awake = self._energy.pressure_on_schedule(on_schedule_at)
            illness = max(
                self._body.health.illness_severity,
                self._body.health.injury_severity,
                self._body.comfort.pain_level,
            )
        with self._affect_tick_lock:
            self._affect.tick(
                body_state={
                    "hunger": self._basic_needs.hunger,
                    "hours_awake": hours_awake,
                    "sleep_pressure": sleep_pressure,
                    "illness": illness,
                    "asleep": asleep,
                },
                social_state={"recent_events": self._social.get_recent_events() if hasattr(self._social, 'get_recent_events') else []},
                weather=self._world.weather.value if hasattr(self._world.weather, 'value') else str(self._world.weather),
                season=self._world.season.value if hasattr(self._world.season, 'value') else str(self._world.season),
                hours=hours,
                now=now,
            )

    def _tick_affect_for_catchup(self, at: datetime, since: datetime, asleep: bool,
                                 wall_since: Optional[datetime] = None) -> None:
        """The catch-up's affect tick (Task 34b): the world hours from ``since``
        to ``at``, at ``at``; ``wall_since`` is the host's wall time at
        ``since``, where her schedule is read for her sleep pressure (Task
        41). A failure is logged and the catch-up goes on, as
        :meth:`_tick_engines_for_catchup` does (its saves are not lost)."""
        try:
            self._tick_affect(max(0.0, (at - since).total_seconds() / 3600), at, asleep,
                              on_schedule_at=wall_since)
        except Exception as e:
            logger.warning(f"Catch-up affect tick failed at {at}: {e}")

    def _tick_affect_span_for_catchup(self, since: datetime, at: datetime, to_wall: timedelta) -> None:
        """The catch-up's affect ticks for one span of the gap, the world hours
        from ``since`` to ``at`` (Task 34b fix round 1): split where her sleep
        hours begin or end, each part asleep exactly when its hours are her
        sleep hours (an AI persona's never are). The hours are judged on the
        host's hour, world instant + ``to_wall``, as the catch-up's sleep
        slots are; a span of no hours is one tick of none."""
        def asleep_at(instant: datetime) -> bool:
            return not self._is_ai and self._is_sleep_hour((instant + to_wall).hour)

        start = since
        while True:
            asleep = asleep_at(start)
            end = at
            boundary = (start + to_wall).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1) - to_wall
            while boundary < at:
                if asleep_at(boundary) != asleep:
                    end = boundary
                    break
                boundary += timedelta(hours=1)
            self._tick_affect_for_catchup(end, start, asleep, start + to_wall)
            if end >= at:
                return
            start = end

    def _give_substance(self, activity_name: str, tags, now: Optional[datetime] = None) -> None:
        """Tell her body she had ``activity_name`` (a drink or a smoke by its
        name or its tags: ``BodySystem.on_substance_activity``) -- unless she is
        an AI persona: she has no body, and no drink reaches one by any path,
        her own pick, a plan slot, a housemate's activity or the catch-up,
        whatever tags the activity carries; the tag-based exclusions
        (:meth:`_excluded_activities`, her plan) stay as well (humanness Task
        19, ruling T19-R6). ``now``: when she had it -- the catch-up passes
        the backfilled activity's instant (ruling T19a-R1); without it, the
        world's instant."""
        if self._is_ai:
            return
        self._body.on_substance_activity(activity_name, tags=tags,
                                         now=now if now is not None else self._world_clock()())

    def _tick_engines_for_catchup(self, activity_name: str, timestamp: datetime,
                                   weather: str, season: str, hours: Optional[float] = None):
        """Tick all engines once for a catch-up activity (lightweight, no DB writes).

        ``hours``: the backdated world hours since the catch-up's previous
        activity (or the gap's start), which her hunger rises by before this
        activity (a meal then relieves it); ``None`` is one energy interval,
        as a tick without it always charged."""
        try:
            # Affect: activity emotions
            self._affect.on_activity(activity_name)

            # Body: activity effects, her last workout stamped with the
            # backfilled activity's own instant (ruling T19a-R1): her
            # fitness ages that stamp on the world's clock.
            self._body.on_activity(activity_name, now=timestamp)
            self._give_substance(
                activity_name, getattr(self._activity_engine.get_activity(activity_name), "tags", frozenset()),
                now=timestamp)

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
                self._finance.on_activity(activity_name, now=timestamp)
                self._finance.tick(now=timestamp)
                self._career.on_activity(activity_name)
                self._career.tick(now=timestamp)
                self._habitation.on_activity(activity_name)
                # The hours before this activity first, then the activity: a
                # backfilled meal relieves the hunger they built.
                self._sustenance.tick(now=timestamp, hours=hours)
                self._sustenance.on_activity(activity_name, now=timestamp,
                                             meal=activity_name in self._setting.names_tagged("meal"))
                self._errands.on_activity(activity_name)
                self._errands.tick(now=timestamp)

            # Goal progress (expects ActivityLog, not str), stamped with the
            # backfilled activity's instant too (ruling T19a-R1): her
            # motivation ages her last progress on the world's clock.
            from aura_life.models import ActivityLog
            self._goal_engine.update_progress_from_activity(
                ActivityLog(activity_name=activity_name), now=timestamp
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
            # There is no PHYSICAL category: the activity's own (yoga is REST, a run EXPLORATION), else EXPLORATION.
            # Main's 0.5.0 fix is the released behaviour, so it wins over the branch's all-EXPLORATION mapping.
            known = self._activity_engine.get_activity(activity_name)
            return known.category if known else ActivityCategory.EXPLORATION
        if activity_name in social:
            return ActivityCategory.SOCIAL
        return ActivityCategory.REST

    def _catch_up_line(self, pool: List[str]) -> str:
        """One line from a catch-up pool of her setting (a service-stream
        draw), or "" when the pool is empty (no draw)."""
        return self._service_rng.choice(pool) if pool else ""

    def _get_catchup_narrative(self, activity_name: str, hour: int) -> str:
        """Generate a simple narrative for a catch-up activity, from her
        setting's catch-up texts (``SettingSpec.catch_up``): its sleep line,
        a morning-routine line, or the activity's own; anything else (or a
        text her setting leaves empty) is told generically."""
        catch_up = self._setting.catch_up
        # A morning-routine line is drawn on every call, whatever the activity:
        # the dict literal this replaced drew it while being built.
        narratives = {
            **catch_up.by_activity,
            "sleeping": catch_up.sleep,
            "morning_routine": self._catch_up_line(catch_up.morning_routine),
        }
        template = (narratives.get(activity_name)
                    or "{Subj} spent some time " + activity_name.replace('_', ' '))
        return self._render_text(template)

    def _get_activity_for_hour(self, hour: int) -> tuple:
        """
        Get appropriate activity for a given hour based on persona's sleep schedule.

        Returns (activity_name, category, narrative) tuple; the narratives are
        her setting's catch-up texts (``SettingSpec.catch_up``).
        """
        catch_up = self._setting.catch_up
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
                self._render_text(catch_up.sleep)
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
                self._render_text(self._catch_up_line(catch_up.morning_routine))
            )
        elif hours_awake < 5:
            # Morning activity
            activity_name = self._service_rng.choice(["reading", "learning", "creative_work"])
            return (
                activity_name,
                ActivityCategory.CREATIVE if "creative" in activity_name else ActivityCategory.MENTAL,
                self._render_text(self._catch_up_line(catch_up.morning_activity))
            )
        elif hours_awake < 7:
            # Midday / lunch
            return (
                "cooking",
                ActivityCategory.REST,
                self._render_text(self._catch_up_line(catch_up.midday))
            )
        elif hours_awake < 11:
            # Afternoon
            activity_name = self._service_rng.choice(["exploring_interests", "gentle_walk", "creative_work"])
            return (
                activity_name,
                ActivityCategory.CREATIVE,
                self._render_text(self._catch_up_line(catch_up.afternoon))
            )
        elif hours_awake < 14:
            # Evening
            activity_name = self._service_rng.choice(["relaxing", "watching_sunset", "evening_routine"])
            return (
                activity_name,
                ActivityCategory.REST,
                self._render_text(self._catch_up_line(catch_up.evening))
            )
        else:
            # Late evening / winding down
            return (
                "winding_down",
                ActivityCategory.REST,
                self._render_text(catch_up.late)
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
                elif days_until < 2:
                    urgency = 0.6
                else:
                    urgency = 0.45

                # Boost for high-importance or strong-feeling events
                if row["importance"] > 0.7 or row["feeling"] not in ("neutral", ""):
                    urgency = min(urgency + 0.1, 1.0)

                # The day it is on, by the calendar and in words (Task 17):
                # an event under a day away can be tomorrow's.
                day_gap = (event_date.date() - now.date()).days
                when = ("today" if day_gap <= 0 else "tomorrow" if day_gap == 1
                        else f"in {_number_words(day_gap)} days")
                hint = (
                    f"{_user_ref_tokens(self._user_info)['user_Poss']} event '{row['event_name']}'"
                    f" is {when}. Bring it up naturally — ask them about it or wish them well."
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
                        f"{_user_ref_tokens(self._user_info)['user_Poss']} event"
                        f" '{row['event_name']}' just happened."
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
        """Generate a narrative summarizing a long gap period (her setting's
        ``catch_up.gap_week`` / ``gap_days`` / ``gap_short``). Each is
        rendered: the contemporary ``gap_days`` carries no token, so it reads
        as it always did, and another setting's may carry one."""
        days = hours / 24
        catch_up = self._setting.catch_up

        if days >= 7:
            return self._render_text(catch_up.gap_week)
        elif days >= 2:
            return self._render_text(catch_up.gap_days)
        else:
            return self._render_text(catch_up.gap_short)
