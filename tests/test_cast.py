"""build_cast / register_genre / unregister_genre.

A cast is n personas that can share a settlement: distinct names, genders
dealt evenly unless told otherwise, every member built by the same builder
build_genre_concept uses (the name is pre-assigned through the builder's
`name=` hook, never patched into the dict — no prose field embeds the name,
and the test below keeps it that way). Same seed, same cast.
"""
import dataclasses
import random
from collections import Counter

import pytest

from aura_life.personas.genre_randomizer import (
    GENDERS,
    GENRE_REGISTRY,
    GenreSpec,
    build_cast,
    build_genre_concept,
    register_genre,
    unregister_genre,
)

GENRES = sorted(GENRE_REGISTRY)


def _pool(genre, gender):
    return set(GENRE_REGISTRY[genre].name_pools[gender])


@pytest.mark.parametrize("genre", GENRES)
def test_cast_of_twelve_has_distinct_names_and_the_single_persona_shape(genre):
    cast = build_cast(genre, 12, random.Random(1))
    assert len(cast) == 12
    names = [m["name"] for m in cast]
    assert len(set(names)) == 12, names
    shape = set(build_genre_concept(genre, random.Random(0)))
    for m in cast:
        assert set(m) == shape
        assert m["name"] in _pool(genre, m["gender"])
        assert m["genre"] == genre


@pytest.mark.parametrize("genre", GENRES)
def test_balanced_cast_of_twelve_is_4_4_4(genre):
    counts = Counter(m["gender"] for m in build_cast(genre, 12, random.Random(3)))
    assert counts == {g: 4 for g in GENDERS}


def test_balanced_remainder_goes_to_rng_picked_genders():
    counts = Counter(m["gender"] for m in build_cast("romance", 13, random.Random(3)))
    assert sorted(counts.values()) == [4, 4, 5]
    counts = Counter(m["gender"] for m in build_cast("romance", 2, random.Random(3)))
    assert sorted(counts.values()) == [1, 1]
    assert build_cast("romance", 0, random.Random(3)) == []


def test_balanced_order_is_shuffled_not_grouped():
    seqs = {tuple(m["gender"] for m in build_cast("drama", 12, random.Random(s))) for s in range(6)}
    grouped = tuple(g for g in GENDERS for _ in range(4))
    assert any(seq != grouped for seq in seqs)
    assert len(seqs) > 1


def test_explicit_gender_gives_all_that_gender():
    for g in GENDERS:
        cast = build_cast("noir", 12, random.Random(9), gender=g)
        assert {m["gender"] for m in cast} == {g}
        names = [m["name"] for m in cast]
        assert len(set(names)) == 12 and set(names) <= _pool("noir", g)
    with pytest.raises(ValueError):
        build_cast("noir", 3, random.Random(9), gender="other")


def test_balance_false_draws_each_gender_independently_like_build_genre_concept():
    rng = random.Random(5)
    expected = [rng.choice(GENDERS) for _ in range(12)]
    got = [m["gender"] for m in build_cast("scifi", 12, random.Random(5), balance=False)]
    assert got == expected
    assert len({m["name"] for m in build_cast("scifi", 12, random.Random(5), balance=False)}) == 12


def test_n_over_the_pool_raises_naming_genre_gender_and_both_counts():
    # romance has 14 female names
    with pytest.raises(ValueError) as e:
        build_cast("romance", 15, random.Random(0), gender="female")
    msg = str(e.value)
    assert "'romance'" in msg and "female" in msg and "14" in msg and "15" in msg
    # horror has 12 per pool: 37 balanced needs 13 of one gender
    with pytest.raises(ValueError) as e:
        build_cast("horror", 37, random.Random(0))
    msg = str(e.value)
    assert "'horror'" in msg and "12" in msg and "13" in msg
    # 36 balanced (12/12/12) is exactly the pools
    assert len(build_cast("horror", 36, random.Random(0))) == 36
    with pytest.raises(KeyError):
        build_cast("western", 3, random.Random(0))


def test_same_seed_same_cast_byte_for_byte():
    for genre in GENRES:
        assert build_cast(genre, 12, random.Random(77)) == build_cast(genre, 12, random.Random(77))
        assert build_cast(genre, 12, random.Random(77)) != build_cast(genre, 12, random.Random(78))


@pytest.mark.parametrize("genre", GENRES)
def test_no_prose_field_embeds_the_name(genre):
    """The name is injected through the builder hook, so if any prose ever
    starts embedding it, this is where the pre-assignment would go stale."""
    for m in build_cast(genre, 12, random.Random(11)):
        for key in ("description", "appearance", "relationship_with_user", "tone_directive", "goal"):
            assert m["name"] not in m[key], (key, m["name"], m[key])


def test_build_genre_concept_still_draws_its_own_name():
    """The hook defaults to the builder's own rng.choice: a single persona
    consumes the same draws as before (the golden fixture pins the values)."""
    a = build_genre_concept("romance", random.Random(99))
    b = build_genre_concept("romance", random.Random(99))
    assert a == b and a["name"] in _pool("romance", a["gender"])


# ---------------------------------------------------------------------------
# register_genre / unregister_genre
# ---------------------------------------------------------------------------

def _custom(key="western", **over):
    base = GENRE_REGISTRY["drama"]
    fields = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    fields.update(key=key, display_label=key.title(), builder=None, intensity_ladder=None)
    fields.update(over)
    return GenreSpec(**fields)


def test_register_unregister_round_trip_and_duplicate_refusal():
    assert "western" not in GENRE_REGISTRY
    assert unregister_genre("western") is False
    try:
        register_genre(_custom())
        assert GENRE_REGISTRY["western"].key == "western"
        with pytest.raises(ValueError, match="already registered.*replace=True"):
            register_genre(_custom())
        assert GENRE_REGISTRY["western"].display_label == "Western"
        register_genre(_custom(display_label="Spaghetti Western"), replace=True)
        assert GENRE_REGISTRY["western"].display_label == "Spaghetti Western"
    finally:
        assert unregister_genre("western") is True
    assert "western" not in GENRE_REGISTRY
    assert unregister_genre("western") is False


def test_shipped_genre_is_never_silently_overwritten():
    with pytest.raises(ValueError, match="'romance' is already registered"):
        register_genre(_custom(key="romance"))
    assert GENRE_REGISTRY["romance"].display_label == "Romance"


def test_register_rejects_non_spec():
    with pytest.raises(TypeError):
        register_genre({"key": "western"})


@pytest.mark.parametrize("over, needle", [
    ({"ai_archetypes": []}, "ai_archetypes"),
    ({"human_archetypes": []}, "human_archetypes"),
    ({"human_archetypes": [("a", "b", "c")]}, "5-tuple"),
    ({"name_pools": {}, "name_pool": []}, "name_pools['female']"),
    ({"name_pools": {"female": ["Ada"]}, "name_pool": []}, None),   # male/nonbinary fall back
    ({"appearance_template": ""}, "appearance_template"),
    ({"shadow_level": "bogus"}, "shadow_level"),
    ({"shadow": None}, "shadow must be a ShadowSeedSpec"),
    ({"goal_pool": []}, "goal_pool"),
    ({"style_theme_pool": []}, "style_theme_pool"),
    ({"theme_colors": []}, "theme_colors"),
])
def test_register_validates_what_the_builder_needs(over, needle):
    spec = _custom(**over)
    try:
        if needle is None:
            register_genre(spec)
            assert build_genre_concept("western", random.Random(1))["name"] == "Ada"
            return
        with pytest.raises(ValueError, match="not buildable") as e:
            register_genre(spec)
        assert needle in str(e.value)
        assert "western" not in GENRE_REGISTRY
    finally:
        unregister_genre("western")


def test_registered_spec_is_copied_so_no_shipped_genre_can_be_corrupted_through_it():
    """dataclasses.replace(GENRE_REGISTRY['romance'], key=...) shares every
    list and the ShadowSeedSpec with romance. Registering must sever that."""
    romance = GENRE_REGISTRY["romance"]
    spec = dataclasses.replace(romance, key="western")
    assert spec.shadow is romance.shadow and spec.human_archetypes is romance.human_archetypes
    struggles, rows = list(romance.shadow.struggles), list(romance.human_archetypes)
    try:
        register_genre(spec)
        reg = GENRE_REGISTRY["western"]
        assert reg is not spec and reg.shadow is not romance.shadow
        reg.shadow.struggles.append("CORRUPT")
        reg.human_archetypes.append(("x", "y", "z", [], "w"))
        assert "CORRUPT" not in romance.shadow.struggles and romance.human_archetypes == rows
        spec.shadow.struggles.append("CALLER")      # the caller's object, post-registration
        assert "CALLER" not in reg.shadow.struggles
    finally:
        unregister_genre("western")
        romance.shadow.struggles[:] = struggles


def test_registered_custom_genre_builds_a_cast():
    try:
        register_genre(_custom())
        cast = build_cast("western", 12, random.Random(2))
        assert len({m["name"] for m in cast}) == 12
        assert Counter(m["gender"] for m in cast) == {g: 4 for g in GENDERS}
        assert {m["genre"] for m in cast} == {"western"}
        assert set(cast[0]) == set(build_genre_concept("western", random.Random(0)))
    finally:
        unregister_genre("western")


def test_custom_builder_receives_the_preassigned_name():
    calls = []

    def builder(spec, rng, gender, name=None):
        calls.append(name)
        return {"name": name or rng.choice(spec.name_pools[gender]), "gender": gender}

    try:
        register_genre(_custom(builder=builder))
        single = build_genre_concept("western", random.Random(1))
        assert calls == [None] and single["name"] in _pool("western", single["gender"])
        cast = build_cast("western", 6, random.Random(1))
        assert None not in calls[1:] and [m["name"] for m in cast] == calls[1:]
        assert len(set(calls[1:])) == 6
    finally:
        unregister_genre("western")


def test_legacy_three_arg_builder_still_works_for_single_personas():
    def builder(spec, rng, gender):
        return {"name": rng.choice(spec.name_pools[gender]), "gender": gender}

    try:
        register_genre(_custom(builder=builder))
        assert build_genre_concept("western", random.Random(1))["gender"] in GENDERS
        with pytest.raises(TypeError):
            build_cast("western", 3, random.Random(1))
    finally:
        unregister_genre("western")
