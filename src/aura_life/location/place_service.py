"""
PlaceService — home city resolution, persistence, and backfill.

Resolution tiers (human personas only; AI personas are a no-op):

  Tier 1 — profile-explicit: persona already has home_city or lat/lon set.
  Tier 2 — device GPS: a fuzzed (~40 km) GPS point was POSTed by the Android
            app; the server uses it as the home anchor.  Timezone is resolved
            via Open-Meteo Forecast (which returns ``timezone`` for any lat/lon).
            City label may be blank — weather and time still work from lat/lon.
            Only active when AURA_LOCATION_GPS_ENABLED=true.  Safe-fail: any
            error falls through to Tier 3.
  Tier 3 — LLM-pick: LLM picks a plausible real city; geocoded + tz-validated;
            re-rolled up to PLACE_RESOLVE_MAX_ATTEMPTS times on failure;
            falls back to a built-in safe default if all rolls fail.

T1.3 will wire timezone into time-of-day — not here.
"""

import json
import logging
import random as _random
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Sentinel appearance_origin value a creation path sets on a brand-new persona to
# request a one-time demographic-appearance roll on first home assignment.  Any
# other value (default "local", or a resolved local/adopted/immigrant/expat) means
# the persona is NOT a fresh roll candidate and must never be re-rolled.
_APPEARANCE_PENDING = "pending"


# ============= Built-in fallback cities (server tz offset → EN/FR city) =============
# Keyed by integer UTC offset in hours; used when all LLM+geocode attempts fail.
# Coverage: offsets −12..+14, biased toward EN/FR-speaking places.

_FALLBACK_CITIES: dict = {
    -12: {"city": "Baker Island", "country": "United States", "lat": 0.19, "lon": -176.48, "timezone": "Etc/GMT+12"},
    -11: {"city": "Pago Pago", "country": "American Samoa", "lat": -14.28, "lon": -170.70, "timezone": "Pacific/Pago_Pago"},
    -10: {"city": "Honolulu", "country": "United States", "lat": 21.31, "lon": -157.86, "timezone": "Pacific/Honolulu"},
    -9:  {"city": "Anchorage", "country": "United States", "lat": 61.22, "lon": -149.90, "timezone": "America/Anchorage"},
    -8:  {"city": "Vancouver", "country": "Canada", "lat": 49.25, "lon": -123.12, "timezone": "America/Vancouver"},
    -7:  {"city": "Calgary", "country": "Canada", "lat": 51.05, "lon": -114.07, "timezone": "America/Edmonton"},
    -6:  {"city": "Chicago", "country": "United States", "lat": 41.88, "lon": -87.63, "timezone": "America/Chicago"},
    -5:  {"city": "Toronto", "country": "Canada", "lat": 43.65, "lon": -79.38, "timezone": "America/Toronto"},
    -4:  {"city": "Halifax", "country": "Canada", "lat": 44.65, "lon": -63.58, "timezone": "America/Halifax"},
    -3:  {"city": "Montreal", "country": "Canada", "lat": 45.50, "lon": -73.57, "timezone": "America/Montreal"},  # approximate; Montreal is UTC-5/-4
    -2:  {"city": "Saint-Pierre", "country": "Saint Pierre and Miquelon", "lat": 46.78, "lon": -56.17, "timezone": "America/Miquelon"},
    -1:  {"city": "Ponta Delgada", "country": "Portugal", "lat": 37.74, "lon": -25.67, "timezone": "Atlantic/Azores"},
    0:   {"city": "London", "country": "United Kingdom", "lat": 51.51, "lon": -0.13, "timezone": "Europe/London"},
    1:   {"city": "Paris", "country": "France", "lat": 48.85, "lon": 2.35, "timezone": "Europe/Paris"},
    2:   {"city": "Brussels", "country": "Belgium", "lat": 50.85, "lon": 4.35, "timezone": "Europe/Brussels"},
    3:   {"city": "Nairobi", "country": "Kenya", "lat": -1.29, "lon": 36.82, "timezone": "Africa/Nairobi"},
    4:   {"city": "Dubai", "country": "United Arab Emirates", "lat": 25.20, "lon": 55.27, "timezone": "Asia/Dubai"},
    5:   {"city": "Karachi", "country": "Pakistan", "lat": 24.86, "lon": 67.01, "timezone": "Asia/Karachi"},
    6:   {"city": "Dhaka", "country": "Bangladesh", "lat": 23.73, "lon": 90.39, "timezone": "Asia/Dhaka"},
    7:   {"city": "Bangkok", "country": "Thailand", "lat": 13.75, "lon": 100.52, "timezone": "Asia/Bangkok"},
    8:   {"city": "Singapore", "country": "Singapore", "lat": 1.29, "lon": 103.85, "timezone": "Asia/Singapore"},
    9:   {"city": "Tokyo", "country": "Japan", "lat": 35.69, "lon": 139.69, "timezone": "Asia/Tokyo"},
    10:  {"city": "Sydney", "country": "Australia", "lat": -33.87, "lon": 151.21, "timezone": "Australia/Sydney"},
    11:  {"city": "Noumea", "country": "New Caledonia", "lat": -22.27, "lon": 166.46, "timezone": "Pacific/Noumea"},
    12:  {"city": "Auckland", "country": "New Zealand", "lat": -36.86, "lon": 174.77, "timezone": "Pacific/Auckland"},
    13:  {"city": "Nuku'alofa", "country": "Tonga", "lat": -21.14, "lon": -175.22, "timezone": "Pacific/Tongatapu"},
    14:  {"city": "Apia", "country": "Samoa", "lat": -13.83, "lon": -172.33, "timezone": "Pacific/Apia"},
}


def _tz_offset_hours(timezone_str: str) -> Optional[float]:
    """Return the current UTC offset in hours for an IANA timezone string, or None."""
    if not timezone_str:
        return None
    try:
        import zoneinfo  # Python 3.9+
        tz = zoneinfo.ZoneInfo(timezone_str)
        offset = datetime.now(tz).utcoffset()
        if offset is None:
            return None
        return offset.total_seconds() / 3600.0
    except Exception:
        # Fallback: try pytz if available
        try:
            import pytz  # type: ignore
            tz = pytz.timezone(timezone_str)
            offset = datetime.now(tz).utcoffset()
            if offset is None:
                return None
            return offset.total_seconds() / 3600.0
        except Exception:
            return None


def _parse_city_json(text: str) -> Optional[dict]:
    """Tolerantly parse a {city, country} JSON dict from LLM output.

    Strips markdown code fences and finds the first {...} block.
    Returns None if parsing fails or required keys are missing.
    """
    if not text:
        return None
    # Strip markdown fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```", "", text)
    # Find first {...}
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
        city = obj.get("city", "").strip()
        country = obj.get("country", "").strip()
        if city and country:
            return {"city": city, "country": country}
        # Try alternate keys
        city = city or obj.get("name", "").strip() or obj.get("place", "").strip()
        country = country or obj.get("nation", "").strip() or obj.get("country_name", "").strip()
        if city and country:
            return {"city": city, "country": country}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


class PlaceService:
    """
    Resolves and persists a persona's home city.

    Injectable deps for testability:
      llm             — object with .generate(text, system_prompt, max_tokens) -> str
      geocode         — callable(name, count, session) -> dict | None
      server_tz       — tzinfo or callable returning current UTC offset hours (float)
      rng             — random.Random instance (seeded in tests)
      get_device_loc  — callable() -> dict|None; defaults to
                        aura_life.location.device_location.get_device_location.
                        Override in tests to mock the device store.
      forecast_tz     — callable(lat, lon) -> str|None; returns IANA tz string
                        for a lat/lon via Open-Meteo Forecast.  Override in
                        tests to avoid network calls.
    """

    def __init__(
        self,
        *,
        llm=None,
        geocode=None,
        server_tz=None,
        rng=None,
        get_device_loc=None,
        forecast_tz=None,
    ):
        self._llm = llm
        self._geocode = geocode
        self._server_tz = server_tz  # unused for now; offset computed via stdlib
        self._rng = rng or _random.Random()
        self._get_device_loc = get_device_loc
        self._forecast_tz = forecast_tz

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from aura_life.hooks import get_llm_service
        return get_llm_service()

    def _get_geocode(self):
        if self._geocode is not None:
            return self._geocode
        from aura_life.hooks import geocode
        return geocode

    def _get_config(self):
        from aura_life.hooks import get_config
        return get_config()

    def _get_device_location(self) -> Optional[dict]:
        """Return the stored device location dict or None."""
        if self._get_device_loc is not None:
            return self._get_device_loc()
        from aura_life.location.device_location import get_device_location
        return get_device_location()

    def _resolve_tz_for_point(self, lat: float, lon: float) -> str:
        """Return an IANA timezone string for (lat, lon) via Open-Meteo Forecast.

        Safe-fail: returns "" on any error or missing data.
        """
        try:
            if self._forecast_tz is not None:
                return self._forecast_tz(lat, lon) or ""
            from aura_life.hooks import resolve_timezone
            return resolve_timezone(lat, lon) or ""
        except Exception as exc:
            logger.warning("_resolve_tz_for_point(%.4f, %.4f) failed: %s", lat, lon, exc)
            return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def server_local_offset_hours(self) -> float:
        """Current UTC offset of the server machine in hours."""
        try:
            return datetime.now().astimezone().utcoffset().total_seconds() / 3600.0
        except Exception:
            return 0.0

    def resolve_home(self, definition) -> Optional[dict]:
        """Return {city, country, lat, lon, timezone} for *definition*'s home.

        Returns None for AI personas. Never raises — any failure returns a safe
        default or None.
        """
        # AI personas have no physical home
        if getattr(definition, "persona_type", "human") == "ai":
            return None

        cfg = self._get_config()

        # --- Tier 1: profile-explicit home ---
        home_city = getattr(definition, "home_city", "") or ""
        home_lat = getattr(definition, "home_lat", None)
        home_lon = getattr(definition, "home_lon", None)
        home_country = getattr(definition, "home_country", "") or ""
        home_tz = getattr(definition, "home_timezone", "") or ""

        if home_lat is not None and home_lon is not None:
            # Coords already present — use directly (no geocode needed)
            return {
                "city": home_city,
                "country": home_country,
                "lat": float(home_lat),
                "lon": float(home_lon),
                "timezone": home_tz,
            }

        if home_city:
            # City name present — geocode it
            result = self._geocode_safe(home_city)
            if result:
                return result
            # Geocode failed — return a stub with the city name so it's still set
            logger.warning(
                "resolve_home: geocode failed for profile city %r; using name-only stub",
                home_city,
            )
            return {
                "city": home_city,
                "country": home_country,
                "lat": None,
                "lon": None,
                "timezone": home_tz,
            }

        # --- Tier 2: device GPS (fuzzed, user's own area) ---
        if cfg.location_gps_enabled:
            device_home = self._resolve_via_device(cfg)
            if device_home is not None:
                return device_home

        # --- Tier 3: LLM-pick ---
        return self._resolve_via_llm(definition, cfg)

    def assign_home_if_missing(self, definition, life_service) -> bool:
        """Assign a home city to *definition* if it lacks one.

        Persists home_* to profile.db and current_* to life.db via
        life_service._save_place_state().  Idempotent (no-op when home
        is already set).  Returns True if a home was assigned.
        """
        cfg = self._get_config()
        if not cfg.place_enabled:
            return False

        # AI personas never have a home
        if getattr(definition, "persona_type", "human") == "ai":
            return False

        # Already have a home?
        if self._has_home(definition):
            return False

        home = self.resolve_home(definition)
        if not home:
            return False

        # --- Persist to profile.db ---
        self._persist_to_profile_db(life_service, home)

        # --- Update life.db current_* via _save_place_state ---
        from aura_life.models import PlaceLocationState
        place = life_service._place_location
        if not place.current_city:
            life_service._place_location = PlaceLocationState(
                current_city=home["city"],
                current_lat=home.get("lat"),
                current_lon=home.get("lon"),
                current_timezone=home.get("timezone", ""),
                on_trip=place.on_trip,
                trip_destination=place.trip_destination,
                trip_returns_at=place.trip_returns_at,
                trip_reason=place.trip_reason,
                weather_code=place.weather_code,
                weather_label=place.weather_label,
                weather_temp_c=place.weather_temp_c,
                weather_is_day=place.weather_is_day,
                weather_fetched_at=place.weather_fetched_at,
                weather_source=place.weather_source,
            )
        try:
            life_service._save_place_state()
        except Exception as exc:
            logger.warning("assign_home_if_missing: _save_place_state failed: %s", exc)

        # Also update the in-memory definition so subsequent code sees the home
        try:
            definition.home_city = home["city"]
            definition.home_country = home["country"]
            definition.home_lat = home.get("lat")
            definition.home_lon = home.get("lon")
            definition.home_timezone = home.get("timezone", "")
        except AttributeError:
            pass

        # --- Generate cultural stance when none is set yet ---
        existing_stance = getattr(definition, "cultural_stance", None)
        if not existing_stance:
            self._maybe_generate_cultural_stance(definition, home, life_service)

        # --- Generate demographic appearance for a NEW randomized persona ---
        # Gated on the "pending" sentinel that creation paths set on a brand-new
        # human persona.  EXISTING personas (appearance_origin == "local" or any
        # resolved value) are NEVER re-rolled.  AI personas already returned above.
        if getattr(definition, "appearance_origin", "local") == _APPEARANCE_PENDING:
            self._maybe_generate_appearance(definition, home, life_service)

        logger.info(
            "assign_home_if_missing: assigned %s, %s to persona %s",
            home["city"], home["country"],
            getattr(definition, "id", "?"),
        )
        return True

    # ------------------------------------------------------------------
    # Private implementation
    # ------------------------------------------------------------------

    @staticmethod
    def _has_home(definition) -> bool:
        """True when the definition already has a usable home location."""
        return bool(
            getattr(definition, "home_city", "")
            or getattr(definition, "home_lat", None) is not None
        )

    def _geocode_safe(self, city_name: str) -> Optional[dict]:
        try:
            return self._get_geocode()(city_name)
        except Exception as exc:
            logger.warning("geocode_safe(%r) error: %s", city_name, exc)
            return None

    def _resolve_via_device(self, cfg) -> Optional[dict]:
        """Tier 2: use the stored fuzzed device location as the home anchor.

        Returns a home dict {city, country, lat, lon, timezone} on success, or
        None if no device location is stored or any step fails (safe-fail).
        City and country may be blank — lat/lon + timezone are sufficient for
        weather and time-of-day.
        """
        try:
            loc = self._get_device_location()
            if not loc:
                return None
            lat = loc["lat"]
            lon = loc["lon"]
            tz = self._resolve_tz_for_point(lat, lon)
            logger.info(
                "resolve_home: Tier-2 device GPS (%.4f, %.4f) tz=%r",
                lat, lon, tz,
            )
            return {
                "city": "",
                "country": "",
                "lat": lat,
                "lon": lon,
                "timezone": tz,
            }
        except Exception as exc:
            logger.warning("_resolve_via_device failed, falling through to Tier-3: %s", exc)
            return None

    def _resolve_via_llm(self, definition, cfg) -> dict:
        """Tier 3: ask the LLM for a plausible home city, geocode + validate."""
        server_offset = self.server_local_offset_hours()
        max_offset = getattr(cfg, "place_max_tz_offset_hours", 5)
        max_attempts = getattr(cfg, "place_resolve_max_attempts", 4)

        # Build a short persona sketch for the LLM
        traits = getattr(definition, "core_traits", []) or []
        interests = getattr(definition, "interests", []) or []
        occupation = getattr(definition, "occupation", "") or ""
        sketch_parts = []
        if traits:
            sketch_parts.append(f"traits: {', '.join(traits[:3])}")
        if occupation:
            sketch_parts.append(f"occupation: {occupation}")
        if interests:
            sketch_parts.append(f"interests: {', '.join(interests[:3])}")
        sketch = "; ".join(sketch_parts) if sketch_parts else "no specific traits"

        system_prompt = (
            "You are a location assistant. Respond with ONLY a JSON object, "
            "no prose, no markdown fences."
        )
        user_prompt = (
            f"Pick ONE real city for a fictional persona ({sketch}).\n"
            f"Requirements:\n"
            f"- English OR French spoken as a first or second language\n"
            f"- Reliable smartphone and internet access\n"
            f"- UTC offset within ±{max_offset} hours of UTC{server_offset:+.0f}\n"
            f"Respond with exactly: {{\"city\": \"...\", \"country\": \"...\"}}"
        )

        llm = self._get_llm()
        last_result: Optional[dict] = None

        for attempt in range(max_attempts):
            try:
                raw = llm.generate(
                    user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=60,
                )
            except Exception as exc:
                logger.warning("resolve_via_llm attempt %d: LLM error: %s", attempt, exc)
                continue

            parsed = _parse_city_json(raw)
            if not parsed:
                logger.debug("resolve_via_llm attempt %d: JSON parse failed", attempt)
                continue

            geo = self._geocode_safe(f"{parsed['city']}, {parsed['country']}")
            if not geo:
                logger.debug(
                    "resolve_via_llm attempt %d: geocode failed for %r",
                    attempt, parsed,
                )
                continue

            # Validate tz offset
            tz_offset = _tz_offset_hours(geo.get("timezone", ""))
            if tz_offset is not None:
                if abs(tz_offset - server_offset) > max_offset:
                    logger.debug(
                        "resolve_via_llm attempt %d: tz offset %.1fh out of ±%dh range (server=%.1fh)",
                        attempt, tz_offset, max_offset, server_offset,
                    )
                    last_result = geo  # remember but don't accept yet
                    continue

            logger.info(
                "resolve_via_llm: resolved home as %s, %s (attempt %d)",
                geo["city"], geo["country"], attempt,
            )
            return geo

        # All attempts failed — return safe default for server's tz
        return self._safe_default(server_offset)

    def _safe_default(self, server_offset_hours: float) -> dict:
        """Return a built-in fallback city near the server's UTC offset."""
        rounded = int(round(server_offset_hours))
        # Clamp to table range
        rounded = max(-12, min(14, rounded))
        if rounded in _FALLBACK_CITIES:
            city = _FALLBACK_CITIES[rounded].copy()
            logger.warning(
                "resolve_home: using safe-default city %s, %s (offset=%+.1fh)",
                city["city"], city["country"], server_offset_hours,
            )
            return city
        # Absolute last resort
        return {
            "city": "",
            "country": "",
            "lat": None,
            "lon": None,
            "timezone": "",
        }

    def _maybe_generate_cultural_stance(self, definition, home: dict, life_service) -> None:
        """Generate and persist a cultural stance when none exists yet.

        Safe-fail: any error is logged and silently swallowed so home assignment
        is never rolled back.  AI personas are a no-op (handled in generate_cultural_stance).
        """
        try:
            from aura_life.personas.place_generation import generate_cultural_stance
            stance_data = generate_cultural_stance(
                definition, home, llm=self._llm
            )
            if not stance_data.get("cultural_stance"):
                return  # LLM returned empty — nothing to persist
            self._persist_cultural_stance(life_service, stance_data)
            # Update in-memory definition
            try:
                definition.cultural_stance = stance_data["cultural_stance"]
                definition.cultural_summary = stance_data.get("cultural_summary", "")
            except AttributeError:
                pass
        except Exception as exc:
            logger.warning(
                "_maybe_generate_cultural_stance: failed for %s: %s",
                getattr(definition, "id", "?"), exc,
            )

    def _maybe_generate_appearance(self, definition, home: dict, life_service) -> None:
        """Generate + persist demographic-realistic appearance for a NEW persona.

        Called only when ``appearance_origin == "pending"`` (set by a creation path
        on a brand-new human persona).  Grounds physical features in the just-assigned
        ``home`` and a rolled origin (with an outlier chance).  Safe-fail: any error
        is logged and swallowed so home assignment is never rolled back.  AI personas
        are a no-op (handled in generate_appearance, and never reach here anyway).
        """
        try:
            from aura_life.personas.place_generation import generate_appearance
            data = generate_appearance(definition, home, llm=self._llm, rng=self._rng)
            appearance = data.get("appearance") or {}
            origin = data.get("appearance_origin", "local")
            if not appearance:
                # LLM gave nothing usable — clear the sentinel so we don't retry
                # forever, but write no fabricated features.
                origin = "local"
            self._persist_appearance(life_service, appearance, origin)
            # Update in-memory definition so this session sees the new look and the
            # sentinel is cleared (no re-roll within the same run).  Also clear
            # base_prompt so image_service uses the rolled demographic fields instead.
            try:
                details = getattr(definition, "appearance_details", None)
                if isinstance(details, dict):
                    details.update(appearance)
                    details["base_prompt"] = ""
                definition.appearance_origin = origin
            except AttributeError:
                pass
        except Exception as exc:
            logger.warning(
                "_maybe_generate_appearance: failed for %s: %s",
                getattr(definition, "id", "?"), exc,
            )

    def _persist_appearance(self, life_service, appearance: dict, origin: str) -> None:
        """Write demographic appearance fields + appearance_origin to profile.db.

        Non-destructive: only the whitelisted physical "looks" columns
        (via update_appearance) and the appearance_origin column are touched.

        Clears ``base_prompt`` so the demographic fields built here win over any
        stale authored base_prompt from the creation wizard.  This is safe because
        this method is ONLY called for NEW personas (appearance_origin == "pending").
        """
        try:
            from pathlib import Path
            from aura_life.personas.profile_db import ProfileDatabase
            life_db_path = life_service._db_path
            profile_db_path = str(Path(life_db_path).parent / "profile.db")
            pdb = ProfileDatabase(profile_db_path)
            if pdb.exists():
                if appearance:
                    pdb.update_appearance(appearance)
                # Clear any stale authored base_prompt so the rolled demographic
                # fields are used by image_service instead of the old catch-all.
                pdb.update_appearance({"base_prompt": ""})
                pdb.update_appearance_origin(origin)
        except Exception as exc:
            logger.warning("_persist_appearance failed: %s", exc)

    def _persist_cultural_stance(self, life_service, stance_data: dict) -> None:
        """Write cultural_stance + cultural_summary to profile.db (non-destructive)."""
        try:
            from pathlib import Path
            from aura_life.personas.profile_db import ProfileDatabase
            life_db_path = life_service._db_path
            profile_db_path = str(Path(life_db_path).parent / "profile.db")
            pdb = ProfileDatabase(profile_db_path)
            if pdb.exists():
                pdb.update_cultural_stance(
                    stance=stance_data.get("cultural_stance", []),
                    summary=stance_data.get("cultural_summary", ""),
                )
        except Exception as exc:
            logger.warning("_persist_cultural_stance failed: %s", exc)

    def _persist_to_profile_db(self, life_service, home: dict) -> None:
        """Write home_* columns to the persona's profile.db (non-destructive)."""
        try:
            from pathlib import Path
            from aura_life.personas.profile_db import ProfileDatabase
            life_db_path = life_service._db_path
            profile_db_path = str(Path(life_db_path).parent / "profile.db")
            pdb = ProfileDatabase(profile_db_path)
            if pdb.exists():
                pdb.update_home_location(
                    city=home.get("city", ""),
                    country=home.get("country", ""),
                    lat=home.get("lat"),
                    lon=home.get("lon"),
                    timezone=home.get("timezone", ""),
                )
        except Exception as exc:
            logger.warning("_persist_to_profile_db failed: %s", exc)
