"""
World Environment System

Manages the persona's virtual world: locations, weather, time, and cherished objects.
"""

import random
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ..models import (
    Location,
    Weather,
    TimeOfDay,
    Season,
    CherishedObject,
    WorldState,
    LOCATION_ENUM_TO_KEY,
)
from ..settings import DEFAULT_SETTING, SettingSpec, get_setting
# Legacy names: the generic place descriptions (Task 9), the weather
# descriptions and the cherished objects (its fix round, ruling T9-R5) moved,
# unchanged, into the contemporary setting pack
# (aura_life.settings.contemporary) -- a world reads them from the setting it
# is given; re-exported so an import from here keeps working.
from ..settings.contemporary import (  # noqa: F401
    CHERISHED_OBJECTS,
    LOCATION_DESCRIPTIONS,
    WEATHER_DESCRIPTIONS,
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
        now: Optional[Callable[[], datetime]] = None,
        rng=None,
        seed=None,
        setting: Optional[SettingSpec] = None,
    ):
        """Initialize the world environment.

        Args:
            persona_locations: Dict mapping location keys to descriptions
                from the persona's text profile (e.g. {"home": "cozy apartment...", "cafe": "..."}).
            sleep_schedule: Optional sleep schedule dict from persona profile.
                Contains wake_hour, bedtime_hour etc. Used to calculate
                schedule-relative TimeOfDay so night-owl personas get correct
                energy/mood at their active hours.
            now: The clock this world runs on -- a zero-argument callable
                returning a naive :class:`datetime`. Defaults to
                ``datetime.now``, so an existing caller is unaffected. A
                consumer driving *simulated* time (a sandbox stepping days in
                milliseconds, a replay, a test) supplies its own and the whole
                world -- including every engine that reads the clock through
                :meth:`now` -- follows it. See :meth:`now`.
            rng: Optional ``random.Random`` this world draws weather (and any
                other world-level randomness) from. A world can be shared by
                every persona in a household (:class:`~aura_life.life_service.LifeService`
                never passes it one of a persona's own streams for exactly
                that reason), so it owns its own source rather than taking
                one from any single persona. Takes precedence over ``seed``.
            seed: Optional seed to build one from, when ``rng`` is not given
                (ignored if it is). ``None`` for both -- the default -- is a
                fresh, unseeded ``random.Random()`` (never the module), so a
                bare ``WorldEnvironment()`` still works and shares no draw
                sequence with any other instance or the module. A caller
                that wants two worlds (or two runs) to draw the same weather
                passes the same ``seed`` or an equally-seeded ``rng`` to each.
            setting: The setting pack (:class:`~aura_life.settings.SettingSpec`)
                whose ``place_descriptions`` (a place no persona profile
                describes), ``weather_descriptions`` and
                ``cherished_objects`` this world reads. ``None`` -- the
                default -- is :data:`~aura_life.settings.DEFAULT_SETTING`'s.
                A caller describing a specific persona in a shared world
                passes her setting per call instead (``setting=`` on
                :meth:`get_location_description`, :meth:`get_status`,
                :meth:`export_state` ...).
        """
        self._rng = rng if rng is not None else random.Random(seed)
        self._setting: SettingSpec = setting if setting is not None else get_setting(DEFAULT_SETTING)
        self._persona_locations: Dict[str, str] = persona_locations or {}
        self._sleep_schedule: Optional[Dict] = sleep_schedule
        self._current_location: str = "home"
        # Must be installed before the WorldState below: building it calls
        # _get_appropriate_weather(), which reads the clock.
        self._now: Callable[[], datetime] = now or datetime.now
        self._state = WorldState(
            current_location=Location.LIVING_ROOM,  # legacy field kept for compat
            weather=self._get_appropriate_weather(),
            virtual_time=self.now(),
            time_of_day=self._calculate_time_of_day(self.now()),
            season=self._calculate_season(self.now()),
        )
        self._update_ambiance()

    def now(self) -> datetime:
        """The current instant, from this world's clock.

        Every wall-clock read inside this class goes through here, and
        :class:`~aura_life.life_service.LifeService` hands this bound method to
        the engines that measure elapsed time (today: the energy system), so a
        world on a simulated clock produces a simulated circadian rhythm rather
        than one keyed to how long the host process has been alive.

        A subclass that derives time from something other than a callable --
        Hollow's ``DeterministicWorld`` derives it from a tick counter and an
        epoch -- overrides this method instead of passing ``now=``. Whatever
        such an override reads must be assigned **before** it calls
        ``super().__init__()``: the constructor builds ``WorldState``, and doing
        so reads the clock.
        """
        return self._now()

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
        # Update virtual time to match the world's clock
        now = self.now()
        self._state.virtual_time = now
        self._state.time_of_day = self._calculate_time_of_day(now)
        self._state.season = self._calculate_season(now)

        # Weather transition (20% chance per tick)
        if self._rng.random() < 0.2:
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

    def get_location_description(
        self,
        location: Optional[str] = None,
        persona_locations: Optional[Dict[str, str]] = None,
        setting: Optional[SettingSpec] = None,
    ) -> str:
        """Get description of a location. Checks persona-specific descriptions first.

        Args:
            location: The location key to describe. Defaults to the current one.
            persona_locations: Descriptions to check instead of this world's own
                ``_persona_locations``. A world shared by several
                :class:`~aura_life.life_service.LifeService` instances holds only
                one ``_persona_locations`` dict, so a caller describing a specific
                persona's room passes that persona's own mapping here rather than
                relying on whichever persona's data this instance was constructed
                (or last handed) with. ``None`` -- the default -- keeps today's
                behaviour for a private world or a caller that predates this
                parameter.
            setting: The setting whose ``place_descriptions`` are the generic
                fallback, instead of this world's own -- for the same reason:
                a caller describing a specific persona in a shared world
                passes hers. ``None`` -- the default -- is this world's own.
        """
        loc = location or self._current_location
        plocs = self._persona_locations if persona_locations is None else persona_locations
        # Persona-specific description takes priority
        if loc in plocs:
            return plocs[loc]
        # Also check with lowercase key variants
        loc_lower = loc.lower()
        for key, desc in plocs.items():
            if key.lower() == loc_lower:
                return desc
        # Generic fallback
        generic = (self._setting if setting is None else setting).place_descriptions
        return generic.get(loc, generic.get(loc_lower, f"somewhere ({loc})"))

    def get_weather_description(self, setting: Optional[SettingSpec] = None) -> str:
        """Get description of current weather: ``setting``'s (this world's own
        when ``None``) ``weather_descriptions``."""
        return (self._setting if setting is None else setting).weather_descriptions.get(self._state.weather, "")

    def get_ambiance(self) -> str:
        """Get current ambiance description."""
        return self._state.ambiance_description

    def get_mood_from_weather(self) -> Dict[str, float]:
        """Get mood effects from current weather."""
        return WEATHER_MOOD_EFFECTS.get(self._state.weather, {})

    def get_cherished_objects_at_location(self, location: Optional[str] = None,
                                          setting: Optional[SettingSpec] = None) -> List[CherishedObject]:
        """Get cherished objects at current or specified location (``setting``'s,
        this world's own when ``None``)."""
        loc = location or self._current_location
        # Match cherished objects whose Location enum value maps to this string key
        results = []
        for obj in (self._setting if setting is None else setting).cherished_objects:
            obj_key = LOCATION_ENUM_TO_KEY.get(obj.location.value, obj.location.value)
            if obj_key == loc or obj.location.value == loc:
                results.append(obj)
        return results

    def get_random_cherished_object(self, setting: Optional[SettingSpec] = None) -> Optional[CherishedObject]:
        """Get a random cherished object for narrative flavor (``setting``'s,
        this world's own when ``None``)."""
        objects = (self._setting if setting is None else setting).cherished_objects
        if objects:
            return self._rng.choice(objects)
        return None

    def export_state(
        self,
        persona_locations: Optional[Dict[str, str]] = None,
        sleep_schedule: Optional[Dict] = None,
        current_location: Optional[str] = None,
        setting: Optional[SettingSpec] = None,
    ) -> dict:
        """Structured dict for LLM pipeline digest passes.

        Args:
            persona_locations: Forwarded to :meth:`get_location_description`.
                Also folds into the exported ``ambiance`` sentence's location
                clause instead of the cached one.
            sleep_schedule: Forwarded to :meth:`get_time_of_day`.
            current_location: The location key to report instead of this
                world's own tracked one -- a caller sharing this world across
                personas (:class:`~aura_life.life_service.LifeService`, which
                owns its own current location precisely so it can pass it
                here, see Task 27 / ruling T8-R1) passes this persona's own,
                so ``location`` and ``location_description`` describe her
                instead of wherever this (possibly shared) instance's own
                ``current_location`` happens to be.
            setting: The persona's setting, forwarded to
                :meth:`get_location_description` (its generic place
                descriptions) and read for the weather's description; folds
                into ``ambiance`` like ``persona_locations``.

        With none of ``persona_locations``, ``current_location`` and
        ``setting``, ``time_of_day`` and ``ambiance`` are exactly
        today's (this world's own tracked phase and cached ambiance).
        ``location_description`` is a new key -- :meth:`get_status` already
        has it, and adding a key here is additive, never a removed or
        repurposed one. A caller sharing this world across personas passes
        all of its own, so ``time_of_day``, ``location``,
        ``location_description`` and ``ambiance`` describe that persona
        instead of whichever persona's data this instance holds.
        """
        loc = self._current_location if current_location is None else current_location
        location_description = self.get_location_description(
            loc, persona_locations=persona_locations, setting=setting)
        ambiance = (
            self._state.ambiance_description
            if persona_locations is None and current_location is None and setting is None
            else self._build_ambiance(location_description, setting=setting)
        )
        return {
            "location": loc,
            "location_description": location_description,
            "weather": self._state.weather.value,
            "time_of_day": self.get_time_of_day(sleep_schedule).value,
            "season": self._state.season.value,
            "ambiance": ambiance,
        }

    def get_status(
        self,
        persona_locations: Optional[Dict[str, str]] = None,
        sleep_schedule: Optional[Dict] = None,
        current_location: Optional[str] = None,
        setting: Optional[SettingSpec] = None,
    ) -> dict:
        """Get world status as dict.

        Args:
            persona_locations: Forwarded to :meth:`get_location_description`.
            sleep_schedule: Forwarded to :meth:`get_time_of_day`.
            current_location: The location key to report instead of this
                world's own tracked one -- see :meth:`export_state`, whose
                ``current_location`` argument means the same thing.
            setting: As in :meth:`export_state` (it also sets
                ``weather_description``, and rebuilds ``ambiance`` the same
                way).

        With none of the four, this is exactly today's behaviour (this
        world's own tracked location and time-of-day phase, and its cached
        ambiance sentence). A caller sharing this world across personas
        passes its own of each, so ``location``, ``location_description`` and
        ``time_of_day`` describe that persona rather than whichever persona's
        data this instance holds -- and so does ``ambiance`` (fix round 1,
        Important): with either override given it is rebuilt from that
        persona's own location, mirroring :meth:`export_state`, rather than
        staying this world's own cached sentence. A shared world's own
        ``current_location`` is never written by a persona's move (Task 27 /
        ruling T8-R1), so that cached sentence would otherwise stay frozen at
        whatever it was built from at construction and contradict the
        ``location``/``location_description`` this same dict reports for the
        persona asking.
        """
        loc = self._current_location if current_location is None else current_location
        location_description = self.get_location_description(
            loc, persona_locations=persona_locations, setting=setting)
        ambiance = (
            self._state.ambiance_description
            if persona_locations is None and current_location is None and setting is None
            else self._build_ambiance(location_description, setting=setting)
        )
        return {
            "location": loc,
            "location_description": location_description,
            "weather": self._state.weather.value,
            "weather_description": self.get_weather_description(setting),
            "time_of_day": self.get_time_of_day(sleep_schedule).value,
            "season": self._state.season.value,
            "ambiance": ambiance,
            "virtual_time": self._state.virtual_time.isoformat(),
        }

    def get_time_of_day(self, sleep_schedule: Optional[Dict] = None) -> TimeOfDay:
        """This world's time-of-day phase, optionally for a given sleep schedule.

        With no argument, returns the phase this world already tracks
        (equivalent to the :attr:`time_of_day` property) -- current as of the
        last :meth:`tick`, computed from this world's own ``_sleep_schedule``.
        A caller sharing this world across personas (see
        :class:`~aura_life.life_service.LifeService`, which no longer writes a
        shared world's ``_sleep_schedule`` at construction) passes its own
        schedule instead of trusting that tracked phase: the phase is then
        recalculated fresh, at this world's current instant, from that
        schedule -- so it is that persona's own phase even when this world
        was never ticked with her schedule attached.
        """
        if sleep_schedule is None:
            return self._state.time_of_day
        return self._calculate_time_of_day(self.now(), sleep_schedule)

    # ============= Private Methods =============

    def _calculate_time_of_day(
        self, dt: datetime, sleep_schedule: Optional[Dict] = None,
    ) -> TimeOfDay:
        """Calculate time of day relative to a sleep schedule.

        Instead of using wall-clock hours, maps hours-since-wake to
        circadian phases so a persona waking at noon gets DAWN at 12:00,
        MORNING at 14:00, etc.  Falls back to wall clock if no schedule.

        Args:
            dt: The instant to compute the phase for.
            sleep_schedule: Schedule to use instead of this world's own
                ``_sleep_schedule``. ``None`` -- the default -- keeps today's
                behaviour (this world's own schedule, or the wall-clock
                fallback when it has none); see :meth:`get_time_of_day` for
                the public entry point a caller sharing this world uses to
                pass a specific persona's schedule.
        """
        schedule = self._sleep_schedule if sleep_schedule is None else sleep_schedule
        if not schedule:
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

        wake_hour = schedule.get("wake_hour", 7)
        bedtime_hour = schedule.get("bedtime_hour", 23)

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
        now = self.now()
        time_of_day = self._wall_clock_time_of_day(now)
        season = self._calculate_season(now)

        # Night times
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            return self._rng.choice([Weather.CLEAR_NIGHT, Weather.STARRY, Weather.FOGGY])

        # Season-appropriate day weather
        if season == Season.WINTER:
            return self._rng.choice([Weather.CLOUDY, Weather.SNOWY, Weather.FOGGY, Weather.RAINY])
        elif season == Season.SUMMER:
            return self._rng.choice([Weather.SUNNY, Weather.SUNNY, Weather.CLOUDY])
        elif season == Season.SPRING:
            return self._rng.choice([Weather.SUNNY, Weather.CLOUDY, Weather.RAINY, Weather.FOGGY])
        else:  # Autumn
            return self._rng.choice([Weather.CLOUDY, Weather.RAINY, Weather.FOGGY, Weather.SUNNY])

    def _transition_weather(self) -> None:
        """Transition weather based on probabilities."""
        current = self._state.weather
        time_of_day = self._wall_clock_time_of_day(self.now())

        # Force night weather during night hours
        if time_of_day in (TimeOfDay.NIGHT, TimeOfDay.LATE_NIGHT):
            if current not in (Weather.CLEAR_NIGHT, Weather.STARRY, Weather.FOGGY, Weather.STORMY):
                self._state.weather = self._rng.choice([Weather.CLEAR_NIGHT, Weather.STARRY])
                return

        # Force day weather during day hours
        if time_of_day in (TimeOfDay.DAWN, TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING):
            if current in (Weather.CLEAR_NIGHT, Weather.STARRY):
                self._state.weather = self._rng.choice([Weather.SUNNY, Weather.CLOUDY])
                return

        # Normal transition
        transitions = WEATHER_TRANSITIONS.get(current, {})
        if transitions:
            weather_options = list(transitions.keys())
            probabilities = list(transitions.values())
            self._state.weather = self._rng.choices(weather_options, probabilities)[0]

    def _build_ambiance(self, location_desc: Optional[str] = None,
                        setting: Optional[SettingSpec] = None) -> str:
        """Compose an ambiance sentence from a location description, current weather and wall-clock time.

        Args:
            location_desc: Text to open the sentence with. ``None`` -- the
                default -- uses this world's own :meth:`get_location_description`;
                :meth:`export_state` passes a specific persona's own
                description instead when it was given one.
            setting: Whose weather description to use (this world's own
                when ``None``).
        """
        loc_desc = self.get_location_description() if location_desc is None else location_desc
        weather_desc = self.get_weather_description(setting)

        # Time-specific additions — use wall clock for physical light descriptions
        wall_time = self._wall_clock_time_of_day(self.now())
        time_additions = {
            TimeOfDay.DAWN: "The world is waking up softly",
            TimeOfDay.MORNING: "Morning light fills the space",
            TimeOfDay.AFTERNOON: "The afternoon settles in peacefully",
            TimeOfDay.EVENING: "Evening light paints everything golden",
            TimeOfDay.NIGHT: "Night has fallen, quiet and still",
            TimeOfDay.LATE_NIGHT: "The world sleeps, wrapped in silence",
        }
        time_desc = time_additions.get(wall_time, "")

        return f"{loc_desc}. {weather_desc}. {time_desc}."

    def _update_ambiance(self) -> None:
        """Update the ambiance description based on current state."""
        self._state.ambiance_description = self._build_ambiance()


class PersonaWorldView:
    """One persona's view onto a ``WorldEnvironment`` she shares with others.

    :class:`~aura_life.life_service.LifeService` hands this -- never the
    shared world itself -- to anything that renders a location description
    for a system prompt (today: ``LifeContextBuilder``), so a persona sharing
    a world with other personas still describes her own room instead of
    whichever persona's ``persona_locations`` the shared instance was
    constructed or last handed with (see :meth:`WorldEnvironment.get_location_description`).

    Weather is genuinely shared physical state (the same sky) and passes
    straight through to the wrapped world. Current location is not (Task 27 /
    ruling T8-R1 corrects Task 2 here): it is this persona's own, read fresh
    on every call from *current_location* -- a zero-argument callable, not a
    snapshot, because this view is built once, in
    :class:`~aura_life.life_service.LifeService`'s constructor, and this
    persona's location moves many times over her lifetime (the same shape of
    problem :meth:`WorldEnvironment.now` solves for the clock). Passing it
    straight through, like weather, is exactly the bug this corrects: it is
    what let one persona's move relocate every persona sharing the world.

    A private (unshared) world needs no wrapping: its own
    ``persona_locations`` and location already belong to the one persona
    using it.
    """

    def __init__(
        self,
        world: WorldEnvironment,
        persona_locations: Dict[str, str],
        current_location: Callable[[], str],
        setting: Optional[SettingSpec] = None,
    ):
        """``setting``: this persona's setting pack, whose place
        descriptions (where her profile describes no place) and weather
        descriptions this view reads; ``None`` leaves the wrapped world's own."""
        self._world = world
        self._persona_locations = persona_locations
        self._current_location = current_location
        self._setting = setting

    def get_location_description(self, location: Optional[str] = None) -> str:
        """This persona's description of *location* (or her own current one)."""
        loc = self._current_location() if location is None else location
        if self._setting is None:
            return self._world.get_location_description(loc, persona_locations=self._persona_locations)
        return self._world.get_location_description(
            loc, persona_locations=self._persona_locations, setting=self._setting)

    def get_weather_description(self) -> str:
        if self._setting is None:
            return self._world.get_weather_description()
        return self._world.get_weather_description(self._setting)

    @property
    def current_location(self) -> str:
        return self._current_location()

    @property
    def weather(self) -> Weather:
        return self._world.weather
