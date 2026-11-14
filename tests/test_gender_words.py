"""The word a profile writes for her gender reaches her pronouns.

A profile says ``Gender: woman`` (aura's persona wizard writes that word by
default, and the profiles shipped with aura and aura-personality carry it),
while `GENDERS` names the same thing "female". Before this test existed
`resolve_gender` knew only the three `GENDERS` words, so every such persona
was rendered as they/them.
"""
import pytest

from aura_life.personas.personality_config import PersonalityDefinition
from aura_life.personas.pronoun_render import render_line, resolve_gender


@pytest.mark.parametrize("word, expected", [
    ("woman", "female"), ("Woman", "female"), (" girl ", "female"), ("f", "female"), ("female", "female"),
    ("man", "male"), ("boy", "male"), ("M", "male"), ("male", "male"),
    ("nonbinary", "nonbinary"),
])
def test_the_word_a_profile_writes_resolves_to_her_gender(word, expected):
    assert resolve_gender(word) == expected


@pytest.mark.parametrize("word", ["", None, "none", "robot", "womanly", "human"])
def test_an_unknown_word_is_never_guessed(word):
    assert resolve_gender(word) == "nonbinary"


def test_a_woman_is_rendered_as_she_and_a_man_as_he():
    assert render_line("{Subj} lit {poss} first cigarette", gender="woman") == "She lit her first cigarette"
    assert render_line("{Subj} cleaned {poss} gun", gender="man") == "He cleaned his gun"
    assert render_line("{Subj} {was} out all night", gender="woman") == "She was out all night"


def test_a_life_service_renders_a_profile_s_woman_as_she(tmp_path):
    from aura_life.life_service import LifeService

    definition = PersonalityDefinition(id="w", name="W", appearance_details={"gender": "woman"})
    svc = LifeService(db_path=str(tmp_path / "life.db"), persona_id="w", definition=definition)
    assert svc._render_text("{Subj} kept {poss} word") == "She kept her word"
