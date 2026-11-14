"""Task 7 (aura humanness program): profile sections and definition fields.

Covers spec §4.1 (profile text format additions: EXAMPLE DIALOGUE, STATE
EXPRESSIONS, ENGINE SEEDS Traits/Setting/Household/Attachment
Style/Intimacy Rate, VOICE & COMMUNICATION Never Say/Allow Phrases, SOCIAL
CIRCLE "[kind]") and §4.2 (the new ``PersonalityDefinition`` fields,
``to_personality_definition()`` additionally emitting quirks/
communication_traits/avoids/relationship_style, ``from_concept`` carrying
the generator's goal into ``personal_goal``, and ``ProfileDatabase``
persisting + migrating every new field).
"""
import pathlib
import random
import sqlite3
from dataclasses import fields

import pytest

from aura_life.personas.genre_randomizer import build_genre_concept
from aura_life.personas.keys import NPC_KINDS, STATE_KEYS, TRAIT_KEYS
from aura_life.personas.personality_config import (
    PersonalityDefinition,
    get_default_languages,
)
from aura_life.personas.profile_db import ProfileDatabase, _default_languages_sql_literal
from aura_life.personas.profile_parser import ParsedProfile, ProfileParser

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "profile_full_sections.txt"
DEF_FIELDS = {f.name for f in fields(PersonalityDefinition)}

# The Task 7 fields on PersonalityDefinition (spec §4.2), excluding
# personal_goal (from_concept-only -- no profile.txt key sources it, see
# test_from_concept_carries_goal_into_personal_goal).
NEW_DEFINITION_FIELDS = [
    "example_dialogue", "state_expressions", "traits", "setting",
    "household", "attachment_style", "intimacy_rate", "never_say",
    "allow_phrases",
]
# Existing ParsedProfile fields that spec §4.2 says to_personality_definition()
# must ALSO start emitting.
NEWLY_EMITTED_OLD_FIELDS = ["quirks", "communication_traits", "avoids", "relationship_style"]


def _definition_from_dict(d: dict) -> PersonalityDefinition:
    return PersonalityDefinition(**{k: v for k, v in d.items() if k in DEF_FIELDS})


# ---------------------------------------------------------------------------
# Shared key vocabularies (spec §4.1) -- values are binding, copied verbatim.
# ---------------------------------------------------------------------------

def test_shared_key_tuples_match_the_spec_verbatim():
    assert STATE_KEYS == (
        "tired", "hungry", "lonely", "stressed", "low", "restless",
        "excited", "just_woke", "drinking", "hungover", "sick", "after_absence",
    )
    assert TRAIT_KEYS == (
        "sociability", "volatility", "rumination", "impulsivity",
        "conscientiousness", "openness", "warmth", "weather_sensitivity",
    )
    assert NPC_KINDS == (
        "friend", "family", "estranged", "threat", "colleague", "partner", "co_resident",
    )


def test_keys_are_re_exported_from_the_personas_package():
    import aura_life.personas as personas
    assert personas.STATE_KEYS is STATE_KEYS
    assert personas.TRAIT_KEYS is TRAIT_KEYS
    assert personas.NPC_KINDS is NPC_KINDS


# ---------------------------------------------------------------------------
# EXAMPLE DIALOGUE
# ---------------------------------------------------------------------------

def test_example_dialogue_blocks_and_verbatim_lines():
    profile = ProfileParser.parse_file(FIXTURE)
    assert len(profile.example_dialogue) == 3
    assert profile.example_dialogue[0] == [
        ("{{user}}", "hey. you around?"),
        ("Odessa", "On the water. Give me a minute."),
        ("{{user}}", "no rush"),
        ("Odessa", "Good, because the tide isn't taking requests."),
    ]
    assert profile.example_dialogue[1] == [
        ("{{user}}", "rough day?"),
        ("Odessa", "Engine number three again. It's held together by spite at this point."),
    ]
    # Inner punctuation (periods, apostrophes, a contraction) is untouched.
    last_line = profile.example_dialogue[2][-1]
    assert last_line == (
        "Odessa",
        "Quiet. Lights on the water where there shouldn't be any. I like it more than I say.",
    )


def test_example_dialogue_block_with_no_lines_is_dropped_and_warned():
    text = (
        "== BASIC INFO ==\n"
        "Name: Odessa\n"
        "\n"
        "== EXAMPLE DIALOGUE ==\n"
        "<START>\n"
        "{{user}}: hi\n"
        "Odessa: hey\n"
        "<START>\n"
        "<START>\n"
        "{{user}}: still there?\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.example_dialogue == [
        [("{{user}}", "hi"), ("Odessa", "hey")],
        [("{{user}}", "still there?")],
    ]
    warnings = profile.validate()
    assert any("EXAMPLE DIALOGUE" in w and "dropped" in w for w in warnings)


def test_example_dialogue_absent_section_is_empty_list():
    profile = ProfileParser.parse_text("== BASIC INFO ==\nName: X\n")
    assert profile.example_dialogue == []


# --- Fix round 1, Important #1: wrapped lines / speaker misattribution ----

def test_example_dialogue_wrapped_line_without_colon_is_appended():
    """A word-wrapped continuation line with no colon at all joins the
    previous turn instead of being dropped."""
    text = (
        "== BASIC INFO ==\nName: Odessa\n\n"
        "== EXAMPLE DIALOGUE ==\n"
        "<START>\n"
        "Odessa: On the water, give me a minute\n"
        "because the tide is not taking requests today.\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.example_dialogue == [
        [("Odessa", "On the water, give me a minute because the tide is not taking requests today.")]
    ]


def test_example_dialogue_wrapped_line_with_colon_is_appended_not_a_new_speaker():
    """A wrapped continuation line that happens to contain a colon
    ("this thing: it is cool") must NOT be read as a new speaker turn --
    it joins the previous turn, colon and all."""
    text = (
        "== BASIC INFO ==\nName: Odessa\n\n"
        "== EXAMPLE DIALOGUE ==\n"
        "<START>\n"
        "{{user}}: hey, I wanted to ask you something\n"
        "this thing: it is cool, isn't it\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.example_dialogue == [
        [("{{user}}", "hey, I wanted to ask you something this thing: it is cool, isn't it")]
    ]


def test_example_dialogue_user_marker_with_internal_spaces_normalizes():
    """"{{ user }}" (and any-case "{{User}}") normalizes to "{{user}}"."""
    text = (
        "== EXAMPLE DIALOGUE ==\n"
        "<START>\n"
        "{{ user }}: hey\n"
        "<START>\n"
        "{{User}}: hi again\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.example_dialogue == [
        [("{{user}}", "hey")],
        [("{{user}}", "hi again")],
    ]


def test_example_dialogue_case_mismatched_persona_name_is_recognized():
    """A dialogue line's speaker prefix is matched case-insensitively
    against the persona's Name, but normalized to the Name AS WRITTEN in
    BASIC INFO, not to however the dialogue line typed it."""
    text = (
        "== BASIC INFO ==\nName: Odessa\n\n"
        "== EXAMPLE DIALOGUE ==\n"
        "<START>\n"
        "ODESSA: hello there\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.example_dialogue == [[("Odessa", "hello there")]]


def test_example_dialogue_orphan_continuation_before_any_turn_warns():
    """A continuation line with no preceding turn in its block is dropped
    (not silently attached to nothing) and reported by validate()."""
    text = (
        "== EXAMPLE DIALOGUE ==\n"
        "<START>\n"
        "a stray line with no speaker yet\n"
        "{{user}}: hi\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.example_dialogue == [[("{{user}}", "hi")]]
    warnings = profile.validate()
    assert any("EXAMPLE DIALOGUE" in w and "continuation" in w and "dropped" in w for w in warnings)


# ---------------------------------------------------------------------------
# STATE EXPRESSIONS
# ---------------------------------------------------------------------------

def test_state_expressions_parsed_including_unknown_key_kept_and_warned():
    profile = ProfileParser.parse_file(FIXTURE)
    assert profile.state_expressions["tired"] == "short answers, lets the radio do the talking"
    assert profile.state_expressions["hungry"] == "gets sharper-tongued, not slower"
    assert profile.state_expressions["lonely"] == "calls someone about nothing in particular"
    # "low tide" -> key normalized like every other section ("low_tide"), not
    # in STATE_KEYS -- kept anyway, reported by validate().
    assert profile.state_expressions["low_tide"] == "extra care taken with everyone, like the world's fragile today"
    assert "low_tide" not in STATE_KEYS

    warnings = profile.validate()
    assert any("low_tide" in w for w in warnings)


# ---------------------------------------------------------------------------
# ENGINE SEEDS: Traits / Setting / Household / Attachment Style / Intimacy Rate
# ---------------------------------------------------------------------------

def test_traits_setting_household_attachment_intimacy_parsed():
    profile = ProfileParser.parse_file(FIXTURE)
    assert profile.traits == {
        "sociability": 0.35, "volatility": 0.2, "rumination": 0.5,
        "impulsivity": 0.3, "conscientiousness": 0.75, "openness": 0.6,
        "warmth": 0.55, "weather_sensitivity": 0.9,
    }
    assert set(profile.traits) <= set(TRAIT_KEYS)
    assert profile.setting == "contemporary"
    assert profile.household == ["nova"]
    assert profile.attachment_style == "avoidant"
    assert profile.intimacy_rate == 0.15


# --- Fix round 1, Minor #4: key case-folding ------------------------------

def test_state_expression_and_trait_keys_are_case_folded():
    text = (
        "== STATE EXPRESSIONS ==\n"
        "TIRED: goes quiet\n"
        "\n"
        "== ENGINE SEEDS ==\n"
        "Traits: Sociability 0.3\n"
    )
    profile = ProfileParser.parse_text(text)
    assert profile.state_expressions == {"tired": "goes quiet"}
    assert profile.traits == {"sociability": 0.3}


# --- Fix round 1, Minor #5: invalid Attachment Style is dropped + warned --

def test_invalid_attachment_style_is_dropped_and_warned():
    text = "== ENGINE SEEDS ==\nAttachment Style: chaotic\n"
    profile = ProfileParser.parse_text(text)
    assert profile.attachment_style == ""
    warnings = profile.validate()
    assert any("Attachment Style" in w and "dropped" in w for w in warnings)


@pytest.mark.parametrize("raw,expected_warn_fragment", [
    ("sociability 1.5", "sociability"),      # out of range
    ("sociability high", "sociability"),     # unparsable
])
def test_trait_value_out_of_range_or_unparsable_is_dropped_and_warned(raw, expected_warn_fragment):
    text = f"== ENGINE SEEDS ==\nTraits: {raw}, warmth 0.4\n"
    profile = ProfileParser.parse_text(text)
    assert "sociability" not in profile.traits
    assert profile.traits.get("warmth") == 0.4  # the rest of the line still parses
    warnings = profile.validate()
    assert any(expected_warn_fragment in w and "dropped" in w for w in warnings)


def test_unknown_trait_key_is_kept_and_warned():
    text = "== ENGINE SEEDS ==\nTraits: grit 0.6\n"
    profile = ProfileParser.parse_text(text)
    assert profile.traits == {"grit": 0.6}
    assert "grit" not in TRAIT_KEYS
    warnings = profile.validate()
    assert any("grit" in w for w in warnings)


@pytest.mark.parametrize("raw", ["1.5", "-0.1", "nope"])
def test_intimacy_rate_out_of_range_or_unparsable_is_dropped_and_warned(raw):
    text = f"== ENGINE SEEDS ==\nIntimacy Rate: {raw}\n"
    profile = ProfileParser.parse_text(text)
    assert profile.intimacy_rate is None
    warnings = profile.validate()
    assert any("Intimacy Rate" in w and "dropped" in w for w in warnings)


def test_intimacy_rate_omitted_is_unset():
    profile = ProfileParser.parse_text("== ENGINE SEEDS ==\nHumor Style: dry\n")
    assert profile.intimacy_rate is None


# ---------------------------------------------------------------------------
# VOICE & COMMUNICATION: Never Say / Allow Phrases
# ---------------------------------------------------------------------------

def test_never_say_and_allow_phrases_are_semicolon_separated():
    profile = ProfileParser.parse_file(FIXTURE)
    assert profile.never_say == ["I'm here for you", "How can I help", "as an AI"]
    assert profile.allow_phrases == ["damn", "hell"]


# ---------------------------------------------------------------------------
# SOCIAL CIRCLE: optional "[kind]" tag
# ---------------------------------------------------------------------------

def test_social_circle_kind_tag_parsed_with_default_and_unknown_kept():
    profile = ProfileParser.parse_file(FIXTURE)
    assert [n["name"] for n in profile.social_circle] == ["Theo", "Mireille", "Kade", "Pearl"]
    assert [n["kind"] for n in profile.social_circle] == ["colleague", "family", "threat", "friend"]


def test_social_circle_unknown_kind_is_kept_verbatim_and_warned():
    text = "== SOCIAL CIRCLE ==\n- Glitch [rival]: a friendly rival, shared interests: none\n"
    profile = ProfileParser.parse_text(text)
    assert profile.social_circle[0]["kind"] == "rival"
    assert "rival" not in NPC_KINDS
    warnings = profile.validate()
    assert any("rival" in w for w in warnings)


# ---------------------------------------------------------------------------
# to_personality_definition(): quirks / communication_traits / avoids /
# relationship_style, plus every new Task 7 field.
# ---------------------------------------------------------------------------

def test_to_personality_definition_emits_the_previously_missing_old_fields():
    profile = ProfileParser.parse_file(FIXTURE)
    d = profile.to_personality_definition()
    assert d["quirks"] == profile.behavioral_quirks and profile.behavioral_quirks
    assert d["communication_traits"] == profile.communication_traits and profile.communication_traits
    assert d["avoids"] == profile.avoids and profile.avoids
    assert d["relationship_style"] == profile.relationship_style and profile.relationship_style


def test_to_personality_definition_emits_every_new_task7_field():
    profile = ProfileParser.parse_file(FIXTURE)
    d = profile.to_personality_definition()
    definition = _definition_from_dict(d)
    for name in NEW_DEFINITION_FIELDS:
        assert getattr(definition, name) == getattr(profile, name), name


# ---------------------------------------------------------------------------
# Full round trip: parse -> definition -> ProfileDatabase -> definition.
# ---------------------------------------------------------------------------

def test_fixture_round_trips_every_new_field_through_the_database(tmp_path):
    profile = ProfileParser.parse_file(FIXTURE)
    direct = _definition_from_dict(profile.to_personality_definition())

    db = ProfileDatabase(str(tmp_path / "odessa" / "profile.db"))
    db.save_from_parsed_profile(profile, is_preset=True)
    loaded_dict = db.load()
    assert loaded_dict is not None
    via_db = _definition_from_dict(loaded_dict)

    for name in NEW_DEFINITION_FIELDS + NEWLY_EMITTED_OLD_FIELDS:
        assert getattr(direct, name) == getattr(via_db, name), name

    # Social circle's new "kind" key survives the round trip too. (Whole-dict
    # equality isn't asserted here: a DB load always includes "personality"
    # -- possibly "" -- while a direct parse only adds that key when the
    # profile line had a second comma-separated clause; that gap predates
    # Task 7 and is not this task's new field.)
    assert [n["kind"] for n in via_db.social_circle] == ["colleague", "family", "threat", "friend"]
    assert [n["kind"] for n in direct.social_circle] == [n["kind"] for n in via_db.social_circle]
    assert [n["name"] for n in direct.social_circle] == [n["name"] for n in via_db.social_circle]


def test_load_raw_includes_every_new_field(tmp_path):
    """Fix round 1, Minor #3: load_raw() (the PremadePersonaInfo path) has
    the same new-field logic as load() but had zero coverage of its own."""
    profile = ProfileParser.parse_file(FIXTURE)
    db = ProfileDatabase(str(tmp_path / "odessa_raw" / "profile.db"))
    db.save_from_parsed_profile(profile, is_preset=True)

    raw = db.load_raw()
    assert raw is not None
    assert raw["state_expressions"] == profile.state_expressions
    assert raw["traits"] == profile.traits
    assert raw["example_dialogue"] == profile.example_dialogue
    assert raw["setting"] == profile.setting
    assert raw["household"] == profile.household
    assert raw["attachment_style"] == profile.attachment_style
    assert raw["intimacy_rate"] == profile.intimacy_rate
    assert raw["never_say"] == profile.never_say
    assert raw["allow_phrases"] == profile.allow_phrases
    assert raw["personal_goal"] == ""  # ParsedProfile never sets this; from_concept-only
    assert [n["kind"] for n in raw["social_circle"]] == ["colleague", "family", "threat", "friend"]
    assert [n["name"] for n in raw["social_circle"]] == [n["name"] for n in profile.social_circle]


def test_save_from_create_request_round_trips_every_new_field(tmp_path):
    """Fix round 1, Important #2: save_from_create_request() is the aura
    host's live persona-creation path and writes every Task 7 field, but
    had no test of its own -- only save_from_parsed_profile (the .txt
    migration path) was covered."""
    request = {
        "name": "Kestrel",
        "example_dialogue": [
            [("{{user}}", "hi"), ("Kestrel", "hey, give me a second")],
            [("{{user}}", "you good?")],
        ],
        "state_expressions": {"tired": "goes quiet", "hungry": "snaps"},
        "traits": {"sociability": 0.4, "warmth": 0.6},
        "setting": "dustlands-2090",
        "household": ["nova", "roberta"],
        "attachment_style": "anxious",
        "intimacy_rate": 0.25,
        "never_say": ["as an AI"],
        "allow_phrases": ["damn"],
        "personal_goal": "get off the island",
        "social_circle": [{
            "name": "Nova", "kind": "partner",
            "relationship": "co-resident", "personality": "steady",
            "shared_interests": "the road",
        }],
    }

    db = ProfileDatabase(str(tmp_path / "kestrel" / "profile.db"))
    db.save_from_create_request(request)
    loaded = db.load()
    assert loaded is not None

    for key, expected in request.items():
        if key in ("name", "social_circle"):
            continue
        assert loaded[key] == expected, key
    assert loaded["name"] == "Kestrel"
    assert loaded["social_circle"] == request["social_circle"]


def test_profile_without_new_sections_gets_task7_defaults_and_still_parses(tmp_path):
    """A profile written before Task 7 (no EXAMPLE DIALOGUE / STATE EXPRESSIONS /
    Traits / Setting / Household / Attachment Style / Intimacy Rate / Never
    Say / Allow Phrases) must keep behaving exactly as before: every new field
    sits at its spec default, and old fields are unaffected."""
    text = (
        "== BASIC INFO ==\n"
        "Name: Plain\n"
        "Age: 30\n"
        "\n"
        "== PERSONALITY TRAITS (Server Config) ==\n"
        "Core Traits:\n"
        "- steady\n"
        "Avoids: small talk\n"
        "\n"
        "== SOCIAL CIRCLE ==\n"
        "- Sam: an old friend, shared interests: none\n"
        "\n"
        "== SYSTEM PROMPT ==\n"
        "You are Plain.\n"
    )
    profile = ProfileParser.parse_text(text)

    assert profile.example_dialogue == []
    assert profile.state_expressions == {}
    assert profile.traits == {}
    assert profile.setting == ""
    assert profile.household == []
    assert profile.attachment_style == ""
    assert profile.intimacy_rate is None
    assert profile.never_say == []
    assert profile.allow_phrases == []
    assert profile.social_circle == [{
        "name": "Sam", "kind": "friend",
        "relationship": "an old friend", "shared_interests": "none",
    }]

    d = _definition_from_dict(profile.to_personality_definition())
    for name in NEW_DEFINITION_FIELDS:
        assert getattr(d, name) in ([], {}, "", None)
    assert d.personal_goal == ""

    # Fix round 1, Minor #7: every PRE-EXISTING PersonalityDefinition field
    # (i.e. every field Task 7 did not add), each against an explicit
    # expected value -- not just name/core_traits/avoids. A regression that
    # clobbered some unrelated field while wiring in the new sections would
    # have passed the three-field spot check silently; it cannot pass this.
    expected_old_fields = {
        "id": "plain",
        "name": "Plain",
        "age_range": "30",
        "appearance": "",
        "nationality": "",
        "occupation": "",
        "voice_style": "",
        "communication_traits": [],
        "tts_profile_id": "plain",
        "core_traits": ["steady"],
        "relationship_style": "",
        "relationship_with_user": "",
        "relationship_title": "",
        "orientation": "",
        "emotional_baseline": {},
        "interests": [],
        "avoids": ["small talk"],
        "quirks": [],
        "db_path": "life.db",
        "theme_color": 0xFFBB86FC,
        "style_vibe": "",
        "tts_temperature": 0.95,
        "tts_speed_factor": 1.0,
        "tts_repetition_penalty": 1.05,
        "system_prompt": "You are Plain.",
        "appearance_details": {"age": "30"},
        "locations": {},
        "outfits": {},
        "image_sharing": "sometimes",
        "sleep_schedule": {
            "bedtime_hour": 23, "bedtime_minute": 0, "wake_hour": 7, "wake_minute": 0,
            "wake_up_chance": 0.05, "bedtime_variance": 60, "wake_variance": 45,
            "weekend_bedtime_shift": 90, "weekend_wake_shift": 90,
        },
        "social_circle": [{
            "name": "Sam", "kind": "friend",
            "relationship": "an old friend", "shared_interests": "none",
        }],
        "media_preferences": {},
        "humor_style": "",
        "taste_seeds": {},
        "comfort_zone_seeds": [],
        "backstory": "",
        "hormonal_enabled": False,
        "core_values": [],
        "struggles": [],
        "character_defects": [],
        "intrusive_thought_themes": [],
        "substance_tendencies": {},
        "behavioral_tendencies": {},
        "spending_habit": 0.5,
        "monthly_salary": 2600.0,
        "home_type": "apartment",
        "persona_type": "human",
        "home_city": "",
        "home_country": "",
        "home_lat": None,
        "home_lon": None,
        "home_timezone": "",
        "cultural_stance": [],
        "cultural_summary": "",
        "appearance_origin": "local",
        # Computed, not hardcoded to ["English", "French"]: this must be the
        # SHIPPED default regardless of whether some other test's
        # set_default_languages() call ran (and restored itself) earlier in
        # this session -- get_default_languages() is the single source of
        # truth ParsedProfile's own field default reads too.
        "languages": list(get_default_languages()),
    }
    new_task7_fields = set(NEW_DEFINITION_FIELDS) | {"personal_goal"}
    all_field_names = {f.name for f in fields(PersonalityDefinition)}
    assert set(expected_old_fields) | new_task7_fields == all_field_names, (
        "expected_old_fields is missing or has an extra PersonalityDefinition field name -- "
        f"missing={all_field_names - set(expected_old_fields) - new_task7_fields}, "
        f"extra={set(expected_old_fields) - all_field_names}"
    )
    for field_name, expected_value in expected_old_fields.items():
        assert getattr(d, field_name) == expected_value, field_name

    # And the database side keeps the same defaults through a round trip.
    db = ProfileDatabase(str(tmp_path / "plain" / "profile.db"))
    db.save_from_parsed_profile(profile, is_preset=True)
    via_db = _definition_from_dict(db.load())
    assert via_db.example_dialogue == [] and via_db.state_expressions == {} and via_db.traits == {}
    assert via_db.setting == "" and via_db.household == [] and via_db.attachment_style == ""
    assert via_db.intimacy_rate is None and via_db.never_say == [] and via_db.allow_phrases == []
    # A DB load always includes "personality" (possibly ""); see the round
    # trip test above for why that key is not asserted on the direct-parse side.
    assert via_db.social_circle == [{
        "name": "Sam", "kind": "friend", "personality": "",
        "relationship": "an old friend", "shared_interests": "none",
    }]


# ---------------------------------------------------------------------------
# from_concept(): the generator's "goal" -> personal_goal
# ---------------------------------------------------------------------------

def test_from_concept_carries_goal_into_personal_goal():
    concept = build_genre_concept("romance", rng=random.Random(5), gender="female")
    d = PersonalityDefinition.from_concept(concept)
    assert d.personal_goal == concept["goal"] and concept["goal"]


def test_from_concept_override_wins_over_concept_goal():
    concept = build_genre_concept("drama", rng=random.Random(6), gender="male")
    d = PersonalityDefinition.from_concept(concept, personal_goal="override")
    assert d.personal_goal == "override"


def test_from_concept_without_goal_key_leaves_personal_goal_default():
    d = PersonalityDefinition.from_concept({"name": "x"})
    assert d.personal_goal == ""


# ---------------------------------------------------------------------------
# ProfileDatabase migration: a pre-Task-7 database opens and gains the new
# columns/tables in place.
# ---------------------------------------------------------------------------

# Verbatim copy of the profile_core / profile_social_circle CREATE TABLE
# statements as they existed immediately before Task 7 (no setting /
# attachment_style / intimacy_rate / personal_goal columns on profile_core,
# no kind column on profile_social_circle) -- a stand-in for "a database
# created by the current [pre-Task-7] code".
_PRE_TASK7_SCHEMA = """
    CREATE TABLE profile_core (
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
        bedtime_hour INTEGER DEFAULT 23,
        bedtime_minute INTEGER DEFAULT 0,
        wake_hour INTEGER DEFAULT 7,
        wake_minute INTEGER DEFAULT 0,
        wake_up_chance REAL DEFAULT 0.05,
        bedtime_variance INTEGER DEFAULT 60,
        wake_variance INTEGER DEFAULT 45,
        weekend_bedtime_shift INTEGER DEFAULT 90,
        weekend_wake_shift INTEGER DEFAULT 90,
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
        background TEXT DEFAULT '',
        what_makes_unique TEXT DEFAULT '',
        contradictions TEXT DEFAULT '',
        secret_side TEXT DEFAULT '',
        relationship_with_user TEXT DEFAULT '',
        relationship_title TEXT DEFAULT '',
        orientation TEXT DEFAULT '',
        humor_style TEXT DEFAULT '',
        hormonal_enabled INTEGER DEFAULT 0,
        backstory TEXT DEFAULT '',
        spending_habit REAL DEFAULT 0.5,
        monthly_salary REAL DEFAULT 2600.0,
        home_type TEXT DEFAULT 'apartment',
        persona_type TEXT DEFAULT 'human',
        home_city TEXT DEFAULT '',
        home_country TEXT DEFAULT '',
        home_lat REAL,
        home_lon REAL,
        home_timezone TEXT DEFAULT '',
        cultural_stance TEXT DEFAULT '[]',
        cultural_summary TEXT DEFAULT '',
        appearance_origin TEXT DEFAULT 'local',
        languages TEXT DEFAULT __DEFAULT_LANGUAGES__,
        owner_device_id TEXT DEFAULT '',
        is_preset INTEGER DEFAULT 0,
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT ''
    );

    CREATE TABLE profile_social_circle (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        relationship TEXT DEFAULT '',
        personality TEXT DEFAULT '',
        shared_interests TEXT DEFAULT ''
    );
""".replace("__DEFAULT_LANGUAGES__", _default_languages_sql_literal())


def _make_pre_task7_db(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_PRE_TASK7_SCHEMA)
        conn.execute(
            "INSERT INTO profile_core (id, name) VALUES (1, 'Migrated')"
        )
        conn.execute(
            "INSERT INTO profile_social_circle (name, relationship, shared_interests) "
            "VALUES ('Old Friend', 'known for years', 'none')"
        )
        conn.commit()
    finally:
        conn.close()


def test_pre_task7_database_migrates_in_place(tmp_path):
    db_path = tmp_path / "legacy" / "profile.db"
    _make_pre_task7_db(db_path)

    db = ProfileDatabase(str(db_path))  # __init__ runs the migration

    conn = sqlite3.connect(str(db_path))
    try:
        core_cols = {r[1] for r in conn.execute("PRAGMA table_info(profile_core)")}
        circle_cols = {r[1] for r in conn.execute("PRAGMA table_info(profile_social_circle)")}
        table_names = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()

    assert {"setting", "attachment_style", "intimacy_rate", "personal_goal"} <= core_cols
    assert "kind" in circle_cols
    assert {"profile_state_expressions", "profile_traits", "profile_example_dialogue"} <= table_names

    # Fix round 1, Minor #6: read the RAW SQL value directly. load()'s
    # "r['kind'] or 'friend'" fallback would make this assertion pass even
    # if the ALTER TABLE's DEFAULT clause silently failed to backfill the
    # pre-existing row and left it NULL -- checking the raw column value
    # is what actually proves the migration (not load()'s safety net) did it.
    conn = sqlite3.connect(str(db_path))
    try:
        raw_kind = conn.execute("SELECT kind FROM profile_social_circle").fetchone()[0]
    finally:
        conn.close()
    assert raw_kind == "friend"

    loaded = db.load()
    assert loaded is not None
    assert loaded["name"] == "Migrated"
    assert loaded["setting"] == "" and loaded["attachment_style"] == ""
    assert loaded["intimacy_rate"] is None and loaded["personal_goal"] == ""
    assert loaded["state_expressions"] == {} and loaded["traits"] == {}
    assert loaded["example_dialogue"] == []
    assert loaded["household"] == [] and loaded["never_say"] == [] and loaded["allow_phrases"] == []
    # The pre-existing NPC row is backfilled to the documented default kind.
    assert loaded["social_circle"] == [{
        "name": "Old Friend", "relationship": "known for years",
        "personality": "", "shared_interests": "none", "kind": "friend",
    }]


def test_update_field_works_on_every_new_scalar_column(tmp_path):
    """update_field() checks the column against the live schema (PRAGMA
    table_info) before writing -- a passing call here doubles as proof the
    migration actually added the column."""
    db = ProfileDatabase(str(tmp_path / "scalar" / "profile.db"))
    db.save_from_parsed_profile(ParsedProfile(name="Scalar"))  # a row must exist for UPDATE to touch
    db.update_field("setting", "dustlands-2090")
    db.update_field("attachment_style", "anxious")
    db.update_field("intimacy_rate", 0.42)
    db.update_field("personal_goal", "get off the island")
    loaded = db.load()
    assert loaded["setting"] == "dustlands-2090"
    assert loaded["attachment_style"] == "anxious"
    assert loaded["intimacy_rate"] == 0.42
    assert loaded["personal_goal"] == "get off the island"
