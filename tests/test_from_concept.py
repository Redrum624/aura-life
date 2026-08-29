"""PersonalityDefinition.from_concept — the bridge between the generator's
concept dict and LifeService(definition=...)."""
import random
from dataclasses import fields

import pytest

from aura_life.life_service import LifeService
from aura_life.personas.genre_randomizer import (
    GENDERS, GENRE_REGISTRY, build_blended_concept, build_genre_concept,
)
from aura_life.personas.personality_config import PersonalityDefinition

FIELDS = {f.name for f in fields(PersonalityDefinition)}
NON_FIELDS = {"age", "archetype", "description", "gender", "genre", "goal",
              "intensity", "style_theme", "tone_directive"}
SEEDED = ("core_traits", "core_values", "struggles", "character_defects",
          "intrusive_thought_themes", "behavioral_tendencies")


def _svc(tmp_path, definition):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return LifeService(
        db_path=str(tmp_path / "life.db"),
        persona_id="concept",
        definition=definition,
        memory_service=None,
        user_model_provider=None,
    )


@pytest.mark.parametrize("gender", GENDERS)
@pytest.mark.parametrize("genre", sorted(GENRE_REGISTRY))
def test_every_genre_and_gender_converts(genre, gender):
    concept = build_genre_concept(genre, rng=random.Random(7), gender=gender)
    d = PersonalityDefinition.from_concept(concept)
    assert isinstance(d, PersonalityDefinition)
    assert set(concept) - FIELDS == NON_FIELDS
    for k in set(concept) & FIELDS - {"theme_color"}:
        assert getattr(d, k) == concept[k], k
    for k in NON_FIELDS:
        assert not hasattr(d, k), k
    for k in SEEDED:
        assert getattr(d, k) == concept[k] and concept[k], k


def test_blended_concept_converts():
    concept = build_blended_concept(["noir", "sexy"], rng=random.Random(3))
    d = PersonalityDefinition.from_concept(concept)
    assert d.name == concept["name"] and d.core_values == concept["core_values"]


def test_overrides_apply_last_and_unknown_override_is_refused():
    concept = build_genre_concept("drama", rng=random.Random(1), gender="male")
    d = PersonalityDefinition.from_concept(concept, name="Zed", db_path="x.db", home_lat=None)
    assert d.name == "Zed" and d.db_path == "x.db" and d.home_lat is None
    assert d.occupation == concept["occupation"]
    with pytest.raises(TypeError, match="archetype"):
        PersonalityDefinition.from_concept(concept, archetype="anything")


@pytest.mark.parametrize("key,bad", [
    ("core_values", "curiosity"),            # str where List[str] belongs
    ("struggles", ("a", "b")),                # tuple is not coerced to list
    ("core_traits", ["warm", 3]),             # element of the wrong type
    ("behavioral_tendencies", [("pride", 0.4)]),
    ("behavioral_tendencies", {"pride": "high"}),
    ("substance_tendencies", "wine"),
])
def test_wrong_shape_raises_naming_the_key(key, bad):
    concept = dict(build_genre_concept("noir", rng=random.Random(5), gender="female"))
    concept[key] = bad
    with pytest.raises(TypeError, match=key):
        PersonalityDefinition.from_concept(concept)
    with pytest.raises(TypeError, match=key):
        PersonalityDefinition.from_concept({}, **{key: bad})


def test_theme_color_hex_str_becomes_the_argb_int_the_loaders_produce():
    """The generator emits '#RRGGBB'; the field is an ARGB int and both profile
    loaders parse it before the definition exists. Same parse, same int."""
    from aura_life.personas.profile_db import _parse_color

    concept = build_genre_concept("romance", rng=random.Random(2), gender="nonbinary")
    assert isinstance(concept["theme_color"], str)
    d = PersonalityDefinition.from_concept(concept)
    assert isinstance(d.theme_color, int) and d.theme_color == _parse_color(concept["theme_color"])
    assert d.theme_color == int("FF" + concept["theme_color"].lstrip("#"), 16)
    assert PersonalityDefinition.from_concept(concept, theme_color="#80112233").theme_color == 0x80112233
    assert PersonalityDefinition.from_concept(concept, theme_color=7).theme_color == 7
    with pytest.raises(TypeError, match="theme_color"):
        PersonalityDefinition.from_concept(concept, theme_color="purple")


def test_age_and_gender_are_carried_the_way_the_profile_loaders_carry_them():
    """profile_db.load_profile maps age -> age_range=str(age) and puts gender
    and age into appearance_details; place_generation reads age_range and the
    image path reads appearance_details. A concept must arrive the same way."""
    concept = build_genre_concept("scifi", rng=random.Random(4), gender="male")
    d = PersonalityDefinition.from_concept(concept)
    assert d.age_range == str(concept["age"])
    assert d.appearance_details == {"gender": "male", "age": str(concept["age"])}
    o = PersonalityDefinition.from_concept(
        concept, age_range="30s", appearance_details={"gender": "female", "hair_color": "red"}
    )
    assert o.age_range == "30s" and o.appearance_details == {"gender": "female", "hair_color": "red"}
    bare = PersonalityDefinition.from_concept({"name": "x"})
    assert bare.age_range == "" and bare.appearance_details == {}


def test_life_service_receives_the_character_only_through_from_concept(tmp_path):
    """The defect this method closes: LifeService reads its definition with
    getattr(definition, name, default) everywhere. A raw concept dict answers
    none of those reads, so every engine starts EMPTY while construction
    succeeds — no error, no log, just a blank character. from_concept() hands
    the engines a real definition; the raw dict is the negative control."""
    concept = build_genre_concept("drama", rng=random.Random(11), gender="female")
    for k in SEEDED:
        assert concept[k], f"fixture needs {k} populated"

    svc = _svc(tmp_path / "typed", PersonalityDefinition.from_concept(concept))
    assert svc._core_traits == concept["core_traits"]
    assert set(svc._identity._values) == set(concept["core_values"])
    assert svc._identity._struggles == concept["struggles"]
    assert svc._identity._character_defects == concept["character_defects"]
    assert svc._shadow._intrusive_pool == concept["intrusive_thought_themes"]
    assert svc._is_ai == (concept["persona_type"] == "ai")

    raw = _svc(tmp_path / "raw", concept)
    assert raw._core_traits == []
    assert raw._identity._values == {}
    assert raw._identity._struggles == []
    assert raw._identity._character_defects == []
    assert raw._shadow._intrusive_pool == []
