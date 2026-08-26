"""
Profile Parser

Parses text profile files into PersonalityDefinition objects.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ParsedProfile:
    """Parsed profile data from a text file."""
    # Basic Info
    name: str = ""
    description: str = ""  # Short description for persona selection UI
    age: int = 25
    appearance: str = ""
    nationality: str = ""
    occupation: str = ""
    theme_color: str = "#FFBB86FC"
    style_vibe: str = ""

    # Personality Traits
    core_traits: List[str] = field(default_factory=list)
    relationship_style: str = ""
    emotional_baseline: Dict[str, float] = field(default_factory=dict)
    interests: List[str] = field(default_factory=list)
    avoids: List[str] = field(default_factory=list)
    behavioral_quirks: List[str] = field(default_factory=list)

    # Backstory & Depth
    background: str = ""  # How they became who they are
    what_makes_unique: str = ""  # What sets them apart
    contradictions: str = ""  # Internal conflicts that make them human
    secret_side: str = ""  # What they hide or struggle with
    relationship_with_user: str = ""  # How they view the user
    relationship_title: str = ""     # Short bond label — friend, boyfriend, stepdad, etc.
    orientation: str = ""            # Sexual/romantic orientation (e.g. straight, bi, gay)

    # Voice & Communication
    voice_style: str = ""
    tts_profile: str = ""
    tts_temperature: float = 0.95
    tts_speed: float = 1.0
    tts_repetition_penalty: float = 1.05
    communication_traits: List[str] = field(default_factory=list)

    # Sleep Schedule
    bedtime_hour: int = 23
    bedtime_minute: int = 0
    wake_hour: int = 7
    wake_minute: int = 0
    wake_up_chance: float = 0.05
    bedtime_variance: int = 60
    wake_variance: int = 45
    weekend_bedtime_shift: int = 90
    weekend_wake_shift: int = 90

    # Visual Appearance (for image generation)
    appearance_details: Dict[str, str] = field(default_factory=dict)

    # Image Sharing Behavior (never, rarely, sometimes, freely)
    image_sharing: str = "sometimes"

    # Location descriptions for image generation (home, workplace, cafe, etc.)
    locations: Dict[str, str] = field(default_factory=dict)

    # Outfit descriptions per context (sleep, morning, work, workout, etc.)
    outfits: Dict[str, str] = field(default_factory=dict)

    # Social Circle (NPCs)
    social_circle: List[Dict[str, str]] = field(default_factory=list)

    # Media Preferences
    media_preferences: Dict[str, List[str]] = field(default_factory=dict)

    # System Prompt
    system_prompt: str = ""

    # Engine seed fields
    humor_style: str = ""                  # "dry", "silly", "witty", "absurdist"
    taste_seeds: Dict[str, List[str]] = field(default_factory=dict)
    comfort_zone_seeds: List[str] = field(default_factory=list)
    hormonal_enabled: bool = False
    core_values: List[str] = field(default_factory=list)  # e.g. ["curiosity", "connection", "creativity"]
    struggles: List[str] = field(default_factory=list)
    character_defects: List[str] = field(default_factory=list)
    intrusive_thought_themes: List[str] = field(default_factory=list)
    substance_tendencies: Dict[str, str] = field(default_factory=dict)
    behavioral_tendencies: Dict[str, float] = field(default_factory=dict)

    # New-engine seeds (Money / Job / Habitation)
    spending_habit: float = 0.5            # 0=frugal .. 1=spender
    monthly_salary: float = 2600.0         # net monthly income
    home_type: str = "apartment"           # apartment, house, studio, shared flat
    persona_type: str = "human"            # "human" or "ai" — gates physical-life engines

    # Place identity fields (T1.1)
    home_city: str = ""
    home_country: str = ""
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    home_timezone: str = ""                # IANA tz, e.g. "Europe/Lisbon"
    cultural_stance: List[dict] = field(default_factory=list)  # [{facet, stance, note}]
    cultural_summary: str = ""
    appearance_origin: str = "local"       # local | adopted | immigrant | expat
    languages: List[str] = field(default_factory=lambda: ["English", "French"])

    def validate(self) -> List[str]:
        """Validate the parsed profile and return a list of warnings.

        Required fields produce error-level warnings; missing optional fields
        produce info-level warnings. All warnings are also logged.
        """
        warnings = []

        # Required fields
        if not self.name:
            warnings.append("REQUIRED: 'Name' is missing")
        if not self.system_prompt:
            warnings.append("REQUIRED: 'System Prompt' section is missing or empty")

        # Important optional fields
        if not self.emotional_baseline:
            warnings.append("Missing 'Emotional Baseline' — using defaults")
        if not self.core_traits:
            warnings.append("Missing 'Core Traits' — persona may feel generic")
        if not self.voice_style:
            warnings.append("Missing 'Voice Style'")
        if not self.appearance_details:
            warnings.append("Missing 'Visual Appearance' — image generation will use defaults")

        for w in warnings:
            logger.warning(f"Profile '{self.name or '?'}': {w}")

        return warnings

    def to_personality_definition(self):
        """Convert to a dict suitable for constructing a PersonalityDefinition."""
        # Convert hex color to ARGB int
        theme_color_int = self._parse_color(self.theme_color)

        # Build appearance_details, adding age from basic info
        appearance_details = dict(self.appearance_details)
        if "age" not in appearance_details:
            appearance_details["age"] = str(self.age)

        # Log sleep schedule for debugging
        logger.debug(f"to_personality_definition for {self.name}: bedtime={self.bedtime_hour}:{self.bedtime_minute:02d}, wake={self.wake_hour}:{self.wake_minute:02d}")

        return {
            "id": self.name.lower(),
            "name": self.name,
            "age_range": str(self.age),
            "appearance": self.appearance,
            "nationality": self.nationality,
            "occupation": self.occupation,
            "theme_color": theme_color_int,
            "style_vibe": self.style_vibe,
            "core_traits": self.core_traits,
            "interests": self.interests,
            "voice_style": self.voice_style,
            "tts_profile_id": self.tts_profile or self.name.lower(),
            "tts_temperature": self.tts_temperature,
            "tts_repetition_penalty": self.tts_repetition_penalty,
            "emotional_baseline": self.emotional_baseline,
            "system_prompt": self.system_prompt,
            # Visual appearance for image generation
            "appearance_details": appearance_details,
            # Location descriptions for image generation
            "locations": dict(self.locations),
            # Outfit descriptions per context
            "outfits": dict(self.outfits),
            # Image sharing frequency
            "image_sharing": self.image_sharing,
            # Sleep schedule
            "sleep_schedule": {
                "bedtime_hour": self.bedtime_hour,
                "bedtime_minute": self.bedtime_minute,
                "wake_hour": self.wake_hour,
                "wake_minute": self.wake_minute,
                "wake_up_chance": self.wake_up_chance,
                "bedtime_variance": self.bedtime_variance,
                "wake_variance": self.wake_variance,
                "weekend_bedtime_shift": self.weekend_bedtime_shift,
                "weekend_wake_shift": self.weekend_wake_shift,
            },
            # Social circle (NPCs)
            "social_circle": list(self.social_circle),
            # Media preferences
            "media_preferences": dict(self.media_preferences),
            # Engine seed fields
            "humor_style": self.humor_style,
            "taste_seeds": dict(self.taste_seeds),
            "comfort_zone_seeds": list(self.comfort_zone_seeds),
            "backstory": self.background,  # background in ParsedProfile → backstory in PersonalityDefinition
            "hormonal_enabled": self.hormonal_enabled,
            "core_values": list(self.core_values),
            "struggles": list(self.struggles),
            "character_defects": list(self.character_defects),
            "intrusive_thought_themes": list(self.intrusive_thought_themes),
            "substance_tendencies": dict(self.substance_tendencies),
            "behavioral_tendencies": dict(self.behavioral_tendencies),
            # New-engine seeds
            "spending_habit": self.spending_habit,
            "monthly_salary": self.monthly_salary,
            "home_type": self.home_type,
            "persona_type": self.persona_type,
            "relationship_with_user": self.relationship_with_user,
            "relationship_title": self.relationship_title,
            "orientation": self.orientation,
            # Place identity fields (T1.1)
            "home_city": self.home_city,
            "home_country": self.home_country,
            "home_lat": self.home_lat,
            "home_lon": self.home_lon,
            "home_timezone": self.home_timezone,
            "cultural_stance": list(self.cultural_stance),
            "cultural_summary": self.cultural_summary,
            "appearance_origin": self.appearance_origin,
            "languages": list(self.languages),
        }

    def _parse_color(self, color_str: str) -> int:
        """Parse color string like '#FFBB86FC' to ARGB int."""
        # Extract hex from string like "Purple (#FFBB86FC)" or just "#FFBB86FC"
        match = re.search(r'#([0-9A-Fa-f]{8})', color_str)
        if match:
            return int(match.group(1), 16)
        # Try 6-digit hex
        match = re.search(r'#([0-9A-Fa-f]{6})', color_str)
        if match:
            return int("FF" + match.group(1), 16)
        return 0xFFBB86FC  # Default purple


class ProfileParser:
    """Parses text profile files."""

    SECTION_MARKERS = [
        "== BASIC INFO ==",
        "== BACKSTORY & DEPTH ==",
        "== PERSONALITY TRAITS",
        "== VOICE & COMMUNICATION ==",
        "== SLEEP SCHEDULE ==",
        "== VISUAL APPEARANCE",
        "== LOCATIONS ==",
        "== OUTFITS ==",
        "== SOCIAL CIRCLE ==",
        "== MEDIA PREFERENCES ==",
        "== ENGINE SEEDS ==",
        "== LOCATION ==",
        "== PLACE ==",
        "== SYSTEM PROMPT ==",
    ]

    @classmethod
    def parse_file(cls, file_path: Path) -> ParsedProfile:
        """Parse a profile file and return ParsedProfile."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        profile = cls.parse_text(content)
        profile.validate()
        return profile

    @classmethod
    def parse_text(cls, text: str) -> ParsedProfile:
        """Parse profile text and return ParsedProfile."""
        profile = ParsedProfile()

        # Split into sections
        sections = cls._split_sections(text)

        # Parse each section
        if "BASIC INFO" in sections:
            cls._parse_basic_info(sections["BASIC INFO"], profile)

        if "BACKSTORY & DEPTH" in sections:
            cls._parse_backstory(sections["BACKSTORY & DEPTH"], profile)

        if "PERSONALITY TRAITS" in sections:
            cls._parse_personality_traits(sections["PERSONALITY TRAITS"], profile)

        if "VOICE & COMMUNICATION" in sections:
            cls._parse_voice_communication(sections["VOICE & COMMUNICATION"], profile)

        if "SLEEP SCHEDULE" in sections:
            cls._parse_sleep_schedule(sections["SLEEP SCHEDULE"], profile)

        if "VISUAL APPEARANCE" in sections:
            cls._parse_visual_appearance(sections["VISUAL APPEARANCE"], profile)

        if "LOCATIONS" in sections:
            cls._parse_locations(sections["LOCATIONS"], profile)

        if "OUTFITS" in sections:
            cls._parse_outfits(sections["OUTFITS"], profile)

        if "SOCIAL CIRCLE" in sections:
            cls._parse_social_circle(sections["SOCIAL CIRCLE"], profile)

        if "MEDIA PREFERENCES" in sections:
            cls._parse_media_preferences(sections["MEDIA PREFERENCES"], profile)

        if "ENGINE SEEDS" in sections:
            cls._parse_engine_seeds(sections["ENGINE SEEDS"], profile)

        if "LOCATION" in sections:
            cls._parse_location_section(sections["LOCATION"], profile)

        if "SYSTEM PROMPT" in sections:
            profile.system_prompt = sections["SYSTEM PROMPT"].strip()

        return profile

    @classmethod
    def _split_sections(cls, text: str) -> Dict[str, str]:
        """Split text into sections based on == markers."""
        sections = {}
        current_section = None
        current_content = []

        for line in text.split("\n"):
            # Check for section marker
            if line.startswith("== ") and line.rstrip().endswith(" =="):
                # Save previous section
                if current_section:
                    sections[current_section] = "\n".join(current_content)

                # Extract section name
                section_name = line.strip("= ").strip()
                # Normalize section names
                if "BASIC INFO" in section_name:
                    current_section = "BASIC INFO"
                elif "BACKSTORY" in section_name or "DEPTH" in section_name:
                    current_section = "BACKSTORY & DEPTH"
                elif "PERSONALITY" in section_name:
                    current_section = "PERSONALITY TRAITS"
                elif "VOICE" in section_name or "COMMUNICATION" in section_name:
                    current_section = "VOICE & COMMUNICATION"
                elif "SLEEP" in section_name or "SCHEDULE" in section_name:
                    current_section = "SLEEP SCHEDULE"
                elif "VISUAL APPEARANCE" in section_name or "IMAGE GENERATION" in section_name:
                    current_section = "VISUAL APPEARANCE"
                elif "LOCATIONS" in section_name:
                    current_section = "LOCATIONS"
                elif "OUTFITS" in section_name:
                    current_section = "OUTFITS"
                elif "SOCIAL CIRCLE" in section_name:
                    current_section = "SOCIAL CIRCLE"
                elif "MEDIA PREFERENCES" in section_name:
                    current_section = "MEDIA PREFERENCES"
                elif "SYSTEM PROMPT" in section_name:
                    current_section = "SYSTEM PROMPT"
                elif "ENGINE SEEDS" in section_name:
                    current_section = "ENGINE SEEDS"
                elif section_name in ("LOCATION", "PLACE"):
                    current_section = "LOCATION"
                else:
                    current_section = section_name
                current_content = []
            elif current_section:
                # Skip end markers
                if not line.startswith("====="):
                    current_content.append(line)

        # Save last section
        if current_section:
            sections[current_section] = "\n".join(current_content)

        return sections

    @classmethod
    def _parse_basic_info(cls, text: str, profile: ParsedProfile):
        """Parse BASIC INFO section."""
        for line in text.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if key == "name":
                profile.name = value
            elif key == "description":
                profile.description = value
            elif key == "age":
                try:
                    profile.age = int(value)
                except ValueError:
                    pass
            elif key == "appearance":
                profile.appearance = value
            elif key == "nationality":
                profile.nationality = value
            elif key == "occupation":
                profile.occupation = value
            elif key == "spending habit":
                try:
                    profile.spending_habit = max(0.0, min(1.0, float(value)))
                except ValueError:
                    pass
            elif key == "monthly salary":
                try:
                    profile.monthly_salary = float(value.replace("$", "").replace(",", "").strip())
                except ValueError:
                    pass
            elif key == "home type":
                profile.home_type = value
            elif key == "persona type":
                profile.persona_type = "ai" if "ai" in value.lower() else "human"
            elif key == "orientation":
                profile.orientation = value.lower().strip()
            elif key == "theme color":
                profile.theme_color = value
            elif key == "style vibe":
                profile.style_vibe = value

    @classmethod
    def _parse_backstory(cls, text: str, profile: ParsedProfile):
        """Parse BACKSTORY & DEPTH section."""
        for line in text.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if not value:
                continue

            if key == "background":
                profile.background = value
            elif key == "what makes unique" or key == "what makes them unique":
                profile.what_makes_unique = value
            elif key == "contradictions":
                profile.contradictions = value
            elif key == "secret/hidden side" or key == "secret" or key == "hidden side":
                profile.secret_side = value
            elif key == "relationship w/user" or key == "relationship with user":
                profile.relationship_with_user = value
            elif key == "relationship title":
                profile.relationship_title = value

    @classmethod
    def _parse_personality_traits(cls, text: str, profile: ParsedProfile):
        """Parse PERSONALITY TRAITS section."""
        current_list = None

        for line in text.split("\n"):
            line = line.strip()

            if line.startswith("Core Traits:"):
                current_list = "core_traits"
                continue
            elif line.startswith("Relationship Style:"):
                profile.relationship_style = line.split(":", 1)[1].strip()
                current_list = None
                continue
            elif line.startswith("Emotional Baseline:"):
                current_list = "emotional_baseline"
                continue
            elif line.startswith("Interests:"):
                current_list = "interests"
                # Check if inline
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.interests = [i.strip() for i in rest.split(",")]
                    current_list = None
                continue
            elif line.startswith("Avoids:"):
                current_list = "avoids"
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.avoids = [i.strip() for i in rest.split(",")]
                    current_list = None
                continue
            elif line.startswith("Behavioral Quirks:"):
                current_list = "behavioral_quirks"
                continue
            elif line.startswith("Humor Style:"):
                profile.humor_style = line.split(":", 1)[1].strip()
                current_list = None
                continue
            elif line.startswith("Hormonal Enabled:"):
                val = line.split(":", 1)[1].strip().lower()
                profile.hormonal_enabled = val in ("yes", "true", "1")
                current_list = None
                continue
            elif line.startswith("Comfort Zone Seeds:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.comfort_zone_seeds = [i.strip() for i in rest.split(",") if i.strip()]
                current_list = None
                continue
            elif line.startswith("Taste Seeds (") or line.startswith("Taste Seeds("):
                # Format: "Taste Seeds (Music): jazz, lo-fi, ambient"
                import re as _re
                m = _re.match(r'Taste Seeds\s*\((\w+)\):\s*(.*)', line)
                if m:
                    cat = m.group(1).lower()
                    items = [i.strip() for i in m.group(2).split(",") if i.strip()]
                    if items:
                        profile.taste_seeds[cat] = items
                current_list = None
                continue

            # Parse list items
            if line.startswith("- "):
                item = line[2:].strip()
                if current_list == "core_traits":
                    # Extract just the main trait before the em dash
                    profile.core_traits.append(item)
                elif current_list == "interests":
                    profile.interests.append(item)
                elif current_list == "avoids":
                    profile.avoids.append(item)
                elif current_list == "behavioral_quirks":
                    profile.behavioral_quirks.append(item)
                elif current_list == "emotional_baseline":
                    # Parse "emotion: value" format
                    if ":" in item:
                        emotion, val = item.split(":", 1)
                        try:
                            profile.emotional_baseline[emotion.strip()] = float(val.strip())
                        except ValueError:
                            pass

    @classmethod
    def _parse_voice_communication(cls, text: str, profile: ParsedProfile):
        """Parse VOICE & COMMUNICATION section."""
        current_list = None

        for line in text.split("\n"):
            if ":" not in line and not line.strip().startswith("-"):
                continue

            line = line.strip()

            if line.startswith("Communication Traits:"):
                current_list = "communication_traits"
                continue

            if line.startswith("- "):
                if current_list == "communication_traits":
                    profile.communication_traits.append(line[2:].strip())
                continue

            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if key == "voice style":
                profile.voice_style = value
            elif key == "tts profile":
                profile.tts_profile = value
            elif key == "tts temperature":
                try:
                    profile.tts_temperature = float(value)
                except ValueError:
                    pass
            elif key == "tts speed":
                try:
                    profile.tts_speed = float(value)
                except ValueError:
                    pass
            elif key == "tts repetition penalty":
                try:
                    profile.tts_repetition_penalty = float(value)
                except ValueError:
                    pass

    @classmethod
    def _parse_sleep_schedule(cls, text: str, profile: ParsedProfile):
        """Parse SLEEP SCHEDULE section."""
        logger.debug(f"Parsing SLEEP SCHEDULE section:\n{text[:200]}")
        for line in text.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            try:
                if key == "bedtime":
                    # Parse "23:00" or "11:00 PM" format
                    time_parts = cls._parse_time(value)
                    if time_parts:
                        profile.bedtime_hour, profile.bedtime_minute = time_parts
                        logger.debug(f"Parsed bedtime: {profile.bedtime_hour}:{profile.bedtime_minute:02d}")
                elif key == "wake time":
                    time_parts = cls._parse_time(value)
                    if time_parts:
                        profile.wake_hour, profile.wake_minute = time_parts
                        logger.debug(f"Parsed wake time: {profile.wake_hour}:{profile.wake_minute:02d}")
                elif key == "wake up chance":
                    profile.wake_up_chance = float(value)
                elif key == "bedtime variance":
                    profile.bedtime_variance = int(value.split()[0])  # "60 minutes" -> 60
                elif key == "wake variance":
                    profile.wake_variance = int(value.split()[0])
                elif key == "weekend bedtime shift":
                    profile.weekend_bedtime_shift = int(value.split()[0])
                elif key == "weekend wake shift":
                    profile.weekend_wake_shift = int(value.split()[0])
            except (ValueError, IndexError):
                pass

    @classmethod
    def _parse_time(cls, time_str: str) -> Optional[Tuple[int, int]]:
        """Parse time string like '23:00', '11:00 PM', or '2:30 AM'."""
        time_str = time_str.strip().upper()

        # Try 24-hour format first (23:00)
        match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if match:
            return int(match.group(1)), int(match.group(2))

        # Try 12-hour format (11:00 PM)
        match = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)$', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            period = match.group(3)

            if period == "PM" and hour != 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0

            return hour, minute

        return None

    @classmethod
    def _parse_visual_appearance(cls, text: str, profile: ParsedProfile):
        """Parse VISUAL APPEARANCE section for image generation."""
        # Field name mappings (profile key -> appearance_details key)
        field_map = {
            "gender": "gender",
            "age": "age",
            "hair color": "hair_color",
            "hair style": "hair_style",
            "hair length": "hair_length",
            "eye color": "eye_color",
            "skin tone": "skin_tone",
            "body type": "body_type",
            "body": "body_type",
            "build": "body_type",
            "ethnicity": "ethnicity",
            "race": "ethnicity",
            "clothing style": "clothing_style",
            "clothing": "clothing_style",
            "outfit": "clothing_style",
            "default outfit": "clothing_style",
            "art style": "art_style",
            "base prompt": "base_prompt",
            "room description": "room_description",
            "room": "room_description",
            "setting": "room_description",
            "default setting": "room_description",
            "background": "room_description",
            "distinguishing features": "distinguishing_features",
            "features": "distinguishing_features",
            "unique features": "distinguishing_features",
            "makeup": "makeup",
            "accessories": "accessories",
            "jewelry": "accessories",
        }

        for line in text.split("\n"):
            if ":" not in line:
                continue

            # Split on first colon only (base_prompt may contain colons)
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if not value:
                continue

            # Handle image_sharing separately (it's a profile field, not appearance_details)
            if key == "image sharing":
                if value.lower() in ("never", "rarely", "sometimes", "freely"):
                    profile.image_sharing = value.lower()
                continue

            # Map to appearance_details key
            if key in field_map:
                profile.appearance_details[field_map[key]] = value

    @classmethod
    def _parse_locations(cls, text: str, profile: ParsedProfile):
        """Parse LOCATIONS section for persona-specific place descriptions."""
        for line in text.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()

            if not value:
                continue

            profile.locations[key] = value

    @classmethod
    def _parse_outfits(cls, text: str, profile: ParsedProfile):
        """Parse OUTFITS section for context-based clothing descriptions."""
        for line in text.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()

            if not value:
                continue

            profile.outfits[key] = value

    @classmethod
    def _parse_social_circle(cls, text: str, profile: ParsedProfile):
        """Parse SOCIAL CIRCLE section.

        Each line: "- Name: relationship, personality brief, shared interests: x, y, z"
        """
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith("- "):
                continue

            item = line[2:].strip()
            if ":" not in item:
                continue

            # Split "Name: rest"
            name_part, rest = item.split(":", 1)
            name = name_part.strip()
            rest = rest.strip()

            # Parse "relationship, personality, shared interests: x, y, z"
            npc = {"name": name}

            if "shared interests:" in rest.lower():
                main_part, interests_part = rest.lower().split("shared interests:", 1)
                # Re-extract main_part from original rest to preserve case
                split_idx = rest.lower().index("shared interests:")
                main_part = rest[:split_idx].rstrip(", ")
                interests_part = rest[split_idx + len("shared interests:"):].strip()
                npc["shared_interests"] = interests_part
            else:
                main_part = rest

            # Split main_part into relationship and personality
            parts = [p.strip() for p in main_part.split(",") if p.strip()]
            if len(parts) >= 1:
                npc["relationship"] = parts[0]
            if len(parts) >= 2:
                npc["personality"] = ", ".join(parts[1:])

            profile.social_circle.append(npc)

    @classmethod
    def _parse_media_preferences(cls, text: str, profile: ParsedProfile):
        """Parse MEDIA PREFERENCES section.

        Lines like:
        Favorite Books: title1, title2, ...
        Favorite Shows: show1, show2, ...
        Music Tastes: artist1, artist2, ...
        """
        for line in text.split("\n"):
            if ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if not value:
                continue

            items = [i.strip() for i in value.split(",") if i.strip()]

            if "book" in key:
                profile.media_preferences["books"] = items
            elif "show" in key or "tv" in key:
                profile.media_preferences["shows"] = items
            elif "music" in key or "artist" in key:
                profile.media_preferences["music"] = items
            elif "podcast" in key:
                profile.media_preferences["podcasts"] = items

    @classmethod
    def _parse_engine_seeds(cls, text: str, profile: ParsedProfile):
        """Parse ENGINE SEEDS section.

        Lines like:
        Humor Style:     dry
        Backstory:       Grew up in a small town...
        Comfort Zone Seeds: cooking, reading, yoga
        Taste Seeds (Music): jazz, lo-fi, ambient
        Taste Seeds (Food): thai, italian
        Hormonal Enabled: yes
        """
        import re as _re
        for line in text.split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue

            if line.startswith("Humor Style:"):
                profile.humor_style = line.split(":", 1)[1].strip()
            elif line.startswith("Backstory:"):
                profile.background = line.split(":", 1)[1].strip()
            elif line.startswith("Comfort Zone Seeds:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.comfort_zone_seeds = [i.strip() for i in rest.split(",") if i.strip()]
            elif line.startswith("Taste Seeds"):
                m = _re.match(r'Taste Seeds\s*\((\w+)\):\s*(.*)', line)
                if m:
                    cat = m.group(1).lower()
                    items = [i.strip() for i in m.group(2).split(",") if i.strip()]
                    if items:
                        profile.taste_seeds[cat] = items
            elif line.startswith("Core Values:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.core_values = [v.strip().lower() for v in rest.split(",") if v.strip()]
            elif line.startswith("Struggles:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.struggles = [i.strip() for i in rest.split(",") if i.strip()]
            elif line.startswith("Character Defects:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.character_defects = [i.strip() for i in rest.split(",") if i.strip()]
            elif line.startswith("Intrusive Thought Themes:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    profile.intrusive_thought_themes = [i.strip() for i in rest.split(",") if i.strip()]
            elif line.startswith("Behavioral Tendencies:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    for pair in rest.split(","):
                        pair = pair.strip()
                        if ":" in pair:
                            tname, tval = pair.split(":", 1)
                            try:
                                profile.behavioral_tendencies[tname.strip().lower()] = float(tval.strip())
                            except ValueError:
                                pass
            elif line.startswith("Substance Tendencies:"):
                rest = line.split(":", 1)[1].strip()
                if rest:
                    for pair in rest.split(","):
                        pair = pair.strip()
                        if ":" in pair:
                            subst, freq = pair.split(":", 1)
                            profile.substance_tendencies[subst.strip().lower()] = freq.strip().lower()
            elif line.startswith("Hormonal Enabled:"):
                val = line.split(":", 1)[1].strip().lower()
                profile.hormonal_enabled = val in ("yes", "true", "1")

    @classmethod
    def _parse_location_section(cls, text: str, profile: ParsedProfile):
        """Parse the == LOCATION == (or == PLACE ==) section.

        Supported keys (tolerant of absence — all optional):
            Home City, Home Country, Home Lat, Home Lon, Home Timezone,
            Cultural Summary, Cultural Stance (raw JSON), Appearance Origin,
            Languages (comma-separated)
        """
        import json as _json
        for line in text.split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue

            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()

            if not value:
                continue

            if key == "home city":
                profile.home_city = value
            elif key == "home country":
                profile.home_country = value
            elif key == "home lat":
                try:
                    profile.home_lat = float(value)
                except ValueError:
                    pass
            elif key == "home lon":
                try:
                    profile.home_lon = float(value)
                except ValueError:
                    pass
            elif key == "home timezone":
                profile.home_timezone = value
            elif key == "cultural summary":
                profile.cultural_summary = value
            elif key == "cultural stance":
                try:
                    parsed = _json.loads(value)
                    if isinstance(parsed, list):
                        profile.cultural_stance = parsed
                except (ValueError, TypeError):
                    pass
            elif key == "appearance origin":
                if value.lower() in ("local", "adopted", "immigrant", "expat"):
                    profile.appearance_origin = value.lower()
                else:
                    profile.appearance_origin = value
            elif key == "languages":
                langs = [lang.strip() for lang in value.split(",") if lang.strip()]
                if langs:
                    # Put explicitly listed languages first, add base langs (English/French) if absent
                    seen: set = set()
                    result = []
                    for lang in langs:
                        if lang not in seen:
                            result.append(lang)
                            seen.add(lang)
                    for lang in ("English", "French"):
                        if lang not in seen:
                            result.append(lang)
                    profile.languages = result
