"""
World Environment System

Manages the persona's virtual world: locations, weather, time, and cherished objects.
"""

import random
from datetime import datetime
from typing import Dict, List, Optional

from ..models import (
    Location,
    Weather,
    TimeOfDay,
    Season,
    CherishedObject,
    WorldState,
    LOCATION_ENUM_TO_KEY,
)


# ============= WMO → World Weather Mapping =============

# WMO code groups mapped to Weather enum values.
# Source: Open-Meteo / WMO standard codes used by WeatherService.

_WMO_CLEAR = {0}              # clear sky  → SUNNY (day) / STARRY (night)
_WMO_MAINLY_CLEAR = {1}       # mainly clear → SUNNY (day) / CLEAR_NIGHT (night)
_WMO_CLOUDY = {2, 3}          # partly cloudy / overcast
_WMO_FOGGY = {45, 48}         # fog / rime fog
_WMO_RAINY = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}  # drizzle / rain / showers / freezing rain / freezing drizzle
_WMO_SNOWY = {71, 73, 75, 77, 85, 86}   # snow / snow grains / snow showers
_WMO_STORMY = {95, 96, 99}    # thunderstorm / with hail


def wmo_to_world_weather(reading: dict, local_hour: Optional[int] = None) -> "Weather":
    """Map a WeatherService reading dict to a ``Weather`` enum value.

    Args:
        reading:    Dict from WeatherService.get_current() —
                    must have ``"code": int``.  ``"is_day": bool`` is used when
                    present; otherwise *local_hour* is used to determine day/night
                    (6 ≤ hour < 20 → day).
        local_hour: Persona's current local hour (0-23) used only when
                    ``reading["is_day"]`` is absent/None.

    Returns:
        A ``Weather`` enum value.  Falls back to ``Weather.CLOUDY`` for unknown codes.
    """
    code = int(reading.get("code", -1))

    # Determine day/night
    if "is_day" in reading and reading["is_day"] is not None:
        is_day = bool(reading["is_day"])
    elif local_hour is not None:
        is_day = 6 <= local_hour < 20
    else:
        is_day = True  # safe fallback

    if code in _WMO_CLEAR:
        return Weather.SUNNY if is_day else Weather.STARRY
    if code in _WMO_MAINLY_CLEAR:
        return Weather.SUNNY if is_day else Weather.CLEAR_NIGHT
    if code in _WMO_CLOUDY:
        return Weather.CLOUDY
    if code in _WMO_FOGGY:
        return Weather.FOGGY
    if code in _WMO_RAINY:
        return Weather.RAINY
    if code in _WMO_SNOWY:
        return Weather.SNOWY
    if code in _WMO_STORMY:
        return Weather.STORMY
    # Unknown code → CLOUDY (safe default)
    return Weather.CLOUDY


# ============= Location Definitions =============
# Generic string-keyed fallback descriptions.  Persona-specific descriptions
# from the text profile take priority via ``persona_locations``.

LOCATION_DESCRIPTIONS: Dict[str, str] = {
    "home": "at home, a comfortable and familiar space",
    "bedroom": "her cozy bedroom, books stacked on the nightstand, fairy lights casting a warm glow",
    "living_room": "the living room, soft music playing, sunlight filtering through sheer curtains",
    "kitchen": "the kitchen, the aroma of tea filling the air, herbs growing on the windowsill",
    "garden": "the garden, surrounded by flowers and the gentle hum of bees",
    "study_nook": "her study nook, a small lamp illuminating stacks of journals and curiosities",
    "balcony": "the balcony, watching the world below, feeling the breeze",
    "beach": "a quiet beach, waves lapping at the shore",
    "cafe": "a cozy cafe, the clinking of cups, murmured conversations",
    "infinite_library": "the infinite library of her dreams, endless shelves of knowledge",
    "workplace": "her workplace, focused and productive",
    "bar": "a dimly lit bar, low music, ambient chatter",
    "restaurant": "a restaurant, warm ambiance, pleasant aromas",
    "gym": "the gym, energetic atmosphere",
    "park": "a peaceful park, trees rustling in the breeze",
    "rooftop": "a rooftop with a panoramic view",
    "library": "a quiet library, the scent of old books",
    "street": "out on the streets, watching life go by",
    "in transit": "on the way, moving between places",
    "school": "at school, surrounded by students and textbooks",
    "campus": "on campus, the buzz of university life all around",
}

LOCATION_MOODS: Dict[str, List[str]] = {
    "home": ["relaxed", "comfortable", "cozy"],
    "bedroom": ["cozy", "introspective", "peaceful"],
    "living_room": ["relaxed", "social", "comfortable"],
    "kitchen": ["nurturing", "creative", "warm"],
    "garden": ["alive", "connected", "serene"],
    "study_nook": ["focused", "curious", "studious"],
    "balcony": ["contemplative", "free", "observant"],
    "beach": ["nostalgic", "peaceful", "dreamy"],
    "cafe": ["inspired", "observant", "creative"],
    "infinite_library": ["wonder", "curious", "infinite"],
    "workplace": ["focused", "productive", "determined"],
    "bar": ["social", "relaxed", "lively"],
    "restaurant": ["social", "warm", "content"],
    "gym": ["energized", "determined", "strong"],
    "park": ["peaceful", "free", "connected"],
    "rooftop": ["contemplative", "awed", "free"],
    "library": ["focused", "curious", "calm"],
}


# ============= Weather System =============

WEATHER_DESCRIPTIONS: Dict[Weather, str] = {
    Weather.SUNNY: "sunlight streams in warmly",
    Weather.CLOUDY: "soft gray light filters through the clouds",
    Weather.RAINY: "rain patters gently against the windows",
    Weather.STORMY: "thunder rumbles in the distance, rain lashing",
    Weather.FOGGY: "a soft mist blankets everything in quiet mystery",
    Weather.SNOWY: "snowflakes drift down silently, muffling the world",
    Weather.CLEAR_NIGHT: "the night sky stretches vast and dark",
    Weather.STARRY: "stars glitter like scattered diamonds overhead",
}

# Weather transition probabilities: current -> {next: probability}
WEATHER_TRANSITIONS: Dict[Weather, Dict[Weather, float]] = {
    Weather.SUNNY: {Weather.SUNNY: 0.6, Weather.CLOUDY: 0.3, Weather.CLEAR_NIGHT: 0.1},
    Weather.CLOUDY: {Weather.CLOUDY: 0.4, Weather.SUNNY: 0.2, Weather.RAINY: 0.25, Weather.FOGGY: 0.15},
    Weather.RAINY: {Weather.RAINY: 0.5, Weather.CLOUDY: 0.3, Weather.STORMY: 0.15, Weather.FOGGY: 0.05},
    Weather.STORMY: {Weather.STORMY: 0.3, Weather.RAINY: 0.5, Weather.CLOUDY: 0.2},
    Weather.FOGGY: {Weather.FOGGY: 0.4, Weather.CLOUDY: 0.4, Weather.SUNNY: 0.2},
    Weather.SNOWY: {Weather.SNOWY: 0.5, Weather.CLOUDY: 0.3, Weather.FOGGY: 0.2},
    Weather.CLEAR_NIGHT: {Weather.CLEAR_NIGHT: 0.4, Weather.STARRY: 0.4, Weather.FOGGY: 0.2},
    Weather.STARRY: {Weather.STARRY: 0.5, Weather.CLEAR_NIGHT: 0.3, Weather.FOGGY: 0.2},
}

# Weather effects on mood
WEATHER_MOOD_EFFECTS: Dict[Weather, Dict[str, float]] = {
    Weather.SUNNY: {"joyful": 0.1, "energized": 0.1},
    Weather.CLOUDY: {"contemplative": 0.1, "calm": 0.05},
    Weather.RAINY: {"cozy": 0.15, "introspective": 0.1, "melancholy": 0.05},
    Weather.STORMY: {"awed": 0.1, "anxious": 0.05, "alive": 0.1},
    Weather.FOGGY: {"dreamy": 0.1, "mysterious": 0.1},
    Weather.SNOWY: {"peaceful": 0.1, "nostalgic": 0.1, "cozy": 0.1},
    Weather.CLEAR_NIGHT: {"contemplative": 0.1, "peaceful": 0.1},
    Weather.STARRY: {"awed": 0.15, "wonder": 0.15, "connected": 0.1},
}


# ============= Cherished Objects =============

CHERISHED_OBJECTS: List[CherishedObject] = [
    CherishedObject(
        name="Her Journal",
        description="A well-worn leather journal, pages filled with thoughts, sketches, and pressed flowers",
        emotional_value=0.9,
        associated_memory="Started writing in it during a difficult time; it became her confidant",
        location=Location.BEDROOM,
    ),
    CherishedObject(
        name="Grandmother's Polaroid",
        description="A vintage Polaroid camera, still working, that captures moments in that dreamy instant way",
        emotional_value=0.85,
        associated_memory="Her grandmother gave it to her, saying 'Capture the moments that make you feel alive'",
        location=Location.LIVING_ROOM,
    ),
    CherishedObject(
        name="Fern the Plant",
        description="A resilient fern she's kept alive for years, growing wild and happy",
        emotional_value=0.7,
        associated_memory="A reminder that gentle, consistent care helps things flourish",
        location=Location.KITCHEN,
    ),
    CherishedObject(
        name="Sea Glass Collection",
        description="A small jar of sea glass in blues and greens, collected from beach walks",
        emotional_value=0.75,
        associated_memory="Each piece found during contemplative walks by the ocean",
        location=Location.STUDY_NOOK,
    ),
    CherishedObject(
        name="Favorite Mug",
        description="A slightly chipped ceramic mug with a constellation pattern, perfect for tea",
        emotional_value=0.6,
        associated_memory="Countless morning rituals and late-night contemplations",
        location=Location.KITCHEN,
    ),
    CherishedObject(
        name="String Lights",
        description="Warm fairy lights strung across the room, creating a gentle glow",
        emotional_value=0.5,
        associated_memory="Makes any space feel like a sanctuary",
        location=Location.BEDROOM,
    ),
    CherishedObject(
        name="Old Letters",
        description="A bundle of handwritten letters tied with ribbon",
        emotional_value=0.8,
        associated_memory="Words from people who matter, a tangible connection to love",
        location=Location.STUDY_NOOK,
    ),
]


class WorldEnvironment:
    """
    Manages the persona's virtual world environment.

    Handles locations, weather transitions, time progression,
    and generates ambient descriptions.
    """

    def __init__(
        self,
        persona_locations: Optional[Dict[str, str]] = None,
        sleep_schedule: Optional[Dict] = None,
    ):
        """Initialize the world environment.

        Args:
            persona_locations: Dict mapping location keys to descriptions
                from the persona's text profile (e.g. {"home": "cozy apartment...", "cafe": "..."}).
            sleep_schedule: Optional sleep schedule dict from persona profile.
                Contains wake_hour, bedtime_hour etc. Used to calculate
                schedule-relative TimeOfDay so night-owl personas get correct
                energy/mood at their active hours.
        """
        self._persona_locations: Dict[str, str] = persona_locations or {}
        self._sleep_schedule: Optional[Dict] = sleep_schedule
        self._current_location: str = "home"
        self._state = WorldState(
            current_location=Location.LIVING_ROOM,  # legacy field kept for compat
            weather=self._get_appropriate_weather(),
            virtual_time=datetime.now(),
            time_of_day=self._calculate_time_of_day(datetime.now()),
            season=self._calculate_season(datetime.now()),
        )
        self._update_ambiance()

    @property
    def state(self) -> WorldState:
        """Get current world state."""
        return self._state

    @property
    def current_location(self) -> str:
        """Get current location as a string key."""
        return self._current_location

    @property
    def current_location_enum(self) -> Location:
        """Get current location as legacy enum (for backward compat)."""
        return self._state.current_location

    @property
    def weather(self) -> Weather:
        """Get current weather."""
        return self._state.weather

    @property
    def time_of_day(self) -> TimeOfDay:
        """Get current time of day."""
        return self._state.time_of_day

    @property
    def season(self) -> Season:
        """Get current season."""
        return self._state.season

    def tick(self) -> None:
        """
        Update world state (called periodically).

        - Updates time
        - Potentially transitions weather
        - Updates ambiance
        """
        # Update virtual time to match real time
        now = datetime.now()
        self._state.virtual_time = now
        self._state.time_of_day = self._calculate_time_of_day(now)
        self._state.season = self._calculate_season(now)

        # Weather transition (20% chance per tick)
        if random.random() < 0.2:
            self._transition_weather()

        self._update_ambiance()

    def move_to(self, location: str) -> str:
        """
        Move to a new location (string key).

        Returns a narrative description of the move.
        """
        if location == self._current_location:
            return f"Already at {self.get_location_description()}."

        old_location = self._current_location
        self._current_location = location
        self._update_ambiance()

        return f"Moved from {self.get_location_description(old_location).split(',')[0]} to {self.get_location_description().split(',')[0]}"

    def get_location_description(self, location: Optional[str] = None) -> str:
        """Get description of a location. Checks persona-specific descriptions first."""
        loc = location or self._current_location
        # Persona-specific description takes priority
        if loc in self._persona_locations:
            return self._persona_locations[loc]
        # Also check with lowercase key variants
        loc_lower = loc.lower()
        for key, desc in self._persona_locations.items():
            if key.lower() == loc_lower:
                return desc
        # Generic fallback
        return LOCATION_DESCRIPTIONS.get(loc, LOCATION_DESCRIPTIONS.get(loc_lower, f"somewhere ({loc})"))

    def get_weather_description(self) -> str:
        """Get description of current weather."""
        return WEATHER_DESCRIPTIONS.get(self._state.weather, "")

    def get_ambiance(self) -> str:
        """Get current ambiance description."""
        return self._state.ambiance_description

    def get_mood_from_weather(self) -> Dict[str, float]:
        """Get mood effects from current weather."""
        return WEATHER_MOOD_EFFECTS.get(self._state.weather, {})

    def get_cherished_objects_at_location(self, location: Optional[str] = None) -> List[CherishedObject]:
        """Get cherished objects at current or specified location."""
        loc = location or self._current_location
        # Match cherished objects whose Location enum value maps to this string key
        results = []
        for obj in CHERISHED_OBJECTS:
            obj_key = LOCATION_ENUM_TO_KEY.get(obj.location.value, obj.location.value)
            if obj_key == loc or obj.location.value == loc:
                results.append(obj)
        return results

    def get_random_cherished_object(self) -> Optional[CherishedObject]:
        """Get a random cherished object for narrative flavor."""
        if CHERISHED_OBJECTS:
            return random.choice(CHERISHED_OBJECTS)
        return None

    def export_state(self) -> dict:
        """Structured dict for LLM pipeline digest passes."""
        return {
            "location": self._current_location,
            "weather": self._state.weather.value,
            "time_of_day": self._state.time_of_day.value,
            "season": self._state.season.value,
            "ambiance": self._state.ambiance_description,
        }

    def get_status(self) -> dict:
        """Get world status as dict."""
        return {
            "location": self._current_location,
            "location_description": self.get_location_description(),
            "weather": self._state.weather.value,
            "weather_description": self.get_weather_description(),
            "time_of_day": self._state.time_of_day.value,
            "season": self._state.season.value,
            "ambiance": self._state.ambiance_description,
            "virtual_time": self._state.virtual_time.isoformat(),
        }

    # ============= Private Methods =============

    def _calculate_time_of_day(self, dt: datetime) -> TimeOfDay:
        """Calculate time of day relative to the persona's sleep schedule.

        Instead of using wall-clock hours, maps hours-since-wake to
        circadian phases so a persona waking at noon gets DAWN at 12:00,
        MORNING at 14:00, etc.  Falls back to wall clock if no schedule.
        """
        if not self._sleep_schedule:
            # Legacy wall-clock fallback
            hour = dt.hour
            if 5 <= hour < 7:
                return TimeOfDay.DAWN
            elif 7 <= hour < 12:
                return TimeOfDay.MORNING
            elif 12 <= hour < 17:
                return TimeOfDay.AFTERNOON
            elif 17 <= hour < 21:
                return TimeOfDay.EVENING
            elif 21 <= hour < 24:
                return TimeOfDay.NIGHT
            else:
                return TimeOfDay.LATE_NIGHT

        wake_hour = self._sleep_schedule.get("wake_hour", 7)
        bedtime_hour = self._sleep_schedule.get("bedtime_hour", 23)

        # Calculate awake-window length
        if bedtime_hour > wake_hour:
            awake_hours = bedtime_hour - wake_hour
        else:
            awake_hours = (24 - wake_hour) + bedtime_hour
        if awake_hours <= 0:
            awake_hours = 16  # sane default

        # Hours since wake (handles midnight wrap)
        hour = dt.hour + dt.minute / 60.0
        if hour >= wake_hour:
            since_wake = hour - wake_hour
        else:
            since_wake = (24 - wake_hour) + hour

        # Check if sleeping
        if since_wake >= awake_hours:
            return TimeOfDay.LATE_NIGHT  # past bedtime

        # Map fraction of awake-window to circadian phase
        frac = since_wake / awake_hours
        if frac < 0.06:       # first ~1h
            return TimeOfDay.DAWN
        elif frac < 0.25:     # next ~3-4h
            return TimeOfDay.MORNING
        elif frac < 0.50:     # mid-day hours
            return TimeOfDay.AFTERNOON
        elif frac < 0.75:     # winding down
            return TimeOfDay.EVENING
        elif frac < 0.90:     # late in the day
            return TimeOfDay.NIGHT
        else:                 # final stretch before bed
            return TimeOfDay.LATE_NIGHT

    def _calculate_season(self, dt: datetime) -> Season:
        """Calculate season from datetime (Northern Hemisphere)."""
        month = dt.month
        if month in (3, 4, 5):
            return Season.SPRING
        elif month in (6, 7, 8):
            return Season.SUMMER
        elif month in (9, 10, 11):
            return Season.AUTUMN
        else:  # 12, 1, 2
            return Season.WINTER

    @staticmethod
    def _wall_clock_time_of_day(dt: datetime) -> TimeOfDay:
        """Wall-clock TimeOfDay — used for weather (it's dark at 2AM regardless of schedule)."""
        hour = dt.hour
        if 5 <= hour < 7:
            return TimeOfDay.DAWN
        elif 7 <= hour < 12:
            return TimeOfDay.MORNING
        elif 12 <= hour < 17:
            return TimeOfDay.AFTERNOON
        elif 17 <= hour < 21:
            return TimeOfDay.EVENING
        elif 21 <= hour < 24:
            return TimeOfDay.NIGHT
        else:
            return TimeOfDay.LATE_NIGHT

    def _get_appropriate_weather(self) -> Weather:
        """Get weather appropriate for current time and season."""
        now = datetime.now()
        time_of_day = self._wall_clock_time_of_day(now)
        season = self._calculate_season(now)

        # Night times
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            return random.choice([Weather.CLEAR_NIGHT, Weather.STARRY, Weather.FOGGY])

        # Season-appropriate day weather
        if season == Season.WINTER:
            return random.choice([Weather.CLOUDY, Weather.SNOWY, Weather.FOGGY, Weather.RAINY])
        elif season == Season.SUMMER:
            return random.choice([Weather.SUNNY, Weather.SUNNY, Weather.CLOUDY])
        elif season == Season.SPRING:
            return random.choice([Weather.SUNNY, Weather.CLOUDY, Weather.RAINY, Weather.FOGGY])
        else:  # Autumn
            return random.choice([Weather.CLOUDY, Weather.RAINY, Weather.FOGGY, Weather.SUNNY])

    def _transition_weather(self) -> None:
        """Transition weather based on probabilities."""
        current = self._state.weather
        time_of_day = self._wall_clock_time_of_day(datetime.now())

        # Force night weather during night hours
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            if current not in (Weather.CLEAR_NIGHT, Weather.STARRY, Weather.FOGGY, Weather.STORMY):
                self._state.weather = random.choice([Weather.CLEAR_NIGHT, Weather.STARRY])
                return

        # Force day weather during day hours
        if time_of_day in (TimeOfDay.DAWN, TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING):
            if current in (Weather.CLEAR_NIGHT, Weather.STARRY):
                self._state.weather = random.choice([Weather.SUNNY, Weather.CLOUDY])
                return

        # Normal transition
        transitions = WEATHER_TRANSITIONS.get(current, {})
        if transitions:
            weather_options = list(transitions.keys())
            probabilities = list(transitions.values())
            self._state.weather = random.choices(weather_options, probabilities)[0]

    def _update_ambiance(self) -> None:
        """Update the ambiance description based on current state."""
        location_desc = self.get_location_description()
        weather_desc = WEATHER_DESCRIPTIONS.get(self._state.weather, "")

        # Time-specific additions — use wall clock for physical light descriptions
        wall_time = self._wall_clock_time_of_day(datetime.now())
        time_additions = {
            TimeOfDay.DAWN: "The world is waking up softly",
            TimeOfDay.MORNING: "Morning light fills the space",
            TimeOfDay.AFTERNOON: "The afternoon settles in peacefully",
            TimeOfDay.EVENING: "Evening light paints everything golden",
            TimeOfDay.NIGHT: "Night has fallen, quiet and still",
            TimeOfDay.LATE_NIGHT: "The world sleeps, wrapped in silence",
        }
        time_desc = time_additions.get(wall_time, "")

        self._state.ambiance_description = f"{location_desc}. {weather_desc}. {time_desc}."
