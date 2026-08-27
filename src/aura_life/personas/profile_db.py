"""
Profile Database

SQLite-based persona profile storage. Each persona gets a profile.db
at data/{persona_id}/profile.db with tables for core info, lists,
emotional baseline, locations, outfits, social circle, and media.
"""

import json
import logging
import contextlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from aura_life._safe_ids import safe_join, safe_persona_id
from aura_life.personas.personality_config import get_default_languages

logger = logging.getLogger(__name__)


def _parse_json_list(raw, default):
    """Safely decode a JSON-encoded list stored in the DB.

    Returns `default` when `raw` is None/empty or malformed.
    """
    if not raw:
        return default
    if isinstance(raw, list):
        return raw  # already decoded (future-proof)
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else default
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def _default_languages_list() -> List[str]:
    """Fresh copy of the configured default language list."""
    return list(get_default_languages())


def _default_languages_sql_literal() -> str:
    """The configured default languages as a single-quoted SQL string literal.

    JSON-encoded to match the storage format of the ``languages`` column.
    """
    encoded = json.dumps(_default_languages_list(), separators=(",", ":"))
    return "'" + encoded.replace("'", "''") + "'"


class ProfileDatabase:
    """SQLite CRUD for a single persona's profile.db."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profile_core (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    age INTEGER DEFAULT 25,
                    appearance TEXT DEFAULT '',
                    nationality TEXT DEFAULT '',
                    occupation TEXT DEFAULT '',
                    theme_color TEXT DEFAULT '#BB86FC',
                    style_vibe TEXT DEFAULT '',
                    system_prompt TEXT DEFAULT '',
                    voice_style TEXT DEFAULT '',
                    tts_profile TEXT DEFAULT '',
                    tts_temperature REAL DEFAULT 0.95,
                    tts_speed REAL DEFAULT 1.0,
                    tts_repetition_penalty REAL DEFAULT 1.05,
                    relationship_style TEXT DEFAULT '',
                    image_sharing TEXT DEFAULT 'sometimes',
                    gender TEXT DEFAULT 'female',
                    -- Sleep schedule
                    bedtime_hour INTEGER DEFAULT 23,
                    bedtime_minute INTEGER DEFAULT 0,
                    wake_hour INTEGER DEFAULT 7,
                    wake_minute INTEGER DEFAULT 0,
                    wake_up_chance REAL DEFAULT 0.05,
                    bedtime_variance INTEGER DEFAULT 60,
                    wake_variance INTEGER DEFAULT 45,
                    weekend_bedtime_shift INTEGER DEFAULT 90,
                    weekend_wake_shift INTEGER DEFAULT 90,
                    -- Visual appearance
                    hair_color TEXT DEFAULT '',
                    hair_style TEXT DEFAULT '',
                    hair_length TEXT DEFAULT '',
                    eye_color TEXT DEFAULT '',
                    skin_tone TEXT DEFAULT '',
                    body_type TEXT DEFAULT '',
                    ethnicity TEXT DEFAULT '',
                    clothing_style TEXT DEFAULT '',
                    makeup TEXT DEFAULT '',
                    accessories TEXT DEFAULT '',
                    distinguishing_features TEXT DEFAULT '',
                    bust TEXT DEFAULT '',
                    art_style TEXT DEFAULT 'photorealistic',
                    room_description TEXT DEFAULT '',
                    base_prompt TEXT DEFAULT '',
                    -- Backstory
                    background TEXT DEFAULT '',
                    what_makes_unique TEXT DEFAULT '',
                    contradictions TEXT DEFAULT '',
                    secret_side TEXT DEFAULT '',
                    relationship_with_user TEXT DEFAULT '',
                    relationship_title TEXT DEFAULT '',
                    orientation TEXT DEFAULT '',
                    -- Engine seeds
                    humor_style TEXT DEFAULT '',
                    hormonal_enabled INTEGER DEFAULT 0,
                    backstory TEXT DEFAULT '',
                    spending_habit REAL DEFAULT 0.5,
                    monthly_salary REAL DEFAULT 2600.0,
                    home_type TEXT DEFAULT 'apartment',
                    persona_type TEXT DEFAULT 'human',
                    -- Place identity (T1.1)
                    home_city TEXT DEFAULT '',
                    home_country TEXT DEFAULT '',
                    home_lat REAL,
                    home_lon REAL,
                    home_timezone TEXT DEFAULT '',
                    cultural_stance TEXT DEFAULT '[]',
                    cultural_summary TEXT DEFAULT '',
                    appearance_origin TEXT DEFAULT 'local',
                    languages TEXT DEFAULT __DEFAULT_LANGUAGES__,
                    -- Multi-user isolation: device that created this persona ('' = unset)
                    owner_device_id TEXT DEFAULT '',
                    -- Metadata
                    is_preset INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS profile_lists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_type TEXT NOT NULL,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_emotional_baseline (
                    emotion TEXT PRIMARY KEY,
                    intensity REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_locations (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_outfits (
                    context TEXT PRIMARY KEY,
                    description TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_social_circle (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    relationship TEXT DEFAULT '',
                    personality TEXT DEFAULT '',
                    shared_interests TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS profile_media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL
                );
            """.replace("__DEFAULT_LANGUAGES__", _default_languages_sql_literal()))
            conn.commit()

            # Migrate existing databases: add columns that may not exist yet
            for col, col_def in [
                ("humor_style", "TEXT DEFAULT ''"),
                ("hormonal_enabled", "INTEGER DEFAULT 0"),
                ("backstory", "TEXT DEFAULT ''"),
                ("spending_habit", "REAL DEFAULT 0.5"),
                ("monthly_salary", "REAL DEFAULT 2600.0"),
                ("home_type", "TEXT DEFAULT 'apartment'"),
                ("persona_type", "TEXT DEFAULT 'human'"),
                ("bust", "TEXT DEFAULT ''"),
                ("relationship_title", "TEXT DEFAULT ''"),
                ("orientation", "TEXT DEFAULT ''"),
                # Place identity columns (T1.1)
                ("home_city", "TEXT DEFAULT ''"),
                ("home_country", "TEXT DEFAULT ''"),
                ("home_lat", "REAL"),
                ("home_lon", "REAL"),
                ("home_timezone", "TEXT DEFAULT ''"),
                ("cultural_stance", "TEXT DEFAULT '[]'"),
                ("cultural_summary", "TEXT DEFAULT ''"),
                ("appearance_origin", "TEXT DEFAULT 'local'"),
                ("languages", "TEXT DEFAULT " + _default_languages_sql_literal()),
                ("hair_length", "TEXT DEFAULT ''"),
                # Multi-user isolation (v2.27.0)
                ("owner_device_id", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE profile_core ADD COLUMN {col} {col_def}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Existence check
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        """Check if profile.db has core data."""
        if not Path(self._db_path).exists():
            return False
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) FROM profile_core").fetchone()
            return row[0] > 0
        except Exception:
            return False
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Save from ParsedProfile (migration from .txt)
    # ------------------------------------------------------------------

    def save_from_parsed_profile(self, parsed, is_preset: bool = False):
        """Migrate a ParsedProfile (from .txt parser) into the database."""
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            # Core row
            conn.execute("""
                INSERT OR REPLACE INTO profile_core (
                    id, name, description, age, appearance, nationality, occupation,
                    theme_color, style_vibe, system_prompt, voice_style,
                    tts_profile, tts_temperature, tts_speed, tts_repetition_penalty,
                    relationship_style, image_sharing, gender,
                    bedtime_hour, bedtime_minute, wake_hour, wake_minute,
                    wake_up_chance, bedtime_variance, wake_variance,
                    weekend_bedtime_shift, weekend_wake_shift,
                    hair_color, hair_style, hair_length, eye_color, skin_tone, body_type,
                    ethnicity, clothing_style, makeup, accessories,
                    distinguishing_features, art_style, room_description, base_prompt,
                    background, what_makes_unique, contradictions, secret_side,
                    relationship_with_user, relationship_title, orientation,
                    humor_style, hormonal_enabled, backstory,
                    spending_habit, monthly_salary, home_type,
                    home_city, home_country, home_lat, home_lon, home_timezone,
                    cultural_stance, cultural_summary, appearance_origin, languages,
                    is_preset, created_at, updated_at
                ) VALUES (
                    1, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?
                )
            """, (
                parsed.name, parsed.description, parsed.age,
                parsed.appearance, parsed.nationality, parsed.occupation,
                parsed.theme_color, parsed.style_vibe, parsed.system_prompt,
                parsed.voice_style,
                parsed.tts_profile, parsed.tts_temperature, parsed.tts_speed,
                parsed.tts_repetition_penalty,
                parsed.relationship_style, parsed.image_sharing,
                parsed.appearance_details.get("gender", "female"),
                parsed.bedtime_hour, parsed.bedtime_minute,
                parsed.wake_hour, parsed.wake_minute,
                parsed.wake_up_chance, parsed.bedtime_variance, parsed.wake_variance,
                parsed.weekend_bedtime_shift, parsed.weekend_wake_shift,
                parsed.appearance_details.get("hair_color", ""),
                parsed.appearance_details.get("hair_style", ""),
                parsed.appearance_details.get("hair_length", ""),
                parsed.appearance_details.get("eye_color", ""),
                parsed.appearance_details.get("skin_tone", ""),
                parsed.appearance_details.get("body_type", ""),
                parsed.appearance_details.get("ethnicity", ""),
                parsed.appearance_details.get("clothing_style", ""),
                parsed.appearance_details.get("makeup", ""),
                parsed.appearance_details.get("accessories", ""),
                parsed.appearance_details.get("distinguishing_features", ""),
                parsed.appearance_details.get("art_style", "photorealistic"),
                parsed.appearance_details.get("room_description", ""),
                parsed.appearance_details.get("base_prompt", ""),
                getattr(parsed, "background", ""),
                getattr(parsed, "what_makes_unique", ""),
                getattr(parsed, "contradictions", ""),
                getattr(parsed, "secret_side", ""),
                getattr(parsed, "relationship_with_user", ""),
                getattr(parsed, "relationship_title", ""),
                getattr(parsed, "orientation", ""),
                getattr(parsed, "humor_style", ""),
                1 if getattr(parsed, "hormonal_enabled", False) else 0,
                getattr(parsed, "background", ""),  # backstory = background
                getattr(parsed, "spending_habit", 0.5),
                getattr(parsed, "monthly_salary", 2600.0),
                getattr(parsed, "home_type", "apartment"),
                # Place identity (T1.1)
                getattr(parsed, "home_city", ""),
                getattr(parsed, "home_country", ""),
                getattr(parsed, "home_lat", None),
                getattr(parsed, "home_lon", None),
                getattr(parsed, "home_timezone", ""),
                json.dumps(getattr(parsed, "cultural_stance", [])),
                getattr(parsed, "cultural_summary", ""),
                getattr(parsed, "appearance_origin", "local"),
                json.dumps(getattr(parsed, "languages", _default_languages_list())),
                1 if is_preset else 0, now, now,
            ))
            conn.execute(
                "UPDATE profile_core SET persona_type = ? WHERE id = 1",
                (getattr(parsed, "persona_type", "human"),),
            )

            # Lists
            conn.execute("DELETE FROM profile_lists")
            for list_type, values in [
                ("core_traits", parsed.core_traits),
                ("interests", parsed.interests),
                ("avoids", parsed.avoids),
                ("quirks", parsed.behavioral_quirks),
                ("communication_traits", parsed.communication_traits),
                ("comfort_zone_seeds", getattr(parsed, "comfort_zone_seeds", [])),
                ("core_values", getattr(parsed, "core_values", [])),
                ("struggles", getattr(parsed, "struggles", [])),
                ("character_defects", getattr(parsed, "character_defects", [])),
                ("intrusive_thought_themes", getattr(parsed, "intrusive_thought_themes", [])),
            ]:
                for v in values:
                    if v.strip():
                        conn.execute(
                            "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                            (list_type, v.strip()),
                        )

            # Substance tendencies (dict → stored as "substance_tendencies:{substance}" with value = frequency)
            substance_tendencies = getattr(parsed, "substance_tendencies", {})
            for substance, frequency in substance_tendencies.items():
                conn.execute(
                    "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                    (f"substance_tendencies:{substance}", frequency),
                )

            # Behavioral tendencies (dict → stored as "behavioral_tendencies:{name}" with value = intensity)
            behavioral_tendencies = getattr(parsed, "behavioral_tendencies", {})
            for tname, tval in behavioral_tendencies.items():
                conn.execute(
                    "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                    (f"behavioral_tendencies:{tname}", str(tval)),
                )

            # Taste seeds (dict of lists → stored as "taste_seeds:{category}" list type)
            taste_seeds = getattr(parsed, "taste_seeds", {})
            for category, items in taste_seeds.items():
                for item in items:
                    if item.strip():
                        conn.execute(
                            "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                            (f"taste_seeds:{category}", item.strip()),
                        )

            # Emotional baseline
            conn.execute("DELETE FROM profile_emotional_baseline")
            for emotion, intensity in parsed.emotional_baseline.items():
                conn.execute(
                    "INSERT INTO profile_emotional_baseline (emotion, intensity) VALUES (?, ?)",
                    (emotion, intensity),
                )

            # Locations
            conn.execute("DELETE FROM profile_locations")
            for name, desc in parsed.locations.items():
                conn.execute(
                    "INSERT INTO profile_locations (name, description) VALUES (?, ?)",
                    (name, desc),
                )

            # Outfits
            conn.execute("DELETE FROM profile_outfits")
            for context, desc in parsed.outfits.items():
                conn.execute(
                    "INSERT INTO profile_outfits (context, description) VALUES (?, ?)",
                    (context, desc),
                )

            # Social circle
            conn.execute("DELETE FROM profile_social_circle")
            for npc in parsed.social_circle:
                conn.execute(
                    "INSERT INTO profile_social_circle (name, relationship, personality, shared_interests) VALUES (?, ?, ?, ?)",
                    (npc.get("name", ""), npc.get("relationship", ""),
                     npc.get("personality", ""), npc.get("shared_interests", "")),
                )

            # Media preferences
            conn.execute("DELETE FROM profile_media")
            for media_type, titles in parsed.media_preferences.items():
                for title in titles:
                    if title.strip():
                        conn.execute(
                            "INSERT INTO profile_media (media_type, title) VALUES (?, ?)",
                            (media_type, title.strip()),
                        )

            conn.commit()
            logger.info(f"Migrated profile to DB: {self._db_path}")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Save from create request (API)
    # ------------------------------------------------------------------

    def save_from_create_request(self, req) -> None:
        """Save profile from a PersonaCreateRequest (Pydantic model or dict)."""
        now = datetime.utcnow().isoformat()

        # Support both Pydantic models and plain dicts
        def _get(field, default=""):
            if isinstance(req, dict):
                return req.get(field, default)
            return getattr(req, field, default)

        # Parse bedtime/wake_time strings ("HH:MM") into hour/minute
        bedtime_str = _get("bedtime", "23:00")
        wake_str = _get("wake_time", "7:00")
        bh, bm = _parse_time_str(bedtime_str)
        wh, wm = _parse_time_str(wake_str)

        conn = self._connect()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO profile_core (
                    id, name, description, age, appearance, nationality, occupation,
                    theme_color, style_vibe, system_prompt, voice_style,
                    tts_profile, tts_temperature, tts_speed, tts_repetition_penalty,
                    relationship_style, image_sharing, gender,
                    bedtime_hour, bedtime_minute, wake_hour, wake_minute,
                    wake_up_chance, bedtime_variance, wake_variance,
                    weekend_bedtime_shift, weekend_wake_shift,
                    hair_color, hair_style, hair_length, eye_color, skin_tone, body_type,
                    ethnicity, clothing_style, makeup, accessories,
                    distinguishing_features, art_style, room_description, base_prompt,
                    humor_style, hormonal_enabled, backstory,
                    spending_habit, monthly_salary, home_type,
                    owner_device_id,
                    is_preset, created_at, updated_at
                ) VALUES (
                    1, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?,
                    ?, ?, ?
                )
            """, (
                _get("name"), _get("description"), _get("age", 25),
                _get("appearance"), _get("nationality", "American"), _get("occupation"),
                _get("theme_color", "#BB86FC"), _get("style_vibe", "casual, warm"),
                _get("system_prompt"), _get("voice_style"),
                _get("voice_profile", ""), _get("tts_temperature", 0.95),
                _get("tts_speed", 1.0), _get("tts_repetition_penalty", 1.05),
                _get("relationship_style"), _get("image_sharing", "sometimes"),
                _get("gender", "female"),
                bh, bm, wh, wm,
                _get("wake_up_chance", 0.05), _get("bedtime_variance", 60),
                _get("wake_variance", 45),
                _get("weekend_bedtime_shift", 90), _get("weekend_wake_shift", 90),
                _get("hair_color"), _get("hair_style"), _get("hair_length", ""),
                _get("eye_color"), _get("skin_tone"), _get("body_type"),
                _get("ethnicity"), _get("clothing_style"), _get("makeup"),
                _get("accessories"),
                _get("distinguishing_features"),
                _get("art_style", "photorealistic"),
                _get("room_description"), _get("base_prompt"),
                _get("humor_style", ""),
                1 if _get("hormonal_enabled", False) else 0,
                _get("backstory", ""),
                _get("spending_habit", 0.5),
                _get("monthly_salary", 2600.0),
                _get("home_type", "apartment"),
                _get("owner_device_id", ""),
                0, now, now,
            ))
            conn.execute(
                "UPDATE profile_core SET persona_type = ?, relationship_with_user = ?, relationship_title = ?, orientation = ? WHERE id = 1",
                (_get("persona_type", "human"), _get("relationship_with_user", ""), _get("relationship_title", ""), _get("orientation", "").lower()),
            )
            # Place identity fields (T1.1)
            _langs = _get("languages", _default_languages_list())
            if isinstance(_langs, str):
                _langs = [lang.strip() for lang in _langs.split(",") if lang.strip()] or _default_languages_list()
            _stance = _get("cultural_stance", [])
            conn.execute(
                """UPDATE profile_core SET
                    home_city = ?, home_country = ?, home_lat = ?, home_lon = ?,
                    home_timezone = ?, cultural_stance = ?, cultural_summary = ?,
                    appearance_origin = ?, languages = ?
                WHERE id = 1""",
                (
                    _get("home_city", ""), _get("home_country", ""),
                    _get("home_lat", None), _get("home_lon", None),
                    _get("home_timezone", ""),
                    json.dumps(_stance) if isinstance(_stance, list) else (_stance or "[]"),
                    _get("cultural_summary", ""),
                    _get("appearance_origin", "local"),
                    json.dumps(_langs),
                ),
            )

            # Lists
            conn.execute("DELETE FROM profile_lists")
            for list_type, field_name in [
                ("core_traits", "core_traits"),
                ("interests", "interests"),
                ("avoids", "avoids"),
                ("quirks", "behavioral_quirks"),
                ("communication_traits", "communication_traits"),
                ("comfort_zone_seeds", "comfort_zone_seeds"),
                ("core_values", "core_values"),
                ("struggles", "struggles"),
                ("character_defects", "character_defects"),
                ("intrusive_thought_themes", "intrusive_thought_themes"),
            ]:
                values = _get(field_name, [])
                if isinstance(values, str):
                    values = [v.strip() for v in values.split(",") if v.strip()]
                for v in values:
                    if v.strip():
                        conn.execute(
                            "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                            (list_type, v.strip()),
                        )

            # Substance tendencies (dict → stored as "substance_tendencies:{substance}")
            substance_tendencies = _get("substance_tendencies", {})
            if isinstance(substance_tendencies, dict):
                for substance, frequency in substance_tendencies.items():
                    conn.execute(
                        "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                        (f"substance_tendencies:{substance}", frequency),
                    )

            # Behavioral tendencies (dict → stored as "behavioral_tendencies:{name}")
            behavioral_tendencies = _get("behavioral_tendencies", {})
            if isinstance(behavioral_tendencies, dict):
                for tname, tval in behavioral_tendencies.items():
                    conn.execute(
                        "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                        (f"behavioral_tendencies:{tname}", str(tval)),
                    )

            # Taste seeds (dict of lists → stored as "taste_seeds:{category}" list type)
            taste_seeds = _get("taste_seeds", {})
            if isinstance(taste_seeds, dict):
                for category, items in taste_seeds.items():
                    if isinstance(items, list):
                        for item in items:
                            if item.strip():
                                conn.execute(
                                    "INSERT INTO profile_lists (list_type, value) VALUES (?, ?)",
                                    (f"taste_seeds:{category}", item.strip()),
                                )

            # Emotional baseline
            conn.execute("DELETE FROM profile_emotional_baseline")
            baseline = _get("emotional_baseline", {})
            for emotion, intensity in baseline.items():
                conn.execute(
                    "INSERT INTO profile_emotional_baseline (emotion, intensity) VALUES (?, ?)",
                    (emotion, float(intensity)),
                )

            # Locations
            conn.execute("DELETE FROM profile_locations")
            locations = _get("locations", {})
            for name, desc in locations.items():
                if desc.strip():
                    conn.execute(
                        "INSERT INTO profile_locations (name, description) VALUES (?, ?)",
                        (name, desc.strip()),
                    )

            # Outfits
            conn.execute("DELETE FROM profile_outfits")
            outfits = _get("outfits", {})
            for context, desc in outfits.items():
                if desc.strip():
                    conn.execute(
                        "INSERT INTO profile_outfits (context, description) VALUES (?, ?)",
                        (context, desc.strip()),
                    )

            # Social circle
            conn.execute("DELETE FROM profile_social_circle")
            social_circle = _get("social_circle", [])
            for npc in social_circle:
                if isinstance(npc, dict):
                    conn.execute(
                        "INSERT INTO profile_social_circle (name, relationship, personality, shared_interests) VALUES (?, ?, ?, ?)",
                        (npc.get("name", ""), npc.get("relationship", ""),
                         npc.get("personality", ""), npc.get("shared_interests", "")),
                    )

            # Media preferences
            conn.execute("DELETE FROM profile_media")
            media_prefs = _get("media_preferences", {})
            for media_type, titles in media_prefs.items():
                if isinstance(titles, list):
                    for title in titles:
                        if title.strip():
                            conn.execute(
                                "INSERT INTO profile_media (media_type, title) VALUES (?, ?)",
                                (media_type, title.strip()),
                            )

            conn.commit()
            logger.info(f"Saved profile to DB: {self._db_path}")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Load → dict compatible with PersonalityDefinition
    # ------------------------------------------------------------------

    def load(self) -> Optional[dict]:
        """Load profile from DB and return dict for PersonalityDefinition constructor."""
        if not self.exists():
            return None

        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM profile_core WHERE id = 1").fetchone()
            if not row:
                return None

            name = row["name"]
            persona_id = name.lower().replace(" ", "_")

            # Lists
            lists = {}
            taste_seeds = {}
            substance_tendencies = {}
            behavioral_tendencies = {}
            for r in conn.execute("SELECT list_type, value FROM profile_lists ORDER BY id"):
                lt = r["list_type"]
                if lt.startswith("taste_seeds:"):
                    category = lt.split(":", 1)[1]
                    taste_seeds.setdefault(category, []).append(r["value"])
                elif lt.startswith("substance_tendencies:"):
                    substance = lt.split(":", 1)[1]
                    substance_tendencies[substance] = r["value"]
                elif lt.startswith("behavioral_tendencies:"):
                    tname = lt.split(":", 1)[1]
                    try:
                        behavioral_tendencies[tname] = float(r["value"])
                    except (ValueError, TypeError):
                        pass
                else:
                    lists.setdefault(lt, []).append(r["value"])

            # Emotional baseline
            baseline = {}
            for r in conn.execute("SELECT emotion, intensity FROM profile_emotional_baseline"):
                baseline[r["emotion"]] = r["intensity"]

            # Locations
            locations = {}
            for r in conn.execute("SELECT name, description FROM profile_locations"):
                locations[r["name"]] = r["description"]

            # Outfits
            outfits = {}
            for r in conn.execute("SELECT context, description FROM profile_outfits"):
                outfits[r["context"]] = r["description"]

            # Social circle
            social_circle = []
            for r in conn.execute("SELECT name, relationship, personality, shared_interests FROM profile_social_circle"):
                social_circle.append({
                    "name": r["name"],
                    "relationship": r["relationship"],
                    "personality": r["personality"],
                    "shared_interests": r["shared_interests"],
                })

            # Media preferences
            media_prefs = {}
            for r in conn.execute("SELECT media_type, title FROM profile_media ORDER BY id"):
                media_prefs.setdefault(r["media_type"], []).append(r["title"])

            # Build appearance_details dict
            appearance_details = {}
            for field in [
                "gender", "hair_color", "hair_style", "hair_length", "eye_color", "skin_tone",
                "body_type", "ethnicity", "clothing_style", "makeup", "accessories",
                "distinguishing_features", "bust", "art_style", "room_description", "base_prompt",
            ]:
                val = row[field]
                if val:
                    appearance_details[field] = val
            # Include age in appearance_details
            appearance_details["age"] = str(row["age"])

            # Parse theme_color to ARGB int
            theme_color_int = _parse_color(row["theme_color"] or "#BB86FC")

            return {
                "id": persona_id,
                "name": name,
                "age_range": str(row["age"]),
                "appearance": row["appearance"] or "",
                "nationality": row["nationality"] or "",
                "occupation": row["occupation"] or "",
                "theme_color": theme_color_int,
                "style_vibe": row["style_vibe"] or "",
                "core_traits": lists.get("core_traits", []),
                "interests": lists.get("interests", []),
                "avoids": lists.get("avoids", []),
                "quirks": lists.get("quirks", []),
                "voice_style": row["voice_style"] or "",
                "tts_profile_id": row["tts_profile"] or persona_id,
                "tts_temperature": row["tts_temperature"] or 0.95,
                "tts_speed_factor": row["tts_speed"] or 1.0,
                "tts_repetition_penalty": row["tts_repetition_penalty"] or 1.05,
                "relationship_style": row["relationship_style"] or "",
                "relationship_with_user": (row["relationship_with_user"] if "relationship_with_user" in row.keys() else "") or "",
                "relationship_title": (row["relationship_title"] if "relationship_title" in row.keys() else "") or "",
                "orientation": (row["orientation"] if "orientation" in row.keys() else "") or "",
                "emotional_baseline": baseline,
                "system_prompt": row["system_prompt"] or "",
                "appearance_details": appearance_details,
                "locations": locations,
                "outfits": outfits,
                "image_sharing": row["image_sharing"] or "sometimes",
                "communication_traits": lists.get("communication_traits", []),
                "sleep_schedule": {
                    "bedtime_hour": row["bedtime_hour"],
                    "bedtime_minute": row["bedtime_minute"],
                    "wake_hour": row["wake_hour"],
                    "wake_minute": row["wake_minute"],
                    "wake_up_chance": row["wake_up_chance"],
                    "bedtime_variance": row["bedtime_variance"],
                    "wake_variance": row["wake_variance"],
                    "weekend_bedtime_shift": row["weekend_bedtime_shift"],
                    "weekend_wake_shift": row["weekend_wake_shift"],
                },
                "social_circle": social_circle,
                "media_preferences": media_prefs,
                # Engine seed fields
                "humor_style": row["humor_style"] or "",
                "taste_seeds": taste_seeds,
                "comfort_zone_seeds": lists.get("comfort_zone_seeds", []),
                "core_values": lists.get("core_values", []),
                "backstory": row["backstory"] or row["background"] or "",
                "hormonal_enabled": bool(row["hormonal_enabled"]),
                # New-engine seeds (Money / Job / Habitation)
                "spending_habit": row["spending_habit"] if row["spending_habit"] is not None else 0.5,
                "monthly_salary": row["monthly_salary"] if row["monthly_salary"] is not None else 2600.0,
                "home_type": row["home_type"] or "apartment",
                "persona_type": (row["persona_type"] if "persona_type" in row.keys() else None) or "human",
                # Struggle/defect/intrusive seeds
                "struggles": lists.get("struggles", []),
                "character_defects": lists.get("character_defects", []),
                "intrusive_thought_themes": lists.get("intrusive_thought_themes", []),
                "substance_tendencies": substance_tendencies,
                "behavioral_tendencies": behavioral_tendencies,
                # Place identity (T1.1)
                "home_city": (row["home_city"] if "home_city" in row.keys() else None) or "",
                "home_country": (row["home_country"] if "home_country" in row.keys() else None) or "",
                "home_lat": row["home_lat"] if "home_lat" in row.keys() else None,
                "home_lon": row["home_lon"] if "home_lon" in row.keys() else None,
                "home_timezone": (row["home_timezone"] if "home_timezone" in row.keys() else None) or "",
                "cultural_stance": _parse_json_list(
                    row["cultural_stance"] if "cultural_stance" in row.keys() else None,
                    default=[],
                ),
                "cultural_summary": (row["cultural_summary"] if "cultural_summary" in row.keys() else None) or "",
                "appearance_origin": (row["appearance_origin"] if "appearance_origin" in row.keys() else None) or "local",
                "languages": _parse_json_list(
                    row["languages"] if "languages" in row.keys() else None,
                    default=_default_languages_list(),
                ),
                # Multi-user isolation (v2.27.0)
                "owner_device_id": (row["owner_device_id"] if "owner_device_id" in row.keys() else None) or "",
                # Metadata (prefixed with _ so PersonalityDefinition ignores it)
                "_updated_at": row["updated_at"] or "",
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Load raw info for PremadePersonaInfo (API response)
    # ------------------------------------------------------------------

    def load_raw(self) -> Optional[dict]:
        """Load raw profile data for PremadePersonaInfo construction.

        Returns a dict with field names matching the DB columns plus
        list/collection fields.
        """
        if not self.exists():
            return None

        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM profile_core WHERE id = 1").fetchone()
            if not row:
                return None

            # Convert row to dict
            data = dict(row)

            # Multi-user isolation (v2.27.0) — normalize legacy NULL/missing to ""
            data["owner_device_id"] = data.get("owner_device_id") or ""

            # Lists
            data["core_traits"] = []
            data["interests"] = []
            data["avoids"] = []
            data["quirks"] = []
            data["communication_traits"] = []
            data["comfort_zone_seeds"] = []
            data["core_values"] = []
            data["struggles"] = []
            data["character_defects"] = []
            data["intrusive_thought_themes"] = []
            data["taste_seeds"] = {}
            data["substance_tendencies"] = {}
            data["behavioral_tendencies"] = {}
            for r in conn.execute("SELECT list_type, value FROM profile_lists ORDER BY id"):
                key = r["list_type"]
                if key.startswith("taste_seeds:"):
                    category = key.split(":", 1)[1]
                    data["taste_seeds"].setdefault(category, []).append(r["value"])
                elif key.startswith("substance_tendencies:"):
                    substance = key.split(":", 1)[1]
                    data["substance_tendencies"][substance] = r["value"]
                elif key.startswith("behavioral_tendencies:"):
                    tname = key.split(":", 1)[1]
                    try:
                        data["behavioral_tendencies"][tname] = float(r["value"])
                    except (ValueError, TypeError):
                        pass
                elif key in data:
                    data[key].append(r["value"])

            # Emotional baseline
            data["emotional_baseline"] = {}
            for r in conn.execute("SELECT emotion, intensity FROM profile_emotional_baseline"):
                data["emotional_baseline"][r["emotion"]] = r["intensity"]

            # Locations
            data["locations"] = {}
            for r in conn.execute("SELECT name, description FROM profile_locations"):
                data["locations"][r["name"]] = r["description"]

            # Outfits
            data["outfits"] = {}
            for r in conn.execute("SELECT context, description FROM profile_outfits"):
                data["outfits"][r["context"]] = r["description"]

            # Social circle
            data["social_circle"] = []
            for r in conn.execute("SELECT name, relationship, personality, shared_interests FROM profile_social_circle"):
                data["social_circle"].append({
                    "name": r["name"],
                    "relationship": r["relationship"],
                    "personality": r["personality"],
                    "shared_interests": r["shared_interests"],
                })

            # Media preferences
            data["media_preferences"] = {}
            for r in conn.execute("SELECT media_type, title FROM profile_media ORDER BY id"):
                data["media_preferences"].setdefault(r["media_type"], []).append(r["title"])

            return data
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Field-level updates
    # ------------------------------------------------------------------

    def update_field(self, field: str, value) -> None:
        """Update a single scalar field in profile_core.

        ``field`` is a SQL *identifier*, not a bindable parameter, so it is
        checked against the live schema before it reaches the statement --
        the same persistence-layer boundary ``update_appearance`` enforces
        with ``_LOOKS_COLUMNS`` below. Without it, a caller-supplied
        ``"name = 'x', owner_device_id"`` rewrote the multi-user isolation
        column; ``PRAGMA table_info`` reduces the accepted set to real column
        names, and the identifier is quoted regardless.

        Args:
            field: Name of an existing ``profile_core`` column.
            value: Bound as a parameter, so it is never part of the SQL text.

        Raises:
            ValueError: if ``field`` is not a string, or names no column on
                ``profile_core``. Previously a bad name raised
                ``sqlite3.OperationalError`` (or, when crafted, silently
                succeeded); it now always raises before touching the DB.
        """
        if not isinstance(field, str) or not self._column_exists(field):
            raise ValueError(
                f"update_field: {field!r} is not a profile_core column"
            )
        quoted = '"' + field.replace('"', '""') + '"'
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE profile_core SET {quoted} = ?, updated_at = ? WHERE id = 1",
                (value, datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    # Appearance ("looks") columns that update_appearance is permitted to write.
    # This is the persistence-layer security boundary — a second guard alongside
    # the parser WHITELIST so a bad caller still can't write non-appearance cols.
    _LOOKS_COLUMNS = frozenset({
        "hair_color", "hair_style", "hair_length", "eye_color", "skin_tone",
        "body_type", "ethnicity", "makeup", "accessories",
        "distinguishing_features", "bust", "base_prompt",
    })

    def update_appearance(self, changes: Dict[str, str]) -> Dict[str, str]:
        """Merge whitelisted appearance ("looks") changes into profile_core.

        Only keys in ``_LOOKS_COLUMNS`` are written; any other key is ignored
        (logged) so this method can never mutate name/age/gender/personality/etc.

        Args:
            changes: Canonical appearance field → new value (already normalized
                     by ``prompt.looks_tags.parse_looks_tags``).

        Returns:
            The subset of ``changes`` actually persisted (canonical key → value).
        """
        if not changes:
            return {}

        # Resolve which changes map to real columns. Keep distinguishing between
        # "forbidden" (not a looks field at all) and "no column yet" for clarity.
        applied: Dict[str, str] = {}
        for key, value in changes.items():
            if key not in self._LOOKS_COLUMNS:
                logger.warning("update_appearance: refusing non-appearance field %r", key)
                continue
            # Column existence check (guard against future whitelist/schema drift)
            if not self._column_exists(key):
                logger.warning(
                    "update_appearance: '%s' has no profile_core column — skipped", key
                )
                continue
            applied[key] = value

        if not applied:
            return {}

        set_clause = ", ".join(f"{col} = ?" for col in applied)
        params = list(applied.values())
        params.append(datetime.utcnow().isoformat())

        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE profile_core SET {set_clause}, updated_at = ? WHERE id = 1",
                params,
            )
            conn.commit()
            logger.info(
                "update_appearance: persisted %s → %s",
                list(applied.keys()), self._db_path,
            )
        finally:
            conn.close()
        return applied

    def update_home_location(
        self,
        city: str,
        country: str,
        lat: Optional[float],
        lon: Optional[float],
        timezone: str,
    ) -> None:
        """Persist home_* fields to profile_core without touching any other field.

        Safe to call on existing personas — only the five home columns are written.
        appearance/culture/identity columns are untouched.
        """
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE profile_core
                   SET home_city = ?, home_country = ?, home_lat = ?,
                       home_lon = ?, home_timezone = ?, updated_at = ?
                   WHERE id = 1""",
                (city, country, lat, lon, timezone, datetime.utcnow().isoformat()),
            )
            conn.commit()
            logger.info(
                "update_home_location: %s, %s → %s", city, country, self._db_path
            )
        finally:
            conn.close()

    def update_cultural_stance(self, stance: list, summary: str) -> None:
        """Persist cultural_stance + cultural_summary to profile_core (non-destructive).

        Only touches those two columns; all other profile data is untouched.
        Safe to call on existing personas — does not overwrite other fields.
        """
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE profile_core
                   SET cultural_stance = ?, cultural_summary = ?, updated_at = ?
                   WHERE id = 1""",
                (json.dumps(stance), summary, datetime.utcnow().isoformat()),
            )
            conn.commit()
            logger.info(
                "update_cultural_stance: %d facets → %s", len(stance), self._db_path
            )
        finally:
            conn.close()

    def update_appearance_origin(self, origin: str) -> None:
        """Persist appearance_origin to profile_core (non-destructive).

        Used by the T3.3 demographic-appearance generator to record whether the
        persona's look is local / adopted / immigrant / expat (and to clear the
        "pending" sentinel that flags a NEW randomized persona awaiting a roll).
        Only touches that one column.
        """
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE profile_core
                   SET appearance_origin = ?, updated_at = ?
                   WHERE id = 1""",
                (origin or "local", datetime.utcnow().isoformat()),
            )
            conn.commit()
            logger.info("update_appearance_origin: %s → %s", origin, self._db_path)
        finally:
            conn.close()

    def _column_exists(self, column: str) -> bool:
        """Return True if *column* exists on profile_core."""
        conn = self._connect()
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(profile_core)")}
            return column in cols
        finally:
            conn.close()

    def get_name(self) -> Optional[str]:
        """Quick read of the persona name without loading everything."""
        if not Path(self._db_path).exists():
            return None
        conn = self._connect()
        try:
            row = conn.execute("SELECT name FROM profile_core WHERE id = 1").fetchone()
            return row["name"] if row else None
        except Exception:
            return None
        finally:
            conn.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_time_str(time_str: str) -> tuple:
    """Parse 'HH:MM' into (hour, minute)."""
    try:
        parts = time_str.strip().split(":")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return 23, 0


def _parse_color(color_str: str) -> int:
    """Parse color string like '#FFBB86FC' or '#BB86FC' to ARGB int."""
    import re
    match = re.search(r'#([0-9A-Fa-f]{8})', color_str)
    if match:
        return int(match.group(1), 16)
    match = re.search(r'#([0-9A-Fa-f]{6})', color_str)
    if match:
        return int("FF" + match.group(1), 16)
    return 0xFFBB86FC


def get_profile_db(persona_id: str) -> ProfileDatabase:
    """Get a ProfileDatabase for a persona, using the standard data path.

    Raises:
        ValueError: if ``persona_id`` is not a well-formed id. It becomes a
            directory name here and ``ProfileDatabase.__init__`` mkdir -p's it,
            so an unchecked ``..`` segment created an attacker-chosen tree
            outside ``data_dir``. See :mod:`aura_life._safe_ids`.
    """
    from aura_life.hooks import get_config
    config = get_config()
    persona_id = safe_persona_id(persona_id)
    db_path = str(safe_join(config.data_dir, persona_id, "profile.db"))
    return ProfileDatabase(db_path)


def get_owner_device_id(persona_id: str, data_dir=None) -> str:
    """Owner device of a persona ('' = unset → owner-only for customs, N/A for presets).

    Raises:
        ValueError: if ``persona_id`` is not a well-formed id. This function
            reads the multi-user isolation key back out of whatever
            ``profile.db`` the path lands on, so an unchecked id was an
            arbitrary-read primitive against another tenant's owner token.
            ``.lower()`` normalization is kept -- it now happens inside
            :func:`~aura_life._safe_ids.safe_persona_id`, after the charset
            check passes.
    """
    persona_id = safe_persona_id(persona_id)
    if data_dir is None:
        from aura_life.hooks import get_config
        data_dir = get_config().data_dir
    db_path = safe_join(data_dir, persona_id, "profile.db")
    if not db_path.exists():
        return ""
    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT owner_device_id FROM profile_core LIMIT 1"
            ).fetchone()
            return (row[0] or "") if row else ""
    except sqlite3.OperationalError:
        return ""  # legacy DB without the column
