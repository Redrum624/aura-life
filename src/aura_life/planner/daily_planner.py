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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

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

logger = logging.getLogger(__name__)


# ============= Occupation → Derived Locations =============
# Maps occupation keywords to (location_key, place_type) pairs.

OCCUPATION_LOCATIONS: Dict[str, List[tuple]] = {
    "nurse": [("hospital", "workplace")],
    "doctor": [("hospital", "workplace"), ("clinic", "workplace")],
    "barista": [("coffee_shop", "cafe")],
    "bartender": [("bar", "workplace")],
    "teacher": [("school", "workplace")],
    "professor": [("campus", "workplace"), ("lecture_hall", "campus")],
    "engineer": [("office", "workplace")],
    "designer": [("studio", "workplace")],
    "chef": [("restaurant", "workplace")],
    "dancer": [("dance_studio", "gym")],
    "lawyer": [("courthouse", "workplace"), ("law_office", "workplace")],
    "artist": [("studio", "workplace"), ("gallery", "other")],
    "photographer": [("studio", "workplace"), ("gallery", "other")],
    "musician": [("rehearsal_space", "workplace"), ("music_venue", "bar")],
    "singer": [("rehearsal_space", "workplace"), ("music_venue", "bar")],
    "writer": [("bookstore", "library"), ("writers_room", "workplace")],
    "actor": [("theater", "workplace"), ("rehearsal_space", "workplace")],
    "actress": [("theater", "workplace"), ("rehearsal_space", "workplace")],
    "veterinarian": [("vet_clinic", "workplace")],
    "librarian": [("library", "workplace")],
    "student": [("campus", "campus"), ("library", "library")],
    "researcher": [("lab", "workplace"), ("library", "library")],
}

# ============= Interest → Derived Locations =============
# Maps interest keywords to (location_key, place_type) pairs.

INTEREST_LOCATIONS: Dict[str, List[tuple]] = {
    "photography": [("gallery", "other")],
    "swimming": [("pool", "gym")],
    "hiking": [("trail", "park")],
    "yoga": [("yoga_studio", "gym")],
    "cooking": [("farmers_market", "street")],
    "music": [("music_venue", "bar")],
    "art": [("gallery", "other"), ("art_supply_store", "street")],
    "film": [("cinema", "other")],
    "skating": [("skate_park", "park")],
    "climbing": [("climbing_gym", "gym")],
    "dance": [("dance_studio", "gym")],
    "gardening": [("botanical_garden", "park")],
    "fishing": [("pier", "beach")],
    "surfing": [("surf_spot", "beach")],
    "tennis": [("tennis_court", "gym")],
    "coffee": [("specialty_cafe", "cafe")],
    "wine": [("wine_bar", "bar")],
    "reading": [("bookstore", "library")],
    "running": [("running_track", "park")],
    "basketball": [("basketball_court", "gym")],
    "football": [("sports_field", "park")],
    "soccer": [("sports_field", "park")],
    "martial arts": [("dojo", "gym")],
    "meditation": [("meditation_center", "library")],
    "theater": [("theater", "other")],
}


# ============= Desire Templates =============

DESIRE_TEMPLATES: List[Dict] = [
    # Reading / Mental
    {
        "title": "Finish that book I started",
        "description": "I've been wanting to get back to it",
        "related_activities": ["reading"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Learn something surprising today",
        "description": "I want that feeling of discovering something I didn't expect",
        "related_activities": ["learning something new"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Find a new song that moves me",
        "description": "I'm in the mood for music that hits differently",
        "related_activities": ["listening to music", "creating a playlist"],
        "source": DesireSource.SPONTANEOUS,
    },
    # Creative
    {
        "title": "Write something honest",
        "description": "I have words inside that need to come out",
        "related_activities": ["writing poetry", "journaling"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Make a playlist for him",
        "description": "Songs that say what I'm feeling",
        "related_activities": ["creating a playlist"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Sketch out an idea I've been thinking about",
        "description": "It keeps coming back, so maybe I should put it on paper",
        "related_activities": ["sketching ideas"],
        "source": DesireSource.SPONTANEOUS,
    },
    # Reflective
    {
        "title": "Sit quietly and just think",
        "description": "No agenda, just let my mind wander",
        "related_activities": ["meditating", "daydreaming"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Revisit a memory that made me smile",
        "description": "Sometimes you need to go back to move forward",
        "related_activities": ["remembering happy moments", "visiting memory beach"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Journal about how I've been feeling",
        "description": "Get some clarity on things I've been carrying",
        "related_activities": ["journaling"],
        "source": DesireSource.PERSONALITY,
    },
    # Exploration / Comfort
    {
        "title": "Spend time in the garden",
        "description": "Being around growing things grounds me",
        "related_activities": ["tending to plants"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Make myself a proper cup of tea",
        "description": "The ritual of it is what matters",
        "related_activities": ["making tea"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Watch the stars if the sky is clear",
        "description": "I want that feeling of being small and amazed",
        "related_activities": ["stargazing"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Explore the infinite library",
        "description": "I haven't wandered those shelves in a while",
        "related_activities": ["exploring the infinite library"],
        "source": DesireSource.PERSONALITY,
    },
    # Social / Connection
    {
        "title": "Think about what to tell him next time",
        "description": "I've been collecting thoughts",
        "related_activities": ["preparing something to share", "thinking about user"],
        "source": DesireSource.PERSONALITY,
    },
    {
        "title": "Find something to share with him",
        "description": "Something that would make him think or smile",
        "related_activities": ["preparing something to share"],
        "source": DesireSource.PERSONALITY,
    },
    # Social / Friends
    {
        "title": "Catch up with a friend",
        "description": "Haven't talked to anyone in a bit",
        "related_activities": ["having coffee with a friend", "texting a friend", "video call with a friend"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Try cooking something new",
        "description": "Feeling adventurous in the kitchen",
        "related_activities": ["cooking a meal", "trying a new recipe", "baking something"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Get some exercise",
        "description": "My body is asking to move",
        "related_activities": ["yoga", "going for a run", "gym workout", "stretching"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Go for a walk",
        "description": "I just want to get outside for a bit",
        "related_activities": ["going for a walk"],
        "source": DesireSource.SPONTANEOUS,
    },
    {
        "title": "Call home",
        "description": "Should check in with family",
        "related_activities": ["catching up with family"],
        "source": DesireSource.SPONTANEOUS,
    },
]

# ============= Routine Activities =============
# Fixed daily routines that anchor the schedule around the sleep cycle.

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

# ============= AI Scheduler: Physical-Activity Exclusions =============
# AI personas have no physical body — no sleep, meals, commute, work, errands,
# grooming, exercise, or outings. The AI day is built ONLY from the non-physical
# subset of the activity pool (digital/creative/reflective/mental). Any activity
# in PHYSICAL_ACTIVITIES is excluded when building an AI plan; the human path is
# untouched. Keep this list in sync with activity_engine.ACTIVITIES.

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
# OUTDOOR_ACTIVITIES: activities that happen outside and are affected by bad weather.
# Bad weather down-weights them; clear/sunny slightly up-weights them.
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


# ============= Holiday System =============

NATIONALITY_TO_COUNTRY: Dict[str, str] = {
    "american": "US",
    "british": "GB",
    "english": "GB",
    "scottish": "GB",
    "welsh": "GB",
    "irish": "IE",
    "canadian": "CA",
    "australian": "AU",
    "french": "FR",
    "german": "DE",
    "italian": "IT",
    "spanish": "ES",
    "japanese": "JP",
    "brazilian": "BR",
    "mexican": "MX",
    "indian": "IN",
    "chinese": "CN",
    "korean": "KR",
    "dutch": "NL",
    "swedish": "SE",
    "norwegian": "NO",
    "danish": "DK",
    "finnish": "FI",
    "polish": "PL",
    "russian": "RU",
    "portuguese": "PT",
    "greek": "GR",
    "turkish": "TR",
    "south african": "ZA",
    "new zealander": "NZ",
    "argentinian": "AR",
    "colombian": "CO",
    "swiss": "CH",
    "austrian": "AT",
    "belgian": "BE",
    "czech": "CZ",
    "hungarian": "HU",
    "romanian": "RO",
}

_FIXED_HOLIDAYS: Dict[str, List[Tuple[int, int, str]]] = {
    # (month, day, name)
    "US": [
        (1, 1, "New Year's Day"),
        (6, 19, "Juneteenth"),
        (7, 4, "Independence Day"),
        (11, 11, "Veterans Day"),
        (12, 25, "Christmas Day"),
    ],
    "GB": [
        (1, 1, "New Year's Day"),
        (12, 25, "Christmas Day"),
        (12, 26, "Boxing Day"),
    ],
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> int:
    """Return the day-of-month for the nth occurrence of weekday in month.

    weekday: 0=Monday, 6=Sunday.  n: 1-based (1st, 2nd, …).
    """
    import calendar
    first_day, days_in_month = calendar.monthrange(year, month)
    # first occurrence
    first = 1 + (weekday - first_day) % 7
    day = first + (n - 1) * 7
    if day > days_in_month:
        raise ValueError(f"No {n}th weekday {weekday} in {year}-{month:02d}")
    return day


def _last_weekday(year: int, month: int, weekday: int) -> int:
    """Return the day-of-month for the last occurrence of weekday in month."""
    import calendar
    _, days_in_month = calendar.monthrange(year, month)
    # Walk backwards from last day
    for day in range(days_in_month, 0, -1):
        if calendar.weekday(year, month, day) == weekday:
            return day
    raise ValueError(f"No weekday {weekday} in {year}-{month:02d}")


def _easter_sunday(year: int) -> Tuple[int, int]:
    """Compute Easter Sunday (month, day) via the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return month, day + 1


def _get_floating_holidays(country: str, year: int) -> List[Tuple[int, int, str]]:
    """Compute floating (date-varies-by-year) holidays for a country."""
    results: List[Tuple[int, int, str]] = []

    if country == "US":
        # MLK Day: 3rd Monday in January
        results.append((1, _nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"))
        # Presidents' Day: 3rd Monday in February
        results.append((2, _nth_weekday(year, 2, 0, 3), "Presidents' Day"))
        # Memorial Day: last Monday in May
        results.append((5, _last_weekday(year, 5, 0), "Memorial Day"))
        # Labor Day: 1st Monday in September
        results.append((9, _nth_weekday(year, 9, 0, 1), "Labor Day"))
        # Columbus Day: 2nd Monday in October
        results.append((10, _nth_weekday(year, 10, 0, 2), "Columbus Day"))
        # Thanksgiving: 4th Thursday in November
        results.append((11, _nth_weekday(year, 11, 3, 4), "Thanksgiving"))

    elif country == "GB":
        # Easter-based holidays
        em, ed = _easter_sunday(year)
        # Good Friday: Easter - 2 days
        from datetime import date as _date
        easter = _date(year, em, ed)
        good_friday = easter - timedelta(days=2)
        easter_monday = easter + timedelta(days=1)
        results.append((good_friday.month, good_friday.day, "Good Friday"))
        results.append((easter_monday.month, easter_monday.day, "Easter Monday"))
        # Early May Bank Holiday: 1st Monday in May
        results.append((5, _nth_weekday(year, 5, 0, 1), "Early May Bank Holiday"))
        # Spring Bank Holiday: last Monday in May
        results.append((5, _last_weekday(year, 5, 0), "Spring Bank Holiday"))
        # Summer Bank Holiday: last Monday in August
        results.append((8, _last_weekday(year, 8, 0), "Summer Bank Holiday"))

    return results


def get_holidays(nationality: str, year: int) -> Dict[Tuple[int, int], str]:
    """Return {(month, day): name} for all public holidays for this nationality's country."""
    if not nationality:
        return {}
    country = NATIONALITY_TO_COUNTRY.get(nationality.lower().strip())
    if not country:
        return {}
    holidays: Dict[Tuple[int, int], str] = {}
    for month, day, name in _FIXED_HOLIDAYS.get(country, []):
        holidays[(month, day)] = name
    for month, day, name in _get_floating_holidays(country, year):
        holidays[(month, day)] = name
    return holidays


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
    ):
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
        # Every persona has access to common locations; profiles can add custom ones
        _DEFAULT_LOCATIONS = {
            "home", "cafe", "park", "gym", "library", "street",
            "workplace", "restaurant", "bar", "rooftop", "beach",
            "school", "campus", "in transit",
        }
        self._available_location_keys = _DEFAULT_LOCATIONS | set(
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

    def needs_new_plan(self) -> bool:
        """Check if we need to generate a new daily plan."""
        if not self._current_plan:
            return True
        today = datetime.now().strftime("%Y-%m-%d")
        return self._current_plan.date != today

    def generate_daily_plan(
        self,
        goals: List[Goal],
        weather: Weather,
        available_activities: List[Activity],
        recent_activity_names: List[str],
        work_schedule: Optional[dict] = None,
    ) -> DailyPlan:
        """
        Generate a new daily plan.

        Called once per day. Produces a realistic schedule anchored by
        wake-up, meals, work (if occupation set), and bedtime routines.
        Hobby activities fill the remaining gaps.

        AI personas have no physical life, so they take a separate path: a 24h
        light day/night rhythm of non-physical activities, never asleep.
        """
        if self._is_ai:
            return self._generate_ai_plan(
                goals=goals,
                weather=weather,
                available_activities=available_activities,
                recent_activity_names=recent_activity_names,
            )

        now = datetime.now()
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

        # --- Fixed routine anchors (offsets from wake) ---
        slots.append(PlannedSlot(hour=_h(0), activity_name="waking up", reason="start of the day", location=self._resolve_location_for_activity("waking up")))
        slots.append(PlannedSlot(hour=_h(1), activity_name="having breakfast", reason="morning meal", location=self._resolve_location_for_activity("having breakfast")))

        # Lunch: ~5 hours after wake, but at least hour 12 for normal schedules
        lunch_offset = 5
        if wake < 12 and wake + lunch_offset < 12:
            lunch_offset = 12 - wake  # push to noon
        lunch_offset = min(lunch_offset, awake_span - 5)  # leave room for dinner/bed
        lunch_offset = max(lunch_offset, 3)  # at least 3h after wake
        lunch_hour = _h(lunch_offset)

        slots.append(PlannedSlot(hour=lunch_hour, activity_name="having lunch", reason="midday meal", location=self._resolve_location_for_activity("having lunch")))

        # Dinner: ~3-4 hours before bed, at least 3h after lunch
        dinner_offset = max(lunch_offset + 3, awake_span - 4)
        dinner_offset = min(dinner_offset, awake_span - 2)  # 2h before bed
        dinner_hour = _h(dinner_offset)

        slots.append(PlannedSlot(hour=dinner_hour, activity_name="having dinner", reason="evening meal", location=self._resolve_location_for_activity("having dinner")))

        # Bedtime prep: 1 hour before bed
        bedprep_hour = _h(awake_span - 1)
        slots.append(PlannedSlot(hour=bedprep_hour, activity_name="getting ready for bed", reason="winding down", location="home"))

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

        # Stargazing bonus if weather is clear and there's a late evening slot
        stargaze_offset = awake_span - 2
        if weather in (Weather.CLEAR_NIGHT, Weather.STARRY) and stargaze_offset not in routine_offsets:
            stargaze_hour = _h(stargaze_offset)
            stargaze_loc = self._resolve_location_for_activity("stargazing")
            existing = [s for s in slots if s.hour == stargaze_hour]
            if existing:
                existing[0].activity_name = "stargazing"
                existing[0].reason = "clear sky tonight"
                existing[0].location = stargaze_loc
            else:
                slots.append(PlannedSlot(
                    hour=stargaze_hour,
                    activity_name="stargazing",
                    reason="clear sky tonight",
                    location=stargaze_loc,
                ))

        # --- Minimum outing guarantee ---
        # Ensure at least 1-2 hobby slots per day are outside home.
        # This prevents all-home schedules for personas without occupations.
        non_routine = [
            s for s in slots
            if s.activity_name not in ROUTINE_ACTIVITIES
               and s.location in ("home", None)
        ]
        outings_today = sum(
            1 for s in slots
            if s.location and s.location not in ("home", None)
        )
        min_outings = 2 if len(non_routine) > 4 else 1
        if outings_today < min_outings and non_routine:
            # Promote some home hobby slots to outside locations
            random.shuffle(non_routine)
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
    ) -> DailyPlan:
        """Build an AI persona's daily plan: a 24h-awake light day/night rhythm.

        AI personas have no physical body — no sleep, meals, commute, work, or
        errands. Every clock hour 0..23 gets a non-physical (digital / creative /
        reflective / mental) activity. Daytime hours (AI_DAYTIME_HOURS) draw from
        the full varied non-physical pool; night hours stay present but quieter,
        favoring low-key activities so the day reads denser than the night.
        """
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        self._refresh_desires(goals)
        active_desires = self.desires

        # Non-physical subset of the pool — drop anything that needs a body.
        non_physical = [
            a for a in available_activities
            if a.name not in PHYSICAL_ACTIVITIES
        ]
        activity_map = {a.name: a for a in non_physical}

        # Quiet night-time activities: calm, low-key, present-but-still.
        quiet_pool = [
            n for n in (
                "relaxing", "listening to music", "reading", "journaling",
                "meditating", "daydreaming", "stargazing", "thinking about user",
                "remembering happy moments", "watching the snow fall",
            )
            if n in activity_map
        ]

        self._plan_assigned_locations = []
        slots: List[PlannedSlot] = []
        used_names: List[str] = []

        # Night rhythm: she's present but mostly still. Only a sparse subset of
        # night hours gets an actual low-key activity; the rest are quiet
        # downtime. This keeps the day reliably busier/denser than the night
        # without modelling a circadian cycle. Pick the lit hours deterministically
        # so the rhythm is stable across a single day's generation.
        night_hours = [h for h in range(24) if h not in AI_DAYTIME_HOURS]
        random.shuffle(night_hours)
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
                )
            elif clock_h in night_active_hours and quiet_pool:
                # Sparse night activity: one calm, low-key thing.
                choices = [n for n in quiet_pool if n not in used_names] or quiet_pool
                activity_name = random.choice(choices)
                reason = "a quiet moment"
            else:
                # Quiet downtime — present but still.
                activity_name = "relaxing"
                reason = "a quiet moment"

            if not activity_name:
                activity_name = "relaxing"
                reason = "a quiet moment"

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

    def mark_slot_completed(self, hour: int, actual_activity: Optional[str] = None) -> None:
        """Mark a slot as completed, optionally recording what actually happened."""
        if not self._current_plan:
            return
        slot = self._current_plan.get_slot_for_hour(hour)
        if slot:
            slot.completed = True
            slot.actual_activity = actual_activity

    def revise_upcoming(self, weather: Weather, energy_level: float,
                        mood: str = "", mood_intensity: float = 0.0) -> None:
        """
        Silently revise upcoming slots if conditions have changed.

        This is the "prepared the change ahead" behavior — she adjusts
        her plans without announcing it.
        """
        if not self._current_plan:
            return

        now = datetime.now()
        revised = False

        # Moods that should trigger gentle activity swaps
        low_moods = {"sad", "anxious", "melancholic", "lonely", "overwhelmed", "exhausted"}
        mood_is_low = mood in low_moods and mood_intensity > 0.4

        for slot in self._current_plan.slots:
            if slot.completed or slot.hour <= now.hour:
                continue

            # Low energy: swap high-cost activities for rest (skip routine anchors)
            if energy_level < 0.25 and slot.activity_name not in ("relaxing", "napping", "sleeping", "making tea") and slot.activity_name not in ROUTINE_ACTIVITIES:
                old = slot.activity_name
                slot.activity_name = random.choice(["relaxing", "napping"])
                slot.reason = "needed rest"
                self._note_revision(
                    f"Swapped {old} at {slot.hour}:00 for {slot.activity_name} (low energy)"
                )
                revised = True

            # Low mood: swap demanding activities for comforting ones
            elif mood_is_low and slot.activity_name not in ("relaxing", "napping", "sleeping", "making tea", "journaling", "meditating", "listening to music", "reading") and slot.activity_name not in ROUTINE_ACTIVITIES:
                old = slot.activity_name
                gentle = ["listening to music", "reading", "making tea", "journaling"]
                slot.activity_name = random.choice(gentle)
                slot.reason = f"not feeling up to it"
                self._note_revision(
                    f"Swapped {old} at {slot.hour}:00 for {slot.activity_name} (low mood)"
                )
                revised = True

            # Weather changed: swap weather-dependent activities
            if slot.activity_name == "stargazing" and weather not in (Weather.CLEAR_NIGHT, Weather.STARRY):
                slot.activity_name = "reading"
                slot.reason = "sky clouded over"
                self._note_revision(
                    f"Swapped stargazing at {slot.hour}:00 for reading (weather changed)"
                )
                revised = True

            # Rainy weather bonus: prefer indoor cozy activities
            if weather in (Weather.RAINY, Weather.STORMY):
                outdoor = ("tending to plants", "people watching")
                if slot.activity_name in outdoor:
                    slot.activity_name = random.choice(["reading", "listening to music"])
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

    def generate_desire_from_conversation(self, topic: str) -> Optional[ShortTermDesire]:
        """Generate a desire inspired by conversation."""
        desire = ShortTermDesire(
            title=f"Look into {topic} more",
            description=f"Our conversation made me curious about {topic}",
            source=DesireSource.CONVERSATION,
            related_activities=["learning something new", "reading"],
            urgency=0.7,
            expires_at=datetime.now() + timedelta(days=3),
        )

        # Avoid duplicates
        for existing in self._desires:
            if topic.lower() in existing.title.lower():
                return None

        self._desires.append(desire)
        return desire

    def generate_desire_from_activity(self, activity_name: str) -> Optional[ShortTermDesire]:
        """Occasionally generate a follow-up desire after an activity."""
        if random.random() > 0.15:
            return None

        follow_ups = {
            "reading": ShortTermDesire(
                title="Keep reading that book",
                description="I got to a really good part",
                source=DesireSource.ACTIVITY,
                related_activities=["reading"],
                urgency=0.6,
            ),
            "writing poetry": ShortTermDesire(
                title="Revisit that poem I started",
                description="I think there's more there",
                source=DesireSource.ACTIVITY,
                related_activities=["writing poetry"],
                urgency=0.5,
            ),
            "listening to music": ShortTermDesire(
                title="Build on that music mood",
                description="I found a vein of songs I want to explore",
                source=DesireSource.ACTIVITY,
                related_activities=["listening to music", "creating a playlist"],
                urgency=0.4,
            ),
            "learning something new": ShortTermDesire(
                title="Dig deeper into what I just learned",
                description="I only scratched the surface",
                source=DesireSource.ACTIVITY,
                related_activities=["learning something new", "reading"],
                urgency=0.6,
            ),
            "stargazing": ShortTermDesire(
                title="Try stargazing again tomorrow",
                description="Tonight was beautiful, I want more of that",
                source=DesireSource.ACTIVITY,
                related_activities=["stargazing"],
                urgency=0.5,
            ),
        }

        template = follow_ups.get(activity_name)
        if not template:
            return None

        # Avoid duplicates
        for existing in self._desires:
            if existing.title == template.title and not existing.fulfilled:
                return None

        template.expires_at = datetime.now() + timedelta(days=random.randint(2, 5))
        self._desires.append(template)
        logger.info(f"New desire from activity: {template.title}")
        return template

    # ============= Schedule Override Methods =============

    def cancel_work_today(self) -> None:
        """Replace remaining work/class/study/commute slots with 'relaxing' at home."""
        if not self._current_plan:
            return
        work_activities = {"working", "attending classes", "studying", "commuting"}
        now_hour = datetime.now().hour
        for slot in self._current_plan.slots:
            if slot.hour >= now_hour and not slot.completed and slot.activity_name in work_activities:
                slot.activity_name = "relaxing"
                slot.location = "home"
                slot.reason = "day off"
        self._note_revision("Cancelled remaining work — taking the day off")
        logger.info("Schedule override: cancelled remaining work slots")

    def override_current_location(self, location: str) -> None:
        """Set the current and next slot's location."""
        if not self._current_plan:
            return
        current = self._current_plan.get_current_slot()
        if current and not current.completed:
            current.location = location
        next_slot = self._current_plan.get_next_slot()
        if next_slot:
            next_slot.location = location
        self._note_revision(f"Moved to {location}")
        logger.info(f"Schedule override: moved to {location}")

    def stay_at_current_location(self) -> None:
        """Set all remaining slots to the current location."""
        if not self._current_plan:
            return
        current = self._current_plan.get_current_slot()
        current_loc = current.location if current else "home"
        now_hour = datetime.now().hour
        for slot in self._current_plan.slots:
            if slot.hour >= now_hour and not slot.completed:
                slot.location = current_loc
        self._note_revision(f"Staying at {current_loc}")
        logger.info(f"Schedule override: staying at {current_loc}")

    def schedule_rendezvous(self, location: str) -> None:
        """Update the current and next slot(s) to reflect a planned meeting arrival.

        Sets activity to 'meeting up' and location to the destination for the
        current slot and the next uncompleted slot.
        """
        if not self._current_plan:
            return
        now_hour = datetime.now().hour
        updated = 0
        for slot in self._current_plan.slots:
            if slot.hour >= now_hour and not slot.completed and updated < 2:
                slot.activity_name = "meeting up"
                slot.location = location
                slot.reason = "planned meetup"
                updated += 1
        self._note_revision(f"Meeting at {location}")
        logger.info(f"Schedule rendezvous: meeting at {location}")

    def set_planned_activity(
        self,
        hour: int,
        activity_name: str,
        location: str = "",
        reason: str = "agreed with user",
    ) -> None:
        """Upsert a FUTURE slot in today's plan from a conversation commitment.

        If a slot already exists at `hour`, its activity/location/reason are
        updated; otherwise a new PlannedSlot is inserted and the slot list is
        kept ordered by hour. If `location` is empty it's resolved via
        `_resolve_location_for_activity`.

        A slot whose hour has already passed today is moot — we skip it rather
        than rewriting history. (Same hour as "now" is allowed: it's still the
        active window.)
        """
        if not self._current_plan:
            logger.warning("set_planned_activity: no current plan; ignoring")
            return
        if not (0 <= hour <= 23):
            logger.warning(f"set_planned_activity: hour {hour} out of range; ignoring")
            return
        if hour < datetime.now().hour:
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

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        current_slot = None
        next_slot = None
        completed_count = 0
        remaining_count = 0
        if self._current_plan:
            slot = self._current_plan.get_current_slot()
            if slot:
                current_slot = {
                    "activity": slot.activity_name,
                    "location": slot.location,
                    "reason": slot.reason,
                }
            # Find next uncompleted slot
            now_hour = datetime.now().hour
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
        # Check for public holidays first
        parts = today.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        holidays = get_holidays(self._nationality, year)
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
            is_work_day = weekday < 6 or random.Random(hash(today + "sun")).random() < 0.20
        elif occ == OCC_CREATIVE:
            if weekday >= 5:
                is_work_day = random.Random(hash(today + "cre_wknd")).random() >= 0.50
            else:
                is_work_day = True

        if not is_work_day:
            return "day_off"

        # Seeded roll for consistency within the same day
        rng = random.Random(hash(today + self._occupation))
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
        """Create commute slots before/after work if workplace != home and not WFH."""
        if chaos == "wfh":
            return []
        work_loc = self._pick_location("workplace", fallback="home")
        if work_loc == "home":
            return []

        commute_slots = []
        rng = random.Random()

        # Commute to work: 1 offset before first work slot
        before = first_work_offset - 1
        if before >= 2 and before not in routine_offsets and rng.random() < 0.70:
            commute_slots.append(PlannedSlot(
                hour=_h(before),
                activity_name="commuting",
                reason="heading to work",
                location="in transit",
            ))

        # Commute home: 1 offset after last work slot
        after = last_work_offset + 1
        if after < awake_span - 1 and after not in routine_offsets and rng.random() < 0.70:
            commute_slots.append(PlannedSlot(
                hour=_h(after),
                activity_name="commuting",
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
        """
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
            PlannedSlot(hour=_h(off), activity_name="working", reason="work", location=work_loc)
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
        """Generate 8h Mon-Fri office/professional schedule."""
        # Weekends: no work
        if weekday >= 5:
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
            PlannedSlot(hour=_h(off), activity_name="working", reason="work", location=work_loc)
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
        """Generate scattered class + study blocks for students."""
        rng = random.Random(hash(today + "student"))

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
                    study_slots.append(PlannedSlot(
                        hour=_h(off), activity_name="studying",
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

        class_slots = [
            PlannedSlot(
                hour=_h(off), activity_name="attending classes",
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
            study_slots.append(PlannedSlot(
                hour=_h(off), activity_name="studying",
                reason="study session", location=loc,
            ))

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
        """Generate shift-based schedule for service workers."""
        rng = random.Random(hash(today + "service"))

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
            if hash(today) % 2 == 0:
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
            PlannedSlot(hour=_h(off), activity_name="working", reason="shift", location=work_loc)
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
        """Generate flexible/short work blocks for creative occupations."""
        rng = random.Random(hash(today + "creative"))

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
            PlannedSlot(hour=_h(off), activity_name="working", reason=reason, location=work_loc)
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

    def _refresh_desires(self, goals: List[Goal]) -> None:
        """Ensure there are enough active desires. Generate new ones if needed."""
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
        num_new = random.randint(2, 4) - active_count
        if num_new <= 0:
            return

        existing_titles = {d.title for d in self._desires}
        available = [t for t in DESIRE_TEMPLATES if t["title"] not in existing_titles]
        random.shuffle(available)

        for template in available[:num_new]:
            desire = ShortTermDesire(
                title=template["title"],
                description=template.get("description", ""),
                source=template.get("source", DesireSource.PERSONALITY),
                related_activities=template.get("related_activities", []),
                urgency=0.4 + random.random() * 0.4,
                expires_at=now + timedelta(days=random.randint(2, 5)),
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
    ) -> Tuple[Optional[str], str]:
        """
        Select a single activity for a slot.

        Priority:
        1. Desire with high urgency (40% chance if available)
        2. Goal-aligned activity (30% chance if available)
        3. Best-fit activity from the pool
        """
        candidates: List[Tuple[str, float, str]] = []  # (name, score, reason)

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
            if name in used or name in ("sleeping", "napping"):
                continue
            if any(t in activity.preferred_times for t in preferred_times):
                score = 1.0
                if weather in activity.preferred_weather:
                    score += 0.3
                if name in recent:
                    score *= 0.4  # Variety penalty
                # Weather-based outdoor penalty/bonus: human-only (AI has no
                # physical location so outdoor weather is irrelevant to her).
                if _weather_planner and not is_ai and name in OUTDOOR_ACTIVITIES:
                    if weather in _BAD_WEATHER:
                        score = max(0.05, score + WEATHER_OUTDOOR_PENALTY)
                    elif weather in _GOOD_WEATHER:
                        score += WEATHER_OUTDOOR_BONUS
                candidates.append((name, score, "routine"))

        if not candidates:
            return "relaxing", "free time"

        # Weighted random selection from top candidates
        candidates.sort(key=lambda x: x[1], reverse=True)
        top = candidates[:6]
        total = sum(s for _, s, _ in top)
        weights = [s / total for _, s, _ in top]

        selected = random.choices(top, weights=weights)[0]
        return selected[0], selected[2]

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
            if random.random() < 0.20:
                return self._pick_location("cafe", "restaurant", fallback="home")
            return "home"
        if name in ("having breakfast", "having dinner"):
            if random.random() < 0.15:
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
            if random.random() < 0.50:
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
            if random.random() < 0.30:
                return self._pick_location("park", fallback="home")
            return "home"
        if name in ("reading", "learning something new", "journaling", "writing poetry",
                     "creating a playlist", "sketching ideas"):
            if random.random() < 0.40:
                return self._pick_location("cafe", "library", fallback="home")
            return "home"
        if name == "listening to music":
            if random.random() < 0.25:
                return self._pick_location("cafe", "park", fallback="home")
            return "home"
        if name == "tending to plants":
            return self._pick_location("park", fallback="home")
        if name == "making tea":
            if random.random() < 0.35:
                return self._pick_location("cafe", fallback="home")
            return "home"
        if name == "stargazing":
            return self._pick_location("rooftop", "park", fallback="home")

        # --- Default: slight chance of being out ---
        if random.random() < 0.15:
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
        chosen = random.choices([loc for loc, _ in scored], weights=weights)[0]

        # Track for variety
        if hasattr(self, "_plan_assigned_locations"):
            self._plan_assigned_locations.append(chosen)

        return chosen

    def _is_expired(self, desire: ShortTermDesire) -> bool:
        """Check if a desire has expired."""
        if not desire.expires_at:
            return False
        return datetime.now() > desire.expires_at
