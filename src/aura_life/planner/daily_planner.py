"""
Daily Planner

Generates a consistent daily schedule for the persona.

The plan is generated once per day (at dawn or server start) and followed
throughout the day. If conditions change (weather, energy crisis), upcoming
slots are silently revised — she "prepared the change ahead" rather than
reactively announcing it.
"""

import logging
import random
import zlib
from itertools import zip_longest
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from ..behavior.behavior_system import habit_band
from ..models import (
    DailyPlan,
    PlannedSlot,
    ShortTermDesire,
    DesireSource,
    Goal,
    Activity,
    TimeOfDay,
    Weather,
)
from ..activities.choice import (
    SUBSTANCE_FREQUENCY,
    SUBSTANCE_TAGS,
    SUBSTANCE_UNKNOWN_FREQUENCY,
    ActivityPreferences,
    choice_weight,
    matching_activities,
)
from ..personas.parameters import PersonaParameters
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
from ..settings.spec import ANCHOR_TAGS, COMMITMENT_TAGS, PLAN_ONLY_TAGS
# Legacy names: the wants (desire templates) and the holiday calendar moved,
# unchanged, into the contemporary setting pack
# (aura_life.settings.contemporary) in Task 9 -- the planner reads its
# persona's setting now; re-exported so an import from here keeps working.
from ..settings.contemporary import (  # noqa: F401
    DESIRE_TEMPLATES,
    INTEREST_LOCATIONS,  # the fix round's (ruling T9-R5), as is the next
    OCCUPATION_LOCATIONS,
    NATIONALITY_TO_COUNTRY,
    _FIXED_HOLIDAYS,
    _easter_sunday,
    _get_floating_holidays,
    _last_weekday,
    _nth_weekday,
    get_holidays,
)

logger = logging.getLogger(__name__)

#: A slot's draw is among its best candidates by score, this many (the planner's own cut, unchanged by habits).
SLOT_DRAW_SIZE = 6

# ============= Keeping to the plan =============

#: revise_upcoming swaps an upcoming slot for rest when her energy is below
#: this. Per persona, divided by PersonaParameters.plan_adherence
#: (conscientiousness): a conscientious persona keeps her plans until she is
#: more tired.
PLAN_REVISE_ENERGY_BELOW = 0.25
#: revise_upcoming swaps an upcoming slot for something gentle when a low
#: mood's intensity is above this. Per persona, times plan_adherence.
PLAN_REVISE_MOOD_INTENSITY_ABOVE = 0.4
#: The reason a slot agreed in conversation carries (set_planned_activity's
#: default, and LifeService.add_conversation_plan's): a whim never drops it.
USER_AGREED_REASON = "agreed with user"


# ============= Her own wants (Task 10) =============
# What her definition's want seeds become: each a short-term want in the
# setting's shape, pursued through the activities of her setting that match
# it (aura_life.activities.choice.matching_activities). A seed nothing in her
# setting meets is no want. Titles are first person, like the setting's
# ("Find a new song that moves me"); the seed is her own words. Chosen for
# Task 10 (see its report).

#: An interest.
INTEREST_WANT = {"title": "Make time for {text}", "description": "I've been missing it"}
#: A comfort-zone seed: something she is at home doing.
COMFORT_ZONE_WANT = {"title": "Get back to {text}", "description": "It's where I feel like myself"}
#: A taste, by the taste's kind (``taste_seeds`` key); another kind takes TASTE_WANT.
TASTE_WANTS = {
    "music": {"title": "Put on some {text}", "description": "I'm in the mood for it"},
    "food": {"title": "Have some {text}", "description": "I've been craving it"},
}
TASTE_WANT = {"title": "Find some {text}", "description": "I've been in the mood for it"}
#: Taste kinds whose wants her meals meet.
FOOD_TASTES = ("food", "foods", "cuisine", "eating")
#: Something she reads, watches or listens to, by kind (``media_preferences``
#: key); another kind takes MEDIA_WANT.
MEDIA_WANTS = {
    "music": {"title": "Listen to {text}", "description": "It's been stuck in my head"},
    "shows": {"title": "Watch {text}", "description": "I want to see what happens next"},
    "films": {"title": "Watch {text}", "description": "I've been meaning to"},
    "movies": {"title": "Watch {text}", "description": "I've been meaning to"},
}
MEDIA_WANT = {"title": "Get back into {text}", "description": "I left off somewhere good"}
#: A substance she takes, by the activity tag it is
#: (aura_life.activities.choice.SUBSTANCE_TAGS); none when she avoids it.
SUBSTANCE_WANTS = {
    "alcohol": {"title": "Have a drink", "description": "Just the one. Maybe."},
    "smoking": {"title": "Have a smoke", "description": "Five minutes, outside"},
}


# ============= Routine Activities =============
# Fixed daily routines that anchor the schedule around the sleep cycle: the
# contemporary names of the anchors (since Task 10 each planner reads its
# setting's own, by tag -- aura_life.settings.spec.ANCHOR_TAGS -- and adds
# them to these).

# The reason LifeService gives a slot it fills from a social plan ("plan with Maya, Leo").
SOCIAL_PLAN_REASON_PREFIX = "plan with "

ROUTINE_ACTIVITIES = {
    "waking up",
    "having breakfast",
    "having lunch",
    "having dinner",
    "getting ready for bed",
    "working",
    "commuting",
    "attending classes",
    "studying",
}

# No habit forms on the day's anchors (the planner sets them by the clock, never draws them) or on sleep: they are
# left out of the habit shares, so a habit is a share of her free time.
NOT_HABIT_FORMING = frozenset(ROUTINE_ACTIVITIES | {"sleeping", "napping"})


_NO_HABIT = (1.0, 1.0)


def _slot_draw(
    candidates: List[Tuple[str, float, str]],
    habit: Optional[Dict[str, Tuple[float, float]]],
) -> Tuple[List[Tuple[str, float, str]], List[float]]:
    """A slot's draw: its best SLOT_DRAW_SIZE candidates by score (``candidates`` re-sorted in place), and their
    weights, each its share of the cut's score.

    With ``habit`` (``{activity: (raise, damp)}`` for this part of her day; a name missing is neutral) the raise
    (comfort, x1 to x1.5) first multiplies the candidate's score, so a habit can bring an activity into the six; the
    damp (staleness, /1.5 to x1) multiplies its weight after the cut, and a damped candidate the planner alone would
    have put in the six keeps its place there, so staleness lowers its chance by at most /1.5 and nothing pushes it
    out (behavior_system's DESIGN VALUES). Without a habit the draw is exactly the 0.4.0 one.
    """
    if not habit:
        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[:SLOT_DRAW_SIZE]
        total = sum(s for _, s, _ in top)
        return top, [s / total for _, s, _ in top]
    own = sorted(candidates, key=lambda x: x[1], reverse=True)[:SLOT_DRAW_SIZE]
    kept = {(name, why) for name, _, why in own if habit.get(name, _NO_HABIT)[1] < 1.0}
    candidates[:] = [(name, s * habit.get(name, _NO_HABIT)[0], why) for name, s, why in candidates]
    candidates.sort(key=lambda x: x[1], reverse=True)
    rest = [c for c in candidates if (c[0], c[2]) not in kept][:SLOT_DRAW_SIZE - len(kept)]
    top = sorted([c for c in candidates if (c[0], c[2]) in kept] + rest, key=lambda x: x[1], reverse=True)
    total = sum(s for _, s, _ in top)
    return top, [s / total * habit.get(name, _NO_HABIT)[1] for name, s, _ in top]

# ============= AI Scheduler: Physical-Activity Exclusions =============
# AI personas have no physical body — no sleep, meals, commute, work, errands,
# grooming, exercise, or outings. The AI day is built ONLY from the non-physical
# subset of the activity pool (digital/creative/reflective/mental). Any activity
# tagged "physical" is excluded when building an AI plan; the human path is
# untouched. Legacy name: PHYSICAL_ACTIVITIES is no longer read -- since Task
# 9's fix round (ruling T9-R5) the persona's setting tags its activities
# "physical" (and its routine slot names, SettingSpec.name_tags); kept so an
# import from here keeps working.

PHYSICAL_ACTIVITIES = {
    # Sleep / rest tied to a body
    "sleeping",
    "napping",
    # Routine body anchors
    "waking up",
    "getting ready for bed",
    "morning shower",
    "skincare routine",
    # Meals / eating / cooking
    "having breakfast",
    "having lunch",
    "having dinner",
    "cooking a meal",
    "baking something",
    "trying a new recipe",
    "making tea",
    "making hot chocolate",
    # Work / school
    "working",
    "commuting",
    "attending classes",
    "studying",
    "lunch with coworkers",
    # Errands / chores / outings
    "running errands",
    "tidying up",
    "going for a walk",
    "beach day",
    "collecting autumn leaves",
    "picnic in the park",
    "having coffee with a friend",
    "people watching",
    "tending to plants",
    # Body / exercise
    "yoga",
    "going for a run",
    "gym workout",
    "stretching",
}

# ============= Activity-Importance Classifier =============
# Activity-name fragments that mark a scheduled slot as an important, hard
# commitment she shouldn't be late for. Work shifts and commutes are emitted by
# the planner as "working"/"commuting" (see ROUTINE_ACTIVITIES); appointments/
# classes are author- or chaos-driven. Matched case-insensitively as substrings.
IMPORTANT_ACTIVITY_FRAGMENTS = (
    "working", "commut", "appointment", "meeting", "interview", "class", "studying",
)

# ============= Weather-based activity weighting (T2.3) =============
# Activities tagged "outdoor" happen outside and are affected by bad weather.
# Bad weather down-weights them; clear/sunny slightly up-weights them. Legacy
# name: OUTDOOR_ACTIVITIES is no longer read (Task 9's fix round, ruling
# T9-R5, turned it into the tag); kept so an import from here keeps working.
# Gate: AURA_WEATHER_PLANNER_ENABLED=false disables the adjustment.
OUTDOOR_ACTIVITIES = {
    "going for a walk",
    "going for a run",
    "beach day",
    "collecting autumn leaves",
    "picnic in the park",
    "people watching",
    "tending to plants",
    "stargazing",
    "skateboarding",
    "hiking",
    "surfing",
    "cycling",
}

# Score penalty applied to outdoor activities when weather is bad.
WEATHER_OUTDOOR_PENALTY = -0.4   # bad weather (rain/storm/snow)
WEATHER_OUTDOOR_BONUS  =  0.15   # clear/sunny (conservative — plans still vary)

_BAD_WEATHER = {Weather.RAINY, Weather.STORMY, Weather.SNOWY}
_GOOD_WEATHER = {Weather.SUNNY, Weather.CLEAR_NIGHT, Weather.STARRY}


def _weather_planner_enabled() -> bool:
    """Check AURA_WEATHER_PLANNER_ENABLED at call time (testable via monkeypatch)."""
    import os as _os
    return _os.environ.get("AURA_WEATHER_PLANNER_ENABLED", "true").lower() in ("true", "1", "yes")


def is_important_activity(activity_name: str, errands=None) -> bool:
    """Auto-classify a scheduled activity as an important commitment.

    Work shifts, commutes, appointments, classes -> always important. A generic
    errand slot is important only when something is actually overdue (the
    ErrandsSystem reports `overdue_count > 0`). Human-only in practice: AI
    personas have Job/Errands gated off, so their slots never match.
    """
    name = (activity_name or "").strip().lower()
    if not name:
        return False
    if any(frag in name for frag in IMPORTANT_ACTIVITY_FRAGMENTS):
        return True
    if "errand" in name and errands is not None and getattr(errands, "overdue_count", 0) > 0:
        return True
    return False

# Daytime clock hours (inclusive of 8, exclusive of 22) used for the AI
# "light day/night rhythm": daytime gets denser, more-varied activity; the rest
# of the 24h span stays present but quieter.
AI_DAYTIME_HOURS = set(range(8, 22))

# ============= Occupation Classification =============

OCC_NONE = "none"          # No work (AI companion, retired, left practice)
OCC_STUDENT = "student"    # Scattered classes + study blocks
OCC_STANDARD = "standard"  # 8h Mon-Fri office/professional
OCC_SERVICE = "service"    # Shift-based (nurse, barista, dancer)
OCC_CREATIVE = "creative"  # Flexible/short blocks (singer, artist, freelance)

_OCC_NONE_KEYWORDS = {
    "companion", "retired", "left her", "left his", "unemployed",
    "stay-at-home", "stay at home", "none", "no job", "between jobs",
}
_OCC_STUDENT_KEYWORDS = {"student", "university", "college", "studying", "school"}
_OCC_SERVICE_KEYWORDS = {
    "nurse", "nursing", "paramedic", "barista", "bartender", "barmaid",
    "bouncer", "dancer", "waitress", "waiter", "server", "cashier",
    "shop owner", "shopkeeper", "retail", "receptionist", "dominatrix",
    "striptease", "stripper",
}
_OCC_CREATIVE_KEYWORDS = {
    "singer", "musician", "artist", "painter", "writer", "author",
    "photographer", "filmmaker", "actor", "actress", "performer",
    "freelance", "indie", "composer", "poet", "designer", "illustrator",
}


def classify_occupation(text: str) -> str:
    """Classify an occupation string into one of the OCC_* types.

    For multi-occupation strings (comma-separated), each part is checked
    in priority order: none > student > service > creative > standard.
    """
    if not text or not text.strip():
        return OCC_NONE

    lower = text.lower()

    # Check for no-work keywords first (highest priority)
    for kw in _OCC_NONE_KEYWORDS:
        if kw in lower:
            return OCC_NONE

    # Split on comma for multi-occupation handling; check each part
    parts = [p.strip() for p in lower.split(",")]

    # Student wins over other secondary occupations
    for part in parts:
        for kw in _OCC_STUDENT_KEYWORDS:
            if kw in part:
                return OCC_STUDENT

    # Service keywords
    for part in parts:
        for kw in _OCC_SERVICE_KEYWORDS:
            if kw in part:
                return OCC_SERVICE

    # Creative keywords
    for part in parts:
        for kw in _OCC_CREATIVE_KEYWORDS:
            if kw in part:
                return OCC_CREATIVE

    # Default: if they have an occupation string at all, treat as standard
    return OCC_STANDARD


class DailyPlanner:
    """
    Generates and manages the persona's daily schedule.

    Principles:
    - Plan is generated ONCE per day, at dawn or server start
    - Plan stays consistent throughout the day
    - If conditions change, upcoming slots are silently revised
      ("she prepared the change ahead")
    - Desires and goals shape the plan
    - Energy curves are respected (no high-energy activities at night)
    """

    # Upper bound on a plan's `revision_notes` (see `_note_revision`).
    MAX_REVISION_NOTES = 20

    def __init__(
        self,
        occupation: str = "",
        interests: Optional[List[str]] = None,
        sleep_schedule: Optional[Dict] = None,
        persona_locations: Optional[Dict[str, str]] = None,
        nationality: str = "",
        is_ai: bool = False,
        rng=None,
        params: Optional[PersonaParameters] = None,
        setting: Optional[SettingSpec] = None,
        persona_id: Optional[str] = None,
        preferences: Optional[ActivityPreferences] = None,
        definition=None,
        media_preferences: Optional[Dict[str, List[str]]] = None,
    ):
        """``rng``: optional ``random.Random`` for this planner's bare draws
        (shuffling slot candidates, picking a routine/gentle activity, a
        desire's expiry jitter, ...). ``None`` -- the default -- is a fresh,
        unseeded ``random.Random()`` (never the module), so a bare
        ``DailyPlanner()`` still works and shares no draw sequence with any
        other instance or the module. Its per-day, per-role schedule draws
        (``random.Random(zlib.crc32((today + role).encode()))``, built fresh
        inside each generator) are unaffected: they already derive their own
        seed from the date and role/occupation, independently of any rng.

        ``params``: her traits' engine parameters
        (:class:`~aura_life.personas.parameters.PersonaParameters`). Her
        conscientiousness sets how tired or low she must be before
        :meth:`revise_upcoming` drops upcoming slots (``plan_adherence``);
        her impulsivity the chance :meth:`abandons_slot` drops a planned
        free-time slot on a whim (``plan_deviation_chance``). Without them,
        the thresholds as they are and no whims.

        ``setting``: her setting pack (:class:`~aura_life.settings.SettingSpec`):
        the wants she draws from (``wants``), the one an activity can leave
        behind (``want_follow_ups``), her holiday calendar (``holidays``)
        and the places every plan may use (``places``, before her profile's
        own); and the activity tags it plans by (ruling T9-R5: "physical",
        "outdoor", "quiet", "fallback_rest", "restful", "soothing",
        "gentle", "clear_sky", "rained_off", "rainy_day";
        :data:`~aura_life.settings.spec.ACTIVITY_TAGS`), in the tag orders
        it gives. ``None`` -- the default -- is
        :data:`~aura_life.settings.DEFAULT_SETTING`'s.

        ``persona_id``: whose planner this is -- the swaps and fallbacks
        draw only from the activities open to her
        (:meth:`~aura_life.settings.SettingSpec.activities_for`).

        The day's anchors -- waking, the three meals, bedtime, a shift, the
        commute, a class, study, a meetup -- are her setting's activities for
        them, by tag (:data:`~aura_life.settings.spec.ANCHOR_TAGS`; the first
        so tagged, in its tag order; a meal slot without its own takes her
        first "meal" activity). A slot her setting has no activity for is not
        planned: every slot is something she can do (Task 10).

        ``preferences``: hers (:class:`~aura_life.activities.choice.ActivityPreferences`),
        which a free hour is filled by: what she is into (her interests,
        comfort zones, tastes, media, substances) and how far her traits
        lean her to an activity (``plan_preference``). ``None`` -- the
        default -- builds them from ``params`` and ``interests`` alone.

        ``definition`` (a ``PersonalityDefinition``) and ``media_preferences``:
        her want seeds -- interests, comfort-zone seeds, tastes, media and
        substance tendencies (the templates above) -- whose wants she draws
        alongside her setting's. ``interests`` and ``media_preferences``, when
        given, are hers instead of the definition's."""
        if params is None:
            params = PersonaParameters()
        self._preferences = preferences if preferences is not None else ActivityPreferences(
            params, interests=interests or [])
        self._setting = setting if setting is not None else get_setting(DEFAULT_SETTING)
        self._activities = self._setting.activities_for(persona_id)
        self._anchors: Dict[str, Optional[str]] = {tag: self._first_tagged(tag) for tag in ANCHOR_TAGS}
        for meal in ("breakfast", "lunch", "dinner"):
            self._anchors[meal] = self._anchors[meal] or self._first_tagged("meal")
        #: Never a free hour's pick: the anchors are planned in their own slots
        #: -- the activities tagged for one, and those the planner fills one
        #: with (the universal "having a meal" in a pack without meal slots
        #: of its own: fix round 1, finding 2).
        self._anchor_names = frozenset(
            activity.name for activity in self._activities if activity.tags & set(ANCHOR_TAGS)
        ) | frozenset(name for name in self._anchors.values() if name)
        #: What a whim, a revision or the outing guarantee leaves alone.
        self._routine_names = frozenset(ROUTINE_ACTIVITIES) | self._anchor_names
        #: Her commitments: what cancelling the day's work cancels.
        self._commitment_names = frozenset(
            activity.name for activity in self._activities if activity.tags & set(COMMITMENT_TAGS))
        #: Her own wants (the templates above), drawn alongside her setting's.
        self._own_wants: List[Dict] = self._build_own_wants(definition, interests, media_preferences)
        self._revise_energy_below = PLAN_REVISE_ENERGY_BELOW / params.plan_adherence
        self._revise_mood_intensity_above = PLAN_REVISE_MOOD_INTENSITY_ABOVE * params.plan_adherence
        self._deviation_chance = params.plan_deviation_chance
        # How far she seeks company on a low day (her coping, Task 15:
        # PersonaParameters.contact_seeking; at or below 0, not at all).
        self._contact_seeking = params.contact_seeking
        self._rng = rng if rng is not None else random.Random()
        # AI personas have no physical life: no sleep/meals/work/commute/errands.
        # When set, generate_daily_plan() builds a 24h-awake "light day/night
        # rhythm" from the non-physical activity subset instead of a human day.
        self._is_ai = is_ai
        self._occupation = occupation
        self._occupation_type = classify_occupation(occupation)
        self._interests = interests or []
        self._sleep_schedule = sleep_schedule or {}
        self._persona_locations = persona_locations or {}
        self._nationality = nationality
        # Every persona has access to her setting's places (the contemporary
        # pack's are the set literal this held until Task 9); profiles can add
        # custom ones
        self._available_location_keys = set(self._setting.places) | set(
            k.lower() for k in self._persona_locations.keys()
        )
        self._wake_hour = self._sleep_schedule.get("wake_hour", 7)
        self._bed_hour = self._sleep_schedule.get("bedtime_hour", 23)
        self._current_plan: Optional[DailyPlan] = None
        self._desires: List[ShortTermDesire] = []
        self._last_desire_generation: Optional[datetime] = None

    @property
    def current_plan(self) -> Optional[DailyPlan]:
        return self._current_plan

    @property
    def desires(self) -> List[ShortTermDesire]:
        return [d for d in self._desires if not d.fulfilled and not self._is_expired(d)]

    @property
    def all_desires(self) -> List[ShortTermDesire]:
        return self._desires

    def needs_new_plan(self, now: Optional[datetime] = None) -> bool:
        """Is her plan not for the day ``now`` is on? ``LifeService`` passes
        her local world time (her plan's days are hers); the host's wall
        clock when omitted."""
        if not self._current_plan:
            return True
        today = (now if now is not None else datetime.now()).strftime("%Y-%m-%d")
        return self._current_plan.date != today

    def generate_daily_plan(
        self,
        goals: List[Goal],
        weather: Weather,
        available_activities: List[Activity],
        recent_activity_names: List[str],
        work_schedule: Optional[dict] = None,
        now: Optional[datetime] = None,
        habits: Optional[Dict[str, Dict[str, Tuple[float, float]]]] = None,
    ) -> DailyPlan:
        """
        Generate a new daily plan.

        Called once per day. Produces a realistic schedule anchored by
        wake-up, meals, work (if occupation set), and bedtime routines.
        Hobby activities fill the remaining gaps.

        AI personas have no physical life, so they take a separate path: a 24h
        light day/night rhythm of non-physical activities, never asleep.

        The plan is for the day ``now`` is on, and its weekday decides her
        work: ``LifeService`` passes her local world time; the host's wall
        clock when omitted.

        ``habits`` is ``{part of her day: {activity: (raise, damp)}}``
        (``BehaviorSystem.habit_factors``): each hobby slot's draw is reweighted
        by its part of the day's factors (``_slot_draw``), on the slot's
        choice weights (``choice_weight`` of its score and her plan
        preference). ``None`` draws as without habits.
        """
        if self._is_ai:
            return self._generate_ai_plan(
                goals=goals,
                weather=weather,
                available_activities=available_activities,
                recent_activity_names=recent_activity_names,
                now=now,
                habits=habits,
            )

        now = now if now is not None else datetime.now()
        today = now.strftime("%Y-%m-%d")
        today_weekday = now.weekday()  # 0=Mon, 6=Sun
        slots: List[PlannedSlot] = []

        # Ensure we have fresh desires
        self._refresh_desires(goals)
        active_desires = self.desires

        wake = self._wake_hour
        bed = self._bed_hour

        # For schedules that cross midnight (e.g. bed=2), compute
        # the total awake span so all hour arithmetic stays positive.
        if bed <= wake:
            awake_span = (24 - wake) + bed  # e.g. wake 22, bed 6 -> 8h
        else:
            awake_span = bed - wake  # e.g. wake 7, bed 23 -> 16h

        def _h(offset: int) -> int:
            """Convert wake-relative offset to clock hour (0-23)."""
            return (wake + offset) % 24

        # Build activity pool
        activity_map = {a.name: a for a in available_activities}

        # Track assigned locations for variety scoring during plan generation
        self._plan_assigned_locations: List[str] = []

        # --- Fixed routine anchors (offsets from wake): her setting's
        # activity for each (self._anchors); none, and the slot is not
        # planned (its hour is still kept from the free hours) ---
        def _anchor_slot(tag: str, hour: int, reason: str, location: Optional[str] = None) -> None:
            name = self._anchors[tag]
            if not name:
                return
            if location is None:
                location = self._resolve_location_for_activity(name, activity_def=activity_map.get(name))
            slots.append(PlannedSlot(hour=hour, activity_name=name, reason=reason, location=location))

        _anchor_slot("wake_up", _h(0), "start of the day")
        _anchor_slot("breakfast", _h(1), "morning meal")

        # Lunch: ~5 hours after wake, but at least hour 12 for normal schedules
        lunch_offset = 5
        if wake < 12 and wake + lunch_offset < 12:
            lunch_offset = 12 - wake  # push to noon
        lunch_offset = min(lunch_offset, awake_span - 5)  # leave room for dinner/bed
        lunch_offset = max(lunch_offset, 3)  # at least 3h after wake
        lunch_hour = _h(lunch_offset)

        _anchor_slot("lunch", lunch_hour, "midday meal")

        # Dinner: ~3-4 hours before bed, at least 3h after lunch
        dinner_offset = max(lunch_offset + 3, awake_span - 4)
        dinner_offset = min(dinner_offset, awake_span - 2)  # 2h before bed
        dinner_hour = _h(dinner_offset)

        _anchor_slot("dinner", dinner_hour, "evening meal")

        # Bedtime prep: 1 hour before bed
        bedprep_hour = _h(awake_span - 1)
        _anchor_slot("bedtime", bedprep_hour, "winding down", location="home")

        # Collect offsets already taken by routines
        routine_offsets = {0, 1, lunch_offset, dinner_offset, awake_span - 1}

        # --- Work / school blocks ---
        # The Job engine is the source of truth for WHICH days she works and her
        # shift window; the planner places blocks accordingly. Falls back to the
        # occupation-type generators when no schedule is provided (e.g. tests).
        if work_schedule is not None:
            works_today = bool(work_schedule.get("employed", True)) and \
                today_weekday in work_schedule.get("work_days", [0, 1, 2, 3, 4])
        else:
            works_today = self._occupation_type != OCC_NONE

        if works_today:
            chaos = self._roll_day_chaos(today, today_weekday)

            if chaos not in ("sick_day", "day_off", "holiday"):
                if work_schedule is not None:
                    work_slots, commute_slots = self._generate_shift_window_work(
                        shift_start=int(work_schedule.get("shift_start_hour", 9)),
                        shift_end=int(work_schedule.get("shift_end_hour", 17)),
                        wake=wake,
                        awake_span=awake_span,
                        routine_offsets=routine_offsets,
                        _h=_h,
                        chaos=chaos,
                    )
                else:
                    work_slots, commute_slots = self._generate_work_blocks(
                        today=today,
                        weekday=today_weekday,
                        chaos=chaos,
                        wake=wake,
                        lunch_offset=lunch_offset,
                        dinner_offset=dinner_offset,
                        awake_span=awake_span,
                        routine_offsets=routine_offsets,
                        _h=_h,
                    )
                for ws in work_slots:
                    slots.append(ws)
                    # Mark the offset as taken so hobbies don't overlap
                    off = (ws.hour - wake) % 24
                    routine_offsets.add(off)
                for cs in commute_slots:
                    slots.append(cs)
                    off = (cs.hour - wake) % 24
                    routine_offsets.add(off)

        # --- Fill remaining waking hours with hobby activities ---
        used_names = [s.activity_name for s in slots]
        free_offsets = [
            off for off in range(2, awake_span - 1)
            if off not in routine_offsets
        ]

        for off in free_offsets:
            clock_h = _h(off)
            # Pick time-of-day preferences based on the clock hour
            if clock_h < 12:
                preferred = [TimeOfDay.MORNING]
            elif clock_h < 17:
                preferred = [TimeOfDay.AFTERNOON]
            else:
                preferred = [TimeOfDay.EVENING]

            activity_name, reason = self._select_activity_for_slot(
                preferred_times=preferred,
                goals=goals,
                desires=active_desires,
                activity_map=activity_map,
                recent=recent_activity_names,
                weather=weather,
                used=used_names,
                is_ai=self._is_ai,
                habit=(habits or {}).get(habit_band(clock_h)),
            )
            if activity_name:
                activity_def = activity_map.get(activity_name)
                location = self._resolve_location_for_activity(activity_name, activity_def=activity_def)
                slots.append(PlannedSlot(
                    hour=clock_h,
                    activity_name=activity_name,
                    reason=reason,
                    location=location,
                ))
                used_names.append(activity_name)

        # Clear-sky bonus if weather is clear and there's a late evening slot:
        # her first clear-sky activity (tag "clear_sky": the contemporary
        # "stargazing").
        stargaze_offset = awake_span - 2
        clear_sky = self._setting.tag_pool("clear_sky", available_activities)
        if clear_sky and weather in (Weather.CLEAR_NIGHT, Weather.STARRY) and stargaze_offset not in routine_offsets:
            stargaze_hour = _h(stargaze_offset)
            stargaze_loc = self._resolve_location_for_activity(clear_sky[0])
            existing = [s for s in slots if s.hour == stargaze_hour]
            if existing:
                existing[0].activity_name = clear_sky[0]
                existing[0].reason = "clear sky tonight"
                existing[0].location = stargaze_loc
            else:
                slots.append(PlannedSlot(
                    hour=stargaze_hour,
                    activity_name=clear_sky[0],
                    reason="clear sky tonight",
                    location=stargaze_loc,
                ))

        # --- Minimum outing guarantee ---
        # Ensure at least 1-2 hobby slots per day are outside home.
        # This prevents all-home schedules for personas without occupations.
        non_routine = [
            s for s in slots
            if s.activity_name not in self._routine_names
               and s.location in ("home", None)
        ]
        outings_today = sum(
            1 for s in slots
            if s.location and s.location not in ("home", None)
        )
        min_outings = 2 if len(non_routine) > 4 else 1
        if outings_today < min_outings and non_routine:
            # Promote some home hobby slots to outside locations
            self._rng.shuffle(non_routine)
            for slot in non_routine[:min_outings - outings_today]:
                outside = self._pick_location("cafe", "park", "library")
                if outside != "home":
                    slot.location = outside

        # Sort by hour
        slots.sort(key=lambda s: s.hour)

        plan = DailyPlan(
            date=today,
            slots=slots,
            created_at=datetime.now(),
            weather_at_creation=weather.value,
        )

        self._current_plan = plan
        logger.info(f"Generated daily plan with {len(slots)} slots for {today}")
        return plan

    def _generate_ai_plan(
        self,
        goals: List[Goal],
        weather: Weather,
        available_activities: List[Activity],
        recent_activity_names: List[str],
        now: Optional[datetime] = None,
        habits: Optional[Dict[str, Dict[str, Tuple[float, float]]]] = None,
    ) -> DailyPlan:
        """Build an AI persona's daily plan: a 24h-awake light day/night rhythm.

        AI personas have no physical body — no sleep, meals, commute, work, or
        errands. Every clock hour 0..23 gets a non-physical (digital / creative /
        reflective / mental) activity. Daytime hours (AI_DAYTIME_HOURS) draw from
        the full varied non-physical pool; night hours stay present but quieter,
        favoring low-key activities so the day reads denser than the night.
        For the day ``now`` is on (:meth:`generate_daily_plan`'s).
        """
        now = now if now is not None else datetime.now()
        today = now.strftime("%Y-%m-%d")

        self._refresh_desires(goals)
        active_desires = self.desires

        # Non-physical subset of the pool — drop anything that needs a body
        # (tag "physical").
        non_physical = [
            a for a in available_activities
            if "physical" not in a.tags
        ]
        activity_map = {a.name: a for a in non_physical}

        # Quiet night-time activities: calm, low-key, present-but-still (tag
        # "quiet"), in her setting's draw order.
        quiet_pool = self._setting.tag_pool("quiet", non_physical)
        # Quiet downtime is her rest (tag "fallback_rest": the contemporary
        # "relaxing").
        rest = self._fallback_rest(ai=True)

        self._plan_assigned_locations = []
        slots: List[PlannedSlot] = []
        used_names: List[str] = []

        # Night rhythm: she's present but mostly still. Only a sparse subset of
        # night hours gets an actual low-key activity; the rest are quiet
        # downtime. This keeps the day reliably busier/denser than the night
        # without modelling a circadian cycle. Pick the lit hours deterministically
        # so the rhythm is stable across a single day's generation.
        night_hours = [h for h in range(24) if h not in AI_DAYTIME_HOURS]
        self._rng.shuffle(night_hours)
        night_active_count = min(len(quiet_pool), max(1, len(night_hours) // 3))
        night_active_hours = set(night_hours[:night_active_count])

        for clock_h in range(24):
            is_day = clock_h in AI_DAYTIME_HOURS

            if clock_h < 12:
                preferred = [TimeOfDay.MORNING]
            elif clock_h < 17:
                preferred = [TimeOfDay.AFTERNOON]
            elif clock_h < 22:
                preferred = [TimeOfDay.EVENING]
            else:
                preferred = [TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT]

            activity_name = None
            reason = "free time"

            if is_day:
                # Daytime: varied, desire/goal-aware selection from the full pool.
                activity_name, reason = self._select_activity_for_slot(
                    preferred_times=preferred,
                    goals=goals,
                    desires=active_desires,
                    activity_map=activity_map,
                    recent=recent_activity_names,
                    weather=weather,
                    used=used_names,
                    is_ai=self._is_ai,
                    habit=(habits or {}).get(habit_band(clock_h)),
                )
            elif clock_h in night_active_hours and quiet_pool:
                # Sparse night activity: one calm, low-key thing.
                choices = [n for n in quiet_pool if n not in used_names] or quiet_pool
                activity_name = self._rng.choice(choices)
                reason = "a quiet moment"
            else:
                # Quiet downtime — present but still.
                activity_name = rest
                reason = "a quiet moment"

            if not activity_name:
                activity_name = rest
                reason = "a quiet moment"
            if not activity_name:
                continue  # her setting has no rest to fall back on: the hour stays open

            activity_def = activity_map.get(activity_name)
            location = self._resolve_location_for_activity(
                activity_name, activity_def=activity_def
            )
            slots.append(PlannedSlot(
                hour=clock_h,
                activity_name=activity_name,
                reason=reason,
                location=location,
            ))
            used_names.append(activity_name)

        slots.sort(key=lambda s: s.hour)
        plan = DailyPlan(
            date=today,
            slots=slots,
            created_at=datetime.now(),
            weather_at_creation=weather.value,
        )
        self._current_plan = plan
        logger.info(f"Generated AI daily plan with {len(slots)} slots for {today}")
        return plan

    def get_planned_activity(self, hour: int) -> Optional[PlannedSlot]:
        """Get the planned activity for the current hour."""
        if not self._current_plan:
            return None
        return self._current_plan.get_slot_for_hour(hour)

    def abandons_slot(self, slot: PlannedSlot) -> bool:
        """Does she drop this planned slot on a whim, and do something else?

        Only a free-time slot: never a routine anchor (ROUTINE_ACTIVITIES and
        her setting's anchors -- meals, work, classes), an important
        commitment (:func:`is_important_activity`), a plan agreed with the
        user (USER_AGREED_REASON) or a plan with people (:meth:`is_free_time`).
        The chance is her impulsivity's
        ``plan_deviation_chance``; at or below neutral impulsivity it is 0 and
        no draw is taken, so this planner's stream is exactly as before."""
        if self._deviation_chance <= 0.0 or not self.is_free_time(slot):
            return False
        return self._rng.random() < self._deviation_chance

    def is_commitment(self, slot: Optional[PlannedSlot]) -> bool:
        """Is this planned slot one of her commitments -- a shift, the
        commute, a class, study (her setting's activities tagged "work",
        "commute", "class", "study", and the contemporary names)? An intimate
        activity never takes one (``LifeService``, spec R6)."""
        return slot is not None and slot.activity_name in (
            self._commitment_names | {"working", "attending classes", "studying", "commuting"})

    def is_free_time(self, slot: Optional[PlannedSlot]) -> bool:
        """Is this planned slot free time -- not a routine anchor
        (ROUTINE_ACTIVITIES and her setting's anchors: meals, work, classes
        ...), an important commitment (:func:`is_important_activity`), a
        plan agreed with the user (USER_AGREED_REASON) or a plan with people
        (SOCIAL_PLAN_REASON_PREFIX, ``LifeService.add_social_plan``: a promise
        is kept, as :meth:`revise_upcoming` keeps it)? Only free time is
        dropped on a whim (:meth:`abandons_slot`) or taken by a pressing
        need or a housemate's joint activity (``LifeService``)."""
        if slot is None:
            return False
        return not (slot.activity_name in self._routine_names or is_important_activity(slot.activity_name)
                    or slot.reason == USER_AGREED_REASON
                    or (slot.reason or "").startswith(SOCIAL_PLAN_REASON_PREFIX))

    def mark_slot_completed(self, hour: int, actual_activity: Optional[str] = None) -> None:
        """Mark a slot as completed, optionally recording what actually happened."""
        if not self._current_plan:
            return
        slot = self._current_plan.get_slot_for_hour(hour)
        if slot:
            slot.completed = True
            slot.actual_activity = actual_activity

    def revise_upcoming(self, weather: Weather, energy_level: float,
                        mood: str = "", mood_intensity: float = 0.0,
                        now: Optional[datetime] = None) -> None:
        """
        Silently revise upcoming slots if conditions have changed.

        This is the "prepared the change ahead" behavior — she adjusts
        her plans without announcing it. Upcoming is after the hour ``now``
        is in: ``LifeService`` passes her local world time; the host's wall
        clock when omitted.
        """
        if not self._current_plan:
            return

        now = now if now is not None else datetime.now()
        revised = False

        # Moods that should trigger gentle activity swaps ("low" and "anxious"
        # are the unpleasant mood labels affect_system.MOOD_LABELS gives a
        # sad or keyed-up mood). How low and how tired she must be before she
        # drops a plan is her conscientiousness's (PLAN_REVISE_* constants).
        low_moods = {"sad", "low", "anxious", "melancholic", "lonely", "overwhelmed", "exhausted"}
        mood_is_low = mood in low_moods and mood_intensity > self._revise_mood_intensity_above

        # What the swaps read (her setting's tags, ruling T9-R5): too tired,
        # a slot not already rest ("restful") becomes her fallback rest or a
        # nap; low, one not already "soothing" becomes a "gentle" one; a
        # "clear_sky" slot under clouds, and a "rained_off" one in the rain,
        # become a "rainy_day" one.
        acts = self._activities
        restful = self._setting.names_tagged("restful")
        soothing = self._setting.names_tagged("soothing")
        rest_swaps = self._setting.tag_pool("fallback_rest", acts) + self._setting.tag_pool("nap", acts)
        gentle = self._setting.tag_pool("gentle", acts)
        # How she copes on a low day (Task 15): one who seeks company counts
        # it among her comforts -- she keeps a plan to see someone, and may
        # swap to one; anyone else keeps to the gentle ones and withdraws.
        contact = self._contact_comforts() if mood_is_low and self._contact_seeking > 0 else []
        clear_sky = self._setting.names_tagged("clear_sky")
        rained_off = self._setting.names_tagged("rained_off")
        rainy_day = self._setting.tag_pool("rainy_day", acts)

        for slot in self._current_plan.slots:
            if slot.completed or slot.hour <= now.hour:
                continue
            # A promise to people (LifeService.add_social_plan) is kept whatever her mood or the weather.
            if (slot.reason or "").startswith(SOCIAL_PLAN_REASON_PREFIX):
                continue

            # Low energy: swap high-cost activities for rest (skip routine anchors)
            if (energy_level < self._revise_energy_below and slot.activity_name not in restful
                    and slot.activity_name not in self._routine_names and rest_swaps):
                old = slot.activity_name
                slot.activity_name = self._rng.choice(rest_swaps)
                slot.reason = "needed rest"
                self._note_revision(
                    f"Swapped {old} at {slot.hour}:00 for {slot.activity_name} (low energy)"
                )
                revised = True

            # Low mood: swap demanding activities for comforting ones -- the
            # comfort she would pick (_comfort_among), not any at random
            elif (mood_is_low and slot.activity_name not in soothing and slot.activity_name not in contact
                    and slot.activity_name not in self._routine_names and gentle):
                old = slot.activity_name
                slot.activity_name = self._comfort_among(gentle, contact)
                slot.reason = f"not feeling up to it"
                self._note_revision(
                    f"Swapped {old} at {slot.hour}:00 for {slot.activity_name} (low mood)"
                )
                revised = True

            # Weather changed: swap weather-dependent activities
            if slot.activity_name in clear_sky and weather not in (Weather.CLEAR_NIGHT, Weather.STARRY) and rainy_day:
                old = slot.activity_name
                slot.activity_name = rainy_day[0]
                slot.reason = "sky clouded over"
                self._note_revision(
                    f"Swapped {old} at {slot.hour}:00 for {slot.activity_name} (weather changed)"
                )
                revised = True

            # Rainy weather bonus: prefer indoor cozy activities
            if weather in (Weather.RAINY, Weather.STORMY):
                if slot.activity_name in rained_off and rainy_day:
                    slot.activity_name = self._rng.choice(rainy_day)
                    slot.reason = "staying in because of rain"
                    self._note_revision(
                        f"Moved inside at {slot.hour}:00 (rain)"
                    )
                    revised = True

        if revised:
            logger.info("Silently revised upcoming plan slots")

    def fulfill_desire(self, activity_name: str) -> Optional[ShortTermDesire]:
        """Mark a desire as fulfilled if the activity matches."""
        for desire in self._desires:
            if desire.fulfilled or self._is_expired(desire):
                continue
            if activity_name in desire.related_activities:
                desire.fulfilled = True
                desire.fulfilled_at = datetime.now()
                logger.info(f"Desire fulfilled: {desire.title}")
                return desire
        return None

    def generate_desire_from_activity(self, activity_name: str) -> Optional[ShortTermDesire]:
        """Occasionally generate a follow-up desire after an activity: the
        one her setting's ``want_follow_ups`` names for it, built fresh (a
        key it leaves out takes ``ShortTermDesire``'s own default)."""
        if self._rng.random() > 0.15:
            return None

        want = self._setting.want_follow_ups.get(activity_name)
        if not want:
            return None
        fields = {key: want[key] for key in ("title", "description", "source", "urgency") if key in want}
        template = ShortTermDesire(related_activities=list(want.get("related_activities", [])), **fields)

        # Avoid duplicates
        for existing in self._desires:
            if existing.title == template.title and not existing.fulfilled:
                return None

        template.expires_at = datetime.now() + timedelta(days=self._rng.randint(2, 5))
        self._desires.append(template)
        logger.info(f"New desire from activity: {template.title}")
        return template

    # ============= Schedule Override Methods =============
    # An override rewrites the slots still ahead: every later slot not yet
    # done, and the slot of the hour she is in whether done or not -- each
    # activity tick marks the hour's slot completed and the slot governs the
    # whole hour (Task 10), so skipping a completed one left her on the old
    # plan for the rest of the hour. A rewritten slot is not done any more.

    @staticmethod
    def _rewritable(slot: PlannedSlot, now_hour: int) -> bool:
        """May an override rewrite ``slot``: the hour she is in, or a later,
        uncompleted one?"""
        return slot.hour == now_hour or (slot.hour > now_hour and not slot.completed)

    @staticmethod
    def _rewritten(slot: PlannedSlot) -> None:
        slot.completed = False
        slot.actual_activity = None

    def cancel_work_today(self, now: Optional[datetime] = None) -> None:
        """Replace remaining work/class/study/commute slots with 'relaxing' at home.

        "Remaining" is judged against ``now``'s hour (the host's wall clock when
        omitted); ``LifeService`` passes her local world time. It includes the
        slot of the hour she is in, even once she has started it. The slots are
        the contemporary names and her setting's commitments (tags "work",
        "commute", "class", "study").
        """
        if not self._current_plan:
            return
        work_activities = {"working", "attending classes", "studying", "commuting"} | self._commitment_names
        now_hour = (now if now is not None else datetime.now()).hour
        # A cancelled slot becomes her rest (tag "fallback_rest": the
        # contemporary "relaxing"); with none in her setting it is dropped.
        rest = self._fallback_rest(ai=self._is_ai)
        dropped = []
        for slot in self._current_plan.slots:
            if self._rewritable(slot, now_hour) and slot.activity_name in work_activities:
                if rest is None:
                    dropped.append(slot)
                    continue
                slot.activity_name = rest
                slot.location = "home"
                slot.reason = "day off"
                self._rewritten(slot)
        if dropped:
            self._current_plan.slots = [s for s in self._current_plan.slots if s not in dropped]
        self._note_revision("Cancelled remaining work — taking the day off")
        logger.info("Schedule override: cancelled remaining work slots")

    def override_current_location(self, location: str, now: Optional[datetime] = None) -> None:
        """Set the current and next slot's location.

        The current slot is the latest at or before ``now``'s hour (done or
        not), the next the first later one not done
        (:meth:`DailyPlan.get_current_slot`, :meth:`DailyPlan.get_next_slot`);
        ``now`` omitted, the host's wall clock. ``LifeService`` passes her
        local world time."""
        if not self._current_plan:
            return
        current = self._current_plan.get_current_slot(now)
        next_slot = self._current_plan.get_next_slot(now)
        if current:
            current.location = location
            self._rewritten(current)
        if next_slot:
            next_slot.location = location
        self._note_revision(f"Moved to {location}")
        logger.info(f"Schedule override: moved to {location}")

    def stay_at_current_location(self, now: Optional[datetime] = None) -> None:
        """Set all remaining slots to the current location.

        "Remaining" is judged against ``now``'s hour (the host's wall clock when
        omitted); ``LifeService`` passes her local world time. It includes the
        slot of the hour she is in, even once she has started it. The current
        location is that of her slot at ``now``
        (:meth:`DailyPlan.get_current_slot`).
        """
        if not self._current_plan:
            return
        current = self._current_plan.get_current_slot(now)
        current_loc = current.location if current else "home"
        now_hour = (now if now is not None else datetime.now()).hour
        for slot in self._current_plan.slots:
            if self._rewritable(slot, now_hour):
                slot.location = current_loc
                self._rewritten(slot)
        self._note_revision(f"Staying at {current_loc}")
        logger.info(f"Schedule override: staying at {current_loc}")

    def schedule_rendezvous(self, location: str, now: Optional[datetime] = None) -> None:
        """Update the current and next slot(s) to reflect a planned meeting arrival.

        Sets activity to her setting's meetup (tag "meetup": the contemporary
        'meeting up'; a setting without one keeps each slot's own activity)
        and location to the destination for the current slot and the next
        uncompleted slot. Only slots from ``now``'s hour on count (the host's
        wall clock when omitted), the hour she is in even once started;
        ``LifeService`` passes her local world time.
        """
        if not self._current_plan:
            return
        now_hour = (now if now is not None else datetime.now()).hour
        meetup = self._anchors["meetup"]
        updated = 0
        for slot in self._current_plan.slots:
            if self._rewritable(slot, now_hour) and updated < 2:
                if meetup:
                    slot.activity_name = meetup
                slot.location = location
                slot.reason = "planned meetup"
                self._rewritten(slot)
                updated += 1
        self._note_revision(f"Meeting at {location}")
        logger.info(f"Schedule rendezvous: meeting at {location}")

    def join_activity(self, activity_name: str, location: str, reason: str, now: datetime) -> None:
        """Joining someone in ``activity_name`` at ``location`` takes the hour
        she is in (humanness program Task 28, ruling T13-R1): the slot of
        ``now``'s hour becomes that activity there, for ``reason``, and is not
        done any more, like any override's (:meth:`_rewritten`); an hour her
        plan left empty gains the slot, so it is her current one
        (:meth:`DailyPlan.get_current_slot`) and a later sync of her plan
        keeps her where the activity is. Every other hour stays as planned.
        ``now`` is her local world time (``LifeService`` passes it); there is
        no host-clock default."""
        if not self._current_plan:
            return
        hour = now.hour
        slot = self._current_plan.get_slot_for_hour(hour)
        if slot is None:
            self._current_plan.slots.append(
                PlannedSlot(hour=hour, activity_name=activity_name, reason=reason, location=location))
            # Keep slots ordered by hour (matches how generated plans are built).
            self._current_plan.slots.sort(key=lambda s: s.hour)
        else:
            slot.activity_name = activity_name
            slot.location = location
            slot.reason = reason
            self._rewritten(slot)
        self._note_revision(f"Joined {activity_name} at {location}, {hour:02d}:00 ({reason})")
        logger.info(f"Schedule override: {activity_name} at {location} for {hour:02d}:00 ({reason})")

    def set_planned_activity(
        self,
        hour: int,
        activity_name: str,
        location: str = "",
        reason: str = USER_AGREED_REASON,
        now: Optional[datetime] = None,
    ) -> None:
        """Upsert a FUTURE slot in today's plan from a conversation commitment.

        If a slot already exists at `hour`, its activity/location/reason are
        updated; otherwise a new PlannedSlot is inserted and the slot list is
        kept ordered by hour. If `location` is empty it's resolved via
        `_resolve_location_for_activity`.

        A slot whose hour has already passed today is moot — we skip it rather
        than rewriting history. (Same hour as "now" is allowed: it's still the
        active window.) ``now`` is the instant "already passed" is judged
        against (the host's wall clock when omitted); ``LifeService`` passes
        her local world time.
        """
        if not self._current_plan:
            logger.warning("set_planned_activity: no current plan; ignoring")
            return
        if not (0 <= hour <= 23):
            logger.warning(f"set_planned_activity: hour {hour} out of range; ignoring")
            return
        current_hour = (now if now is not None else datetime.now()).hour
        if hour < current_hour:
            logger.info(f"set_planned_activity: hour {hour:02d}:00 already passed; ignoring")
            return

        loc = location.strip() if location else self._resolve_location_for_activity(activity_name)

        existing = self._current_plan.get_slot_for_hour(hour)
        if existing:
            existing.activity_name = activity_name
            existing.location = loc
            existing.reason = reason
            existing.completed = False
            existing.actual_activity = None
        else:
            self._current_plan.slots.append(
                PlannedSlot(
                    hour=hour,
                    activity_name=activity_name,
                    reason=reason,
                    location=loc,
                )
            )
            # Keep slots ordered by hour (matches how generated plans are built).
            self._current_plan.slots.sort(key=lambda s: s.hour)

        self._note_revision(
            f"Planned {activity_name} at {hour:02d}:00 ({reason})"
        )
        logger.info(f"Planned activity set: {hour:02d}:00 — {activity_name} @ {loc}")

    def _comfort_among(self, gentle: List[str], contact: Sequence[str] = ()) -> str:
        """The gentle activity a low mood swaps a slot for: drawn by who she
        is -- what she is into and how her traits lean her, the weights her
        free hours are planned by (``ActivityPreferences.plan_preference``,
        Task 10) -- not uniformly, so a bad day still looks like her own
        (Task 14 fix round, ruling T14-R1: a day's quality makes low days,
        and a uniform comfort made every persona's low day the same).

        ``contact``: the company a persona who seeks it counts among her
        comforts (Task 15, :meth:`_contact_comforts`), each weighed the same
        way times how far she seeks it (``contact_seeking``, the context of
        ``choice_weight``). None -- everyone else -- is the gentle ones
        alone, the one draw it always was."""
        by_name = {activity.name: activity for activity in self._activities}
        names = list(gentle) + [name for name in contact if name not in gentle]
        weights = [choice_weight(1.0 if index < len(gentle) else self._contact_seeking,
                                 self._preferences.plan_preference(by_name[name]))
                   for index, name in enumerate(names)]
        return self._rng.choices(names, weights=weights)[0]

    def _contact_comforts(self) -> List[str]:
        """The company she can plan on a low day: her activities that meet her
        need for other people (``ActivityPreferences.satisfaction``'s
        "social": the social ones) and that a free hour may hold -- no anchor
        of her day, nothing that happens only when a plan says so, nothing
        physical for an AI persona."""
        return [activity.name for activity in self._activities
                if self._preferences.satisfaction(activity).get("social", 0.0) > 0
                and activity.name not in self._anchor_names
                and not activity.tags & set(PLAN_ONLY_TAGS)
                and not (self._is_ai and "physical" in activity.tags)]

    def _note_revision(self, note: str) -> None:
        """Record a silent plan revision, keeping the list bounded.

        The plan is replaced daily, but `apply_schedule_override` adds one note
        per user schedule command, and the whole list is JSON-serialized into
        the `life_daily_plan` row — so a chatty day would otherwise produce an
        arbitrarily large row.
        """
        if not self._current_plan:
            return
        self._current_plan.revision_notes.append(note)
        # Keep last MAX_REVISION_NOTES notes
        if len(self._current_plan.revision_notes) > self.MAX_REVISION_NOTES:
            self._current_plan.revision_notes = (
                self._current_plan.revision_notes[-self.MAX_REVISION_NOTES:]
            )

    def load_state(self, plan: Optional[DailyPlan], desires: List[ShortTermDesire]) -> None:
        """Load persisted state."""
        self._current_plan = plan
        self._desires = desires

    def export_state(self, now: Optional[datetime] = None) -> dict:
        """Structured dict for LLM pipeline digest passes: her slot, her next
        one and what is done and still ahead, at the hour ``now`` is in
        (``LifeService`` passes her local world time; the host's wall clock
        when omitted)."""
        current_slot = None
        next_slot = None
        completed_count = 0
        remaining_count = 0
        if self._current_plan:
            slot = self._current_plan.get_current_slot(now)
            if slot:
                current_slot = {
                    "activity": slot.activity_name,
                    "location": slot.location,
                    "reason": slot.reason,
                }
            # Find next uncompleted slot
            now_hour = (now if now is not None else datetime.now()).hour
            for s in self._current_plan.slots:
                if s.hour > now_hour and not s.completed:
                    next_slot = {"activity": s.activity_name, "hour": s.hour}
                    break
            for s in self._current_plan.slots:
                if s.completed:
                    completed_count += 1
                elif s.hour <= now_hour:
                    pass  # current or past
                else:
                    remaining_count += 1
        return {
            "current_slot": current_slot,
            "next_slot": next_slot,
            "completed_today": completed_count,
            "remaining": remaining_count,
        }

    def get_schedule_summary(self) -> str:
        """Get a human-readable summary of today's plan."""
        if not self._current_plan:
            return "No plan for today yet."

        lines = []
        for slot in self._current_plan.slots:
            status = "done" if slot.completed else "planned"
            actual = f" (actually: {slot.actual_activity})" if slot.actual_activity and slot.actual_activity != slot.activity_name else ""
            lines.append(f"  {slot.hour:02d}:00 - {slot.activity_name} [{slot.reason}] ({status}){actual}")
        return "\n".join(lines)

    def get_desires_summary(self) -> str:
        """Get a summary of current desires."""
        active = self.desires
        if not active:
            return "No particular wants right now."
        return "\n".join(f"  - {d.title}: {d.description}" for d in active[:5])

    # ============= Private Methods =============

    # --- Occupation-aware schedule generation ---

    def _roll_day_chaos(self, today: str, weekday: int) -> str:
        """Roll a day-level chaos modifier for schedule variety.

        Uses a date-seeded RNG so the same date always produces the same result.
        Only rolls on days that would normally have work for this occupation type.
        """
        # Check for public holidays first (her setting's calendar)
        parts = today.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        holidays = self._setting.holidays_for(self._nationality, year)
        if (month, day) in holidays:
            return "holiday"

        # Determine if today is a work day for this type
        is_work_day = False
        occ = self._occupation_type
        if occ == OCC_STANDARD:
            is_work_day = weekday < 5  # Mon-Fri
        elif occ == OCC_STUDENT:
            is_work_day = weekday < 5
        elif occ == OCC_SERVICE:
            is_work_day = weekday < 6 or random.Random(zlib.crc32((today + "sun").encode("utf-8"))).random() < 0.20
        elif occ == OCC_CREATIVE:
            if weekday >= 5:
                is_work_day = random.Random(zlib.crc32((today + "cre_wknd").encode("utf-8"))).random() >= 0.50
            else:
                is_work_day = True

        if not is_work_day:
            return "day_off"

        # Seeded roll for consistency within the same day
        rng = random.Random(zlib.crc32((today + self._occupation).encode("utf-8")))
        roll = rng.random()

        # Creative workers take occasional unplanned days off; others don't
        if occ == OCC_CREATIVE and roll < 0.04:
            return "day_off"

        # Sick days: rare but realistic for all occupation types
        sick_threshold = 0.04 if occ != OCC_CREATIVE else 0.08
        if roll < sick_threshold:
            return "sick_day"

        # WFH: standard workers only
        if occ == OCC_STANDARD and roll < 0.12:
            return "wfh"

        # Late start: uncommon — school and work have fixed start times
        late_threshold = 0.17 if occ == OCC_STANDARD else 0.09
        if roll < late_threshold:
            return "late_start"

        return "normal"

    def _generate_work_blocks(
        self,
        today: str,
        weekday: int,
        chaos: str,
        wake: int,
        lunch_offset: int,
        dinner_offset: int,
        awake_span: int,
        routine_offsets: set,
        _h,
    ) -> Tuple[List[PlannedSlot], List[PlannedSlot]]:
        """Dispatch to the appropriate occupation-type schedule generator.

        Returns (work_slots, commute_slots).
        """
        occ = self._occupation_type
        if occ == OCC_STUDENT:
            return self._generate_student_schedule(
                today, weekday, chaos, wake, lunch_offset, dinner_offset,
                awake_span, routine_offsets, _h,
            )
        elif occ == OCC_SERVICE:
            return self._generate_service_shift(
                today, weekday, chaos, wake, lunch_offset, dinner_offset,
                awake_span, routine_offsets, _h,
            )
        elif occ == OCC_CREATIVE:
            return self._generate_creative_work(
                today, weekday, chaos, wake, lunch_offset, dinner_offset,
                awake_span, routine_offsets, _h,
            )
        else:
            # OCC_STANDARD (and fallback)
            return self._generate_standard_work(
                today, weekday, chaos, wake, lunch_offset, dinner_offset,
                awake_span, routine_offsets, _h,
            )

    def _make_commute_pair(
        self, first_work_offset: int, last_work_offset: int,
        routine_offsets: set, awake_span: int, _h, chaos: str,
    ) -> List[PlannedSlot]:
        """Create commute slots before/after work if workplace != home and not
        WFH -- and her setting has a commute activity (tag "commute")."""
        commute = self._anchors["commute"]
        if chaos == "wfh" or not commute:
            return []
        work_loc = self._pick_location("workplace", fallback="home")
        if work_loc == "home":
            return []

        commute_slots = []

        # Commute to work: 1 offset before first work slot
        before = first_work_offset - 1
        if before >= 2 and before not in routine_offsets and self._rng.random() < 0.70:
            commute_slots.append(PlannedSlot(
                hour=_h(before),
                activity_name=commute,
                reason="heading to work",
                location="in transit",
            ))

        # Commute home: 1 offset after last work slot
        after = last_work_offset + 1
        if after < awake_span - 1 and after not in routine_offsets and self._rng.random() < 0.70:
            commute_slots.append(PlannedSlot(
                hour=_h(after),
                activity_name=commute,
                reason="heading home",
                location="in transit",
            ))

        return commute_slots

    def _generate_shift_window_work(
        self, shift_start: int, shift_end: int, wake: int, awake_span: int,
        routine_offsets: set, _h, chaos: str,
    ) -> Tuple[List[PlannedSlot], List[PlannedSlot]]:
        """Place a 'working' block across the Job engine's shift window (absolute
        clock hours shift_start..shift_end), skipping meal/routine slots, with
        commute. This is the schedule-driven path — days are gated by the caller.
        Her setting's work activity (tag "work"); none, and no block.
        """
        work = self._anchors["work"]
        if not work:
            return [], []
        is_wfh = chaos == "wfh"
        work_loc = "home" if is_wfh else self._pick_location("workplace", fallback="home")
        late = 1 if chaos == "late_start" else 0

        # Overnight shifts aren't modelled by the Job engine; guard anyway.
        if shift_end <= shift_start:
            shift_end = shift_start + 8

        work_offsets = []
        for clock_h in range(shift_start + late, shift_end):
            off = (clock_h - wake) % 24
            if 2 <= off < awake_span - 1 and off not in routine_offsets:
                work_offsets.append(off)
        work_offsets = sorted(set(work_offsets))

        work_slots = [
            PlannedSlot(hour=_h(off), activity_name=work, reason="work", location=work_loc)
            for off in work_offsets
        ]
        commute_slots = []
        if work_offsets:
            commute_slots = self._make_commute_pair(
                work_offsets[0], work_offsets[-1],
                routine_offsets, awake_span, _h, chaos,
            )
        return work_slots, commute_slots

    def _generate_standard_work(
        self, today, weekday, chaos, wake, lunch_offset, dinner_offset,
        awake_span, routine_offsets, _h,
    ) -> Tuple[List[PlannedSlot], List[PlannedSlot]]:
        """Generate 8h Mon-Fri office/professional schedule (her setting's
        work activity, tag "work"; none, and no schedule)."""
        work = self._anchors["work"]
        # Weekends: no work
        if weekday >= 5 or not work:
            return [], []

        target_hours = 8
        start_offset = 3 if chaos == "late_start" else 2
        is_wfh = chaos == "wfh"
        work_loc = "home" if is_wfh else self._pick_location("workplace", fallback="home")

        work_offsets = []
        # Morning block: start_offset up to lunch
        for off in range(start_offset, lunch_offset):
            if off not in routine_offsets and len(work_offsets) < target_hours:
                work_offsets.append(off)
        # Afternoon block: lunch+1 up to dinner
        for off in range(lunch_offset + 1, dinner_offset):
            if off not in routine_offsets and len(work_offsets) < target_hours:
                work_offsets.append(off)

        work_slots = [
            PlannedSlot(hour=_h(off), activity_name=work, reason="work", location=work_loc)
            for off in work_offsets
        ]

        commute_slots = []
        if work_offsets:
            commute_slots = self._make_commute_pair(
                work_offsets[0], work_offsets[-1],
                routine_offsets, awake_span, _h, chaos,
            )

        return work_slots, commute_slots

    def _generate_student_schedule(
        self, today, weekday, chaos, wake, lunch_offset, dinner_offset,
        awake_span, routine_offsets, _h,
    ) -> Tuple[List[PlannedSlot], List[PlannedSlot]]:
        """Generate scattered class + study blocks for students (her
        setting's class and study activities, tags "class" and "study"; a
        kind her setting has none of is left out)."""
        rng = random.Random(zlib.crc32((today + "student").encode("utf-8")))
        attend, study = self._anchors["class"], self._anchors["study"]

        # Weekends
        if weekday == 6:  # Sunday: off
            return [], []
        if weekday == 5:  # Saturday: 60% chance of 1-2 study hours
            if rng.random() >= 0.60:
                return [], []
            study_count = rng.randint(1, 2)
            study_start = rng.randint(3, max(3, lunch_offset + 1))
            study_slots = []
            for i in range(study_count):
                off = study_start + i
                if off not in routine_offsets and off < dinner_offset:
                    loc = "home" if rng.random() >= 0.50 else self._pick_location("library", "cafe", fallback="home")
                    if study:
                        study_slots.append(PlannedSlot(
                            hour=_h(off), activity_name=study,
                            reason="weekend study", location=loc,
                        ))
            return study_slots, []

        # Weekdays: heavy vs light day
        if weekday in (0, 2, 4):  # Mon/Wed/Fri
            is_heavy = rng.random() < 0.75
        else:  # Tue/Thu
            is_heavy = rng.random() < 0.25

        if is_heavy:
            num_classes = rng.randint(4, 5)
            num_study = rng.randint(1, 2)
        else:
            num_classes = rng.randint(2, 3)
            num_study = 1

        # Pick scattered class offsets (with gaps)
        available_offsets = [
            off for off in range(2, dinner_offset)
            if off not in routine_offsets
        ]
        class_offsets = []
        if available_offsets:
            # Start from a random early offset
            cursor = 0
            while len(class_offsets) < num_classes and cursor < len(available_offsets):
                off = available_offsets[cursor]
                class_offsets.append(off)
                # Skip 1-2 offsets to create gaps between classes
                gap = rng.randint(1, 2) if len(class_offsets) < num_classes else 1
                cursor += gap + 1

        # Study slots: after last class or in gaps
        study_offsets = []
        if class_offsets:
            study_start = class_offsets[-1] + 1
        else:
            study_start = lunch_offset + 1
        for off in range(study_start, dinner_offset):
            if off not in routine_offsets and off not in class_offsets and len(study_offsets) < num_study:
                study_offsets.append(off)

        campus_loc = self._pick_location("school", "campus", "workplace", fallback="home")

        class_offsets = class_offsets if attend else []
        class_slots = [
            PlannedSlot(
                hour=_h(off), activity_name=attend,
                reason="class", location=campus_loc,
            )
            for off in class_offsets
        ]

        study_slots = []
        for off in study_offsets:
            if rng.random() < 0.50:
                loc = self._pick_location("library", "cafe", fallback="home")
            else:
                loc = campus_loc if campus_loc != "home" else "home"
            if study:
                study_slots.append(PlannedSlot(
                    hour=_h(off), activity_name=study,
                    reason="study session", location=loc,
                ))
        study_offsets = study_offsets if study else []

        all_work_offsets = sorted(class_offsets + study_offsets)
        work_slots = class_slots + study_slots

        # Commute to/from campus
        commute_slots = []
        if all_work_offsets and campus_loc != "home":
            commute_slots = self._make_commute_pair(
                all_work_offsets[0], all_work_offsets[-1],
                routine_offsets, awake_span, _h, chaos,
            )
            # Override commute reasons for students
            for cs in commute_slots:
                if "heading to" in cs.reason:
                    cs.reason = "heading to campus"
                elif "heading home" in cs.reason:
                    cs.reason = "heading home"

        return work_slots, commute_slots

    def _generate_service_shift(
        self, today, weekday, chaos, wake, lunch_offset, dinner_offset,
        awake_span, routine_offsets, _h,
    ) -> Tuple[List[PlannedSlot], List[PlannedSlot]]:
        """Generate shift-based schedule for service workers (her setting's
        work activity, tag "work"; none, and no shift)."""
        work = self._anchors["work"]
        if not work:
            return [], []
        rng = random.Random(zlib.crc32((today + "service").encode("utf-8")))

        shift_hours = rng.randint(6, 8)
        work_loc = self._pick_location("workplace", fallback="home")
        lower_occ = self._occupation.lower()

        # Determine shift timing
        evening_keywords = {"barmaid", "bartender", "bouncer", "dancer", "striptease", "stripper"}
        rotating_keywords = {"nurse", "paramedic"}

        is_evening = any(kw in lower_occ for kw in evening_keywords)
        is_rotating = any(kw in lower_occ for kw in rotating_keywords)

        if is_evening:
            # Evening shift: end near bedtime, work backwards
            shift_end_offset = awake_span - 2
            shift_start_offset = max(2, shift_end_offset - shift_hours)
        elif is_rotating:
            # Alternate morning/afternoon by date hash
            if zlib.crc32(today.encode("utf-8")) % 2 == 0:
                shift_start_offset = 2  # morning
            else:
                shift_start_offset = lunch_offset + 1  # afternoon
        else:
            # Default: morning shift like standard
            shift_start_offset = 2

        if chaos == "late_start":
            shift_start_offset += 1

        # Build continuous work block
        work_offsets = []
        for off in range(shift_start_offset, shift_start_offset + shift_hours):
            if off < awake_span - 1 and off not in routine_offsets:
                work_offsets.append(off)

        work_slots = [
            PlannedSlot(hour=_h(off), activity_name=work, reason="shift", location=work_loc)
            for off in work_offsets
        ]

        commute_slots = []
        if work_offsets:
            commute_slots = self._make_commute_pair(
                work_offsets[0], work_offsets[-1],
                routine_offsets, awake_span, _h, chaos,
            )

        return work_slots, commute_slots

    def _generate_creative_work(
        self, today, weekday, chaos, wake, lunch_offset, dinner_offset,
        awake_span, routine_offsets, _h,
    ) -> Tuple[List[PlannedSlot], List[PlannedSlot]]:
        """Generate flexible/short work blocks for creative occupations (her
        setting's work activity, tag "work"; none, and no block)."""
        work = self._anchors["work"]
        if not work:
            return [], []
        rng = random.Random(zlib.crc32((today + "creative").encode("utf-8")))

        work_hours = rng.randint(2, 4)

        # 40% chance of working from home regardless of chaos roll
        is_home = chaos == "wfh" or rng.random() < 0.40
        work_loc = "home" if is_home else self._pick_location("workplace", fallback="home")

        # Pick a creative reason based on occupation keywords
        lower_occ = self._occupation.lower()
        if "singer" in lower_occ or "musician" in lower_occ or "composer" in lower_occ:
            reason = "rehearsal"
        elif "writer" in lower_occ or "author" in lower_occ or "poet" in lower_occ:
            reason = "writing session"
        elif "performer" in lower_occ or "actor" in lower_occ or "actress" in lower_occ:
            reason = "performing"
        else:
            reason = "creative work"

        if chaos == "late_start":
            start = 3
        else:
            start = 2

        # Split blocks: if 4 hours, split into two 2h blocks with a gap
        if work_hours >= 4:
            block1_offsets = []
            for off in range(start, lunch_offset):
                if off not in routine_offsets and len(block1_offsets) < 2:
                    block1_offsets.append(off)
            block2_offsets = []
            for off in range(lunch_offset + 1, dinner_offset):
                if off not in routine_offsets and len(block2_offsets) < 2:
                    block2_offsets.append(off)
            work_offsets = block1_offsets + block2_offsets
        else:
            # Single continuous block, prefer morning
            work_offsets = []
            for off in range(start, dinner_offset):
                if off not in routine_offsets and len(work_offsets) < work_hours:
                    work_offsets.append(off)

        work_slots = [
            PlannedSlot(hour=_h(off), activity_name=work, reason=reason, location=work_loc)
            for off in work_offsets
        ]

        commute_slots = []
        if work_offsets and not is_home:
            commute_slots = self._make_commute_pair(
                work_offsets[0], work_offsets[-1],
                routine_offsets, awake_span, _h, chaos,
            )

        return work_slots, commute_slots

    # --- Desire management ---

    def _build_own_wants(self, definition, interests, media_preferences) -> List[Dict]:
        """Her own wants, from her definition's seeds (the templates at the
        top of this module), each with the activities of her setting that
        meet it -- the day's anchors aside; a seed nothing meets is dropped,
        and so is a title another seed already gave."""
        def field(name, default):
            return (getattr(definition, name, default) if definition is not None else default) or default

        pool = [a for a in self._activities if a.name not in self._anchor_names]
        wants: List[Dict] = []

        def add(frame: Dict[str, str], text: str, related: List[str]) -> None:
            text = str(text or "").strip().rstrip(".").strip()
            if not text or not related:
                return
            title = frame["title"].format(text=text)
            if any(want["title"] == title for want in wants):
                return
            wants.append({"title": title, "description": frame["description"],
                          "related_activities": related, "source": DesireSource.PERSONALITY})

        for text in (interests or field("interests", [])):
            add(INTEREST_WANT, text, matching_activities(text, pool))
        for text in field("comfort_zone_seeds", []):
            add(COMFORT_ZONE_WANT, text, matching_activities(text, pool))
        # A food taste is met by her meals: those that are not the day's
        # anchors, or -- when she has none but them (a pack relying on the
        # universal meal) -- her anchor meals.
        meals = ([a.name for a in pool if "meal" in a.tags]
                 or [a.name for a in self._activities if "meal" in a.tags])
        for kind, items in field("taste_seeds", {}).items():
            kind_text = str(kind).strip().lower()
            for item in ([items] if isinstance(items, str) else items or []):
                related = matching_activities(f"{kind_text} {item}", pool)
                if kind_text in FOOD_TASTES:
                    related = related + [name for name in meals if name not in related]
                add(TASTE_WANTS.get(kind_text, TASTE_WANT), item, related)
        for kind, items in (media_preferences or field("media_preferences", {})).items():
            kind_text = str(kind).strip().lower()
            related = matching_activities(kind_text, pool)
            for item in ([items] if isinstance(items, str) else items or []):
                add(MEDIA_WANTS.get(kind_text, MEDIA_WANT), item,
                    related + [n for n in matching_activities(item, pool) if n not in related])
        for substance, tendency in field("substance_tendencies", {}).items():
            tag = SUBSTANCE_TAGS.get(str(substance).strip().lower())
            pull = SUBSTANCE_FREQUENCY.get(str(tendency or "").strip().lower(), SUBSTANCE_UNKNOWN_FREQUENCY)
            if tag in SUBSTANCE_WANTS and pull > 0:
                frame = SUBSTANCE_WANTS[tag]
                related = [a.name for a in pool if tag in a.tags]
                if related and not any(want["title"] == frame["title"] for want in wants):
                    wants.append({"title": frame["title"], "description": frame["description"],
                                  "related_activities": related, "source": DesireSource.PERSONALITY})
        return wants

    def _refresh_desires(self, goals: List[Goal]) -> None:
        """Ensure there are enough active desires. Generate new ones if needed,
        from her own wants and her setting's, taken in turn (hers first)."""
        # Clean expired/fulfilled
        self._desires = [
            d for d in self._desires
            if not self._is_expired(d) or d.fulfilled
        ]

        active_count = len(self.desires)
        if active_count >= 3:
            return  # Enough desires

        # Only regenerate once per day
        now = datetime.now()
        if self._last_desire_generation and self._last_desire_generation.date() == now.date():
            return

        # Generate 2-4 new desires
        num_new = self._rng.randint(2, 4) - active_count
        if num_new <= 0:
            return

        existing_titles = {d.title for d in self._desires}
        own = [t for t in self._own_wants if t["title"] not in existing_titles]
        shared = [t for t in self._setting.wants if t["title"] not in existing_titles]
        # Hers and her setting's in turn (hers first). With none of her own
        # this is her setting's alone, drawn exactly as before.
        self._rng.shuffle(own)
        self._rng.shuffle(shared)
        available = [t for pair in zip_longest(own, shared) for t in pair if t is not None]

        for template in available[:num_new]:
            desire = ShortTermDesire(
                title=template["title"],
                description=template.get("description", ""),
                source=template.get("source", DesireSource.PERSONALITY),
                related_activities=template.get("related_activities", []),
                urgency=0.4 + self._rng.random() * 0.4,
                expires_at=now + timedelta(days=self._rng.randint(2, 5)),
            )

            # Link to a goal if activities overlap
            for goal in goals:
                if set(desire.related_activities) & set(goal.related_activities):
                    desire.related_goal_title = goal.title
                    desire.urgency = min(1.0, desire.urgency + 0.15)
                    break

            self._desires.append(desire)

        self._last_desire_generation = now
        logger.info(f"Generated {num_new} new desires (total active: {len(self.desires)})")

    def _select_activity_for_slot(
        self,
        preferred_times: List[TimeOfDay],
        goals: List[Goal],
        desires: List[ShortTermDesire],
        activity_map: Dict[str, Activity],
        recent: List[str],
        weather: Weather,
        used: List[str],
        is_ai: bool = False,
        habit: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> Tuple[Optional[str], str]:
        """
        Select a single activity for a slot.

        Priority:
        1. Desire with high urgency (40% chance if available)
        2. Goal-aligned activity (30% chance if available)
        3. Best-fit activity from the pool

        ``habit`` is ``{activity: (raise, damp)}`` for the slot's part of her day (see ``_slot_draw``).
        """
        candidates: List[Tuple[str, float, str]] = []  # (name, score, reason)
        # A free hour is never planned with one of the day's anchors (a meal,
        # a shift, waking up ...): they have their own slots.
        activity_map = {name: a for name, a in activity_map.items() if name not in self._anchor_names}

        # Desire-driven candidates
        for desire in desires:
            for act_name in desire.related_activities:
                if act_name in activity_map and act_name not in used:
                    activity = activity_map[act_name]
                    if any(t in activity.preferred_times for t in preferred_times):
                        score = desire.urgency * 2.0
                        candidates.append((act_name, score, f"want: {desire.title}"))

        # Goal-driven candidates
        for goal in goals:
            for act_name in goal.related_activities:
                if act_name in activity_map and act_name not in used:
                    activity = activity_map[act_name]
                    if any(t in activity.preferred_times for t in preferred_times):
                        score = 1.5
                        if goal.involves_user:
                            score += 0.5
                        candidates.append((act_name, score, f"goal: {goal.title}"))

        # General pool candidates
        _weather_planner = _weather_planner_enabled()
        for name, activity in activity_map.items():
            # Never plan her sleep or a nap (tags "sleep"/"nap": the
            # contemporary "sleeping"/"napping").
            if name in used or {"sleep", "nap"} & activity.tags:
                continue
            if any(t in activity.preferred_times for t in preferred_times):
                score = 1.0
                if weather in activity.preferred_weather:
                    score += 0.3
                if name in recent:
                    score *= 0.4  # Variety penalty
                # Weather-based outdoor penalty/bonus: human-only (AI has no
                # physical location so outdoor weather is irrelevant to her).
                if _weather_planner and not is_ai and "outdoor" in activity.tags:
                    if weather in _BAD_WEATHER:
                        score = max(0.05, score + WEATHER_OUTDOOR_PENALTY)
                    elif weather in _GOOD_WEATHER:
                        score += WEATHER_OUTDOOR_BONUS
                candidates.append((name, score, "routine"))

        if not candidates:
            # Her rest (tag "fallback_rest": the contemporary "relaxing"),
            # or nothing when her setting has none.
            return self._fallback_rest(ai=is_ai), "free time"

        # Who she is weighs every candidate: what she is into and how far
        # her traits lean her to it (Task 10; aura_life.activities.choice).
        candidates = [
            (name, choice_weight(score, self._preferences.plan_preference(activity_map[name])), reason)
            for name, score, reason in candidates
        ]

        # Weighted random selection from top candidates, reweighted by her habits
        top, weights = _slot_draw(candidates, habit)

        selected = self._rng.choices(top, weights=weights)[0]
        return selected[0], selected[2]

    def _first_tagged(self, tag: str) -> Optional[str]:
        """Her first activity carrying ``tag``, in her setting's tag order
        (:meth:`~aura_life.settings.SettingSpec.tag_pool`), or None."""
        names = self._setting.tag_pool(tag, self._activities)
        return names[0] if names else None

    def _fallback_rest(self, ai: bool = False) -> Optional[str]:
        """Her first activity tagged "fallback_rest" (the contemporary
        "relaxing"), from her own catalogue -- its non-physical part for an
        AI persona -- or None when her setting has none."""
        pool = [a for a in self._activities if not ai or "physical" not in a.tags]
        names = self._setting.tag_pool("fallback_rest", pool)
        return names[0] if names else None

    def _has_location(self, key: str) -> bool:
        """Check if a location key is available for this persona."""
        return key.lower() in self._available_location_keys

    def _pick_location(self, *candidates: str, fallback: str = "home") -> str:
        """Return the first candidate location that the persona has, else fallback."""
        for c in candidates:
            if self._has_location(c):
                return c.lower()
        return fallback

    def _resolve_location_for_activity(self, activity_name: str, category: str = "", activity_def: Optional[Activity] = None) -> str:
        """Assign a persona-aware location key to a routine/hobby activity.

        Resolution order:
        1. Hard-coded rules for routines (waking up, meals, sleeping = home, etc.)
        2. Activity.suitable_locations scored with variety penalty
        3. Fallback heuristics based on activity name
        """
        name = activity_name.lower()

        # --- Always home (routines, cooking, gaming, phone calls) ---
        if name in ("waking up", "getting ready for bed", "sleeping",
                     "morning shower", "skincare routine",
                     "cooking a meal", "baking something", "trying a new recipe",
                     "cooking", "baking",
                     "gaming", "playing games", "watching tv", "watching a movie",
                     "making hot chocolate", "watching the snow fall", "online shopping",
                     "texting a friend", "video call with a friend", "catching up with family",
                     "tidying up"):
            return "home"

        # --- Meals: 20% eat out for lunch, 15% for dinner/breakfast ---
        if name == "having lunch":
            if self._rng.random() < 0.20:
                return self._pick_location("cafe", "restaurant", fallback="home")
            return "home"
        if name in ("having breakfast", "having dinner"):
            if self._rng.random() < 0.15:
                return self._pick_location("cafe", "restaurant", fallback="home")
            return "home"

        # --- Work / school: always at workplace ---
        if name == "working":
            return self._pick_location("workplace", fallback="home")
        if name == "commuting":
            return "in transit"
        if name == "attending classes":
            return self._pick_location("school", "campus", "workplace", "library", fallback="home")

        # --- Try Activity.suitable_locations with variety scoring ---
        if activity_def and activity_def.suitable_locations:
            # Filter to locations the persona actually has
            candidates = [
                loc for loc in activity_def.suitable_locations
                if self._has_location(loc)
            ]
            if candidates:
                chosen = self._score_and_pick_location(candidates)
                if chosen:
                    return chosen

        # --- Fallback heuristics (legacy rules) ---
        if name == "studying":
            if self._rng.random() < 0.50:
                return self._pick_location("library", "cafe", fallback="home")
            return "home"

        if name in ("going for a walk", "walking"):
            return self._pick_location("park", "street", fallback="home")
        if name == "going for a run":
            return self._pick_location("park", "street", fallback="home")
        if name == "gym workout":
            return self._pick_location("gym", fallback="home")
        if name == "running errands":
            return self._pick_location("street", "cafe", fallback="home")
        if name in ("people watching",):
            return self._pick_location("cafe", "park", "bar", fallback="home")
        if name in ("having coffee with a friend", "socializing"):
            return self._pick_location("cafe", "bar", "park", fallback="home")
        if name == "lunch with coworkers":
            return self._pick_location("cafe", "workplace", fallback="home")
        if name in ("beach day",):
            return self._pick_location("beach", fallback="park")
        if name in ("collecting autumn leaves", "picnic in the park"):
            return self._pick_location("park", fallback="home")
        if name in ("exercising", "working out", "yoga"):
            return self._pick_location("gym", "park", fallback="home")
        if name in ("stretching", "meditating"):
            if self._rng.random() < 0.30:
                return self._pick_location("park", fallback="home")
            return "home"
        if name in ("reading", "learning something new", "journaling", "writing poetry",
                     "creating a playlist", "sketching ideas"):
            if self._rng.random() < 0.40:
                return self._pick_location("cafe", "library", fallback="home")
            return "home"
        if name == "listening to music":
            if self._rng.random() < 0.25:
                return self._pick_location("cafe", "park", fallback="home")
            return "home"
        if name == "tending to plants":
            return self._pick_location("park", fallback="home")
        if name == "making tea":
            if self._rng.random() < 0.35:
                return self._pick_location("cafe", fallback="home")
            return "home"
        if name == "stargazing":
            return self._pick_location("rooftop", "park", fallback="home")

        # --- Default: slight chance of being out ---
        if self._rng.random() < 0.15:
            return self._pick_location("cafe", "park", fallback="home")
        return "home"

    def _score_and_pick_location(self, candidates: List[str]) -> Optional[str]:
        """Score candidate locations with variety penalty and weighted-random pick.

        Non-home locations that were already assigned today get a 0.4x penalty.
        """
        assigned = getattr(self, "_plan_assigned_locations", [])
        scored: List[tuple] = []
        for loc in candidates:
            score = 1.0
            # Penalize re-use of non-home location in same day plan
            if loc != "home" and loc in assigned:
                score *= 0.4
            scored.append((loc, score))

        if not scored:
            return None

        total = sum(s for _, s in scored)
        if total <= 0:
            return scored[0][0]

        weights = [s / total for _, s in scored]
        chosen = self._rng.choices([loc for loc, _ in scored], weights=weights)[0]

        # Track for variety
        if hasattr(self, "_plan_assigned_locations"):
            self._plan_assigned_locations.append(chosen)

        return chosen

    def _is_expired(self, desire: ShortTermDesire) -> bool:
        """Check if a desire has expired."""
        if not desire.expires_at:
            return False
        return datetime.now() > desire.expires_at
