"""The gender contract, pinned as tests instead of asserted in a CHANGELOG.

Three things a prose claim cannot carry:

* **Back-compat.** Every call form that existed at v0.2.0 still binds, and still
  returns the same 26-key concept dict. `GenreSpec.name_pool` still reads as the
  female pool and the flat `name_pool=[...]` constructor keyword still builds.
* **The one deliberate BEHAVIOUR change.** `concept["gender"]` used to be the
  literal `"female"` for every genre and every seed; it is now drawn uniformly
  from `GENDERS`. `test_default_gender_is_drawn_not_hardcoded_female` exists to
  fail if anyone ever "restores" the old default by accident -- and to make the
  break visible to a reader of the test suite, not only to a reader of the diff.
* **Determinism.** The gender is the FIRST draw off the supplied rng, it costs
  exactly ONE draw, and the same seed replays byte-identically in a fresh
  interpreter. Downstream consumers (Hollow) pass a shared world rng and replay
  runs off the seed, so both the position and the cost of that draw are contract.
"""
import json
import pathlib
import random
import subprocess
import sys

import pytest

from aura_life.personas import genre_randomizer as gr
from aura_life.personas.genre_randomizer import (
    GENDERS,
    GENRE_REGISTRY,
    PRONOUNS,
    GenreSpec,
    build_blended_concept,
    build_genre_concept,
    render,
)

GENRES = sorted(GENRE_REGISTRY)

#: The concept dict's keys, written out rather than sampled. This is the shape
#: v0.2.0 returned, verified against `git show v0.2.0:...` over 200 seeds x 7
#: genres. De-gendering added no key and removed none -- "gender" was already
#: here, it just always held "female".
CONCEPT_KEYS = frozenset({
    "age", "appearance", "archetype", "behavioral_tendencies", "character_defects",
    "core_traits", "core_values", "description", "gender", "genre", "goal",
    "intensity", "interests", "intrusive_thought_themes", "name", "occupation",
    "persona_type", "relationship_style", "relationship_title",
    "relationship_with_user", "struggles", "style_theme", "substance_tendencies",
    "theme_color", "tone_directive", "voice_style",
})

PRONOUN_KEYS = frozenset({
    "subj", "Subj", "obj", "poss", "poss_pron", "refl", "be", "have", "s", "noun",
})


class _SpyRng:
    """Delegating proxy that logs every draw, in order.

    Deliberately NOT a `random.Random` subclass: overriding `random()` on a
    subclass makes CPython swap `_randbelow` for the `random()`-based variant,
    so `choice()` starts logging its own internal draw and the log no longer
    describes the caller. Delegation keeps the log to what the module asked for.
    """

    def __init__(self, seed: int) -> None:
        self._r = random.Random(seed)
        self.log: list = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            value = getattr(self._r, name)(*args, **kwargs)
            self.log.append((name, value))
            return value

        return call


# --------------------------------------------------------------------------
# Back-compat: the v0.2.0 call forms
# --------------------------------------------------------------------------

@pytest.mark.parametrize("genre", GENRES)
def test_no_gender_argument_still_works(genre):
    """The two-argument call every existing caller uses. Hollow's
    hollow/sim/agents.py:285 is exactly this form."""
    concept = build_genre_concept(genre, rng=random.Random(11))
    assert set(concept) == CONCEPT_KEYS
    assert concept["gender"] in GENDERS


def test_no_rng_and_no_gender_still_works():
    """`rng=None` falls back to the module-global random. Still supported."""
    random.seed(0)
    assert set(build_genre_concept("drama")) == CONCEPT_KEYS
    assert set(build_blended_concept(["noir", "sexy"])) == CONCEPT_KEYS


def test_positional_rng_still_binds():
    """`gender` was APPENDED, so the old positional form still means `rng`."""
    a = build_genre_concept("drama", random.Random(3))
    b = build_genre_concept("drama", rng=random.Random(3))
    assert a == b


@pytest.mark.parametrize("genre", GENRES)
@pytest.mark.parametrize("gender", GENDERS)
def test_concept_keys_are_identical_for_every_gender(genre, gender):
    concept = build_genre_concept(genre, rng=random.Random(5), gender=gender)
    assert set(concept) == CONCEPT_KEYS
    assert concept["gender"] == gender


def test_blended_concept_keys_unchanged():
    concept = build_blended_concept(["horror", "romance"], rng=random.Random(7))
    assert set(concept) == CONCEPT_KEYS


@pytest.mark.parametrize("genre", GENRES)
def test_name_pool_still_reads_as_the_female_pool(genre):
    """`GenreSpec.name_pool` is the pre-0.3.0 attribute. Every reader of it --
    including the doc example in Hollow's design spec -- must keep getting the
    same list it got before, in the same order."""
    spec = GENRE_REGISTRY[genre]
    assert spec.name_pool == spec.name_pools["female"]
    assert spec.name_pool is not spec.name_pools["male"]


@pytest.mark.parametrize("genre", GENRES)
def test_gender_pools_are_parallel_and_distinct(genre):
    spec = GENRE_REGISTRY[genre]
    assert set(spec.name_pools) == set(GENDERS)
    sizes = {g: len(spec.name_pools[g]) for g in GENDERS}
    assert len(set(sizes.values())) == 1, f"pools differ in length: {sizes}"
    for g in GENDERS:
        pool = spec.name_pools[g]
        assert pool and all(n.strip() for n in pool)
        assert len(set(pool)) == len(pool), f"{genre}/{g} pool has duplicates"


def test_legacy_flat_name_pool_keyword_still_builds():
    """`GenreSpec(..., name_pool=[...])` was the only way to give a genre names
    at v0.2.0. It must still construct, and must still be readable back."""
    proto = GENRE_REGISTRY["drama"]
    spec = GenreSpec(
        key="x", display_label="X", theme_colors=["#000"],
        human_archetypes=proto.human_archetypes, ai_archetypes=proto.ai_archetypes,
        core_descriptors=proto.core_descriptors, core_values_pool=proto.core_values_pool,
        goal_pool=proto.goal_pool, interests_pool=proto.interests_pool,
        style_theme_pool=proto.style_theme_pool, relationship_style="s",
        voice_style="v", appearance_template="{age}-year-old {noun}",
        shadow_level="light", shadow=proto.shadow, tone_directive="t",
        name_pool=["Ada", "Bea"],
    )
    assert spec.name_pool == ["Ada", "Bea"]
    # A gender with no authored pool falls back to female rather than KeyError.
    assert spec.name_pools["male"] == ["Ada", "Bea"]
    assert spec.name_pools["nonbinary"] == ["Ada", "Bea"]


# --------------------------------------------------------------------------
# The behaviour change
# --------------------------------------------------------------------------

def test_default_gender_is_drawn_not_hardcoded_female():
    """THE BREAKING BEHAVIOUR CHANGE, asserted so it cannot be quietly undone.

    At v0.2.0 this set was exactly {"female"} for every genre and every seed.
    A caller that relied on that -- e.g. one that skipped storing the gender, or
    that wrote female-assuming prose around the concept -- is affected.
    """
    seen = {build_genre_concept("drama", rng=random.Random(s))["gender"]
            for s in range(200)}
    assert seen == set(GENDERS)


def test_explicit_gender_is_used_verbatim():
    for g in GENDERS:
        assert build_genre_concept("noir", rng=random.Random(2), gender=g)["gender"] == g


@pytest.mark.parametrize("builder,arg", [
    (build_genre_concept, "drama"),
    (build_blended_concept, ["drama", "noir"]),
])
def test_unknown_gender_raises_valueerror_naming_value_and_genders(builder, arg):
    with pytest.raises(ValueError) as exc:
        builder(arg, rng=random.Random(1), gender="femme")
    message = str(exc.value)
    assert "femme" in message
    assert all(g in message for g in GENDERS)


def test_pronoun_table_is_complete():
    assert set(PRONOUNS) == set(GENDERS)
    for g in GENDERS:
        assert set(PRONOUNS[g]) == PRONOUN_KEYS, f"{g} is missing pronoun keys"
    # The agreement forms are the point of the table: a naive she -> they swap
    # produces "They's rebuilding" without them.
    assert (PRONOUNS["nonbinary"]["be"], PRONOUNS["nonbinary"]["have"],
            PRONOUNS["nonbinary"]["s"]) == ("are", "have", "")


def test_render_rejects_an_unknown_gender():
    with pytest.raises(ValueError):
        render("{Subj} {be} here", "femme")


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _strings(value)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for value in obj:
            yield from _strings(value)


#: Words that give a persona away as the wrong gender. `they`/`them`/`their`
#: are deliberately absent -- they are also the ordinary plural, so policing them
#: would flag "anyone else have your attention" on a female persona.
GENDER_MARKERS = {
    "female": r"\b(she|her|hers|herself|woman|women|girl|daughter|mother|sister|wife|actress|hostess|waitress)\b",
    "male": r"\b(he|him|his|himself|man|men|boy|son|father|brother|husband|actor)\b",
}


@pytest.mark.parametrize("genre", GENRES)
@pytest.mark.parametrize("gender", GENDERS)
def test_no_cross_gender_word_survives_into_a_persona(genre, gender):
    """The end-to-end version of the whole change: generate a persona and look
    for a word that belongs to a different gender.

    Token coverage (the test above) proves the placeholders were filled; this
    proves the corpus had no *untokenised* gendered word left in it. It is the
    check that catches a pool the rewrite missed -- a `goal_pool` entry or a
    `shadow.struggles` line that is sampled straight into the concept.
    """
    import re

    offenders = []
    for seed in range(60):
        concept = build_genre_concept(genre, rng=random.Random(seed), gender=gender)
        for other, pattern in GENDER_MARKERS.items():
            if other == gender:
                continue
            for text in _strings(concept):
                found = re.search(pattern, text, re.I)
                if found:
                    offenders.append((seed, other, found.group(0), text[:100]))
    assert offenders == [], (
        f"{genre}/{gender}: {len(offenders)} cross-gender words, e.g. {offenders[:3]}"
    )


@pytest.mark.parametrize("gender", GENDERS)
def test_no_cross_gender_word_survives_a_blend(gender):
    """Blends merge pools from the other genres, and those merges are where a
    missed string reappears: the lead genre's prose goes through `render()`, the
    merged-in pools have to as well."""
    import re

    offenders = []
    for genres in (["horror", "romance"], ["noir", "sexy"], ["drama", "scifi", "adventure"]):
        for seed in range(40):
            concept = build_blended_concept(genres, rng=random.Random(seed), gender=gender)
            for other, pattern in GENDER_MARKERS.items():
                if other == gender:
                    continue
                for text in _strings(concept):
                    found = re.search(pattern, text, re.I)
                    if found:
                        offenders.append(("+".join(genres), seed, found.group(0), text[:100]))
    assert offenders == [], f"{gender}: {len(offenders)} cross-gender words, e.g. {offenders[:3]}"


@pytest.mark.parametrize("genre", GENRES)
def test_no_unfilled_token_leaks_into_a_concept(genre):
    """`render()` uses a format map whose `__missing__` leaves the token in
    place rather than raising -- convenient, but it means a typo'd token ships
    as literal "{Subj}" instead of blowing up. This is the net that catches it."""
    leaks = [
        (seed, text)
        for seed in range(120)
        for text in _strings(build_genre_concept(genre, rng=random.Random(seed)))
        if "{" in text or "}" in text
    ]
    assert leaks == [], f"{genre}: unfilled tokens in {len(leaks)} strings: {leaks[:3]}"


# --------------------------------------------------------------------------
# Determinism and draw order
# --------------------------------------------------------------------------

@pytest.mark.parametrize("builder,arg", [
    (build_genre_concept, "drama"),
    (build_genre_concept, "horror"),          # the override builder
    (build_blended_concept, ["horror", "romance"]),
])
def test_gender_is_the_first_draw(builder, arg):
    spy = _SpyRng(1)
    builder(arg, rng=spy)
    assert spy.log, "no draws were taken at all"
    kind, value = spy.log[0]
    assert kind == "choice" and value in GENDERS, f"first draw was {kind}({value!r})"


def test_explicit_gender_costs_exactly_one_fewer_draw():
    """Burning one `choice(GENDERS)` up front must reproduce the default call's
    draw log exactly -- which proves the gender costs one draw and no more, and
    that an explicit gender takes none."""
    default = _SpyRng(1)
    build_genre_concept("drama", rng=default)
    drawn = default.log[0][1]

    explicit = _SpyRng(1)
    explicit.choice(GENDERS)
    build_genre_concept("drama", rng=explicit, gender=drawn)

    assert default.log == explicit.log


def test_same_seed_same_persona_in_process():
    assert (build_genre_concept("drama", rng=random.Random(1))
            == build_genre_concept("drama", rng=random.Random(1)))


_REPLAY = """
import hashlib, json, random
from aura_life.personas.genre_randomizer import build_genre_concept, build_blended_concept
payload = {
    "drama": build_genre_concept("drama", rng=random.Random(1)),
    "horror": build_genre_concept("horror", rng=random.Random(4242)),
    "blend": build_blended_concept(["horror", "romance"], rng=random.Random(7)),
}
print(hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
"""


def _replay(hash_seed: str) -> str:
    import os
    env = dict(os.environ, PYTHONHASHSEED=hash_seed)
    result = subprocess.run([sys.executable, "-c", _REPLAY], capture_output=True,
                            text=True, env=env,
                            cwd=str(pathlib.Path(__file__).resolve().parents[1]))
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_same_seed_same_persona_across_processes():
    """Two fresh interpreters, different PYTHONHASHSEED, identical bytes.

    In-process equality is not enough: dict/set iteration order is the classic
    way a "deterministic" generator turns out to depend on the process.
    """
    first, second = _replay("0"), _replay("12345")
    assert first == second, "same seed produced a different persona in another process"
