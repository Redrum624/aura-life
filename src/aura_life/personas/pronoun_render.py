"""Pronoun and user-reference rendering for prompt-bound / user-visible text.

Reuses :mod:`genre_randomizer`'s ``PRONOUNS`` table (the tested, single source
of truth for persona pronoun forms) instead of forking a second copy. Adds what
the life sim needs on top of it:

* :func:`resolve_gender` -- a LENIENT normalizer. ``genre_randomizer.render``
  raises on an unknown gender (right for a generator that always draws one or
  is told one); a persona already living in the sim may simply have none on
  record (no profile, or a profile that never set one). The humanness
  program's ruling: render those lines as they/them, never raise and never
  default to a specific gender.
* ``was``/``Was`` tokens -- ``genre_randomizer.PRONOUNS`` only carries
  present-tense ``be`` ("is"/"are"); several narrative pools here are past
  tense ("what she was thinking"), where the only irregular form across
  she/he/they is "was"/"were".
* User-reference tokens -- the other person is never hardcoded "the user" or
  assumed male. ``user_info`` (``LifeService``'s constructor arg) carries an
  optional "name"; present, it fills ``{user}``/``{User}``/``{user_poss}``;
  absent, those slots take the exact they/them/their forms
  ``PRONOUNS["nonbinary"]`` already uses for a gender-unknown persona -- the
  same "don't invent a gender/identity" rule, applied to the user.
* :func:`render_line` -- one call that fills a persona's pronoun tokens AND the
  user's reference tokens (plus any caller-supplied ``extra``), leaving any
  other ``{token}`` untouched (same permissive ``format_map`` contract as
  ``genre_randomizer.render``, so a typo'd token ships visibly instead of
  raising).
* :func:`render_second_person` -- the same template addressed to the persona
  ("you", "your"): what her memory stream keeps (Task 12), and quotes back to
  her.
* :func:`format_lenient` -- fills only the given fields (e.g. an NPC's name and
  a topic) and leaves pronoun/user tokens in a template untouched, so an
  engine that formats its own template fields (``{name}``, ``{topic}``, ...)
  before returning the text does not raise on the tokens this module renders
  later, downstream, in `LifeService`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .genre_randomizer import GENDERS, PRONOUNS, _Tokens

#: What a caller may pass for "the other person": a ``user_info``-shaped dict
#: (``{"name": ...}``, ``LifeService``'s own shape), a plain name string, or
#: ``None``/absent.
UserRef = Optional[Union[str, Dict[str, Any]]]


#: The words a profile or a host writes for a gender beside the three of
#: `GENDERS`. A profile says ``Gender: woman``: the persona wizard of aura (the
#: first host) writes that word by default and reads exactly these words as
#: she/her and he/him, and the profiles shipped with aura and aura-personality
#: carry it. Without this table every such persona read as they/them.
GENDER_WORDS: Dict[str, str] = {
    "woman": "female", "girl": "female", "f": "female",
    "man": "male", "boy": "male", "m": "male",
}


def resolve_gender(raw: Optional[str]) -> str:
    """Normalize `raw` to one of `GENDERS`, through `GENDER_WORDS` for the
    words a profile writes ("woman", "man", ...). `None`, `""`, or anything
    unrecognized -> "nonbinary" (they/them) -- the fallback for a persona whose
    gender is not on record, never a guessed specific gender."""
    g = (raw or "").strip().lower()
    g = GENDER_WORDS.get(g, g)
    return g if g in GENDERS else "nonbinary"


def _user_name(user: UserRef) -> str:
    name = user.get("name") if isinstance(user, dict) else user
    return (name or "").strip()


def user_tokens(user: UserRef) -> Dict[str, str]:
    """Token map for referring to the OTHER person (never "the user").

    A real name fills every slot verbatim -- names don't conjugate, so the
    same string is correct in subject, object and (with an appended "'s")
    possessive position. With no name, the slots take
    `PRONOUNS["nonbinary"]`'s they/them/their forms verbatim: the correct
    grammatical fallback for a person whose name is not on record.
    """
    name = _user_name(user)
    if name:
        return {
            "user": name, "User": name,
            "user_poss": f"{name}'s", "user_Poss": f"{name}'s",
        }
    nb = PRONOUNS["nonbinary"]
    return {
        "user": nb["obj"], "User": nb["Subj"],
        "user_poss": nb["poss"], "user_Poss": nb["poss"].capitalize(),
    }


#: Lowercase pronoun-token keys that also get a capitalized variant (``Obj``,
#: ``Poss``, ...) derived automatically -- `genre_randomizer.PRONOUNS` only
#: bothers to carry the capitalized form it itself needs (``Subj``), but a
#: sentence in these narrative pools just as often opens on the possessive
#: ("Her pen ran out...") or the object ("Him? Never mind.") as the subject.
_CAPITALIZABLE = ("obj", "poss", "poss_pron", "refl", "noun")


def render_line(text: str, *, gender: Optional[str] = None, user: UserRef = None,
                 **extra: Any) -> str:
    """Fill a template's persona-pronoun tokens (``{subj}``/``{Subj}``,
    ``{obj}``/``{Obj}``, ``{poss}``/``{Poss}``, ``{poss_pron}``/``{Poss_pron}``,
    ``{refl}``/``{Refl}``, ``{be}``, ``{have}``, ``{was}``/``{Was}``, ``{s}``,
    ``{noun}``/``{Noun}`` -- from `gender`, via `resolve_gender`) and
    user-reference tokens (``{user}``, ``{User}``, ``{user_poss}``,
    ``{user_Poss}`` -- from `user`, via `user_tokens`), plus any `extra` fields
    (e.g. a dream's sampled ingredients). Any other ``{token}`` in `text`
    passes through unfilled, exactly as `genre_randomizer.render` does.
    """
    resolved = resolve_gender(gender)
    tokens = _Tokens(dict(PRONOUNS[resolved]))
    for key in _CAPITALIZABLE:
        value = tokens[key]
        cap_key = key[0].upper() + key[1:]
        tokens[cap_key] = value[0].upper() + value[1:] if value else value
    was = "were" if resolved == "nonbinary" else "was"
    tokens["was"] = was
    tokens["Was"] = was.capitalize()
    tokens.update(user_tokens(user))
    tokens.update(extra)
    return text.format_map(tokens)


#: The persona addressed as "you" (humanness Task 12): an episode of her memory
#: stream (:mod:`aura_life.memory`) keeps the words of what happened addressed
#: to her, because what she remembers is quoted back to her in the second
#: person (the moment, spec section 4.10). "You" agrees with a verb as "they"
#: does -- you are, you have, you were, no verb "s" -- and takes "person" for
#: the noun, as a persona of unknown gender does (``PRONOUNS["nonbinary"]``).
SECOND_PERSON: Dict[str, str] = {
    "subj": "you", "Subj": "You", "obj": "you", "Obj": "You",
    "poss": "your", "Poss": "Your", "poss_pron": "yours", "Poss_pron": "Yours",
    "refl": "yourself", "Refl": "Yourself",
    "be": "are", "have": "have", "s": "", "was": "were", "Was": "Were",
    "noun": "person", "Noun": "Person",
}


def render_second_person(text: str, *, user: UserRef = None, **extra: Any) -> str:
    """Fill a template's persona-pronoun tokens as :data:`SECOND_PERSON` --
    the persona addressed as "you" -- and its user-reference tokens (from
    `user`, via `user_tokens`), plus any `extra` fields. Any other
    ``{token}`` passes through unfilled, as in :func:`render_line`."""
    tokens = _Tokens(SECOND_PERSON)
    tokens.update(user_tokens(user))
    tokens.update(extra)
    return text.format_map(tokens)


def format_lenient(text: str, **fields: Any) -> str:
    """Fill only `fields` in `text`; any other ``{token}`` (a pronoun or user
    token this module's own :func:`render_line` fills later) passes through
    unfilled instead of raising ``KeyError``, unlike plain ``str.format``."""
    return text.format_map(_Tokens(fields))
