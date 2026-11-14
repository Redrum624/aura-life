"""Reflection: what she concludes about her own recent history (humanness
program Task 13, spec section 4.6).

Measured before this task: nothing reflected on the memory stream Task 12
gave her -- it was recorded and, at best, recalled verbatim. Generative
Agents found reflection load-bearing on its own: removing it dropped their
believability score from 29.89 to 26.88 (the analysis this program answers).

Fires when the importance of what she has lived since her last reflection
sums to REFLECTION_THRESHOLD or more -- spec 4.6, the same 1-10-onto-0.1..1
mapping :data:`aura_life.memory.episodes.IMPORTANCE_FLOOR`'s docstring
gives (Generative Agents' 150 is this library's 15.0). :func:`generate_beliefs`
is the deterministic half of it: no draw, no LLM, just what a window of her
own episodes (:class:`~aura_life.memory.store.MemoryStream`) adds up to --
three patterns (the brief's own words): a repeated activity with a person, a
recurring place, a mood trend. Each belief :class:`~aura_life.life_service.LifeService`
remembers from it is an episode of her own, tagged ``"belief"``: it takes its
place in the stream like anything else she has lived -- recalled, decayed,
reinforced, and counted toward the *next* reflection once it ages out of the
current window.

Every belief sentence is written the way an episode's gist already is
(:mod:`aura_life.memory.episodes`): addressed to her as "you" with the
grammar hardcoded, never a ``{subj}``/``{poss}`` pronoun token, so there is
nothing for :func:`aura_life.personas.pronoun_render.render_line` to get
wrong (Task 6's render lint covers this module's templates the same way it
covers :data:`~aura_life.energy.energy_system.ENERGY_DESCRIPTIONS`: a
second-person pool with no pronoun token to begin with -- see
``tests/test_reflection.py``). A person is always named, never given a
pronoun -- the library's existing convention for anyone but the persona
herself (:func:`aura_life.memory.episodes.contact_phrase`).

Fix round 1 (review): a belief's TEXT can reword the same conclusion
forever -- "You've been at the cafe most days this week." every time she
is, in fact, mostly at the cafe -- so each belief carries a PATTERN key
(:data:`BeliefKey`: ``(kind, discriminator)``, never the sentence) encoded
into a tag on its episode (:func:`belief_key_tag`); the caller
(``LifeService._reflect``) skips a key already believed within
:data:`BELIEF_REPEAT_COOLDOWN_DAYS`, reading it straight back off the
stream's own tags rather than a side table. An optional LLM belief is
free-text, not a fixed pattern, so it is validated instead
(:func:`validate_llm_belief`) rather than keyed.
"""

import re
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from .episodes import Episode, mean_valence, place_phrase

#: Spec 4.6 / the Task 13 brief, verbatim: a reflection fires when the
#: summed importance of what happened since the last one reaches this.
REFLECTION_THRESHOLD = 15.0

#: An (activity, person) pair, or a place, counted at least this many times
#: in the reflection window reads as a pattern worth a belief, not a
#: coincidence (chosen: DEFERRED.md/the task report carry it as a deviation
#: -- the brief gives the 15.0 threshold but not this one).
MIN_REPEAT_COUNT = 3

#: Fewer episodes than this in the window is too little to call a mood a
#: trend rather than a blip (chosen, see MIN_REPEAT_COUNT).
MIN_MOOD_SAMPLE = 5

#: How strongly forming a belief is felt -- fed to ``LifeService._remember``'s
#: ``intensity`` for a belief episode: a moderate realization, not a peak
#: feeling (chosen, see MIN_REPEAT_COUNT).
BELIEF_INTENSITY = 0.3

#: At most this many beliefs recorded from one reflection (chosen: a cap in
#: the same spirit as every other capped list in this library --
#: MemoryStream.episodes' own cap, the nostalgia log's 20, the life
#: chapters' 12 -- so one very eventful window cannot flood the stream).
MAX_BELIEFS_PER_REFLECTION = 3

#: A belief's pattern -- ``(kind, discriminator)`` -- never its sentence
#: text: two beliefs with different wording but the same key are the same
#: conclusion, and two with the same words but a different key (a mood
#: trend's "up" vs "down") are not.
BeliefKey = Tuple[str, str]

#: A pattern key already believed within this many simulated days is not
#: believed again -- a reflection that finds nothing new records nothing
#: (fix round 1, Important 1; the review's own value, verbatim).
BELIEF_REPEAT_COOLDOWN_DAYS = 7.0

#: The tag prefix a belief episode's pattern key is encoded into
#: (:func:`belief_key_tag` / :func:`belief_key_from_tag`), so a later
#: reflection can read "this was already believed" straight off the stream
#: instead of a side table.
BELIEF_KEY_TAG_PREFIX = "belief_key:"

#: The one sentence an optional LLM belief may run to (fix round 1,
#: Important 2). Chosen: no existing gist/prompt-text character cap exists
#: to reuse -- Episode.gist() bounds itself to one sentence, never a
#: character count -- so this is roughly 2x a typical hand-written belief
#: sentence here: generous for one real sentence, tight enough to reject a
#: multi-sentence ramble.
LLM_BELIEF_MAX_CHARS = 200

_BARE_PRONOUN_RE = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.IGNORECASE)
_THE_USER_RE = re.compile(r"\bthe user\b", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")
_MID_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s")


def belief_key_tag(key: BeliefKey) -> str:
    """``key`` as a tag on the belief episode it grounds."""
    kind, discriminator = key
    return f"{BELIEF_KEY_TAG_PREFIX}{kind}:{discriminator}"


def belief_key_from_tag(tag: str) -> Optional[BeliefKey]:
    """The reverse of :func:`belief_key_tag`, or ``None`` for a tag that is
    not one (every other tag an episode carries)."""
    if not tag.startswith(BELIEF_KEY_TAG_PREFIX):
        return None
    kind, _, discriminator = tag[len(BELIEF_KEY_TAG_PREFIX):].partition(":")
    return (kind, discriminator)


def validate_llm_belief(raw) -> Optional[str]:
    """``raw`` (the host LLM's reply), whitespace-normalised, if it is fit
    to remember as a belief -- or ``None`` when it fails any check, so the
    caller records nothing from it and the deterministic beliefs stand
    (fix round 1, Important 2): non-empty, at most LLM_BELIEF_MAX_CHARS, no
    digit, no unfilled ``{``/``}``, no bare she/he/him/her/his/hers/
    herself/himself (this is a line addressed to her as "you", never about
    her in the third person), never "the user", and one sentence -- no
    ``.``/``!``/``?`` followed by more text."""
    text = " ".join(str(raw or "").split())
    if not text or len(text) > LLM_BELIEF_MAX_CHARS:
        return None
    if _DIGIT_RE.search(text):
        return None
    if "{" in text or "}" in text:
        return None
    if _BARE_PRONOUN_RE.search(text):
        return None
    if _THE_USER_RE.search(text):
        return None
    if _MID_SENTENCE_BREAK_RE.search(text):
        return None
    return text


def repeated_activity_partners(
    episodes: Sequence[Episode], *, min_count: int = MIN_REPEAT_COUNT
) -> List[Tuple[Tuple[str, str], List[Episode]]]:
    """(activity, person) pairs -- tag ``"activity"``, someone there -- done
    together at least ``min_count`` times in ``episodes``, most frequent
    first, each with the episodes that make up its count (to reinforce,
    ruling T12-R2: reflection that surfaces an episode reinforces it)."""
    groups: Dict[Tuple[str, str], List[Episode]] = defaultdict(list)
    for episode in episodes:
        if "activity" not in episode.tags or not episode.people:
            continue
        for person in episode.people:
            groups[(episode.what, person)].append(episode)
    return sorted(
        (item for item in groups.items() if len(item[1]) >= min_count),
        key=lambda item: (-len(item[1]), item[0]),
    )


def recurring_places(
    episodes: Sequence[Episode], *, min_count: int = MIN_REPEAT_COUNT
) -> List[Tuple[str, List[Episode]]]:
    """Places named on at least ``min_count`` episodes, most frequent first,
    each with its episodes (to reinforce)."""
    groups: Dict[str, List[Episode]] = defaultdict(list)
    for episode in episodes:
        if episode.place:
            groups[episode.place].append(episode)
    return sorted(
        (item for item in groups.items() if len(item[1]) >= min_count),
        key=lambda item: (-len(item[1]), item[0]),
    )


def mood_trend(episodes: Sequence[Episode], *, band: float, min_count: int = MIN_MOOD_SAMPLE) -> Optional[str]:
    """``"up"``, ``"down"`` or ``None``: whether ``episodes``' mean valence
    sits clearly one side of neutral, beyond ``band`` either way (the mood
    model's own pleasant/unpleasant cutoff --
    ``aura_life.affect.affect_system.MOOD_VALENCE_BAND``, so a "trend" agrees
    with what the persona's own mood grid would call pleasant or unpleasant).
    ``None`` with fewer than ``min_count`` episodes: too little to call it a
    trend rather than a blip."""
    if len(episodes) < min_count:
        return None
    mean = mean_valence(episodes)
    if mean >= band:
        return "up"
    if mean <= -band:
        return "down"
    return None


def generate_beliefs(
    episodes: Sequence[Episode], *, mood_band: float, min_repeat: int = MIN_REPEAT_COUNT,
    min_mood_sample: int = MIN_MOOD_SAMPLE, limit: int = MAX_BELIEFS_PER_REFLECTION,
) -> List[Tuple[BeliefKey, str, List[Episode]]]:
    """Deterministic beliefs from ``episodes`` (the reflection window,
    spec 4.6): a repeated activity with a person, a recurring place, a mood
    trend -- the brief's three patterns -- each returned as
    ``(pattern key, belief text, the episodes that ground it)``,
    most-grounded pattern first, at most ``limit``. The key
    (:data:`BeliefKey`) is what the caller dedups on (fix round 1,
    Important 1) -- never the text, which can reword the same conclusion.
    A mood trend grounds nothing concrete (it is a synthesis over the whole
    window, not a recollection of any one episode), so its list is empty --
    nothing for the caller to reinforce there.

    Falls back to her single most important episode, quoted, when no
    pattern meets its count: a reflection that fires (the threshold is
    already met) always leaves at least one belief behind, so the window it
    closes never reopens for lack of anything to conclude -- unless the
    caller's own dedup then finds even that one already believed, in which
    case, per the brief, it records nothing."""
    beliefs: List[Tuple[BeliefKey, str, List[Episode]]] = []
    for (activity, name), grounds in repeated_activity_partners(episodes, min_count=min_repeat):
        key = ("activity_partner", f"{activity}:{name}")
        beliefs.append((key, f"You've been {activity} with {name} a lot lately.", grounds))
    for place, grounds in recurring_places(episodes, min_count=min_repeat):
        key = ("place", place)
        beliefs.append((key, f"You've been {place_phrase(place)} most days this week.", grounds))
    trend = mood_trend(episodes, band=mood_band, min_count=min_mood_sample)
    if trend == "down":
        beliefs.append((("mood_trend", "down"), "You've been feeling low most of this week.", []))
    elif trend == "up":
        beliefs.append((("mood_trend", "up"), "You've been feeling good most of this week.", []))
    if not beliefs and episodes:
        top = max(episodes, key=lambda e: (e.importance, e.at))
        beliefs.append((("fallback", str(top.id)), f"You keep coming back to this: {top.gist()}", [top]))
    return beliefs[:limit]
