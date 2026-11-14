"""Episodes: what she lived, as she keeps it (humanness program Task 12, spec
section 4.6).

An :class:`Episode` is one thing that happened to her: when (``at``, on the
world clock), where (``place``, her location key), with whom (``people``),
what happened (``what``: a short phrase -- an activity as she would name it,
"a call from Mara", or a line of her setting addressed to her, "You spilled
coffee on your shirt"), what she felt (``emotion``: the strongest name, or an
appraisal's), the valence of her mood when she lived it (``valence``, -1..1),
how much it mattered (``importance``, 0.1..1), how firmly it is held
(``strength``), when she last recalled it (``last_recalled``) and what it is
(``tags``: its kind -- "activity", "social", "chaos", "moment", "work",
"goal", "milestone", "book" -- plus the kind's details and the share ids,
"share:<n>" / "event:<n>", of the shareable and life event it came with).
Episodes are immutable: recall gives a new one (:meth:`Episode.recalled`).

Every number, and where it comes from
=====================================

Recency (spec 4.6)::

    recency = RECENCY_PER_HOUR ** (hours since she last recalled it, or since it happened)

Strength (spec 4.6): ``strength`` is S, in days. Retention decays as
``exp(-t / S)``, t the days since she last recalled it (or since it
happened); recalling it adds RECALL_STRENGTH_GAIN to S and starts t again,
so a recalled episode fades more slowly afterwards. Unprompted recall weighs
each episode's score by its retention (ruling T12-R1; ``MemoryStream``); a
query-cued recall does not (ruling T12-R5).

Importance, 0..1 (the brief: from emotion intensity, novelty and the people
involved)::

    importance = IMPORTANCE_FLOOR + (1 - IMPORTANCE_FLOOR)
                 * (EMOTION_WEIGHT * felt + NOVELTY_WEIGHT * novel + PEOPLE_WEIGHT * with_people)

    felt         the event's strongest emotion intensity, 0..1
                 (:func:`emotion_intensity`), or an appraisal's intensity
    novel        1 when the activity, the place or one of the people is one
                 she has not met in NOVELTY_WINDOW_DAYS -- counted only once
                 her memory spans that window (MemoryStream)
    with_people  1 when anyone was there

====================  =====  ==============================================
Value                 Is     From
====================  =====  ==============================================
RECENCY_PER_HOUR      0.995  spec 4.6 (Generative Agents' recency decay)
RECALL_STRENGTH_GAIN  1      spec 4.6 ("recall adds 1 to S")
INITIAL_STRENGTH      1 day  chosen: the unit recall adds, so her first
                             recall of an episode doubles it
IMPORTANCE_FLOOR      0.1    spec 4.6 maps Generative Agents' 1-10 scale
                             onto this one (their 150 is 15.0); their
                             lowest, 1 -- "purely mundane" -- is 0.1
EMOTION_WEIGHT        0.6    chosen (Task 12 report: measured over three
NOVELTY_WEIGHT        0.2    simulated production-cadence days); the three
PEOPLE_WEIGHT         0.2    add up to 1, so importance spans 0.1..1
NOVELTY_WINDOW_DAYS   7      chosen: a week, the span her schedules repeat
                             over (``aura_life.schedule``'s weekly
                             schedules, the career's weekly shifts)
====================  =====  ==============================================

The gist
========

:meth:`Episode.gist` is one plain sentence -- what happened, where, with
whom, what she felt -- quoted back to her in the second person (the moment,
spec 4.10; nostalgia) and never a transcript: "Cooking a meal at home with
Roberta, feeling warm." It has no digit (numbers are spelled out), no
snake_case, no brace, and only the first sentence of ``what``.
"""

import math
import re
import statistics
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Dict, Iterable, Mapping, Optional, Tuple

from ..social.household import name_list

# ============= Every number of an episode (the table above) =============

#: Recency's decay per hour since she last recalled an episode (spec 4.6).
RECENCY_PER_HOUR = 0.995
#: S, in days, of an episode never recalled (chosen: the unit recall adds).
INITIAL_STRENGTH = 1.0
#: What each recall adds to S (spec 4.6).
RECALL_STRENGTH_GAIN = 1.0
#: The importance of the purely mundane: Generative Agents' 1 of 10 on the
#: spec's 0..1 mapping of their scale.
IMPORTANCE_FLOOR = 0.1
#: How much each part of an event counts toward its importance (chosen; they
#: add up to 1, see the table above).
EMOTION_WEIGHT = 0.6
NOVELTY_WEIGHT = 0.2
PEOPLE_WEIGHT = 0.2
#: An activity, place or person she has not met in this many days is new to
#: her (chosen).
NOVELTY_WINDOW_DAYS = 7.0


def hours_between(earlier: datetime, later: datetime) -> float:
    """World hours from ``earlier`` to ``later``, never negative. Tolerates a
    naive and an aware instant together (a host that changed clocks between
    runs) by comparing them as naive."""
    if (earlier.tzinfo is None) != (later.tzinfo is None):
        earlier, later = earlier.replace(tzinfo=None), later.replace(tzinfo=None)
    return max(0.0, (later - earlier).total_seconds() / 3600.0)


def emotion_intensity(emotions: Mapping[str, float]) -> float:
    """How strongly an event was felt, 0..1: its strongest emotion's
    intensity. Not their sum: the library's tables give a routine activity
    three mild feelings to blend into mood ("reading": 0.1, 0.15, 0.2), which
    summed would outweigh a friend's call or a goal reached (Task 12 report,
    measured)."""
    return min(1.0, max((abs(float(intensity)) for intensity in (emotions or {}).values()), default=0.0))


def dominant_emotion(emotions: Mapping[str, float]) -> str:
    """The emotion felt most strongly (the first of equals), or ``""`` when
    nothing was felt."""
    felt = [(name, abs(float(intensity))) for name, intensity in (emotions or {}).items() if intensity]
    if not felt:
        return ""
    return max(felt, key=lambda pair: pair[1])[0]


def mean_valence(episodes: Iterable["Episode"]) -> float:
    """The mean of ``episodes``' valence, or 0.0 (neutral) for an empty
    collection -- her felt tone over a stretch of her life (Task 13, spec
    4.6: a chapter's mood, a reflection's mood-trend belief), read from what
    she actually lived instead of her mood at any one instant."""
    values = [e.valence for e in episodes]
    return statistics.mean(values) if values else 0.0


def importance_of(intensity: float, novel: bool, people: int) -> float:
    """An event's importance, 0.1..1 (the formula in this module's docstring):
    how strongly it was felt (0..1), whether it was new to her, and how many
    people were there."""
    felt = min(1.0, max(0.0, float(intensity)))
    parts = (EMOTION_WEIGHT * felt
             + NOVELTY_WEIGHT * (1.0 if novel else 0.0)
             + PEOPLE_WEIGHT * (1.0 if people > 0 else 0.0))
    return round(IMPORTANCE_FLOOR + (1.0 - IMPORTANCE_FLOOR) * parts, 6)


# ============= The gist's words =============

#: A place her gist names by a phrase of its own; any other reads "at the
#: <place>" (its underscores as spaces; a place called "the ..." keeps its
#: own "the").
PLACE_PHRASES: Dict[str, str] = {
    "home": "at home",
    "workplace": "at work",
    "street": "out on the street",
    "in transit": "on the way",
}

#: What one of her people did, by ``SocialEvent.event_type``, as her memory
#: keeps it -- never the event's own line, which is written about her in the
#: third person. A type not listed is DEFAULT_CONTACT_PHRASE.
CONTACT_PHRASES: Dict[str, str] = {
    "text_received": "a text from {name}",
    "call": "a call from {name}",
    "hangout": "time with {name}",
    "invitation": "an invitation from {name}",
    "mentioned": "thinking of {name}",
}
DEFAULT_CONTACT_PHRASE = "news of {name}"


def contact_phrase(event_type: str, name: str) -> str:
    """What one of her people did, as her memory keeps it: "a call from Mara"."""
    return CONTACT_PHRASES.get(event_type, DEFAULT_CONTACT_PHRASE).format(name=name)


#: What a user's turn was to her, as her memory keeps it (humanness Task 16b
#: step 0, ruling T16a-R2), by kind: never the user's words. Addressed to
#: her, the ``{User}`` slot filled by ``LifeService._addressed_to_her``; no
#: verb after the slot that would have to agree with a name or "they".
#: ``LifeService.observe_user_turn`` picks the kind: hostility aimed at her,
#: then a disclosure, then warmth aimed at her, then what she felt
#: (concerned, amused, warm), then "talk" for a turn with topics only.
CONVERSATION_PHRASES: Dict[str, str] = {
    "hostile": "{User} lashed out at you",
    "disclosure": "{User} opened up to you",
    "sweet": "{User} said something sweet to you",
    "concerned": "{User} told you about a hard time",
    "amused": "{User} made you laugh",
    "warm": "{User} told you something good",
    "talk": "{User} talked with you",
}


def conversation_phrase(kind: str, topics: Iterable[str] = (), *, render=None) -> str:
    """A user's turn as her memory keeps it: :data:`CONVERSATION_PHRASES`'
    line for ``kind`` (``render`` fills its ``{User}`` slot) and what it was
    about, the host's ``topics`` cleaned as a gist is (numbers in words, no
    snake_case or brace) -- "They talked with you about the weekend",
    "Sam opened up to you, talking about work and money"."""
    line = CONVERSATION_PHRASES.get(kind, CONVERSATION_PHRASES["talk"])
    line = render(line) if render is not None else line
    about = []
    for topic in topics or ():
        word = _plain(topic)
        if word and word not in about:
            about.append(word)
    if not about:
        return line
    joiner = " about " if kind == "talk" else ", talking about "
    return f"{line}{joiner}{name_list(about)}"


def place_phrase(place: str) -> str:
    """Where it happened, as a gist says it: "at home", "at the cafe", "on
    the way"; ``""`` for nowhere in particular."""
    key = " ".join(str(place or "").split())
    if not key:
        return ""
    known = PLACE_PHRASES.get(key.lower())
    if known:
        return known
    words = " ".join(key.replace("_", " ").split())
    return f"at {words}" if words.lower().startswith("the ") else f"at the {words}"


_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+")


def _number_words(n: int) -> str:
    """``n`` in words: "twelve", "seventy-seven", "two thousand seventy-seven";
    a million or more digit by digit."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{_ONES[n // 100]} hundred" + (f" {_number_words(n % 100)}" if n % 100 else "")
    if n < 1_000_000:
        return f"{_number_words(n // 1000)} thousand" + (f" {_number_words(n % 1000)}" if n % 1000 else "")
    return " ".join(_ONES[int(digit)] for digit in str(n))


def _spelled(text: str) -> str:
    """``text`` with every number in words ("5" -> "five", "3.5" -> "three
    point five", "4b" -> "four b")."""
    def spoken(match: "re.Match") -> str:
        whole, _, fraction = match.group(0).partition(".")
        words = _number_words(int(whole))
        if fraction:
            words += " point " + " ".join(_ONES[int(digit)] for digit in fraction)
        start, end = match.span()
        before = match.string[start - 1] if start > 0 else ""
        after = match.string[end] if end < len(match.string) else ""
        return f"{' ' if before.isalnum() else ''}{words}{' ' if after.isalnum() else ''}"
    return _NUMBER_RE.sub(spoken, text)


def _plain(text: str) -> str:
    """``text`` as a gist says it: its first sentence, numbers in words, no
    underscore or brace, single spaces, no closing stop."""
    first = _SENTENCE_BREAK_RE.split(" ".join(str(text or "").split()), maxsplit=1)[0]
    first = first.replace("_", " ").replace("{", "").replace("}", "")
    return " ".join(_spelled(first).split()).rstrip(" .!?,;:")


def _feeling(emotion: str) -> str:
    """An emotion name as a gist says it ("let_down" -> "let down"); nothing
    for none, or for neutral."""
    word = _plain(emotion).lower()
    return "" if word in ("", "neutral") else word


def _named_in(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(name.lower())}\b", text.lower()) is not None


@dataclass(frozen=True)
class Episode:
    """One thing that happened to her (spec 4.6; the fields are described in
    this module's docstring). Built by :class:`~aura_life.memory.MemoryStream`,
    which gives it its id and importance."""

    id: int
    at: datetime
    place: str = ""
    people: Tuple[str, ...] = ()
    what: str = ""
    emotion: str = ""
    valence: float = 0.0
    importance: float = IMPORTANCE_FLOOR
    strength: float = INITIAL_STRENGTH
    last_recalled: Optional[datetime] = None
    tags: Tuple[str, ...] = ()

    def _since(self) -> datetime:
        """The instant its recency and retention count from: her last recall
        of it, else when it happened."""
        return self.last_recalled or self.at

    def recency(self, now: datetime) -> float:
        """RECENCY_PER_HOUR per world hour since she last recalled it (or
        since it happened): 1.0 now, 0.887 a day on, 0.43 a week on."""
        return RECENCY_PER_HOUR ** hours_between(self._since(), now)

    def retention(self, now: datetime) -> float:
        """How much of it she still holds, 0..1: ``exp(-t / S)``, t the days
        since she last recalled it (or since it happened), S its strength."""
        strength = self.strength if self.strength > 0 else INITIAL_STRENGTH
        return math.exp(-hours_between(self._since(), now) / 24.0 / strength)

    def recalled(self, now: datetime) -> "Episode":
        """This episode recalled at ``now``: its strength RECALL_STRENGTH_GAIN
        higher, its recency and retention counting from ``now``."""
        return replace(self, strength=self.strength + RECALL_STRENGTH_GAIN, last_recalled=now)

    def gist(self) -> str:
        """One plain sentence: what happened, where, with whom, and what she
        felt -- "Cooking a meal at home with Roberta, feeling warm." Someone
        ``what`` already names is not named again; no digit, no snake_case."""
        what = _plain(self.what) or "a moment"
        sentence = what[:1].upper() + what[1:]
        where = _plain(place_phrase(self.place))
        if where:
            sentence += f" {where}"
        others = [person for person in (_plain(p) for p in self.people) if person and not _named_in(person, what)]
        if others:
            sentence += f" with {name_list(others)}"
        feeling = _feeling(self.emotion)
        if feeling:
            sentence += f", feeling {feeling}"
        return sentence + "."
