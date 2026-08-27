"""
Personality Configuration

Defines the PersonalityDefinition dataclass and profile-based loading.
All persona data comes from profile files in profiles/presets/ or profiles/custom/.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PersonalityDefinition:
    """
    Complete definition of an AI personality.

    All fields are optional with sensible defaults so that profile-based
    definitions only need to set what the profile provides.
    """
    id: str = ""
    name: str = ""

    # Appearance & Demographics
    age_range: str = ""
    appearance: str = ""
    nationality: str = ""
    occupation: str = ""

    # Voice & Communication
    voice_style: str = ""
    communication_traits: List[str] = field(default_factory=list)
    tts_profile_id: str = ""

    # Personality Traits
    core_traits: List[str] = field(default_factory=list)
    relationship_style: str = ""           # general relational style (warm, guarded, …)
    relationship_with_user: str = ""       # the SPECIFIC bond with this user (partner, best friend, …)
    relationship_title: str = ""           # short bond label — friend, boyfriend, stepdad, etc.
    orientation: str = ""                  # sexual/romantic orientation (e.g. straight, bi, gay)
    emotional_baseline: Dict[str, float] = field(default_factory=dict)

    # Topics
    interests: List[str] = field(default_factory=list)
    avoids: List[str] = field(default_factory=list)

    # Quirks & Behaviors
    quirks: List[str] = field(default_factory=list)

    # Technical
    db_path: str = "life.db"
    theme_color: int = 0xFFBB86FC  # ARGB hex color

    # Style
    style_vibe: str = ""

    # TTS voice differentiation params
    tts_temperature: float = 0.9
    tts_speed_factor: float = 1.0
    tts_repetition_penalty: float = 1.05

    # Profile-based fields (from ParsedProfile.to_personality_definition)
    system_prompt: str = ""
    appearance_details: Dict[str, str] = field(default_factory=dict)
    locations: Dict[str, str] = field(default_factory=dict)
    outfits: Dict[str, str] = field(default_factory=dict)
    image_sharing: str = "sometimes"
    sleep_schedule: Optional[Dict] = None
    social_circle: List[Dict[str, str]] = field(default_factory=list)
    media_preferences: Dict[str, List[str]] = field(default_factory=dict)

    # Engine seed fields (Phase 15.8 expansion)
    humor_style: str = ""                  # "dry", "silly", "witty", "absurdist"
    taste_seeds: Dict[str, List[str]] = field(default_factory=dict)  # {"music": ["jazz", "lo-fi"], "food": ["thai"]}
    comfort_zone_seeds: List[str] = field(default_factory=list)  # Activities that start familiar
    backstory: str = ""                    # Rich backstory (from profile or LLM-generated)
    hormonal_enabled: bool = False         # Enable hormonal cycle for this persona
    core_values: List[str] = field(default_factory=list)  # e.g. ["curiosity", "connection", "creativity"]
    struggles: List[str] = field(default_factory=list)
    character_defects: List[str] = field(default_factory=list)
    intrusive_thought_themes: List[str] = field(default_factory=list)
    substance_tendencies: Dict[str, str] = field(default_factory=dict)
    behavioral_tendencies: Dict[str, float] = field(default_factory=dict)

    # New-engine seeds (Money / Job / Habitation)
    spending_habit: float = 0.5            # 0=frugal .. 1=spender
    monthly_salary: float = 2600.0         # net monthly income → Money + Job
    home_type: str = "apartment"           # apartment, house, studio, shared flat
    persona_type: str = "human"            # "human" or "ai" — gates physical-life engines

    # Place identity fields (T1.1)
    home_city: str = ""
    home_country: str = ""
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    home_timezone: str = ""                # IANA tz, e.g. "Europe/Paris"
    cultural_stance: List[dict] = field(default_factory=list)
    cultural_summary: str = ""
    appearance_origin: str = "local"       # local | adopted | immigrant | expat
    languages: List[str] = field(default_factory=lambda: list(get_default_languages()))


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

# The language pair every persona is assumed to speak unless a profile says
# otherwise. This is a configurable library default, not a property of the
# engine: a host that serves another locale calls `set_default_languages()`
# once at startup and every downstream default follows.
_DEFAULT_LANGUAGES: Tuple[str, ...] = ("English", "French")


def get_default_languages() -> Tuple[str, ...]:
    """Return the configured default language list (ordered, first = primary)."""
    return _DEFAULT_LANGUAGES


def set_default_languages(*languages: str) -> None:
    """Override the library's default language list.

    Call once at host startup, before personas are built. Raises ValueError if
    no language is given — an empty default would silently strip languages from
    every persona.
    """
    global _DEFAULT_LANGUAGES
    flat: List[str] = []
    for lang in languages:
        if isinstance(lang, (list, tuple)):
            flat.extend(str(x) for x in lang if str(x).strip())
        elif str(lang).strip():
            flat.append(str(lang).strip())
    if not flat:
        raise ValueError("set_default_languages() needs at least one language")
    seen: set = set()
    _DEFAULT_LANGUAGES = tuple(x for x in flat if not (x in seen or seen.add(x)))


# Countries / territories where French is the primary spoken language.
# Matched case-insensitively against the persona's home_country field.
_FRENCH_PRIMARY_COUNTRIES: frozenset = frozenset({
    # Metropolitan France + micro-states
    "france", "monaco", "luxembourg", "andorra",
    # Caribbean
    "haiti", "guadeloupe", "martinique", "french guiana",
    "saint barthélemy", "saint barthelemy", "saint martin",
    # Sub-Saharan Africa — Francophone
    "senegal", "sénégal",
    "côte d'ivoire", "cote d'ivoire", "ivory coast",
    "mali", "burkina faso", "guinea", "guinée", "guinee",
    "guinea-bissau",
    "niger", "benin", "bénin",
    "togo", "cameroon", "cameroun",
    "republic of the congo", "congo-brazzaville", "congo",
    "democratic republic of the congo", "drc",
    "gabon", "central african republic",
    "chad", "tchad", "djibouti", "mauritania", "mauritanie",
    "comoros", "mayotte", "reunion", "réunion",
    # Indian Ocean
    "seychelles",
    # Pacific
    "new caledonia", "french polynesia",
    # North Africa
    "morocco", "maroc", "algeria", "algérie", "algerie", "tunisia", "tunisie",
})

# Sub-national substrings (case-insensitive) that indicate a French-primary region.
# Checked if the full home_country string was not found in _FRENCH_PRIMARY_COUNTRIES.
_FRENCH_PRIMARY_SUBSTRINGS: tuple = (
    "québec", "quebec",
    "wallonia", "wallonie",
    "francophone",
)


def ensure_bilingual(langs: List[str]) -> List[str]:
    """Return a deduplicated language list that always includes the defaults.

    Rules:
    - The configured default languages come first, in configured order
      (`get_default_languages()`; ships as English then French).
    - Any additional languages authored in the profile are preserved, appended
      after the default block.
    - No duplicates.
    """
    seen: set = set()
    result: List[str] = []

    # Configured defaults first, in order
    for lang in get_default_languages():
        if lang not in seen:
            result.append(lang)
            seen.add(lang)

    # Preserve any additional authored languages, deduped
    for lang in langs:
        if lang not in seen:
            result.append(lang)
            seen.add(lang)

    return result


def native_language_for(home_country: Optional[str], languages: List[str]) -> str:
    """Derive the persona's native (mother-tongue) language.

    Rules (applied in order):
    1. If ``languages`` has a first entry that is not one of the configured
       default languages, treat it as native (the author explicitly signalled it).
    2. Otherwise, check ``home_country`` against the French-primary set /
       substrings. If matched and French is a default language → "French".
    3. Default → the first configured default language (ships as "English").

    AI personas have no physical home (``home_country`` is empty) so they fall
    through to rule 3.
    """
    defaults = get_default_languages()

    # Rule 1: explicitly authored native language outside the defaults
    if languages and languages[0] not in defaults:
        return languages[0]

    # Rule 2: home-country heuristic (only meaningful if French is a default)
    if "French" in defaults:
        country = (home_country or "").strip().lower()
        if country and country in _FRENCH_PRIMARY_COUNTRIES:
            return "French"
        for fragment in _FRENCH_PRIMARY_SUBSTRINGS:
            if fragment in country:
                return "French"

    # Rule 3: default
    return defaults[0]


# ---------------------------------------------------------------------------
# Age speech-register helper
# ---------------------------------------------------------------------------

def age_speech_register(age) -> str:
    """Return a concise speech-register lean for the given age.

    Each lean ends with "while staying true to who she is" — framing the
    register as a TENDENCY, not a directive.  Personality always dominates.

    Returns "" for unknown / unset ages (None, 0, negative, non-integer).
    """
    if age is None or not isinstance(age, int) or age <= 0:
        return ""
    if age <= 24:
        return (
            "lean toward a casual, current register — comfortable with contemporary "
            "slang, abbreviations, and emoji used naturally; often shorter, punchier "
            "messages — while staying true to who she is"
        )
    if age <= 34:
        return (
            "lean toward a relaxed, conversational register — some slang, fuller "
            "thoughts, settled voice — while staying true to who she is"
        )
    if age <= 49:
        return (
            "lean toward a measured register — fewer trendy abbreviations, references "
            "from her own formative era — while staying true to who she is"
        )
    if age <= 64:
        return (
            "lean toward fuller, complete sentences — sparing with current slang, "
            "era-appropriate references — while staying true to who she is"
        )
    return (
        "lean toward considered, traditional phrasing — warmth over trendiness — "
        "while staying true to who she is"
    )


def get_personality(personality_id: str) -> Optional[PersonalityDefinition]:
    """Get a personality by ID string.

    Load order:
    1. data/{persona_id}/profile.db — if it exists and has data
    2. .txt profile file — parse it, migrate to .db, then load from .db
    3. Return None if neither found
    """
    from dataclasses import fields as dc_fields
    from pathlib import Path
    from aura_life.hooks import get_config
    from .profile_db import ProfileDatabase

    config = get_config()
    pid = personality_id.lower()
    db_path = str(config.data_dir / pid / "profile.db")
    profile_db = ProfileDatabase(db_path)

    # Valid field names for PersonalityDefinition — use dataclass introspection
    # so that fields with default_factory (appearance_details, locations, etc.)
    # are included (hasattr() misses them since they have no class-level attribute)
    _valid_fields = {f.name for f in dc_fields(PersonalityDefinition)}

    # 1. Try loading from profile.db
    if profile_db.exists():
        try:
            profile_dict = profile_db.load()
            if profile_dict:
                # Check if preset .txt is newer than profile.db (triggers re-migration)
                txt_path = (config.text_profiles_dir / f"{pid}_profile.txt")
                if txt_path.exists():
                    import os
                    from datetime import datetime
                    txt_mtime = datetime.utcfromtimestamp(os.path.getmtime(str(txt_path)))
                    db_updated = profile_dict.get("_updated_at", "")
                    if db_updated:
                        try:
                            db_time = datetime.fromisoformat(db_updated)
                            if txt_mtime > db_time:
                                from .profile_parser import ProfileParser
                                parsed = ProfileParser.parse_file(txt_path)
                                profile_db.save_from_parsed_profile(parsed, is_preset=True)
                                logger.info(f"Re-migrated {txt_path.name} → profile.db (txt newer than db)")
                                profile_dict = profile_db.load()
                        except (ValueError, TypeError):
                            pass  # Invalid timestamp format, skip re-migration

                definition = PersonalityDefinition(**{
                    k: v for k, v in profile_dict.items()
                    if k in _valid_fields
                })
                definition.db_path = "life.db"
                return definition
        except Exception as e:
            logger.warning(f"Failed to load profile.db for {pid}: {e}")

    # 2. Fallback to .txt — parse, migrate to .db, then load from .db
    profile_paths = [
        config.custom_profiles_dir / f"{pid}_profile.txt",
        config.text_profiles_dir / f"{pid}_profile.txt",
    ]

    for profile_path in profile_paths:
        if profile_path.exists():
            try:
                from .profile_parser import ProfileParser
                parsed = ProfileParser.parse_file(profile_path)

                # Migrate to .db
                is_preset = profile_path.parent == config.text_profiles_dir
                profile_db.save_from_parsed_profile(parsed, is_preset=is_preset)
                logger.info(f"Migrated {profile_path.name} → profile.db for {pid}")

                # Load from .db (ensures round-trip consistency)
                profile_dict = profile_db.load()
                if profile_dict:
                    definition = PersonalityDefinition(**{
                        k: v for k, v in profile_dict.items()
                        if k in _valid_fields
                    })
                    definition.db_path = "life.db"
                    return definition
            except Exception as e:
                logger.warning(f"Failed to parse/migrate profile {profile_path}: {e}")

    return None
